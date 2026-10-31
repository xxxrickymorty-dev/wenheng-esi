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


def _short_num(v):
    """纵轴刻度可读缩写：≥1e8 缩「x 亿」、≥1e4 缩「x.x 万」，其余千分位——
    保证千位分隔的长数字（如 395,215）不把绘图区左缘顶满。"""
    a = abs(v)
    if a >= 1e8:
        return f"{v / 1e8:.1f}".rstrip("0").rstrip(".") + " 亿"
    if a >= 1e4:
        return f"{v / 1e4:.1f} 万"
    return f"{v:,.0f}"


def _tick_idx(n):
    """n 个均匀刻度里取 ~8 个的索引（升序去重）。"""
    return sorted({round(k * (n - 1) / 7) for k in range(8)}) if n > 8 else list(range(n))


def line_chart(series, *, width=860, height=280, y_invert=False, ref_lines=(), y_fmt=None):
    """折线图。series = [(线名, [(x 标签, 值)…])]；x＝期次（各线标签并集按首现序均匀布点，
    刻度 ~8 个），多线按 OK/WARN/INK 轮换，图例在图下方；缺值（None）断线不连线；
    y_invert＝纵轴反转（排名类：小者好，视觉向上）；ref_lines = [(值, 标签)] 横向虚线；
    y_fmt＝纵轴刻度格式（默认 _short_num 可读缩写）。风格与 hbar_log 同族。纯函数。"""
    y_fmt = y_fmt or _short_num
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
    ml, mr, mt, mb = 52, 14, 10, 24
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
    for i in _tick_idx(n):
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


DONUT_COLORS = [OK, WARN, INK, "#7FB79B", "#A8B8D0", "#C9A66B"]


def donut(items, *, width=420, title=""):
    """环形图。items = [(标签, 数值)]，占比自动算；六色循环（够 22 学科用）；
    中心留白放 title（「\\n」分行，末行加重）；右侧图例＝色块＋标签＋「数值 · 占比」
    （数值千分位整数显示；标签超 9 字截断加「…」防与数值列相撞）。
    缺项/空列表/合计为 0 → 空 svg 壳。风格与 hbar_log 同族。纯函数，返回 <svg> 字符串。"""
    items = [(str(lab), v) for lab, v in items if v is not None and v > 0]
    total = sum(v for _lab, v in items)
    if not items or total <= 0:
        return (f'<svg viewBox="0 0 {width} 40" width="100%" role="img" '
                'xmlns="http://www.w3.org/2000/svg"></svg>')
    row_h = 20
    h = max(210, len(items) * row_h + 14)
    cx, cy, r, sw = 118, h / 2, 78, 34
    circ = 2 * math.pi * r
    s = [f'<svg viewBox="0 0 {width} {h:.0f}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    acc = 0.0
    for i, (label, v) in enumerate(items):
        c = DONUT_COLORS[i % len(DONUT_COLORS)]
        seg = v / total * circ
        s.append(f'<circle cx="{cx}" cy="{cy:.1f}" r="{r}" fill="none" stroke="{c}" stroke-width="{sw}" '
                 f'stroke-dasharray="{max(seg - 1.5, 0.4):.2f} {circ:.2f}" stroke-dashoffset="{-acc * circ:.2f}" '
                 f'transform="rotate(-90 {cx} {cy:.1f})"/>')
        acc += v / total
    lines = str(title).split("\n") if title else []
    y0 = cy - (len(lines) - 1) * 8 + 4
    for k, ln in enumerate(lines):
        last = k == len(lines) - 1
        s.append(f'<text x="{cx}" y="{y0 + k * 16:.1f}" text-anchor="middle" '
                 f'font-size="{15 if last else 11}" fill="{INK if last else MUT}" {FONT}>{_esc(ln)}</text>')
    lx = 228
    ly = (h - len(items) * row_h) / 2 + 4
    for i, (label, v) in enumerate(items):
        y = ly + i * row_h
        c = DONUT_COLORS[i % len(DONUT_COLORS)]
        s.append(f'<rect x="{lx}" y="{y - 9:.1f}" width="10" height="10" fill="{c}"/>')
        if len(label) > 9:
            label = label[:8] + "…"
        s.append(f'<text x="{lx + 15}" y="{y:.1f}" font-size="11" fill="{INK}">{_esc(label)}</text>')
        s.append(f'<text x="{width - 6}" y="{y:.1f}" text-anchor="end" font-size="10.5" fill="{MUT}" {FONT}>'
                 f'{_esc(f"{v:,.0f} · {v / total * 100:.1f}%")}</text>')
    s.append("</svg>")
    return "".join(s)


def _star(cx, cy, r_out=5.0, r_in=2.0):
    """五角星 polygon points（尖朝上），entry_timeline 的 1‰ 事件标记。"""
    pts = []
    for k in range(10):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(-90 + k * 36)
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pts)


