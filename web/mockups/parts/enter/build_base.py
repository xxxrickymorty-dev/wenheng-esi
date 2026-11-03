# -*- coding: utf-8 -*-
"""生成「书架屏」底板：把线上首屏原样搬成一份独立 HTML，供各设计方向共用。

只做搬运，不改样式：shelf-landing.css 全文 + index.css 的 --lib-* 令牌 +
LibraryHome.tsx 首屏结构（品牌行 / 金线画框 / 题名栏 / 五册 / 滚动提示 / 角标）。
"""
import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parents[3]     # wenheng/web
OUT = WEB / "mockups" / "parts" / "enter" / "shelf-base.html"

css = (WEB / "src" / "library" / "shelf-landing.css").read_text(encoding="utf-8")
index = (WEB / "src" / "index.css").read_text(encoding="utf-8")

lib = re.search(r":root\{\n  --lib-night:.*?\n\}", index, re.S).group(0)
css = css.replace('url("/app/shelf/assets/', 'url("../../../public/shelf/assets/')
css = css.replace('url(/app/shelf/assets/', 'url(../../../public/shelf/assets/')

BOOKS = [
    ("202609", "会泽院", "huizeyuan.webp", "2026 年 9 月", True),
    ("202607", "至公堂", "zhigongtang.webp", "2026 年 7 月", False),
    ("202605", "银杏", "yinxing.webp", "2026 年 5 月", False),
    ("202603", "阅览室", "yuelanshi.webp", "2026 年 3 月", False),
    ("202601", "校门", "xiaomen.webp", "2026 年 1 月", False),
]
W_STD, GAP = 13.0, 1.9
total = W_STD * len(BOOKS) + GAP * (len(BOOKS) - 1)
x = max(2, (100 - total) / 2)


def chars(text):
    return "".join(f'<span class="ch" style="--ci:{i}">{c}</span>' for i, c in enumerate(text))


vols = []
for i, (period, design, cover, month, featured) in enumerate(BOOKS):
    vols.append(f"""        <a class="vol {'is-featured' if featured else 'is-sub'}" href="#v-{period}"
           style="--x:{x:.1f}%;--i:{i}" aria-label="{period}，{design}装帧">
          <img class="face" src="../../assets/wenheng-covers/{cover}" alt="学科信息参考 {period}，{design}装帧封面" draggable="false">
          <span class="reissue" aria-hidden="true"><span class="re-mask"></span><b class="re-num">{period}</b></span>
          <span class="cap"><b>{period}</b>{design}装帧<em>{month}</em></span>
        </a>""")
    x += W_STD + GAP

HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>陈列馆 · 书架屏底板</title>
<style>
{lib}
*{{box-sizing:border-box}}
{css}
</style>
</head>
<body class="shelf-body">
<header class="brand">
  <svg class="mk" viewBox="0 0 28 38" fill="none" stroke="currentColor" aria-hidden="true">
    <path d="M4 3h20v32H4zM8 7h12v24H8zM11 10v18M17 10v18M8 19h12" stroke-width="1.2"/>
    <path d="m11 14 3 5 3-5" stroke-width="1.2"/>
  </svg>
  <div class="brand-txt"><b>文衡 · 陈列馆</b><span>云南大学图书馆</span></div>
</header>

<section class="shelf-view">
  <span class="wallframe" aria-hidden="true"></span>
  <div class="headline">
    <p class="cap-rule" aria-hidden="true"><span class="line"></span><span class="dia"></span></p>
    <h1 aria-label="学科信息参考">{chars("学科信息参考")}</h1>
    <p class="cap-en" aria-hidden="true">DISCIPLINARY INFORMATION REFERENCE</p>
    <p class="cap-issue">2026 年第 5 期 · 总第 39 期</p>
  </div>
  <div class="shelf lit" id="shelf" aria-label="2026 年馆藏，共 5 册">
{chr(10).join(vols)}
    <p class="down">向 下 滚 动 · 逐 期 册 页</p>
  </div>
  <span class="index" aria-hidden="true">YUNNAN UNIVERSITY LIBRARY / A–01</span>
</section>
</body>
</html>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(HTML, encoding="utf-8")
print("wrote", OUT, OUT.stat().st_size // 1024, "KB")
