# -*- coding: utf-8 -*-
"""写作位（`ai/_writer.py`）：改写/创写两形态——默认关 / 成功 / 事实过盾 / 盾拒 /
keep / veto / 回退 / 留痕；写作位专用模型与预算（`WENHENG_FLEX_MODEL`、180s/8000）。

替身一律经 `ai.using(brain=…)`（与其余 AI 用例同一套约定）；记录落 tmp 根，零仓库污染。
"""
import json
import pathlib

import pytest

import ai
from ai import _writer, _writing

from _ai_helpers import FailingBrain, ScriptedBrain, Turn, raw_digits

TEXT = "2026年7月，化学的总被引 49394 次，高于 1% 阈值 41691 次。"
FACTS = ["池内总被引第 3 位（近 7 期）"]

TOPIC = "成因研判（判断草稿）"
COMPOSE_FACTS = ["化学学科近 7 期接近度持续上行（本期 0.87，上期 0.83）",
                 "全球总被引排名由第 9 位升至第 3 位"]
SAFE = "【手工：成因研判】"


def _rewrite(b):
    """按受保护文本改写：保留全部 [[n]]，换个说法（合法候选）。"""
    rule = b.task.split("【规则稿】\n", 1)[1].split("\n\n【事实摘要】", 1)[0]
    facts = b.task.split("【事实摘要】\n", 1)[1] if "【事实摘要】" in b.task else ""
    return Turn(text=f"本期化学升势明确：{rule} 佐证：{facts.replace(chr(10), '；')}")


def _composed(b, drop=""):
    """按受保护任务创写：题面 + 事实全带上（全部标记恰一次）+ 待审线自标（合法候选）。

    `drop` 用来做 keep 破坏（从候选里删掉必须保留的标记）。
    """
    topic = b.task.split("【节主题】\n", 1)[1].split("\n\n【事实摘要】", 1)[0]
    facts = b.task.split("【事实摘要】\n", 1)[1] if "【事实摘要】" in b.task else ""
    body = topic + "：" + facts.replace("\n- ", "；")
    if drop:
        body = body.replace(drop, "")
    return Turn(text=f"=={body}==。判断为学科积累与规模效应共同作用。")


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
        assert r["label"] == "flexible/single_trend/概况" and r["question"] == ""

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
        text = "接近度的上升【手工：判断】与发文量同向（49394 次）。"
        brain = ScriptedBrain([lambda b: Turn(text="接近度的上升与发文量同向（[[1]] 次）。")])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.write(text, period="202607")
        assert out == text, "「【手工：」被弄坏必须整段回退"
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


