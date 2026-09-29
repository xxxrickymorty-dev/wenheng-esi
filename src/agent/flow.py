# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 固定编排（WH-DOC-03 §6；WH-DOC-04 §3.8）。

**主干步骤与顺序硬编码在本文件**——模型不得增删步骤、不得改顺序
（HLD §2 N2 / 架构设计 §0）。

失败处置语义（2026-09-15 裁决，仲裁 HLD §6.1 / 架构设计 §4.2·§4.7 / 决策方案 §3 三说）
--------------------------------------------------------------------------------
    首轮拦停 → 一次自愈重试 → 再败即升级

    1. 任一步失败，**立即停止**，不进入后续步骤（不"未过仍出稿"）；
    2. 给该步**一次**自愈机会：按失败码匹配规则 → 重跑该步一次；
    3. 重试仍失败 → 状态置 `escalated`，产出《诊断报告》，交人工。

    该裁决同时取消了两处旧描述：架构设计 §4.7 的 `Warned = 断言未过仍出稿`
    （本实现中 Warned 只表示"跑完了但有非阻断告警"），以及决策方案 §3 的
    "全绿才放行"（本实现允许一次自愈后再判定）。

用法：
    python -m agent.flow input/202609/监测表.xlsx
    python -m agent.flow input/202609/监测表.xlsx --run-dir out/_jobs/manual
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

from . import states, tools
from .trace import Trace

#: 主干步骤表（唯一事实源）。`server/config.py` 的 STEPS 应与之一致，
#: 由 tests/test_agent_flow.py 断言防漂移。
STEPS: tuple[dict, ...] = (
    {"id": "parse", "label": "解析台账",
     "desc": "22 个工作表归一化 + 机器断言", "tool": "run_parse"},
    {"id": "compute", "label": "计算大表与概述",
     "desc": "22 学科 × 11 列 + 概述数字事实", "tool": "run_compute"},
    {"id": "forecast", "label": "预测回测",
     "desc": "InCites + 历史差值校准（MAPE < 5%）", "tool": "run_forecast"},
    {"id": "charts", "label": "图表渲染",
     "desc": "16 学科 × 6 图 + 概览图", "tool": "run_charts"},
    {"id": "docx", "label": "母版替换",
     "desc": "红色件原地替换 → 报告初稿 + 红件清单", "tool": "run_docx"},
)

#: 自愈重试上限。裁决为"一次"，改这个数等于改口径——须同步 HLD。
MAX_HEAL_ATTEMPTS = 1

#: 视为"非阻断告警"的错误码：不拦停，但终态记 warned
NON_BLOCKING = ("REF_MISSING",)

#: 一次运行的**成品**——只有它们会被当报告看。实现在 `parse_ledger.quarantine_final_products`
#: （产物目录布局归它管），`run_pipeline.py` 直跑路径与这里**共用同一份**，别各写一套。
FINAL_PRODUCTS: tuple[str, ...] = ("报告初稿_*.docx", "红色件清单.md", "red_slots.json")

#: 撤下的成品去哪。放期次目录**内部**而不是 `out/` 下，是为了让"这一期的历史版本"
#: 跟着这一期走，人工翻档不用两头找；也避开 `out/` 根目录的期次发现逻辑
#: （`server.jobs.PERIOD_DIR_RE` 只认六位数字开头的目录名）。
SUPERSEDED_DIR = "_superseded"


def _file_sha256(path, chunk=1 << 20) -> str | None:
    """文件指纹。文件不在返回 None（编排层测试普遍用假路径）。实现在 parse_ledger。"""
    import parse_ledger                                        # noqa: PLC0415
    return parse_ledger.file_sha256(path, chunk)


def _quarantine_final_products(out_dir, run_dir) -> list[str]:
    """撤下期内已有的成品（委托实现见 `parse_ledger.quarantine_final_products`）。

    调用点选在 parse 成功、期次已知的那一刻 —— 此刻"本次会写这个目录"已经成立。
    """
    import parse_ledger                                        # noqa: PLC0415
    return parse_ledger.quarantine_final_products(out_dir, run_dir)


