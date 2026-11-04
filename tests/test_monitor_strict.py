# -*- coding: utf-8 -*-
"""监测版解读·供应商强制语义（rick 2026-11-04）。

- **开启态**（monkeypatch 配齐 `WENHENG_AI_*` ＋ 注入替身 brain，零网络）：
  `monitor.insight` 的模型位失败（compose 调用失败 / veto 拒收）不许拿
  句骨架占位——照记一条（记录面不丢）后抛 `ai._attempt.AIRequiredError`；
  `report.generate` / `compare.generate` 原样穿透，不落半份产物。
- **关闭态**（清掉 `WENHENG_AI_*`）：一切照旧——失败回落句骨架，
  既有回落用例（test_monitor_insight_shield 等）同口径覆盖。

回落层逐层判定（哪些属于「规则稿占位」）：
① compose 调用失败（回落码随 Outcome.reason）——占位，开启态上抛；
② veto 拒收（guard_reject，调用侧数字白名单）——占位，开启态上抛；
③ 模型文本成功采用（mode=model）——不是回落，开启态照常返回；
④ 非模型位的普通异常（如 veto 钩子自身炸）——不是供应商失败，
   关闭/开启态都维持既有回落（与 flexible.report 同判定）。

替身一律经 `ai.using(brain=…)`；记录落仓库 tmp/ 下（本机沙箱
pytest tmp_path 清理是基线 PermissionError，见交付说明），用完即删。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import ai                                          # noqa: E402
from _ai_helpers import FailingBrain, ScriptedBrain, Turn   # noqa: E402
from ai._attempt import AIRequiredError, strict_enabled     # noqa: E402
from ai._brain import BrainError               # noqa: E402
from monitor import compare as mcmp            # noqa: E402
from monitor import insight as mi              # noqa: E402
from monitor import report as mr               # noqa: E402

OPEN_ENV = {"WENHENG_AI_BACKEND": "openai",
            "WENHENG_AI_BASE_URL": "https://api.example.com/v1",
            "WENHENG_AI_MODEL": "fast-model",
            "WENHENG_AI_KEY": "sk-test"}

FAIL = BrainError("超时", code="timeout")
TOPIC = "为 2 所高校的 202609 期 ESI 学科对比报告写一篇 500 字以上的总体解读。"
FACTS = ["本次对比 2 校，按总被引排序：清华大学（第 1 名）、海南大学（第 300 名）",
         "清华大学上榜 22/22、前1% 22、前1‰ 5"]
SAFE = "规则拼装兜底。"
VALID = "本次对比覆盖 [[1]] 所高校，[[2]] 期格局与 [[1]] 校的位次关系稳定。"


@pytest.fixture
def ai_root():
    """自管临时根（同 test_ai_strict：记录落仓库 tmp/ 下，用完即删）。"""
    d = (pathlib.Path(__file__).resolve().parent.parent / "tmp"
         / f"pt_mon_strict_{uuid.uuid4().hex[:8]}")
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def work_root(ai_root):
    """generate 产物落点（不用 pytest tmp_path：本机沙箱清理是
    基线 PermissionError，见交付说明）。"""
    d = ai_root / "gen"
    d.mkdir()
    return d


@pytest.fixture
def open_state(ai_root, monkeypatch):
    for k, v in OPEN_ENV.items():
        monkeypatch.setenv(k, v)
    return ai_root


@pytest.fixture
def closed_state(ai_root, monkeypatch):
    for k in OPEN_ENV:
        monkeypatch.delenv(k, raising=False)
    return ai_root


def _rows(root):
    p = pathlib.Path(root) / "_ai" / "ai_calls.jsonl"
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def _compose(**kw):
    return mi.compose_text(TOPIC, FACTS, SAFE,
                           label=kw.pop("label", "monitor/insight_test"), **kw)


# ================================================================ 开启态
class Test开启态:
    def test_判定口照旧_替身不改变部署事实(self, open_state):
        assert strict_enabled() is True, "配齐 env＝供应商开启"

    def test_compose调用失败_上抛不落句骨架_照记(self, open_state):
        with ai.using(data_root=open_state, brain=FailingBrain(FAIL)):
            with pytest.raises(AIRequiredError) as ei:
                _compose()
        assert "原因码 brain_error:timeout" in str(ei.value)
        assert "监测版解读" in str(ei.value)
        assert "规则稿" in str(ei.value)
        row = _rows(open_state)[0]
        assert row["capability"] == "polish" and row["mode"] == "rule"
        assert row["fallback"] == "brain_error:timeout", "记录面照记（审计不丢）"
        assert row["label"] == "monitor/insight_test"

    def test_veto拒收_上抛带guard_reject_照记(self, open_state):
        with ai.using(data_root=open_state,
                      brain=ScriptedBrain([Turn(text=VALID)])):
            with pytest.raises(AIRequiredError) as ei:
                _compose(veto=lambda t: True)                # noqa: ARG005
        assert "原因码 guard_reject" in str(ei.value), "veto 拒收＝规则稿占位，同上抛"
        row = _rows(open_state)[0]
        assert row["fallback"] == "guard_reject"

    def test_模型稿成功采用_开启态照常返回(self, open_state):
        with ai.using(data_root=open_state,
                      brain=ScriptedBrain([Turn(text=VALID)])):
            res = _compose()
        assert res["mode"] == "model", "成功采用不是回落，开启态不抛"
        assert "[[" not in res["text"]

    def test_普通异常不属供应商失败_维持既有回落(self, open_state):
        def _boom(*a, **k):                                      # noqa: ARG002
            raise RuntimeError("veto 钩子炸了")

        with ai.using(data_root=open_state,
                      brain=ScriptedBrain([Turn(text=VALID)])):
            res = _compose(veto=_boom)
        assert res == {"text": SAFE, "mode": "rule"}, \
            "非模型位失败不改变既有回落（与 flexible.report 同判定）"

    def test_insight_穿透不吞(self, open_state, monkeypatch):
        def _boom(*a, **k):                                      # noqa: ARG002
            raise AIRequiredError("brain_error:timeout", what="监测版解读")

        monkeypatch.setattr(mi, "facts_of", lambda *a, **k: ["事实行"])
        monkeypatch.setattr(mi, "compose_text", _boom)
        # AIRequiredError 必须从 insight 外层穿透——不得吞成句骨架。
        with pytest.raises(AIRequiredError):
            mi.insight("云南大学", "202609", {"fields": {}})

    def test_report_generate_穿透不落半份产物(self, open_state, monkeypatch,
                                              work_root):
        monkeypatch.setattr(mr, "MONITOR_ROOT", work_root)
        monkeypatch.setattr(mr, "latest_period", lambda: "202609")
        monkeypatch.setattr(mr, "load_cache", lambda p: {"period": p})
        from monitor import insight as _ins_mod

        def _boom(*a, **k):                                   # noqa: ARG002
            raise AIRequiredError("brain_error:timeout", what="监测版解读")

        monkeypatch.setattr(_ins_mod, "insight", _boom)
        with pytest.raises(AIRequiredError):
            mr.generate("云南大学", "202609")
        assert not (work_root / "云南大学" / "202609.html").exists(), \
            "解读算在写盘之前：上抛即整单失败，不落半份产物"

    def test_compare_generate_穿透不落半份产物(self, open_state, monkeypatch,
                                               work_root):
        monkeypatch.setattr(mcmp, "compare_path",
                            lambda cns, p: work_root / f"cmp_{p}.html")
        monkeypatch.setattr(mr, "latest_period", lambda: "202609")
        monkeypatch.setattr(mr, "load_cache", lambda p: {"period": p})
        monkeypatch.setattr(mcmp, "facts_of", lambda cns, c: ["事实行"])

        def _boom(*a, **k):                                   # noqa: ARG002
            raise AIRequiredError("brain_error:timeout", what="监测版解读")

        monkeypatch.setattr(mi, "compose_text", _boom)
        with pytest.raises(AIRequiredError):
            mcmp.generate(["清华大学", "云南大学"], "202609")
        assert not (work_root / "cmp_202609.html").exists(), "不落半份产物"


# ================================================================ 关闭态
class Test关闭态:
    def test_判定口默认关闭(self, closed_state):
        assert strict_enabled() is False, "默认＝供应商关闭"

    def test_compose调用失败_照旧回落句骨架_照记(self, closed_state):
        with ai.using(data_root=closed_state, brain=FailingBrain(FAIL)):
            res = _compose()
        assert res == {"text": SAFE, "mode": "rule"}, "关闭态：现状逐字不变"
        row = _rows(closed_state)[0]
        assert row["fallback"] is None, "调用失败的记录面现状＝fallback None，逐字不变"

    def test_veto拒收_照旧回落句骨架(self, closed_state):
        with ai.using(data_root=closed_state,
                      brain=ScriptedBrain([Turn(text=VALID)])):
            res = _compose(veto=lambda t: True)              # noqa: ARG005
        assert res == {"text": SAFE, "mode": "rule"}

    def test_generate_照旧吞异常出件(self, closed_state, monkeypatch, work_root):
        """关闭态：generate 对 insight 异常的既有兜底不变（ins=None 照出件）。"""
        monkeypatch.setattr(mr, "MONITOR_ROOT", work_root)
        monkeypatch.setattr(mr, "latest_period", lambda: "202609")
        monkeypatch.setattr(mr, "load_cache", lambda p: {"period": p})
        monkeypatch.setattr(mr, "render", lambda *a, **k: "<html></html>")
        from monitor import insight as _ins_mod

        def _boom(*a, **k):                                      # noqa: ARG002
            raise RuntimeError("普通炸")

        monkeypatch.setattr(_ins_mod, "insight", _boom)
        out = mr.generate("云南大学", "202609")
        assert out.exists(), "关闭态：普通异常照旧兜底出件（现状不变）"
