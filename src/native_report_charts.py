# -*- coding: utf-8 -*-
"""复刻报告的原生图表规格：C1–C6（96 个学科槽位）＋ 正文总览图。

与 `charts.py` 的分工：
  · `charts.py` ＝ matplotlib PNG 路径（**网站/前端的唯一图源**，出图步骤不删）；
  · 本模块 ＝ 同一批数据 → 原生 chart part 的 XML + 内嵌工作簿
    （**报告初稿的默认路径**，rick 2026-10-23 定；`WENHENG_NATIVE_CHARTS=0` 可回 PNG）。

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
    # 🔴 期次是六位数，8.26cm 宽里不写 rot 时 Word 会自动斜排（2026-10-23 实测）；
    #    `cat_crosses="min"` 把类目轴压到图底——202605 是 −63，轴在 0 线时柱子会从期次上穿过。
    xml = nc.bar_chart_xml(series, cats, gap_width=525, overlap=-27, label_fmt="0",
                           legend_pos="t", cat_fontsize=7, cat_crosses="min",
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
    # 同 C3：期次标签显式水平（rot="0"）+ 图例置顶，给七列六位数腾出整幅宽度
    xml = nc.bar_chart_xml(series, [str(p) for p in periods], gap_width=525, overlap=-27,
                           label_fmt="0", legend_pos="t", cat_fontsize=7,
                           **_axis_kw(b, integer=True))
    return xml, nc.build_data_xlsx([str(p) for p in periods], series)


def c6_q_dist(w, disc, period):
    """学科发文期刊分区占比：3 系列 × Q1–Q4 分组柱。

    🔴 数值标签用**整数百分比**（`0"%"`）。Word 原生图表没有「标签错行避让」，
    8.26cm 宽里 12 个两位小数标签（`32.98%`）必然互相压死（2026-10-23 实测 7pt/6pt
    都不行，`bestFit` 会让 Word 拒开整份文档）。整数百分比是两端都能接受的最小精度：
    12 个标签全部可读，内嵌工作簿仍保留原始两位小数。
    """
    qkey = f"{period[:4]}.{period[4:]}"
    q1q4 = w["q1q4"]
    cats = ["Q1", "Q2", "Q3", "Q4"]
    series, flat, any_val = [], [], False
    for ent, lab, col in charts.Q_ENTITIES:
        s = q1q4[(q1q4.discipline == disc) & (q1q4.entity == ent) & (q1q4.quarter == qkey)]
        row = [float(s[c].iloc[0]) if len(s) and pd.notna(s[c].iloc[0]) else None
               for c in ("q1", "q2", "q3", "q4")]
        any_val = any_val or any(v is not None for v in row)
        series.append({"name": lab, "values": row, "color": col, "label_fmt": '0"%"'})
        flat.extend(v for v in row if v is not None)
    if not any_val:
        return None, None
    b = nc.auto_axis([flat], floor_zero=True, intervals=6, pad=0.05, integer=True)
    xml = nc.bar_chart_xml(series, cats, gap_width=25, overlap=-8, label_fmt='0"%"',
                           legend_pos="t", **_axis_kw(b, integer=True))
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


# ================================================================ 正文总览图
#: 正文图的插入尺寸（cm）＝ PNG 版 `figsize` 按插图宽度等比换算（两版观感一致）
BODY_SIZES = {
    "1pct": (14.3, 14.67),
    "1permille": (14.5, 11.56),
    "rank_table": (13.9, 12.16),
    "trend_table": (14.5, 14.50),
    "top_by_subject": (13.5, 8.22),
    "top_by_year": (13.5, 7.98),
    "college_cites": (13.6, 7.42),
    "college_papers": (13.6, 7.42),
}

#: 「与 1% 阈值的百分比」这类**字面百分号**（数值已是 57.51，不再乘 100）
PCT_LITERAL = '0.00"%"'


def _body(key, xml, xlsx):
    w, h = BODY_SIZES[key]
    return {"xml": xml, "xlsx": xlsx, "w_cm": w, "h_cm": h}


def ov_1pct(w, period):
    """1% 接近度：22 学科横向堆叠柱（紫＝实际接近度、绿＝到 100% 的差距）+ 红色 100% 基线。"""
    import math  # noqa: PLC0415

    ratio = ((w["total_cites"][period] / w["threshold_1pct"][period]) * 100).dropna().sort_values()
    cats = [charts._cn(d) for d in ratio.index]
    vals = [float(v) for v in ratio]
    gap = [max(0.0, 100.0 - v) for v in vals]
    xmax = int(math.ceil(max(max(vals), 100.0) / 100.0) * 100)
    groups = [
        {"kind": "bar", "cat_ax": "c1", "val_ax": "v1", "bar_dir": "bar",
         "grouping": "stacked", "gap_width": 40, "overlap": 100,
         # 🔴 Word 不渲染**堆叠柱**的系列级数值标签（inBase/ctr/outEnd 都试过，见验证报告 §6.1），
         #    与其留一套不生效的配置，不如显式关掉：数值由柱长与横轴刻度读出。
         "series": [{"name": "与ESI前1%的接近度", "values": vals, "color": "B4A7D6",
                     "label_fmt": PCT_LITERAL, "show_labels": False},
                    {"name": "与ESI前1%的差距", "values": gap, "color": "A9D18E",
                     "label_fmt": PCT_LITERAL, "show_labels": False}]},
        {"kind": "line", "cat_ax": "c1", "val_ax": "v1",
         "series": [{"name": "ESI前1%基线", "values": [100.0] * len(vals), "color": "FF0000",
                     "lw": 19050, "show_labels": False}]},
    ]
    axes = [{"id": "c1", "kind": "cat", "cross": "v1", "pos": "l", "fontsize": 7},
            {"id": "v1", "kind": "val", "cross": "c1", "pos": "b", "minimum": 0,
             "maximum": xmax, "major_unit": 100, "numfmt": PCT_LITERAL, "gridlines": False,
             "fontsize": 6.5}]
    xml = nc.combo_chart_xml(groups, axes, cats, legend_pos="b")
    series = [{"name": "与ESI前1%的接近度", "values": vals, "color": "B4A7D6"},
              {"name": "与ESI前1%的差距", "values": gap, "color": "A9D18E"},
              {"name": "ESI前1%基线", "values": [100.0] * len(vals), "color": "FF0000"}]
    return _body("1pct", xml, nc.build_data_xlsx(cats, series))


def ov_1permille(w, period):
    """1‰ 潜力：已进入 1% 的学科，接近度 + 到 1‰ 的差距（横向堆叠柱）。"""
    entered = w["entered_1pct"][period][w["entered_1pct"][period] >= 1].index
    ratio = (w["total_cites"][period][entered]
             / w["threshold_1permille"][period][entered] * 100).dropna().sort_values()
    cats = [charts._cn(d) for d in ratio.index]
    vals = [float(v) for v in ratio]
    gap = [100.0 - v for v in vals]
    groups = [{"kind": "bar", "cat_ax": "c1", "val_ax": "v1", "bar_dir": "bar",
               "grouping": "stacked", "gap_width": 60, "overlap": 100,
               # 同 1pct：Word 不渲染堆叠柱的系列级数值标签 → 显式关掉（见验证报告 §6.1）
               "series": [{"name": "1‰接近度", "values": vals, "color": "B4A7D6",
                           "label_fmt": PCT_LITERAL, "show_labels": False},
                          {"name": "与前1‰差距", "values": gap, "color": "A9D18E",
                           "label_fmt": PCT_LITERAL, "show_labels": False}]}]
    axes = [{"id": "c1", "kind": "cat", "cross": "v1", "pos": "l", "fontsize": 9.5},
            {"id": "v1", "kind": "val", "cross": "c1", "pos": "b", "minimum": 0,
             "maximum": 105, "major_unit": 20, "numfmt": "0", "gridlines": True,
             "fontsize": 9.5}]
    xml = nc.combo_chart_xml(groups, axes, cats, legend_pos="b")
    series = [{"name": "1‰接近度", "values": vals, "color": "B4A7D6"},
              {"name": "与前1‰差距", "values": gap, "color": "A9D18E"}]
    return _body("1permille", xml, nc.build_data_xlsx(cats, series))


def ov_top_by_subject(w, period):
    """顶尖论文学科分布（篇）。"""
    s = w["top_papers"][period].dropna() if period in w["top_papers"].columns \
        else w["top_papers"].iloc[:, -1].dropna()
    s = s[s > 0].sort_values(ascending=False)
    cats = [charts._cn(d) for d in s.index]
    vals = [float(v) for v in s]
    b = nc.auto_axis([vals], floor_zero=True, intervals=6, pad=0.12, integer=True)
    series = [{"name": "顶尖论文发文量", "values": vals, "color": C_BLUE, "label_fmt": "0"}]
    xml = nc.bar_chart_xml(series, cats, gap_width=350, overlap=-27, label_fmt="0",
                           major_unit=b[2], minimum=0, maximum=b[1], numfmt="0",
                           cat_rotation="-2700000", cat_fontsize=6.6)
    return _body("top_by_subject", xml, nc.build_data_xlsx(cats, series))


def ov_top_by_year(w, period):
    """顶尖论文年代分布（篇）。"""
    s = w["top_by_year"][period].dropna() if period in w["top_by_year"].columns \
        else w["top_by_year"].iloc[:, -1].dropna()
    s = s[s > 0]
    cats = [str(i) for i in s.index]
    vals = [float(v) for v in s]
    b = nc.auto_axis([vals], floor_zero=True, intervals=5, pad=0.12, integer=True)
    series = [{"name": "顶尖论文发文量", "values": vals, "color": nc.C_ORANGE, "label_fmt": "0"}]
    xml = nc.bar_chart_xml(series, cats, gap_width=100, overlap=-27, label_fmt="0",
                           major_unit=b[2], minimum=0, maximum=b[1], numfmt="0",
                           legend_pos=None)
    return _body("top_by_year", xml, nc.build_data_xlsx(cats, series))


#: 学院贡献度：<1.5% 的份额合并为「其他（k 个单位）」（与 `charts.chart_college_pie` 同口径）
COLLEGE_TH = 0.015
COLLEGE_PALETTE = ["4472C4", "70AD47", "FFC000", "ED7D31", "7030A0", "00B0F0", "C00000",
                   "F4B183", "8FAADC", "C5E0B4", "FFE699", "B4A7D6", "9DC3E6", "A9D18E",
                   "D9D9D9"]


def ov_college_pie(cs, mode):
    """学院贡献度饼图 / 环形图（mode='cites' 实心饼 / 'papers' 环形）。"""
    raw = [((u["cites"] if mode == "cites" else u["papers"]), u["unit"]) for u in cs["units"]]
    total = sum(v for v, _u in raw) or 1
    keep = [(v, u) for v, u in raw if v / total >= COLLEGE_TH]
    small = [(v, u) for v, u in raw if v / total < COLLEGE_TH]
    if small:
        keep.append((sum(v for v, _u in small), f"其他（{len(small)} 个单位）"))
    cats = [u for _v, u in keep]
    vals = [float(v) for v, _u in keep]
    series = [{"name": "被引频次" if mode == "cites" else "发文量", "values": vals}]
    key = "college_cites" if mode == "cites" else "college_papers"
    xml = nc.pie_chart_xml(series, cats, doughnut=(mode == "papers"), hole=42,
                           legend_pos="r", label_fmt=PCT_LITERAL)
    return _body(key, xml, nc.build_data_xlsx(cats, series))


#: 趋势图配色/标记（与 `charts.chart_trend_table` 同口径）
TREND_COLORS = ["5B9BD5", "7030A0", "8C8C8C", "FFC000"]
TREND_MARKERS = ["circle", "square", "triangle", "diamond"]


def ov_trend_table(w, *, n_periods=7, end_period=None, top_k=4):
    """我校主要学科近期发展趋势（4 学科 × 7 期的 1‰ 接近度 + 100% 红基线 + 原生数据表）。"""
    picked, periods, picks = charts.trend_picks(
        w["total_cites"], w["threshold_1permille"], end_period=end_period,
        n=n_periods, top_k=top_k, entered=w["entered_1pct"])
    series = []
    for i, d in enumerate(picks):
        vals = picked.loc[d].tolist()
        series.append({"name": charts._cn(d), "values": [float(v) for v in vals],
                       "color": TREND_COLORS[i % len(TREND_COLORS)],
                       "marker": TREND_MARKERS[i % len(TREND_MARKERS)], "lw": 22860,
                       "label_fmt": PCT_LITERAL, "val_fmt": PCT_LITERAL,
                       # 只标**末点**（4 线 × 7 期全标会挤成一团，同 PNG 口径）
                       "hide_labels": tuple(range(len(vals) - 1))})
    # 100% 基线：常量线画进图里（rick 2026-09-24「这张图必须要有千分之一的阈值线」）
    series.append({"name": "ESI1‰ 基线", "values": [100.0] * len(periods), "color": "FF0000",
                   "lw": 20320, "marker": "none", "show_labels": False})
    xml = nc.line_chart_xml(series, periods, numfmt=PCT_LITERAL, label_fmt=PCT_LITERAL,
                            minimum=20, maximum=100, major_unit=20, legend_pos="b",
                            cat_fontsize=9.5, val_fontsize=10,
                            title="我校主要学科近期发展趋势",
                            dtable=nc.data_table_xml())
    data = [{"name": charts._cn(d), "values": [float(v) for v in picked.loc[d]]} for d in picks]
    return _body("trend_table", xml, nc.build_data_xlsx(periods, data))


def ov_rank_table(w, *, n_periods=7, end_period=None):
    """我校 ESI 排名情况：国内排名 / 国内高校排名（左轴柱）+ 国际排名（右轴折线），双轴反序。"""
    df = w["ynd_rank"].set_index("period").sort_index()
    df = df[df["rank_intl"].notna() | df["rank_cn"].notna()]
    if end_period:
        df = df[df.index <= str(end_period)]
    df = df.tail(n_periods)
    periods = [str(p) for p in df.index]
    bars = [{"name": "国内排名", "values": [float(v) for v in df["rank_cn"]], "color": "ED7D31"},
            {"name": "国内高校排名", "values": [float(v) for v in df["rank_cn_uni"]],
             "color": "FFC000"}]
    groups = [
        {"kind": "bar", "cat_ax": "c1", "val_ax": "v1", "bar_dir": "col",
         "grouping": "clustered", "gap_width": 120, "overlap": -10,
         "series": [dict(s, label_fmt="0", show_labels=False) for s in bars]},
        {"kind": "line", "cat_ax": "c2", "val_ax": "v2",
         "series": [{"name": "国际排名（右标）", "values": [float(v) for v in df["rank_intl"]],
                     "color": "4472C4", "marker": "circle", "lw": 22860,
                     "label_fmt": "0", "show_labels": False}]},
    ]
    axes = [
        {"id": "c1", "kind": "cat", "cross": "v1", "pos": "b", "crosses": "max",
         "fontsize": 10},
        {"id": "v1", "kind": "val", "cross": "c1", "pos": "l", "reverse": True,
         "minimum": 120, "maximum": 170, "major_unit": 5, "numfmt": "0", "fontsize": 10},
        {"id": "c2", "kind": "cat", "cross": "v2", "pos": "b", "delete": True,
         "fontsize": 10},
        {"id": "v2", "kind": "val", "cross": "c2", "pos": "r", "reverse": True,
         "minimum": 400, "maximum": 1400, "major_unit": 200, "numfmt": "0",
         "gridlines": False, "fontsize": 10},
    ]
    xml = nc.combo_chart_xml(groups, axes, periods, title="我校ESI排名情况",
                             legend_pos="b", cat_fontsize=10, val_fontsize=10)
    data = bars + [{"name": "国际排名（右标）",
                    "values": [float(v) for v in df["rank_intl"]]}]
    return _body("rank_table", xml, nc.build_data_xlsx(periods, data))


def body_charts(ledger_dir, *, n_periods=7, end_period=None, college=None):
    """产出正文图表规格：`{key: {"xml","xlsx","w_cm","h_cm"}}`。

    `college` 传 `college_stats.load()` 的结果（`fill_docx.fill_college` 已经 load 过，
    别在这里再读一遍盘）。单张失败不影响其它——调用方逐张 try，失败即回落 PNG。
    """
    w = load_wide(ledger_dir)
    _periods, _delta, P = window(ledger_dir, n_periods, end_period)
    w["top_by_year"] = pd.read_parquet(pathlib.Path(ledger_dir) / "wide" / "top_by_year.parquet")
    w["by_year"] = w["top_by_year"]
    out = {}
    out["1pct"] = ov_1pct(w, P)
    out["1permille"] = ov_1permille(w, P)
    out["top_by_subject"] = ov_top_by_subject(w, P)
    out["top_by_year"] = ov_top_by_year(w, P)
    out["trend_table"] = ov_trend_table(w, n_periods=n_periods, end_period=end_period)
    out["rank_table"] = ov_rank_table(w, n_periods=n_periods, end_period=end_period)
    if college:
        out["college_cites"] = ov_college_pie(college, "cites")
        out["college_papers"] = ov_college_pie(college, "papers")
    return out