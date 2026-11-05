# -*- coding: utf-8 -*-
"""零依赖 Markdown 渲染（只支持本产线实际用到的子集）。

为什么不引第三方库：本仓零 CDN、依赖表越小越好；而报告用到的语法是可控的有限集合
（标题 / 表格 / 列表 / 引用 / 水平线 / 图片 / 粗体 / 行内代码）。

两处消费，**同一份实现**（避免"网页上对、导出件上错"）：
  1. `report.py` 写独立可打开的 `report.html`（可导出、可离线看）；
  2. 演示站 `/p/<期次>/flexible` 内联渲染（图片路径换成服务端路由）。
"""
from __future__ import annotations

import base64
import html
import mimetypes
import pathlib
import re

_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MARK = re.compile(r"==([^=\n]+)==")     # 待审线（票 01）：==句子== → 细下划线


def _inline(s: str) -> str:
    """行内：先转义，再还原我们自己的标记（顺序不能反）。"""
    # 图片标记会被还原成 HTML 属性；必须同时转义引号，不能只转义标签。
    s = html.escape(s, quote=True)
    s = _IMG.sub(r'<img src="\2" alt="\1">', s)
    s = _CODE.sub(r"<code>\1</code>", s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    # 只认成对 ==…==（单行内，逐行调用天然满足）；单侧 == 不入链、原样保留
    s = _MARK.sub(r'<span class="fx-mark">\1</span>', s)
    return s


def _strip_legacy_banner(md: str) -> str:
    """旧稿兜底（2026-10-15 rick：报告里不再重复「内部参考·非报送」声明）。

    历史 `report.md` 顶部含一整行「本件为内部参考…（母版 704 槽位、三道闸、可签发）。」；
    该声明已由页面导语承担（下载件走各自页脚），渲染一律剥离——**同行的待审线图例保留**；
    整行只剩声明时直接丢弃。新稿不再写这一行（`report._render`），此函数幂等。
    """
    def _repl(m):
        rest = m.group(1).strip("　 ")
        return f"> {rest}" if rest else ""
    return re.sub(r"(?m)^> \*\*本件为内部参考[^\n]*?（母版 704 槽位、三道闸、可签发）。[　\s]*(.*)$",
                  _repl, md)


def render(md: str, *, img_prefix: str = "", img_map=None, _wrap_tail: bool = True) -> str:
    """Markdown → HTML 片段（不含 <html>/<body>）。

    Args:
        img_prefix: 在所有图片路径前加的前缀（演示站用来换成服务端路由）
        img_map:    {原文件名: 新URL}，优先于 img_prefix；用于把
                    `../charts/x.png` 映射到 `/p/<期次>/flexible/chart/<intent>/x.png`

    尾部约定（rick 2026-10-14）：「## 本稿如何产生」起的固定附录（架构主张 + 数据来源链）
    收进一枚「关于本稿」折叠块，不与正文混排；重复的「内部参考…」页脚行不再渲染
    （线已提示过的，禁止再提示第二遍）。
    """
    md = _strip_legacy_banner(md)
    if _wrap_tail:
        m = re.search(r"(?m)^##\s*本稿如何产生", md)
        if m:
            head = render(md[:m.start()], img_prefix=img_prefix, img_map=img_map,
                          _wrap_tail=False)
            tail_md = re.sub(r"(?m)^\*内部参考[^\n]*\*[ \t]*\n?", "", md[m.start():])
            tail = render(tail_md, img_prefix=img_prefix, img_map=img_map,
                          _wrap_tail=False)
            return (head + '\n<details class="fx-about">'
                           '<summary>关于本稿 · 本稿如何产生与数据来源链</summary>'
                           f'<div class="fx-about-in">{tail}</div></details>')
    out, i = [], 0
    lines = md.split("\n")
    in_ul = in_ol = in_q = in_tbl = False

    def close():
        nonlocal in_ul, in_ol, in_q, in_tbl
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        if in_q:
            out.append("</blockquote>")
            in_q = False
        if in_tbl:
            out.append("</tbody></table>")
            in_tbl = False

    while i < len(lines):
        ln = lines[i]
        raw = ln.rstrip()

        # 表格：本行含 | 且下一行是分隔行
        if raw.startswith("|") and i + 1 < len(lines) and \
                re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            close()
            cells = [c.strip() for c in raw.strip("|").split("|")]
            out.append('<table class="dense"><thead><tr>'
                       + "".join(f"<th>{_inline(c)}</th>" for c in cells)
                       + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cs = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cs) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue

        if not raw.strip():
            close()
            i += 1
            continue
        if raw.startswith("---") and set(raw.strip()) <= {"-"}:
            close()
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if m:
            close()
            lvl = min(len(m.group(1)) + 1, 6)      # h1 → h2（页面已有 h1）
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if raw.startswith(">"):
            if not in_q:
                close()
                out.append("<blockquote>")
                in_q = True
            out.append(f"<p>{_inline(raw.lstrip('> ').strip())}</p>")
            i += 1
            continue

        mi = _IMG.match(raw.strip())
        if mi:
            close()
            figs = []
            while True:
                alt, src = mi.group(1), mi.group(2)
                cap = None
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    m2 = re.match(r"^\*([^*].*)\*$", lines[j].strip())
                    if m2:
                        cap = m2.group(1)
                        i = j
                figs.append((alt, _img_url(src, img_prefix, img_map), cap))
                i += 1
                k = i
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines):
                    mi = _IMG.match(lines[k].strip())
                    if mi:
                        i = k
                        continue
                break
            # 连续图合成一组 → CSS 两列（rick 2026-09-29：图缩小、一排放两张）
            parts = []
            for alt, src, cap in figs:
                fig = (f'<figure><img src="{html.escape(src, quote=True)}" '
                       f'alt="{html.escape(alt)}">')
                if cap:
                    fig += f"<figcaption>{_inline(cap)}</figcaption>"
                fig += "</figure>"
                parts.append(fig)
            out.append('<div class="figrow">' + "".join(parts) + "</div>")
            continue

        m = re.match(r"^[-*]\s+(.*)$", raw)
        if m:
            if not in_ul:
                close()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)$", raw)
        if m:
            if not in_ol:
                close()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue

        close()
        out.append(f"<p>{_inline(raw)}</p>")
        i += 1
    close()
    return "\n".join(out)


