# -*- coding: utf-8 -*-
"""模型调用边界（`ai/_attempt.py`）：规则部署 / 失败码 / 盾拒 / egress / 调用方 mapping。

直测边界接口（它是四个调用方共用的 seam），不回绕到能力口。
"""
import ai
from ai import _attempt, _shield
from ai._brain import BrainError, RuleBrain

from _ai_helpers import FailingBrain, ScriptedBrain, Turn


def _run(brain, task="共 3 项，其中 2 项超线。", **kw):
    with ai.using(brain=brain):
        return _attempt.attempt(task, system="s", ability="diagnose", **kw)


class Test_边界:
    def test_规则部署_不算失败_规则物原样带回(self):
        out = _run(RuleBrain())
        assert out.attempted is False and out.reason is None
        assert out.text == "共 3 项，其中 2 项超线。"
        assert out.shield == {"checked": 2, "passed": 2}
        assert out.backend == "rule" and out.notice == ""

    def test_模型成功_还原并登记占位面候选(self):
        out = _run(ScriptedBrain([lambda b: Turn(text="改写：" + b.task)]))
        assert out.attempted is True and out.text == "改写：共 3 项，其中 2 项超线。"
        assert out.candidate_protected == "改写：共 [[1]] 项，其中 [[2]] 项超线。"
        assert out.shield == {"checked": 2, "passed": 2} and out.notice == ""

    def test_BrainError_带动态码与文案(self):
        out = _run(FailingBrain(BrainError("超时", code="timeout")))
        assert out.text is None and out.attempted is True
        assert out.reason == "brain_error:timeout"
        assert "模型调用失败" in out.notice and "超时" in out.notice
        assert out.shield == {"checked": 2, "passed": 0}

    def test_非BrainError异常_也统一成brain_error码(self):
        class Boom:
            name, is_rule = "boom", False

            def think(self, brief):                              # noqa: ARG002
                raise ValueError("坏了")

        out = _run(Boom())
        assert out.reason == "brain_error:ValueError" and "坏了" in out.notice

    def test_工具请求与空回复(self):
        out = _run(ScriptedBrain([Turn(calls=({"tool": "x"},))]))
        assert out.reason == "calls_unsupported" and "工具" in out.notice
        out = _run(ScriptedBrain([Turn(text="")]))
        assert out.reason == "empty_reply" and "模型未返回正文" in out.notice

    def test_盾拒_游离数字进detail(self):
        out = _run(ScriptedBrain([Turn(text="涨了 5%")]))
        assert out.text is None and out.reason == "shield_reject"
        assert out.detail and out.detail["stray"] == ["5"] and out.shield["passed"] == 0
        assert "数字校验" in out.notice

    def test_自由型_允许子集_allow_substrings(self):
        out = _run(ScriptedBrain([Turn(text="overview_1permille 与 [[1]]")]),
                   anchored=False, allow_substrings=("overview_1permille",))
        assert out.reason is None and out.text == "overview_1permille 与 3"

    def test_传入mapping_以调用方编号为准_重排不串来源(self):
        protected, mapping = _shield.protect_chunks(["问题", "数字 42 和 7"])
        out = _run(ScriptedBrain([Turn(text="数字 [[2]] 和 [[1]]")]),
                   task=protected[0], mapping=mapping, anchored=False)
        assert out.protected == "问题"          # 不再二次过盾
        assert out.text == "数字 7 和 42"
        assert out.candidate_protected == "数字 [[2]] 和 [[1]]"

    def test_egress_公式_items与bytes(self):
        with ai.using(brain=RuleBrain()):
            out = _attempt.attempt("无数字", system="s", ability="diagnose",
                                   evidence=("a", "b"))
            assert out.egress["items"] == 3 and out.egress["bytes"] > 0
            out = _attempt.attempt("无数字", system="s", ability="diagnose",
                                   evidence=("a",), tools=({"k": "v"},))
            assert out.egress["items"] == 3
