# -*- coding: utf-8 -*-
"""零依赖 Markdown 渲染（只支持本产线实际用到的子集）。

为什么不引第三方库：本仓零 CDN、依赖表越小越好；而报告用到的语法是可控的有限集合
（标题 / 表格 / 列表 / 引用 / 水平线 / 图片 / 粗体 / 行内代码）。

两处消费，**同一份实现**（避免"网页上对、导出件上错"）：
  1. `report.py` 写独立可打开的 `report.html`（可导出、可离线看）；
  2. 演示站 `/p/<期次>/flexible` 内联渲染（图片路径换成服务端路由）。
"""
from __future__ import annotations

import html
import re

_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _inline(s: str) -> str:
    """行内：先转义，再还原我们自己的标记（顺序不能反）。"""
    # 图片标记会被还原成 HTML 属性；必须同时转义引号，不能只转义标签。
    s = html.escape(s, quote=True)
    s = _IMG.sub(r'<img src="\2" alt="\1">', s)
    s = _CODE.sub(r"<code>\1</code>", s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    return s


def render(md: str, *, img_prefix: str = "", img_map=None) -> str:
    """Markdown → HTML 片段（不含 <html>/<body>）。

    Args:
        img_prefix: 在所有图片路径前加的前缀（演示站用来换成服务端路由）
        img_map:    {原文件名: 新URL}，优先于 img_prefix；用于把
                    `../charts/x.png` 映射到 `/p/<期次>/flexible/chart/<intent>/x.png`
    """
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
            src = _img_url(mi.group(2), img_prefix, img_map)
            out.append(f'<figure><img src="{html.escape(src, quote=True)}" '
                       f'alt="{html.escape(mi.group(1))}"></figure>')
            i += 1
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
figure{{margin:16px 0;text-align:center}}
figure img{{max-width:100%;border:1px solid var(--line);border-radius:3px;background:#fff}}
hr{{border:0;border-top:1px solid var(--line);margin:26px 0}}
ul,ol{{padding-left:22px}} li{{margin:5px 0}}
a{{color:var(--zhu)}}
</style></head><body><div class="wrap">
{body}
</div></body></html>
"""


def standalone(md: str, title: str) -> str:
    """渲染成可离线打开的**独立** HTML 件。"""
    return SHELL.format(title=html.escape(title), body=render(md))
