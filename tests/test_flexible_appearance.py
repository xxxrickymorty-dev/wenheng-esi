# -*- coding: utf-8 -*-
"""灵活报告外观三轴（模板 / 皮肤 / 字体）落地回归。

对应 monitor 线（tests/test_monitor_appearance.py）的同一条纪律，
落到 flexible 线（mdview.SHELL 外壳 / report 产物 / 路由）：

1 不带 appearance 时 standalone() 输出与改造前逐字节一致（golden sha256 锁定）；
2 带外观：html 挂三个 data-* 属性、--rpt-* 变量与签名 meta 注入；
3 五套模板 CSS 互不相同且 B 为空串（同一份 DOM 上的 CSS 变体）；
4 不认识的值静默回落缺省、绝不抛异常；
5 flex_meta.json 记 appearance；下载口复刻路由逻辑用 meta 外观
  重渲染出与生成件相同的签名；润色（plan 复用）不把外观洗掉；
6 ECharts 渲染层 _INIT_JS 本身不改（读 --rpt-*，读不到回落），
   注入 CSS 提供它要的变量名。

纯函数用例零依赖；数据驱动用例复用 test_flexible 的做法——
金标期次拷到临时目录、显式注入 RuleBrain（不出网）、
产物只落 tmp_path、缺数据走 `_guard_registry.skip_unless`。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

import pytest

from _guard_registry import skip_unless

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from flexible import mdview, report                 # noqa: E402
import flexible.appearance as fa                 # noqa: E402
from monitor import appearance as ap            # noqa: E402

# ---------------------------------------------------------------- 纯函数部分

#: 1 的基线：改造前 standalone() 对固定 md 的输出逐字节 sha256。
#: 2026-11-05 实测固定值；None 时外壳/正文一个字节都不许动。
_GOLDEN_STANDALONE_SHA = ("82222a5380e63b3ad305f05bbf6feca47ec7106ef837bf0a8"
                          "f4617aa89839091")

#: 固定样例 md：覆盖稿首元信息 / 大数表 / 列表 / 图 / 待审线 / 关于本稿。
SAMPLE_MD = """# 测试稿

> 期次：202607
> 意图：单学科态势

正文一段，说明本期表现。

## 一、总体态势

| 指标 | 数值 | 来源 |
|---|---|---|
| 高被引论文 | 12 | 台账 L12 |

- 项一
- 项二

![图](charts/x.png)

==待审句==与普通句。

## 本稿如何产生

