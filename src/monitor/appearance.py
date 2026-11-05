# -*- coding: utf-8 -*-
"""报告外观三轴：模板（版式）/ 皮肤（配色）/ 字体。

给监测版单校报告与对比件用。这里只产「要注入 <style> 的 CSS」，不改数字、
不改 DOM 顺序——数字永远来自 report_data()，正文由确定性句骨架出。

设计要点（2026-11-05 v2 规格）：
- 五套模板不是五份 HTML 骨架，而是**同一份 DOM 上的五套 CSS 变体**；
  每套写成 `[data-template="X"]` 覆盖规则，B 就是现网 _CSS 基线（不叠加）。
- 皮肤用 `--rpt-*` 变量注入（系统皮肤是另一条轨，不下发、互不引用）。
- 字体用 `--rpt-f-body / --rpt-f-title`，隶与行楷只进标题。
- 单文件自足：零外链、零 CDN。

馆员读法：「换模板＝换版式，换皮肤＝换纸墨颜色，换字体＝换字」，三者可任意搭配。
请求里没带、或带了不认识的值，一律悄悄回落到缺省（会泽绿 / 现代黑基线 / 宋），
不报错、不给 400——免得手滑把整单生成挡在门外。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 取值表
#: 模板五套（A 会泽经折 / B 现有版式＝基线 / C 册页图录 / D 碑拓夜泊 / E 方志双栏）
DEFAULT_TEMPLATE = "B"
TEMPLATE_IDS = frozenset({"A", "B", "C", "D", "E"})

#: 皮肤 12 套：accent / accent2 / tint / paper / ink（v2 规格 §2.2 唯一色值源）
DEFAULT_SKIN = "huize"
SKINS = {
    "huize":     {"accent": "#143729", "accent2": "#276B4C", "tint": "#E8F1ED", "paper": "#F5F3EC", "ink": "#15222B"},
    "daiqing":   {"accent": "#2F5D62", "accent2": "#447C7A", "tint": "#E6EFED", "paper": "#F5F3EC", "ink": "#22261F"},
    "zhusha":    {"accent": "#8B1E1E", "accent2": "#B73A2C", "tint": "#F6E7D7", "paper": "#F7F2E8", "ink": "#2A1E1A"},
    "tenghuang": {"accent": "#C28C1A", "accent2": "#D4A72C", "tint": "#FBF3D7", "paper": "#FAF5E6", "ink": "#2E2718"},
    "piaolv":    {"accent": "#5E8E7E", "accent2": "#7DAF9F", "tint": "#E9F2EF", "paper": "#F4F6EE", "ink": "#1F2A22"},
    "wulan":     {"accent": "#4A6B8A", "accent2": "#6E8CA8", "tint": "#E6EDF3", "paper": "#F4F6F8", "ink": "#1C2530"},
    "mohui":     {"accent": "#3C3C3F", "accent2": "#666668", "tint": "#EDEDEA", "paper": "#F3F1EA", "ink": "#1A1A1A"},
    "qingshan":  {"accent": "#4E7E8C", "accent2": "#6E8F6A", "tint": "#E6EDEA", "paper": "#F5F0E6", "ink": "#2E3E42"},
    "taohua":    {"accent": "#D6A5AB", "accent2": "#A9C5C2", "tint": "#F7EDEF", "paper": "#F7F3EC", "ink": "#4A4142"},
    "hetang":    {"accent": "#7E9A7D", "accent2": "#A9C8C7", "tint": "#E8F0EB", "paper": "#F2F0EA", "ink": "#2B3A31"},
    "qiushan":   {"accent": "#A56A43", "accent2": "#7B4A36", "tint": "#F2E6D6", "paper": "#EAD9BF", "ink": "#38332E"},
    "yebo":      {"accent": "#C9A961", "accent2": "#8FA3B0", "tint": "#2A3138", "paper": "#20262B", "ink": "#ECE8DF"},
}
SKIN_IDS = frozenset(SKINS)

#: 字体 6 套（v2 规格 §2.3）。body 走正文、title 走标题；var(--f-*) 是下面的基础字族栈。
#: 楷/仿宋/隶/行楷正文放大 .8px；隶与行楷**只进标题**，正文分别落回宋 / 仿宋。
DEFAULT_FONT = "song"
FONTS = {
    "song": {"body": "var(--f-song)", "title": "var(--f-song)", "adj": "0px"},
    "hei":  {"body": "var(--f-hei)",  "title": "var(--f-hei)",  "adj": "0px"},
    "kai":  {"body": "var(--f-kai)",  "title": "var(--f-kai)",  "adj": ".8px"},
    "fang": {"body": "var(--f-fang)", "title": "var(--f-fang)", "adj": ".8px"},
    "li":   {"body": "var(--f-song)", "title": "var(--f-li)",    "adj": ".8px"},
    "xing": {"body": "var(--f-fang)", "title": "var(--f-xing)",  "adj": ".8px"},
}
FONT_IDS = frozenset(FONTS)

APPEARANCE_KEYS = ("template", "skin_rpt", "font")
_DEFAULTS = {"template": DEFAULT_TEMPLATE, "skin_rpt": DEFAULT_SKIN, "font": DEFAULT_FONT}
_ALLOWED = {"template": TEMPLATE_IDS, "skin_rpt": SKIN_IDS, "font": FONT_IDS}


# ---------------------------------------------------------------- 归一化
def normalize_value(key: str, value) -> str:
    """单个字段归一：不认识的值一律回落缺省，绝不抛异常（接口不报 400）。"""
    allowed = _ALLOWED.get(key)
    if allowed is None:
        return ""
    return value if isinstance(value, str) and value in allowed else _DEFAULTS[key]


def normalize(appearance: dict | None) -> dict:
    """补齐三轴：缺的键、不认识的值都用缺省填满。渲染层与测试都吃这一份结果。"""
    a = appearance if isinstance(appearance, dict) else {}
    return {k: normalize_value(k, a.get(k)) for k in APPEARANCE_KEYS}


def appearance_from_body(body) -> dict:
    """从生成请求体里抽报告外观：**只收确实带了的**三个字段，逐个归一。

    没带任何字段 → 空 dict（调用方据此判断「不加 params 键、不传 generate」）。
    带了不认识的值 → 静默回落缺省。系统皮肤（skin-sys）是前端的事，这里不认。
    """
    if not isinstance(body, dict):
        return {}
    return {k: normalize_value(k, body.get(k)) for k in APPEARANCE_KEYS if k in body}


# ---------------------------------------------------------------- 签名与标记
# 生成件 <head> 里留一枚可核对的标记：馆员在设置里换了模板/皮肤/字体再点「生成」，
# 后端靠它判断「旧文件的外观和这次要的不一样」，从而重出而不是直接返回旧件。
_META_NAME = "wenheng-appearance"
_META_RE = re.compile(r'<meta\s+name="' + _META_NAME + r'"\s+content="([^"]*)"\s*/?>')
# 判断幂等时只读文件开头这一小段字符（标记就在 <head> 靠前处），不整份读大文件。
_HEAD_READ_LIMIT = 4096


def signature(appearance: dict | None) -> str:
    """三轴签名＝归一后的 `template|skin_rpt|font`（例如 `A|huize|song`）。

    三个值都取自白名单，没有引号 / 尖括号 / &，写进 HTML 属性不用转义。
    """
    a = normalize(appearance)
    return f"{a['template']}|{a['skin_rpt']}|{a['font']}"


def head_meta(appearance: dict | None) -> str:
    """生成件 <head> 里的标记行（自带换行）。

    appearance 为 None → 返回空串：一个字都不加，保证不带外观时逐字节不变。
    """
    if appearance is None:
        return ""
    return f'<meta name="{_META_NAME}" content="{signature(appearance)}">\n'


def read_signature(html_text: str) -> str | None:
    """从 HTML 文本（通常只是头部片段）里解析标记值；缺失 / 畸形 → None（legacy 件）。"""
    m = _META_RE.search(html_text)
    return m.group(1) if m else None


def read_signature_from_file(path) -> str | None:
    """只读文件头部若干字符解析签名，不整份读大文件；读不了 / 无标记 → None。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return read_signature(fh.read(_HEAD_READ_LIMIT))
    except (OSError, UnicodeError, ValueError):
        return None