def entry_timeline(rows, *, periods, width=960):
    """入榜时间轴（甘特式）。periods＝全期次标签列表（x 轴，均匀 ~8 刻度）；
    rows = [{"label", "first_seen", "entry1"?, "entrypm"?, "pre"?}]，每行一条细轨道
    （从 first_seen 到最右）：entry1 期次画 OK 色菱形（进入前 1%），entrypm 期次画
    WARN 色五角星（进入前 1‰），pre=True 的行（档案起点前已入围）轨道起点画实心圆
    ＋浅色延伸；行高 18px，标签列左对齐，底部 x 刻度与图例。不在 periods 里的期次
    标记跳过（不编造位置）。缺行/空 periods → 空 svg 壳。纯函数，返回 <svg> 字符串。"""
    if not rows or not periods:
        return (f'<svg viewBox="0 0 {width} 30" width="100%" role="img" '
                'xmlns="http://www.w3.org/2000/svg"></svg>')
    idx = {p: i for i, p in enumerate(periods)}
    label_w, right_w, row_h, top = 150, 16, 18, 8
    h = top + len(rows) * row_h + 30 + 18
    track_w = width - label_w - right_w
    x = lambda p: label_w + track_w * idx[p] / max(len(periods) - 1, 1)
    x_end = x(periods[-1])
    s = [f'<svg viewBox="0 0 {width} {h:.0f}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for i, r0 in enumerate(rows):
        y = top + i * row_h + row_h / 2
        s.append(f'<text x="{label_w - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="{INK}">{_esc(r0["label"])}</text>')
        fs = r0.get("first_seen")
        if fs not in idx:
            continue
        x0 = x(fs)
        if r0.get("pre"):
            s.append(f'<line x1="{x(periods[0]):.1f}" y1="{y:.1f}" x2="{x0:.1f}" y2="{y:.1f}" stroke="{BAR_BG}" stroke-width="2"/>')
            s.append(f'<circle cx="{x0:.1f}" cy="{y:.1f}" r="3" fill="{INK}"/>')
        s.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x_end:.1f}" y2="{y:.1f}" stroke="{LINE}" stroke-width="2"/>')
        e1, epm = r0.get("entry1"), r0.get("entrypm")
        same = e1 is not None and e1 == epm
        if e1 in idx:
            x1 = x(e1) - (4 if same else 0)
            s.append(f'<polygon points="{x1:.1f},{y - 4:.1f} {x1 + 4:.1f},{y:.1f} {x1:.1f},{y + 4:.1f} {x1 - 4:.1f},{y:.1f}" fill="{OK}"/>')
        if epm in idx:
            xp = x(epm) + (4 if same else 0)
            s.append(f'<polygon points="{_star(xp, y)}" fill="{WARN}"/>')
    for i in _tick_idx(len(periods)):
        s.append(f'<text x="{x(periods[i]):.1f}" y="{top + len(rows) * row_h + 16:.1f}" text-anchor="middle" '
                 f'font-size="9.5" fill="{MUT}" {FONT}>{_esc(periods[i])}</text>')
    gy = h - 10
    gx = label_w
    s.append(f'<polygon points="{_star(gx + 4, gy - 3, 4.5, 1.8)}" fill="{WARN}"/>')
    s.append(f'<text x="{gx + 13}" y="{gy}" font-size="10.5" fill="{MUT}">进入前 1‰</text>')
    s.append(f'<polygon points="{gx + 96},{gy - 7:.1f} {gx + 100},{gy - 3:.1f} {gx + 96},{gy + 1:.1f} {gx + 92},{gy - 3:.1f}" fill="{OK}"/>')
    s.append(f'<text x="{gx + 107}" y="{gy}" font-size="10.5" fill="{MUT}">进入前 1%</text>')
    s.append("</svg>")
    return "".join(s)
