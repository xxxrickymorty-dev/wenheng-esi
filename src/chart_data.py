# -*- coding: utf-8 -*-
"""图册图表数据导出（同源口径）：**画了什么就导什么**。

背景（2026-10-28 方案 A 试点，rick 选定）：前端图册要换 ECharts 交互版，
但报告 PNG 是权威产物——多一套渲染**不能**多一套算法，否则「前端看到的」和
「报告里的」会各说各话。本模块因此不自己算任何数字：窗口取 `period.filled`、
期次交集取 `charts._avail`、×100 与画图函数同款，输入就是 `render_all` 喂给
画图函数的同一批台账宽表。报告 PNG 路径一个字节不动。

v1 只导「国际／国内排名百分位」双折线（`rank_pct` 键）；其余图型按
「新增一个 build_* + 多一个导出键」的节奏扩，键名与 `out/<期次>/charts/`
里的 PNG 文件名对应（rank_pct.png → rank_pct）。

服务端（`/api/periods/<p>/charts-data`，待 server/routes 重构落地后挂）现读
现算即可：台账宽表几 MB，无状态、无缓存一致性问题。
"""
from __future__ import annotations

import pathlib

import pandas as pd

import charts
import period as period_mod

SCHEMA = 1

RANK_SERIES = (           # 键 → 画图函数里的 label（与 PNG 图例逐字一致）
    ("intl", "国际排名百分位值"),
    ("cn", "国内排名百分位值"),
)


def _window(ledger_dir: pathlib.Path, end_period, n_periods: int) -> list[str]:
    """与 `charts.render_all` 同一条窗口口径：当期往前 n_periods 期（含当期）。"""
    total_cites = pd.read_parquet(ledger_dir / "wide" / "total_cites.parquet")
    filled = period_mod.filled({"total_cites": total_cites})
    end_period = end_period or charts._infer_end_period(ledger_dir)
    if end_period:
        filled = [c for c in filled if c <= str(end_period)]
    return filled[-n_periods:]


def rank_pct_payload(rank_intl: pd.DataFrame, rank_cn: pd.DataFrame,
                     periods: list[str]) -> dict:
    """双折线数据：每学科＝台账 rank_pct ×100（与 `chart_rank_pct` 同一变换）。

    期次交集用 `charts._avail`（只留该学科两条序列确有列的期次），NaN 出 null
    ——画图函数画的就是这些点，前端拿到的必须是同一批。
    """
    out = {}
    for disc in charts.DETAIL_TABLES:
        if disc not in rank_intl.index:
            continue
        avail = charts._avail(rank_intl, periods)     # 与 chart_rank_pct 同一交集

        def ser(df: pd.DataFrame) -> list:
            s = df.loc[disc, avail].astype(float) * 100
            return [None if pd.isna(v) else float(v) for v in s]

        out[disc] = {
            "name_cn": charts._cn(disc),
            "periods": avail,
            "series": {key: ser(piv) for key, piv in
                       (("intl", rank_intl), ("cn", rank_cn))},
            "labels": {key: lab for key, lab in RANK_SERIES},
        }
    return out


def build(ledger_dir="out/202607", end_period=None, n_periods=7) -> dict:
    """整包导出：现读台账宽表，返回可直接 JSON 化的 dict（不落盘、不动 out/）。"""
    ledger_dir = pathlib.Path(ledger_dir)
    periods = _window(ledger_dir, end_period, n_periods)
    longdf = pd.read_parquet(ledger_dir / "ledger_long.parquet")
    piv = {}
    for source in ("rank_intl", "rank_cn"):
        d = longdf[(longdf.source == source) & (longdf.metric == "rank_pct")]
        piv[source] = d.pivot(index="discipline", columns="period", values="value")
    return {
        "schema": SCHEMA,
        "end_period": periods[-1] if periods else None,
        "periods": periods,
        "rank_pct": rank_pct_payload(piv["rank_intl"], piv["rank_cn"], periods),
    }
