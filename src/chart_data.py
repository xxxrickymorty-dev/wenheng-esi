# -*- coding: utf-8 -*-
"""图册图表数据导出（同源口径）：**画了什么就导什么**。

背景（2026-10-28 rick 裁决：前端全部图表换 ECharts）：报告 PNG 仍是权威产物，
多一套渲染**不能**多一套算法，否则「前端看到的」和「报告里的」会各说各话。
本模块因此不自己算任何数字——窗口取 `period.filled`、期次交集取 `charts._avail`、
差分/占比/合并「其他」等变换全部照抄对应画图函数的原口径；报告 PNG 路径一个字节不动。

键名与 `out/<期次>/charts/` 里的 PNG 文件名对应（`q_dist.png` → `q_dist`），
学科分组键＝目录名（`_slug` 压缩后的英文名）。`_overview` 下含概览 8 张与预测图
（预测图序列来自 `report_forecast` 出图时写进 `forecast_charts.json` 的 `series`，
老期次没这个字段 → 缺键，前端回退 PNG）。

服务端 `/api/periods/<p>/charts-data` 现读现算即可：台账宽表几 MB，无状态、无缓存一致性问题。
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd

import charts
import college_stats
import period as period_mod

SCHEMA = 2

RANK_SERIES = (           # 键 → 画图函数里的 label（与 PNG 图例逐字一致）
    ("intl", "国际排名百分位值"),
    ("cn", "国内排名百分位值"),
)

RANK_TABLE_SERIES = (     # 键 →（label, 颜色）＝ chart_rank_table 的三条线
    ("cn", "国内排名", "#ED7D31"),
    ("cn_uni", "国内高校排名", "#FFC000"),
    ("intl", "国际排名（右标）", "#4472C4"),
)

TREND_COLORS = (charts.C_LIGHTBLUE, "#7030A0", "#8C8C8C", "#FFC000")  # chart_trend_table 同款


def _num(v) -> float | None:
    """浮点或 None：NaN → null。保留原始浮点（画图函数收到的就是它，前端只做格式化）。"""
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    return float(v)


def _nums(seq) -> list:
    return [_num(v) for v in seq]


def _filled(ledger_dir: pathlib.Path, end_period) -> list[str]:
    """当期（含）之前的全部有效期次，升序——`render_all` 的窗口与差分基期都从这里切。"""
    total_cites = pd.read_parquet(ledger_dir / "wide" / "total_cites.parquet")
    filled = period_mod.filled({"total_cites": total_cites})
    end_period = end_period or charts._infer_end_period(ledger_dir)
    if end_period:
        filled = [c for c in filled if c <= str(end_period)]
    return filled


# ---------- 逐学科六图 ----------

def rank_pct_payload(rank_intl: pd.DataFrame, rank_cn: pd.DataFrame,
                     periods: list[str]) -> dict:
    """双折线：台账 rank_pct ×100（`chart_rank_pct` 同一变换）。"""
    out = {}
    for disc in charts.DETAIL_TABLES:
        if disc not in rank_intl.index:
            continue
        avail = charts._avail(rank_intl, periods)     # 与 chart_rank_pct 同一交集

        def ser(df: pd.DataFrame) -> list:
            return _nums(df.loc[disc, avail].astype(float) * 100)

        out[disc] = {
            "name_cn": charts._cn(disc),
            "periods": avail,
            "series": {key: ser(piv) for key, piv in
                       (("intl", rank_intl), ("cn", rank_cn))},
            "labels": {key: lab for key, lab in RANK_SERIES},
        }
    return out


def _per_discipline(wide: dict, periods: list[str], delta_p: list[str],
                    P: str) -> dict:
    """五个逐学科图型的导出（rank_pct 另走独立函数，q_dist 只取当期快照）。

    `delta_p`＝窗口外多带一期的列（`render_all` 给新增发文量图就是传它——
    差分吃掉首期，7 根柱得有 8 期底料）。
    """
    avail = {m: charts._avail(wide[m], periods) for m in
             ("cnci", "total_cites", "threshold_1pct", "top_papers")}
    avail["papers"] = charts._avail(wide["papers"], delta_p)

    def per_disc(disc: str) -> dict:
        row = {"name_cn": charts._cn(disc)}
        # C2 CNCI：原始值 + 1.0 国际均值基准线（chart_cnci 口径）
        if disc in wide["cnci"].index:
            row["cnci"] = {"periods": avail["cnci"],
                           "values": _nums(wide["cnci"].loc[disc, avail["cnci"]]),
                           "baseline": 1.0}
        # C3 新增发文量：相邻期差分，首期作差分基期被吃掉（chart_papers_delta 口径）
        if disc in wide["papers"].index:
            ps = avail["papers"]
            v = wide["papers"].loc[disc, ps].astype(float)
            d = v.diff().iloc[1:] if len(ps) > 1 else v.iloc[0:0]
            row["papers_new"] = {"periods": ps[1:], "values": _nums(d)}
        # C4 被引频次与 1% 阈值：两条原始序列（chart_cites_threshold 口径）
        if disc in wide["total_cites"].index:
            row["cites_threshold"] = {
                "periods": avail["total_cites"],
                "cites": _nums(wide["total_cites"].loc[disc, avail["total_cites"]]),
                "threshold": _nums(wide["threshold_1pct"].loc[disc, avail["total_cites"]])}
        # C5 顶尖论文量：缺失按 0 画（chart_top_papers 的 fillna(0)）
        if disc in wide["top_papers"].index:
            row["top_papers"] = {
                "periods": avail["top_papers"],
                "values": _nums(wide["top_papers"].loc[disc, avail["top_papers"]].fillna(0))}
        # C6 分区占比：当期快照，三实体 × Q1–Q4（chart_q_dist 口径；外显名随原件）
        row["q_dist"] = {
            "quarter": f"{P[:4]}.{P[4:]}",
            "entities": [{"key": ent, "name": lab, "color": col,
                          "values": _q_row(wide["q1q4"], disc, ent, f"{P[:4]}.{P[4:]}")}
                         for ent, lab, col in charts.Q_ENTITIES],
        }
        return row

    return {disc: per_disc(disc) for disc in charts.DETAIL_TABLES
            if disc in wide["total_cites"].index}


def _q_row(q1q4: pd.DataFrame, disc: str, ent: str, qkey: str) -> list:
    s = q1q4[(q1q4.discipline == disc) & (q1q4.entity == ent) & (q1q4.quarter == qkey)]
    return [_num(s[c].iloc[0]) if len(s) else None for c in ("q1", "q2", "q3", "q4")]


# ---------- 概览八图 ----------

def _overview_payload(wide: dict, periods: list[str], P: str, n_periods: int,
                      end_period) -> dict:
    cites, thr_p = wide["total_cites"], wide["threshold_1permille"]
    ov: dict = {}

    # 1% 接近度：紫柱＝实际、绿段＝差距（<100% 才画差距），升序（chart_overview_1pct）
    ratio = (cites[P] / wide["threshold_1pct"][P] * 100).dropna().sort_values()
    ov["1pct"] = {"items": [{"name_cn": charts._cn(d), "ratio": _num(r),
                             "gap": _num(max(0.0, 100 - float(r)))}
                            for d, r in ratio.items()]}

    # 1‰ 接近度：只画事件表已进 1% 的学科；差距＝100−ratio 不截断（chart_overview_1permille）
    entered = wide["entered_1pct"][P]
    ins = entered[entered >= 1].index
    ratio_p = (cites[P][ins] / thr_p[P][ins] * 100).dropna().sort_values()
    ov["1permille"] = {"items": [{"name_cn": charts._cn(d), "ratio": _num(r),
                                  "gap": _num(100 - float(r))}
                                 for d, r in ratio_p.items()]}

    # 排名表：三条序列原样（chart_rank_table；表由前端照数据画）
    if "ynd_rank" in wide:
        df = wide["ynd_rank"].set_index("period").sort_index()
        df = df[df["rank_intl"].notna() | df["rank_cn"].notna()]
        df = df[df.index <= str(end_period)].tail(n_periods)
        ov["rank_table"] = {
            "periods": [str(p) for p in df.index],
            "series": {key: _nums(df[col]) for key, col in
                       (("cn", "rank_cn"), ("cn_uni", "rank_cn_uni"),
                        ("intl", "rank_intl"))},
            "labels": {key: {"label": lab, "color": col} for key, lab, col in RANK_TABLE_SERIES},
        }

    # 发展趋势表：1‰ 接近度前 4 学科 + 100% 基线（chart_trend_table；口径单一来源＝trend_picks）
    picked, t_periods, picks = charts.trend_picks(
        cites, thr_p, end_period=end_period, n=n_periods,
        top_k=4, entered=wide["entered_1pct"])
    ov["trend_table"] = {
        "periods": t_periods,
        "series": [{"disc": d, "name_cn": charts._cn(d), "color": TREND_COLORS[i % 4],
                    "values": _nums(picked.loc[d])}
                   for i, d in enumerate(picks)],
        "baseline": 100.0,
    }

    # 顶尖论文年代/学科分布：当期列，去 NaN、去 0（chart_top_by_year/_subject 口径）
    by_year = wide.get("top_by_year")
    if by_year is not None:
        s = by_year[P] if P in by_year.columns else by_year.iloc[:, -1]
        s = s.dropna()
        s = s[s > 0]
        ov["top_by_year"] = {"labels": [str(i) for i in s.index],
                             "values": _nums(s)}
    top = wide["top_papers"]
    s = top[P] if P in top.columns else top.iloc[:, -1]
    s = s.dropna()
    s = s[s > 0].sort_values(ascending=False)
    ov["top_by_subject"] = {"items": [{"name_cn": charts._cn(d), "value": _num(v)}
                                      for d, v in s.items()]}

    # 学院贡献两张饼：<1.5% 合并为「其他（k 个单位）」，其他恒为中性灰（chart_college_pie 口径）
    for mode, key in (("cites", "college_cites"), ("papers", "college_papers")):
        items = _college_items(wide.get("_college_stats"), mode)
        if items is not None:
            ov[key] = {"items": items}
    return ov


def _college_items(stats, mode: str) -> list | None:
    """学院饼图条目（合并口径与 `chart_college_pie` 逐行一致）。None＝本期无学院统计。"""
    if not stats or not stats.get("units"):
        return None
    raw = [((u["cites"] if mode == "cites" else u["papers"]), u["unit"])
           for u in stats["units"]]
    total = sum(v for v, _u in raw) or 1
    TH = 0.015
    keep = [(v, u) for v, u in raw if v / total >= TH]
    small = [(v, u) for v, u in raw if v / total < TH]
    if small:
        keep.append((sum(v for v, _u in small), f"其他（{len(small)} 个单位）"))
    palette = ["#4472C4", "#70AD47", "#FFC000", "#ED7D31", "#7030A0", "#00B0F0", "#C00000",
               "#F4B183", "#8FAADC", "#C5E0B4", "#FFE699", "#B4A7D6", "#9DC3E6", "#A9D18E",
               "#D9D9D9"]
    out = []
    for i, (v, u) in enumerate(keep):
        gray = (small and i == len(keep) - 1)
        out.append({"name": u, "value": _num(v),
                    # 饼图标签的百分比也是画进 PNG 的数（v/total*100），一并导出
                    "pct": _num(v / total * 100),
                    "color": "#D9D9D9" if gray else palette[i % len(palette)]})
    return out


# ---------- 预测图（序列由 report_forecast 出图时落档，这里只搬运） ----------

def _forecast_payload(ledger_dir: pathlib.Path) -> dict:
    """`forecast_<序>_<cites|rank>` → 出图时记录的序列；老期次无 series 字段 → 跳过。"""
    mp = ledger_dir / "forecast_charts.json"
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for c in meta.get("charts", []):
        if not isinstance(c, dict) or not isinstance(c.get("png"), str):
            continue
        if not isinstance(c.get("series"), dict):
            continue                      # 老期次：只有元数据，没序列 → 前端回退 PNG
        out[c["png"].removesuffix(".png")] = c["series"]
    return out


# ---------- 整包 ----------

def _college_stats_as_drawn(ledger_dir: pathlib.Path,
                            end_period) -> dict | None:
    """学院统计照 PNG 的来源取：**缓存逐字优先**，缺席才现算。

    报告的学院饼图/合成表就是拿 `college_stats.json` 画的；直接走
    `college_stats.load` 在缓存口径过期时会重算——归一映射会把单元
    重新分组（2026-10-28 实测 202607：缓存 24 单元 → 重算 23 单元，
    「天文研究所＋别名」并成一行），前端饼图就跟报告 PNG 对不上了。
    所以这里宁可逐字用缓存（画了什么导什么），不追求「更新」。
    """
    j = pathlib.Path(ledger_dir) / "college_stats.json"
    if j.exists():
        try:
            st = json.loads(j.read_text(encoding="utf-8"))
            if st and st.get("units"):
                return st
        except (OSError, json.JSONDecodeError):
            pass
    return college_stats.load(ledger_dir, end_period, save=False)


def build(ledger_dir="out/202607", end_period=None, n_periods=7) -> dict:
    """整包导出：现读台账宽表，返回可直接 JSON 化的 dict（不落盘、不动 out/）。"""
    ledger_dir = pathlib.Path(ledger_dir)
    filled = _filled(ledger_dir, end_period)
    periods = filled[-n_periods:]
    delta_p = filled[-(n_periods + 1):]      # 新增发文量的差分基期（render_all 同款）
    P = periods[-1]
    end_period = end_period or P
    wide = {m: pd.read_parquet(ledger_dir / "wide" / f"{m}.parquet") for m in
            ("total_cites", "papers", "cnci", "threshold_1pct", "threshold_1permille",
             "top_papers", "q1q4", "entered_1pct", "ynd_rank")}
    for optional, key in (("top_by_year", "top_by_year"), ("college_stats", "_college_stats")):
        p = ledger_dir / "wide" / f"{optional}.parquet"
        if key == "_college_stats":
            wide[key] = _college_stats_as_drawn(ledger_dir, end_period)
        elif p.exists():
            wide[key] = pd.read_parquet(p)
    longdf = pd.read_parquet(ledger_dir / "ledger_long.parquet")
    piv = {}
    for source in ("rank_intl", "rank_cn"):
        d = longdf[(longdf.source == source) & (longdf.metric == "rank_pct")]
        piv[source] = d.pivot(index="discipline", columns="period", values="value")

    return {
        "schema": SCHEMA,
        "end_period": P,
        "periods": periods,
        "rank_pct": rank_pct_payload(piv["rank_intl"], piv["rank_cn"], periods),
        "disciplines": _per_discipline(wide, periods, delta_p, P),
        "_overview": _overview_payload(wide, periods, P, n_periods, end_period),
        "forecast": _forecast_payload(ledger_dir),
    }
