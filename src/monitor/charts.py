# -*- coding: utf-8 -*-
"""监测版图表工具：纯 SVG 生成器，校名无关，输入纯数据即可复用到任何学校。

自工作区 `tmp/monitor_charts.py` 收编（2026-10-31，P0-2）；海南大学 v1.1 样例的
四张图（接近度 / 1‰ 条带 / 学科分布 / 期刊集中度）即出自这两个函数。

设计口径：架构图同族令牌（零圆角、一档线宽、tabular-nums）；图表只承载数据，
不带标题（章节标题在外部）；每张图返回 <svg> 字符串，由报告生成器内联。
"""
import math

INK = "#17181a"
MUT = "#6f7278"
LINE = "#e4e1da"
OK = "#2f6f5e"
WARN = "#9a6b14"
BAR_BG = "#eef0ee"
FONT = 'font-family="ui-monospace,Consolas,monospace"'


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def hbar_log(rows, *, lo=1.0, ref=None, ref_label="", width=860, fmt=str,
             label_w=150, bar_h=20, gap=9, tick_fmt=None):
    """水平条形（log 轴）。rows = [(label, value, badge?)]; ref = 参考线值。
    tick_fmt＝刻度标签格式（默认纯数字；接近度图传 `lambda v: f"{v:g}×"`）。"""
    tick_fmt = tick_fmt or (lambda v: f"{v:g}")
    n = len(rows)
    hi = max(v for _, v, *_ in rows)
    hi *= 1.12
    plot_x, plot_w = label_w, width - label_w - 70
    top, h = 6, n * (bar_h + gap) + 14
    lx = lambda v: plot_x + plot_w * (math.log(max(v, lo)) - math.log(lo)) / (math.log(hi) - math.log(lo))
    s = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for v, lv in ((1, "1"), (5, "5"), (10, "10"), (20, "20"), (30, "30"), (50, "50")):
        if lo <= v <= hi:
            x = lx(v)
            s.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + n * (bar_h + gap) - gap + 4}" stroke="{LINE}" stroke-width="1"/>'
                     f'<text x="{x:.1f}" y="{top + n * (bar_h + gap) + 9}" text-anchor="middle" font-size="10" fill="{MUT}" {FONT}>{tick_fmt(v)}</text>')
    for i, item in enumerate(rows):
        label, val = item[0], item[1]
        badge = item[2] if len(item) > 2 else ""
        y = top + i * (bar_h + gap)
        w = max(2.0, lx(val) - plot_x)
        s.append(f'<text x="{label_w - 8}" y="{y + bar_h / 2 + 3.6}" text-anchor="end" font-size="11.5" fill="{INK}">{_esc(label)}</text>')
        s.append(f'<rect x="{plot_x}" y="{y}" width="{plot_w}" height="{bar_h}" fill="{BAR_BG}"/>')
        s.append(f'<rect x="{plot_x}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{OK}"/>')
        tx = lx(val) + 7
        anchor, txt = "start", fmt(val) + badge
        if lx(val) > width - 90:
            tx, anchor = lx(val) - 7, "end"
        s.append(f'<text x="{tx:.1f}" y="{y + bar_h / 2 + 3.6}" text-anchor="{anchor}" font-size="11" fill="{INK}" {FONT}>{_esc(txt)}</text>')
    if ref is not None:
        x = lx(ref)
        s.append(f'<line x1="{x:.1f}" y1="{top - 2}" x2="{x:.1f}" y2="{top + n * (bar_h + gap) - gap + 4}" stroke="{WARN}" stroke-width="1.5" stroke-dasharray="4 3"/>')
        s.append(f'<text x="{x + 5:.1f}" y="{top + 8}" font-size="10" fill="{WARN}" {FONT}>{_esc(ref_label)}</text>')
    s.append("</svg>")
    return "".join(s)


def permille_strip(rows, *, width=860):
    """1‰ 位置条带。rows = [(学科, rank, m, line)]；ink 方块=本校位，warn 竖线=1‰ 线。"""
    label_w, track_w, right_w = 150, width - 150 - 190, 150
    row_h, top = 34, 8
    h = len(rows) * row_h + 8
    s = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for i, (label, rank, m, line) in enumerate(rows):
        y = top + i * row_h + row_h / 2
        x = lambda pos: label_w + track_w * (pos - 1) / (m - 1)
        s.append(f'<text x="{label_w - 8}" y="{y + 4}" text-anchor="end" font-size="11.5" fill="{INK}">{_esc(label)}</text>')
        s.append(f'<line x1="{label_w}" y1="{y}" x2="{label_w + track_w}" y2="{y}" stroke="{LINE}" stroke-width="3"/>')
        lx = x(line)
        s.append(f'<line x1="{lx:.1f}" y1="{y - 11}" x2="{lx:.1f}" y2="{y + 11}" stroke="{WARN}" stroke-width="2"/>')
        rx = x(rank)
        s.append(f'<rect x="{rx - 4:.1f}" y="{y - 4}" width="8" height="8" fill="{INK}"/>')
        s.append(f'<text x="{label_w + track_w + 10}" y="{y + 4}" font-size="11" fill="{MUT}" {FONT}>第 {rank} / {m} 位 · 1‰线 第 {line} 位</text>')
    s.append("</svg>")
    return "".join(s)
