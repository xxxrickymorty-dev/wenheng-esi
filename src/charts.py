# -*- coding: utf-8 -*-
"""图表模板库 C1–C8：从台账序列重绘《学科信息参考》全部期次图。

样式策略（决策 D0/B）：先 1:1 仿 Excel 观感（Excel 默认配色 + 细网格），
美化迭代留给可视化组。图幅 8.26×5.50 cm @300dpi，与母版槽位一致。
"""
import pathlib
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

try:
    from parse_ledger import DISCIPLINES_CN
except ImportError:  # 直接运行时的兜底
    DISCIPLINES_CN = {}


def _cn(en):
    return DISCIPLINES_CN.get(en, en)

FONT = "SimHei"  # Windows 黑体；服务器环境换 Noto Sans CJK
plt.rcParams.update({
    "font.sans-serif": [FONT, "Microsoft YaHei", "sans-serif"],
    "axes.unicode_minus": False,
    "figure.dpi": 300,
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.edgecolor": "#BFBFBF",
    "axes.linewidth": 0.8,
})

# Excel 默认配色
C_BLUE, C_ORANGE, C_GRAY, C_YELLOW, C_LIGHTBLUE = "#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5"
FIG_W, FIG_H = 8.26 / 2.54, 5.50 / 2.54  # 3.25 x 2.17 inch

DETAIL_TABLES = [  # 16 个详细学科（T03–T18 顺序）
    "Chemistry", "Plant & Animal Science", "Environment/Ecology", "Engineering",
    "Materials Science", "Geosciences", "Computer Science", "Pharmacology & Toxicology",
    "Agricultural Sciences", "Biology & Biochemistry", "Social Sciences, general",
    "Clinical Medicine", "Microbiology", "Mathematics", "Physics",
    "Molecular Biology & Genetics",
]


def _slug(en):
    return re.sub(r"[^A-Za-z0-9]+", "", en)


def _fig(w=FIG_W, h=FIG_H):
    fig, ax = plt.subplots(figsize=(w, h))
    return fig, ax


def _avail(df, periods):
    """期次交集：只画该序列确实存在的期次。"""
    return [p for p in periods if p in df.columns]


def _save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=0.4)
    fig.savefig(path, dpi=300)  # 不用 bbox_inches，保持与母版槽位一致的精确比例 8.26:5.50
    plt.close(fig)


def _xticks(ax, periods, step=None):
    labels = [f"{p[:4]}.{p[4:]}" for p in periods]
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(labels, rotation=60, fontsize=7)
    ax.grid(axis="y", color="#E7E6E6", linewidth=0.6)


# ---------- C1 国内外排名百分位趋势 ----------
def chart_rank_pct(rank_intl, rank_cn, disc, out_png, periods):
    periods = _avail(rank_intl, periods)
    fig, ax = _fig()
    ri = rank_intl.loc[disc, periods].astype(float)
    rc = rank_cn.loc[disc, periods].astype(float)
    ax.plot(range(len(periods)), ri, marker="o", ms=2.5, lw=1.2, color=C_BLUE, label="国际排名百分位")
    ax.plot(range(len(periods)), rc, marker="s", ms=2.5, lw=1.2, color=C_ORANGE, label="国内排名百分位")
    _xticks(ax, periods)
    ax.legend(fontsize=7, loc="best")
    ax.set_ylabel("排名百分位", fontsize=8)
    _save(fig, out_png)


# ---------- C2 CNCI 变化 ----------
def chart_cnci(cnci, disc, out_png, periods):
    periods = _avail(cnci, periods)
    fig, ax = _fig()
    v = cnci.loc[disc, periods].astype(float)
    ax.plot(range(len(periods)), v, marker="o", ms=2.5, lw=1.2, color=C_BLUE)
    ax.axhline(1.0, color=C_ORANGE, lw=1, ls="--")
    ax.text(0.01, 1.0, " 世界平均=1", color=C_ORANGE, fontsize=7, va="bottom")
    _xticks(ax, periods)
    ax.set_ylabel("CNCI", fontsize=8)
    _save(fig, out_png)


# ---------- C3 新增发文量 ----------
def chart_papers_delta(papers, disc, out_png, periods):
    periods = _avail(papers, periods)
    fig, ax = _fig()
    v = papers.loc[disc, periods].astype(float)
    d = v.diff()
    ax.bar(range(len(periods)), d, color=C_BLUE, width=0.65)
    _xticks(ax, periods)
    ax.set_ylabel("新增发文量（篇）", fontsize=8)
    _save(fig, out_png)


# ---------- C4 被引频次与 ESI 阈值 ----------
def chart_cites_threshold(cites, threshold, disc, out_png, periods):
    periods = _avail(cites, periods)
    fig, ax = _fig()
    c = cites.loc[disc, periods].astype(float)
    t = threshold.loc[disc, periods].astype(float)
    ax.plot(range(len(periods)), c, marker="o", ms=2.5, lw=1.3, color=C_BLUE, label="总被引频次")
    ax.plot(range(len(periods)), t, marker="^", ms=2.5, lw=1.1, color=C_ORANGE, label="ESI 1%阈值")
    _xticks(ax, periods)
    ax.legend(fontsize=7, loc="best")
    _save(fig, out_png)


