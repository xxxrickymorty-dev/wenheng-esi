# -*- coding: utf-8 -*-
"""报告逐格核验工具自身的回归（2026-09-20）。

守的是 **核验工具自己不能撒谎** —— 一个会漏比、会看错列的核验器比没有核验更危险：
它给出的"全对"会让人放心地签发一份错报告（T20「植物学与动物学」整行留白被
`compare_with_original` 漏比 11 格、却报「231/231 全对」就是这么发生的）。

本组用**构造的小 docx** 当输入，不依赖真实台账/产物（数据缺了也照样跑）。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO / "src"), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import verify_report_cells as vrc                            # noqa: E402
import parse_ledger                                          # noqa: E402


class FakeBook:
    """顶掉 openpyxl 的最小台账：只要 sheets[表名] = list[list]。"""

    def __init__(self, sheets):
        self.sheets = sheets

    row_of = vrc.Book.row_of
    col_of = vrc.Book.col_of
    group_col = vrc.Book.group_col
    at = vrc.Book.at
    at_group = vrc.Book.at_group


def _sheet(periods, rows):
    """期次表头 + 数据行。periods 每项 3 列（n_inst_1pct, rank, rank_pct）。"""
    hdr = [""]
    for p in periods:
        hdr += [p, "", ""]
    return [hdr] + rows


# ============================================================ ① 组内取列
def test_取列必须落在组内正确位置而不是期次表头格():
    """🔴 这是本工具第一版的真 bug：`col_of` 返回的是期次表头那一格（组内第 1 列
    ＝榜内机构数），直接拿它当 rank 会一次冒出几十条假差异
    （「报告 200 ≠ 源 598」）。"""
    book = FakeBook({"新国内排名": _sheet(
        ["202605", "202607"],
        [["Chemistry", 300, 468, 0.2469, 260, 153, 0.2268]])})
    assert book.col_of("新国内排名", "202607") == 4          # 期次表头那一格
    assert book.group_col("新国内排名", "202607", 0) == 4    # 榜内机构数
    assert book.group_col("新国内排名", "202607", 1) == 5    # rank ← 报告要的是它
    assert book.group_col("新国内排名", "202607", 2) == 6    # rank_pct
    v, loc = book.at_group("新国内排名", "Chemistry", "202607", 1)
    assert (v, loc) == (153, "新国内排名!F2")
    v, loc = book.at_group("新国际排名".replace("国际", "国内"), "Chemistry", "202605", 1)
    assert v == 468, "上期 rank 应当取 202605 组"


# ============================================================ ② 行名归一
def test_行名归一后整行能命中_否则报错():
    """T20 行名「植物学与动物学」查不到时，**必须报错**而不是静默跳过 ——
    2026-09-20 前正是静默跳过，导致那一行 11 格留白且回测漏比。"""
    tbl = [["学科/高校", "云大", "昆工"],
           ["植物学与动物学", "Y", "Y"],
           ["化学", "Y", "73.20%"]]
    mat = {"matrix": {"植物与动物学": {"云大": {"v": "Y"}, "昆工": {"v": "Y"}},
                      "化学": {"云大": {"v": "Y"}, "昆工": {"v": "73.20%"}}}}
    n, bad, notes = vrc.verify_matrix(tbl, mat)
    assert not bad, f"归一后应当全部命中，却报 {bad}"
    assert n == 4 and not notes

    # 去掉数据 → 归一后查不到 → 必须报「整行会被静默留空」
    mat2 = {"matrix": {"化学": {"云大": {"v": "Y"}, "昆工": {"v": "73.20%"}}}}
    n2, bad2, _ = vrc.verify_matrix(tbl, mat2)
    assert any("静默留空" in m for _, _, m, _ in bad2), bad2
    assert n2 == 4, "漏掉的行也要计入总数，否则覆盖率会虚高"


def test_源端空值报提示而不是错误():
    """源端就没有的格（早期 ESI 无该列 / InCites 无此校此科）报告里也空 ——
    两边都空**不是**一致，要单独报出来，否则「99 格全对」会被误读成「99 格都有数」。"""
    tbl = [["学科/高校", "云大", "昆工"], ["化学", "Y", ""]]
    mat = {"matrix": {"化学": {"云大": {"v": "Y"}, "昆工": {"v": "",
                                                          "src": "该期无此校数据"}}}}
    n, bad, notes = vrc.verify_matrix(tbl, mat)
    assert not bad and n == 2
    assert notes and "1 格空" in notes[0][1], notes


# ============================================================ ③ 表22 对账分档
def test_清单非本期时差异降级为提示():
    """顶尖论文清单是台账外人工贴入，复现稿沿用母版清单 → 与当期台账合计本就不同。
    判据＝行数是否等于台账合计：相等＝本期的，强校验；不等＝非本期的，降级提示。
    """
    book = FakeBook({"TOP论文": [["", "202607"],
                                 ["高被引论文合计", 2]]})
    big = [["ESI学科", "", "", "", "", "", "", "", "", "顶尖论文"],
           ["化学", "", "", "", "", "", "", "", "", "1"],
           ["工程学", "", "", "", "", "", "", "", "", "1"]]
    # 本期清单：2 行 = 台账合计 → 强校验；分学科计数与大表一致 → 无错无提示
    tbl_ok = [["序号", "WOS", "被引", "ESI学科"],
              ["1", "W1", "9", "CHEMISTRY"],
              ["2", "W2", "8", "ENGINEERING"]]
    n, errs, notes = vrc.verify_top_papers(tbl_ok, book, "202607", big)
    assert n == 2 and not errs and not notes, (errs, notes)

    # 非本期清单：3 行 ≠ 合计 2 → 差异降级为提示，错误为空
    tbl_other = [["序号", "WOS", "被引", "ESI学科"],
                 ["1", "W1", "9", "CHEMISTRY"],
                 ["2", "W2", "8", "CHEMISTRY"],
                 ["3", "W3", "7", "ENGINEERING"]]
    n2, errs2, notes2 = vrc.verify_top_papers(tbl_other, book, "202607", big)
    assert not errs2, f"非本期清单不该报错误：{errs2}"
    assert any("非本期" in m for _, _, m, _ in notes2), notes2
    assert any("分学科计数" in who for _, who, _, _ in notes2), notes2


def test_清单内部一致性问题任何情况都报错():
    """序号跳号与「被引不增」与"是不是本期"无关，任何稿都必须报错。"""
    book = FakeBook({"TOP论文": [["", "202607"], ["高被引论文合计", 99]]})
    big = [["ESI学科", "", "", "", "", "", "", "", "", "顶尖论文"], ["化学", "", "", "", "", "", "", "", "", "0"]]
    tbl = [["序号", "WOS", "被引", "ESI学科"],
           ["1", "W1", "5", "CHEMISTRY"],
           ["3", "W2", "9", "CHEMISTRY"]]        # 跳号 + 被引回升
    n, errs, notes = vrc.verify_top_papers(tbl, book, "202607", big)
    msgs = " ".join(m for _, _, m, _ in errs)
    assert "不连续" in msgs and "应降序" in msgs, errs


# ============================================================ ④ 别名表
def test_别名表是显式的且值都是规范名():
    assert parse_ledger.norm_disc_cn("植物学与动物学") == "植物与动物学"
    assert parse_ledger.norm_disc_cn("化学") == "化学"
    assert set(parse_ledger.DISC_CN_ALIAS.values()) <= set(parse_ledger.DISCIPLINES_CN.values())
