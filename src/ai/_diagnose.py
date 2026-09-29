# -*- coding: utf-8 -*-
"""diagnose 构建器：把 `agent/narrator.py` 的规则拼装搬进 AI 层（SPEC §4 步骤 1）。

迁移纪律：**rule 输出与旧版逐字一致**（金样见 `tests/fixtures/ai/diagnose_rule_*.txt`），
并给每个数字登记来源指针（failure#字段 / 规则库原文）。

本文件只做「失败上下文 → 分段文本 + 每个数字的来源标注」：
不碰模型、不碰盾、不碰留痕；「怎么核对」的动作模板仍归规则库管
（别在这里重写动作说明，否则规则改了报告不变）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 模板里允许被填的占位符。**只认这些** —— 规则库里 `{工作表名: 行号}` 这类
#: 字面示例必须原样保留，所以这里不能用 `str.format`。
_PH = re.compile(r"\{(sheet|metric|period|expect|actual|missing|names)\}")

_PERIOD = re.compile(r"(?<!\d)(20\d{4})(?!\d)")
_EXPECT = re.compile(r"=(\d+)\s*(?:\(|（|$)")
_ACTUAL = re.compile(r"实际\s*(\d+)")
_MISSING = re.compile(r"缺\s*(\[[^\]]*\])")
_METRIC = re.compile(r"宽表\s+([A-Za-z_]\w*)")
# ⚠ 「新国际排名」必须排在「国际排名」前面，否则后者会先命中、把「新」吃掉。
_SHEET = re.compile(r"(新国际排名|新国内排名|国际排名|国内排名|进入前1%矩阵|"
                    r"云大ESI排名|千分之一阈值|省高校表|顶尖论文合计)")

RULE_FILE = "src/agent/rules/repair_rules.yaml"

#: 失败回执里各字段的人话标签（sources.label 用）。
_FAIL_LABELS = {
    "period": "失败回执 · 期次",
    "expect": "失败回执 · 期望值",
    "actual": "失败回执 · 实际值",
    "missing": "失败回执 · 缺失项",
    "names": "失败回执 · 认不出的名字",
    "message": "失败回执 · 错误说明",
}

NONE = {"src": "none"}


def rule_kind(rule_id):
    return {"src": "rule", "rule": rule_id}


@dataclass
class Part:
    """一个可独立成段的构建结果；`kinds[i]` 描述 `lines[i]` 的数字来源规则。"""

    name: str
    lines: list[str] = field(default_factory=list)
    kinds: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 上下文
def _sheet_of_metric(metric):
    """宽表指标名（total_cites）→ 台账工作表中文名（总被引）。

    反查表在 `parse_ledger.WIDE_METRIC`（唯一事实源）。取不到返回 None ——
    宁可报告里少一句，也不维护第二份映射（会漂移）。
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