# ---------------------------------------------------------------- CSS 片段
def _root_css(skin_id: str, font: dict) -> str:
    """注入的 :root —— --rpt-* 皮肤变量 + 字体变量 + 把现网 _CSS 的老变量名接到皮肤上。

    老变量（--bg/--ink/--muted/--line…）被重指向 --rpt-*，这样现网 _CSS 不用改一行
    就跟着换纸墨。次要文字用 color-mix 派生，保证对比度。yebo 的纸墨值本就反着写，
    于是深色皮肤自动是「深纸浅字」。
    """
    s = SKINS[skin_id]
    seal, gold = ("#C0503F", "#C9A961") if skin_id == "yebo" else ("#8B1E1E", "#B08E48")
    decls = [
        f"--rpt-accent:{s['accent']}",
        f"--rpt-accent-2:{s['accent2']}",
        f"--rpt-tint:{s['tint']}",
        f"--rpt-paper:{s['paper']}",
        f"--rpt-ink:{s['ink']}",
        f"--rpt-seal:{seal}",
        f"--rpt-gold:{gold}",
        "--rpt-muted:color-mix(in srgb,var(--rpt-ink) 80%,var(--rpt-paper))",
        "--rpt-rule:color-mix(in srgb,var(--rpt-ink) 16%,var(--rpt-paper))",
        "--rpt-rule-2:color-mix(in srgb,var(--rpt-ink) 9%,var(--rpt-paper))",
        "--rpt-rule-strong:color-mix(in srgb,var(--rpt-ink) 28%,var(--rpt-paper))",
        "--rpt-accent-text:var(--rpt-accent)",
        # 基础字族栈（kai/fang/li/xing 用 var() 串成回落链）
        '--f-song:"Noto Serif SC","Songti SC",SimSun,serif',
        '--f-hei:"Microsoft YaHei","PingFang SC",SimHei,system-ui,sans-serif',
        '--f-kai:KaiTi,"Kaiti SC","STKaiti",var(--f-song)',
        '--f-fang:FangSong,"STFangsong",SimFang,var(--f-song)',
        '--f-li:LiSu,SimLi,"STLiti",var(--f-kai)',
        '--f-xing:"STXingkai","华文行楷",var(--f-kai)',
        f"--rpt-f-body:{font['body']}",
        f"--rpt-f-title:{font['title']}",
        f"--rpt-fs-adj:{font['adj']}",
        # 把现网 _CSS 的老变量接到 --rpt-*（后写的 :root 覆盖 _CSS 里的旧值）
        "--bg:var(--rpt-paper)",
        "--card:var(--rpt-tint)",
        "--ink:var(--rpt-ink)",
        "--ink-2:var(--rpt-muted)",
        "--muted:var(--rpt-muted)",
        "--line:var(--rpt-rule)",
        "--line-2:var(--rpt-rule-2)",
        "--ok:var(--rpt-accent)",
        "--ok-bg:var(--rpt-tint)",
        "--warn:var(--rpt-seal)",
        "--warn-bg:var(--rpt-tint)",
    ]
    return ":root{" + "".join(d + ";" for d in decls) + "}"


