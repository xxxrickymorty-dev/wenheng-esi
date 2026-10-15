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
SHELL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--paper:#FBF8F3;--ink:#2B2622;--ink-2:#5A5148;--ink-3:#8A7F72;--line:#DED5C6;
--zhu:#B23A2A;--mono:"SFMono-Regular",Consolas,"Liberation Mono",monospace}}
body{{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.75 "Songti SC","Noto Serif CJK SC",SimSun,serif}}
.wrap{{max-width:860px;margin:0 auto;padding:40px 28px 80px}}
h2,h3,h4{{font-weight:600;line-height:1.35;margin:26px 0 10px}}
h2{{font-size:20px;border-bottom:1px solid var(--line);padding-bottom:6px}}
h3{{font-size:17px}} h4{{font-size:15px}}
table.dense{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}}
table.dense th,table.dense td{{border:1px solid var(--line);padding:6px 9px;text-align:left}}
table.dense th{{background:#F3EDE3;font-weight:600}}
table.dense td:first-child{{white-space:nowrap}}
blockquote{{margin:12px 0;padding:10px 14px;background:#F5F0E7;
border-left:3px solid var(--zhu);border-radius:0 3px 3px 0;color:var(--ink-2)}}
blockquote p{{margin:4px 0}}
code{{font-family:var(--mono);font-size:12.5px;background:#F0EAE0;
padding:1px 5px;border-radius:3px}}
/* 待审线（票 01）：==句子== → 细下划线；与网页 .fx-md .fx-mark 同款（同 class、同参数） */
.fx-mark{{text-decoration:underline;text-decoration-thickness:1px;
text-underline-offset:2px;text-decoration-color:var(--ink-2)}}
figure{{margin:16px 0;text-align:center}}
figure img{{max-width:100%;border:1px solid var(--line);border-radius:3px;background:#fff}}
/* 连续图两列一组（一篇里图不占满宽，观感更紧凑） */
.figrow{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:16px 0}}
.figrow figure{{margin:0}}
.figrow figcaption{{font-size:12.5px;color:var(--ink-3);margin-top:5px}}
@media (max-width:640px){{.figrow{{grid-template-columns:1fr}}}}
details.fx-about{{margin-top:22px;border:1px dashed var(--line);border-radius:3px;background:#F5F0E7}}
details.fx-about>summary{{cursor:pointer;padding:10px 14px;font-size:14px;color:var(--ink-2)}}
details.fx-about .fx-about-in{{padding:2px 14px 12px;border-top:1px solid var(--line)}}
details.fx-about h2{{font-size:16px;border-bottom:0;padding-bottom:0;margin:16px 0 6px}}
hr{{border:0;border-top:1px solid var(--line);margin:26px 0}}
ul,ol{{padding-left:22px}} li{{margin:5px 0}}
a{{color:var(--zhu)}}
</style></head><body><div class="wrap">
{body}
</div></body></html>
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


def standalone(md: str, title: str, *, base_dir=None) -> str:
    """渲染成可离线打开的**独立** HTML 件。

    `base_dir`（＝报告所在目录）：给了就把 `charts/*.png` 内联成 data URI——
    「下载报告」拿到的是**单文件**，离开 `charts/` 目录也带图。
    """
    body = render(md)
    if base_dir is not None:
        body = inline_images(body, base_dir)
    return SHELL.format(title=html.escape(title), body=body)