def extract_context(failure, repair=None) -> dict:             # noqa: ARG001
    """从一次失败里抽出拼装所需的上下文。**只读** `failure` 已有字段。

    抽不到就是 None —— 调用方按"缺则降级"处理，绝不拿默认值编一句出来。
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
    # 断言消息里未必带期次，但 `run_parse` 一定会在 ToolError 上挂 period。
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


def _join_bits(bits):
    """把若干「位」（每位的分段列表 [(text, spans)]）用 `，` 连成一句。

    spans 随拼接位移（失败回执字段 → 字符区间），供来源标注逐次命中。
    """
    text = ""
    spans = []
    for i, segs in enumerate(bits):
        if i:
            text += "，"
        for s, sp in segs:
            base = len(text)
            text += s
            for a, b, key in sp:
                spans.append((base + a, base + b, key))
    return text, spans


def _fact_line_traced(ctx):
    """「本次实况」一句话 + 值区间。缺关键项就整句不给（与旧版逐字一致）。"""
    bits = []
    if ctx.get("period"):
        p = str(ctx["period"])
        bits.append([(p, [(0, len(p), "period")]), (" 期", [])])
    if ctx.get("sheet"):
        bits.append([(f"「{ctx['sheet']}」", [])])
    elif ctx.get("metric"):
        bits.append([(f"宽表 {ctx['metric']}", [])])
    if ctx.get("expect") and ctx.get("actual"):
        e, a = str(ctx["expect"]), str(ctx["actual"])
        bits.append([("期望 ", []), (e, [(0, len(e), "expect")]),
                     ("、实际 ", []), (a, [(0, len(a), "actual")])])
    if ctx.get("missing"):
        m = str(ctx["missing"])
        bits.append([("缺 ", []), (m, [(0, len(m), "missing")])])
    if ctx.get("names"):
        n = ctx["names"]
        bits.append([("认不出来的名字：", []), (n, [(0, len(n), "names")])])
    if not bits:
        return None, []
    text, spans = _join_bits(bits)
    return text + "。", spans


def _fill_traced(tpl, ctx):
    """填充模板，**按句降级**（与旧 `_fill` 逐字一致），并记录被填值的字符区间。"""
    if not tpl:
        return None, []
    kept = []
    spans = []
    pos = 0
    for line in str(tpl).splitlines():
        line = line.strip()
        if not line:
            continue
        used = set(_PH.findall(line))
        if any(not ctx.get(k) for k in used):
            continue                        # 缺上下文 → 丢这一句，别硬造半截指引
        out = []
        cursor = 0
        for m in _PH.finditer(line):
            out.append(line[cursor:m.start()])
            val = str(ctx[m.group(1)])
            start = pos + sum(len(x) for x in out)
            spans.append((start, start + len(val), m.group(1)))
            out.append(val)
            cursor = m.end()
        out.append(line[cursor:])
        piece = "".join(out)
        kept.append(piece)
        pos += len(piece)
    if not kept:
        return None, []
    return "".join(kept), spans


def _rule_title(rule_id) -> str:
    """`discipline_alias_map` → `学科名别名映射（discipline_alias_map）`。"""
    if not rule_id:
        return "规则库"
    try:
        from agent import heal                                   # noqa: PLC0415
        r = heal.rule_by_id(rule_id)
    except Exception:                                            # noqa: BLE001
        r = None
    name = (r or {}).get("name")
    return f"{name}（{rule_id}）" if name else str(rule_id)


def _howto_traced(rec, ctx):
    """取规则库 `howto` 填上下文。返回 (文本, 值区间)；规则库没写 howto → (None, [])。"""
    try:
        from agent import heal                                   # noqa: PLC0415
        rule = heal.rule_by_id(rec.get("rule")) if rec.get("rule") else None
    except Exception:                                            # noqa: BLE001
        rule = None
    tpl = (rule or {}).get("howto") or rec.get("howto")
    return _fill_traced(tpl, ctx)


# ---------------------------------------------------------------- 组装
def _advice_part(rec, ctx):
    """一条「需人工」的记录 → Part（与旧 `compose` 逐条拼接逐字一致）。"""
    rule_id = rec.get("rule")
    how, spans = _howto_traced(rec, ctx)
    adv = rec.get("advice")
    if not how and not adv:
        return None

    lines = ["", f"### 需人工：{_rule_title(rule_id)}", "",
             f"- 原因：{rec.get('why') or '—'}",
             f"- 依据：{rec.get('doc') or '—'}"]
    kinds = [NONE, rule_kind(rule_id), NONE, rule_kind(rule_id), rule_kind(rule_id)]
    if how:
        prefix = "- **怎么核对**："
        lines.append(prefix + how)
        kinds.append({"src": "howto", "rule": rule_id,
                      "spans": [(len(prefix) + a, len(prefix) + b, k) for a, b, k in spans]})
    if how and adv:
        lines.append("")
        kinds.append(NONE)
    if adv:
        lines.append(f"> 规则库口径：{adv}")
        kinds.append(rule_kind(rule_id))
    return Part(name=f"需人工：{_rule_title(rule_id)}", lines=lines, kinds=kinds)


def build(root, period, payload):                              # noqa: ARG001
    """诊断构建器入口：失败回执 → RuleDraft（规则版 + 逐数字来源 + 外发面）。

    `root` / `period` 对诊断无意义（只吃 payload 里的失败回执），签名与其它构建器对齐。
    """
    from . import _shield                                          # noqa: PLC0415
    from ._draft import RuleDraft                                  # noqa: PLC0415
    from ._types import Source                                     # noqa: PLC0415

    parts = _parts(payload.get("failure"), payload.get("repair"))
    rule_text = "\n".join(ln for p in parts for ln in p.lines)
    protected_text, mapping = _shield.protect(rule_text)
    sources = []
    for part in parts:
        for line, kind in zip(part.lines, part.kinds):
            for m in _shield.NUM.finditer(line):
                k = str(len(sources) + 1)
                skind, pointer, label, detail = attribute(kind, m.start(), m.group(0))
                sources.append(Source(index=int(k), kind=skind, pointer=pointer,
                                      label=label, detail=detail,
                                      value=mapping.get(k, m.group(0))))
    return RuleDraft(rule_text=rule_text, rule_protected=protected_text, mapping=mapping,
                     sources=tuple(sources), parts=tuple(parts), task=protected_text,
                     evidence=(), fact_keys=frozenset(range(1, len(mapping) + 1)))


def _parts(failure, repair=None):
    """一次失败的**全部**建议段。返回 parts；可空（无可说）。"""
    ctx = extract_context(failure)
    parts = []
    fact, spans = _fact_line_traced(ctx)
    if fact:
        parts.append(Part(
            name="本次失败实况",
            lines=["", "### 本次失败实况", "", f"- {fact}"],
            kinds=[NONE, NONE, NONE,
                   {"src": "failure", "rule": None, "fallback": "message",
                    "spans": [(2 + a, 2 + b, k) for a, b, k in spans]}]))
    for rec in (repair or {}).get("advice") or []:
        part = _advice_part(rec, ctx)
        if part:
            parts.append(part)
    return parts


def attribute(kind, pos, value) -> tuple:
    """一个数字出现位置的来源：返回 (kind, pointer, label, detail)。"""
    for a, b, key in kind.get("spans") or []:
        if a <= pos < b:
            return ("failure", f"failure#{key}",
                    _FAIL_LABELS.get(key, "失败回执"),
                    f"本次失败回执字段 {key}")
    if kind.get("src") in ("rule", "howto"):
        rid = kind.get("rule") or "static"
        return ("fact", f"{RULE_FILE}#{rid}", f"规则库原文 · {rid}",
                "规则库 repair_rules.yaml（馆员口径）")
    if kind.get("src") == "failure":
        key = kind.get("fallback") or "message"
        return ("failure", f"failure#{key}", _FAIL_LABELS.get(key, "失败回执"),
                f"本次失败回执字段 {key}")
    return ("fact", f"{RULE_FILE}#static", "规则库原文", "规则库 repair_rules.yaml（馆员口径）")
