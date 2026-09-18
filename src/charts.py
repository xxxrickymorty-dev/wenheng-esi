# -*- coding: utf-8 -*-
"""图表模板库 C1–C6：从台账序列重绘《学科信息参考》全部期次图。

样式口径（WH-DOC-13，2026-09-17 按第 4 期原件 1:1 复刻，见 `评审文档/13`）：
  1. 窗口＝**当期往前 7 期**（含当期）；期次标签写六位数字 `202507`，水平排列。
  2. 字体＝西文 **Times New Roman** + 中文 **宋体**（原件观感；服务器走 Noto Serif CJK）。
  3. **每点/每柱标数值**；图例**无框**——多系列在坐标区外顶部居中，单系列在坐标区外右上
     （不能再放坐标区**内**的右上：纵轴自适应后柱子会顶到轴顶，图例会压住柱子的数值标签）。
     数值标签自动避让（见 `_labels`）：标签之间、标签与图例/标题/刻度字一律不许重叠。
  4. 纵轴：图1 **反向**（百分位下降＝上升趋势）；**逐学科完全自适应**——范围只由本学科
     数据决定（外加个别必须可见的基准值，如图2 的 1.0），再按整齐步长取整成好读刻度。
     🔴 **不设任何固定常量**（见 `_auto_ylim`）。2026-09-18 Rick 定调：原件那套刻度是
     Excel 给化学调的，硬编码到别的学科又丑又裁数据。视觉上端另留一行标签的空
     （`reserve_top`），否则最顶上那行数值会顶出坐标区撞上图例。
  5. 颜色：系列1 蓝 `#4472C4`、系列2 绿 `#70AD47`、系列3 黄 `#FFC000`；只留左/下轴脊。

图幅固定 8.26×5.50 cm @300dpi — 与母版槽位一致，**不随原件截图比例改动**（改这里要跑全套验收）。
"""
import math
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


_LAYOUT_PAD = 0.6          # tight_layout 内边距：出图与量几何必须同一个口径
# ⚠️ 单位陷阱：`annotate(..., textcoords="offset points")` 的偏移量 `xyann` 是 **pt**，
# 而包围盒是 **px**（300dpi 下 1pt = 4.17px）。两者混用会差 4 倍 —— 这里把两套都写清楚。
_LABEL_DY_PT = 4                                   # _labels 默认上/下偏移（pt）
_LABEL_LINE_PT = FONT_SIZE * 1.35                  # 一行文字实占高度（pt，含上下留白）
_LABEL_PX = (_LABEL_DY_PT + _LABEL_LINE_PT) / 72.0 * plt.rcParams["figure.dpi"]   # ≈56px


def _relayout(fig):
    """按**出图口径**跑一次 tight_layout。

    🔴 量任何像素位置之前必须先跑：只有 `_save` 里才调 tight_layout，不跑就等于在
    **默认 subplots 位置**上量，跟真正出图的那张对不上（标签避让、图例避让全会算歪）。
    """
    try:
        fig.tight_layout(pad=_LAYOUT_PAD)
    except Exception:                       # noqa: BLE001  布局失败不该把出图整个挂掉
        pass


def _axes_h_px(ax):
    """坐标区高度（px）——走 figure 比例换算，不需要 renderer。"""
    fig = ax.figure
    return ax.get_position().height * fig.get_figheight() * fig.dpi


def _save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    _relayout(fig)
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


def _text_box(fig, artist):
    """量出单个文字的画布包围盒（px）。"""
    try:
        bb = artist.get_window_extent(fig.canvas.get_renderer())
    except Exception:                           # noqa: BLE001
        return None
    return bb if (bb.width > 0 and bb.height > 0) else None


def _ov_area(a, b):
    """两个包围盒的交叠面积（不相交＝0）。"""
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    return w * h if (w > 0 and h > 0) else 0.0


