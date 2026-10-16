# -*- coding: utf-8 -*-
"""取数状态（src/acquisition_state.py）：逐文件核验 + 状态组装。

合成一套最小两路下载包跑全量分组；另用真实 202609 包做一次带护栏的回归。
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import acquisition_state as A  # noqa: E402

from _guard_registry import skip_unless  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


def _xlsx(path: pathlib.Path, rows: list, sheet: str = "Sheet0") -> None:
    wb = openpyxl.Workbook()
    ws = wb.worksheets[0]
    ws.title = sheet
    for r in rows:
        ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _subject_rows(tag: str, name: str, n: int = 12) -> list:
    rows = [[f"Indicators Results List: Institutions   Filter Results By: ResearchFields   "
             f"Filter Value(s): {name.upper()}   Show: Top"]]
    rows.append(["RowSeq", "Institutions", "Web of Science Documents", "Cites"])
    rows.extend([[i, f"Univ {i}", 100 + i, 200 + i] for i in range(n)])
    return rows


def _build_esi(root: pathlib.Path, period: str) -> None:
    d = root / period
    _xlsx(d / "Institutions.xlsx", [["Institutions", "Cites"]] + [[f"U{i}", i] for i in range(150)])
    for s in A.SUBJECTS:
        _xlsx(d / f"{s.replace('/', ' ')}.xlsx", _subject_rows("subjects", s))
    for f in ("全球学科.xlsx", "中国学科.xlsx", "云大学科.xlsx"):
        _xlsx(d / f, [["Research Fields", "Cites"]] + [[f"F{i}", i] for i in range(25)])
    for suffix in ("top", "highly cited", "hot papers"):
        _xlsx(d / f"7{suffix}.xlsx", [["Documents Result List: Institutions"]] +
              [["Accession Number", "Article Name"]] + [["WOS:x", "文"]] * 3)
        (d / f"7{suffix}.csv").write_text(
            "Documents Result List:  Institutions - 'YUNNAN UNIVERSITY' Show - Top Papers\n"
            "Accession Number,DOI,Article Name\n\"WOS:x\",\"10.1\",\"文\"\n", encoding="utf-8-sig")
    for f in ("ThresholdESI.xlsx", "ThresholdHighlyCited.xlsx", "ThresholdHot.xlsx"):
        _xlsx(d / f, [["Threshold", "Cites"]] + [[f"T{i}", i] for i in range(25)])
    for f in ("BaselineCitationRates.xlsx", "BaselinePercentiles.xlsx", "BaselineFieldRankings.xlsx"):
        _xlsx(d / f, [["Baseline", "Value"]] + [[f"B{i}", i] for i in range(25)])


def _build_incites(root: pathlib.Path, snap: str) -> None:
    d = root / snap
    for s in A.SUBJECTS:
        name = "Social Sciences, general" if s == "Social Sciences, General" else s
        _xlsx(d / f"{name.replace('/', ' ')}.xlsx",
              [["名称", "Web of Science 论文数", "被引频次"]] + [[f"U{i}", i, i * 2] for i in range(12)])
    _xlsx(d / "全球 研究领域.xlsx", [["名称", "Web of Science 论文数"]] + [["F", 1]] * 25)
    _xlsx(d / "中国研究领域.xlsx", [["名称", "Web of Science 论文数"]] + [["F", 1]] * 25)
    _xlsx(d / "云南大学研究领域.xlsx", [["名称", "Web of Science 论文数"]] + [["F", 1]] * 25)
    _xlsx(d / "全球机构排名.xlsx", [["名称", "Web of Science 论文数"]] +
          [[f"U{i}", i] for i in range(1001)])


@pytest.fixture()
def fake_roots(tmp_path, monkeypatch):
    esi = tmp_path / "ESI数据"
    inc = tmp_path / "incites"
    snap = "数据覆盖2016-2026.06.30"
    _build_esi(esi, "202609")
    _build_incites(inc, snap)
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    return esi, inc, snap


def test_scan_all_groups_green(fake_roots):
    esi, inc, snap = fake_roots
    state = A.scan("202609", esi_root=esi, snapshot=snap)
    assert state["totals"] == {"groups": 9, "expected": 64, "verified": 64,
                               "downloaded": 64, "failed": 0}
    assert all(g["state"] == "done" for g in state["groups"])
    assert state["data_period"]["incites"] == "2026-06-30"


def test_scan_marks_bad_file_and_fails_group(fake_roots):
    esi, inc, snap = fake_roots
    bad = esi / "202609" / "Chemistry.xlsx"
    bad.write_bytes(b"this is not xlsx")
    state = A.scan("202609", esi_root=esi, snapshot=snap)
    subj = next(g for g in state["groups"] if g["id"] == "esi-subjects")
    chem = next(f for f in subj["files"] if f["name"] == "Chemistry.xlsx")
    assert chem["state"] == "bad" and "打不开" in chem["note"]
    assert subj["state"] == "fail"
    assert state["totals"]["verified"] == 63 and state["totals"]["failed"] == 1


def test_scan_pending_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    state = A.scan("202609", esi_root=tmp_path / "none-esi", snapshot="")
    assert state["totals"]["verified"] == 0
    assert all(g["state"] == "pending" for g in state["groups"])


def test_unmapped_period_does_not_borrow_latest_snapshot(tmp_path, monkeypatch):
    """scan 收紧（2026-10-16）：未登记 SNAP_MAP 的期次不得借用「最新一个」InCites 快照。

    旧行为会把最新快照里的 22 学科文件算成新期次的（实测未取数的 202611 凭空 26/64）。
    """
    inc = tmp_path / "incites"
    _build_incites(inc, "数据覆盖2016-2026.06.30")            # 最新快照里有一整套文件
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    monkeypatch.setattr(A, "INCITES_ROOT_DEFAULT", inc)
    monkeypatch.setattr(A, "_snap_map", lambda: {"202609": "数据覆盖2016-2026.06.30"})
    state = A.scan("202611", esi_root=tmp_path / "none-esi")
    assert state["snapshot"] == "" and state["snapshot_registered"] is False
    assert state["data_period"]["incites"] == ""
    inc_g = next(g for g in state["groups"] if g["id"] == "incites-subjects")
    assert inc_g["state"] == "pending" and inc_g["verified"] == 0
    assert state["totals"]["verified"] == 0                   # 一个文件都不该算进来


def test_resolve_snapshot_explicit_and_mapped(monkeypatch):
    monkeypatch.setattr(A, "_snap_map", lambda: {"202609": "数据覆盖2016-2026.06.30"})
    assert A.resolve_snapshot("202609", A.INCITES_ROOT_DEFAULT) == "数据覆盖2016-2026.06.30"
    assert A.resolve_snapshot("202605", A.INCITES_ROOT_DEFAULT, "显式快照") == "显式快照"
    assert A.resolve_snapshot("202611", A.INCITES_ROOT_DEFAULT) == ""   # 未登记 → 空


def test_write_load_roundtrip_and_preserve(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    A.write_state("202609", {"totals": {"verified": 1}, "preflight": {"browser": "ok"}})
    got = A.load_state("202609")
    assert got["period"] == "202609" and got["preflight"]["browser"] == "ok"
    assert got["updated_at"]
    # 再扫一次要保留 preflight / copy（不重建时抹掉人工/流程写过的字段）
    state = A.scan("202609", esi_root=tmp_path / "none", snapshot="")
    A.write_state("202609", state)
    assert A.load_state("202609")["preflight"]["browser"] == "ok"


def test_snapshot_resolution_and_date():
    assert A._snap_date("数据覆盖2016-2026.06.30") == "2026-06-30"
    assert A._snap_date("") == ""
    assert A._period_esi_label("202609") == "2026 年 9 月"


def test_scan_real_202609():
    """真实包回归（缺件才登记跳过：探针说资源在、却跳过 = 会话收尾判失败）。"""
    period = "202609"
    esi = A.ESI_ROOT_DEFAULT / period
    if not esi.is_dir():
        skip_unless(f"真实 ESI 包不存在：{esi}", lambda: esi.is_dir())
    state = A.scan(period)
    assert state["totals"]["verified"] >= 60, state["totals"]
    assert state["totals"]["failed"] == 0
