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
import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.transforms import Bbox

try:
    from parse_ledger import DISCIPLINES_CN
except ImportError:  # 直接运行时的兜底
    DISCIPLINES_CN = {}

import college_stats  # noqa: E402


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


_PAD_RATIO = 0.20      # 真碰撞判定：障碍外扩比例（按一行字高）。必须**小于**柱标签基线间隙
                       # （`dy=4pt`≈16.7px，0.20 行≈7.9px），否则柱标签会被自己的柱子判成压字
_SOFT_RATIO = 0.55     # 数值标签之间的「舒适间距」（按一行字高）——真碰撞/网格线都打平时按它择优
_GRID_BAND_PX = 3.0    # 网格线等效厚度（px）：标签压上它就记压线（否则数字像被划了删除线）


def _inflate(bb, px):
    """包围盒四周外扩 px —— 障碍物用它，把「刚好不压」变成「留出可见间隙」。"""
    return Bbox.from_extents(bb.x0 - px, bb.y0 - px, bb.x1 + px, bb.y1 + px)


def _labels(ax, xs, ys, fmt="{:.2f}", dy=4, size=FONT_SIZE, dodge=True, two_sided=True,
            color=None):
    """逐点标数值；默认正值标上方、负值标下方，并**自动避让**别压到任何字。

    🔴 必须防压字（rick 2026-09-18 截图：顶尖论文 27 压在「顶尖论文发文量」上）。
    两条线的数值贴在一起、或分组柱三根挨着时，标签比柱子还宽，按默认位置必叠。

    做法（贪心 + 取最优）：
      1. 全部先按默认位置放下，跑一次 `_relayout` 出图口径布局，再量**真实像素**包围盒；
      2. 逐个候选档位（一档＝一行字高）试抬/试降，障碍物＝**已归位的标签 + 图例 + 标题 +
         轴标签 + 纵轴刻度字 + 横轴期次字 + 柱体 + 横网格线 + 同图前一次 `_labels` 的标签**；
      3. 取**框内重叠面积最小**的那一档；一样差就守原位（绝不会比不打理更差）；
      4. 允许最多越出坐标区顶三行 —— 轴顶留白只够一行，挤在顶部的两三个标签得摞起来；
         越出去那点空隙里除了图例/标题没别的东西，而那俩是障碍物，压上就会扣分。

    🔴 三条 2026-09-18 加深的防线（Rick 截图：图例压数字 / 两个数字贴成一片）：
      · **障碍外扩留缝**（`_PAD_RATIO`）：只判「不相交」不够 —— 实测 Mathematics 的
        `5490`×`5478` 只差 6.2px，框上不压、看着就是叠的。判定时把障碍物放大，
        逼出可见间隙。
      · **双向落位**（`two_sided`）：默认按正负号定上下，但两条线数值接近时
        （图4 被引频次 vs ESI 阈值）**都在上方**就必然挤。现在两侧都试、取重叠小的那侧，
        同分仍守自然侧（观感不变）。所以 down 侧必须同时改 `va`。
      · **网格线当障碍**：横网格线穿过数字＝看着像划掉。把每条网格线扩成一条细带计入
        重叠面积，标签能躲就躲（软约束：够小，不会为躲线而牺牲真压字）。
      · **柱体当障碍**：柱状图不许把标签沉进柱子（否则双向落位会把标签塞进蓝柱里）。
      · **标签当障碍**：label 全体作为 obstacle，避免两组标签交叉。

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
                                fontsize=size, color=(color or C_TEXT)))
        ups.append(up)
    if not anns or not dodge:
        return anns

    _relayout(fig)                          # 先按出图口径布局，量到的像素才对得上最终那张
    fig.canvas.draw()                       # 再画一次，让 transform / renderer 就位
    r = fig.canvas.get_renderer()
    ab = ax.get_window_extent(r)            # 坐标区
    fixed = []                              # 「真障碍」：压上就是压字
    label_prior = []                        # 其中「别的数值标签」单拎出来，供三级目标里的舒适间距用
    legend_box = None                       # 图例包围盒（无框时不可见，但贴太近观感仍是「图例压数字」）
    leg = ax.get_legend()
    if leg is not None:
        legend_box = leg.get_window_extent(r)
        fixed.append(legend_box)
    for t in (ax.title, ax.xaxis.label, ax.yaxis.label):
        if t.get_text().strip():
            bb = _text_box(fig, t)
            if bb is not None:
                fixed.append(bb)
    for t in prior:                         # 之前 _labels 放下的标签
        bb = _text_box(fig, t)
        if bb is not None:
            fixed.append(bb)
            label_prior.append(bb)
    for t in ax.get_yticklabels():          # 纵轴刻度字（标签贴轴时会被压）
        bb = _text_box(fig, t)
        if bb is not None:
            fixed.append(bb)
    for t in ax.get_xticklabels():          # 横轴期次字（负值标签往下走时会撞它，20260918 服务器实测）
        bb = _text_box(fig, t)
        if bb is not None:
            fixed.append(bb)
    for p in ax.patches:                    # 柱体：标签不许沉进柱子里
        try:
            bb = p.get_window_extent(r)
        except Exception:                   # noqa: BLE001
            continue
        if bb.width > 0 and bb.height > 0:
            fixed.append(bb)
    bands = []                              # 「次级障碍」：横网格线，能躲就躲，但绝不为它牺牲真碰撞
    y0d, y1d = ax.get_ylim()
    for tv in ax.get_yticks():
        if not (y0d <= tv <= y1d):
            continue
        gy = ax.transData.transform((0, tv))[1]
        bands.append(Bbox.from_extents(ab.x0, gy - _GRID_BAND_PX,
                                       ab.x1, gy + _GRID_BAND_PX))

    gap = size * 1.35                       # 一档＝一行字高（**pt**！xyann 的单位是 pt，别塞 px）
    pad_px = gap * _PAD_RATIO / 72.0 * fig.dpi
    soft_px = gap * _SOFT_RATIO / 72.0 * fig.dpi
    # 允许最多越出轴顶三行：轴顶留白只够一行，挤在顶部的几个标签要错落开才行；
    # 越出去那条带子里只有图例/标题（都在 fixed 里，压上会被扣分），而图例已抬到
    # 1.14（`_legend_top`），轴顶上方留了约 60px 的空带专供标签用。
    slack = gap / 72.0 * fig.dpi * 3
    top_lim = ab.y1 + slack
    bot_lim = ab.y0 - slack
    placed = []

    def _ov(bb):
        """三级目标 `(真碰撞, 网格线压线, 标签间舒适度)`——**严格按这个顺序比较**。

        🔴 不能合成一个总分：
          · 合成之后「躲开一条 6px 网格线」和「撞进图例」都是几百 px²，标签会为了躲线
            主动钻到图例底下（2026-09-18 实测：网格线穿标签 51→0 的同时，标签×图例
            从 3 处涨到 12 处）。所以真碰撞必须优先。
          · 再加第三级：真碰撞和网格线都打平时（都是 0），还要比**谁留的余量更大**。
            否则会挑出「框上不压、看着就是叠的」那种解 —— Mathematics 实测：`5347` 为躲
            一条网格线往上抬一行，离上方 `5492` 只剩 13.9px，而**往下是空的**（净空 113px），
            只是两侧都是 0 分，前两级比不出来。
        """
        real = sum(_ov_area(bb, _inflate(p, pad_px)) for p in placed)
        real += sum(_ov_area(bb, _inflate(p, pad_px)) for p in fixed)
        grid = sum(_ov_area(bb, b) for b in bands)
        soft = sum(_ov_area(bb, _inflate(p, soft_px)) for p in placed)
        soft += sum(_ov_area(bb, _inflate(p, soft_px)) for p in label_prior)
        if legend_box is not None:
            # 图例无框（原件口径）→ 包围盒不可见，可「框上不压、看着还是贴」。服务器字体实测：
            # 顶尖论文图 44/27/29 三个柱标离图例框只有 12.0–15.8px，Rick 就是这么截的图。
            soft += _ov_area(bb, _inflate(legend_box, soft_px))
        return real, grid, soft

    def _place(ann, side, base, k):
        """side=True 向上、False 向下；向下必须同时把 va 翻成 top，否则文字朝反方向长。"""
        ann.set_va("bottom" if side else "top")
        ann.xyann = (0, base + (k * gap if side else -k * gap))
        ann.update_positions(r)
        return ann.get_window_extent(r)

    def _best_on(ann, side, base):
        """在一侧里找目标最小的档位；返回 ((真碰撞, 网格线, 舒适度), k)。"""
        b_k, b_ov, k_ok = 0, None, 0
        for k in range(0, 40):              # 粗搜：一档＝一行字高，够任何拥挤情况
            bb = _place(ann, side, base, k)
            if side:
                if bb.y1 > top_lim:         # 再抬就飞到标题区了 → 别抬了
                    break
            elif bb.y0 < bot_lim:           # 再降就沉到轴刻度字下方了 → 别降了
                break
            k_ok = k
            ov = _ov(bb)
            if b_ov is None or ov < b_ov:
                b_ov, b_k = ov, k
            if ov <= (0, 0, 0):
                break
            if k >= 3 and ov[0] <= 0:
                break                       # 真碰撞已清零：往更远处挪 >3 行只为躲网格线/找空隙，不值当
        if b_ov and (b_ov[0] or b_ov[2]):   # 还有真碰撞或不够宽松 → 按 1/4 行细搜
            for j in range(-4, 5):
                k = b_k + j / 4.0
                if not (0 <= k <= k_ok):
                    continue
                ov = _ov(_place(ann, side, base, k))
                if ov < b_ov:
                    b_ov, b_k = ov, k
                if ov <= (0, 0, 0):
                    break
        return (b_ov if b_ov is not None else (0.0, 0.0, 0.0)), b_k

    for ann, up0 in zip(anns, ups):
        cands = []
        for side in ((True, False) if two_sided else (up0,)):
            ov, k = _best_on(ann, side, dy if side else -dy)
            # 第 4 元＝「是否离开了自然侧」：三项分数都一样时守自然侧，观感与原件一致
            cands.append((ov[0], ov[1], ov[2], 0 if side == up0 else 1, side, k))
        cands.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
        _, _, _, _, side, k = cands[0]
        # 目标最小的那一档；实在躲不开也只会退回原位，不会比原来更差
        placed.append(_place(ann, side, dy if side else -dy, k))
    return anns
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
    🔴 `borderaxespad` 必须给够：0.2 时图例底边只离轴顶 5.8px —— 柱顶那行数字顶格的
    时候，两者在 8.26cm 宽的图里只隔约 1.3mm，肉眼就是「图例压着数字」（同日实测
    Chemistry 44 / EnvEcology 27 / Engineering 29 三处，间隙仅 15–19px）。给到 1.0
    （≈29px）才拉开；但**不能再大**，再大就顶到标题上（`_title` 的 pad 只有 24pt）。
    """
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=ncol, frameon=False,
              fontsize=FONT_SIZE, handlelength=1.2, handletextpad=0.4,
              columnspacing=1.0, borderaxespad=1.0)


