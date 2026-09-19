# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 诊断叙事（B 档；2026-09-19）。

解决的是一个很具体的坏味道：同一条自愈规则，无论哪一期、哪个学科失败，
《诊断报告》里贴出来的建议**一字不差** —— 因为它直接引用 `repair_rules.yaml`
的 `advice_unapproved`（静态口径说明）。人工拿着它还得回去自己数 22 行。

本模块把它换成**按本次失败现场拼装**的两句：

    - **本次实况**：202607 期，宽表「总被引」期望 22 个学科、实际认出 21 个，
      缺 ['Chemistry']；台账里认不出来的名字：「某某新学科」。
    - **怎么核对**：打开台账「总被引」工作表，在首列找到「某某新学科」，
      确认它对应 22 个规范学科里的哪一个，把 `中文名: 英文名` 补进 ……

「怎么核对」的动作模板写在**规则库**的 `howto` 字段里（口径仍归馆员管），
本模块只负责把上下文填进去 —— 别在这里重写动作说明，否则规则改了报告不变。

后端可插拔（默认 `rule`，零依赖）
------------------------------------------------------------------
    rule    —— 纯规则拼装：确定性、离线、毫秒级。**演示站永远走这条**
               （阿里云 2核2G 跑不了任何 LLM，见 MEMORY.md「仓库与部署」）
    ollama  —— 本机小模型润色（Qwen2.5-3B 级别），走数字防护盾
    http    —— 任意兼容端点（POST {"prompt":…} → {"text":…}）

选择顺序：`advise(..., backend=)` 显式指定 > 环境变量 `WENHENG_NARRATOR_BACKEND`
> `rule`。

三条铁律（不可越）
------------------------------------------------------------------
1. **不进数据路径**。上下文只来自 `ToolError.as_dict()` 已有的字段
   （`fails` / `diagnostics`）；本模块不读台账、不读产物、不联网拿数据。
2. **模型只碰文字，且必过防护盾**。走 `local_llm.protect → generate →
   validate → restore`：数字全部替换成 `[[n]]` 占位符，输出里占位符必须
   各出现且仅出现一次、不得新增任何数字；任一校验失败即**回退规则输出**。
3. **默认 rule**。任何依赖缺失 / 调用异常都等价于"没接模型"，不报错、不降级
   成空文案 —— 诊断报告宁可朴素，也不能没有。
