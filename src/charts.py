# -*- coding: utf-8 -*-
"""图表模板库 C1–C6：从台账序列重绘《学科信息参考》全部期次图。

样式口径（WH-DOC-13，2026-09-17 按第 4 期原件 1:1 复刻，见 `评审文档/13`）：
  1. 窗口＝**当期往前 7 期**（含当期）；期次标签写六位数字 `202507`，水平排列。
  2. 字体＝西文 **Times New Roman** + 中文 **宋体**（原件观感；服务器走 Noto Serif CJK）。
  3. **每点/每柱标数值**；图例**无框**——多系列在图内顶部居中，单系列在右上。
  4. 纵轴：图1 **反向**（百分位下降＝上升趋势）；图2 固定 **0.5–2**；
     图3/4/5 刻度 1:1 抄原件（逐图硬编码）。
  5. 颜色：系列1 蓝 `#4472C4`、系列2 绿 `#70AD47`、系列3 黄 `#FFC000`；只留左/下轴脊。

图幅固定 8.26×5.50 cm @300dpi — 与母版槽位一致，**不随原件截图比例改动**（改这里要跑全套验收）。
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

# 西文衬线在前（数字/字母走 Times），中文回退到宋体族——与原件一致。
# 末段是**兜底**：Linux 服务器若没装 fonts-noto-cjk-extra（不含 Serif），至少退到黑体不出方框。
_FONT_CANDIDATES = ["Times New Roman", "SimSun", "Noto Serif CJK SC", "Noto Serif SC",
                    "Source Han Serif SC", "STSong", "Songti SC", "AR PL UMing CN",
                    "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Zen Hei", "SimHei",
                    "Microsoft YaHei", "AR PL UKai CN", "Droid Sans Fallback"]


def _font_stack():
    try:
        avail = {f.name for f in font_manager.fontManager.ttflist}
    except Exception:
        avail = set()
    picked = [n for n in _FONT_CANDIDATES if n in avail]
    return picked or ["DejaVu Serif"]


STACK = _font_stack()
FONT = STACK[0]  # 兼容既有引用（Windows=Times New Roman；Linux=Noto Serif CJK SC）

# Excel 默认配色
C_BLUE, C_ORANGE, C_GRAY, C_YELLOW, C_LIGHTBLUE = "#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5"
C_GREEN = "#70AD47"        # 原件「系列2」＝绿：国内排名 / CNCI 国际均值 / ESI 阈值 / 中国大陆
C_AXIS, C_GRID, C_TEXT = "#BFBFBF", "#D9D9D9", "#404040"
FONT_SIZE, TITLE_SIZE = 7, 9.5
FIG_W, FIG_H = 8.26 / 2.54, 5.50 / 2.54  # 3.25 x 2.17 inch

plt.rcParams.update({
    # 🔴 必须把字体名列表直接给 font.family：matplotlib 的**逐字形 fallback 只认这一条路径**。
    # 写成 font.family="serif" + font.serif=[...] 不会 fallback（实测 matplotlib 3.11.2：
    # 中文全部报 "Glyph ... missing from font(s) Times New Roman"，10/10 缺字）。
    "font.family": STACK,
    "axes.unicode_minus": False,
    "figure.dpi": 300,
    "font.size": FONT_SIZE,
    "axes.titlesize": TITLE_SIZE,
    "axes.edgecolor": C_AXIS,
    "axes.linewidth": 0.8,
})

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
    fig.tight_layout(pad=0.6)
    fig.savefig(path, dpi=300)  # 不用 bbox_inches，保持与母版槽位一致的精确比例 8.26:5.50
    plt.close(fig)


def _style(ax):
    """原件观感：只留左/下轴脊、无刻度短线、水平网格压在数据下方。"""
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(C_AXIS)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(axis="both", length=0, pad=3.5, labelsize=FONT_SIZE, colors=C_TEXT)
    ax.grid(axis="y", color=C_GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def _title(ax, text):
    ax.set_title(text, fontsize=TITLE_SIZE, color="#1F1F1F", pad=24)


def _labels(ax, xs, ys, fmt="{:.2f}", dy=4, size=FONT_SIZE):
    """逐点标数值；正值标上方、负值自动改标下方。"""
    for x, y in zip(xs, ys):
        if y is None or pd.isna(y):
            continue
        up = float(y) >= 0
        ax.annotate(fmt.format(y) if fmt else str(y), (x, y),
                    textcoords="offset points", xytext=(0, dy if up else -dy),
                    ha="center", va="bottom" if up else "top",
                    fontsize=size, color=C_TEXT)


def _xticks(ax, periods):
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels([str(p) for p in periods], fontsize=FONT_SIZE)


def _legend_top(ax, ncol=2):
    """多系列折线：图内顶部居中、横排、无框（原件口径）。"""
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=ncol, frameon=False,
              fontsize=FONT_SIZE, handlelength=1.7, handletextpad=0.4,
              columnspacing=1.2, borderaxespad=0.2)


def _legend_ur(ax, ncol=1):
    """单系列柱状图：右上、无框（原件口径）。"""
    ax.legend(loc="upper right", ncol=ncol, frameon=False, fontsize=FONT_SIZE,
              handlelength=1.2, handletextpad=0.4, columnspacing=1.0,
              borderaxespad=0.4)


# ---------- C1 国内外排名百分位趋势 ----------
def chart_rank_pct(rank_intl, rank_cn, disc, out_png, periods):
    periods = _avail(rank_intl, periods)
    fig, ax = _fig()
    ri = rank_intl.loc[disc, periods].astype(float) * 100
    rc = rank_cn.loc[disc, periods].astype(float) * 100
    x = list(range(len(periods)))
    ax.plot(x, ri, marker="o", ms=3.5, lw=1.0, mfc="white", mec=C_BLUE, mew=0.9,
            color=C_BLUE, label="国际排名百分位值")
    ax.plot(x, rc, marker="o", ms=3.5, lw=1.0, mfc="white", mec=C_GREEN, mew=0.9,
            color=C_GREEN, label="国内排名百分位值")
    _style(ax)
    _xticks(ax, periods)
    _labels(ax, x, ri, "{:.2f}%")
    _labels(ax, x, rc, "{:.2f}%")
    ax.set_ylim(40, 20)                      # 反向：数值越小（排名越好）越靠上
    ax.set_yticks([20, 25, 30, 35, 40])
    ax.set_yticklabels(["20%", "25%", "30%", "35%", "40%"])
    _title(ax, "国内外排名百分位趋势")
    _legend_top(ax)
    _save(fig, out_png)


# ---------- C2 CNCI 变化 ----------
def chart_cnci(cnci, disc, out_png, periods):
    periods = _avail(cnci, periods)
    fig, ax = _fig()
    v = cnci.loc[disc, periods].astype(float)
    x = list(range(len(periods)))
    base = [1.0] * len(periods)
    ax.plot(x, v, marker="o", ms=3.5, lw=1.0, mfc="white", mec=C_BLUE, mew=0.9,
            color=C_BLUE, label="CNCI 值")
    ax.plot(x, base, marker="o", ms=3.5, lw=1.0, mfc="white", mec=C_GREEN, mew=0.9,
            color=C_GREEN, label="CNCI 国际均值")
    _style(ax)
    _xticks(ax, periods)
    _labels(ax, x, v, "{:.2f}")
    _labels(ax, x, base, "{:.0f}")
    ax.set_ylim(0.5, 2.0)                    # 原件口径：基准线 1 落在约 1/3 高处
    ax.set_yticks([0.5, 0.6, 0.9, 1.2, 1.5, 1.8, 2.0])
    ax.set_yticklabels(["0.5", "0.6", "0.9", "1.2", "1.5", "1.8", "2"])
    _title(ax, "CNCI 变化情况")
    _legend_top(ax)
    _save(fig, out_png)


# ---------- C3 新增发文量 ----------
def chart_papers_delta(papers, disc, out_png, periods):
    """periods 须含「窗口外上一期」：增量＝相邻期差分，只取 7 期会让首点变 NaN。"""
    ps = _avail(papers, periods)
    fig, ax = _fig()
    v = papers.loc[disc, ps].astype(float)
    d = v.diff().iloc[1:] if len(ps) > 1 else v.iloc[0:0]
    ps = ps[1:]
    x = list(range(len(ps)))
    ax.bar(x, d, color=C_BLUE, width=0.16, label="新增发文量")
    _style(ax)
    _xticks(ax, ps)
    _labels(ax, x, d, "{:.0f}")
    ax.set_ylim(-90, 120)
    ax.set_yticks([-90, -60, -30, 0, 30, 60, 90, 120])
    _title(ax, "新增发文量（篇）")
    _legend_ur(ax)
    _save(fig, out_png)


# ---------- C4 被引频次与 ESI 阈值 ----------
def chart_cites_threshold(cites, threshold, disc, out_png, periods):
    periods = _avail(cites, periods)
    fig, ax = _fig()
    c = cites.loc[disc, periods].astype(float)
    t = threshold.loc[disc, periods].astype(float)
    x = list(range(len(periods)))
    ax.plot(x, c, marker="o", ms=3.5, lw=1.0, mfc="white", mec=C_BLUE, mew=0.9,
            color=C_BLUE, label="被引频次")
    ax.plot(x, t, marker="o", ms=3.5, lw=1.0, mfc="white", mec=C_GREEN, mew=0.9,
            color=C_GREEN, label="ESI 阈值")
    _style(ax)
    _xticks(ax, periods)
    _labels(ax, x, c, "{:.0f}")   # 原件数据标签无千分位（轴刻度才有）
    _labels(ax, x, t, "{:.0f}")
    ax.set_ylim(5000, 50000)
    ax.set_yticks([5000, 10000, 20000, 30000, 40000, 50000])
    ax.set_yticklabels(["5,000", "10,000", "20,000", "30,000", "40,000", "50,000"])
    _title(ax, "被引频次与 ESI 阈值变化")
    _legend_ur(ax, ncol=2)
    _save(fig, out_png)


# ---------- C5 顶尖论文量 ----------
def chart_top_papers(top, disc, out_png, periods):
    periods = _avail(top, periods)
    fig, ax = _fig()
    v = top.loc[disc, periods].fillna(0).astype(float)
    x = list(range(len(periods)))
    ax.bar(x, v, color=C_BLUE, width=0.16, label="顶尖论文发文量")
    _style(ax)
    _xticks(ax, periods)
    _labels(ax, x, v, "{:.0f}")
    ax.set_ylim(30, 45)                      # 原件口径：截断轴，不从 0 起
    ax.set_yticks(list(range(30, 46)))
    _title(ax, "顶尖论文量（篇）")
    _legend_ur(ax)
    _save(fig, out_png)


# ---------- C6 期刊分区占比（单期快照，三个口径并列） ----------
Q_ENTITIES = [("云南大学", "云南大学", C_BLUE),
              ("中国大陆", "中国大陆", C_GREEN),
              ("全球", "国际", C_YELLOW)]   # 数据里叫「全球」，原件外显「国际」


def chart_q_dist(q1q4, disc, out_png, period):
    fig, ax = _fig()
    qkey = f"{period[:4]}.{period[4:]}"      # q1q4.parquet 的 quarter 形如 2026.07
    vals, any_val = {}, False
    for ent, _, _ in Q_ENTITIES:
        s = q1q4[(q1q4.discipline == disc) & (q1q4.entity == ent) & (q1q4.quarter == qkey)]
        row = []
        for c in ("q1", "q2", "q3", "q4"):
            v = float(s[c].iloc[0]) if len(s) and pd.notna(s[c].iloc[0]) else float("nan")
            row.append(v)
            any_val = any_val or not pd.isna(v)
        vals[ent] = row
    if not any_val:
        ax.text(0.5, 0.5, "（无分区数据）", ha="center", va="center", fontsize=9)
        _save(fig, out_png)
        return
    group_w = 0.40                       # 原件组宽/周期 ≈ 0.4
    width = group_w / len(Q_ENTITIES)
    centers = list(range(4))
    for k, (ent, lab, col) in enumerate(Q_ENTITIES):
        pos = [c - group_w / 2 + width / 2 + k * width for c in centers]
        ax.bar(pos, vals[ent], width=width * 0.92, color=col, label=lab)
        # {:g} 按数据原样出位数：原件里既有 57.51% 也有 11.7% / 7.9%
        _labels(ax, pos, vals[ent], "{:g}%", dy=3, size=6.5)
    _style(ax)
    ax.set_xticks(centers)
    ax.set_xticklabels(["Q1", "Q2", "Q3", "Q4"], fontsize=FONT_SIZE)
    ax.set_ylim(0, 60)
    ax.set_yticks([0, 10, 20, 30, 40, 50, 60])
    _title(ax, "学科发文期刊分区占比情况")
    _legend_top(ax, ncol=3)              # 原件图 6 图例在顶部居中（不是右上）
    _save(fig, out_png)


# ---------- 概览图：我校 ESI 排名情况（对标第4期 P042 原生图表）----------
def chart_ynd_rank(ynd_rank, out_png, end_period=None, n=7):
    """我校排名三序列折线：国内排名 / 国内高校排名 / 国际排名（右轴）。"""
    df = ynd_rank.set_index("period").sort_index()
    df = df[df["rank_intl"].notna() | df["rank_cn"].notna()]
    if end_period:
        df = df[df.index <= str(end_period)]
    df = df.tail(n)
    periods = [str(p) for p in df.index]

    fig, ax = _fig()
    ax.plot(range(len(df)), df["rank_cn"], marker="o", ms=3, lw=1.2, color=C_BLUE, label="国内排名")
    ax.plot(range(len(df)), df["rank_cn_uni"], marker="s", ms=3, lw=1.2, color=C_ORANGE, label="国内高校排名")
    ax2 = ax.twinx()
    ax2.plot(range(len(df)), df["rank_intl"], marker="^", ms=3, lw=1.2, color=C_GRAY, ls="--", label="国际排名（右标）")
    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(periods, fontsize=FONT_SIZE)
    ax.grid(axis="y", color=C_GRID, linewidth=0.7)
    ax.invert_yaxis()
    ax2.invert_yaxis()
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [l.get_label() for l in lines], fontsize=6.5, loc="center left", frameon=False)
    _save(fig, out_png)


# ---------- 概览图：1% 接近度（红基线；对标第4期风格）----------
def chart_overview_1pct(cites, threshold, out_png, period):
    fig, ax = _fig(3.25, 3.15)
    ratio = (cites[period] / threshold[period]) * 100
    ratio = ratio.dropna().sort_values()
    colors = ["#B4A7D6" if v >= 100 else "#A9D18E" for v in ratio]
    ax.barh(range(len(ratio)), ratio, color=colors, height=0.7)
    for i, v in enumerate(ratio):
        ax.text(v + 8, i, f"{v:.2f}%", va="center", fontsize=6, color=C_TEXT)
    ax.axvline(100, color="red", lw=1.6)
    ax.set_yticks(range(len(ratio)))
    ax.set_yticklabels([_cn(d) for d in ratio.index], fontsize=6.5)
    ax.set_xlabel("被引频次 / 1%阈值（%）", fontsize=8)
    ax.grid(axis="x", color=C_GRID, linewidth=0.6)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#B4A7D6", label="与ESI前1%的接近度"),
                       Patch(color="#A9D18E", label="与ESI前1%的差距"),
                       Patch(color="red", label="ESI前1%基线")],
              fontsize=6.5, loc="lower right", frameon=False)
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
        ax.text(v + 2, i, f"{v:.2f}%", va="center", fontsize=6, color=C_TEXT)
    ax.set_yticks(list(y))
    ax.set_yticklabels([_cn(d) for d in ratio.index], fontsize=6.5)
    ax.set_xlim(0, 105)
    ax.set_xlabel("占 1‰ 阈值比例（%）", fontsize=8)
    ax.grid(axis="x", color=C_GRID, linewidth=0.6)
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
    ax.grid(axis="x", color=C_GRID, linewidth=0.6)
    _save(fig, out_png)


def _infer_end_period(ledger_dir):
    """未显式指定当期时从产物目录名推断（out/202607、out/202605_复现 → 202607 / 202605）。"""
    m = re.search(r"(\d{6})", pathlib.Path(ledger_dir).name)
    return m.group(1) if m else None


def render_all(ledger_dir="out/202607", out_dir=None, n_periods=7, end_period=None):
    """渲染 16 学科 × 6 图 + 3 张概览图。

    窗口＝**当期往前 n_periods 期（含当期）**，与原件口径一致；end_period 缺省时从 ledger_dir
    名字推断 —— 不传会让复现历史期次时把图画到最新期（WH-DOC-13 的 P0）。
    """
    ledger_dir = pathlib.Path(ledger_dir)
    out_dir = pathlib.Path(out_dir or ledger_dir) / "charts"
    w = {m: pd.read_parquet(ledger_dir / "wide" / f"{m}.parquet") for m in
         ["total_cites", "papers", "cnci", "threshold_1pct", "top_papers", "proximity_1pct"]}
    thr_p = pd.read_parquet(ledger_dir / "wide" / "threshold_1permille.parquet")
    longdf = pd.read_parquet(ledger_dir / "ledger_long.parquet")
    q1q4 = pd.read_parquet(ledger_dir / "wide" / "q1q4.parquet")

    all_p = [str(c) for c in w["total_cites"].columns if str(c).isdigit()]
    filled = [c for c in all_p if w["total_cites"][c].notna().any()]
    end_period = end_period or _infer_end_period(ledger_dir)
    if end_period:
        filled = [c for c in filled if c <= str(end_period)]
    periods = filled[-n_periods:]
    delta_p = filled[-(n_periods + 1):]   # 多取一期：新增发文量走差分，否则首点 NaN
    P = periods[-1]
    rank_intl = longdf[(longdf.source == "rank_intl") & (longdf.metric == "rank_pct")] \
        .pivot(index="discipline", columns="period", values="value")
    rank_cn = longdf[(longdf.source == "rank_cn") & (longdf.metric == "rank_pct")] \
        .pivot(index="discipline", columns="period", values="value")

    made = []
    for d in DETAIL_TABLES:
        folder = out_dir / _slug(d)
        chart_rank_pct(rank_intl, rank_cn, d, folder / "rank_pct.png", periods)
        chart_cnci(w["cnci"], d, folder / "cnci.png", periods)
        chart_papers_delta(w["papers"], d, folder / "papers_new.png", delta_p)
        chart_cites_threshold(w["total_cites"], w["threshold_1pct"], d, folder / "cites_threshold.png", periods)
        chart_top_papers(w["top_papers"], d, folder / "top_papers.png", periods)
        chart_q_dist(q1q4, d, folder / "q_dist.png", P)
        made.append(d)

    ov = out_dir / "_overview"
    ynd_rank = pd.read_parquet(ledger_dir / "wide" / "ynd_rank.parquet")
    chart_ynd_rank(ynd_rank, ov / "ynd_rank.png", end_period=end_period, n=n_periods)
    chart_overview_1pct(w["total_cites"], w["threshold_1pct"], ov / "1pct.png", P)
    chart_overview_1permille(w["total_cites"], thr_p, w["proximity_1pct"], ov / "1permille.png", P)
    total = len(made) * 6 + 3
    print(f"charts: {len(made)} 学科 × 6 图 + 概览 3 张 = {total} 张 → {out_dir}"
          f"（窗口 {periods[0]}–{P}，{len(periods)} 期）")
    return total


if __name__ == "__main__":
    import sys
    ld = sys.argv[1] if len(sys.argv) > 1 else None
    if ld is None:
        outs = sorted(pathlib.Path("out").glob("20*/"), key=lambda p: p.name)
        ld = str(outs[-1]).replace("\\", "/")
    render_all(ld)