# ---------- C1 国内外排名百分位趋势 ----------
def chart_rank_pct(rank_intl, rank_cn, disc, out_png, periods, *, invert=None):
    """`invert` 是给**灵活报告 spec** 用的语义开关（None＝本例的原口径：反向轴）。

    🔴 所有 `*` 之后的语义参数都遵循同一约定：**None ＝ 保持本函数原有行为**。
    复刻报告永不传它们，因此复刻出图逐字节不变（有 PNG 哈希判据守着）。
    """
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
    _auto_ylim(ax, [ri, rc], intervals=4, pad=0.06, fmt="{:g}%",
               invert=(True if invert is None else bool(invert)))
    # 数值标签最后放：要躲开上面已定好的轴/标题/图例（两条线贴近时标签必压）
    _labels(ax, x, ri, "{:.2f}%")
    _labels(ax, x, rc, "{:.2f}%")
    _save(fig, out_png)


# ---------- C2 CNCI 变化 ----------
def chart_cnci(cnci, disc, out_png, periods, *, include=None):
    """`include`：必须出现在轴内的参照值。None ＝ 本函数原口径（锚住国际均值 1.0）。"""
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
    _auto_ylim(ax, [v], include=([1.0] if include is None else list(include)),
               intervals=5, pad=0.05, lo_pad=0.12, fmt="{:g}")
    # 先放基准线那一排「1」，CNCI 值再来躲 —— 两者数值接近时才不会叠
    _labels(ax, x, base, "{:.0f}")
    _labels(ax, x, v, "{:.2f}")
    _save(fig, out_png)