"""
from __future__ import annotations

import os
import pathlib
import re

BACKENDS = ("rule", "ollama", "http")
DEFAULT_BACKEND = "rule"
ENV_BACKEND = "WENHENG_NARRATOR_BACKEND"
ENV_HTTP = "WENHENG_NARRATOR_HTTP"
ENV_MODEL = "WENHENG_NARRATOR_MODEL"

#: 模板里允许被填的占位符。**只认这些** —— 规则库里 `{工作表名: 行号}` 这类
#: 字面示例必须原样保留，所以这里不能用 `str.format`（它会把所有 `{}` 都吃掉）。
_PH = re.compile(r"\{(sheet|metric|period|expect|actual|missing|names)\}")

_PERIOD = re.compile(r"(?<!\d)(20\d{4})(?!\d)")
_EXPECT = re.compile(r"=(\d+)\s*(?:\(|（|$)")
_ACTUAL = re.compile(r"实际\s*(\d+)")
_MISSING = re.compile(r"缺\s*(\[[^\]]*\])")
_METRIC = re.compile(r"宽表\s+([A-Za-z_]\w*)")
# ⚠ 「新国际排名」必须排在「国际排名」前面，否则后者会先命中、把「新」吃掉。
_SHEET = re.compile(r"(新国际排名|新国内排名|国际排名|国内排名|进入前1%矩阵|"
                    r"云大ESI排名|千分之一阈值|省高校表|顶尖论文合计)")


def backend_of(name: str | None = None) -> str:
    """解析后端名。未知值一律回落 `rule`，不抛（诊断报告不能因为配错就写不出来）。"""
    v = (name or os.environ.get(ENV_BACKEND) or DEFAULT_BACKEND).strip().lower()
    return v if v in BACKENDS else DEFAULT_BACKEND


# ---------------------------------------------------------------- 上下文
def _sheet_of_metric(metric: str | None) -> str | None:
    """宽表指标名（total_cites）→ 台账工作表中文名（总被引）。

    反查表在 `parse_ledger.WIDE_METRIC`（唯一事实源）。取不到就返回 None ——
    宁可报告里少一句，也不要在这里维护第二份映射（会漂移）。
    """
    if not metric:
        return None
    try:
        import parse_ledger                                    # noqa: PLC0415
    except ImportError:
        return None
    for title, m in getattr(parse_ledger, "WIDE_METRIC", {}).items():
        if m == metric:
            return title
    return None


def extract_context(failure, repair=None) -> dict:
    """从一次失败里抽出拼装所需的上下文。**只读** `failure` 已有字段。

    抽不到就是 None —— 调用方按"缺则降级"处理，绝不拿默认值编一句出来
    （编出来的"本次实况"比没有更糟：人工会照着去找一个不存在的位置）。
    """
    fails = failure.get("fails") if isinstance(failure, dict) else None
    fails = [str(m) for m in fails] if isinstance(fails, (list, tuple)) else []
    text = " · ".join([str(failure.get("message") or "")] + fails)

    diag = (failure.get("diagnostics") or {}) if isinstance(failure, dict) else {}
    unmatched = diag.get("unmatched_names") or {}

    ctx = {"period": None, "sheet": None, "metric": None, "expect": None,
           "actual": None, "missing": None, "names": None, "n_fails": len(fails)}

    m = _PERIOD.search(text)
    if m:
        ctx["period"] = m.group(1)
    # 断言消息里未必带期次（如「宽表 X 学科数=22」），但 `run_parse` 一定会在
    # ToolError 上挂 period —— 它是本次失败最权威的期次，优先级高于文本里抓到的。
    if isinstance(failure, dict) and failure.get("period"):
        ctx["period"] = str(failure["period"])
    m = _METRIC.search(text)
    if m:
        ctx["metric"] = m.group(1)
    m = _SHEET.search(text)
    if m:
        ctx["sheet"] = m.group(1)
    if not ctx["sheet"] and ctx["metric"]:
        ctx["sheet"] = _sheet_of_metric(ctx["metric"])
    m = _EXPECT.search(text)
    if m:
        ctx["expect"] = m.group(1)
    m = _ACTUAL.search(text)
    if m:
        ctx["actual"] = m.group(1)
    m = _MISSING.search(text)
    if m:
        ctx["missing"] = m.group(1).strip("[]").replace("'", "")

    # 认不出的名字：{指标: [名字]} → 合并成一句；顺带补 sheet（可能 fails 里没有）
    names = []
    for metric, ns in unmatched.items():
        names += [str(n) for n in (ns or [])]
        if not ctx["sheet"]:
            ctx["sheet"] = _sheet_of_metric(metric)
        if not ctx["metric"]:
            ctx["metric"] = metric
    if names:
        ctx["names"] = "、".join(f"「{n}」" for n in names)
    return ctx


def _fact_line(ctx: dict) -> str | None:
    """「本次实况」一句话。缺关键项就整句不给。"""
    bits = []
    if ctx.get("period"):
        bits.append(f"{ctx['period']} 期")
    if ctx.get("sheet"):
        bits.append(f"「{ctx['sheet']}」")
    elif ctx.get("metric"):
        bits.append(f"宽表 {ctx['metric']}")
    if ctx.get("expect") and ctx.get("actual"):
        bits.append(f"期望 {ctx['expect']}、实际 {ctx['actual']}")
    if ctx.get("missing"):
        bits.append(f"缺 {ctx['missing']}")
    if ctx.get("names"):
        bits.append(f"认不出来的名字：{ctx['names']}")
    if not bits:
        return None
    return "，".join(bits) + "。"


def _fill(tpl, ctx) -> str | None:
    """填占位符，**按句降级**。

    模板（规则库 `howto`，yaml 用 `|` 块保留换行）写成一行一句：
    某句用到的占位符在本次上下文里没有 → **只丢那一句**，不是丢整段。
    粒度选"句"而不是"整段"是实测出来的：表头偏移这类失败拿不到期望值/实际值，
    若整段丢弃，报告就只剩一句"请填 declared"，而真正有用的是"去数表头在第几行"。
    """
    if not tpl:
        return None
    kept = []
    for line in str(tpl).splitlines():
        line = line.strip()
        if not line:
            continue
        used = set(_PH.findall(line))
        if any(not ctx.get(k) for k in used):
            continue                        # 缺上下文 → 丢这一句，别硬造半截指引
        kept.append(_PH.sub(lambda m: str(ctx[m.group(1)]), line))
    if not kept:
        return None
    return "".join(kept)                    # 中文模板，句间不加空格


def _rule_title(rule_id) -> str:
    """`discipline_alias_map` → `学科名别名映射（discipline_alias_map）`。

    规则库读不出来就退回 id —— 标题不是关键路径，不值得为它让整个报告写不出来。
    """
    if not rule_id:
        return "规则库"
    try:
        from . import heal                                      # noqa: PLC0415
        r = heal.rule_by_id(rule_id)
    except Exception:                                           # noqa: BLE001
        r = None
    name = (r or {}).get("name")
    return f"{name}（{rule_id}）" if name else str(rule_id)


def _howto(rec, ctx) -> str | None:
    """取规则库的 `howto` 并填上下文。规则库没写 howto → None（不是错误）。"""
    from . import heal                                          # noqa: PLC0415
    try:
        rule = heal.rule_by_id(rec.get("rule")) if rec.get("rule") else None
    except Exception:                                           # noqa: BLE001
        rule = None
    tpl = (rule or {}).get("howto") or rec.get("howto")
    return _fill(tpl, ctx)


# ---------------------------------------------------------------- 模型后端
def _model_generate(prompt: str, backend: str) -> str:
    """调模型。异常一律向上抛 —— 由 `advise` 统一回退，不在内部吞掉。"""
    if backend == "ollama":
        import local_llm                                        # noqa: PLC0415
        return local_llm.generate(prompt, model=os.environ.get(ENV_MODEL)
                                  or local_llm.DEFAULT_MODEL)
    if backend == "http":
        import json
        import urllib.request
        url = os.environ.get(ENV_HTTP)
        if not url:
            raise RuntimeError(f"未配置 {ENV_HTTP}")
        body = json.dumps({"prompt": prompt}).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:     # noqa: S310
            return str((json.load(r) or {}).get("text") or "").strip()
    raise RuntimeError(f"未知后端 {backend}")


def _polish(text: str, backend: str):
    """过一遍模型（含数字防护盾）。返回 (最终文本, meta)。失败回退原文。"""
    try:
        import local_llm                                        # noqa: PLC0415
    except ImportError:
        return text, {"mode": "fallback", "reason": "local_llm 不可用"}
    protected, mapping = local_llm.protect(text)
    try:
        out = _model_generate(_PROMPT.format(text=protected), backend)
    except Exception as e:                                      # noqa: BLE001
        return text, {"mode": "fallback", "reason": f"调用失败：{type(e).__name__}: {e}"}
    ok, detail = local_llm.validate(out, mapping)
    if not ok:
        return text, {"mode": "fallback", "reason": f"校验失败：{detail}"}
    return local_llm.restore(out, mapping), {"mode": "polished"}


_PROMPT = """你是图书馆业务系统的运维说明写手。下面是一条给馆员看的人工核对指引，
请在不改变任何事实与数字的前提下改得更清楚、更好执行。

