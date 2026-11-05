# -*- coding: utf-8 -*-
"""灵活报告（第二条产线）的外观：模板 / 皮肤 / 字体。

与监测版（monitor/appearance.py）共用同一套三轴数据与归一逻辑——
12 套皮肤、6 套字体、取值表与「不认识的值静默回落」都在那边，
这里只 import 公开 API（SKINS/FONTS/normalize/signature/head_meta/
appearance_from_body），**不复制表**。

本模块做的事：把 monitor 的 `--rpt-*` 皮肤变量接到 flexible 自己的
HTML 外壳（mdview.SHELL，R04 书脊骨架）上。SHELL 的老变量名与
monitor 网页不同（--bg/--ink/--ink-2/--faint/--line/--sans），
注入时把老变量重指向 --rpt-*，SHELL 一行不用改就跟着换纸墨。

五套模板与 monitor 同语义（A 会泽经折 / B 基线 / C 册页图录 /
D 碑拓夜泊 / E 方志双栏），但操作对象是 flexible 自己的 DOM
（.sheet/.spine/.tophead/.secthead/.stats/table.dense/figure/
.fx-about/.export-mark），所以 CSS 是另写的一套，不是照抄。

红线：外观只动版式/颜色/字体，数字与正文一个字不改。
零外链、零 CDN。
"""
from __future__ import annotations

from monitor.appearance import (FONTS, SKINS, appearance_from_body,  # noqa: F401
                                 head_meta, normalize, signature)