class Test创写:
    """`compose()`：节主题 + 事实摘要（无规则稿）→ 判断草稿；失败一律返回安全值。"""

    def test_默认关_不碰模型不写记录(self, tmp_path, monkeypatch):
        monkeypatch.delenv(_writer.ENV_ON, raising=False)

        class _Bomb:
            name, is_rule = "bomb", False

            def think(self, brief):                                    # noqa: ARG002
                raise AssertionError("默认关时不应调用模型")

        with ai.using(data_root=tmp_path, brain=_Bomb()):
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607")
        assert out == SAFE
        assert _records(tmp_path) == [], "默认关不应写记录"

    def test_空题面_直返安全值不碰模型(self, tmp_path, monkeypatch):
        """开关开着、题面为空：无稿可创，安全值直返（与 write 的空输入同政策）。"""
        monkeypatch.setenv(_writer.ENV_ON, "1")

        class _Bomb:
            name, is_rule = "bomb", False

            def think(self, brief):                                    # noqa: ARG002
                raise AssertionError("空题面不应调用模型")

        with ai.using(data_root=tmp_path, brain=_Bomb()):
            out = _writer.compose("  ", facts=COMPOSE_FACTS, safe=SAFE, period="202607")
        assert out == SAFE and _records(tmp_path) == []

    def test_成功_数字还原_待审线保留_恰一条记录(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([_composed])
        st: dict = {}
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607",
                                  label="flexible/single_judge/成因研判", status=st)
        assert out != SAFE and "0.87" in out and "近 7 期" in out
        assert "==" in out, "待审线自标原样保留"
        assert st == {"mode": "model", "backend": "scripted", "fallback": None}
        rows = _records(tmp_path)
        assert len(rows) == 1, "每次调用恰一条"
        r = rows[0]
        assert r["capability"] == "polish" and r["mode"] == "model"
        assert r["fallback"] is None and r["backend"] == "scripted"
        assert r["egress"]["bytes"] > 0
        assert r["shield"]["checked"] > 0 and r["shield"]["checked"] == r["shield"]["passed"]
        assert r["label"] == "flexible/single_judge/成因研判" and r["question"] == ""

    def test_题面事实进盾_外发零数字原值(self, tmp_path, monkeypatch):
        """题面里的数字与事实一样过盾，外发面零数字原值。"""
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([_composed])
        with ai.using(data_root=tmp_path, brain=brain):
            _writer.compose("化学学科近 7 期接近度上行（判断草稿）", facts=COMPOSE_FACTS,
                            safe=SAFE, period="202607")
        assert brain.briefs, "应有一次外发"
        for t in brain.briefs[0].egress_texts():
            assert not raw_digits(t), f"外发含数字原值：{t[:80]!r}"

    def test_盾拒_游离数字或丢占位符(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([lambda b: Turn(text="化学学科接近度持续上行，判断为积累效应。")])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607")
        assert out == SAFE
        assert _records(tmp_path)[0]["fallback"] == "shield_reject"

    def test_keep被弄坏_回退安全值(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([lambda b: _composed(b, drop="【手工：节注】")])
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.compose(TOPIC + "【手工：节注】", facts=COMPOSE_FACTS, safe=SAFE,
                                  period="202607")
        assert out == SAFE, "题面里该保留的标记被弄坏必须回退安全值"
        assert _records(tmp_path)[0]["fallback"] == "keep_broken"

    def test_veto_守卫拒(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([_composed])
        st: dict = {}
        with ai.using(data_root=tmp_path, brain=brain):
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607",
                                  veto=lambda t: True, status=st)     # noqa: ARG005
        assert out == SAFE
        assert st["fallback"] == "guard_reject"
        assert _records(tmp_path)[0]["fallback"] == "guard_reject"

    def test_模型失败_回退安全值(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        from ai._brain import BrainError
        with ai.using(data_root=tmp_path, brain=FailingBrain(BrainError("超时", code="timeout"))):
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607")
        assert out == SAFE
        assert _records(tmp_path)[0]["fallback"] == "brain_error:timeout"

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
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607")
        assert out == SAFE
        assert _records(tmp_path)[0]["fallback"] == "brain_error:egress_budget"

    def test_开了开关但未配云_回退安全值_记规则版(self, tmp_path, monkeypatch):
        """开了开关但没有云：无规则稿可回，安全值照发；照记一条 mode=rule。"""
        monkeypatch.setenv(_writer.ENV_ON, "1")
        from ai._brain import RuleBrain
        with ai.using(data_root=tmp_path, brain=RuleBrain()):
            out = _writer.compose(TOPIC, facts=COMPOSE_FACTS, safe=SAFE, period="202607")
        assert out == SAFE
        r = _records(tmp_path)[0]
        assert r["mode"] == "rule" and r["fallback"] is None


class Test写作位模型与预算:
    """`WENHENG_FLEX_MODEL` 与 180s/8000：只在写作位生效，对话/规划不动（装配口在 `_writing`）。"""

    def test_模型名_默认reasoner级_env覆盖(self, monkeypatch):
        monkeypatch.delenv(_writing.ENV_MODEL, raising=False)
        assert _writing.flex_model() == _writing.DEFAULT_MODEL
        monkeypatch.setenv(_writing.ENV_MODEL, "reasoner-x")
        assert _writing.flex_model() == "reasoner-x"

    def test_装配_写作位专用模型与预算_快模型不动(self, monkeypatch):
        monkeypatch.setenv("WENHENG_AI_BACKEND", "openai")
        monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
        monkeypatch.setenv("WENHENG_AI_MODEL", "fast-model")
        monkeypatch.setenv(_writing.ENV_MODEL, "reasoner-model")
        from ai._brain import OpenAIBrain
        from ai._config import build_brain

        flex = _writing.flex_brain()
        assert isinstance(flex, OpenAIBrain)
        assert flex.model == "reasoner-model"
        assert flex.timeout == 180.0 and flex.max_tokens == 8000
        fast = build_brain()
        assert isinstance(fast, OpenAIBrain), "对话/规划仍按 WENHENG_AI_* 装配"
        assert fast.model == "fast-model"
        assert fast.timeout == 30.0 and fast.max_tokens == 2048

    def test_demo档_锁规则版(self, monkeypatch):
        """演示站 `profile=demo`：即使机器上配了云，写作位也不出网。"""
        monkeypatch.setenv("WENHENG_AI_PROFILE", "demo")
        monkeypatch.setenv("WENHENG_AI_BACKEND", "openai")
        monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
        assert _writing.flex_brain().is_rule

    def test_注入替身优先于env(self, monkeypatch):
        monkeypatch.setenv("WENHENG_AI_BACKEND", "openai")
        monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
        brain = ScriptedBrain([])
        with ai.using(brain=brain):
            assert _writing.flex_brain() is brain