def _labels(ax, xs, ys, fmt="{:.2f}", dy=4, size=FONT_SIZE, dodge=True):
    """逐点标数值；正值标上方、负值自动标下方，并**自动避让**别压到任何字。

    🔴 必须防压字（rick 2026-09-18 截图：顶尖论文 27 压在「顶尖论文发文量」上）。
    两条线的数值贴在一起、或分组柱三根挨着时，标签比柱子还宽，按默认位置必叠。

    做法（贪心 + 取最优）：
      1. 全部先按默认位置放下，跑一次 `_relayout` 出图口径布局，再量**真实像素**包围盒；
      2. 逐个候选档位（一档＝一行字高）试抬，障碍物＝**已归位的标签 + 图例 + 标题 +
         轴标签 + 纵轴刻度字 + 同图前一次 `_labels` 放下的标签**；
      3. 取**框内重叠面积最小**的那一档；一样差就守原位（绝不会比不打理更差）；
      4. 允许最多越出坐标区顶两行 —— 轴顶留白只够一行，挤在顶部的两三个标签得摞起来；
         越出去那点空隙里除了图例/标题没别的东西，而那俩是障碍物，压上就会扣分。

    ⚠️ 单位陷阱：`xyann` 是 **pt**，包围盒是 **px**（300dpi 下差 4.17 倍），别混。
    ⚠️ 调用顺序必须把 `_title` / `_legend_*` / `_auto_ylim` 排在 `_labels` **之前**
       —— 它们任一改动都会移动标签的像素位置，先量后改等于白量。
    """
    fig = ax.figure
    prior = list(ax.texts)                  # 本图此前已放的标签（同图多次 _labels 时要互相避让）
    anns, ups = [], []
    for x, y in zip(xs, ys):
        if y is None or pd.isna(y):
            continue
        up = float(y) >= 0
        anns.append(ax.annotate(fmt.format(y) if fmt else str(y), (x, y),
                                textcoords="offset points",
                                xytext=(0, dy if up else -dy),
                                ha="center", va="bottom" if up else "top",
                                fontsize=size, color=C_TEXT))
        ups.append(up)
    if not anns or not dodge:
        return anns

    _relayout(fig)                          # 先按出图口径布局，量到的像素才对得上最终那张
    fig.canvas.draw()                       # 再画一次，让 transform / renderer 就位
    r = fig.canvas.get_renderer()
    fixed = []
    leg = ax.get_legend()
    if leg is not None:
        fixed.append(leg.get_window_extent(r))
    for t in (ax.title, ax.xaxis.label, ax.yaxis.label):
        if t.get_text().strip():
            bb = _text_box(fig, t)
            if bb is not None:
                fixed.append(bb)
    for t in prior:                         # 之前 _labels 放下的标签
        bb = _text_box(fig, t)
        if bb is not None:
            fixed.append(bb)
    for t in ax.get_yticklabels():          # 纵轴刻度字（标签贴轴时会被压）
        bb = _text_box(fig, t)
        if bb is not None:
            fixed.append(bb)
    for t in ax.get_xticklabels():          # 横轴期次字（负值标签往下走时会撞它，20260918 服务器实测）
        bb = _text_box(fig, t)
        if bb is not None:
            fixed.append(bb)

    gap = size * 1.35                       # 一档＝一行字高（**pt**！xyann 的单位是 pt，别塞 px）
    ab = ax.get_window_extent(r)            # 坐标区
    # 允许最多越出轴顶三行：轴顶留白只够一行，挤在顶部的几个标签要错落开才行；
    # 越出去那条带子里只有图例/标题（都在 fixed 里，压上会被扣分），而图例已抬到
    # 1.14（`_legend_top`），轴顶上方留了约 60px 的空带专供标签用。
    slack = gap / 72.0 * fig.dpi * 3
    top_lim = ab.y1 + slack
    bot_lim = ab.y0 - slack
    placed = []

    def _ov(bb):
        return (sum(_ov_area(bb, p) for p in placed)
                + sum(_ov_area(bb, p) for p in fixed))

    def _place(ann, up, base, k):
        ann.xyann = (0, base + (k * gap if up else -k * gap))
        ann.update_positions(r)
        return ann.get_window_extent(r)

    for ann, up in zip(anns, ups):
        base = dy if up else -dy
        best_k, best_ov, k_ok = 0, None, 0
        for k in range(0, 40):              # 粗搜：一档＝一行字高，够任何拥挤情况
            bb = _place(ann, up, base, k)
            if up:
                if bb.y1 > top_lim:         # 再抬就飞到标题区了 → 别抬了
                    break
            elif bb.y0 < bot_lim:           # 再降就沉到轴刻度字下方了 → 别降了
                break
            k_ok = k
            ov = _ov(bb)
            if best_ov is None or ov < best_ov:
                best_ov, best_k = ov, k
            if ov <= 0:
                break
        if best_ov:                         # 粗档之间还有缝（一行高 ≈ 39px）→ 再按 1/4 行细搜
            for j in range(-4, 5):
                k = best_k + j / 4.0
                if not (0 <= k <= k_ok):
                    continue
                ov = _ov(_place(ann, up, base, k))
                if ov < best_ov:
                    best_ov, best_k = ov, k
                if ov <= 0:
                    break
        # 框内**重叠最少**的那一档；实在躲不开也只会退回原位，不会比原来更差
        placed.append(_place(ann, up, base, best_k))
    return anns


