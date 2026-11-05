# -*- coding: utf-8 -*-
"""架构深化施工单（20261101）M1 工位新增测试：C1 解析收敛 + C7 交接账（模块侧）。

C1：build_cache 整体委托 trend 解析器且缓存形态不变、fields/thr1 与趋势库同源、
    cn_rank 宽口径两侧同值、22 学科中文名唯一来源、norm 单处实现。
C7：generate 幂等（产物已存在不触发 insight，LLM 不重复调）、docx.export 先查件再装配、
    docx.ensure 规则、doctor D7 趋势库在册。

打桩一律在 tmp_path / monkeypatch 上做，不触碰 monitor_data 的演示产物。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from _guard_registry import skip_unless            # noqa: E402
from monitor import compare as mcmp                # noqa: E402
from monitor import doctor as mdoc                 # noqa: E402
from monitor import insight as mi                  # noqa: E402
from monitor import report as mr                   # noqa: E402
from monitor import trend as mt                    # noqa: E402

_PERIOD = mr.latest_period()
_cache_probe = lambda: bool(_PERIOD) and mr.cache_path(_PERIOD).exists()   # noqa: E731


# ---------------------------------------------------------------- C1 解析收敛

def test_c1_build_cache_delegates_to_trend(monkeypatch, tmp_path: pathlib.Path):
    """build_cache 整体委托 trend.extract_period_full（打桩确认调用），缓存写入形态不变，
    fields/thr1 与趋势库件逐值同源，cn_rank 宽口径（海大化学 123）。"""
    src_probe = lambda: (mr.ESI_ROOT / "202609" / "Institutions.xlsx").exists()   # noqa: E731
    if not src_probe():
        skip_unless("监测版源数据缺席（数据与复现/ESI数据/202609）", src_probe)
    calls: list[str] = []
    real = mt.extract_period_full

    def spy(period):
        calls.append(period)
        return real(period)

    monkeypatch.setattr(mt, "extract_period_full", spy)
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)          # 落盘指到 tmp，不动真缓存
    cache = mr.build_cache("202609")
    assert calls == ["202609"], "解析必须整体委托 trend"
    assert set(cache) == {"period", "built", "download", "n_inst", "fields", "thr1",
                          "global_papers", "cn_inst", "neighbors"}, "缓存写入形态不变"
    tfile = mt.TREND_ROOT / "202609.json"
    if not tfile.exists():
        skip_unless("趋势库 202609 件缺席", lambda: tfile.exists())
    t = json.loads(tfile.read_text(encoding="utf-8"))
    assert cache["fields"] == t["fields"], "fields 与趋势库件逐值同源（宽口径随之同值）"
    assert cache["thr1"] == t["thr1"]
    assert cache["n_inst"] == t["n_inst"] == 10674
    assert cache["fields"]["Chemistry"]["schools"]["HAINAN UNIVERSITY"][1] == 123, \
        "cn_rank＝CM∪N/A 宽口径（与 trend 同口径）"
    assert cache["cn_inst"], "省内关键词子集不得为空"
    assert cache["neighbors"]["HAINAN UNIVERSITY"], "±3 邻近窗不得为空"


def test_c1_build_cache_missing_dir_raises(monkeypatch, tmp_path: pathlib.Path):
    """期次目录缺失 → FileNotFoundError（保持服务端 404 语义），不落残缓存。"""
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    try:
        mr.build_cache("190001")
        raised = None
    except FileNotFoundError as exc:
        raised = exc
    assert raised is not None and "190001" in str(raised)
    assert not (tmp_path / "_cache_190001.json").exists(), "坏期次不得落缓存"


def test_c1_cn_table_from_ledger():
    """22 学科中文名唯一来源＝parse_ledger.DISCIPLINES_CN（按 STEM 键重排）——22 条逐字钉死。"""
    expected = {"Agricultural Sciences": "农业科学", "Biology & Biochemistry": "生物学与生物化学",
                "Chemistry": "化学", "Clinical Medicine": "临床医学", "Computer Science": "计算机科学",
                "Economics & Business": "经济与商业", "Engineering": "工程学",
                "Environment Ecology": "环境生态学", "Geosciences": "地球科学", "Immunology": "免疫学",
                "Materials Science": "材料科学", "Mathematics": "数学", "Microbiology": "微生物学",
                "Molecular Biology & Genetics": "分子生物学与遗传学", "Multidisciplinary": "多学科",
                "Neuroscience & Behavior": "神经系统科学与行为学",
                "Pharmacology & Toxicology": "药理学与毒理学", "Physics": "物理学",
                "Plant & Animal Science": "植物与动物学", "Psychiatry Psychology": "精神病学与心理学",
                "Social Sciences, General": "社会科学", "Space Science": "空间科学"}
    assert mr.CN == expected and len(mr.CN) == 22
    assert mi.cn_name("Chemistry") == "化学"
    assert mi.cn_name("不在表中") == "不在表中", "名单外原样返回（insight.cn_name 语义不变）"


def test_c1_norm_single_source():
    """norm 归一收敛为 report.norm 单处实现（None 兜底＝表头空单元格语义）。"""
    assert mr.norm(" Environment/Ecology ") == "ENVIRONMENT ECOLOGY"
    assert mr.norm("Social Sciences, General") == "SOCIAL SCIENCES, GENERAL"
    assert mr.norm(None) == "", "None → 空串（trend._cols 喂 None 表头不炸）"


# ---------------------------------------------------------------- C7 交接账（模块侧）

def test_c7_report_generate_idempotent(monkeypatch, tmp_path: pathlib.Path):
    """同校同期产物已存在 → generate 直接返回该路径，不再触发 insight（LLM 不重复调）。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    monkeypatch.setattr(mr, "load_cache", lambda p: cache)
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    calls: list[str] = []

    def fake_insight(cn, period, c):
        calls.append(cn)
        return {"text": "打桩解读。", "mode": "rule"}

    monkeypatch.setattr(mi, "insight", fake_insight)
    p1 = mr.generate("海南大学", _PERIOD)
    assert p1 == tmp_path / "海南大学" / f"{_PERIOD}.html" and p1.exists()
    assert calls == ["海南大学"], "首次生成恰好触发一次 insight"
    stamp = p1.read_text(encoding="utf-8")
    p2 = mr.generate("海南大学", _PERIOD)
    assert p2 == p1 and p1.read_text(encoding="utf-8") == stamp, "重入不重写"
    assert len(calls) == 1, "第二次生成不得再触发 insight"