def _heal_hook(failure, ctx):
    """自愈钩子。接入 `src/agent/heal.py` + `rules/repair_rules.yaml`（M3）。

    返回 dict 表示已定方案（会被写进 `repair.yaml`）；返回 None 表示规则库无匹配。
    无论哪种，编排器都照裁决把该步**重跑一次**再判——自愈是"给一次机会"，不是"条件重试"。
    """
    try:
        from . import heal                                     # noqa: PLC0415
    except ImportError:
        return None
    return heal.attempt(failure, ctx)


class RunResult:
    __slots__ = ("status", "period", "steps", "failure", "run_dir", "elapsed",
                 "warnings", "artifacts", "repairs", "ledger_sha256",
                 "superseded")

    def __init__(self, status, run_dir):
        self.status = status          # states.*
        self.run_dir = str(run_dir)
        self.period = None
        self.steps = []               # [{step, status, attempt, elapsed}]
        self.failure = None           # 失败步的 tool 错误 dict
        self.warnings = []
        self.artifacts = {}
        self.repairs = []             # M3：自愈决策记录（rule / overlay / 拒绝项）
        self.ledger_sha256 = None     # 台账指纹（运行前后各取一次，用于只读护栏）
        self.superseded = []          # 本次运行撤下的上版成品
        self.elapsed = 0.0

    def as_dict(self):
        return {"status": self.status, "period": self.period, "run_dir": self.run_dir,
                "steps": self.steps, "failure": self.failure,
                "warnings": self.warnings, "artifacts": self.artifacts,
                "repairs": self.repairs,
                "ledger_sha256": self.ledger_sha256,
                "superseded": self.superseded,
                "elapsed": round(self.elapsed, 2)}


def _advice_block(err, repair, out_root=None):
    """「需人工」若干小节（B 档；2026-09-19；D1 起改调 AI 层 `diagnose`）。

    旧写法直接贴规则库的 `advice_unapproved`：同一条规则，哪一期、哪个学科
    失败写出来一字不差，人工还得回去自己数 22 行。AI 层把它换成
    「本次实况 + 怎么核对（按上下文拼装）」（构建器由 `agent/narrator` 迁入，
    rule 输出逐字一致；金样 `tests/fixtures/ai/diagnose_rule_*.txt` 对拍守）。

    🔴 这里**兜底到旧写法**而不是让异常冒出去：《诊断报告》是升级态交给人工的
    唯一交接物，写不出来比写得朴素严重得多。回落语义已在 AI 层内部完成，
    这层 try/except 只作「报告不能因任何事中断」的防御。
    """
    def legacy():
        out = []
        for a in repair.get("advice") or []:
            out += ["", f"### 需人工：{a.get('rule') or '规则库'}", "",
                    f"- 原因：{a.get('why')}", f"- 依据：{a.get('doc') or '—'}", "",
                    f"> {a.get('advice') or '—'}"]
        return out, {"backend": "rule", "mode": "rule", "segments": [], "notice": ""}

    if not (repair or {}).get("advice"):
        return [], {"backend": "rule", "mode": "rule", "segments": [], "notice": ""}
    try:
        import ai                                              # noqa: PLC0415

        scope = ai.using(data_root=out_root) if out_root else _nullcontext()
        with scope:
            ans = ai.run("diagnose", str((err or {}).get("period") or ""),
                         payload={"failure": err, "repair": repair}, actor="system")
        seg = ans.text.splitlines()
        if seg:
            return seg, {"backend": ans.backend, "mode": ans.mode,
                         "segments": [s.as_dict() for s in ans.segments],
                         "record_id": ans.record_id, "notice": ans.notice}
        return legacy()                     # 拼不出任何一句 → 退回静态文案
    except Exception:                                          # noqa: BLE001
        return legacy()