#: 字体落进 DOM：正文吃 --rpt-f-body，标题吃 --rpt-f-title（隶/行楷只到标题）。
#: h2 .num 与 td .en 的等宽数字字体在 _CSS 里自带 font-family，优先级更高，保持不变。
_FONT_CSS = """html[data-font] body{font-family:var(--rpt-f-body);font-size:calc(15.5px + var(--rpt-fs-adj))}
html[data-font] h1,html[data-font] h2{font-family:var(--rpt-f-title)}"""

#: 图表上色（2026-11-05 v3）：monitor/charts.py 带外观时输出 class 名
#: （gk-*＝fill、gl-*＝stroke、gf-mono＝等宽字族），不再写死 hex——实测 var() 在
#: SVG 表现属性里各引擎解析不一致（svgwg#1031），class + 注入 CSS 跨引擎稳，
#: 且 CSS 规则优先级恒高于表现属性；None 路径（SVG 里无 class）零影响。
#: 派生系列色（s4/s5）向 --rpt-ink 方向 color-mix：浅皮变深、深皮（yebo）变浅，
#: 两头对比度都不丢。发丝线线宽/虚线档在 charts.py 侧（数据 > 参考线 > 网格）。
_CHART_CSS = """section svg .gk-ink{fill:var(--rpt-ink)}section svg .gl-ink{stroke:var(--rpt-ink)}
section svg .gk-mut{fill:var(--rpt-muted)}section svg .gl-mut{stroke:var(--rpt-muted)}
section svg .gk-rule{fill:var(--rpt-rule)}section svg .gl-rule{stroke:var(--rpt-rule)}
section svg .gk-rule2{fill:var(--rpt-rule-2)}section svg .gl-rule2{stroke:var(--rpt-rule-2)}
section svg .gk-acc{fill:var(--rpt-accent)}section svg .gl-acc{stroke:var(--rpt-accent)}
section svg .gk-gold{fill:var(--rpt-gold)}section svg .gl-gold{stroke:var(--rpt-gold)}
section svg .gk-s0{fill:var(--rpt-accent)}section svg .gl-s0{stroke:var(--rpt-accent)}
section svg .gk-s1{fill:var(--rpt-gold)}section svg .gl-s1{stroke:var(--rpt-gold)}
section svg .gk-s2{fill:var(--rpt-accent-2)}section svg .gl-s2{stroke:var(--rpt-accent-2)}
section svg .gk-s3{fill:var(--rpt-muted)}section svg .gl-s3{stroke:var(--rpt-muted)}
section svg .gk-s4{fill:color-mix(in srgb,var(--rpt-accent) 62%,var(--rpt-ink))}section svg .gl-s4{stroke:color-mix(in srgb,var(--rpt-accent) 62%,var(--rpt-ink))}
section svg .gk-s5{fill:color-mix(in srgb,var(--rpt-accent-2) 62%,var(--rpt-ink))}section svg .gl-s5{stroke:color-mix(in srgb,var(--rpt-accent-2) 62%,var(--rpt-ink))}
section svg .gf-mono{font-family:var(--rpt-f-body),ui-monospace,Consolas,monospace}"""