# ---------- C5 顶尖论文量 ----------
def chart_top_papers(top, disc, out_png, periods):
    periods = _avail(top, periods)
    fig, ax = _fig()
    v = top.loc[disc, periods].fillna(0).astype(float)
    ax.bar(range(len(periods)), v, color=C_YELLOW, width=0.65)
    _xticks(ax, periods)
    ax.set_ylabel("顶尖论文量（篇）", fontsize=8)
    _save(fig, out_png)


# ---------- C6 期刊分区占比 ----------
def chart_q_dist(q1q4, disc, out_png):
    fig, ax = _fig()
    sub = q1q4[(q1q4.discipline == disc) & (q1q4.entity == "云南大学")].dropna(subset=["q1"])
    sub = sub.drop_duplicates("quarter")
    if sub.empty:
        ax.text(0.5, 0.5, "（无分区数据）", ha="center", va="center", fontsize=9)
        _save(fig, out_png)
        return
    x = range(len(sub))
    ax.stackplot(x, sub.q1, sub.q2, sub.q3, sub.q4,
                 colors=[C_BLUE, C_LIGHTBLUE, C_YELLOW, C_GRAY],
                 labels=["Q1", "Q2", "Q3", "Q4"], alpha=0.9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(sub.quarter.tolist(), rotation=60, fontsize=7)
    ax.set_ylim(0, 100)
    ax.set_ylabel("占比 %", fontsize=8)
    ax.legend(fontsize=7, loc="lower left", ncol=4)
    ax.grid(axis="y", color="#E7E6E6", linewidth=0.6)
    _save(fig, out_png)


# ---------- 概览图：我校 ESI 排名情况（对标第4期 P042 原生图表）----------
def chart_ynd_rank(ynd_rank, out_png, end_period=None, n=7):
    """我校排名三序列折线：国内排名 / 国内高校排名 / 国际排名（右轴）。"""
    df = ynd_rank.set_index("period").sort_index()
    df = df[df["rank_intl"].notna() | df["rank_cn"].notna()]
    if end_period:
        df = df[df.index <= end_period]
    df = df.tail(n)
    periods = [f"{p[:4]}.{p[4:]}" for p in df.index]

    fig, ax = _fig()
    ax.plot(range(len(df)), df["rank_cn"], marker="o", ms=3, lw=1.3, color=C_BLUE, label="国内排名")
    ax.plot(range(len(df)), df["rank_cn_uni"], marker="s", ms=3, lw=1.3, color=C_ORANGE, label="国内高校排名")
    ax2 = ax.twinx()
    ax2.plot(range(len(df)), df["rank_intl"], marker="^", ms=3, lw=1.3, color=C_GRAY, ls="--", label="国际排名（右标）")
    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(periods, rotation=45, fontsize=7)
    ax.set_ylabel("国内排名", fontsize=8)
    ax2.set_ylabel("国际排名（右标）", fontsize=8)
    ax.grid(axis="y", color="#E7E6E6", linewidth=0.6)
    ax.invert_yaxis()
    ax2.invert_yaxis()
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [l.get_label() for l in lines], fontsize=6.5, loc="center left")
    _save(fig, out_png)


# ---------- 概览图：1% 接近度（红基线；对标第4期风格）----------
def chart_overview_1pct(cites, threshold, out_png, period):
    fig, ax = _fig(3.25, 3.15)
    ratio = (cites[period] / threshold[period]) * 100
    ratio = ratio.dropna().sort_values()
    colors = ["#B4A7D6" if v >= 100 else "#A9D18E" for v in ratio]
    ax.barh(range(len(ratio)), ratio, color=colors, height=0.7)
    for i, v in enumerate(ratio):
        ax.text(v + 8, i, f"{v:.2f}%", va="center", fontsize=6, color="#404040")
    ax.axvline(100, color="red", lw=1.6)
    ax.set_yticks(range(len(ratio)))
    ax.set_yticklabels([_cn(d) for d in ratio.index], fontsize=6.5)
    ax.set_xlabel("被引频次 / 1%阈值（%）", fontsize=8)
    ax.grid(axis="x", color="#E7E6E6", linewidth=0.6)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#B4A7D6", label="与ESI前1%的接近度"),
                       Patch(color="#A9D18E", label="与ESI前1%的差距"),
                       Patch(color="red", label="ESI前1%基线")],
              fontsize=6.5, loc="lower right")
    _save(fig, out_png)