def _nullcontext():
    import contextlib                                          # noqa: PLC0415
    return contextlib.nullcontext()


def _write_diagnosis(run_dir, ledger, step, err, attempts, repair=None, out_root=None):
    """逾限升级时产出《诊断报告》（SRS R-26）。

    两种触发共用一个出口：步骤自愈逾限，以及运行期原件只读护栏。后者不是"自愈没成"，
    所以标题与处置都另走一套——否则人工会按"补一条规则"去处理一个跟规则无关的事故。
    """
    guard_fired = step["id"] == "guard"
    narrative = None          # B 档：叙事后端留痕（末尾要交代报告有没有经模型加工）
    p = pathlib.Path(run_dir) / "诊断报告.md"
    body = [
        f"# 诊断报告 · {'原件只读护栏触发' if guard_fired else '自愈逾限'}",
        "",
        f"- 台账：`{ledger}`",
        f"- 失败步骤：**{step['label']}**（`{step['id']}` → 工具 `{step['tool']}`）",
        f"- 错误码：`{err.get('code')}`",
        f"- 错误说明：{err.get('message')}",
        f"- 已尝试：首轮 + {attempts} 次自愈重试（上限 {MAX_HEAL_ATTEMPTS}）",
    ]
    # —— M3：把"自愈做了什么、为什么没成功"写清楚，否则人工接手要重新考古 ——
    if repair and repair.get("library_error"):
        body += ["", "## 规则库不可用", "",
                 "自愈这次**没能开始工作**：规则库文件读不出来（不是台账脏）。",
                 "", f"- 原因：`{repair['library_error']}`",
                 "- 处置：修好 `src/agent/rules/repair_rules.yaml` 后重跑；"
                 "在此之前自愈对所有失败都等于没有规则。"]
    elif repair:
        body += ["", "## 自愈过程", "",
                 f"- 结论：`{repair.get('outcome')}`",
                 f"- 已应用规则：{repair.get('rules') or '（无）'}",
                 f"- 记录：`{repair.get('repair_yaml') or '（未落盘）'}`"]
        if repair.get("overlay"):
            body += [f"- 提交的读表口径：`{json.dumps(repair['overlay'], ensure_ascii=False)}`"]
        advice_lines, narrative = _advice_block(err, repair, out_root=out_root)
        body += advice_lines
    if guard_fired:
        body += ["", "## 台账指纹", "",
                 f"- 运行前：`{err.get('before')}`",
                 f"- 运行后：`{err.get('after')}`",
                 "",
                 "两者不等 = 本次运行期间台账文件被改写。**本次运行的全部结论作废**，"
                 "因为无法保证报告数字对应的就是你刚拿到的那个台账。"]
    body += ["", "## 明细", "",
             f"```json\n{json.dumps(err, ensure_ascii=False, indent=2)}\n```"]
    unknown = (err.get("diagnostics") or {}).get("unmatched_names") or {}
    if unknown:
        body += ["", "## 台账里认不出来的学科名", "",
                 "把下面这些名字与规范名单对上，或补进 `repair_rules.yaml` 的别名表：", ""]
        for sheet, names in unknown.items():
            body += [f"- `{sheet}` 首列：{names}"]
    if guard_fired:
        body += ["", "## 处置", "",
                 "1. 该运行已停止，产物不采信；",
                 "2. 先查清是谁改的台账（手工编辑？脚本？同步盘？），"
                 "拉到与馆员核对过的版本后重跑；",
                 "3. 严禁把这条护栏当成「误报」关掉 —— 它拦的是「报告跟台账对不上」的最坏情况。"]
    else:
        body += ["", "## 处置", "",
                 "1. 该运行已停止，**未继续后续步骤**，不产出报告初稿；",
                 "2. 请人工核对台账对应工作表/期次列，修正后重跑（重跑会新建运行，本记录保留）；",
                 "3. 若属新出现的脏例，请在 `src/agent/rules/repair_rules.yaml` 补规则并经馆员确认。",
                 ]
    if err.get("fails"):
        body += ["", "## 未通过的断言", ""] + [f"- {m}" for m in err["fails"]]
    # —— 有没有经过模型，必须写在报告上，不能靠猜 ——
    # 尾注判定读 AI 层的逐段出处（`Answer.segments`，SPEC §1）：
    #   任一模型段 → 润色交代；有回落说明 → 回退交代；否则「未经过模型加工」。
    # rule 模式输出与迁移前逐字一致（D1 金样对拍守）。
    tail = "> 本报告由 `src/agent/flow.py` 自动生成"
    narrative = narrative or {}
    be = narrative.get("backend")
    modes = [s.get("mode") for s in narrative.get("segments") or []]
    notice = narrative.get("notice") or ""
    record_id = narrative.get("record_id")
    if "model" in modes:
        tail += (f"；「本次实况 / 怎么核对」两段经 **{be}** 后端润色，"
                 "数字已过防护盾校验（占位符完备、无新增数字）。")
        if record_id:
            tail += f"（留痕 {record_id}）"
    elif notice:
        tail += f"；**{be}** 后端不可用或校验未过，已回退规则输出（{notice}）。"
    else:
        tail += "，未经过模型加工。"
    body += ["", "---", "", tail]
    p.write_text("\n".join(body), encoding="utf-8")
    return p


