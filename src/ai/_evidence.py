# -*- coding: utf-8 -*-
"""证据装配（票 02）——引擎 Result → 编号就绪的证据段（文本 + 精确格指针）。

契约：

- 输出 `chunks`（有序 `[(key, text)]`）与 `cells`（`{key: [(数字串, 工作表, 学科中文名, 期次)]}`）；
- 文本里的数字**全部来自 Result 的值/期次**（没有手写数字）；cells 由来源链直接给出——
  不再手写、不再按值猜格（登记口仍是同一套「唯一命中才到格」的兜底语义）；
- 渲染口径与 _qa v1 的台账段**逐字一致**（行为保持是票 02 的判据；v1 用例钉着）。

不 import pandas：只消费 Result 字典（值已是 float）。
"""
from __future__ import annotations

_CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}

#: 指标 → 段内显示名（沿用 qa v1 口径，不用引擎白名单里的全称）。
_CN = {
    "proximity_1pct": "接近度", "papers": "论文数", "total_cites": "总被引频次",
    "cnci": "CNCI", "threshold_1pct": "前 1% 阈值", "threshold_1permille": "前 1‰ 阈值",
    "top_papers": "顶尖论文", "rank_cn": "国内排名", "rank_intl": "国际排名",
}

#: 指标 → 数字格式：pct＝比值×100 两位小数；f2＝两位小数；rank＝「第 X 位」；其余整数。
_FMT = {"proximity_1pct": "pct", "cnci": "f2", "rank_cn": "rank", "rank_intl": "rank"}

#: 事件/整体排名表在台账里的工作表名（固定口径）。
_EVENT_SHEET = "学科进入时间"
_YND_SHEET = "云大ESI排名"


def _fmt(value, fmt):
    """台账值 → 数字串（NaN/坏 → None，不猜）。

    `pct` 只乘 100，百分号由文本拼——cells 与盾捕获的数字串（`\\d+(\\.\\d+)?`）必须同形。
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    if fmt == "pct":
        return f"{f * 100:.2f}"
    if fmt == "int":
        return f"{int(round(f))}"
    return f"{f:.2f}"


def _sheet_of(point) -> str:
    return str((point.get("source") or {}).get("origin_sheet") or "")


def _series(res):
    """`series` Result → (key, text, cells)；无点 → None。"""
    metric, disc = str(res.get("metric") or ""), str(res.get("disc") or "")
    cn, fmt = str(res.get("disc_cn") or disc), _FMT.get(metric, "int")
    cn_metric = _CN.get(metric, str(res.get("metric_cn") or metric))
    points = res.get("points") or []
    if not points:
        return None
    sheet = _sheet_of(points[0])
    parts, cells = [], []
    num_fmt = "int" if fmt == "rank" else fmt          # 排名显示「第 155 位」（v1 口径）
    for pt in points:
        v = _fmt(pt.get("value"), num_fmt)
        if v is None:
            continue
        p = str(pt.get("period"))
        if fmt == "rank":
            parts.append(f"{p} 第 {v} 位")
        elif fmt == "pct":
            parts.append(f"{p} {v}%")
        else:
            parts.append(f"{p} {v}")
        cells.append((v, sheet, cn, p))
        cells.append((p, sheet, cn, p))          # 期次标签也指到该格
    if not parts:
        return None
    n = _CN_NUM.get(len(parts), len(parts))
    key = f"台账数据·{cn}·{cn_metric}"
    text = (f"{cn} · {cn_metric}（台账《{sheet}》表，最近{n}期）："
            + "、".join(parts) + "。")
    return key, text, cells


def _events(res):
    """`events` Result → (key, text, cells)；无事件且非「一直在内」→ None。"""
    disc = str(res.get("disc") or "")
    cn = str(res.get("disc_cn") or disc)
    first = str((res.get("in_since") or {}).get(disc) or "")
    if first:
        text = (f"{cn} · 进入 ESI 前 1%（台账《{_EVENT_SHEET}》表）：自台账最早一期"
                f"（{first}）起一直在前 1% 内。")
        return f"台账数据·{cn}·进出", text, [(first, _EVENT_SHEET, cn, first)]
    events = res.get("events") or []
    if not events:
        return None
    recent = events[-4:]                          # 引擎已按时间先后排好
    latest = recent[-1]
    earlier = "、".join(f"{e['period']} {'进入' if e.get('type') == 'in' else '退出'}"
                       for e in recent[:-1])
    tail = f"；此前：{earlier}" if earlier else ""
    text = (f"{cn} · ESI 前 1% 名单的进出事件（台账《{_EVENT_SHEET}》表）："
            f"最近一次 {latest['period']} "
            f"{'进入' if latest.get('type') == 'in' else '退出'}{tail}。")
    cells = [(str(e["period"]), _EVENT_SHEET, cn, str(e["period"])) for e in recent]
    return f"台账数据·{cn}·进出", text, cells


def _overall(res):
    """`overall_rank` Result → (key, text, cells)；无行 → None。"""
    points = res.get("points") or []
    parts, cells = [], []
    for pt in points:
        p = str(pt.get("period"))
        intl = _fmt(pt.get("rank_intl"), "int")
        if intl is None:
            continue
        cn_ = _fmt(pt.get("rank_cn"), "int")
        uni = _fmt(pt.get("rank_cn_uni"), "int")
        seg = f"{p}：国际排名 {intl} 位"
        cells.append((p, _YND_SHEET, "云南大学", p))
        for v, name in ((cn_, "国内排名"), (uni, "国内高校排名")):
            if v is not None:
                seg += f"、{name} {v} 位"
                cells.append((v, _YND_SHEET, "云南大学", p))
        parts.append(seg)
        cells.append((intl, _YND_SHEET, "云南大学", p))
    if not parts:
        return None
    n = _CN_NUM.get(len(parts), len(parts))
    text = (f"云南大学 · 整体排名（台账《{_YND_SHEET}》表，按时间先后，共{n}期）："
            + "；".join(parts) + "。")
    return "台账数据·云大排名", text, cells


#: kind → 渲染器（引擎白名单里的 kind 子集；其余 kind 不进证据）。
_RENDERERS = {"series": _series, "events": _events, "overall_rank": _overall}


def assemble(results, question="") -> dict:
    """Result 列表 → Evidence：`{"chunks": [(key, text)], "cells": {key: [(值串, 表, 学科, 期次)]}}`。"""
    chunks, cells = [], {}
    for res in results or []:
        if not isinstance(res, dict):
            continue
        render = _RENDERERS.get(str(res.get("kind") or ""))
        if render is None:
            continue
        out = render(res)
        if out is None:
            continue
        key, text, cs = out
        chunks.append((key, text))
        cells[key] = cs
    return {"chunks": chunks, "cells": cells}