def test_c7_重新生成必须真的重出_force(monkeypatch, tmp_path: pathlib.Path):
    """2026-11-05 修：旧件是规则兜底时，幂等让「重新生成」空跑 → AI 解读永远出不来。

    `force=True` 覆盖重出、重跑 insight；不传照旧幂等（模型不重复调）。
    """
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    monkeypatch.setattr(mr, "load_cache", lambda p: cache)
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    calls: list[str] = []
    mode = {"now": "rule"}

    def fake_insight(cn, period, c):
        calls.append(cn)
        return {"text": "打桩解读。", "mode": mode["now"]}

    monkeypatch.setattr(mi, "insight", fake_insight)
    p1 = mr.generate("海南大学", _PERIOD)
    assert "规则拼装" in p1.read_text(encoding="utf-8")
    mode["now"] = "model"                       # 模型修好了
    p2 = mr.generate("海南大学", _PERIOD)
    assert p2 == p1 and "规则拼装" in p2.read_text(encoding="utf-8"), "不传 force＝幂等"
    assert len(calls) == 1
    p3 = mr.generate("海南大学", _PERIOD, force=True)
    assert len(calls) == 2, "force 要重跑 insight"
    assert p3 == p1 and "模型解读" in p3.read_text(encoding="utf-8"), "旧件被覆盖成模型解读"