# ---------- C3 新增发文量 ----------
def chart_papers_delta(papers, disc, out_png, periods, *, zero_base=None):
    """periods 须含「窗口外上一期」：增量＝相邻期差分，只取 7 期会让首点变 NaN。

    `zero_base`：None ＝ 本函数原口径（增量可正可负，0 必须在轴内）。
    """
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
    _auto_ylim(ax, [d], zero_base=(True if zero_base is None else bool(zero_base)),
               intervals=6, pad=0.08, integer=True,
               fmt="{:.0f}", reserve_bottom=_LABEL_PX)
    _labels(ax, x, d, "{:.0f}")
    _save(fig, out_png)


# ---------- C4 被引频次与 ESI 阈值 ----------
def chart_cites_threshold(cites, threshold, disc, out_png, periods, *, zero_base=None,
                          include=None):
    """`zero_base` / `include`：None ＝ 本函数原口径（不锚零、不加参照值）。"""
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
    _auto_ylim(ax, [c, t], intervals=5, pad=0.06, fmt="{:,.0f}",
               zero_base=(False if zero_base is None else bool(zero_base)),
               include=(None if include is None else list(include)))
    _labels(ax, x, c, "{:.0f}")   # 原件数据标签无千分位（轴刻度才有）
    _labels(ax, x, t, "{:.0f}")
    _save(fig, out_png)