数据来自台账。
"""


def _standalone_sample(**kw) -> str:
    return mdview.standalone(SAMPLE_MD, "测试稿", **kw)


def test_1_不带外观逐字节不变():
    base = _standalone_sample()
    assert hashlib.sha256(base.encode("utf-8")).hexdigest() == \
        _GOLDEN_STANDALONE_SHA, "改造前后：不带 appearance 时输出必须逐字节一致"
    assert _standalone_sample(appearance=None) == base, "None 与不传完全一致"
    # 注入机制完全惰性：不挂属性、不追加第二段 <style>、不写签名 meta
    assert base.count("<style>") == 1
    for marker in ("data-template", "data-skin-rpt", "data-font",
                   "--rpt-", "wenheng-appearance"):
        assert marker not in base


def test_2_带外观挂属性变量与签名():
    a = {"template": "A", "skin_rpt": "zhusha", "font": "kai"}
    h = _standalone_sample(appearance=a)
    assert '<html lang="zh-CN" data-template="A" data-skin-rpt="zhusha" ' \
           'data-font="kai">' in h
    assert '<meta name="wenheng-appearance" content="A|zhusha|kai">' in h
    # 皮肤色值来自 monitor 的唯一色值源（朱砂 paper / ink）
    assert "--rpt-paper:#F7F2E8" in h and "--rpt-ink:#2A1E1A" in h
    # SHELL 老变量被重指向 --rpt-*（外壳一行不改就换纸墨）
    for old, new in (("--bg:var(--rpt-paper)", "--ink:var(--rpt-ink)"),
                     ("--ink-2:var(--rpt-muted)", "--line:var(--rpt-rule)"),
                     ("--faint:var(--rpt-rule-2)", "--sans:var(--rpt-f-body)")):
        assert old in h and new in h
    # 字体：正文吃 --rpt-f-body（楷体），书脊/节标题/h2 h3 吃 --rpt-f-title
    assert "--rpt-f-body:var(--f-kai)" in h and "--rpt-f-title:var(--f-kai)" in h
    assert "html[data-font] .spine .t" in h and "html[data-font] h2" in h
    # 正文与数字区一字不动（改动前后 body 内容一致）
    assert '<div class="kpi"><div class="v">12</div>' in h
    assert '<span class="fx-mark">待审句</span>' in h


def test_3_五套模板CSS互不相同且B为空():
    assert fa.TEMPLATE_CSS["B"] == "", "B＝现网外壳基线，不叠加"
    assert len(set(fa.TEMPLATE_CSS.values())) == 5, "五套 CSS 变体互不相同"
    # 同一份 DOM：五套模板渲染出的正文区逐字节一致，只有注入 CSS 不同
    styles, bodies = [], []
    for t in "ABCDE":
        h = _standalone_sample(appearance={"template": t})
        assert f'data-template="{t}"' in h
        styles.append(h.split("</style><style>", 1)[1].split("</style>", 1)[0])
        bodies.append(h.split("</head>", 1)[1])
    assert len(set(styles)) == 5, "五套模板注入的 CSS 互不相同"
    assert len(set(bodies)) == 1, "版式只改 CSS，DOM 与数字一字不动"
    # 差异点抽查：A 金线压边 / C 大留白分隔 / D 碑刻字距压暗 / E 双栏
    assert "var(--rpt-gold)" in fa.TEMPLATE_CSS["A"]
    assert "margin:72px" in fa.TEMPLATE_CSS["C"]
    assert "letter-spacing:.22em" in fa.TEMPLATE_CSS["D"] and \
        "color-mix" in fa.TEMPLATE_CSS["D"]
    assert "column-count:2" in fa.TEMPLATE_CSS["E"] and \
        "column-span:all" in fa.TEMPLATE_CSS["E"]


def test_4_不认识的值静默回落():
    assert ap.normalize({"template": "Z", "skin_rpt": "不存在", "font": 42}) == \
        {"template": "B", "skin_rpt": "huize", "font": "song"}
    assert ap.normalize({}) == {"template": "B", "skin_rpt": "huize", "font": "song"}
    # 请求体抽取：只收三键、未知回落、绝不抛异常
    assert ap.appearance_from_body(None) == {}
    assert ap.appearance_from_body({"skin_sys": "huize"}) == {}
    assert ap.appearance_from_body({"template": "Z", "font": "kai"}) == \
        {"template": "B", "font": "kai"}
    # 一堆非法值直接渲染也不报错，落到缺省基线
    h = _standalone_sample(appearance={"template": "Z", "skin_rpt": "?", "font": 42})
    assert 'data-template="B"' in h and 'data-skin-rpt="huize"' in h
    assert 'data-font="song"' in h and "--rpt-paper:#F5F3EC" in h


def test_5_皮肤与字体全表注入():
    for sid, s in ap.SKINS.items():
        css = fa.flex_appearance_css({"skin_rpt": sid})
        assert f"--rpt-accent:{s['accent']}" in css
        assert f"--rpt-paper:{s['paper']}" in css and f"--rpt-ink:{s['ink']}" in css
    y = fa.flex_appearance_css({"skin_rpt": "yebo"})
    assert "--rpt-paper:#20262B" in y and "--rpt-ink:#ECE8DF" in y, "深纸浅字"
    assert "@media print" in y and "yebo" in y, "yebo 打印反白规则在"
    for fid, f in ap.FONTS.items():
        css = fa.flex_appearance_css({"font": fid})
        assert f"--rpt-f-body:{f['body']}" in css
        assert f"--rpt-f-title:{f['title']}" in css
    li = fa.flex_appearance_css({"font": "li"})
    assert "--rpt-f-title:var(--f-li)" in li, "隶只进标题，正文落回宋"


def test_6_ECharts渲染层读的变量名注入齐全():
    # _INIT_JS 本身不改：仍读 window.__RPT__ 与 --rpt-*（读不到回落写死色值）
    assert "--rpt-" in mdview._INIT_JS and "__RPT__" in mdview._INIT_JS
    css = fa.flex_appearance_css({})
    for name in ("--rpt-ink:", "--rpt-muted:", "--rpt-rule:",
                 "--rpt-f-body:", "--rpt-paper:"):
        assert name in css, f"ECharts 渲染层需要的 {name} 要在 :root 里"


# ---------------------------------------------------------------- 数据驱动部分
# 复用 test_flexible 的做法：金标期次拷临时目录、RuleBrain 注入（不出网）。


def _period_dir():
    from conftest import REPO
    outs = [p for p in (REPO / "out").glob("20*") if p.is_dir()]
    gold = [p for p in outs if p.name == "202607"
            and (p / "ledger_long.parquet").is_file()]
    if gold:
        return gold[0]
    ok = [p for p in outs if (p / "ledger_long.parquet").is_file()]
    return ok[0] if ok else None


@pytest.fixture(scope="session")
def src(tmp_path_factory):
    d = _period_dir()
    if d is None:
        skip_unless("out/ 下无含 ledger_long.parquet 的期次产物",
                    lambda: bool(_period_dir()))
    tmp = tmp_path_factory.mktemp("period") / d.name
    tmp.mkdir()
    shutil.copyfile(d / "ledger_long.parquet", tmp / "ledger_long.parquet")
    shutil.copytree(d / "wide", tmp / "wide")
    from flexible.datasource import DataSource
    return DataSource(tmp)


@pytest.fixture(scope="session")
def flex_out(src):
    """带外观生成一次灵活报告（规则后端），供多条用例复用。"""
    import ai
    from ai._brain import RuleBrain
    a = {"template": "A", "skin_rpt": "yebo", "font": "kai"}
    with ai.using(brain=RuleBrain()):
        r = report.generate(src.dir, "single_trend", appearance=a)
    return r, a


def test_7_flex_meta记外观_生成件挂签名(flex_out):
    r, a = flex_out
    d = pathlib.Path(r["dir"])
    meta = json.loads((d / "flex_meta.json").read_text(encoding="utf-8"))
    assert meta.get("appearance") == a, "外观原样记进 meta（下载口要复用）"
    html = (d / "report.html").read_text(encoding="utf-8")
    assert 'data-template="A"' in html and 'data-skin-rpt="yebo"' in html
    assert f'content="{ap.signature(a)}"' in html


def test_8_下载口复刻路由逻辑_同外观同签名(flex_out, src):
    """复刻下载口：report.md + flex_sources.json + meta 外观 → 重渲染。

    生成件与下载件的签名必须一致（同一外观重渲染不改签名）。
    """
    r, a = flex_out
    d = pathlib.Path(r["dir"])
    from flexible import echart as fx_echart
    md_text = (d / "report.md").read_text(encoding="utf-8")
    entries = json.loads((d / "flex_sources.json").read_text(encoding="utf-8"))
    payloads = fx_echart.payloads_for(
        [e for e in entries if e.get("kind") == "chart"], src.dir)
    import re
    m = re.match(r"(?m)^#\s+(.+)$", md_text)
    title = m.group(1).strip() if m else "灵活分析稿"
    text = mdview.standalone(md_text, title, base_dir=d,
                              chart_payloads=payloads, appearance=a)
    gen_html = (d / "report.html").read_text(encoding="utf-8")
    sig = f'content="{ap.signature(a)}"'
    assert sig in text and sig in gen_html, "下载件与生成件同签名"
    assert 'data-template="A" data-skin-rpt="yebo" data-font="kai"' in text


def test_9_meta缺失或旧稿_回落None行为不变(src, flex_out):
    """meta 缺失 / 没记外观（旧稿）→ 外观按 None 走，回落行为不变。"""
    from server.routes.flexible import _flex_appearance_from_meta
    r, _a = flex_out
    d = pathlib.Path(r["dir"])
    assert _flex_appearance_from_meta(src.dir, "single_trend") == _a
    # 旧稿：meta 里没有 appearance 键（改完还原，别弄脏共享夹具）
    meta = json.loads((d / "flex_meta.json").read_text(encoding="utf-8"))
    meta.pop("appearance")
    (d / "flex_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    assert _flex_appearance_from_meta(src.dir, "single_trend") is None
    assert _flex_appearance_from_meta(src.dir, "没有这份稿") is None
    meta["appearance"] = _a
    (d / "flex_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    # None 渲染：无任何外观痕迹
    text = mdview.standalone((d / "report.md").read_text(encoding="utf-8"),
                              "t", appearance=None)
    for marker in ("data-template", "--rpt-", "wenheng-appearance"):
        assert marker not in text


def test_10_润色复用plan_外观不被洗掉(flex_out, src):
    """润色路径（plan 复用重出稿）：把 meta 里的外观传回去，外观保留。"""
    from server.routes.flexible import _flex_appearance_from_meta
    r, a = flex_out
    # 模拟润色口：从 meta 读回外观传下去
    got = _flex_appearance_from_meta(src.dir, "single_trend")
    assert got == a
    import ai
    from ai._brain import RuleBrain
    with ai.using(brain=RuleBrain()):
        r2 = report.generate(src.dir, "single_trend", plan=r["plan"],
                              appearance=got)
    meta = json.loads((pathlib.Path(r2["dir"]) / "flex_meta.json")
                      .read_text(encoding="utf-8"))
    assert meta.get("appearance") == a, "润色不把外观洗掉"
    html = (pathlib.Path(r2["dir"]) / "report.html").read_text(encoding="utf-8")
    assert f'content="{ap.signature(a)}"' in html


def test_10b_不带外观润色_与从前一致(flex_out, src):
    """不传外观（旧稿没有该键）：meta 无 appearance 键、html 无痕迹。"""
    import ai
    from ai._brain import RuleBrain
    r, _a = flex_out
    with ai.using(brain=RuleBrain()):
        r2 = report.generate(src.dir, "single_trend", plan=r["plan"])
    meta = json.loads((pathlib.Path(r2["dir"]) / "flex_meta.json")
                      .read_text(encoding="utf-8"))
    assert "appearance" not in meta, "不带外观：meta 形状与从前一致"
    html = (pathlib.Path(r2["dir"]) / "report.html").read_text(encoding="utf-8")
    for marker in ("data-template", "--rpt-", "wenheng-appearance"):
        assert marker not in html
