# -*- coding: utf-8 -*-
"""run_latest（一键出报告入口）的母本定位闸：input/ 里没有母本就报错，不猜、不扫。

2026-10-13 起 input/ 只放母本（一份、含全部期次）；find_ledger 是该口径的守门人。
入口的其余部分是 run_pipeline.main 的直通调用（其行为归 test_run_pipeline_argv.py
与写路径验收），不在本文件重复。
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import ledger  # noqa: E402
import run_latest  # noqa: E402


def test_find_ledger_命中母本(tmp_path):
    p = tmp_path / "input" / ledger.LEDGER_NAME
    p.parent.mkdir(parents=True)
    p.write_bytes(b"xlsx")
    assert run_latest.find_ledger(tmp_path) == p


def test_find_ledger_缺母本_报错并指路(tmp_path):
    (tmp_path / "input").mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        run_latest.find_ledger(tmp_path)
    assert "未找到动态监测表" in str(exc.value)
    assert "input" in str(exc.value)


def test_find_ledger_input目录不存在也报错(tmp_path):
    with pytest.raises(SystemExit):
        run_latest.find_ledger(tmp_path / "不存在")