def test_c7_compare_generate_idempotent(monkeypatch, tmp_path: pathlib.Path):
    """对比件同校集合同期已存在 → 直接返回，不重跑 insight（compose_text 打桩计数）。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    monkeypatch.setattr(mr, "load_cache", lambda p: cache)
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    calls: list[str] = []

    def fake_compose(topic, facts, safe, *, label, veto=None):
        calls.append(label)
        return {"text": safe, "mode": "rule"}

    monkeypatch.setattr(mi, "compose_text", fake_compose)
    p1 = mcmp.generate(["海南大学", "清华大学"], _PERIOD)
    p2 = mcmp.generate(["清华大学", "海南大学"], _PERIOD)
    assert p1 == p2 and p1.exists()
    assert len(calls) == 1, "重入只复用已存在件，不再调解读"


def test_c7_docx_export_checks_existence_first(monkeypatch, tmp_path: pathlib.Path):
    """export 存在性检查在装配之前——命中时 report_data（含 trend.combine 全库扫描）不执行。"""
    from monitor import docx as mdx
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    out = tmp_path / "海南大学" / f"{_PERIOD}.docx"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"stale")                                  # 预置旧件

    def boom(*a, **k):
        raise AssertionError("已存在时不得进入装配（trend.combine 全库扫描不该付费）")

    monkeypatch.setattr(mr, "report_data", boom)
    p = mdx.export("海南大学", _PERIOD, {})
    assert p == out and p.read_bytes() == b"stale", "命中直接返回，旧件不被重写"


def test_c7_docx_ensure_rules(monkeypatch, tmp_path: pathlib.Path):
    """ensure：当期缺失 → 现算导出；已存在 → 直接返回；老期次 / 名单外 → None 不补。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    from monitor import docx as mdx
    cache = mr.load_cache(_PERIOD)
    monkeypatch.setattr(mr, "load_cache", lambda p: cache)
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)
    assert mdx.ensure("不存在大学", _PERIOD) is None, "名单外不补"
    assert mdx.ensure("海南大学", "190001") is None, "老期次缺失不补（docx 只随当期生成）"
    assert not (tmp_path / "海南大学" / "190001.docx").exists()
    p = mdx.ensure("海南大学", _PERIOD)
    assert p == tmp_path / "海南大学" / f"{_PERIOD}.docx" and p.exists(), "当期缺失现算导出"
    mtime = p.stat().st_mtime
    assert mdx.ensure("海南大学", _PERIOD) == p and p.stat().st_mtime == mtime, "已存在直接返回"


def test_c7_doctor_d7_trend_register(monkeypatch, tmp_path: pathlib.Path):
    """D7 趋势库在册：索引缺 / 当期件缺 / 索引判 bad / 在册件缺盘 逐件点名；齐备 → ok。"""
    troot = tmp_path / "_trend"
    monkeypatch.setattr(mr, "MONITOR_ROOT", tmp_path)

    def write_index(periods: dict):
        troot.mkdir(exist_ok=True)
        (troot / "_index.json").write_text(
            json.dumps({"built_at": "2026-11-01T00:00:00", "periods": periods}),
            encoding="utf-8")

    ok, detail = mdoc._trend_in_register("202609")
    assert not ok and "_index.json" in detail and "src.monitor.trend" in detail, "索引缺失指修复口令"
    write_index({"202609": {"status": "ok"}})
    ok, detail = mdoc._trend_in_register("202609")
    assert not ok and "202609.json" in detail, "当期件缺失 → 点名缺哪件"
    (troot / "202609.json").write_text("{}", encoding="utf-8")
    ok, detail = mdoc._trend_in_register("202609")
    assert ok, "当期件在且索引 ok → 通过"
    write_index({"202609": {"status": "bad", "reason": "D6"}})
    ok, detail = mdoc._trend_in_register("202609")
    assert not ok and "bad" in detail and "D6" in detail, "索引判 bad → fail 带理由"
    write_index({"202609": {"status": "ok"}, "202001": {"status": "ok"}})
    ok, detail = mdoc._trend_in_register("202609")
    assert not ok and "202001" in detail, "在册件缺盘 → 逐件点名"


def test_c7_doctor_d7_in_check_output():
    """doctor.check 的 items 含 D7，且真库当期在册（D7 与 D1/D2/D3/D6 一同进报告）。"""
    if not _PERIOD or not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    rep = mdoc.check(_PERIOD)
    ids = [i["id"] for i in rep["items"]]
    assert ids == ["D1", "D2", "D3", "D7", "D6"], "D7 落位 D3 之后、D6 之前"
    d7 = next(i for i in rep["items"] if i["id"] == "D7")
    assert d7["ok"], f"真库当期应在册：{d7['detail']}"
