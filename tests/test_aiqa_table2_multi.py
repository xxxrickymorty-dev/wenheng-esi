# -*- coding: utf-8 -*-
"""问数库的**报告大表/概述按多期收**（2026-10-28 定）。

背景：`report_table2` / `report_overview` 的主键本来就含 `period`，但 ETL 原先只灌
`build()` 那一个期次 —— 于是问「202609 的报告大表」要么回退、要么答空，而 `out/`
下明明有 5 期 `table2.csv`。这里钉住「逐期全收」+「缺文件跳过不编数」两条。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiqa_db                                                  # noqa: E402

_HEADER = ("discipline,rank_cn_change,papers,cnci,total_cites,thr_1pct,"
           "thr_1pct_gap,thr_1permille,permille_rank,top_papers,prox_change\n")


def _write_table2(root: pathlib.Path, period: str, *, rows: int = 2) -> None:
    d = root / "out" / period
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(f"Disc{i},-{i},{100 + i},1.5,{900 + i},800,50,9000,2.5,{7 + i},↑1%\n"
                   for i in range(rows))
    (d / "table2.csv").write_text(_HEADER + body, encoding="utf-8-sig")


def _write_overview(root: pathlib.Path, period: str) -> None:
    d = root / "out" / period
    d.mkdir(parents=True, exist_ok=True)
    (d / "overview_facts.json").write_text('{"n_disc": 22, "period": "%s"}' % period,
                                           encoding="utf-8")


def test_多期大表与概述全部收进来(tmp_path):
    root = tmp_path / "repo"
    for p in ("202601", "202603", "202605"):
        _write_table2(root, p)
        _write_overview(root, p)

    t2, t2_periods = aiqa_db._multi_period_rows(
        root, aiqa_db._table2_rows, "table2.csv")
    ov, ov_periods = aiqa_db._multi_period_rows(
        root, aiqa_db._overview_rows, "overview_facts.json")

    assert t2_periods == ["202601", "202603", "202605"]
    assert ov_periods == ["202601", "202603", "202605"]
    assert len(t2) == 6                       # 3 期 × 2 行
    assert len(ov) == 6                       # 3 期 × 2 键
    # 每期都自带 period，不是都挂同一个
    assert sorted({r[0] for r in t2}) == ["202601", "202603", "202605"]


def test_缺文件的期次跳过_不编数(tmp_path):
    root = tmp_path / "repo"
    _write_table2(root, "202601")
    (root / "out" / "202603").mkdir(parents=True)      # 有目录、没 table2.csv
    _write_table2(root, "202605")

    t2, periods = aiqa_db._multi_period_rows(
        root, aiqa_db._table2_rows, "table2.csv")

    assert periods == ["202601", "202605"]             # 202603 不出现
    assert len(t2) == 4


def test_非期次目录不算(tmp_path):
    root = tmp_path / "repo"
    _write_table2(root, "202601")
    _write_table2(root, "_aidata")                      # 非六位期次名
    _write_table2(root, "2026")                         # 不足六位

    _, periods = aiqa_db._multi_period_rows(
        root, aiqa_db._table2_rows, "table2.csv")

    assert periods == ["202601"]


def test_out_目录不存在时给空(tmp_path):
    rows, periods = aiqa_db._multi_period_rows(
        tmp_path / "nowhere", aiqa_db._table2_rows, "table2.csv")
    assert rows == [] and periods == []
