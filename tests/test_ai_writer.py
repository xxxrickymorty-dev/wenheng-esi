# -*- coding: utf-8 -*-
"""写作位（`ai/_writer.py`）：默认关 / 成功 / 事实过盾 / 盾拒 / keep / veto / 回退 / 留痕。

替身一律经 `ai.using(brain=…)`（与其余 AI 用例同一套约定）；记录落 tmp 根，零仓库污染。
"""
import json
import pathlib

import pytest

import ai
from ai import _writer

from _ai_helpers import FailingBrain, ScriptedBrain, Turn, raw_digits

TEXT = "2026年7月，化学的总被引 49394 次，高于 1% 阈值 41691 次。"
FACTS = ["池内总被引第 3 位（近 7 期）"]


def _rewrite(b):
    """按受保护文本改写：保留全部 [[n]]，换个说法（合法候选）。"""
    rule = b.task.split("【规则稿】\n", 1)[1].split("\n\n【事实摘要】", 1)[0]
    facts = b.task.split("【事实摘要】\n", 1)[1] if "【事实摘要】" in b.task else ""
    return Turn(text=f"本期化学升势明确：{rule} 佐证：{facts.replace(chr(10), '；')}")


def _records(tmp):
    p = pathlib.Path(tmp) / "202607" / "ai_calls.jsonl"
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


class Test写作位:
    def test_默认关_不碰模型不写记录(self, tmp_path, monkeypatch):
        monkeypatch.delenv(_writer.ENV_ON, raising=False)

        class _Bomb:
            name, is_rule = "bomb", False

            def think(self, brief):                                    # noqa: ARG002
                raise AssertionError("默认关时不应调用模型")

        with ai.using(data_root=tmp_path, brain=_Bomb()):
            out = _writer.write(TEXT, facts=FACTS)
        assert out == TEXT
        assert _records(tmp_path) == [], "默认关不应写记录"

    def test_成功_数字还原_恰一条记录(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([_rewrite])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.write(TEXT, facts=FACTS, period="202607",
                                label="flexible/single_trend/概况")
        assert out != TEXT and "49394" in out and "3 位" in out
        rows = _records(tmp_path)
        assert len(rows) == 1, "每次调用恰一条"
        r = rows[0]
        assert r["capability"] == "polish" and r["mode"] == "model"
        assert r["fallback"] is None and r["backend"] == "scripted"
        assert r["egress"]["bytes"] > 0
        assert r["shield"]["checked"] > 0 and r["shield"]["checked"] == r["shield"]["passed"]
        assert r["question"] == "flexible/single_trend/概况"

    def test_事实进盾_外发零数字原值(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([_rewrite])
        with ai.using(data_root=tmp_path, brain=brain):
            _writer.write(TEXT, facts=FACTS, period="202607")
        assert brain.briefs, "应有一次外发"
        for t in brain.briefs[0].egress_texts():
            assert not raw_digits(t), f"外发含数字原值：{t[:80]!r}"

    def test_盾拒_游离数字或丢占位符(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([lambda b: Turn(text="化学的总被引激增，涨幅明显。")])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.write(TEXT, facts=FACTS, period="202607")
        assert out == TEXT
        assert _records(tmp_path)[0]["fallback"] == "shield_reject"

    def test_keep被弄坏_回退(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        text = "接近度的上升待验证假设与发文量同向（49394 次）。"
        brain = ScriptedBrain([lambda b: Turn(text="接近度的上升与发文量同向（[[1]] 次）。")])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.write(text, period="202607")
        assert out == text, "「待验证假设」被弄坏必须整段回退"
        assert _records(tmp_path)[0]["fallback"] == "keep_broken"

    def test_veto_守卫拒(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([_rewrite])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.write(TEXT, facts=FACTS, period="202607",
                                veto=lambda t: True)               # noqa: ARG005
        assert out == TEXT
        assert _records(tmp_path)[0]["fallback"] == "guard_reject"

    def test_模型失败_回退原文(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=tmp_path, brain=FailingBrain()):
            out = _writer.write(TEXT, facts=FACTS, period="202607")
        assert out == TEXT
        assert _records(tmp_path)[0]["fallback"].startswith("brain_error:")

    def test_超预算不发包(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        import urllib.request
        from ai._brain import OpenAIBrain

        def boom(*a, **k):                                         # noqa: ARG001
            raise AssertionError("超预算不应发包")

        monkeypatch.setattr(urllib.request, "urlopen", boom)
        brain = OpenAIBrain(base_url="https://api.example.com/v1", model="m",
                            key="sk-test", max_egress_chars=10)
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.write(TEXT, facts=FACTS, period="202607")
        assert out == TEXT
        assert _records(tmp_path)[0]["fallback"] == "brain_error:egress_budget"

    def test_开了开关但未配云_记规则版(self, tmp_path, monkeypatch):
        """部署上开了写作位但没有 key：照记一条 mode=rule，产出原文。"""
        monkeypatch.setenv(_writer.ENV_ON, "1")
        from ai._brain import RuleBrain
        with ai.using(data_root=tmp_path, brain=RuleBrain()):
            out = _writer.write(TEXT, facts=FACTS, period="202607")
        assert out == TEXT
        r = _records(tmp_path)[0]
        assert r["mode"] == "rule" and r["fallback"] is None