def _chart_css() -> str:
    """图表 class 上色规则（charts.py 带外观时的配套注入；v2 的按 hex 属性值
    覆盖做法已退役——图表现在自带 class，不再有 hex 可对号）。"""
    return _CHART_CSS


#: yebo 深色皮打印时反白：纸转白、墨转深，免得深色底吃光墨粉、浅字印不出来。
_PRINT_CSS = """@media print{
html[data-skin-rpt="yebo"]{--rpt-paper:#fff;--rpt-ink:#1A1A1A;--rpt-muted:#444;
--rpt-accent:#3C3C3F;--rpt-accent-2:#666668;--rpt-rule:#ccc;--rpt-rule-2:#ddd;
--rpt-rule-strong:#999;--rpt-tint:#fff;--rpt-seal:#8B1E1E;--rpt-gold:#8A6A2F}
html[data-skin-rpt="yebo"] body{background:#fff;color:#1A1A1A}
}"""


# ---------------------------------------------------------------- 五套模板 CSS 变体
#: 五套都作用在同一份 DOM 上，靠下面这几条 `[data-template="X"]` 覆盖规则拉开差异。
#: 类名与 DOM 顺序一律保留（SchoolsPage 反解靠 .nums .nm/.nl/.nv/.nx、section.flow table）。
TEMPLATE_CSS = {
    # A 会泽经折：左窄栏竖排书脊（h1::before + 竖排）＋ 金线压边、细横线表。
    "A": """[data-template="A"] .wrap{position:relative;padding-left:76px;max-width:1040px}
[data-template="A"] h1::before{content:"学 科 监 测";position:absolute;left:0;top:40px;
writing-mode:vertical-rl;text-orientation:upright;
font-family:var(--rpt-f-title);font-size:20px;font-weight:400;letter-spacing:.5em;
line-height:1;height:264px;color:var(--rpt-accent-text);
border-right:.5px solid var(--rpt-gold);padding-right:14px;white-space:nowrap}
[data-template="A"] section{border-top:.5px solid var(--rpt-gold);padding-top:18px}
[data-template="A"] footer{border-top:.5px solid var(--rpt-gold)}
[data-template="A"] .nums .nm{border:0;border-left:1px solid var(--rpt-gold);border-radius:0;background:transparent}
[data-template="A"] h2 .num{color:var(--rpt-gold)}""",
    # B 现有版式＝现网 _CSS 基线：不叠加任何版式覆盖，只吃皮肤与字体变量。
    "B": "",
    # C 册页图录：一屏一页绢本卡、大留白、上下细分隔做册页。
    "C": """[data-template="C"] .wrap{max-width:940px}
[data-template="C"] section{margin-top:64px;padding:30px 0 42px;
border-top:.5px solid var(--rpt-rule-strong);border-bottom:.5px solid var(--rpt-rule-2)}
[data-template="C"] section::after{content:"";display:block;height:.5px;background:var(--rpt-rule-2);margin-top:36px}
[data-template="C"] h2{letter-spacing:.16em}
[data-template="C"] .nums .nm{border:0;border-bottom:.5px solid var(--rpt-rule-strong);border-radius:0;background:transparent;padding-left:0}
[data-template="C"] table{margin-top:22px}""",
    # D 碑拓夜泊：极细金线发丝（边框/表线）＋ 碑刻感字距；深色纸由 yebo 皮肤配合达成，
    #    这里只用 color-mix 做一点压暗，浅色皮肤下深字仍清晰、不与皮肤轴打架。
    "D": """[data-template="D"] body{background:color-mix(in srgb,var(--rpt-paper) 92%,var(--rpt-ink))}
[data-template="D"] h1,[data-template="D"] h2{letter-spacing:.18em;font-weight:500}
[data-template="D"] .nums .nm{border:1px solid var(--rpt-gold);background:transparent}
[data-template="D"] section{border-top:.5px solid var(--rpt-gold);padding-top:20px}
[data-template="D"] th,[data-template="D"] td,[data-template="D"] footer{border-color:var(--rpt-gold)}
[data-template="D"] footer{border-top:.5px solid var(--rpt-gold)}
[data-template="D"] h2 .num{color:var(--rpt-gold)}
[data-template="D"] .lead b{background:transparent;color:var(--rpt-gold);border-bottom:.5px solid var(--rpt-gold)}""",
    # E 方志·双栏夹批：解读段两栏紧排（只命中带内联 style 的解读段）+ 表格密度收紧。
    "E": """[data-template="E"] table{font-size:12px;margin-top:10px}
[data-template="E"] th,[data-template="E"] td{padding-top:4px;padding-bottom:4px}
[data-template="E"] section:has(p[style]){column-count:2;column-gap:30px}
[data-template="E"] section:has(p[style]) h2{column-span:all}
[data-template="E"] section:has(p[style]) p{break-inside:avoid}""",
}


def appearance_css(appearance: dict | None) -> str:
    """返回要注入 <style> 的 CSS 字符串（追加在 _CSS 之后）。

    appearance 只带部分字段也行，normalize() 会补齐。B 模板无版式覆盖，
    所以五套各自产出的 CSS 互不相同，但数字区永远是同一份 DOM。
    """
    a = normalize(appearance)
    parts = [
        _root_css(a["skin_rpt"], FONTS[a["font"]]),
        _FONT_CSS,
        _chart_css(),
        _PRINT_CSS,
        TEMPLATE_CSS[a["template"]],
    ]
    return "\n".join(p for p in parts if p)