# ---------- C5 顶尖论文量 ----------
def chart_top_papers(top, disc, out_png, periods, *, floor_zero=None):
    """`floor_zero`：None ＝ 本函数原口径（截断轴，下界跟本学科最小值走，保留原件观感）。"""
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
    _auto_ylim(ax, [v], intervals=7, pad=0.06, integer=True, fmt="{:.0f}",
               floor_zero=(False if floor_zero is None else bool(floor_zero)))
    _labels(ax, x, v, "{:.0f}")
    _save(fig, out_png)


# ---------- C6 期刊分区占比（单期快照，三个口径并列） ----------
Q_ENTITIES = [("云南大学", "云南大学", C_BLUE),
              ("中国大陆", "中国大陆", C_GREEN),
              ("全球", "国际", C_YELLOW)]   # 数据里叫「全球」，原件外显「国际」


def chart_q_dist(q1q4, disc, out_png, period, *, floor_zero=None):
    """`floor_zero`：None ＝ 本函数原口径（占比柱状图必须有零基准）。"""
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
    _auto_ylim(ax, [flat], floor_zero=(True if floor_zero is None else bool(floor_zero)),
               intervals=6, pad=0.05, integer=True, fmt="{:.0f}")
    # 标签必须在轴/标题/图例定后再放（_labels 要靠真实像素位置避让）
    for ent, _, _ in Q_ENTITIES:
        # {:g} 按数据原样出位数：原件里既有 57.51% 也有 11.7% / 7.9%
        _labels(ax, pos_of[ent], vals[ent], "{:g}%", dy=3, size=6.5)
    _save(fig, out_png)


