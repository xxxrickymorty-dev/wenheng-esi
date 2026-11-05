# -*- coding: utf-8 -*-
"""报告外观三轴（模板 / 皮肤 / 字体）落地回归。

全部用例为纯函数 / 内存输入：渲染一律用打桩的 report_data，落盘一律不碰真实
`monitor_data/`（任务口把 create/launch 打桩，不写文件、不起线程）。因此无需
`_guard_registry` 跳过登记。

八条硬约束对应下面的 1–8：
1 不带 appearance 时 render() 输出与改造前逐字节一致（golden sha256 锁定）；
2 五个 template id 各自产出不同 CSS，且数字区是同一份 DOM；
3 12 套皮肤 --rpt-* 注入正确，含 yebo 纸墨反转；
4 6 套字体栈注入正确，隶 / 行楷只作用标题；
5 非法值回落缺省、接口不报错；
6 job params 只在带字段时才加键，单飞 / 幂等键形状不变；外观透传到 generate；
7 Word 出口未被调用 / 未变；
8 generate 幂等按 <head> 签名：换了外观（不带 force）要重出，同外观仍幂等，
  None 与 force 语义照旧（2026-11-05 修「重新生成空跑」同款真 bug）。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import monitor.docx as mdx                          # noqa: E402
import pytest                                       # noqa: E402
from _guard_registry import skip_unless             # noqa: E402
from monitor import appearance as ap                # noqa: E402
from monitor import compare as mc                   # noqa: E402
from monitor import report as mr                    # noqa: E402
from server.routes import monitor as routes         # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 1 的基线：改造前 render()（打桩 report_data 后）输出的逐字节 sha256。
#: 2026-11-05 实测固定值；内容区与 <style> 两行都不许被外观机制改动一个字节。
_GOLDEN_RENDER_SHA = "99e2f79955babe1a4c90286a6ac5833b320925d5faaa3e07b77bbb5c4be7f706"

#: 7 的基线：三个 Word 出口源文件在本次改造前的逐字节 sha256。
_WORD_FILES_SHA = {
    "src/monitor/docx.py": "f92a054aee7cfe3e5268cac8fd15be00bb9533c80c83edfbec75434cea4774a6",
    "src/flexible/docxview.py": "7fe85fc3b89e6731f934325f185e727ae3746041b104a9e08518db7013639ac9",
    "src/fill_docx.py": "a171c8941bd0d9e5dff61949cbd894d6a5b085169562f77208b8c7eb14b96eeb",
}


def _fixed_data() -> dict:
    """固定的 report_data 结果：把渲染外壳与真实数据解耦（数字恒为 12 / 22）。"""
    def sec(n):
        return {"num": n, "title": "第" + n + "节", "notes": ["注"], "flow": True}
    return {
        "cn": "测试大学", "tag": "985 工程", "period": "202609", "built": "2026-11-05",
        "meta": "元信息",
        "nums": [{"label": "指标", "value": "12", "suffix": " / 22", "note": "说明"}],
        "absent_note": None, "insight": None,
        "sections": [sec("一"), sec("二"), sec("三"), sec("四"), sec("五")],
        "algorithms": ["算法"],
        "footer": {"source": "来源", "trend": "趋势", "engine": "引擎"},
    }


@pytest.fixture
def stub_data(monkeypatch):
    """所有 render 走固定数据，隔离真实台账 / 缓存漂移。"""
    monkeypatch.setattr(mr, "report_data", lambda *a, **k: _fixed_data())


# ---------------------------------------------------------------- 1 字节不变
def test_1_不带外观逐字节不变(stub_data):
    base = mr.render("测试大学", "202609", {})
    assert hashlib.sha256(base.encode("utf-8")).hexdigest() == _GOLDEN_RENDER_SHA, \
        "改造前后：不带 appearance 时输出必须逐字节一致"
    assert mr.render("测试大学", "202609", {}, appearance=None) == base
    # 注入机制完全惰性：不挂属性、不追加 CSS
    assert '<html lang="zh-CN">\n' in base
    assert f"<style>{mr._CSS}</style>" in base and base.count("<style>") == 1
    for marker in ("data-template", "data-skin-rpt", "data-font", "--rpt-"):
        assert marker not in base


def test_1b_generate_不带外观仍幂等(monkeypatch, tmp_path):
    """generate 幂等 / 原子写盘语义不受新增 appearance 形参影响（产物只落 tmp_path）。"""
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    monkeypatch.setattr(mr, "load_cache", lambda p: {"period": p})   # 真值 → 不触发建缓存
    monkeypatch.setattr(mr, "report_data", lambda *a, **k: _fixed_data())
    import monitor.insight as mi
    monkeypatch.setattr(mi, "insight", lambda *a, **k: None)          # 零 LLM
    p1 = mr.generate("测试大学", "202609")
    assert p1.exists() and "data-template" not in p1.read_text(encoding="utf-8")
    stamp = p1.read_bytes()
    p2 = mr.generate("测试大学", "202609")            # 幂等：不重写
    assert p2 == p1 and p1.read_bytes() == stamp


# ---------------------------------------------------------------- 2 五套模板
def test_2_五模板CSS各不同且数字同一份(stub_data):
    styles, bodies = {}, []
    for t in "ABCDE":
        h = mr.render("测试大学", "202609", {}, appearance={"template": t})
        styles[t] = h.split("<style>", 1)[1].split("</style>", 1)[0]
        assert f'data-template="{t}"' in h, "html 上要挂归一后的模板 id"
        assert '<div class="nv">12<small> / 22</small></div>' in h, "数字同一份"
        assert "data:image" not in h, "图表只许内联 svg"
        bodies.append(h.split("</style>", 1)[1])       # <style> 之后＝内容区
    assert len(set(styles.values())) == 5, "五个 template id 产出五套不同 CSS"
    assert len(set(bodies)) == 1, "版式只改 CSS，内容与数字区一字不动"


# ---------------------------------------------------------------- 3 十二套皮肤
def test_3_十二皮肤rpt变量注入正确(stub_data):
    for sid, s in ap.SKINS.items():
        css = ap.appearance_css({"skin_rpt": sid})
        assert f"--rpt-accent:{s['accent']}" in css
        assert f"--rpt-accent-2:{s['accent2']}" in css
        assert f"--rpt-tint:{s['tint']}" in css
        assert f"--rpt-paper:{s['paper']}" in css
        assert f"--rpt-ink:{s['ink']}" in css
        h = mr.render("测试大学", "202609", {}, appearance={"skin_rpt": sid})
        assert f'data-skin-rpt="{sid}"' in h
    # yebo 深色：纸墨反转 + 专用印色 / 金线
    y = ap.appearance_css({"skin_rpt": "yebo"})
    assert "--rpt-paper:#20262B" in y and "--rpt-ink:#ECE8DF" in y, "深纸浅字"
    assert "--rpt-seal:#C0503F" in y and "--rpt-gold:#C9A961" in y
    assert "@media print" in y and "yebo" in y, "yebo 打印反白规则在"
    # 普通皮用默认印色 / 金线；次要文字由 color-mix 派生
    n = ap.appearance_css({"skin_rpt": "huize"})
    assert "--rpt-seal:#8B1E1E" in n and "--rpt-gold:#B08E48" in n
    assert "color-mix(in srgb,var(--rpt-ink) 80%,var(--rpt-paper))" in n
    # 老变量被接到 --rpt-*（现网 _CSS 不改一行就跟着换纸墨）
    assert "--bg:var(--rpt-paper)" in n and "--ink:var(--rpt-ink)" in n


# ---------------------------------------------------------------- 4 六套字体
def test_4_六字体栈注入_隶行楷只进标题():
    for fid, f in ap.FONTS.items():
        css = ap.appearance_css({"font": fid})
        assert f"--rpt-f-body:{f['body']}" in css
        assert f"--rpt-f-title:{f['title']}" in css
        assert f"--rpt-fs-adj:{f['adj']}" in css
    base = ap.appearance_css({})
    for stack in ("--f-song:", "--f-hei:", "--f-kai:", "--f-fang:", "--f-li:", "--f-xing:"):
        assert stack in base, "六套基础字族栈都要在 :root 里"
    assert "KaiTi,\"Kaiti SC\",\"STKaiti\"" in base and "FangSong,\"STFangsong\"" in base
    # 正文规则吃 --rpt-f-body、标题规则吃 --rpt-f-title
    assert "html[data-font] body{font-family:var(--rpt-f-body)" in base
    assert "html[data-font] h1,html[data-font] h2{font-family:var(--rpt-f-title)}" in base
    # 隶：标题 LiSu、正文宋；行楷：标题 STXingkai、正文仿宋
    li = ap.appearance_css({"font": "li"})
    assert "--rpt-f-title:var(--f-li)" in li and "--rpt-f-body:var(--f-song)" in li
    assert "--f-li:LiSu,SimLi" in li
    xing = ap.appearance_css({"font": "xing"})
    assert "--rpt-f-title:var(--f-xing)" in xing and "--rpt-f-body:var(--f-fang)" in xing
    assert "STXingkai" in xing
    # 楷 / 仿宋 / 隶 / 行楷正文放大，宋 / 黑不放大
    assert "--rpt-fs-adj:.8px" in li and "--rpt-fs-adj:0px" in base


# ---------------------------------------------------------------- 5 非法值回落
def test_5_非法值回落缺省且接口不报错(stub_data):
    assert ap.normalize({"template": "Z", "skin_rpt": "不存在", "font": 42}) == \
        {"template": "B", "skin_rpt": "huize", "font": "song"}
    assert ap.normalize({}) == {"template": "B", "skin_rpt": "huize", "font": "song"}
    assert ap.normalize_value("template", None) == "B"
    assert ap.normalize_value("font", ["hei"]) == "song", "非字符串也回落"
    # 请求体抽取：只收三键、系统皮肤不认、未知回落、绝不抛异常
    assert ap.appearance_from_body(None) == {}
    assert ap.appearance_from_body({"skin_sys": "huize"}) == {}
    assert ap.appearance_from_body({"template": "Z", "font": "kai", "school": "X"}) == \
        {"template": "B", "font": "kai"}
    assert routes._appearance_prefs({"template": "Z", "skin_rpt": 9}) == \
        {"template": "B", "skin_rpt": "huize"}
    # 一堆非法值直接渲染也不报错，落到缺省基线（B + 会泽绿 + 宋）
    h = mr.render("测试大学", "202609", {},
                  appearance={"template": "Z", "skin_rpt": "?", "font": 42})
    assert 'data-template="B"' in h and 'data-skin-rpt="huize"' in h
    assert 'data-font="song"' in h and "--rpt-paper:#F5F3EC" in h


# ---------------------------------------------------------------- 6 任务口 params
def test_6_job_params只在带字段时加键(monkeypatch):
    created, found = [], []
    monkeypatch.setattr(routes.monitor_jobs, "find_running",
                        lambda kind, params: (found.append(dict(params)) or None))
    monkeypatch.setattr(routes.monitor_jobs, "create",
                        lambda kind, params, actor, **kw:
                        (created.append(dict(params)) or {"id": "x", "status": "running"}))
    monkeypatch.setattr(routes.monitor_jobs, "launch", lambda *a, **k: None)
    monkeypatch.setattr(routes.monitor_report, "latest_period", lambda: "202609")

    # 单校：不带外观 → params 形状与从前逐字一致（单飞 / 幂等断言盯着它）
    routes._report_job_create("清华大学", "tester")
    assert created[-1] == {"school": "清华大学", "period": "202609"}
    assert found[-1] == created[-1]
    # 带一个字段 → 只加那一个键
    routes._report_job_create("清华大学", "tester", force=True, prefs={"template": "A"})
    assert created[-1] == {"school": "清华大学", "period": "202609", "template": "A"}

    # 对比：不带外观 → 原形状；带字段 → 追加
    routes._compare_job_create(["清华大学", "云南大学"], "tester")
    assert created[-1] == {"schools": ["清华大学", "云南大学"], "period": "202609"}
    routes._compare_job_create(["清华大学", "云南大学"], "tester",
                               prefs={"font": "kai", "skin_rpt": "yebo"})
    assert created[-1] == {"schools": ["清华大学", "云南大学"], "period": "202609",
                           "font": "kai", "skin_rpt": "yebo"}
    assert found[-1] == created[-1], "find_running / create 拿同一份幂等键"


def test_6b_外观透传到generate_不带时不加kwarg(monkeypatch, tmp_path):
    got_r, got_c = [], []
    monkeypatch.setattr(routes.monitor_jobs, "find_running", lambda *a, **k: None)
    monkeypatch.setattr(routes.monitor_jobs, "create",
                        lambda kind, params, actor, **kw: {"id": "x", "status": "running"})
    # launch 立即执行 thunk（不落盘、不真生成）
    monkeypatch.setattr(routes.monitor_jobs, "launch", lambda job, thunk, **kw: thunk())
    monkeypatch.setattr(routes.monitor_report, "latest_period", lambda: "202609")
    monkeypatch.setattr(routes.monitor_report, "generate",
                        lambda cn, period, **kw: (got_r.append(dict(kw)) or tmp_path / "r.html"))
    monkeypatch.setattr(routes.monitor_compare, "generate",
                        lambda cns, period, **kw: (got_c.append(dict(kw)) or tmp_path / "c.html"))

    routes._report_job_create("清华大学", "tester", prefs={"template": "A"})
    assert got_r[-1] == {"force": False, "appearance": {"template": "A"}}
    routes._report_job_create("清华大学", "tester")
    assert got_r[-1] == {"force": False} and "appearance" not in got_r[-1]

    routes._compare_job_create(["清华大学", "云南大学"], "tester")
    assert got_c[-1] == {}, "不带外观：保持 generate(seen, period) 原调用形状"
    routes._compare_job_create(["清华大学", "云南大学"], "tester", prefs={"font": "kai"})
    assert got_c[-1] == {"appearance": {"font": "kai"}}


# ---------------------------------------------------------------- 7 Word 出口
def test_7_Word出口未被调用且未变(stub_data, monkeypatch):
    # 三个 Word 源文件逐字节未变
    for rel, sha in _WORD_FILES_SHA.items():
        p = _ROOT / rel
        assert p.exists(), f"Word 出口文件缺席：{rel}"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, f"Word 出口被改动：{rel}"
    # 外观模块不碰 docx
    assert "docx" not in (_ROOT / "src/monitor/appearance.py").read_text(
        encoding="utf-8").lower()
    # Tripwire：带外观渲染所有组合都不触发 Word 出口（否则 _boom 直接炸）
    def _boom(*a, **k):
        raise AssertionError("外观渲染不该碰 Word 出口")

    monkeypatch.setattr(mdx, "export", _boom)
    monkeypatch.setattr(mdx, "ensure", _boom)
    for t in "ABCDE":
        for sid in ("huize", "yebo"):
            for fid in ("song", "li", "xing"):
                h = mr.render("测试大学", "202609", {},
                              appearance={"template": t, "skin_rpt": sid, "font": fid})
                assert '<div class="nv">12' in h


def test_7b_对比件无外观字节一致():
    """compare.render 不带 appearance 时 <html>/<style> 与 mr._CSS 逐字保持。

    只读渲染一次真实缓存（不生成任何文件），与显式 appearance=None 对比。
    数据缺席时按登记簿规则跳过并留探针。
    """
    p = mr.latest_period()
    probe = lambda: bool(p) and mr.cache_path(p).exists()   # noqa: E731
    if not probe():
        skip_unless("监测版期次缓存未建（对比件只读校验缺席）", probe)
    cache = mr.load_cache(p)
    h = mc.render(["海南大学", "清华大学"], p, cache)
    assert '<html lang="zh-CN">\n' in h
    assert f"<style>{mr._CSS}\n.mwrap" in h
    assert "data-template" not in h and "--rpt-" not in h
    assert h == mc.render(["海南大学", "清华大学"], p, cache, appearance=None)


# ---------------------------------------------------------------- 8 生成幂等 vs 外观变更
@pytest.fixture
def gen_env(monkeypatch, tmp_path):
    """generate 的隔离环境：产物只落 tmp_path、零 LLM、report_data 固定、insight 计数。

    `calls` 每被调一次加一项——用来判定「有没有重出」（重出必重跑 insight）。
    """
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    monkeypatch.setattr(mr, "load_cache", lambda p: {"period": p})     # 真值 → 不触发建缓存
    monkeypatch.setattr(mr, "report_data", lambda *a, **k: _fixed_data())
    import monitor.insight as mi
    calls: list[int] = []
    monkeypatch.setattr(mi, "insight", lambda *a, **k: (calls.append(1) or None))
    return tmp_path, calls


def _sig(a: dict) -> str:
    return ap.signature(a)


def test_8b_签名与标记单元():
    """signature / head_meta / read_signature 的纯函数契约。"""
    assert ap.signature({"template": "A", "skin_rpt": "yebo", "font": "kai"}) == "A|yebo|kai"
    assert ap.signature({"template": "E"}) == "E|huize|song", "缺键归一补缺省"
    assert ap.signature({"template": "Z", "font": 42}) == "B|huize|song", "非法回落"
    assert ap.head_meta(None) == "", "不带外观：一个字都不加"
    m = ap.head_meta({"template": "A"})
    assert 'content="A|huize|song"' in m and "<meta" in m
    assert ap.read_signature("<head>\n" + m + "<title>x</title></head>") == "A|huize|song"
    assert ap.read_signature('<html><head></head><body>x</body></html>') is None, "legacy 无标记"
    assert ap.read_signature('<meta name="wenheng-appearance" content="B|huize|song">') == \
        "B|huize|song"


def test_8_同外观二次生成不重出(gen_env):
    """同外观 → 只读头部核对标记后直接返回旧件，不重跑 insight、不重写。"""
    _tmp, calls = gen_env
    a = {"template": "A", "skin_rpt": "huize", "font": "song"}
    p1 = mr.generate("测试大学", "202609", appearance=a)
    n1 = len(calls)
    body = p1.read_bytes()
    p2 = mr.generate("测试大学", "202609", appearance=a)
    assert p2 == p1
    assert len(calls) == n1, "同外观幂等：模型不再调"
    assert p2.read_bytes() == body, "同外观幂等：文件不重写"
    assert f'content="{_sig(a)}"' in p2.read_text(encoding="utf-8")
    assert ap.read_signature_from_file(p2) == _sig(a)


@pytest.mark.parametrize("key,val", [("template", "E"), ("skin_rpt", "yebo"),
                                     ("font", "xing")])
def test_8_换外观不带force也重出(gen_env, key, val):
    """三轴任一变了 → 不带 force 也覆盖重出，且新文件标记是新签名。"""
    _tmp, calls = gen_env
    a1 = {"template": "A", "skin_rpt": "huize", "font": "song"}
    p1 = mr.generate("测试大学", "202609", appearance=a1)
    n1 = len(calls)
    a2 = dict(a1)
    a2[key] = val
    p2 = mr.generate("测试大学", "202609", appearance=a2)   # 刻意不传 force
    assert p2 == p1
    assert len(calls) == n1 + 1, f"换 {key} 要重出（重跑 insight）"
    txt = p2.read_text(encoding="utf-8")
    assert f'content="{_sig(a2)}"' in txt, "标记已更新为本次签名"
    assert f'content="{_sig(a1)}"' not in txt, "旧签名不留痕"
    assert ap.read_signature_from_file(p2) == _sig(a2)


def test_8_legacy无标记件重出(gen_env):
    """旧件没有标记（legacy 产物）＋带外观请求 → 重出并补上标记。"""
    tmp, calls = gen_env
    out = tmp / "测试大学" / "202609.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    legacy = mr.render("测试大学", "202609", {})             # 不带外观、无标记
    assert "wenheng-appearance" not in legacy
    out.write_text(legacy, encoding="utf-8")
    n0 = len(calls)
    a = {"template": "C", "skin_rpt": "yebo", "font": "kai"}
    p = mr.generate("测试大学", "202609", appearance=a)
    assert p == out
    assert len(calls) == n0 + 1, "legacy 缺标记 → 重出"
    assert f'content="{_sig(a)}"' in p.read_text(encoding="utf-8")


def test_8_appearance为None旧行为逐字不变(gen_env):
    """不带 appearance：文件在就返回，连读都不读；golden 字节不变、不加标记、不调模型。"""
    tmp, calls = gen_env
    out = tmp / "测试大学" / "202609.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    legacy = mr.render("测试大学", "202609", {})
    assert hashlib.sha256(legacy.encode("utf-8")).hexdigest() == _GOLDEN_RENDER_SHA
    out.write_text(legacy, encoding="utf-8")
    n0 = len(calls)
    p = mr.generate("测试大学", "202609")                    # 不带 appearance
    assert p == out
    assert len(calls) == n0, "旧行为：不重出、不调模型"
    assert p.read_text(encoding="utf-8") == legacy, "旧件逐字不动"
    assert "wenheng-appearance" not in p.read_text(encoding="utf-8")


def test_8_force仍覆盖(gen_env):
    """force=True：即便同外观也跳过幂等早退，照旧覆盖重出。"""
    _tmp, calls = gen_env
    a = {"template": "A", "skin_rpt": "huize", "font": "song"}
    p1 = mr.generate("测试大学", "202609", appearance=a)
    n1 = len(calls)
    p2 = mr.generate("测试大学", "202609", appearance=a, force=True)
    assert p2 == p1
    assert len(calls) == n1 + 1, "force 覆盖重出（重跑 insight）"
    assert f'content="{_sig(a)}"' in p2.read_text(encoding="utf-8")


def test_8c_compare_generate外观变则重出(monkeypatch, tmp_path):
    """对比件同样有幂等早退，按同一套签名逻辑补：同外观幂等、换皮肤重出。"""
    import monitor.insight as mi
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    monkeypatch.setattr(mr, "load_cache", lambda p: {"period": p})
    monkeypatch.setattr(mi, "compose_text", lambda *a, **k: None)

    def fake_render(*a, **k):
        return ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
                + mr.head_meta(k.get("appearance"))
                + "</head>\n<body>对比件</body>\n</html>\n")
    monkeypatch.setattr(mc, "render", fake_render)

    a1 = {"template": "A", "skin_rpt": "huize", "font": "song"}
    p1 = mc.generate(["清华大学", "云南大学"], "202609", appearance=a1)
    assert f'content="{_sig(a1)}"' in p1.read_text(encoding="utf-8")
    body = p1.read_bytes()
    p2 = mc.generate(["清华大学", "云南大学"], "202609", appearance=a1)
    assert p2 == p1 and p2.read_bytes() == body, "同外观幂等：不重写"
    a2 = {"template": "A", "skin_rpt": "yebo", "font": "song"}
    p3 = mc.generate(["清华大学", "云南大学"], "202609", appearance=a2)
    assert f'content="{_sig(a2)}"' in p3.read_text(encoding="utf-8")
