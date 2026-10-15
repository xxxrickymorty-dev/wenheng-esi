# -*- coding: utf-8 -*-
"""回落语义一致性（码 × 驱动）：同一个失败在能力口与写作位上码/mode 必须一致。

驱动不同、政策不同（能力口记录面是发布文本，写作位是任务占位面），但「失败怎么标」
只有一个来源（`ai/_attempt.py`）。本用例是那张码 × 驱动表。
"""
import json
import pathlib

import pytest

import ai
from ai import _writer
from ai._brain import BrainError

from _ai_helpers import FailingBrain, seed_period


def _rows(root, period="202607"):
    p = pathlib.Path(root) / period / "ai_calls.jsonl"
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.mark.parametrize("code,reason", [
    ("timeout", "brain_error:timeout"),
    ("rate_limit", "brain_error:rate_limit"),
    ("bad_response", "brain_error:bad_response"),
])
class Test_码与驱动:
    def test_能力口_失败_记rule_带码(self, tmp_path, code, reason):
        seed_period(tmp_path)
        with ai.using(data_root=tmp_path, brain=FailingBrain(BrainError("超时", code=code))):
            ans = ai.run("qa", "202607", payload={"question": "本期总被引多少？"},
                         actor="admin")
        assert ans.mode == "rule"
        row = _rows(tmp_path)[0]
        assert row["capability"] == "qa"
        assert row["mode"] == "rule" and row["fallback"] == reason

    def test_写作位_失败_记rule_带码(self, tmp_path, monkeypatch, code, reason):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=tmp_path, brain=FailingBrain(BrainError("超时", code=code))):
            out = _writer.write("2026年7月，化学的总被引 49394 次。", period="202607")
        assert out == "2026年7月，化学的总被引 49394 次。"
        row = _rows(tmp_path)[0]
        assert row["capability"] == "polish"
        assert row["mode"] == "rule", "回退原文时不得记成模型版"
        assert row["fallback"] == reason

    def test_创写形态_失败_记rule_带码(self, tmp_path, monkeypatch, code, reason):
        """compose 与 write 同一张码表：失败回退安全值，码/ mode 一致。"""
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=tmp_path, brain=FailingBrain(BrainError("超时", code=code))):
            out = _writer.compose("成因研判（判断草稿）", facts=["接近度近 7 期上行"],
                                  safe="【手工：成因】", period="202607")
        assert out == "【手工：成因】"
        row = _rows(tmp_path)[0]
        assert row["capability"] == "polish"
        assert row["mode"] == "rule", "回退安全值时不得记成模型版"
        assert row["fallback"] == reason