def _xticks(ax, periods):
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels([str(p) for p in periods], fontsize=FONT_SIZE)


# ---------- 纵轴自适应（原件口径＝Excel 自动轴：按本学科数据定范围）----------
_NICE_MULTS = (1, 2, 2.5, 5, 10)
_INT_MULTS = (1, 2, 5, 10)          # 计数值：不许出现 2.5 这种步长


def _nice_step(span, intervals, integer=False):
    """挑一个整齐步长，使区间数 ≤ intervals（刻度数 ≤ intervals+1）。"""
    span = abs(float(span)) or 1.0
    intervals = max(1, int(intervals))
    raw = span / intervals
    mag = 10.0 ** math.floor(math.log10(raw))
    if integer:
        mag = max(mag, 1.0)          # 整数步长最小 1
    for m in (_INT_MULTS if integer else _NICE_MULTS):
        s = m * mag
        if s >= raw - 1e-12 and span / s <= intervals + 1e-9:
            return s
    s = mag * 10
    while span / s > intervals:
        s *= 2
    return s


def _auto_ylim(ax, series, include=None, intervals=5, pad=0.08, lo_pad=None,
               hi_pad=None, floor_zero=False, zero_base=False, integer=False,
               clamp_zero=True, fmt=None, invert=False, reserve_top=_LABEL_PX,
               reserve_bottom=None):
    """按**本学科数据**动态定纵轴（＝原件 Excel 自动轴的口径）。

    🔴 不要退回固定常量。原件那套刻度是 Excel 给**化学**调的，硬编码到全部学科会出事 ——
    实测 16 学科里 15 个的「顶尖论文量」落在 30–45 之外（药理学只有 1–4，柱子缩成一条线），
    14 个的排名百分位落在 20–40% 之外，还有 4 个学科的 Q1 占比 >60% 被直接裁掉。

    include     —— 必须出现在轴内的额外值（图2 的基准线 1.0）；
    floor_zero  —— 下界钉死 0（柱状图要有零基准）；
    zero_base   —— 把 0 并进数据范围（图3 增量可正可负）；
    clamp_zero  —— 数据本身非负时，轴下界不跌破 0（默认开；图3 有负值时自动失效）；
    invert      —— 反向轴（图1：百分位越小＝排名越好＝越靠上）；
    reserve_top —— 在**视觉上端**多留这么高的空（px），给最顶上那行数值标签用。
                   只把 `set_ylim` 那一端往外挪，**刻度一个不动**（刻度仍按整齐步长排），
                   所以观感不变、不会多出一个难看的半格刻度。不需要留就传 None。
    reserve_bottom —— 同理，留给**视觉下端**那行标签（图3 的负增量，标签标在柱下方，
                   不留位就会压到横轴期次字）。默认 None＝不留。
    返回刻度列表；无数据时返回 None。
    """
    vals = []
    for s in series:
        vals.extend(pd.to_numeric(pd.Series(s), errors="coerce").dropna().tolist())
    if include is not None:
        vals.extend(list(include) if isinstance(include, (list, tuple)) else [include])
    vals = [float(v) for v in vals if v is not None and not pd.isna(v)]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    if zero_base:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if floor_zero:
        lo = 0.0
    span = hi - lo
    if span <= 0:                      # 全平序列：造个假跨度，别把图压成一条线
        span = max(abs(hi), abs(lo), 1.0) * 0.2
        lo, hi = lo - span / 2, hi + span / 2
        span = hi - lo
    if floor_zero and lo_pad is None:
        q_lo = lo                                   # 柱状图：下界就是 0，不留白
    else:
        q_lo = lo - span * (pad if lo_pad is None else lo_pad)
    q_hi = hi + span * (pad if hi_pad is None else hi_pad)
    if clamp_zero and lo >= 0:
        q_lo = max(q_lo, 0.0)                       # 非负数没必要把轴拉进负区
    step = _nice_step(q_hi - q_lo, intervals, integer)
    t_lo = round(math.floor(q_lo / step + 1e-9) * step, 10)
    t_hi = round(math.ceil(q_hi / step - 1e-9) * step, 10)
    n = int(round((t_hi - t_lo) / step))
    ticks = [round(t_lo + i * step, 10) for i in range(n + 1)]
    y_lo, y_hi = t_lo, t_hi                     # 轴范围（可能比分度范围略宽）
    if (reserve_top or reserve_bottom) and n > 0:
        # 视觉上/下端多留一行标签的高度。不留的话，最顶上的柱子/点的数值标签会顶出
        # 坐标区撞上图例（rick 2026-09-18 截图：顶尖论文 27 压在「顶尖论文发文量」上），
        # 最底下的负值标签会沉下去压在横轴期次字上（同日服务器字体下实测）。
        # 只挪 set_ylim，不动 ticks —— 既不破观感，也不会多出半格刻度。
        _relayout(ax.figure)                    # 图例/标题已就位，量到的才是出图后的高度
        h = _axes_h_px(ax)
        if h > 0:
            span_t = t_hi - t_lo
            if reserve_top:
                extra = reserve_top / h * span_t
                if invert:                      # 反向轴：视觉上端＝数值小的一端
                    y_lo = min(y_lo, lo - extra)
                else:
                    y_hi = max(y_hi, hi + extra)
            if reserve_bottom and lo < 0:       # 只有真有负值（标签标在点下方）才留
                extra = reserve_bottom / h * span_t
                if invert:                      # 反向轴：视觉下端＝数值大的一端
                    y_hi = max(y_hi, hi + extra)
                else:
                    y_lo = min(y_lo, lo - extra)
    if invert:
        ax.set_ylim(y_hi, y_lo)
    else:
        ax.set_ylim(y_lo, y_hi)
    ax.set_yticks(ticks)
    if fmt:
        ax.set_yticklabels([fmt.format(t) for t in ticks])
    return ticks