def _img_url(src: str, prefix: str, img_map) -> str:
    if img_map:
        name = src.split("/")[-1]
        if name in img_map:
            return img_map[name]
    if prefix and not src.startswith(("http://", "https://", "/")):
        return prefix + src.split("/")[-1]
    return src


#: 独立 HTML 件的外壳（自包含、无外部资源 —— 与 collation 离线快照同思路）
#: 2026-11-04（二）：骨架照搬 Lieflat 报告模板 R04「月度运营一页纸」
#: （`lieflat-charts` skill · templates/reports/report-04.zh.html）——
#: 竖排书脊 / 右对齐节标题引线 / 大数统计行 / fit-width 等比缩放；
#: 色板仍走 MONO 灰阶，字体本地栈零外链（数学稿同款）。
#: class 名保留（wrap / dense / fx-mark / fx-about / figrow / export-mark）。
SHELL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#F0EFEB;--ink:#1C1C1A;--ink-2:#57564F;--ink-3:#8F8E88;--faint:#C6C5BF;
--line:#DEDDD6;
--sans:"Inter","Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
--mono:"SFMono-Regular",Consolas,"Liberation Mono",monospace}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.8 var(--sans);
-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums lining-nums;
display:flex;justify-content:center;padding:52px 24px 72px}}
/* R04 骨架：书脊 + 版心（版心列沿用 .wrap 类名） */
.sheet{{width:1080px;max-width:1080px;display:grid;grid-template-columns:110px 1fr}}
.spine{{position:relative;border-right:1px solid var(--ink)}}
.spine .t{{position:absolute;top:0;left:12px;writing-mode:vertical-rl;
font-weight:900;line-height:1.15;letter-spacing:.08em;white-space:nowrap}}
.spine .b{{position:absolute;bottom:0;left:46px;writing-mode:vertical-rl;
font-size:9px;font-weight:700;letter-spacing:.26em;color:var(--ink-3)}}
.wrap{{padding-left:38px;min-width:0}}
/* 顶注：站名 · 元信息（R04 tophead 同款；声明只在页脚出现一次） */
.tophead{{display:flex;gap:14px;align-items:baseline;border-bottom:1px solid var(--ink);
padding-bottom:10px;margin-bottom:34px;flex-wrap:wrap}}
.tophead .site{{font-weight:700;font-size:13px;letter-spacing:.08em}}
.tophead .sep{{color:var(--faint)}}
.tophead .tag{{font-size:10.5px;font-weight:600;letter-spacing:.1em;color:var(--ink-3)}}
/* R04 节标题：右对齐 + 引线 */
.secthead{{display:flex;align-items:baseline;gap:14px;margin:42px 0 10px}}
.secthead.first{{margin-top:0}}
.secthead .line{{flex:1;border-top:1px solid var(--ink)}}
.secthead .t{{font-weight:700;font-size:15px;letter-spacing:.14em;white-space:nowrap}}
/* R04 大数统计行（首个「指标/数值/来源」表升级而来；来源降为小字，账本信息不丢） */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
margin:16px 0 8px;border-top:1px solid var(--ink)}}
.stats>div{{padding:20px 18px 8px;border-right:1px dotted var(--faint)}}
.stats>div:first-child{{padding-left:0}}
.stats>div:last-child{{border-right:0;padding-right:0}}
.stats .kpi .v{{font-size:34px;font-weight:700;line-height:1.1}}
.stats .kpi .l{{font-size:12px;font-weight:600;margin-top:6px}}
.stats .kpi .r{{font-size:10.5px;color:var(--ink-3);margin-top:3px;line-height:1.6}}
.stats .kpi .r code{{background:none;padding:0;font-family:var(--sans);color:var(--ink-3)}}
h2,h3,h4{{font-weight:700;line-height:1.4;margin:30px 0 12px}}
h2{{font-size:19px}}
h3{{font-size:16.5px;margin:20px 0 8px}} h4{{font-size:14.5px}}
details.fx-about h2{{font-size:15px;border-bottom:0;padding-bottom:0;margin:16px 0 6px}}
p{{margin:10px 0}}
table.dense{{border-collapse:collapse;width:100%;margin:14px 0;font-size:13px}}
table.dense th,table.dense td{{border:1px solid var(--line);padding:7px 10px;text-align:left}}
table.dense th{{background:#E7E6E0;font-weight:600;font-size:12px;letter-spacing:.04em}}
table.dense td:first-child{{white-space:nowrap}}
table.dense td:nth-child(2){{font-variant-numeric:tabular-nums;font-weight:600}}
blockquote{{margin:14px 0;padding:10px 14px;background:#E9E8E2;
border-left:3px solid var(--ink);color:var(--ink-2)}}
blockquote p{{margin:4px 0}}
code{{font-family:var(--mono);font-size:12px;background:#E7E6E0;
padding:1px 5px;border-radius:3px}}
/* 待审线（票 01）：==句子== → 细下划线；与网页 .fx-md .fx-mark 同款（同 class、同参数） */
.fx-mark{{text-decoration:underline;text-decoration-thickness:1px;
text-underline-offset:2px;text-decoration-color:var(--ink-3)}}
figure{{margin:18px 0;text-align:center}}
figure img{{max-width:100%;border:1px solid var(--line);border-radius:3px;background:#fff}}
/* 连续图两列一组（一篇里图不占满宽，观感更紧凑） */
.figrow{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:16px 0}}
.figrow figure{{margin:0}}
@media (max-width:640px){{.figrow{{grid-template-columns:1fr}}}}
/* ECharts 图卡（数学稿同款：无卡片，图直接坐在纸面上，
   图注走数学稿 srcline 小字；库与数据仍全内联） */
figure.fx-echart{{margin:22px 0 4px;text-align:left}}
.fx-chart{{width:100%;height:340px}}
.figrow .fx-chart{{height:280px}}
figure figcaption{{font-size:10px;font-weight:600;letter-spacing:.08em;
color:var(--faint);margin-top:10px;text-align:left;line-height:1.8}}
details.fx-about{{margin-top:22px;border:1px dashed var(--faint);border-radius:3px;background:#E9E8E2}}
details.fx-about>summary{{cursor:pointer;padding:10px 14px;font-size:13.5px;color:var(--ink-2)}}
details.fx-about .fx-about-in{{padding:2px 14px 12px;border-top:1px solid var(--line)}}
hr{{border:0;border-top:1px solid var(--line);margin:28px 0}}
ul,ol{{padding-left:22px}} li{{margin:5px 0}}
a{{color:var(--ink);text-decoration:underline;text-decoration-color:var(--faint)}}
/* 导出件页脚标注（2026-10-15）：报告内不再重复声明，声明在下载件页脚出现一次 */
.export-mark{{margin-top:34px;padding-top:10px;border-top:1px solid var(--line);
font-size:12px;color:var(--ink-3);text-align:center;letter-spacing:.06em}}
</style></head><body><div class="sheet">
<div class="spine"><div class="t" style="font-size:{spine_px}px">{spine}</div>
<div class="b">{spine_b}</div></div>
<div class="wrap">
<div class="tophead"><span class="site">文衡 · 灵活报告</span><span class="sep">|</span>
<span class="tag">{tophead}</span></div>
{body}
<p class="export-mark">内部参考 · 非报送件　｜　灵活报告（第二条产线）　｜　不带盖章位</p>
{scripts}
</div></div>
<script>
(function(){{
var sheet=document.querySelector('.sheet');var W=1080;
var fit=function(){{var cs=getComputedStyle(document.body);
var avail=document.documentElement.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
sheet.style.zoom=Math.min(1,avail/W)}};
fit();addEventListener('resize',fit);
}})();
</script>
</body></html>
"""


def inline_images(html_text: str, base_dir) -> str:
    """把页内**相对路径的本地图**换成一枚枚 `data:` URI（单文件带走图）。

    用途：① 生成期（`standalone`）——落盘的 report.html 双击即开、不依赖旁边的 `charts/`；
    ② 下载口**即时**替换——旧稿也立刻能带图下（磁盘原件一个字节不动）。
    只内联 `<img src="…">` 里**相对**且真实存在的文件；绝对/网络/data URI、越界路径、缺文件
    一律原样保留（宁可少内联，不编、不越权）。
    """
    base = pathlib.Path(base_dir).resolve()

    def _repl(m):
        prefix, src, suffix = m.group(1), m.group(2), m.group(3)
        if src.startswith(("http://", "https://", "data:", "//", "/")):
            return m.group(0)
        p = (base / src).resolve()
        if p != base and not p.is_relative_to(base):
            return m.group(0)                                   # 越界（.. 之类）原样留着
        if not p.is_file():
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"{prefix}data:{mime};base64,{b64}{suffix}"

    return re.sub(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', _repl, html_text)


#: 稿首元信息行（`report._render` 写的稿首引用块）：
#: `> 期次：…` / `> 意图：…` / `> 生成时间：…` —— 摘去进顶注，正文不再重复。
_META_LINE = re.compile(r"(?m)^> (期次|意图|规划后端|生成时间)：(.*)$")


def _split_meta(md: str) -> tuple[str, dict[str, str]]:
    """摘出稿首元信息行，返回 (剩余 md, {键: 值})。幂等。"""
    metas: dict[str, str] = {}

    def _repl(m):
        metas[m.group(1)] = m.group(2).strip()
        return ""

    md = _META_LINE.sub(_repl, md)
    md = re.sub(r"(?m)^> ?\n", "", md)      # 摘走后剩下的空引用行
    return md, metas


def _plain(s: str) -> str:
    """顶注小字用：去强调标记。"""
    return s.replace("**", "")


def _spine_px(title: str) -> int:
    n = len(title)
    return 52 if n <= 8 else (42 if n <= 13 else 34)


#: 首个「指标 / 数值 / 来源」表 → R04 大数统计行（只升第一张；其余表保持 dense）。
#: v＝数值（去强调），l＝指标名，r＝来源（账本定位小字，信息不丢）。
_KPI_TABLE = re.compile(
    r'<table class="dense"><thead><tr><th>指标</th><th>数值</th><th>[^<]*</th>'
    r"</tr></thead><tbody>(.*?)</tbody></table>", re.S)
_KPI_ROW = re.compile(r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>")


def _stats_row(body: str) -> str:
    m = _KPI_TABLE.search(body)
    if not m:
        return body
    kpis = []
    for name, val, src in _KPI_ROW.findall(m.group(1)):
        v = val.replace("<strong>", "").replace("</strong>", "")
        kpis.append(f'<div><div class="kpi"><div class="v">{v}</div>'
                    f'<div class="l">{name}</div>'
                    f'<div class="r">{src}</div></div></div>')
    if not kpis:
        return body
    return (body[:m.start()] + '<div class="stats">' + "".join(kpis)
            + "</div>" + body[m.end():])


def _sectheads(body: str) -> str:
    """节标题 → R04 右对齐引线样式；「关于本稿」折叠块内不动。

    `render` 把 `##` 升一级输出 `<h3>`（h1→h2 是稿题，已在 standalone 摘除），
    所以这里抓 h3。"""
    cut = body.find('<details class="fx-about">')
    head, tail = (body, "") if cut < 0 else (body[:cut], body[cut:])
    n = [0]

    def _repl(m):
        first = " first" if n[0] == 0 else ""
        n[0] += 1
        return (f'<div class="secthead{first}">'
                f'<span class="line"></span>'
                f'<span class="t">{m.group(1)}</span></div>')

    return re.sub(r"<h3>(.*?)</h3>", _repl, head) + tail


def standalone(md: str, title: str, *, base_dir=None, chart_payloads=None) -> str:
    """渲染成可离线打开的**独立** HTML 件（R04 骨架）。

    `base_dir`（＝报告所在目录）：给了就把 `charts/*.png` 内联成 data URI——
    「下载报告」拿到的是**单文件**，离开 `charts/` 目录也带图。

    `chart_payloads`（`echart.payloads_for` 的结果）：给了就把对应
    `<img>` 图替换成 ECharts 容器（数学稿观感），库与数据全部内联，
    仍是单文件零外链；没给的图保持 PNG 内联（docx 出口不受影响）。
    🔴 payload 不含轴范围——渲染层 `scale:true` 让轴由数据自适应。

    稿首元信息（期次 / 意图 / 规划后端）摘进顶注；首个「指标/数值/来源」表
    升级为大数统计行；`h2` 升级为右对齐节标题。
    """
    md, metas = _split_meta(md)
    md = re.sub(r"(?m)^#\s+.+\n", "", md, count=1)   # 标题进书脊，正文不重复
    body = _sectheads(_stats_row(render(md)))
    scripts = ""
    if chart_payloads:
        body, fx = _swap_charts(body, chart_payloads)
        if fx:
            scripts = _chart_scripts(fx)
    if base_dir is not None:
        body = inline_images(body, base_dir)
    if metas:
        parts = []
        if "期次" in metas:
            parts.append("期次 " + _plain(metas["期次"]))
        if "意图" in metas:
            parts.append(_plain(metas["意图"]))
        if "生成时间" in metas:
            parts.append("生成时间 " + _plain(metas["生成时间"]))
        tag = " · ".join(parts)
    else:
        tag = "学科信息参考 · 第二条产线"
    return SHELL.format(title=html.escape(title), body=body, scripts=scripts,
                        spine=html.escape(title), spine_px=_spine_px(title),
                        spine_b="灵活报告 · 第二条产线", tophead=tag)


_FIG = re.compile(
    r'<figure><img src="([^"]+)" alt="([^"]*)">'
    r'(?:<figcaption>(.*?)</figcaption>)?</figure>', re.S)


def _swap_charts(body: str, payloads: dict) -> tuple[str, list[dict]]:
    """把 payload 覆盖到的 `<figure><img …>` 换成 ECharts 容器。

    返回 (新 body, 按文档顺序的 payload 列表)。未覆盖的图原样保留。
    """
    fx: list[dict] = []

    def _repl(m):
        src, alt, cap = m.group(1), m.group(2), m.group(3)
        name = src.split("/")[-1]
        p = payloads.get(name)
        if p is None:
            return m.group(0)
        idx = len(fx)
        fx.append(p)
        cap_html = cap or html.escape(alt)
        return (f'<figure class="fx-echart">'
                f'<div class="fx-chart" id="fxc{idx}"></div>'
                f'<figcaption>{cap_html}</figcaption></figure>')

    return _FIG.sub(_repl, body), fx


_LIB_PATH = pathlib.Path(__file__).parent / "vendor" / "echarts.min.js"
_LIB_CACHE: str | None = None


def _echarts_lib() -> str:
    global _LIB_CACHE
    if _LIB_CACHE is None:
        _LIB_CACHE = _LIB_PATH.read_text(encoding="utf-8")
    return _LIB_CACHE


#: 渲染层（2026-11-04 三）：逐项对齐 `数学稿` 图表——无卡片、只留
#: 底部轴线、点状网格、大字号、白底浮层 tooltip、粗端标；
#: 实线＝实测 / 虚线＝阈值对标。色值与数学稿逐字一致。
#: 🔴 红线遵守方式：y 轴不写 min/max（数学稿是硬编码 4,900，
#: 产线版不许抄），用 `scale:true` 按数据自适应；
#: payload 里也没有轴范围字段（结构上不存在，同 spec.py）。
_INIT_JS = """
(function(){
/* 图表颜色优先跟着报告皮肤：先认 window.__RPT__，再认注入的 --rpt-* 变量；
   两者都读不到（旧稿 / 生成时没带外观参数）就回落原来的写死色值，行为与从前一致。 */
var __R=window.__RPT__||{};
var __css=function(n){try{var v=getComputedStyle(document.documentElement).getPropertyValue('--rpt-'+n);return v&&v.trim()?v.trim():null}catch(e){return null}};
var __pick=function(key,name,fb){return __R[key]!=null?__R[key]:(__css(name)||fb)};
var FONT=__pick('font','f-body','"Inter","Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif');
var INK=__pick('ink','ink','#1C1C1A'),MUT=__pick('muted','muted','#8F8E88'),GRID=__pick('grid','rule','#DEDDD6');
var fmt=function(n){return n==null?'':Number(n).toLocaleString('en-US')};
var FMT={
  int:function(v){return fmt(Math.round(v))},
  dec3:function(v){return Number(v).toFixed(3)},
  dec2:function(v){return Number(v).toFixed(2)},
  pct2:function(v){return Number(v).toFixed(2)+'%'}
};
function base(p){
  return {
    textStyle:{fontFamily:FONT,color:INK},
    color:[INK,MUT,'#A9A89F'],
    grid:{left:10,right:104,top:46,bottom:10,containLabel:true},
    tooltip:{trigger:'axis',backgroundColor:'#FFFFFF',borderColor:'#E3E2DC',
      borderWidth:1,padding:[14,18],borderRadius:6,
      textStyle:{color:INK,fontSize:13.5,fontFamily:FONT},
      extraCssText:'box-shadow:0 4px 16px rgba(28,28,26,.10);',
      axisPointer:{lineStyle:{color:MUT,type:'dashed'}}},
    legend:{top:2,left:2,itemWidth:26,itemHeight:10,itemGap:24,
      textStyle:{color:MUT,fontSize:13,fontFamily:FONT}},
    xAxis:{type:'category',boundaryGap:p.type!=='line',data:p.cats.map(lbl),
      axisLine:{lineStyle:{color:INK,width:1.2}},axisTick:{show:false},
      axisLabel:{color:MUT,fontSize:12.5,fontFamily:FONT,margin:14},
      splitLine:{show:false}},
    yAxis:yaxis(p),
    animationDuration:900,animationEasing:'cubicOut',
    series:p.series.map(function(s){return serie(p,s)})
  };
}
function lbl(p){return p.length===6?p.slice(0,4)+'-'+p.slice(4):p}
function yaxis(p){
  var f=FMT[p.fmt]||fmt;
  var y={type:'value',scale:true,             /* 🔴 轴范围由数据决定，无 min/max */
    axisLine:{show:false},axisTick:{show:false},
    axisLabel:{color:MUT,fontSize:12.5,fontFamily:FONT,formatter:f,margin:12},
    splitLine:{lineStyle:{color:GRID,type:'dotted',width:1}}};
  if(p.invert)y.inverse=true;
  if(p.type==='bar'&&p.fmt==='int')y.minInterval=1;
  return y;
}
function serie(p,s){
  var f=FMT[p.fmt]||fmt;
  if(p.type==='bar'){
    return {name:s.name,type:'bar',data:s.data,barWidth:'34%',
      itemStyle:{color:s.dash?MUT:INK},label:{show:true,position:'top',
      color:s.dash?MUT:INK,fontSize:12,fontWeight:600,fontFamily:FONT,
      formatter:o=>f(o.value)}};
  }
  var c=s.dash?MUT:INK;
  var o={name:s.name,type:'line',data:s.data,smooth:false,
    symbol:'circle',symbolSize:s.dash?7:8,
    lineStyle:{width:s.dash?2.2:2.6,color:c,type:s.dash?'dashed':'solid'},
    itemStyle:{color:c},
    endLabel:{show:true,color:c,distance:10,fontSize:14,
      fontWeight:s.dash?400:'bold',fontFamily:FONT,
      formatter:o=>f(o.value)}};
  if(p.markline&&!s.dash){
    o.markLine={silent:true,symbol:'none',
      lineStyle:{color:MUT,type:'dashed',width:2},
      label:{formatter:p.markline.label,color:MUT,fontSize:12,
        fontFamily:FONT,position:'insideEndTop'},
      data:[{yAxis:p.markline.value}]};
  }
  return o;
}
var FX=window.FX_CHARTS||[];
FX.forEach(function(p,i){
  var el=document.getElementById('fxc'+i);
  if(!el||!window.echarts)return;
  var opt=base(p);
  if(p.fmt==='pct2'){
    opt.tooltip.valueFormatter=function(v){return FMT.pct2(v)};
  }
  echarts.init(el).setOption(opt);
});
})();
"""


def _chart_scripts(fx: list[dict]) -> str:
    import json as _json
    data = _json.dumps(fx, ensure_ascii=False, separators=(",", ":"))
    return (f'<script>window.FX_CHARTS={data};</script>'
            f'<script>{_echarts_lib()}</script>'
            f'<script>{_INIT_JS}</script>')
