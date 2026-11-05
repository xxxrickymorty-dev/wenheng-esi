# -*- coding: utf-8 -*-
"""monitor/charts.py 外观参数化回归（2026-11-05）。

金标：appearance=None 输出与改造前**逐字节一致**——三条核心生成器各钉一条
sha256（改造前后曾用 tmp/_charts_none_bytes.py 全分支比对 11 例全过）。
带外观：SVG 只出 class（gk-*＝fill、gl-*＝stroke、gf-mono＝等宽字族），
真色值由 appearance._chart_css() 注入的 --rpt-* 规则决定——var() 在 SVG
表现属性里各引擎解析不一致（svgwg#1031），不走 var() 直写。
透传：render → report_data → charts.*，appearance 原样下传。

纯内存用例（透传一条只读真实缓存、不落盘），无需 _guard_registry 之外的登记。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from _guard_registry import skip_unless             # noqa: E402
from monitor import appearance as ap                # noqa: E402
from monitor import charts as mc                    # noqa: E402
from monitor import report as mr                    # noqa: E402

# ---------------------------------------------------------------- 金标 sha256
# 样例数据钉在下面三个用例里；改样例必须连 sha256 一起换（并跑全分支比对）。
_HBAR_GOLD = "45f924e4842fc0a42e82f09b81bb889a7a22040facd8554cc6e4e4b75f6c0322"
_LINE_GOLD = "45dfc346a29d3f2152b51719efb671e045e5614b3e886d71f27b370dbeed3446"
_STRIP_GOLD = "c8efd5a7ea5950deb49acb99ecbd6c5270ef08c17f1de58d15cf64a48835dbf4"

_HBAR_ROWS = [("化学", 56.3, " ↑"), ("植物与动物学", 31.2), ("工程学", 12.87),
              ("数学", 6.1), ("一个名字特别特别长的学科 label", 1.02)]
_LINE_SERIES = [("总被引", [("202601", 100), ("202603", None), ("202605", 220), ("202607", 315)]),
                ("化学", [("202601", None), ("202603", 8)]),
                ("物理", [("202605", 42)])]
_STRIP_ROWS = [("化学", 12, 1200, 120), ("植物与动物学", 3, 900, 90),
               ("社会科学，综合", 45, 3000, 300)]

#: 现网 None 路径的全部硬编码色（带外观时一个都不许再出现）
_HEXES = ("#17181a", "#6f7278", "#e4e1da", "#2f6f5e", "#9a6b14", "#eef0ee",
          "#7FB79B", "#A8B8D0", "#C9A66B")


def test_1_hbar_None逐字节():
    svg = mc.hbar_log(_HBAR_ROWS, lo=0.5, ref=1.0, ref_label="1× 阈值",
                      fmt=lambda v: f"{v:.2f}", tick_fmt=lambda v: f"{v:g}×")
    assert hashlib.sha256(svg.encode()).hexdigest() == _HBAR_GOLD
    assert "class=" not in svg and "var(" not in svg, "None 路径不加 class / var"


def test_1b_line_None逐字节():
    svg = mc.line_chart(_LINE_SERIES, ref_lines=[(300, "1‰"), (50, "1%")], y_invert=True)
    assert hashlib.sha256(svg.encode()).hexdigest() == _LINE_GOLD
    assert "class=" not in svg and "var(" not in svg


def test_1c_strip_None逐字节():
    svg = mc.permille_strip(_STRIP_ROWS)
    assert hashlib.sha256(svg.encode()).hexdigest() == _STRIP_GOLD
    assert "class=" not in svg and "var(" not in svg


def test_2_带外观走class且无hex():
    a = {"skin_rpt": "zhusha"}
    svg = mc.hbar_log(_HBAR_ROWS, lo=0.5, ref=1.0, ref_label="1× 阈值",
                      fmt=lambda v: f"{v:.2f}", appearance=a)
    assert 'class="gk-acc"' in svg and 'class="gl-rule"' in svg, "fill/stroke 都走 class"
    assert 'class="gf-mono"' in svg, "等宽字族走 class（字体跟 --rpt-f-body）"
    for hx in _HEXES:
        assert hx not in svg, f"带外观不许再出现硬编码色 {hx}"
    assert "var(" not in svg, "var() 不直写进 SVG（表现属性解析不一致，走注入 CSS）"
    # 空 dict 与部分字段同样生效（normalize 由 CSS 侧兜底，图表只看 None 与否）
    assert 'class="gk-acc"' in mc.hbar_log(_HBAR_ROWS, appearance={})
    # 三图型都换了语法
    svg2 = mc.line_chart(_LINE_SERIES, appearance=a)
    assert 'class="gl-s0"' in svg2 and 'r="2"' in svg2, "折线发丝级 + 数据点小圆"
    svg3 = mc.permille_strip(_STRIP_ROWS, appearance=a)
    assert 'stroke-width="1.2"' in svg3 and 'stroke-width="1.4"' in svg3, "细轨 + 1‰ 线降级"


def test_3_发丝线层级_数据大于参考大于网格():
    svg = mc.line_chart(_LINE_SERIES, ref_lines=[(300, "1‰")],
                        appearance={"skin_rpt": "huize"})
    assert 'stroke-width="1.3"' in svg, "数据线 1.3"
    assert 'stroke-width="1.1"' in svg, "参考线 1.1"
    assert 'stroke-width=".6"' in svg, "网格 0.6 点线"
    assert 'stroke-dasharray="1 3"' in svg, "横向网格转 dotted"
    bar = mc.hbar_log(_HBAR_ROWS, appearance={"skin_rpt": "huize"})
    assert 'stroke-width=".6"' in bar and 'stroke-dasharray="2 3"' in bar, "竖向网格转虚线导轨"
    assert 'stroke-width=".5"' in bar, "每行一条 .5px 账本纸横线"
    ref = mc.hbar_log(_HBAR_ROWS, lo=0.5, ref=1.0, appearance={"skin_rpt": "huize"})
    assert 'stroke-width="1"' in ref, "参考线 1px（< 柱体、> 网格）"


def test_4_图表class有配套CSS注入():
    css = ap.appearance_css({"skin_rpt": "yebo"})
    for cls in (".gk-ink", ".gl-ink", ".gk-mut", ".gl-mut", ".gk-rule", ".gl-rule",
                ".gk-rule2", ".gl-rule2", ".gk-acc", ".gl-acc", ".gk-gold", ".gl-gold",
                ".gk-s0", ".gl-s0", ".gk-s5", ".gl-s5", ".gf-mono"):
        assert cls + "{" in css, f"注入 CSS 缺 {cls}"
    assert "color-mix(in srgb,var(--rpt-accent) 62%,var(--rpt-ink))" in css, \
        "派生系列色向 ink 方向 mix（浅皮变深、深皮变浅，两头对比度都不丢）"
    assert "font-family:var(--rpt-f-body),ui-monospace" in css
    # CSS 只在带外观时注入；None 渲染出的 SVG 无 class，规则命中不了它
    assert "class=" not in mc.hbar_log(_HBAR_ROWS)


# ---------------------------------------------------------------- 透传
def test_5_appearance透传到图表生成器(monkeypatch):
    """render → report_data → charts.*：appearance 原样下传；None 也如实传 None。"""
    p = mr.latest_period()
    probe = lambda: bool(p) and mr.cache_path(p).exists()          # noqa: E731
    if not probe():
        skip_unless("监测版期次缓存未建（透传校验缺席）", probe)
    cache = mr.load_cache(p)
    got: list = []

    def _spy(name):
        real = getattr(mc, name)

        def wrap(*a, **k):
            got.append((name, k.get("appearance", "__missing__")))
            return real(*a, **k)
        return wrap

    for name in ("donut", "permille_strip", "line_chart", "entry_timeline", "hbar_log"):
        monkeypatch.setattr(mr.charts, name, _spy(name))
    mr.render("海南大学", p, cache, appearance={"skin_rpt": "zhusha"})
    assert got, "渲染应调用过图表生成器"
    assert all(ap_ == {"skin_rpt": "zhusha"} for _, ap_ in got), \
        f"appearance 没原样下传：{set(map(str, (a for _, a in got)))}"
    got.clear()
    mr.render("海南大学", p, cache)
    assert got and all(ap_ is None for _, ap_ in got), "不带外观：图表收到 None（逐字节旧路径）"


def test_6_对比件图表也吃外观(monkeypatch):
    """compare.render 的三处图表落点同样下传 appearance。"""
    p = mr.latest_period()
    probe = lambda: bool(p) and mr.cache_path(p).exists()          # noqa: E731
    if not probe():
        skip_unless("监测版期次缓存未建（对比件透传校验缺席）", probe)
    from monitor import compare as mcmp
    cache = mr.load_cache(p)
    got: list = []

    def _spy(name):
        real = getattr(mcmp.mch, name)

        def wrap(*a, **k):
            got.append(k.get("appearance", "__missing__"))
            return real(*a, **k)
        return wrap

    for name in ("line_chart", "dumbbell", "donut"):
        monkeypatch.setattr(mcmp.mch, name, _spy(name))
    mcmp.render(["海南大学", "清华大学"], p, cache, appearance={"skin_rpt": "yebo"})
    assert got, "对比件应调用过图表生成器"
    assert all(ap_ == {"skin_rpt": "yebo"} for ap_ in got)
    got.clear()
    mcmp.render(["海南大学", "清华大学"], p, cache)
    assert got and all(ap_ is None for ap_ in got)
