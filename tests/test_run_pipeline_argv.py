# -*- coding: utf-8 -*-
"""run_pipeline 的命令行参数闸：未知参数必须报错退出，不许"忽略后照跑"。

2026-10-23 实案：`python src\\run_pipeline.py --help`（本脚本当时没有这个开关）
被当成可选参数忽略，直接拿默认台账开跑，把 out/202609 的成品撤进了 _superseded。
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import run_pipeline  # noqa: E402


def test_help_只打印用法_不跑流水线(capsys):
    with pytest.raises(SystemExit) as exc:
        run_pipeline._parse_argv(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--period" in out and "--backtest" in out


def test_未知参数_退出码2(capsys):
    with pytest.raises(SystemExit) as exc:
        run_pipeline._parse_argv(["--bogus"])
    assert exc.value.code == 2
    assert "不认识的参数" in capsys.readouterr().err


def test_period_缺值_退出码2():
    with pytest.raises(SystemExit) as exc:
        run_pipeline._parse_argv(["--period"])
    assert exc.value.code == 2


def test_period_非数字_退出码2():
    with pytest.raises(SystemExit) as exc:
        run_pipeline._parse_argv(["--period", "2026-09"])
    assert exc.value.code == 2


def test_两个台账路径_退出码2():
    with pytest.raises(SystemExit) as exc:
        run_pipeline._parse_argv(["a.xlsx", "b.xlsx"])
    assert exc.value.code == 2


def test_正常参数解析():
    src, period, backtest = run_pipeline._parse_argv(
        ["input/台账.xlsx", "--period", "202609", "--backtest"])
    assert src == "input/台账.xlsx"
    assert period == "202609"
    assert backtest is True

    src2, period2, backtest2 = run_pipeline._parse_argv([])
    assert src2 is None and period2 is None and backtest2 is False
