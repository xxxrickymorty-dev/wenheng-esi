# -*- coding: utf-8 -*-
"""并入守卫（src/ledger_merge.py）：期次归因 + 写后五查。

合成小型「台账」（一张链路 sheet），对五种场景逐一断言：
干净并入过；改旧格 / 新增不归期 / 审写不一致 / 少格 → 各自被点名。
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import ledger_merge as LM  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


def _wb(path: pathlib.Path, rows: list, sheet: str = "总被引") -> None:
    wb = openpyxl.Workbook()
    ws = wb.worksheets[0]
    ws.title = sheet
    for r in rows:
        ws.append(r)
    wb.save(path)


def _base_rows():
    header = ["学科", "202603", "202607"]
    return [header] + [[f"学科{i}", 100 + i, 200 + i] for i in range(5)]


def _add_period_rows(rows, values=None):
    out = [list(r) for r in rows]
    out[0] = out[0] + ["202609"]
    for i in range(5):
        out[i + 1] = out[i + 1] + [(values or [300, 301, 302, 303, 304])[i]]
    return out


@pytest.fixture()
def files(tmp_path):
    master = tmp_path / "master.xlsx"
    copy = tmp_path / "copy.xlsx"
    _wb(master, _base_rows())
    _wb(copy, _add_period_rows(_base_rows()))
    return master, copy


def test_clean_merge_passes(files, tmp_path):
    master, copy = files
    after = tmp_path / "after.xlsx"
    after.write_bytes(copy.read_bytes())
    res = LM.write_after_checks(master, after, copy, "202609")
    assert res["ok"] is True, res["reasons"]
    assert res["added_cells"] == 6          # 期次表头 1 格 + 数据 5 格


def test_old_cell_modified_is_flagged(files, tmp_path):
    master, copy = files
    after = tmp_path / "after.xlsx"
    rows = _add_period_rows(_base_rows())
    rows[2][1] = 999                       # 改 202603 的旧格
    _wb(after, rows)
    res = LM.write_after_checks(master, after, copy, "202609")
    assert res["ok"] is False
    assert any("非当期旧格被改" in r for r in res["reasons"]), res["reasons"]


def test_unattributed_add_is_flagged(files, tmp_path):
    master, copy = files
    after = tmp_path / "after.xlsx"
    rows = _add_period_rows(_base_rows())
    rows[0] = rows[0] + ["备注"]           # 新增列没有期次号
    for i in range(5):
        rows[i + 1] = rows[i + 1] + [1]
    _wb(after, rows)
    res = LM.write_after_checks(master, after, copy, "202609")
    assert res["ok"] is False
    assert any("不在当期列/行" in r for r in res["reasons"]), res["reasons"]


def test_copy_master_mismatch_is_flagged(files, tmp_path):
    master, copy = files
    after = tmp_path / "after.xlsx"
    _wb(after, _add_period_rows(_base_rows(), values=[300, 301, 302, 303, 999]))
    res = LM.write_after_checks(master, after, copy, "202609")
    assert res["ok"] is False
    assert any("审写不一致" in r for r in res["reasons"]), res["reasons"]


def test_removed_cell_is_flagged(files, tmp_path):
    master, copy = files
    after = tmp_path / "after.xlsx"
    rows = _add_period_rows(_base_rows())
    rows[1][1] = None                      # 少了 202603 的一个旧格
    _wb(after, rows)
    res = LM.write_after_checks(master, after, copy, "202609")
    assert res["ok"] is False
    assert any("少了" in r for r in res["reasons"]), res["reasons"]


def test_period_group_continuation():
    """新国际排名式「每期 3 列一组、只有首列带期次号」——右侧延续列也归当期。"""
    cells = {
        (1, "B"): "202609",
        (2, "B"): "1", (2, "C"): "2", (2, "D"): "3",
        (5, "F"): "202607",
    }
    ok, bad = LM.attribute(cells, "202609")
    assert (2, "B") in ok and (2, "C") in ok and (2, "D") in ok
    assert (5, "F") in bad


def test_dotted_period_labels_attributed():
    """Q1-Q4 / 实际与预测差值的期次标签是 `2026.09` 点格式——归因也要认（覆盖审计抓到的坑）。"""
    cells = {(1, "B"): "2026.09", (2, "B"): "0.31", (5, "D"): "2026.07"}
    ok, bad = LM.attribute(cells, "202609")
    assert (1, "B") in ok and (2, "B") in ok
    assert (5, "D") in bad


def test_review_summary_lists_changed_sheets(files):
    master, copy = files
    rows = LM.review_summary(master, copy, "202609")
    assert rows and rows[0]["name"] == "总被引"
    assert rows[0]["source"] == "ESI"
    assert "格" in rows[0]["content"]