# ---------------------------------------------------------------- :root 注入
def _root_css(skin_id: str, font: dict) -> str:
    """:root —— --rpt-* 皮肤变量 + 基础字族栈 + SHELL 老变量重指向。

    老变量（--bg/--ink/--ink-2/--faint/--line/--sans）接在 --rpt-* 上，
    后写的 :root 覆盖 SHELL 里的旧值；次要文字与分隔线用 color-mix
    从纸墨派生，深色皮（yebo 的纸墨值本就反着写）自动是深纸浅字。
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
        # 基础字族栈（FONTS 里 kai/fang/li/xing 用 var() 串回落链）
        '--f-song:"Noto Serif SC","Songti SC",SimSun,serif',
        '--f-hei:"Microsoft YaHei","PingFang SC",SimHei,system-ui,sans-serif',
        '--f-kai:KaiTi,"Kaiti SC","STKaiti",var(--f-song)',
        '--f-fang:FangSong,"STFangsong",SimFang,var(--f-song)',
        '--f-li:LiSu,SimLi,"STLiti",var(--f-kai)',
        '--f-xing:"STXingkai","华文行楷",var(--f-kai)',
        f"--rpt-f-body:{font['body']}",
        f"--rpt-f-title:{font['title']}",
        f"--rpt-fs-adj:{font['adj']}",
        # SHELL 老变量重指向 --rpt-*（--ink-3 是 SHELL 的小字灰，一并跟纸墨走）
        "--bg:var(--rpt-paper)",
        "--ink:var(--rpt-ink)",
        "--ink-2:var(--rpt-muted)",
        "--ink-3:var(--rpt-muted)",
        "--line:var(--rpt-rule)",
        "--faint:var(--rpt-rule-2)",
        "--sans:var(--rpt-f-body)",
    ]
    return ":root{" + "".join(d + ";" for d in decls) + "}"


#: 字体落进 DOM：正文吃 --rpt-f-body（SHELL 的 --sans 已重指向，body 天然跟随，
#: 这里只补字号微调），标题（书脊 / 节标题 / h2 h3）吃 --rpt-f-title。
#: 隶 / 行楷只进标题，正文分别落回宋 / 仿宋——与 monitor 同一套约定。
_FONT_CSS = """html[data-font] body{font-size:calc(15px + var(--rpt-fs-adj))}
html[data-font] .spine .t,html[data-font] .secthead .t,
html[data-font] h2,html[data-font] h3{font-family:var(--rpt-f-title)}"""

#: SHELL 里有几处写死浅色底（表头 / 引用 / 代码 / 折叠块 / 图底），
#: 变量够不着它们——按选择器重指到皮肤色，深色皮才不至于白块压深纸。
_SURFACE_CSS = """[data-skin-rpt] table.dense th{background:var(--rpt-tint)}
[data-skin-rpt] blockquote{background:var(--rpt-tint)}
[data-skin-rpt] code{background:var(--rpt-tint)}
[data-skin-rpt] details.fx-about{background:var(--rpt-tint)}
[data-skin-rpt] figure img{background:var(--rpt-paper)}"""

#: yebo 深色皮打印时反白：纸转白、墨转深，免得深色底吃光墨粉、浅字印不出来。
_PRINT_CSS = """@media print{
html[data-skin-rpt="yebo"]{--rpt-paper:#fff;--rpt-ink:#1A1A1A;--rpt-muted:#444;
--rpt-accent:#3C3C3F;--rpt-accent-2:#666668;--rpt-rule:#ccc;--rpt-rule-2:#ddd;
--rpt-rule-strong:#999;--rpt-tint:#fff;--rpt-seal:#8B1E1E;--rpt-gold:#8A6A2F}
html[data-skin-rpt="yebo"] body{background:#fff;color:#1A1A1A}
}"""


# ---------------------------------------------------------------- 五套模板 CSS 变体
#: 同一份 SHELL DOM 上的五套 `[data-template="X"]` 覆盖规则。
#: B ＝现网 R04 外壳基线，不叠加任何版式覆盖。
TEMPLATE_CSS = {
    # A 会泽经折：现有竖排书脊骨架上压金线（书脊 / 顶注 / 节引线 / 统计行），
    #   表格去竖线只留细横线（经折装是一栏栏横条）。
    "A": """[data-template="A"] .spine{border-right:1px solid var(--rpt-gold)}
[data-template="A"] .spine .t{color:var(--rpt-accent)}
[data-template="A"] .tophead{border-bottom:1px solid var(--rpt-gold)}
[data-template="A"] .secthead .line{border-top:1px solid var(--rpt-gold)}
[data-template="A"] .stats{border-top:1px solid var(--rpt-gold)}
[data-template="A"] .export-mark{border-top:1px solid var(--rpt-gold)}
[data-template="A"] table.dense th,[data-template="A"] table.dense td{
border-left:0;border-right:0;border-top:.5px solid var(--rpt-rule-2)}
[data-template="A"] table.dense th{border-bottom:1px solid var(--rpt-gold)}""",
    # B 现有版式＝现网 SHELL 基线：不叠加，只吃皮肤与字体变量。
    "B": "",
    # C 册页图录：一屏一页、大留白、上下细分隔——节与节之间拉开成册页。
    "C": """[data-template="C"] .secthead{margin:72px 0 20px;padding-bottom:14px;
border-bottom:.5px solid var(--rpt-rule-2)}
[data-template="C"] .secthead.first{margin-top:8px}
[data-template="C"] .secthead .t{letter-spacing:.2em}
[data-template="C"] figure{margin:34px 0}
[data-template="C"] table.dense{margin:26px 0}
[data-template="C"] .export-mark{margin-top:64px}""",
    # D 碑拓夜泊：极细金线发丝 + 碑刻感字距 + 压暗纸面（color-mix 一点墨进纸，
    #   浅色皮下深字仍清晰，不与皮肤轴打架）。
    "D": """[data-template="D"] body{background:color-mix(in srgb,var(--rpt-paper) 92%,var(--rpt-ink))}
[data-template="D"] .spine .t,[data-template="D"] .secthead .t,
[data-template="D"] h2,[data-template="D"] .tophead .site{letter-spacing:.22em}
[data-template="D"] .spine{border-right:.5px solid var(--rpt-gold)}
[data-template="D"] .tophead{border-bottom:.5px solid var(--rpt-gold)}
[data-template="D"] .secthead .line{border-top:.5px solid var(--rpt-gold)}
[data-template="D"] .stats{border-top:.5px solid var(--rpt-gold)}
[data-template="D"] table.dense th,[data-template="D"] table.dense td{
border-color:var(--rpt-gold);border-width:.5px}""",
    # E 方志·双栏夹批：正文两栏排（图 / 表 / 统计行 / 折叠块通栏），
    #   表格密度收紧——方志是一页页密排的小字。
    "E": """[data-template="E"] .wrap{column-count:2;column-gap:34px}
[data-template="E"] .tophead,[data-template="E"] .secthead,
[data-template="E"] .stats,[data-template="E"] figure,[data-template="E"] .figrow,
[data-template="E"] table.dense,[data-template="E"] blockquote,
[data-template="E"] details.fx-about,[data-template="E"] hr,
[data-template="E"] .export-mark{column-span:all}
[data-template="E"] p,[data-template="E"] li{break-inside:avoid}
[data-template="E"] table.dense{font-size:12px;margin:10px 0}
[data-template="E"] table.dense th,[data-template="E"] table.dense td{padding:4px 8px}""",
}


def flex_appearance_css(appearance: dict | None) -> str:
    """返回要追加到 SHELL `<style>` 之后的 CSS（monitor 模式同款）。

    appearance 只带部分字段也行，normalize() 会补齐；不认识的值
    静默回落缺省。B 模板无版式覆盖，五套各自产出的 CSS 互不相同。
    """
    a = normalize(appearance)
    parts = [
        _root_css(a["skin_rpt"], FONTS[a["font"]]),
        _FONT_CSS,
        _SURFACE_CSS,
        _PRINT_CSS,
        TEMPLATE_CSS[a["template"]],
    ]
    return "\n".join(p for p in parts if p)