def _legend_top(ax, ncol=2):
    """多系列折线：**坐标区外**顶部居中、横排、无框（原件观感）。

    🔴 必须与轴顶**留出一段距离**（`borderaxespad` ≈1.6 字高 ≈46px，别贴上去）：
    贴上去等于把轴顶那条带子整条封死，数值标签就没有上升通道了（2026-09-18 实测图 6：
    中间那组的标签抬一档正好撞上图例，只能退而求其次留 400px² 的重叠）。
    但**不能抬太高**（试过 bbox_to_anchor=1.14）：抬到 1.14 就顶到标题上，
    16 学科 × 2 张图全部「标题压图例」。外移量走 borderaxespad 最稳。
    """
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=ncol, frameon=False,
              fontsize=FONT_SIZE, handlelength=1.7, handletextpad=0.4,
              columnspacing=1.2, borderaxespad=1.6)


def _legend_ur(ax, ncol=1):
    """单系列柱状图：图例放在**坐标区之外**的顶部右侧（原件口径）。

    🔴 不能放坐标区**内**的右上（原实现 `loc="upper right"`）：纵轴改成逐学科自适应后，
    柱子常常顶到轴顶，图例就跟最后一根柱的数值标签叠在一起（rick 2026-09-18 截图指正，
    Environment/Ecology 顶尖论文 27 压在「顶尖论文发文量」上）。
    """
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=ncol, frameon=False,
              fontsize=FONT_SIZE, handlelength=1.2, handletextpad=0.4,
              columnspacing=1.0, borderaxespad=0.2)


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
    _title(ax, "国内外排名百分位趋势")
    _legend_top(ax)
    # 反向轴：百分位越小＝排名越好＝越靠上；范围逐学科自适应
    # （轴放最后：_auto_ylim 要按 tight_layout 后的真实高度算「轴顶留白」）
    _auto_ylim(ax, [ri, rc], intervals=4, pad=0.06, fmt="{:g}%", invert=True)
    # 数值标签最后放：要躲开上面已定好的轴/标题/图例（两条线贴近时标签必压）
    _labels(ax, x, ri, "{:.2f}%")
    _labels(ax, x, rc, "{:.2f}%")
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
    _title(ax, "CNCI 变化情况")
    _legend_top(ax)
    # 基准线 1.0 必须始终可见（它是 CNCI 的判读参照），故 include 进来；下侧多留白
    _auto_ylim(ax, [v], include=[1.0], intervals=5, pad=0.05, lo_pad=0.12, fmt="{:g}")
    # 先放基准线那一排「1」，CNCI 值再来躲 —— 两者数值接近时才不会叠
    _labels(ax, x, base, "{:.0f}")
    _labels(ax, x, v, "{:.2f}")
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
    _title(ax, "新增发文量（篇）")
    _legend_ur(ax)
    # 增量可正可负 → 0 必须在轴内；计数值 → 整数刻度；负值标签标在柱下方，下端也要留位
    _auto_ylim(ax, [d], zero_base=True, intervals=6, pad=0.08, integer=True,
               fmt="{:.0f}", reserve_bottom=_LABEL_PX)
    _labels(ax, x, d, "{:.0f}")
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
    _title(ax, "被引频次与 ESI 阈值变化")
    _legend_top(ax, ncol=2)   # 双系列折线 → 顶部居中（原件口径；原先误用右上，轴收紧后会压字）
    _auto_ylim(ax, [c, t], intervals=5, pad=0.06, fmt="{:,.0f}")
    _labels(ax, x, c, "{:.0f}")   # 原件数据标签无千分位（轴刻度才有）
    _labels(ax, x, t, "{:.0f}")
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
    _title(ax, "顶尖论文量（篇）")
    _legend_ur(ax)
    # 原件是截断轴（不从 0 起），保留这个观感：下界跟着本学科最小值走
    _auto_ylim(ax, [v], intervals=7, pad=0.06, integer=True, fmt="{:.0f}")
    _labels(ax, x, v, "{:.0f}")
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
    pos_of = {}
    for k, (ent, lab, col) in enumerate(Q_ENTITIES):
        pos = [c - group_w / 2 + width / 2 + k * width for c in centers]
        pos_of[ent] = pos
        ax.bar(pos, vals[ent], width=width * 0.92, color=col, label=lab)
    _style(ax)
    ax.set_xticks(centers)
    ax.set_xticklabels(["Q1", "Q2", "Q3", "Q4"], fontsize=FONT_SIZE)
    flat = [v for row in vals.values() for v in row]
    _title(ax, "学科发文期刊分区占比情况")
    _legend_top(ax, ncol=3)              # 原件图 6 图例在顶部居中（不是右上）
    # 占比柱状图：必须有零基准，上界跟本学科最大值走
    _auto_ylim(ax, [flat], floor_zero=True, intervals=6, pad=0.05, integer=True, fmt="{:.0f}")
    # 标签必须在轴/标题/图例定后再放（_labels 要靠真实像素位置避让）
    for ent, _, _ in Q_ENTITIES:
        # {:g} 按数据原样出位数：原件里既有 57.51% 也有 11.7% / 7.9%
        _labels(ax, pos_of[ent], vals[ent], "{:g}%", dy=3, size=6.5)
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
