# -*- coding: utf-8 -*-
"""复刻报告的原生图表规格：C1–C6（96 个学科槽位）＋ 正文总览图。

与 `charts.py` 的分工：
  · `charts.py` ＝ matplotlib PNG 路径（**默认路径，一个字节不动**）；
  · 本模块 ＝ 同一批数据 → 原生 chart part 的 XML + 内嵌工作簿（可选路径，开关控制）。

口径必须与 PNG 路径一致（窗口 7 期、差分多取一期、纵轴逐学科自适应、颜色、图例位置、
数值标签）。纵轴范围/刻度直接复用 `native_charts.auto_axis`（它内部复用
`charts._nice_step`），`tests/test_native_charts.py` 逐学科比对两条路径的刻度。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pandas as pd  # noqa: E402

import charts  # noqa: E402
import native_charts as nc  # noqa: E402
import period as period_mod  # noqa: E402

C_BLUE, C_GREEN, C_YELLOW = nc.C_BLUE, nc.C_GREEN, nc.C_YELLOW

#: 学科槽位图文件名（与 `fill_docx.CHART_SLOTS` 同序）
SLOT_FILES = ["rank_pct.png", "cnci.png", "papers_new.png",
              "cites_threshold.png", "top_papers.png", "q_dist.png"]


def load_wide(ledger_dir):
    """与 `charts.render_all` 同源：一次读齐所有宽表 + 长表。"""
    ledger_dir = pathlib.Path(ledger_dir)
    w = {m: pd.read_parquet(ledger_dir / "wide" / f"{m}.parquet") for m in
         ["total_cites", "papers", "cnci", "threshold_1pct", "top_papers",
          "proximity_1pct", "entered_1pct"]}
    w["threshold_1permille"] = pd.read_parquet(ledger_dir / "wide" / "threshold_1permille.parquet")
    w["q1q4"] = pd.read_parquet(ledger_dir / "wide" / "q1q4.parquet")
    w["ynd_rank"] = pd.read_parquet(ledger_dir / "wide" / "ynd_rank.parquet")
    w["_long"] = pd.read_parquet(ledger_dir / "ledger_long.parquet")
    return w


def window(ledger_dir, n_periods=7, end_period=None):
    """窗口＝当期往前 7 期（含当期）；差分要多取一期。返回 `(periods, delta_periods, P)`。"""
    ledger_dir = pathlib.Path(ledger_dir)
    total = pd.read_parquet(ledger_dir / "wide" / "total_cites.parquet")
    filled = period_mod.filled({"total_cites": total})
    end_period = end_period or charts._infer_end_period(ledger_dir)
    if end_period:
        filled = [c for c in filled if c <= str(end_period)]
    periods = filled[-n_periods:]
    return periods, filled[-(n_periods + 1):], periods[-1]


def _numfmt_for(ticks, integer):
    return "0" if integer else "General"


def _axis_kw(bounds, *, integer=False, percent=False, thousands=False):
    lo, hi, step, _ticks = bounds
    fmt = "0" if integer else "General"
    if percent:
        fmt = "0%" if integer else "0.00%"
    if thousands:
        fmt = "#,##0"
    return {"minimum": lo, "maximum": hi, "major_unit": step, "numfmt": fmt}


# ---------------------------------------------------------------- C1–C6
def c1_rank_pct(w, disc, periods):
    ri = w["_long"].pipe(lambda d: d[(d.source == "rank_intl") & (d.metric == "rank_pct")]) \
        .pivot(index="discipline", columns="period", values="value").loc[disc, periods].astype(float)
    rc = w["_long"].pipe(lambda d: d[(d.source == "rank_cn") & (d.metric == "rank_pct")]) \
        .pivot(index="discipline", columns="period", values="value").loc[disc, periods].astype(float)
    # 🔴 原生图表存**小数**：numFmt `0.00%` 会再乘 100（存 28.77 会显示 2877.16%，实测）
    b = nc.auto_axis([ri.tolist(), rc.tolist()], intervals=4, pad=0.06, invert=True)
    series = [{"name": "国际排名百分位值", "values": ri.tolist(), "color": C_BLUE},
              {"name": "国内排名百分位值", "values": rc.tolist(), "color": C_GREEN}]
    xml = nc.line_chart_xml(series, [str(p) for p in periods], reverse=True,
                            label_fmt="0.00%", **_axis_kw(b, percent=True))
    return xml, nc.build_data_xlsx([str(p) for p in periods], series)


def c2_cnci(w, disc, periods):
    v = w["cnci"].loc[disc, periods].astype(float)
    base = [1.0] * len(periods)
    b = nc.auto_axis([v.tolist()], include=[1.0], intervals=5, pad=0.05, lo_pad=0.12)
    series = [{"name": "CNCI 值", "values": v.tolist(), "color": C_BLUE, "label_fmt": "0.00"},
              {"name": "CNCI 国际均值", "values": base, "color": C_GREEN, "label_fmt": "0"}]
    xml = nc.line_chart_xml(series, [str(p) for p in periods], **_axis_kw(b))
    return xml, nc.build_data_xlsx([str(p) for p in periods], series)


def c3_papers_delta(w, disc, delta_periods):
    v = w["papers"].loc[disc, delta_periods].astype(float)
    d = v.diff().iloc[1:]
    cats = [str(p) for p in delta_periods[1:]]
    b = nc.auto_axis([d.tolist()], zero_base=True, intervals=6, pad=0.08, integer=True)
    series = [{"name": "新增发文量", "values": d.tolist(), "color": C_BLUE, "label_fmt": "0"}]
    xml = nc.bar_chart_xml(series, cats, gap_width=525, overlap=-27, label_fmt="0",
                           **_axis_kw(b, integer=True))
    return xml, nc.build_data_xlsx(cats, series)


def c4_cites_threshold(w, disc, periods):
    c = w["total_cites"].loc[disc, periods].astype(float)
    t = w["threshold_1pct"].loc[disc, periods].astype(float)
    b = nc.auto_axis([c.tolist(), t.tolist()], intervals=5, pad=0.06, zero_base=False)
    series = [{"name": "被引频次", "values": c.tolist(), "color": C_BLUE, "label_fmt": "0"},
              {"name": "ESI 阈值", "values": t.tolist(), "color": C_GREEN, "label_fmt": "0"}]
    xml = nc.line_chart_xml(series, [str(p) for p in periods],
                            label_fmt="0", **_axis_kw(b, thousands=True))
    return xml, nc.build_data_xlsx([str(p) for p in periods], series)


def c5_top_papers(w, disc, periods):
    v = w["top_papers"].loc[disc, periods].fillna(0).astype(float)
    b = nc.auto_axis([v.tolist()], intervals=7, pad=0.06, integer=True, floor_zero=False)
    series = [{"name": "顶尖论文发文量", "values": v.tolist(), "color": C_BLUE, "label_fmt": "0"}]
    xml = nc.bar_chart_xml(series, [str(p) for p in periods], gap_width=525, overlap=-27,
                           label_fmt="0", **_axis_kw(b, integer=True))
    return xml, nc.build_data_xlsx([str(p) for p in periods], series)


def c6_q_dist(w, disc, period):
    qkey = f"{period[:4]}.{period[4:]}"
    q1q4 = w["q1q4"]
    cats = ["Q1", "Q2", "Q3", "Q4"]
    series, flat, any_val = [], [], False
    for ent, lab, col in charts.Q_ENTITIES:
        s = q1q4[(q1q4.discipline == disc) & (q1q4.entity == ent) & (q1q4.quarter == qkey)]
        row = [float(s[c].iloc[0]) if len(s) and pd.notna(s[c].iloc[0]) else None
               for c in ("q1", "q2", "q3", "q4")]
        any_val = any_val or any(v is not None for v in row)
        series.append({"name": lab, "values": row, "color": col, "label_fmt": '0.##"%"'})
        flat.extend(v for v in row if v is not None)
    if not any_val:
        return None, None
    b = nc.auto_axis([flat], floor_zero=True, intervals=6, pad=0.05, integer=True)
    xml = nc.bar_chart_xml(series, cats, gap_width=25, overlap=-8, label_fmt='0.##"%"',
                           **_axis_kw(b, integer=True))
    return xml, nc.build_data_xlsx(cats, series)


#: 槽位图 → 构造函数（与 `charts.render_all` 的调用一一对应）
SLOT_BUILDERS = {
    "rank_pct.png": lambda w, d, ctx: c1_rank_pct(w, d, ctx["periods"]),
    "cnci.png": lambda w, d, ctx: c2_cnci(w, d, ctx["periods"]),
    "papers_new.png": lambda w, d, ctx: c3_papers_delta(w, d, ctx["delta_periods"]),
    "cites_threshold.png": lambda w, d, ctx: c4_cites_threshold(w, d, ctx["periods"]),
    "top_papers.png": lambda w, d, ctx: c5_top_papers(w, d, ctx["periods"]),
    "q_dist.png": lambda w, d, ctx: c6_q_dist(w, d, ctx["P"]),
}


def slot_charts(ledger_dir, *, n_periods=7, end_period=None, disciplines=None):
    """产出 96 个槽位图规格：`{(slug, fname): {"xml":…, "xlsx":…}}`。"""
    w = load_wide(ledger_dir)
    periods, delta_periods, P = window(ledger_dir, n_periods, end_period)
    ctx = {"periods": periods, "delta_periods": delta_periods, "P": P}
    out = {}
    for disc in (disciplines or charts.DETAIL_TABLES):
        slug = charts._slug(disc)
        for fname in SLOT_FILES:
            xml, xlsx = SLOT_BUILDERS[fname](w, disc, ctx)
            if xml is None:
                continue
            out[(slug, fname)] = {"xml": xml, "xlsx": xlsx}
    return out