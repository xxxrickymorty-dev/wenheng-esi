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


def line_chart(series, *, width=860, height=280, y_invert=False, ref_lines=(), y_fmt=None):
    """折线图。series = [(线名, [(x 标签, 值)…])]；x＝期次（各线标签并集按首现序均匀布点，
    刻度 ~8 个），多线按 OK/WARN/INK 轮换，图例在图下方；缺值（None）断线不连线；
    y_invert＝纵轴反转（排名类：小者好，视觉向上）；ref_lines = [(值, 标签)] 横向虚线；
    y_fmt＝纵轴刻度格式（默认千分位整数）。风格与 hbar_log 同族。纯函数，返回 <svg> 字符串。"""
    y_fmt = y_fmt or (lambda v: f"{v:,.0f}")
    cols = list(dict.fromkeys(x for _name, pts in series for x, _v in pts))
    vals = [v for _name, pts in series for _x, v in pts if v is not None]
    vals += [v for v, _lab in ref_lines]
    if not cols or not vals:
        return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
                'xmlns="http://www.w3.org/2000/svg"></svg>')
    lo, hi = min(vals), max(vals)
    if lo == hi:
        lo, hi = lo - abs(lo) * 0.1 - 1, hi + abs(hi) * 0.1 + 1
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    ml, mr, mt, mb = 56, 14, 10, 24
    plot_w, plot_h = width - ml - mr, height - mt - mb
    colors = [OK, WARN, INK]

    def xi(x):
        return ml + (plot_w * cols.index(x) / (len(cols) - 1) if len(cols) > 1 else plot_w / 2)

    def yi(v):
        frac = (v - lo) / (hi - lo)
        # 自然向＝小值在下；y_invert＝小值在上（排名小=好，视觉向上）
        return mt + plot_h * (frac if y_invert else 1 - frac)

    s = [f'<svg viewBox="0 0 {width} {height + 24}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y = yi(v)
        s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + plot_w}" y2="{y:.1f}" stroke="{LINE}" stroke-width="1"/>')
        s.append(f'<text x="{ml - 6}" y="{y + 3.5:.1f}" text-anchor="end" font-size="10" fill="{MUT}" {FONT}>{_esc(y_fmt(v))}</text>')
    n = len(cols)
    tick_idx = sorted({round(k * (n - 1) / 7) for k in range(8)}) if n > 8 else list(range(n))
    for i in tick_idx:
        s.append(f'<text x="{xi(cols[i]):.1f}" y="{height - 6}" text-anchor="middle" font-size="10" fill="{MUT}" {FONT}>{_esc(cols[i])}</text>')
    for v, lab in ref_lines:
        y = yi(v)
        s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + plot_w}" y2="{y:.1f}" stroke="{WARN}" stroke-width="1.5" stroke-dasharray="4 3"/>')
        s.append(f'<text x="{ml + plot_w}" y="{y - 4:.1f}" text-anchor="end" font-size="10" fill="{WARN}" {FONT}>{_esc(lab)}</text>')
    for j, (name, pts) in enumerate(series):
        c = colors[j % 3]
        runs: list[list] = [[]]
        for x, v in pts:
            if v is None:
                runs.append([])
            else:
                runs[-1].append((x, v))
        for run in runs:
            if len(run) >= 2:
                pts_s = " ".join(f"{xi(x):.1f},{yi(v):.1f}" for x, v in run)
                s.append(f'<polyline points="{pts_s}" fill="none" stroke="{c}" stroke-width="1.5"/>')
            elif len(run) == 1:
                x, v = run[0]
                s.append(f'<rect x="{xi(x) - 2.5:.1f}" y="{yi(v) - 2.5:.1f}" width="5" height="5" fill="{c}"/>')
    lx = ml
    for j, (name, _pts) in enumerate(series):
        c = colors[j % 3]
        s.append(f'<rect x="{lx:.1f}" y="{height + 8}" width="10" height="10" fill="{c}"/>')
        s.append(f'<text x="{lx + 15:.1f}" y="{height + 17}" font-size="11" fill="{INK}">{_esc(name)}</text>')
        lx += 26 + sum(11 if ord(ch) > 0x2E7F else 6.5 for ch in name)
    s.append("</svg>")
    return "".join(s)


def dumbbell(rows, *, width=860, name_a="", name_b=""):
    """哑铃图（两值对比，排名类：小者好）。rows = [(标签, 值 a, 值 b)]；每行一条水平轨道，
    两端圆点（a＝OK 色、b＝INK 色）＋中间连线，值标在点侧（a 上、b 下）；
    name_a/name_b＝图例（图上方一行）。风格与 hbar_log 同族。纯函数，返回 <svg> 字符串。"""
    label_w, right_w, row_h, top = 150, 56, 36, 30
    h = top + len(rows) * row_h + 6
    vals = [v for _label, a, b in rows for v in (a, b) if v is not None]
    hi = (max(vals) if vals else 1.0) * 1.05
    track_w = width - label_w - right_w
    xs = lambda v: label_w + track_w * (max(v, 1) - 1) / max(hi - 1, 1e-9)
    s = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    lx = label_w
    for nm, c in ((name_a, OK), (name_b, INK)):
        s.append(f'<rect x="{lx}" y="5" width="10" height="10" fill="{c}"/>')
        s.append(f'<text x="{lx + 15}" y="14" font-size="11" fill="{INK}">{_esc(nm)}</text>')
        lx += 40 + sum(11 if ord(ch) > 0x2E7F else 6.5 for ch in nm)
    for i, (label, a, b) in enumerate(rows):
        y = top + i * row_h + row_h / 2
        s.append(f'<text x="{label_w - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11.5" fill="{INK}">{_esc(label)}</text>')
        s.append(f'<line x1="{label_w}" y1="{y:.1f}" x2="{label_w + track_w}" y2="{y:.1f}" stroke="{LINE}" stroke-width="1"/>')
        if a is None or b is None:
            continue                                        # 缺值侧画不出点：只留轨道，不编数字
        xa, xb = xs(a), xs(b)
        s.append(f'<line x1="{xa:.1f}" y1="{y:.1f}" x2="{xb:.1f}" y2="{y:.1f}" stroke="{MUT}" stroke-width="1.5"/>')
        s.append(f'<circle cx="{xa:.1f}" cy="{y:.1f}" r="4" fill="{OK}"/>')
        s.append(f'<circle cx="{xb:.1f}" cy="{y:.1f}" r="4" fill="{INK}"/>')
        s.append(f'<text x="{xa:.1f}" y="{y - 8:.1f}" text-anchor="middle" font-size="10" fill="{OK}" {FONT}>{_esc(f"{a:g}")}</text>')
        s.append(f'<text x="{xb:.1f}" y="{y + 18:.1f}" text-anchor="middle" font-size="10" fill="{INK}" {FONT}>{_esc(f"{b:g}")}</text>')
    s.append("</svg>")
    return "".join(s)
