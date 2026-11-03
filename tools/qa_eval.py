# -*- coding: utf-8 -*-
"""qa 金问集评测（票 A，规格 2026-10-31）：逐例 `ai.run("qa")` → 期望值/工具/模式判定。

**手动工具，不进 pytest 收集**：真网关按例计费（~27 例 × --repeat）。判定的纯逻辑
（schema 校验 / 期望值运行时解值 / contains / ops 判定）另有不触网单测
`tests/test_qa_eval.py`——单测用假 view 与假 Answer，不发包。

用法（wenheng/ 下）：

    uv run python tools/qa_eval.py --model ynu-deepseek   # 用模型清单里的指定模型
    uv run python tools/qa_eval.py                        # 缺省＝当前部署（清单 active 或 .env）
    uv run python tools/qa_eval.py --case direct-prox-chem    # 只跑一例
    uv run python tools/qa_eval.py --repeat 3                 # 每例跑 3 遍

题集：`config/qa_eval_cases.json`（金问集，字段 {id, group, question, history?,
period, expect}）。**期望值严禁硬编码**——expect.values 只写
`{metric, disc, period?}`，metric 用 `ai._plan.MODEL_METRICS` 的无数字别名
（proximity / threshold / threshold_permille / papers / cnci / top_papers / …），
值由本工具运行时经 `flexible.queries.execute` 从数据面读出。

逐例判据（PASS 需全部满足）：

- `mode == model`（qa 必须模型作答；澄清/越权类模型照发时 fallback 记 off_topic，
  mode 仍是 model——回落码只进组统计，不当 FAIL）；
- expect.values 的每个值串都出现在**还原后的答案文本**里（contains 判定；值串
  格式化与 `_evidence.value_face` 同一份——接近度两位小数百分数、CNCI 两位小数、
  排名与其余指标为不带千分位的整数；期望值解不出 → 该项 FAIL 并注明原因）；
- expect.ops 的每件工具名都出现在 `Answer.receipts`（refused 回执也算——
  越权学科正是要它；回落/盾拒路径不发布回执，按未满足计 FAIL）。

退出码：题集校验失败＝2；有 FAIL＝1；全过＝0。
留痕照写 `out/<期次>/ai_calls.jsonl`（诚实审计：评测调用与本站问答同一记录面）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import re
import sys
import time


def _utf8_stream(stream):
    """Windows 控制台防 GBK 炸（输出含 ‰ 等字符）。"""
    fn = getattr(stream, "reconfigure", None)
    if fn is not None:
        try:
            fn(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass


_utf8_stream(sys.stdout)
_utf8_stream(sys.stderr)

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import ai                                                # noqa: E402
from ai import _config, _evidence, _models, _plan, _qa, _record   # noqa: E402
from ai._brain import OpenAIBrain                        # noqa: E402
from flexible import queries                             # noqa: E402

CASES_PATH = REPO / "config" / "qa_eval_cases.json"

#: ops 断言的工具名全集＝qa 写作轮五件只读工具（名字唯一出处 `_qa._TOOL_OPS`）。
TOOL_NAMES = tuple(_qa._TOOL_OPS)

#: 指标别名 → 引擎规范名（唯一口径 `metric_face.FACE` 的模型面视图）。
_ALIAS = {alias: canon for alias, canon, _cn in _plan.MODEL_METRICS}

_PERIOD_RE = re.compile(r"20\d{4}$")


def load_env():
    """照 `server/config.py` 的姿势读 server/.env（setdefault，不打印值）——
    缺省部署路径（不带 --model）靠它拿到 .env 的后端配置。"""
    env_file = REPO / "server" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ================================================================ 纯逻辑（单测覆盖）
def validate_cases(cases) -> list[str]:
    """金问集 schema 校验：字段齐全、expect 合法、每组 ≥2 例、总量 20–30。

    返回错误列表（空＝合法）；不触网、不读数据。
    """
    if not isinstance(cases, list):
        return ["题集必须是 JSON 数组"]
    errs: list[str] = []
    if not (20 <= len(cases) <= 30):
        errs.append(f"例数 {len(cases)} 不在 20–30")
    ids: set = set()
    groups: dict = {}
    for i, case in enumerate(cases):
        tag = f"第 {i + 1} 例"
        if not isinstance(case, dict):
            errs.append(f"{tag}：不是对象")
            continue
        unknown = set(case) - {"id", "group", "question", "history", "period", "expect"}
        if unknown:
            errs.append(f"{tag}：未知字段 {sorted(unknown)}")
        cid = str(case.get("id") or "")
        if not cid:
            errs.append(f"{tag}：缺 id")
        elif cid in ids:
            errs.append(f"{tag}：id 重复 {cid}")
        ids.add(cid)
        name = cid or tag
        group = str(case.get("group") or "")
        if not group:
            errs.append(f"{name}：缺 group")
        groups.setdefault(group, []).append(name)
        if not str(case.get("question") or "").strip():
            errs.append(f"{name}：缺 question")
        if not _PERIOD_RE.fullmatch(str(case.get("period") or "")):
            errs.append(f"{name}：period 非法 {case.get('period')!r}")
        hist = case.get("history") or []
        if not isinstance(hist, list) or any(
                not isinstance(h, dict) or h.get("who") not in ("me", "wh")
                or not str(h.get("text") or "").strip() for h in hist):
            errs.append(name + "：history 须为 [{who: me|wh, text}, …] 形状的列表")
        errs.extend(_validate_expect(name, case.get("expect")))
    thin = sorted(g for g, members in groups.items() if len(members) < 2)
    if thin:
        errs.append(f"这些组不足 2 例：{thin}")
    return errs


def _validate_expect(name, expect) -> list[str]:
    """单个 expect 的合法性：values/ops/mode 三键，别名与工具名都收口。"""
    if not isinstance(expect, dict):
        return [f"{name}：expect 必须是对象"]
    errs: list[str] = []
    unknown = set(expect) - {"values", "ops", "mode"}
    if unknown:
        errs.append(f"{name}：expect 未知字段 {sorted(unknown)}")
    values = expect.get("values") or []
    if not isinstance(values, list):
        errs.append(f"{name}：expect.values 必须是列表")
    for j, v in enumerate(values):
        if not isinstance(v, dict) or set(v) - {"metric", "disc", "period"}:
            errs.append(f"{name}：values[{j}] 只许 metric/disc/period")
            continue
        if v.get("metric") not in _ALIAS:
            errs.append(f"{name}：values[{j}] metric {v.get('metric')!r} "
                        "不在 MODEL_METRICS 别名表")
        if not str(v.get("disc") or "").strip():
            errs.append(f"{name}：values[{j}] 缺 disc")
        p = v.get("period")
        if p is not None and not _PERIOD_RE.fullmatch(str(p)):
            errs.append(f"{name}：values[{j}] period 非法 {p!r}")
    ops = expect.get("ops") or []
    if not isinstance(ops, list) or any(op not in TOOL_NAMES for op in ops):
        errs.append(f"{name}：ops 必须是工具名列表（允许：{list(TOOL_NAMES)}）")
    if expect.get("mode", "model") != "model":
        errs.append(f"{name}：mode 只许 model（缺省）")
    return errs


def resolve_values(view, case) -> list[dict]:
    """expect.values → 运行时解值：`[{metric, disc, period, want, why}]`。

    `want`＝答案文本里应出现的数字串（`_evidence.value_face` 同一份格式化——答案里的
    数字就是它还原出来的）；期次缺省＝case.period；取不到值/查询被拒 →
    `want=None` 且 `why` 注明（judge 按未满足计 FAIL）。
    """
    out: list[dict] = []
    for v in (case.get("expect") or {}).get("values") or []:
        metric = _ALIAS[v["metric"]]
        p = str(v.get("period") or case["period"])
        row = {"metric": v["metric"], "disc": v["disc"], "period": p,
               "want": None, "why": ""}
        try:
            res = queries.execute(view, "at", metric=metric, disc=v["disc"], period=p)
        except Exception as e:                                  # noqa: BLE001
            row["why"] = f"{type(e).__name__}: {e}"
            out.append(row)
            continue
        raw = res.get("value")
        if raw is None:
            row["why"] = "该期无数据"
        else:
            row["want"] = _evidence.value_face(metric, raw)
        out.append(row)
    return out


def judge(case, answer, resolved=()) -> tuple[bool, list[str]]:
    """逐例判定（纯逻辑）：`(ok, 原因列表)`。

    `answer` 按鸭子类型读 `mode / text / receipts`（单测给 SimpleNamespace 假 Answer）；
    `resolved` 是 `resolve_values` 的行。ops 按 receipts 的工具名集合判——
    回落/盾拒不发布回执，ops 自然按未满足计。
    """
    expect = case.get("expect") or {}
    reasons: list[str] = []
    mode = expect.get("mode", "model")
    if answer.mode != mode:
        reasons.append(f"mode={answer.mode}（期望 {mode}；回落码见组统计）")
    values = expect.get("values") or []
    if values:
        if len(resolved) != len(values):
            reasons.append(f"期望值行数不符（expect {len(values)}，"
                           f"解出 {len(resolved)}）")
        else:
            text = str(answer.text or "")
            for r in resolved:
                if r["want"] is None:
                    reasons.append(f"期望值解不出：{r['metric']}/{r['disc']}/{r['period']}"
                                   + (f"（{r['why']}）" if r.get("why") else ""))
                elif r["want"] not in text:
                    reasons.append(f"答案未含期望值 {r['want']}"
                                   f"（{r['metric']}/{r['disc']}/{r['period']}）")
    ops = expect.get("ops") or []
    if ops:
        got = sorted({str(getattr(rcpt, "tool", "") or "")
                      for rcpt in (answer.receipts or ())} - {""})
        for op in ops:
            if op not in got:
                reasons.append(f"回执缺工具 {op}（实际回执工具：{got or '无'}；"
                               "回落/盾拒路径不发布回执）")
    return (not reasons), reasons


# ================================================================ 执行（真网关）
def _brain_for(model_id: str):
    """`--model <models.json 的 id>` → OpenAIBrain（不改清单、不写 out/_ai）。"""
    entry = next((m for m in _models.read()["models"] if m["id"] == model_id), None)
    if entry is None:
        print(f"模型清单里没有 id {model_id!r}（清单见 out/_ai/models.json）。")
        return None
    if not (entry["base_url"] and entry["model"] and entry["key"]):
        print(f"模型 {model_id!r} 配置不齐（base_url/model/key），不发包。")
        return None
    cfg = _config._env_config()          # 超时与预算跟部署同一口（.env / 默认）
    print(f"模型：{model_id}（{entry['model']} @ {entry['base_url']}）")
    return OpenAIBrain(base_url=entry["base_url"], model=entry["model"],
                       key=entry["key"], timeout=cfg["timeout"],
                       max_tokens=cfg["max_tokens"],
                       max_egress_chars=cfg["max_egress_chars"])


def find_record(root, period: str, rid) -> dict | None:
    """按 record_id 回读这条调用的留痕（fallback / 记录耗时都在记录面）。"""
    if not rid:
        return None
    path = _record.call_path(root, period)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("record_id") == rid:
            return rec
    return None


def run_case(case, resolved, view_ok: bool) -> dict:
    """跑一例：ai.run("qa") → 回读留痕 → judge。运行期故障不抛（以 row 表达）。"""
    period = str(case["period"])
    payload = {"question": str(case["question"]),
               "history": [dict(h) for h in (case.get("history") or [])]}
    t0 = time.perf_counter()
    try:
        ans = ai.run("qa", period, payload=payload, actor="admin")
    except Exception as e:                                      # noqa: BLE001
        return {"id": case["id"], "group": case["group"], "ok": False,
                "mode": "error", "fallback": None,
                "reasons": [f"run 异常 {type(e).__name__}: {e}"],
                "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    rec = find_record(_record.data_root(), period, ans.record_id) or {}
    if view_ok:
        ok, reasons = judge(case, ans, resolved)
    else:
        ok, reasons = False, ["数据面视图不可用（期望值无从解起）"]
    return {"id": case["id"], "group": case["group"], "ok": ok,
            "mode": ans.mode, "fallback": rec.get("fallback"),
            "reasons": reasons, "elapsed_ms": elapsed_ms}


def print_stats(rows) -> None:
    """组统计（保持题集的组序）：通过/总例、盾拒数、回落码分布、平均耗时。"""
    order: list = []
    by_group: dict = {}
    for row in rows:
        if row["group"] not in by_group:
            order.append(row["group"])
            by_group[row["group"]] = []
        by_group[row["group"]].append(row)
    print("\n===== 组统计 =====")
    for g in order:
        rs = by_group[g]
        passed = sum(1 for r in rs if r["ok"])
        shield = sum(1 for r in rs if r["fallback"] == "shield_reject")
        codes: dict = {}
        for r in rs:
            code = r["fallback"] or ("model" if r["mode"] == "model" else r["mode"])
            codes[code] = codes.get(code, 0) + 1
        avg = sum(r["elapsed_ms"] for r in rs) // max(len(rs), 1)
        print(f"{g}: 通过 {passed}/{len(rs)}；盾拒 {shield}；"
              f"分布 {json.dumps(codes, ensure_ascii=False)}；平均 {avg}ms")
    total = len(rows)
    ok = sum(1 for r in rows if r["ok"])
    print(f"总计：通过 {ok}/{total}（{ok / total * 100:.0f}%）")


def main() -> int:
    ap = argparse.ArgumentParser(description="qa 金问集评测（真网关，手动工具，不进 pytest）")
    ap.add_argument("--model", default="", help="models.json 里的模型 id（缺省＝当前部署）")
    ap.add_argument("--case", default="", help="只跑指定 id 的一例")
    ap.add_argument("--repeat", type=int, default=1, help="每例跑几遍（默认 1）")
    args = ap.parse_args()
    load_env()

    try:
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"题集读不了：{e}")
        return 2
    errs = validate_cases(cases)
    if errs:
        for e in errs:
            print(f"题集校验失败：{e}")
        return 2
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"题集里没有 id 为 {args.case!r} 的例。")
            return 2
    if args.repeat < 1:
        print("--repeat 至少 1。")
        return 2

    override = _brain_for(args.model) if args.model else None
    if args.model and override is None:
        return 2

    root = _record.data_root()
    print(f"题集 {len(cases)} 例 × {args.repeat} 遍，数据根 {root}，"
          f"期次以各例 period 为准。")
    print("⚠ 真网关调用，留痕照写 out/<期次>/ai_calls.jsonl（诚实审计，设计内）。\n")

    view_cache: dict = {}
    rows: list = []
    ctx = ai.using(brain=override) if override is not None else contextlib.nullcontext()
    with ctx:
        for case in cases:
            period = str(case["period"])
            view = view_cache.get(period)
            if view is None:
                view = _qa._view_for(root, period)
                view_cache[period] = view
            resolved = resolve_values(view, case) if view is not None else []
            for rep in range(1, args.repeat + 1):
                row = run_case(case, resolved, view is not None)
                row["repeat"] = rep
                rows.append(row)
                mark = "PASS" if row["ok"] else "FAIL"
                tail = "" if row["ok"] else f" ← {'；'.join(row['reasons'])}"
                print(f"[{mark}] {row['id']}（{row['group']}，第{rep}遍）"
                      f"{row['elapsed_ms']}ms fallback={row['fallback']}{tail}",
                      flush=True)

    print_stats(rows)
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
