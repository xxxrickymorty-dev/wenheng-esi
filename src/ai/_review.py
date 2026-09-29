# -*- coding: utf-8 -*-
"""review 构建器（复核参谋；票 09 / SPEC §4 步骤 3 的 review 半边）。

只读三样产物：红件清单 `red_slots.json`、校验结果 `meta.json.assertions`、
缺失项 `meta.json.missing`——机器能给的是「核哪一处、依据是什么、风险多高」；
**不代签、不改稿**（采纳/忽略只是界面指引，由 server 自己存）。

风险序是确定的：待人工 → 校验未过 → 数据类红件（台账/大表/人工原件/预测模型）→
版式类（模板/句骨架/期次参数）。模型轮只做「组织语言 + 排序」，看不见任何数字；
清单里的每个数字都指向它出处的红件条目或校验结果（product 指针）。
"""
from __future__ import annotations

import json
import pathlib

from ._draft import Part, RuleDraft, assemble_parts, fixed

TOP_N = 6               # 「先看这几条」最多几条
LIST_MAX = 8            # 名单类分段最多列几条
GROUP_MAX = 8           # 概览最多几类

TASK = ("下面是一期报告的机器复核清单。请把它整理成给馆员的核对建议：按风险从高到低排序，"
        "先说清先看哪几条；引用清单里的数字时保留 [[n]] 标记（原样、每个至多一次）；"
        "严禁新增任何数字；保留结尾的边界说明。")

_CLASS_ORDER = ("台账/上游数据", "大表（table2.csv）", "人工原件名单", "预测模型",
                "模板槽位", "句骨架", "期次参数", "其它")

_BLANK = fixed("product", "red_slots.json", "红件清单")


def _load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _classify(source: str) -> str:
    s = source or ""
    if "table2.csv" in s:
        return "大表（table2.csv）"
    if "人工原件" in s:
        return "人工原件名单"
    if "期次参数" in s:
        return "期次参数"
    if "sentences" in s:
        return "句骨架"
    if "report_forecast" in s:
        return "预测模型"
    if "fill_docx" in s or "模板" in s:
        return "模板槽位"
    if any(x in s for x in ("xlsx", "parquet", "宽表", "数据覆盖", "ESI数据", "csv")):
        return "台账/上游数据"
    return "其它"


def _slot_line(r) -> str:
    return f"{r.get('location') or '（未标位置）'}：{r.get('old') or '—'} → {r.get('new') or '—'}"


def _slot_kind(i: int, r) -> dict:
    return fixed("product", f"red_slots.json#{i}",
                 f"红件 · {r.get('location') or '（未标位置）'}",
                 f"来源：{r.get('source') or '—'}")


def _manual_part(manual) -> Part:
    lines = ["", "### 待人工", ""]
    kinds = [_BLANK, _BLANK, _BLANK]
    if not manual:
        lines.append("- 本次没有待人工项。")
        kinds.append(_BLANK)
    else:
        for i, r in manual[:LIST_MAX]:
            lines.append(f"- {_slot_line(r)}")
            kinds.append(_slot_kind(i, r))
        if len(manual) > LIST_MAX:
            lines.append(f"- 另有 {len(manual) - LIST_MAX} 处未列出，见红件清单。")
            kinds.append(_BLANK)
    return Part("待人工", lines, kinds)


def _assert_part(assertions, meta) -> Part:
    total = len(meta.get("assertions") or [])
    lines = ["", "### 校验未过", ""]
    kinds = [_BLANK, _BLANK, _BLANK]
    if not assertions:
        lines.append(f"- 本期 {total} 项校验全部通过。")
        kinds.append(_BLANK)
    else:
        for a in assertions[:LIST_MAX]:
            text = a[1] if isinstance(a, (list, tuple)) and len(a) > 1 else str(a)
            lines.append(f"- {text}")
            kinds.append(fixed("product", "meta.json#assertions", "校验结果",
                               "meta.json assertions（未过项）"))
    return Part("校验未过", lines, kinds)


def _overview_part(red, ordered_classes) -> Part:
    lines = ["", "### 红件概览", ""]
    kinds = [_BLANK, _BLANK, _BLANK]
    for c in ordered_classes[:GROUP_MAX]:
        n = len(by_class_of(red, c))
        lines.append(f"- {c}：{n} 处")
        kinds.append(_BLANK)
    if len(ordered_classes) > GROUP_MAX:
        lines.append(f"- 另有 {len(ordered_classes) - GROUP_MAX} 类未列出。")
        kinds.append(_BLANK)
    return Part("红件概览", lines, kinds)


