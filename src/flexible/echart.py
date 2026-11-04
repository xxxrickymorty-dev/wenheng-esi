# -*- coding: utf-8 -*-
"""图表 ECharts 化（2026-11-04，rick：把 数学稿 的图表观感模板化）。

`数学.html`（202609 数学）证明了观感上限：Apache ECharts 内联、
MONO 灰阶（实线＝实测 / 虚线＝阈值对标）、endLabel 大数、dotted 网格。
本模块把这套观感**模板化**进产线：

- **数据层**（本文件）：按图型从台账 parquet 取点，产出**纯数据 payload**
  （categories + series + 语义标记）。🔴 payload 结构上**没有轴范围字段**
  ——与 `spec.py` 同一条红线：轴范围由数据决定，渲染层用 ECharts
  `scale:true` 自适应，不写 min/max。
- **渲染层**（`mdview.py` 内嵌 JS）：把 payload 转成 ECharts option，
  样式常量与数学稿逐字一致。

PNG 产线原样保留（docx 仍用 PNG；`spec.make` 不动）——ECharts 只替换
**HTML 出口**（`mdview.standalone` 与下载口即时升级）。
"""
from __future__ import annotations

import pathlib

import pandas as pd

from . import spec as sp

#: MONO 色板（与数学稿一致；渲染层再引用，这里只做常量出处）
PALETTE = {"ink": "#1C1C1A", "muted": "#8F8E88",
           "faint": "#C6C5BF", "grid": "#DEDDD6"}


def _series_vals(tbl: pd.DataFrame, disc: str, periods: list[str]) -> list:
    row = tbl.loc[disc, periods].astype(float)
    return [None if pd.isna(v) else round(float(v), 4) for v in row]


#: 🔴 内嵌 payload 也要过的红线：轴范围字段（前缀匹配）一律拒收
_FORBIDDEN_STEMS = ("min", "max", "scale")


def _axis_guard(p, depth: int = 0):
    """跨校对比图的内嵌 payload 过同一道红线：带轴范围字段 → None。

    递归检查嵌套 dict（yaxis.min 这类藏一层也不行）；payload 是
    浅结构，深度保险丝只是防御。
    """
    if depth > 6 or not isinstance(p, dict):
        return None
    for k in p:
        if any(str(k).lower().startswith(s) for s in _FORBIDDEN_STEMS):
            return None
    for v in p.values():
        if isinstance(v, dict) and _axis_guard(v, depth + 1) is None:
            return None
        if isinstance(v, list):
            for x in v:
                if isinstance(x, dict) and _axis_guard(x, depth + 1) is None:
                    return None
    return p