def run(ledger, out_root="out", run_dir=None, reference=None, backtest=False):
    """跑一次受控编排。返回 `RunResult`。本函数**不抛异常**——失败以状态表达。"""
    t0 = time.time()
    ledger = str(ledger)
    out_root = pathlib.Path(out_root)

    # 运行目录：未指定则先落临时名，parse 拿到期次后再规整（与 _jobs 约定一致）
    run_dir = pathlib.Path(run_dir) if run_dir else (out_root / "_jobs" / "manual")
    tr = Trace(run_dir)

    result = RunResult(states.PENDING, run_dir)
    ctx = {"ledger": ledger, "out_root": str(out_root), "run_dir": str(run_dir),
           "reference": reference, "overlay": None}   # overlay 由 heal 填入（M3）

    #: 台账指纹（只读护栏的基准）。跑一次 7MB 的 sha256 约 20ms，换的是"原件只读"
    #: 这条红线在**运行期**有人看着，而不是只在测试里被证明过。
    led_sha0 = _file_sha256(ledger)

    tr.event("plan", observation=f"台账 {pathlib.Path(ledger).name}",
             decision="run", reason=f"{len(STEPS)} 步主干（固定顺序）")
    tr.transition(states.PENDING, states.RUNNING, trigger="start")

    current = states.RUNNING
    for step in STEPS:
        tr.event("act", tool=step["tool"], args={"step": step["id"]})
        started = time.time()
        tool_err = None
        attempt = 1

        try:
            payload = _invoke(step, ctx, result)
        except tools.ToolError as e:
            tool_err = e.as_dict()

        # 非阻断告警（如无原件时的回测）：记警告，不拦停
        if tool_err and tool_err["code"] in NON_BLOCKING:
            result.warnings.append(f"{step['id']}: {tool_err['message']}")
            tr.event("observe", tool=step["tool"], observation="跳过（可降级）",
                     decision="continue", reason=tool_err["code"])
            tr.task_run(step["id"], attempt, started, time.time(), "warn")
            result.steps.append({"step": step["id"], "status": "warn", "attempt": attempt,
                                 "elapsed": round(time.time() - started, 2)})
            continue

        # ---- 裁决落地：首轮拦停 → 一次自愈 → 再败升级 ----
        if tool_err:
            tr.event("observe", tool=step["tool"], observation=tool_err["message"],
                     decision="halt", reason=tool_err["code"])
            tr.event("decide", tool=step["tool"], decision="halt",
                     reason="首轮失败即拦停，不进入后续步骤")
            current = _transition(tr, current, states.RETRYING, trigger=tool_err["code"])
            tr.task_run(step["id"], attempt, started, time.time(), "failed", )
            result.steps.append({"step": step["id"], "status": "failed", "attempt": attempt,
                                 "elapsed": round(time.time() - started, 2)})

            repaired = None
            if MAX_HEAL_ATTEMPTS > 0:
                tr.event("plan", tool=step["tool"], decision="heal",
                         reason=f"尝试自愈（上限 {MAX_HEAL_ATTEMPTS} 次）")
                repaired = _heal_hook(tool_err, ctx)
                applied = bool(repaired and repaired.get("overlay"))
                if repaired and repaired.get("library_error"):
                    # 规则库自己坏了 ≠ 没有匹配规则。两者都照裁决"给一次重跑机会"，
                    # 但轨迹与诊断报告必须说清是哪一种：否则人工会拿着"没有匹配规则"
                    # 去台账里找一个并不存在的脏例，而真正该修的是规则库文件。
                    obs = f"规则库不可用（{repaired['library_error']}）"
                elif applied:
                    obs = "已提交读表口径 " + ",".join(repaired.get("rules") or [])
                elif repaired:
                    obs = ("规则命中但不能执行（" + ",".join(
                        r.get("rule") or "?" for r in repaired.get("refused") or [])
                        + "）")
                else:
                    obs = "规则库无匹配"
                tr.event("act", tool="apply_repair_rule", args=repaired, observation=obs,
                         decision="retry",
                         reason=(f"自愈结论 {repaired.get('outcome')}" if repaired
                                 else "无匹配规则，仍按裁决给一次重跑机会"))
                if repaired:
                    result.repairs.append(repaired)

            attempt = 2
            started = time.time()
            try:
                payload = _invoke(step, ctx, result)
                tool_err = None
            except tools.ToolError as e:
                tool_err = e.as_dict()

            if tool_err:
                tr.task_run(step["id"], attempt, started, time.time(), "failed")
                result.steps.append({"step": step["id"], "status": "failed", "attempt": attempt,
                                     "elapsed": round(time.time() - started, 2)})
                tr.escalate(reason=f"{step['id']} 自愈逾限", detail=tool_err)
                current = _transition(tr, current, states.ESCALATED,
                                      trigger="heal_exhausted", attempt=attempt)
                result.failure = {**tool_err, "step": step["id"]}
                _write_diagnosis(run_dir, ledger, step, tool_err, MAX_HEAL_ATTEMPTS,
                                 repair=repaired, out_root=out_root)
                break
            tr.task_run(step["id"], attempt, started, time.time(), "done")
            result.steps.append({"step": step["id"], "status": "done", "attempt": attempt,
                                 "elapsed": round(time.time() - started, 2)})
            tr.event("observe", tool=step["tool"], observation="重试成功",
                     decision="continue", reason="heal_ok")
            current = _transition(tr, current, states.RUNNING, trigger="heal_ok")
        else:
            tr.task_run(step["id"], attempt, started, time.time(), "done")
            result.steps.append({"step": step["id"], "status": "done", "attempt": attempt,
                                 "elapsed": round(time.time() - started, 2)})
            tr.event("observe", tool=step["tool"], observation="ok", decision="continue")

        # 期次与产物随步骤回填
        if step["id"] == "parse" and not result.failure:
            result.period = payload.get("period")
            if result.period and run_dir.name == "manual":
                pass          # 保持调用方指定目录，不擅自改名
            if result.period:
                # 此刻已确定"本次会改写 out/<期次>/"——先把上版成品撤下来。
                # 撤下而不是删除：若本次失败，期内没有成品（诚实的"未出稿"），
                # 而上一版仍完整躺在 _superseded/ 里可追溯。
                moved = _quarantine_final_products(out_root / result.period, run_dir)
                if moved:
                    result.superseded += moved
                    tr.event("observe", observation=f"撤下上版成品：{moved}",
                             decision="continue",
                             reason="避免失败运行留下「新表格 + 旧报告」混装")
        if isinstance(payload, dict):
            result.artifacts.update({k: v for k, v in payload.items()
                                     if k in ("out_dir", "table2", "docx")})

    # ------------------------------------------------ 原件只读护栏（R-24 运行期落点）
    # 测试里的 sha256 断言只证明了"我测的那条路径没改台账"。这条是运行期的：
    # 自愈、工具、以及将来接进来的人工重放，只要动了原件，都在同一处被拦下。
    result.ledger_sha256 = led_sha0
    led_sha1 = _file_sha256(ledger)
    if led_sha0 and led_sha1 and led_sha0 != led_sha1:
        guard = {"code": "FILE_INVALID",
                 "message": "台账在本次运行期间被改写 —— 原件只读红线（R-24）被破",
                 "step": "guard", "before": led_sha0, "after": led_sha1}
        result.warnings.append("guard: " + guard["message"])
        tr.event("observe", observation=guard["message"], decision="halt",
                 reason="ledger_mutated")
        tr.event("decide", decision="escalated", reason="原件被改写，本次运行结果不可采信")
        if current in (states.RUNNING, states.RETRYING):
            current = _transition(tr, current, states.ESCALATED, trigger="ledger_mutated")
        if result.failure is None:
            result.failure = guard
            _write_diagnosis(run_dir, ledger,
                             {"id": "guard", "label": "原件只读护栏",
                              "tool": "（运行期护栏，不属主干步骤）"},
                             guard, 0, out_root=out_root)

    # ------------------------------------------------------------ 终态
    if result.failure is None:
        if current == states.RUNNING:
            dst = states.WARNED if result.warnings else states.COMPLETED
            _transition(tr, current, dst, trigger="all_steps_done")
            result.status = dst
    else:
        result.status = states.ESCALATED

    result.elapsed = time.time() - t0
    (run_dir / "run_result.json").write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    tr.event("decide", decision=result.status,
             reason=f"{len(result.steps)} 次步骤执行 · 用时 {result.elapsed:.1f}s")
    return result