def by_class_of(red, cls):
    return [(i, r) for i, r in enumerate(red) if _classify(str(r.get("source") or "")) == cls]


def _top_part(manual, assertions, red, ordered_classes) -> Part:
    picks = []                       # [(line, kind)]
    for i, r in manual:
        if len(picks) >= TOP_N:
            break
        picks.append((f"{len(picks) + 1}. 【待人工】{_slot_line(r)}", _slot_kind(i, r)))
    for a in assertions:
        if len(picks) >= TOP_N:
            break
        text = a[1] if isinstance(a, (list, tuple)) and len(a) > 1 else str(a)
        picks.append((f"{len(picks) + 1}. 【校验未过】{text}",
                      fixed("product", "meta.json#assertions", "校验结果",
                            "meta.json assertions（未过项）")))
    for c in ordered_classes:
        if c in ("句骨架", "期次参数", "模板槽位"):
            continue
        for i, r in by_class_of(red, c):
            if len(picks) >= TOP_N:
                break
            picks.append((f"{len(picks) + 1}. 【{c}】{_slot_line(r)}", _slot_kind(i, r)))
        if len(picks) >= TOP_N:
            break
    lines = ["", "### 先看这几条", ""]
    kinds = [_BLANK, _BLANK, _BLANK]
    if not picks:
        lines.append("- 没有需要优先核对的条目。")
        kinds.append(_BLANK)
    else:
        for ln, kd in picks:
            lines.append(ln)
            kinds.append(kd)
    return Part("先看这几条", lines, kinds)


def _remind_part(red, ordered_classes, missing) -> Part:
    lines = ["", "### 漏检提醒", ""]
    kinds = [_BLANK, _BLANK, _BLANK]
    for c in ("人工原件名单", "期次参数", "预测模型"):
        if c in ordered_classes:
            n = len(by_class_of(red, c))
            lines.append(f"- {c}：{n} 处来自人工环节，机器没有可直接判定的校验，建议照原件再核。")
            kinds.append(_BLANK)
    if missing:
        lines.append(f"- 本期缺项 {len(missing)} 处：{'、'.join(missing[:5])}")
        kinds.append(fixed("product", "meta.json#missing", "缺失项", "meta.json missing"))
    if len(lines) == 3:
        lines.append("- 机器能核的都已核过；仍建议抽查大表首尾行与正文数字。")
        kinds.append(_BLANK)
    return Part("漏检提醒", lines, kinds)


def _boundary_part() -> Part:
    return Part("边界", ["", "### 边界", "",
                         "- 以上只是核对指引；采纳或忽略都不会代签、不会改稿。"],
                [_BLANK, _BLANK, _BLANK, _BLANK])


def build(root, period, payload) -> RuleDraft:                # noqa: ARG001
    d = pathlib.Path(root) / str(period)
    red = _load_json(d / "red_slots.json")
    if not isinstance(red, list) or not red:
        raise FileNotFoundError(f"该期没有可用的 red_slots.json：{d}")
    meta = _load_json(d / "meta.json", default={}) or {}
    assertions = [a for a in (meta.get("assertions") or [])
                  if not (isinstance(a, (list, tuple)) and a and a[0] == "PASS")]
    missing = [str(x) for x in (meta.get("missing") or [])]

    manual = [(i, r) for i, r in enumerate(red) if "【手工" in str(r.get("new", ""))]
    ordered_classes = [c for c in _CLASS_ORDER
                       if any(_classify(str(r.get("source") or "")) == c for r in red)]

    parts = [
        _top_part(manual, assertions, red, ordered_classes),
        _manual_part(manual),
        _assert_part(assertions, meta),
        _overview_part(red, ordered_classes),
        _remind_part(red, ordered_classes, missing),
        _boundary_part(),
    ]
    rule_text, protected, mapping, sources = assemble_parts(parts)
    return RuleDraft(rule_text=rule_text, rule_protected=protected, mapping=mapping,
                     sources=sources, parts=tuple(parts), task=TASK,
                     evidence=(protected,),
                     fact_keys=frozenset(range(1, len(mapping) + 1)))