def payload_for(chart: dict, ld) -> dict | None:
    """chart（`spec.make` 返回 dict 或 flex_sources.json 的 chart 条目）→
    ECharts 数据 payload；不支持的图型返回 None。

    🔴 数据语义与 `charts.py` 各图函数逐点对齐（同一张表、同一个窗口、
    同一种差分/百分位换算）——两条出口呈现同一份数据。
    """
    # 跨校对比图：数据 payload 在取数时已随账本走（无台账查询链），
    # 这里只过红线守卫后原样带回。
    if chart.get("payload") is not None:
        return _axis_guard(chart["payload"])
    kind = chart.get("chart_kind") if chart.get("kind") == "chart" else chart.get("kind")
    spec = chart.get("spec") or {}
    disc = spec.get("disc") or (chart.get("source") or {}).get("discipline")
    periods = [str(p) for p in chart.get("periods") or []]
    if not periods:
        return None
    ld = pathlib.Path(ld)

    try:
        if kind in ("cites_threshold", "cites_permille"):
            thr_name = "threshold_1pct" if kind == "cites_threshold" else "threshold_1permille"
            thr_cn = "ESI 前 1% 阈值" if kind == "cites_threshold" else "ESI 前 1‰ 阈值"
            cites = sp._t(ld, "total_cites")
            thr = sp._t(ld, thr_name)
            periods = [p for p in periods if p in cites.columns]
            if not periods or disc not in cites.index:
                return None
            return {
                "kind": kind, "type": "line", "cats": periods,
                "series": [
                    {"name": "被引频次", "data": _series_vals(cites, disc, periods), "dash": False},
                    {"name": thr_cn, "data": _series_vals(thr, disc, periods), "dash": True},
                ],
                "fmt": "int",
            }

        if kind == "cnci":
            tbl = sp._t(ld, "cnci")
            periods = [p for p in periods if p in tbl.columns]
            if not periods or disc not in tbl.index:
                return None
            return {
                "kind": kind, "type": "line", "cats": periods,
                "series": [{"name": "CNCI", "data": _series_vals(tbl, disc, periods), "dash": False}],
                "markline": {"value": 1.0, "label": "全球平均 1.0"},
                "fmt": "dec3",
            }

        if kind == "rank_pct":
            ri = sp._t(ld, "rank_intl")
            rc = sp._t(ld, "rank_cn")
            periods = [p for p in periods if p in ri.columns]
            if not periods or disc not in ri.index:
                return None
            # 与 charts.chart_rank_pct 同口径：值 ×100 变百分位
            iv = [round(v * 100, 2) for v in _series_vals(ri, disc, periods)]
            cv = [round(v * 100, 2) for v in _series_vals(rc, disc, periods)]
            return {
                "kind": kind, "type": "line", "cats": periods,
                "series": [
                    {"name": "国际排名百分位", "data": iv, "dash": False},
                    {"name": "国内排名百分位", "data": cv, "dash": True},
                ],
                "invert": True, "fmt": "pct2",
            }

        if kind == "papers_delta":
            tbl = sp._t(ld, "papers")
            # 窗口含「外上一期」做差分（与 spec.make 的 extra 一致）
            ps = [p for p in periods if p in tbl.columns]
            if len(ps) < 2 or disc not in tbl.index:
                return None
            v = tbl.loc[disc, ps].astype(float)
            d = v.diff().iloc[1:]
            ps = ps[1:]
            return {
                "kind": kind, "type": "bar", "cats": ps,
                "series": [{"name": "新增发文量",
                            "data": [None if pd.isna(x) else float(x) for x in d],
                            "dash": False}],
                "fmt": "int",
            }

        if kind == "top_papers":
            tbl = sp._t(ld, "top_papers")
            periods = [p for p in periods if p in tbl.columns]
            if not periods or disc not in tbl.index:
                return None
            v = tbl.loc[disc, periods].fillna(0).astype(float)
            return {
                "kind": kind, "type": "bar", "cats": periods,
                "series": [{"name": "顶尖论文量",
                            "data": [float(x) for x in v], "dash": False}],
                "fmt": "int",
            }

        if kind == "q_dist":
            q = sp._t(ld, "q1q4")
            period = periods[-1]
            qkey = f"{period[:4]}.{period[4:]}"
            ents = [("云南大学", False), ("中国大陆", True), ("全球", True)]
            series = []
            for ent, dash in ents:
                s = q[(q.discipline == disc) & (q.entity == ent) & (q.quarter == qkey)]
                row = [float(s[c].iloc[0]) if len(s) and pd.notna(s[c].iloc[0]) else None
                       for c in ("q1", "q2", "q3", "q4")]
                series.append({"name": ent, "data": row, "dash": dash})
            return {
                "kind": kind, "type": "bar", "cats": ["Q1", "Q2", "Q3", "Q4"],
                "series": series, "fmt": "int",
            }
    except Exception:
        # 数据不可得（旧稿缺表等）→ 回落 PNG，绝不编数据
        return None
    return None


def payloads_for(charts: list[dict], ld) -> dict[str, dict]:
    """一批 chart dict → {png 文件名: payload}（供 mdview 替换 <img>）。

    同时兼容生成期（`path`）与 flex_sources.json（`file`）两种形状。
    """
    out: dict[str, dict] = {}
    for ch in charts or []:
        if not isinstance(ch, dict):
            continue
        name = ch.get("path") or ch.get("file")
        if not name:
            continue
        p = payload_for(ch, ld)
        if p is not None:
            out[pathlib.Path(name).name] = p
    return out
