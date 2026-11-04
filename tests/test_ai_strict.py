# -*- coding: utf-8 -*-
"""供应商强制语义（rick 2026-11-04）：添加了供应商＝全系统强制模型。

- **开启态**（monkeypatch 配齐 `WENHENG_AI_*` ＋ 注入替身 brain）：
  模型位失败**不许回落规则稿占位**——能整单失败的抛
  `ai._attempt.AIRequiredError`（灵活规划 / 写作位 / 主产线诊断），
  问文衡给失败说明（人话 + 原因码）；**记录面照记**（审计不丢）。
- **关闭态**（清掉 `WENHENG_AI_*`）：一切照旧——失败回落规则，
  既有回落用例（test_ai_writer / test_ai_fallback_parity …）同口径覆盖。

替身一律经 `ai.using(brain=…)`；记录落 tmp 根，零仓库污染。
判定口径只有一条：部署配置非规则版（`_attempt.strict_enabled()`），
注入的 brain 只影响当次调用、不改变部署事实。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import uuid

import pytest

import ai
from ai import _writer
from ai._attempt import AIRequiredError, strict_enabled
from ai._brain import BrainError

from _ai_helpers import FailingBrain, ScriptedBrain, Turn, seed_period

OPEN_ENV = {"WENHENG_AI_BACKEND": "openai",
            "WENHENG_AI_BASE_URL": "https://api.example.com/v1",
            "WENHENG_AI_MODEL": "fast-model",
            "WENHENG_AI_KEY": "sk-test"}

TEXT = "2026年7月，化学的总被引 49394 次，高于 1% 阈值 41691 次。"
TOPIC = "成因研判（判断草稿）"
SAFE = "【手工：成因研判】"
FAIL = BrainError("超时", code="timeout")


@pytest.fixture
def ai_root():
    """自管临时根（本机沙箱里 pytest tmp_path 清理是基线 PermissionError，
    见交付说明）——记录落仓库 tmp/ 下，用完即删，零仓库污染。"""
    d = (pathlib.Path(__file__).resolve().parent.parent / "tmp"
         / f"pt_strict_{uuid.uuid4().hex[:8]}")
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def open_state(ai_root, monkeypatch):
    """开启态：配齐供应商 env（部署事实）；brain 由用例自行注入。"""
    for k, v in OPEN_ENV.items():
        monkeypatch.setenv(k, v)
    return ai_root


@pytest.fixture
def closed_state(ai_root, monkeypatch):
    """关闭态（默认部署）：清掉供应商 env——回落语义原样。"""
    for k in OPEN_ENV:
        monkeypatch.delenv(k, raising=False)
    return ai_root


def _rows(root, period="202607"):
    p = pathlib.Path(root) / period / "ai_calls.jsonl"
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def _rows_ai(root):
    """空期次（如对话内核轮未落期次）的记账目录。"""
    return _rows(root, "_ai")


def _cap(rows, capability):
    return [r for r in rows if r.get("capability") == capability]


# ================================================================ 判定口
class Test判定口:
    def test_配齐env即开启_清掉即关闭(self, monkeypatch):
        for k in OPEN_ENV:
            monkeypatch.delenv(k, raising=False)
        assert strict_enabled() is False, "默认＝供应商关闭"
        for k, v in OPEN_ENV.items():
            monkeypatch.setenv(k, v)
        assert strict_enabled() is True, "配齐＝供应商开启"

    def test_demo锁与缺key都算关闭(self, monkeypatch):
        for k, v in OPEN_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("WENHENG_AI_PROFILE", "demo")
        assert strict_enabled() is False
        monkeypatch.delenv("WENHENG_AI_PROFILE", raising=False)
        monkeypatch.delenv("WENHENG_AI_KEY", raising=False)
        assert strict_enabled() is False

    def test_注入替身不改变部署事实(self, closed_state):
        with ai.using(brain=FailingBrain()):
            assert strict_enabled() is False, "brain 注入只影响当次调用"


# ================================================================ 写作位
class Test写作位_开启态:
    def test_改写失败_上抛不落原文_照记(self, open_state, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=open_state, brain=FailingBrain(FAIL)):
            with pytest.raises(AIRequiredError) as ei:
                _writer.write(TEXT, facts=["池内总被引第 3 位（近 7 期）"],
                              period="202607", label="flexible/single_trend/概况")
        assert "原因码 brain_error:timeout" in str(ei.value)
        assert "规则稿" in str(ei.value)
        row = _rows(open_state)[0]
        assert row["capability"] == "polish" and row["mode"] == "rule"
        assert row["fallback"] == "brain_error:timeout", "记录面照记（审计不丢）"

    def test_创写失败_上抛不落安全值_照记(self, open_state, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=open_state, brain=FailingBrain(FAIL)):
            with pytest.raises(AIRequiredError):
                _writer.compose(TOPIC, facts=["接近度近 7 期上行"],
                                safe=SAFE, period="202607",
                                label="flexible/single_judge/成因研判")
        row = _rows(open_state)[0]
        assert row["fallback"] == "brain_error:timeout" and row["mode"] == "rule"

    def test_守卫拒_同样上抛(self, open_state, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        brain = ScriptedBrain([lambda b: Turn(
            text="本期化学升势明确："
                 + b.task.split("【规则稿】" + chr(10), 1)[1])])
        with ai.using(data_root=open_state, brain=brain):
            with pytest.raises(AIRequiredError):
                _writer.write(TEXT, facts=[], period="202607",
                              veto=lambda t: True)               # noqa: ARG005
        assert _rows(open_state)[0]["fallback"] == "guard_reject"


class Test写作位_关闭态:
    """关闭态照旧回落（与 test_ai_writer / test_ai_fallback_parity 同口径）。"""

    def test_改写失败_回退原文_照记(self, closed_state, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=closed_state, brain=FailingBrain(FAIL)):
            out = _writer.write(TEXT, period="202607")
        assert out == TEXT
        assert _rows(closed_state)[0]["fallback"] == "brain_error:timeout"

    def test_创写失败_回退安全值_照记(self, closed_state, monkeypatch):
        monkeypatch.setenv(_writer.ENV_ON, "1")
        with ai.using(data_root=closed_state, brain=FailingBrain(FAIL)):
            out = _writer.compose(TOPIC, facts=[], safe=SAFE, period="202607")
        assert out == SAFE
        assert _rows(closed_state)[0]["fallback"] == "brain_error:timeout"


# ================================================================ 问文衡（qa）
class Test问文衡_开启态:
    def test_单轮问答失败_失败说明带原因码_不落规则稿正文(self, open_state):
        seed_period(open_state)
        with ai.using(data_root=open_state, brain=FailingBrain(FAIL)):
            ans = ai.run("qa", "202607", payload={"question": "本期总被引多少？"},
                         actor="admin")
        assert ans.mode == "failed"
        assert ("超时" in ans.text or "没有作答" in ans.text)
        assert "原因码" in ans.text and "brain_error:timeout" in ans.text
        assert ans.text != ans.rule_text, "失败说明不是规则拼装正文"
        row = _cap(_rows(open_state), "qa")[0]
        assert row["mode"] == "failed" and row["fallback"] == "brain_error:timeout"

    def test_取数规划失败_上抛不拿规则规划顶包(self, open_state, monkeypatch):
        from ai import _plan
        with ai.using(brain=FailingBrain(FAIL)):
            with pytest.raises(AIRequiredError) as ei:
                _plan.plan("随便说说近况", disciplines=["Chemistry"])
        assert "原因码 brain_error:timeout" in str(ei.value)


class Test问文衡_关闭态:
    def test_问答失败照旧显式失败态_文案不带原因码(self, closed_state):
        seed_period(closed_state)
        with ai.using(data_root=closed_state, brain=FailingBrain(FAIL)):
            ans = ai.run("qa", "202607", payload={"question": "本期总被引多少？"},
                         actor="admin")
        assert ans.mode == "failed"
        assert "原因码" not in ans.text, "关闭态文案与从前逐字一致"

    def test_取数规划失败_照旧回规则带note(self, closed_state):
        from ai import _plan
        with ai.using(brain=FailingBrain(FAIL)):
            plan = _plan.plan("随便说说近况", disciplines=["Chemistry"])
        assert plan["origin"] == "rule" and plan["note"] == "brain_error:timeout"


# ================================================================ 主产线 AI 位（diagnose）
class Test主产线_开启态:
    def test_诊断失败_照记后上抛(self, open_state):
        seed_period(open_state)
        with ai.using(data_root=open_state, brain=FailingBrain(FAIL)):
            with pytest.raises(AIRequiredError) as ei:
                ai.run("diagnose", "202607",
                       payload={"failure": {"code": "ASSERT_FAIL", "period": "202607"}},
                       actor="system")
        assert "原因码 brain_error:timeout" in str(ei.value)
        row = _cap(_rows(open_state), "diagnose")[0]
        assert row["mode"] == "failed" and row["fallback"] == "brain_error:timeout"


class Test主产线_关闭态:
    def test_诊断失败_照旧规则稿直出(self, closed_state):
        seed_period(closed_state)
        with ai.using(data_root=closed_state, brain=FailingBrain(FAIL)):
            ans = ai.run("diagnose", "202607",
                         payload={"failure": {"code": "ASSERT_FAIL", "period": "202607"}},
                         actor="system")
        assert ans.mode == "rule" and ans.text, "关闭态：规则稿直出（现状不变）"


# ================================================================ 对话内核轮
class Test对话内核轮_开启态:
    def test_内核失败_失败说明不落规则拼装_记录照记(self, open_state):
        class _Boom:
            name = "boom"

            def __call__(self, *a, **k):                        # noqa: ARG002
                raise RuntimeError("内核炸了")

        with ai.using(data_root=open_state, dialog_kernel=_Boom(),
                      inventory=(lambda _p: None)):
            ans = ai.run("dialog", "",
                         payload={"text": "上上期呢",
                                  "history": [{"who": "me", "text": "查最新的化学接近度"}],
                                  "periods": ["202609", "202607"]},
                         actor="admin")
        assert ans.mode == "failed"
        assert "原因码" in ans.text, "内核轮失败＝这轮对话失败，不拿规则拼装顶包"
        rec = _cap(_rows_ai(open_state), "dialog")
        assert rec and rec[0]["mode"] == "fallback", "记录面照实（fallback）"

    def test_规则命中_不经内核_照旧规则应答(self, open_state):
        with ai.using(data_root=open_state, inventory=(lambda _p: None)):
            ans = ai.run("dialog", "",
                         payload={"text": "帮我做 9 月的报告"}, actor="admin")
        assert ans.mode == "rule", "规则确定性命中不经内核，开启态也不变"


# ================================================================ 灵活产线（planner / report）
class Test灵活规划_开启态:
    @pytest.fixture(autouse=True)
    def _prompt(self, monkeypatch):
        from flexible import planner
        monkeypatch.setattr(planner, "_model_prompt",
                            lambda *a, **k: "提示（替身，不需要真台账）")

    def test_模型规划失败_上抛不落规则规划(self, open_state):
        from flexible import planner
        with ai.using(brain=FailingBrain(FAIL)):
            with pytest.raises(AIRequiredError) as ei:
                planner._brain_plan(None, "single_trend")
        assert "原因码 brain_error:timeout" in str(ei.value)

    def test_模型输出坏JSON_上抛(self, open_state):
        from flexible import planner
        with ai.using(brain=ScriptedBrain([Turn(text="我不是 JSON。")])):
            with pytest.raises(AIRequiredError) as ei:
                planner._brain_plan(None, "single_trend")
        assert "原因码 bad_json" in str(ei.value)


class Test灵活规划_关闭态:
    @pytest.fixture(autouse=True)
    def _prompt(self, monkeypatch):
        from flexible import planner
        monkeypatch.setattr(planner, "_model_prompt",
                            lambda *a, **k: "提示（替身，不需要真台账）")

    def test_失败照旧回规则规划带原因(self, closed_state):
        from flexible import planner
        with ai.using(brain=FailingBrain(FAIL)):
            got, reason, _backend = planner._brain_plan(None, "single_trend")
        assert got is None and reason == "brain_error:timeout"


class Test灵活报告_写作位穿透:
    def _boom_ai_required(self, monkeypatch, name):
        def _boom(*a, **k):                                          # noqa: ARG005
            raise AIRequiredError("brain_error:timeout", what="写作位")
        monkeypatch.setattr(f"ai._writer.{name}", _boom)

    def test_写作位失败_穿透不吞_不落规则稿(self, open_state, monkeypatch):
        from flexible import report as flex_report
        self._boom_ai_required(monkeypatch, "write")
        with pytest.raises(AIRequiredError):
            flex_report._polish("write", TEXT, label="x")

    def test_创写失败_穿透不落安全值(self, open_state, monkeypatch):
        from flexible import report as flex_report
        self._boom_ai_required(monkeypatch, "compose")
        with pytest.raises(AIRequiredError):
            flex_report._compose(TOPIC, SAFE, label="x")

    def test_兜底补标_开启态不许出现(self, open_state, monkeypatch):
        from flexible import report as flex_report

        class _FakeOp:
            @staticmethod
            def backfill_marks(t):
                return t, 2                       # 模拟漏标 2 句被规则补上

            @staticmethod
            def judgement_leaks(t):                       # noqa: ARG004
                return False

        monkeypatch.setattr(flex_report, "op", _FakeOp)

        def _fake_compose(*a, **k):                              # noqa: ARG005
            st = k.get("status")
            if st is not None:
                st.update({"mode": "model", "backend": "scripted",
                           "fallback": None})
            return "草稿正文"

        monkeypatch.setattr("ai._writer.compose", _fake_compose)
        with pytest.raises(AIRequiredError) as ei:
            flex_report._compose(TOPIC, SAFE, label="成因研判")
        assert "backstop" in str(ei.value)

    def test_普通异常仍回安全值_关闭态照旧(self, closed_state, monkeypatch):
        from flexible import report as flex_report

        def _boom(*a, **k):                                          # noqa: ARG005
            raise RuntimeError("普通炸")

        monkeypatch.setattr("ai._writer.compose", _boom)
        got, n = flex_report._compose(TOPIC, SAFE, label="x")
        assert (got, n) == (SAFE, 0), "非供应商失败的普通异常不改变既有回落"