# ---------- 概览图（对标第4期原生图表）：带数据表的排名图 / 发展趋势图 ----------
def _save_raw(fig, path):
    """不跑 tight_layout 的出图（表格式版面自己摆位）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)


def _data_table(fig, rect, col_labels, row_labels, rows, *, fontsize=6.2, color=None):
    """在 fig 指定区域放一张数据表（第4期原生图表下方的数据表样式）。"""
    tax = fig.add_axes(rect)
    tax.axis("off")
    text = [[("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))) for v in row] for row in rows]
    tb = tax.table(cellText=text, rowLabels=row_labels, colLabels=col_labels,
                   cellLoc="center", rowLoc="center", loc="center", bbox=[0, 0, 1, 1])
    tb.auto_set_font_size(False)
    tb.set_fontsize(fontsize)
    for cell in tb.get_celld().values():
        cell.set_linewidth(0.4)
        cell.set_edgecolor("#BFBFBF")
        try:
            cell.get_text().set_color(color or C_TEXT)
        except AttributeError:
            pass
    return tb


def chart_rank_table(ynd_rank, out_png, end_period=None, n=7):
    """我校 ESI 排名情况（对标第4期 chart1：图内标题 + 逐点数值 + 底部图例 + 数据表，双轴反序）。

    配色对齐原件：国内排名=橙、国内高校排名=金、国际排名=蓝（右轴）；轴范围亦照原件
    固定（左 120–170、右 400–1400，反序），7 期窗口内数据形貌与原件一致。
    """
    df = ynd_rank.set_index("period").sort_index()
    df = df[df["rank_intl"].notna() | df["rank_cn"].notna()]
    if end_period:
        df = df[df.index <= str(end_period)]
    df = df.tail(n)
    periods = [str(p) for p in df.index]

    # 字号/颜色按 rick 反馈加大加深（只影响本图；全局常量不动）
    ink = "#1F1F1F"
    fig = Figure(figsize=(5.6, 4.9))
    FigureCanvasAgg(fig)   # 🔴 _labels 要量像素包围盒，裸 Figure 的 FigureCanvasBase 没有 get_renderer
    ax = fig.add_axes([0.15, 0.47, 0.64, 0.38])
    ax2 = ax.twinx()
    x = list(range(len(df)))
    ln1, = ax.plot(x, df["rank_cn"], marker="o", ms=4.5, lw=1.8, color="#ED7D31", label="国内排名")
    ln2, = ax.plot(x, df["rank_cn_uni"], marker="o", ms=4.5, lw=1.8, color="#FFC000", label="国内高校排名")
    ln3, = ax2.plot(x, df["rank_intl"], marker="o", ms=4.5, lw=1.8, color="#4472C4", label="国际排名（右标）")
    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=9)
    ax.set_xlim(-0.6, len(df) - 0.4)
    # 轴范围对齐原件（均为反序：名次越小越靠上）
    ax.set_ylim(170, 120)
    ax2.set_ylim(1400, 400)
    ax.set_yticks(list(range(120, 171, 5)))
    ax2.set_yticks(list(range(400, 1401, 200)))
    ax.grid(axis="y", color=C_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
        ax2.spines[s].set_visible(False)
    ax.tick_params(length=0, labelsize=9, colors=ink)
    ax2.tick_params(length=0, labelsize=9, colors=ink)
    ax.set_title("我校ESI排名情况", fontsize=13, color=ink, pad=10)
    # 图例：底部左侧（原件样式）；挂在 ax 上，_labels 才能把它当障碍避让
    ax.legend([ln1, ln2, ln3], [l.get_label() for l in (ln1, ln2, ln3)],
              fontsize=9, loc="upper left", bbox_to_anchor=(-0.12, -0.13),
              ncol=3, frameon=False, labelcolor=ink)
    # 逐点数值（国内/高校左轴，国际右轴）——必须在标题/图例/轴范围之后再放
    _labels(ax, x, [float(v) for v in df["rank_cn"]], "{:.0f}", size=8.0, color=ink)
    _labels(ax, x, [float(v) for v in df["rank_cn_uni"]], "{:.0f}", size=8.0, color=ink)
    _labels(ax2, x, [float(v) for v in df["rank_intl"]], "{:.0f}", size=8.0, color=ink)
    _data_table(fig, [0.25, 0.05, 0.60, 0.26], periods,
                ["国内排名", "国内高校排名", "国际排名（右标）"],
                [[df["rank_cn"].get(p) for p in df.index],
                 [df["rank_cn_uni"].get(p) for p in df.index],
                 [df["rank_intl"].get(p) for p in df.index]],
                fontsize=8.0, color=ink)
    _save_raw(fig, out_png)


def chart_ynd_rank(ynd_rank, out_png, end_period=None, n=7):
    """兼容别名：灵活报告 spec 的 `ynd_rank` 图型 → 一律走第4期格式的 `chart_rank_table`。"""
    return chart_rank_table(ynd_rank, out_png, end_period=end_period, n=n)


def _trend_data_table(fig, rect, col_labels, row_labels, rows, row_colors, *,
                      label_frac=0.22, fontsize=8.2, ink="#1F1F1F"):
    """Excel 式「数据表」：贴在绘图区正下方，数据列与折线数据点一一对齐。

    行标签列（学科名）向左伸出坐标区、文字用系列色 —— 原件**没有图例**，这张表就是图例
    （第 3/4/5 期原生图的 dTable：showOutline/HorzBorder/VertBorder/Keys 全开）。
    """
    tax = fig.add_axes(rect)
    tax.set_xlim(0, 1)
    tax.set_ylim(0, 1)
    tax.axis("off")
    ncol = len(col_labels)
    nr = len(rows) + 1
    cw = (1.0 - label_frac) / ncol
    rh = 1.0 / nr
    xs = [0.0, label_frac] + [label_frac + cw * (k + 1) for k in range(ncol)]
    for i in range(nr):
        y0 = 1.0 - (i + 1) * rh
        for j in range(ncol + 1):
            tax.add_patch(Rectangle((xs[j], y0), xs[j + 1] - xs[j], rh, fill=False,
                                    edgecolor=C_AXIS, lw=0.4))
    for j, lab in enumerate(col_labels):
        tax.text((xs[j + 1] + xs[j + 2]) / 2, 1 - rh / 2, str(lab), ha="center", va="center",
                 fontsize=fontsize, color=ink)
    for i, (name, row) in enumerate(zip(row_labels, rows)):
        yc = 1 - (i + 1.5) * rh
        tax.text(label_frac / 2, yc, name, ha="center", va="center",
                 fontsize=fontsize, color=row_colors[i])
        for j, v in enumerate(row):
            tax.text((xs[j + 1] + xs[j + 2]) / 2, yc, v, ha="center", va="center",
                     fontsize=fontsize, color=ink)
    return tax


def chart_trend_table(cites, thr_1permille, out_png, end_period=None, n=7, top_k=4,
                      entered=None):
    """我校主要学科近期发展趋势（对标第 3/4/5 期原生图：1‰ 接近度前 4 学科 + ESI1‰ 线 + 图下数据表）。

    与原件逐项对齐（其 chart XML 口径）：粗体标题；纵轴 0–100%、`0.00%` 两位小数；
    **无图例 / 无网格 / 无数据点标记**；数据表贴在图下、列与数据点对齐、行标签用系列色。
    系列顺序＝**进入 ESI 1% 的先后**（原件三期一致：化学→植物与动物学→环境生态学→工程学），
    由 `entered`（wide/entered_1pct.parquet）的首次在榜期给出；同期的按末列总被引降序兜底
    （矩阵左端截断会把老学科并列到同一期）。不传 `entered` 时退回按最新接近度降序。
    """
    df = (cites / thr_1permille * 100.0).copy()
    df.columns = [str(c) for c in df.columns]
    if end_period:
        df = df[[c for c in df.columns if c <= str(end_period)]]
    df = df.iloc[:, -n:]
    latest = df.iloc[:, -1].dropna().sort_values(ascending=False)
    picks = list(latest.index[:top_k])
    if entered is not None:
        def _first_in(d):
            if d not in entered.index:
                return "999999"
            for c in entered.columns:
                v = entered.loc[d, c]
                if v == v and float(v) > 0:          # v == v 用来排除 NaN
                    return str(c)
            return "999999"

        cw = cites if not end_period else cites[[c for c in cites.columns if str(c) <= str(end_period)]]
        cite_last = {}
        for d in picks:
            s = pd.to_numeric(cw.loc[d], errors="coerce").dropna() if d in cw.index else None
            cite_last[d] = float(s.iloc[-1]) if s is not None and len(s) else 0.0
        picks.sort(key=lambda d: (_first_in(d), -cite_last[d]))
    picked = df.loc[picks]
    periods = [str(c) for c in df.columns]
    # 原件配色＝Office 主题色按系列序（其 chart XML 只显式写了 #7030A0 与红）：化学=accent1、
    # 植物与动物学=#7030A0、环境生态学=accent3、工程学=accent4。
    # accent3 原色 #A5A5A5 太浅（rick 反馈颜色浅）→ 稍加深到 #8C8C8C（线/标签同色）。
    colors = [C_LIGHTBLUE, "#7030A0", "#8C8C8C", "#FFC000"]

    ink = "#1F1F1F"
    markers = ("o", "s", "^", "D")
    fig = Figure(figsize=(6.6, 4.5))
    FigureCanvasAgg(fig)   # 🔴 _labels 要量像素包围盒，裸 Figure 的 FigureCanvasBase 没有 get_renderer
    # 图区横向必须与下方数据表的数据列一一对齐（表数据区 = 0.062+0.910×0.22 … 0.972）
    ax = fig.add_axes([0.262, 0.485, 0.710, 0.375])
    for i, d in enumerate(picks):
        ax.plot(range(len(periods)), picked.loc[d], color=colors[i % len(colors)],
                lw=1.8, marker=markers[i % len(markers)], ms=4.5, label=_cn(d))
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels([])                   # 期次标签只在下方表头行出现一次（Excel 数据表同款）
    # 纵轴聚焦数据带（rick：几根线粘连）——0–100 会把 43–57% 挤成一条；100% 基线移出窗口，
    # 用右上角红字注明（全量 100% 在表格 ESI1‰ 行）。
    ax.set_ylim(25, 65)
    ax.set_yticks(range(25, 66, 5))
    ax.set_yticklabels([f"{v:.2f}%" for v in range(25, 66, 5)], fontsize=9)
    ax.text(1.0, 0.98, "ESI1‰ 基线 = 100%", transform=ax.transAxes, ha="right", va="top",
            color="#FF0000", fontsize=8)
    for s in ("top", "right", "bottom"):    # 底轴不画线：表格顶边框就是那条线（原件同款）
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, labelsize=9, colors=ink)
    ax.tick_params(axis="x", pad=2)
    ax.legend(fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 1.01),
              ncol=4, frameon=False, labelcolor=ink)
    title = fig.text(0.517, 0.975, "我校主要学科近期发展趋势", ha="center", va="top",
                     fontsize=13, color="#1F1F1F")
    # 宋体/Noto Serif 没有可命中的 bold 字面（matplotlib 会静默回退成常规字重）→ 用描边假粗，
    # 与原件「标题加粗」观感一致，且 Windows/Linux 两端表现一致。
    title.set_path_effects([path_effects.withStroke(linewidth=0.7, foreground="#1F1F1F")])
    # 数值标注：4 线 × 7 期全标会挤成一团（避让后数字离点太远）→ 每条线只标最后一期，
    # 全量数值在下方数据表（已加大加深）。ESI1‰ 基线不标。
    # 逐条单独放（dodge=False）：4 个末点纵向已拉开，直接贴在各自点上方；
    # 开避让反而会和前一个标签互相顶走，出现「数字跑到别条线头上」的错配。
    x = list(range(len(periods)))
    for d in picks:
        vals = [float(v) for v in picked.loc[d]]
        _labels(ax, [x[-1]], [vals[-1]], "{:.2f}%", size=8.0, color=ink, dodge=False)
    rows = [[("" if picked.loc[d, p] != picked.loc[d, p]
              else f"{float(picked.loc[d, p]):.2f}%") for p in periods] for d in picks]
    rows.append(["100%"] * len(periods))     # 原件 ESI1‰ 行是 0% 格式（不写两位小数）
    # 学科名统一墨色（rick：不要给学科字体上色）；ESI1‰ 基线行仍是红的
    _trend_data_table(fig, [0.062, 0.102, 0.910, 0.360], periods,
                      [_cn(d) for d in picks] + ["ESI1‰"], rows,
                      [ink] * len(picks) + ["#FF0000"])
    _save_raw(fig, out_png)


def chart_top_by_year(by_year, out_png, period):
    """顶尖论文年代分布（篇）（对标第4期 chart4：按出版年柱状）。"""
    s = by_year[period] if period in by_year.columns else by_year.iloc[:, -1]
    s = s.dropna()
    s = s[s > 0]
    fig, ax = _fig(4.4, 2.6)
    ax.bar(range(len(s)), [float(v) for v in s], color=C_ORANGE, width=0.66)
    for i, v in enumerate(s):
        ax.text(i, float(v) + 0.6, f"{int(v)}", ha="center", fontsize=6.2, color=C_TEXT)
    ax.set_xticks(range(len(s)))
    ax.set_xticklabels([str(i) for i in s.index], fontsize=FONT_SIZE)
    _style(ax)
    _title(ax, "顶尖论文年代分布（篇）")
    _save(fig, out_png)


def chart_top_by_subject(top_papers, out_png, period):
    """顶尖论文学科分布（篇）（对标第4期 chart5：按学科柱状）。"""
    s = top_papers[period] if period in top_papers.columns else top_papers.iloc[:, -1]
    s = s.dropna()
    s = s[s > 0].sort_values(ascending=False)
    fig, ax = _fig(4.6, 2.8)
    ax.bar(range(len(s)), [float(v) for v in s], color=C_BLUE, width=0.62)
    for i, v in enumerate(s):
        ax.text(i, float(v) + 0.6, f"{int(v)}", ha="center", fontsize=6.0, color=C_TEXT)
    ax.set_xticks(range(len(s)))
    ax.set_xticklabels([_cn(d) for d in s.index], fontsize=5.6, rotation=38, ha="right")
    _style(ax)
    _title(ax, "顶尖论文学科分布（篇）")
    _save(fig, out_png)


def chart_college_pie(stats, out_png, mode):
    """学院贡献度饼图（对标第4期两张）：mode='cites' 被引频次实心饼 / 'papers' 发文量环形。

    <1.5% 的份额合并为「其他（k 个单位）」，避免小份额标签挤成一团。
    """
    units = stats["units"]
    raw = [((u["cites"] if mode == "cites" else u["papers"]), u["unit"]) for u in units]
    total = sum(v for v, _u in raw) or 1
    TH = 0.015
    keep = [(v, u) for v, u in raw if v / total >= TH]
    small = [(v, u) for v, u in raw if v / total < TH]
    if small:
        keep.append((sum(v for v, _u in small), f"其他（{len(small)} 个单位）"))
    vals = [v for v, _u in keep]
    labels = [u for _v, u in keep]
    palette = ["#4472C4", "#A9D18E", "#FFC000", "#ED7D31", "#7030A0", "#00B0F0", "#C00000",
               "#548235", "#BF8F00", "#2E75B6", "#948A54", "#C55A11", "#5B9BD5", "#70AD47"]
    fig = Figure(figsize=(5.6, 3.6))
    ax = fig.add_axes([0.01, 0.01, 0.98, 0.98])
    ax.set_aspect("equal")
    wedges, _ = ax.pie(vals, startangle=90, counterclock=False,
                       colors=[palette[i % len(palette)] for i in range(len(vals))],
                       wedgeprops=dict(width=0.42 if mode == "papers" else 1.0,
                                       edgecolor="white", linewidth=0.5))
    for w, lab, v in zip(wedges, labels, vals):
        ang = math.radians((w.theta1 + w.theta2) / 2)
        x, y = math.cos(ang), math.sin(ang)
        ax.annotate(f"{lab}：{v / total * 100:.2f}%", xy=(x * 0.95, y * 0.95),
                    xytext=(x * 1.30, y * 1.30), ha="left" if x >= 0 else "right",
                    va="center", fontsize=6.2, color=C_TEXT,
                    arrowprops=dict(arrowstyle="-", color="#BFBFBF", lw=0.6))
    ax.set_xlim(-3.2, 3.2)
    ax.set_ylim(-1.8, 1.8)
    _save_raw(fig, out_png)


# ---------- 预测章配图：实际 + 模型（拟合历史 + 递推预测）----------
def chart_forecast(hist_periods, hist, model_hist, fut_periods, fut,
                   labels, colors, out_png, grid=True, figsize=(7.4, 3.6)):
    """预测章「模型预测图」：两个指标各画「实际（实线）+ 模型（虚线，含历史拟合段）」。

    · `hist` / `model_hist` / `fut` 均为 **(指标1, 指标2)** 二元组；
    · `labels` / `colors` 四元组：指标1、指标1预测值、指标2、指标2预测值；
    · 模型历史段从首个有限拟合值画起（V1 口径前 6 期无拟合）。
    """
    fig, ax = _fig(*figsize)
    xh = list(range(len(hist_periods)))
    n_h = len(hist_periods)
    all_p = [str(p) for p in list(hist_periods) + list(fut_periods)]

    for j in range(2):
        ax.plot(xh, hist[j], color=colors[2 * j], lw=1.5, label=labels[2 * j], zorder=3)
        line_x, line_y = [], []
        for x, v in zip(xh, model_hist[j]):
            try:
                if math.isfinite(float(v)):
                    line_x.append(x)
                    line_y.append(float(v))
            except (TypeError, ValueError):
                continue
        if line_x:
            line_x = line_x + [n_h + k for k in range(len(fut_periods))]
            line_y = line_y + [float(v) for v in fut[j]]
            ax.plot(line_x, line_y, color=colors[2 * j + 1], lw=1.3, ls="--",
                    label=labels[2 * j + 1], zorder=2)

    xt = [i for i, p in enumerate(all_p) if p.endswith("01")]
    if len(xt) > 10:
        xt = xt[::2]
    ax.set_xticks(xt)
    ax.set_xticklabels([all_p[i] for i in xt], fontsize=6.2)
    ax.set_xlim(-0.6, len(all_p) - 0.4)
    _style(ax)
    if not grid:
        ax.grid(False)
    ax.legend(fontsize=6.8, loc="lower center", bbox_to_anchor=(0.5, -0.38),
              ncol=4, frameon=False)
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
def chart_overview_1permille(cites, thr_1permille, entered_1pct, out_png, period):
    """🔴 `entered_1pct` 必须是**事件表推导的 0/1 矩阵**，不是接近度。

    两者在第 1 期 202601 会差一个学科（数学）：接近度口径多算 → 图里多一条，
    而正文按事件表写 13 个，图文自相矛盾。口径源见 `parse_ledger.build_entered_1pct`。
    """
    # 字号/颜色按 rick 反馈加大加深（与排名图同规格；原图表图例在底部：chart2 legendPos=b）
    ink = "#1F1F1F"
    fig, ax = _fig(3.7, 2.95)
    entered = entered_1pct[period][entered_1pct[period] >= 1].index
    ratio = (cites[period][entered] / thr_1permille[period][entered] * 100).dropna().sort_values()
    gap = 100 - ratio
    y = range(len(ratio))
    ax.barh(y, ratio, color="#B4A7D6", height=0.7, label="1‰接近度")
    ax.barh(y, gap, left=ratio, color="#A9D18E", height=0.7, label="与前1‰差距")
    for i, v in enumerate(ratio):
        ax.text(v + 1.5, i, f"{v:.2f}%", va="center", fontsize=7.5, color=ink)
    ax.set_yticks(list(y))
    ax.set_yticklabels([_cn(d) for d in ratio.index], fontsize=8.5)
    ax.set_xlim(0, 105)
    ax.set_xlabel("占 1‰ 阈值比例（%）", fontsize=10, color=ink)
    ax.grid(axis="x", color=C_GRID, linewidth=0.6)
    ax.tick_params(axis="both", length=0, labelsize=8.5, colors=ink)
    ax.legend(fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.15),
              ncol=2, frameon=False, labelcolor=ink)
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
         ["total_cites", "papers", "cnci", "threshold_1pct", "top_papers",
          "proximity_1pct", "entered_1pct"]}
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
    chart_overview_1pct(w["total_cites"], w["threshold_1pct"], ov / "1pct.png", P)
    chart_overview_1permille(w["total_cites"], thr_p, w["entered_1pct"], ov / "1permille.png", P)
    # 对标第4期原生图表：排名（带数据表）、发展趋势（带数据表）、顶尖论文年代/学科分布
    chart_rank_table(ynd_rank, ov / "rank_table.png", end_period=end_period, n=n_periods)
    chart_trend_table(w["total_cites"], thr_p, ov / "trend_table.png", end_period=end_period,
                      n=n_periods, entered=w["entered_1pct"])
    chart_top_by_subject(w["top_papers"], ov / "top_by_subject.png", P)
    by_year_path = ledger_dir / "wide" / "top_by_year.parquet"
    if by_year_path.exists():
        chart_top_by_year(pd.read_parquet(by_year_path), ov / "top_by_year.png", P)
    cs = college_stats.load(ledger_dir, end_period, save=True)
    if cs:
        chart_college_pie(cs, ov / "college_cites.png", "cites")
        chart_college_pie(cs, ov / "college_papers.png", "papers")
    total = len(made) * 6 + 8
    print(f"charts: {len(made)} 学科 × 6 图 + 概览/学院 8 张 = {total} 张 → {out_dir}"
          f"（窗口 {periods[0]}–{P}，{len(periods)} 期）")
    return total


if __name__ == "__main__":
    import sys
    ld = sys.argv[1] if len(sys.argv) > 1 else None
    if ld is None:
        outs = sorted(pathlib.Path("out").glob("20*/"), key=lambda p: p.name)
        ld = str(outs[-1]).replace("\\", "/")
    render_all(ld)
