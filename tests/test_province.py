# -*- coding: utf-8 -*-
"""省域对比表 T19 的复现口径（2026-09-20）。

这张表历期都是馆员**手工填**的（母版里整表空白）。查证后确认数据源是
**ESI 原始包的机构总表**（不是台账 —— 台账《高校学科发展》是另一个口径，
昆工发文量 19259 vs 机构总表 31045，对不上）。

本组测试钉的是"口径别漂"：
  ① 11 校名单与人工原件**逐字同序**（这是业务口径，不来自任何数据源）；
  ② 算出来的 99 格与人工原件**逐格一致** ← 最重要，口径错一格就说明假设崩了；
  ③ 22 个学科榜文件名白名单（按 `DISCIPLINES_EN` 拼只会命中 20 个，
     导致「ESI前1%学科数」每校统一少 1 —— 实测踩到过）；
  ④ 每格都带溯源（可指回 ESI 文件与行号）。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO / "src"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import extract_province as ep                                   # noqa: E402
from _guard_registry import skip_unless                         # noqa: E402

ESI = REPO.parent / "数据与复现" / "ESI数据" / "202607"
ORIG = REPO.parent / "云南大学原报告" / "云南大学学科信息参考2026年第4期.docx"


def _need_esi():
    if not (ESI / "institutions.xlsx").exists():
        skip_unless("缺 ESI 原始包（数据与复现/ESI数据/202607）",
                    lambda: (ESI / "institutions.xlsx").exists())


def _need_orig():
    if not ORIG.exists():
        skip_unless("缺人工原件（云南大学原报告/2026年第4期）", lambda: ORIG.exists())


# ============================================================ ① 名单
def test_11校名单与人工原件同序():
    """名单是业务口径（报告固定列这 11 所），必须与原件逐字同序。"""
    _need_orig()
    from docx import Document
    d = Document(str(ORIG))
    t19 = next(t for t in d.tables if (len(t.rows), len(t.columns)) == (13, 10))
    orig = [r.cells[0].text.strip() for r in t19.rows[2:] if r.cells[0].text.strip()]
    assert [cn for cn, _ in ep.UNIVERSITIES] == orig


def test_别把非高校机构算进来():
    """机构总表里还有中科院昆明植物所/动物所、云南省农科院，名字同样带 YUNNAN/KUNMING。"""
    en = " ".join(e for _, e in ep.UNIVERSITIES)
    assert "INSTITUTE" not in en and "ACADEMY" not in en


# ============================================================ ② 逐格一致（核心）
def test_与人工原件逐格一致():
    _need_esi()
    _need_orig()
    data = ep.compute(ESI.parent, "202607")
    ok, total, diffs = ep.compare_with_original(data, ORIG, "202607")
    assert total == 99, f"应比 99 格（11 校 × 9 列），实为 {total}"
    assert ok == total, f"与原件不一致：{diffs[:5]}"


# ============================================================ ③ 学科榜白名单
def test_学科榜白名单是22个():
    assert len(ep.DISC_FILES) == 22


def test_学科榜文件名与实际文件对得上():
    """按规范名拼会漏 3 个（斜杠/大小写差异）→ 每校「ESI前1%学科数」少 1。"""
    _need_esi()
    got = ep._disc_workbooks(ESI)
    missing = [x for x in ep.DISC_FILES if x not in got]
    assert not missing, f"这些学科榜没找到：{missing}"


# ============================================================ ④ 溯源
def test_每格都带溯源():
    _need_esi()
    data = ep.compute(ESI.parent, "202607")
    bad = [(cn, col) for cn, rec in data["universities"].items()
           for col, item in rec.items() if not (item or {}).get("src")]
    assert not bad, f"这些格缺溯源：{bad[:5]}"


def test_工作台与fill_docx的省域列名一致():
    """两处各写一份列名表 → 漂移了就是静默失效：工作台把 T19/r5c3 翻成错的列名，
    或者 fill_docx 按错的列序填表。"""
    from server import workbench
    import fill_docx
    assert workbench.PROVINCE_COLS == fill_docx.PROVINCE_COLS


def test_溯源指向ESI原始包():
    _need_esi()
    data = ep.compute(ESI.parent, "202607")
    src = data["universities"]["云南大学"]["发文量"]["src"]
    assert "institutions.xlsx" in src and "ESI数据" in src


# ============================================================ ⑤ 列序会变（按表头读）
HDR_15 = ["", "Institutions", "Countries/Regions", "Web of Science Documents", "Cites",
          "Cites/Paper", "Top Papers", "Cites to Top Papers", "Cites/Top Paper",
          "Highly Cited Papers", "Cites to Highly Cited Papers", "Cites/Highly Cited Paper",
          "Hot Papers", "Cites to Hot Papers", "Cites/Hot Paper"]
ROW_15 = [1, "YUNNAN UNIVERSITY", "CHINA MAINLAND", 21720, 327007, 15.06, 291,
          41979, 144.26, 290, 41979, 144.75, 13, 1000, 76.9]
HDR_9 = ["", "Institutions", "Countries/Regions", "Web of Science Documents", "Cites",
         "Cites/Paper", "Top Papers", "Highly Cited Papers", "Hot Papers"]
ROW_9 = [1, "YUNNAN UNIVERSITY", "CHINA MAINLAND", 21009, 309949, 14.75, 274, 272, 11]
HDR_7 = ["", "Institutions", "Countries/Regions", "Web of Science Documents", "Cites",
         "Cites/Paper", "Top Papers"]
ROW_7 = [1, "YUNNAN UNIVERSITY", "CHINA MAINLAND", 19596, 273732, 13.97, 245]


def _make_inst(tmp_path, period, hdr, row):
    import openpyxl
    d = pathlib.Path(tmp_path) / period
    d.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet0"
    ws.cell(5, 1, "Indicators Results")
    for j, h in enumerate(hdr, 1):
        ws.cell(6, j, h)
    for j, v in enumerate(row, 1):
        ws.cell(7, j, v)
    wb.save(d / "Institutions.xlsx")


def test_十五列新导出按表头读高被引与热点(tmp_path):
    """🔴 2026-09-24 rick 问「热点论文为什么不填写」的真因：202609 起机构总表默认
    15 列（三组各带 Cites to / Cites per），`Hot Papers` 从第 9 列挪到第 13 列。
    按固定下标读 → 高被引被填成 `Cites to Top Papers`（41979）、热点读空。
    本测试用同构合成表钉住「按表头找列」。"""
    _make_inst(tmp_path, "202609", HDR_15, ROW_15)
    rec = ep.compute(tmp_path, "202609")["universities"]["云南大学"]
    assert rec["高被引论文"]["v"] == 290, "读到 Cites to Top Papers 了（=41979）"
    assert rec["热点论文"]["v"] == 13, "热点论文被读成空"
    assert rec["顶尖论文"]["v"] == 291 and rec["被引频次"]["v"] == 327007


def test_旧九列版式仍读对(tmp_path):
    """202607 那版 9 列：高被引第 8 列、热点第 9 列 —— 不能被新逻辑读错。"""
    _make_inst(tmp_path, "202607", HDR_9, ROW_9)
    rec = ep.compute(tmp_path, "202607")["universities"]["云南大学"]
    assert rec["高被引论文"]["v"] == 272 and rec["热点论文"]["v"] == 11


def test_七列老版式两列留空(tmp_path):
    """202601/202605 版源端就没有这两列 → None（填表时留空，不是漏填）。"""
    _make_inst(tmp_path, "202601", HDR_7, ROW_7)
    rec = ep.compute(tmp_path, "202601")["universities"]["云南大学"]
    assert rec["高被引论文"]["v"] is None and rec["热点论文"]["v"] is None
    assert rec["顶尖论文"]["v"] == 245


def test_表头认不出必需列时拒绝出数(tmp_path):
    """宁可拒绝，不许带病出表：缺 Top Papers 的表头直接拦停。"""
    _make_inst(tmp_path, "209901", HDR_7[:6], ROW_7[:6])
    try:
        ep.compute(tmp_path, "209901")
    except SystemExit as e:
        assert "认不出" in str(e)
    else:
        raise AssertionError("表头缺列时应该拒绝")