严格规则：
1. [[n]] 是数字占位标记，必须原样保留，每个出现且只出现一次；
2. 严禁新增、删除或修改任何其它数字、表名、学科名、文件路径；
3. 只输出指引本身，不要加标题、不要加解释、不要加客套话。

原文：
{text}
"""


# ---------------------------------------------------------------- 对外
def advise(rec, ctx, backend: str | None = None) -> tuple[list[str], dict]:
    """把一条「需人工」建议拼成 markdown 行。返回 (lines, meta)。

    只写**这条规则专属**的两样：怎么核对 + 规则库口径原文。
    「本次实况」由 `compose()` 单独成节（它属于整次失败，挂在任何一条规则
    下面都会让人以为另外几条规则说的是另一件事）。

    `rec` 是 `heal.attempt()` 产出的 advice 项 `{rule, why, doc, advice}`；
    `ctx` 由 `extract_context()` 给出。

    两条硬保证：① 永不抛异常（它跑在写《诊断报告》的路径上，抛了就没报告了）；
    ② 后端失败 = 规则输出，不会出现"模型编了一半"的文案。
    """
    be = backend_of(backend)
    meta = {"backend": be, "mode": "rule", "filled": []}
    lines: list[str] = []
    try:
        how = _howto(rec, ctx)
        if how:
            lines.append(f"- **怎么核对**：{how}")
            meta["filled"].append("howto")
        if be != DEFAULT_BACKEND and lines:
            joined = "\n".join(lines)
            joined, info = _polish(joined, be)
            meta.update(info)
            lines = joined.split("\n")
    except Exception as e:                                      # noqa: BLE001
        meta.update({"mode": "fallback", "reason": f"{type(e).__name__}: {e}"})
    if lines and rec.get("advice"):
        lines += [""]
    if rec.get("advice"):
        lines += [f"> 规则库口径：{rec['advice']}"]
    return lines, meta


def compose(failure, repair=None, backend: str | None = None) -> tuple[list[str], dict]:
    """一次失败的**全部**建议段（对应《诊断报告》「需人工」若干小节）。

    返回 (lines, meta)。`meta["metas"]` 逐条记录用了哪个后端、有没有回退，
    供 `flow` 写进报告末尾 —— 报告里出现模型生成的内容必须可追溯。
    """
    ctx = extract_context(failure, repair)
    lines, metas = [], []

    # 「本次实况」单独成节：它描述的是**整次失败**，不是某条规则。
    # 挂在每条规则下面会重复 N 遍，且让人以为各条规则说的是不同的事。
    fact = _fact_line(ctx)
    if fact:
        lines += ["", "### 本次失败实况", "", f"- {fact}"]
    for rec in (repair or {}).get("advice") or []:
        seg, m = advise(rec, ctx, backend=backend)
        if not seg:
            continue
        title = _rule_title(rec.get("rule"))
        lines += ["", f"### 需人工：{title}", "",
                  f"- 原因：{rec.get('why') or '—'}",
                  f"- 依据：{rec.get('doc') or '—'}"] + seg
        metas.append(m)
    return lines, {"context": ctx, "metas": metas, "backend": backend_of(backend)}


def main():
    """手工验一把：`python -m agent.narrator`（用一条样例失败）。"""
    import json

    sample = {"code": "ASSERT_FAIL", "message": "2 项断言未过",
              "fails": ["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
              "diagnostics": {"unmatched_names": {"total_cites": ["某某新学科"]}}}
    repair = {"advice": [{"rule": "discipline_alias_map",
                          "why": "未确认规则类型（R-24）",
                          "doc": "WH-DOC-04 §6.5",
                          "advice": "请馆员核对该学科归属后，在 repair_rules.yaml 填 approved_by"}]}
    lines, meta = compose(sample, repair)
    print("\n".join(lines))
    print("\n--- meta ---")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