def _invoke(step, ctx, result):
    """调用该步对应的工具。parse 步自动把产物目录定为 out/<期次>。

    `ctx["overlay"]` 由 `heal.attempt()` 在首轮失败后填入（M3）：它只影响本次运行
    的**读表口径**，台账文件不被改动。
    """
    overlay = ctx.get("overlay") or None
    if step["id"] == "parse":
        # 先探一次期次，好把产物落到期次目录（与 run_pipeline 行为一致）
        out_dir = result.artifacts.get("out_dir") or str(
            pathlib.Path(ctx["out_root"]) / "_pending")
        payload = tools.call("run_parse", ledger=ctx["ledger"], out_dir=out_dir,
                             overlay=overlay)
        period = payload.get("period")
        if period and out_dir.endswith("_pending"):
            real = pathlib.Path(ctx["out_root"]) / period
            payload = tools.call("run_parse", ledger=ctx["ledger"], out_dir=str(real),
                                 overlay=overlay)
        return payload
    out_dir = result.artifacts.get("out_dir") or str(
        pathlib.Path(ctx["out_root"]) / (result.period or "_pending"))
    if step["id"] == "docx":
        return tools.call("run_docx", out_dir=out_dir)
    return tools.call(step["tool"], out_dir=out_dir)


def _transition(tr, src, dst, trigger, attempt=1):
    tr.transition(src, dst, trigger=trigger, attempt=attempt)
    return dst


def main():
    ap = argparse.ArgumentParser(description="文衡 Agent 层 · 固定编排（P1/M2）")
    ap.add_argument("ledger")
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--reference", default=None, help="已出版原件 docx（用于回测）")
    args = ap.parse_args()
    r = run(args.ledger, out_root=args.out_root, run_dir=args.run_dir,
            reference=args.reference)
    print(json.dumps(r.as_dict(), ensure_ascii=False, indent=1))
    return 0 if r.status in (states.COMPLETED, states.WARNED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