# ---------- 概览图：1‰ 潜力（已进入1%学科，接近度+差距堆叠）----------
def chart_overview_1permille(cites, thr_1permille, proximity_1pct, out_png, period):
    fig, ax = _fig(3.25, 2.55)
    entered = proximity_1pct[period][proximity_1pct[period] >= 1].index
    ratio = (cites[period][entered] / thr_1permille[period][entered] * 100).dropna().sort_values()
    gap = 100 - ratio
    y = range(len(ratio))
    ax.barh(y, ratio, color="#B4A7D6", height=0.7, label="1‰接近度")
    ax.barh(y, gap, left=ratio, color="#A9D18E", height=0.7, label="与前1‰差距")
    for i, v in enumerate(ratio):
        ax.text(v + 2, i, f"{v:.2f}%", va="center", fontsize=6, color="#404040")
    ax.set_yticks(list(y))
    ax.set_yticklabels([_cn(d) for d in ratio.index], fontsize=6.5)
    ax.set_xlim(0, 105)
    ax.set_xlabel("占 1‰ 阈值比例（%）", fontsize=8)
    ax.grid(axis="x", color="#E7E6E6", linewidth=0.6)
    ax.legend(fontsize=6.5, loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, frameon=False)
    _save(fig, out_png)


# ---------- 旧版概览图（保留兼容）----------
def chart_overview_1pct_v0(cites, threshold, out_png, period):
    fig, ax = _fig()
    ratio = (cites[period] / threshold[period]) * 100
    ratio = ratio.dropna().sort_values()
    colors = [C_BLUE if v < 100 else "#2E7D32" for v in ratio]
    ax.barh(range(len(ratio)), ratio, color=colors, height=0.65)
    ax.axvline(100, color="red", lw=1.4)
    ax.set_yticks(range(len(ratio)))
    ax.set_yticklabels(ratio.index, fontsize=6.5)
    ax.set_xlabel("被引频次 / 1%阈值（%）", fontsize=8)
    ax.grid(axis="x", color="#E7E6E6", linewidth=0.6)
    _save(fig, out_png)


def render_all(ledger_dir="out/202607", out_dir=None, n_periods=18, end_period=None):
    """渲染 16 学科 × 6 图 + 2 张概览图。end_period=历史复跑时指定当期（如 202605）。"""
    ledger_dir = pathlib.Path(ledger_dir)
    out_dir = pathlib.Path(out_dir or ledger_dir) / "charts"
    w = {m: pd.read_parquet(ledger_dir / "wide" / f"{m}.parquet") for m in
         ["total_cites", "papers", "cnci", "threshold_1pct", "top_papers", "proximity_1pct"]}
    thr_p = pd.read_parquet(ledger_dir / "wide" / "threshold_1permille.parquet")
    longdf = pd.read_parquet(ledger_dir / "ledger_long.parquet")
    q1q4 = pd.read_parquet(ledger_dir / "wide" / "q1q4.parquet")

    all_p = [str(c) for c in w["total_cites"].columns if str(c).isdigit()]
    filled = [c for c in all_p if w["total_cites"][c].notna().any()]
    if end_period:
        filled = [c for c in filled if c <= end_period]
    periods = filled[-n_periods:]
    P = filled[-1]
    rank_intl = longdf[(longdf.source == "rank_intl") & (longdf.metric == "rank_pct")] \
        .pivot(index="discipline", columns="period", values="value")
    rank_cn = longdf[(longdf.source == "rank_cn") & (longdf.metric == "rank_pct")] \
        .pivot(index="discipline", columns="period", values="value")

    made = []
    for d in DETAIL_TABLES:
        folder = out_dir / _slug(d)
        chart_rank_pct(rank_intl, rank_cn, d, folder / "rank_pct.png", periods)
        chart_cnci(w["cnci"], d, folder / "cnci.png", periods)
        chart_papers_delta(w["papers"], d, folder / "papers_new.png", periods)
        chart_cites_threshold(w["total_cites"], w["threshold_1pct"], d, folder / "cites_threshold.png", periods)
        chart_top_papers(w["top_papers"], d, folder / "top_papers.png", periods)
        chart_q_dist(q1q4, d, folder / "q_dist.png")
        made.append(d)

    ov = out_dir / "_overview"
    ynd_rank = pd.read_parquet(ledger_dir / "wide" / "ynd_rank.parquet")
    chart_ynd_rank(ynd_rank, ov / "ynd_rank.png", end_period=end_period)
    chart_overview_1pct(w["total_cites"], w["threshold_1pct"], ov / "1pct.png", P)
    chart_overview_1permille(w["total_cites"], thr_p, w["proximity_1pct"], ov / "1permille.png", P)
    total = len(made) * 6 + 3
    print(f"charts: {len(made)} 学科 × 6 图 + 概览 3 张 = {total} 张 → {out_dir}")
    return total


if __name__ == "__main__":
    import sys
    ld = sys.argv[1] if len(sys.argv) > 1 else None
    if ld is None:
        outs = sorted(pathlib.Path("out").glob("20*/"), key=lambda p: p.name)
        ld = str(outs[-1]).replace("\\", "/")
    render_all(ld)
