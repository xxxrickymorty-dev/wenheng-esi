# -*- coding: utf-8 -*-
"""模型调用边界（`ai/_attempt.py`）：规则部署 / 失败码 / 盾拒 / egress / 调用方 mapping。

直测边界接口（它是四个调用方共用的 seam），不回绕到能力口。
"""
import json

import ai
from ai import _attempt, _shield
from ai._brain import BrainError, RuleBrain

from _ai_helpers import FailingBrain, ScriptedBrain, Turn, raw_digits, tool_texts


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


class Test_工具环:
    """原生工具环（OpenAI 官方多轮协议，2026-10-31 定稿）：
    think → calls → 执行 → assistant(tool_calls)+tool 消息进 Brief.history → 再 think。
    结果不再折进 evidence（evidence 恒为首轮证据）；末轮 Brief.tools 物理收口为空；
    同参重复调用不触发执行器。仅「真模型 + 带工具 + 给了执行器」时启用；
    无 tools 的既有路径逐字不变（上面全例钉着）。
    """

    TOOLS = ({"type": "function", "function": {"name": "query_series"}},)

    @staticmethod
    def _execute(seen, text="台账里没有查到这一项。", receipt="r1"):
        def run(call):
            seen.append(call)
            return text, receipt
        return run

    def test_发工具_执行_第二轮作答_回执进Outcome(self):
        seen = []
        brain = ScriptedBrain([
            Turn(calls=({"name": "query_series", "arguments": {"metric": "papers"}},)),
            lambda b: Turn(text="答：" + b.task)])
        out = _run(brain, task="问 3", tools=self.TOOLS,
                   execute=self._execute(seen), max_steps=2)
        assert seen == [{"name": "query_series", "arguments": {"metric": "papers"}}]
        assert out.text == "答：问 3" and out.reason is None
        assert out.receipts == ("r1",), "成功路径带回执行回执"
        b1, b2 = brain.briefs
        assert b1.step == 1 and b1.max_steps == 2 and b1.tools == self.TOOLS
        assert b1.history == (), "首轮无历史"
        assert b2.step == 2 and b2.evidence == (), \
            "工具结果不折进证据：evidence 恒为首轮证据"
        assert len(b2.history) == 2, "assistant(tool_calls) 一条 + role:tool 一条"
        asst, tool = b2.history
        assert asst["role"] == "assistant" and asst["content"] is None
        (tc,) = asst["tool_calls"]
        assert tc["id"] == "call_0" and tc["type"] == "function"
        assert tc["function"]["name"] == "query_series"
        assert json.loads(tc["function"]["arguments"]) == {"metric": "papers"}, \
            "arguments 为 JSON 串"
        assert tool["role"] == "tool" and tool["tool_call_id"] == tc["id"], "id 配对"
        assert tool["content"] == "台账里没有查到这一项。"
        assert out.egress["bytes"] == sum(b.egress_bytes() for b in brain.briefs), \
            "egress 按每轮 Brief 求和（history 已计入外发面）"
        assert out.egress["items"] == (1 + 0 + 1 + 0) + (1 + 0 + 0 + 1), \
            "首轮基面+工具 schema；次轮基面+历史（末轮 tools 已收口）"
        # 零数字断在内容面：history 序列化里含协议 id（call_<i> 合成/网关真 id 都含数字），
        # 那是协议管道不是数据值；工具结果与参数必须零数字。
        assert not raw_digits(tool["content"]) and not raw_digits(tc["function"]["arguments"])

    def test_规则部署_工具环物理不启用(self):
        seen = []

        def execute(call):
            seen.append(call)
            return "x", "r"

        out = _run(RuleBrain(), task="共 3 项", tools=self.TOOLS, execute=execute)
        assert out.attempted is False and out.text == "共 3 项"
        assert seen == [] and out.receipts == (), "规则适配器忽略 tools，执行器不被调"

    def test_执行器异常_回落带类型码(self):
        def execute(call):                                     # noqa: ARG001
            raise ValueError("坏了")
        out = _run(ScriptedBrain([Turn(calls=({"name": "x", "arguments": {}},))]),
                   tools=self.TOOLS, execute=execute, max_steps=2)
        assert out.text is None and out.reason == "brain_error:ValueError"
        assert "工具执行失败" in out.notice and "坏了" in out.notice

    def test_执行器返回裸数字_GUARD_REJECT_detail记工具名(self):
        out = _run(ScriptedBrain([Turn(calls=({"name": "query_x", "arguments": {}},))]),
                   tools=self.TOOLS, execute=self._execute([], text="涨了 5%"),
                   max_steps=2)
        assert out.text is None and out.reason == "guard_reject"
        assert out.detail["tool"] == "query_x" and out.detail["stray"] == ["5"]
        assert "数字校验" in out.notice

    def test_末轮仍calls_CALLS_UNSUPPORTED_回执不发布(self):
        calls = Turn(calls=({"name": "x", "arguments": {}},))
        seen = []
        brain = ScriptedBrain([calls, calls])
        out = _run(brain, tools=self.TOOLS,
                   execute=self._execute(seen), max_steps=2)
        assert out.reason == "calls_unsupported" and "连续请求工具未作答" in out.notice
        assert len(seen) == 1, "第一轮的调用执行过"
        assert out.receipts == (), "回落路径不发布回执"
        assert brain.briefs[1].tools == (), "末轮 Brief.tools 物理收口为空"
        assert brain.briefs[1].evidence == (), "结果不进证据"
        assert len(brain.briefs[1].history) == 2, "首轮的 assistant+tool 消息已进 history"

    def test_带mapping_执行器续号_边界认新标记(self):
        """真实 wiring 的关键：执行器侧 `NumberedText.append` 把新 k 写进**同一张 mapping**
        （dict 原地生长），边界校验用的就是它——新标记不算未知。"""
        mapping = {"1": "3"}
        seen = []

        def execute(call):
            seen.append(call)
            mapping["2"] = "42"                    # 模拟 NumberedText.append 的原地续号
            return "查得 [[2]] 项。", "r"

        protected = _shield.protect_chunks(["问 3"])[0][0]
        brain = ScriptedBrain([
            Turn(calls=({"name": "query_series", "arguments": {}},)),
            lambda b: Turn(text="答 " + b.task + " 查得 [[2]] 项。")])
        with ai.using(brain=brain):
            out = _attempt.attempt(protected, system="s", ability="diagnose",
                                   mapping=mapping, anchored=False,
                                   tools=self.TOOLS, execute=execute, max_steps=2)
        assert out.text == "答 问 3 查得 42 项。", "工具结果的编号被还原"
        assert out.receipts == ("r",)
        assert tool_texts(brain.briefs[1])[-1] == "查得 [[2]] 项。", \
            "续号后的占位面住在工具消息里"

    def test_重复同参调用_第二次不触发执行器_工具消息回去重句(self):
        seen = []
        call = {"name": "query_at", "arguments": {"metric": "thr", "disc": "Physics"}}
        brain = ScriptedBrain([
            Turn(calls=(call,)),
            Turn(calls=(call,)),
            lambda b: Turn(text="答：" + b.task)])
        out = _run(brain, task="问 3", tools=self.TOOLS,
                   execute=self._execute(seen), max_steps=3)
        assert seen == [call], "同参第二次不再触发执行器"
        assert out.text == "答：问 3" and out.reason is None
        assert out.receipts == ("r1",), "去重不产生回执"
        t1, t2 = tool_texts(brain.briefs[2])[-2:]
        assert t1 == "台账里没有查到这一项。"
        assert t2 == ("（该查询已执行过，参数完全相同；结果见上面的同名工具消息。"
                      "请依据已有结果作答，不要再调用工具。）"), "去重句进 history"
        assert not raw_digits(t1) and not raw_digits(t2), "结果与去重句零数字"

    def test_同轮内重复同参_同样只执行一次(self):
        seen = []
        call = {"name": "query_at", "arguments": {"metric": "thr"}}
        brain = ScriptedBrain([
            Turn(calls=(call, call)),
            lambda b: Turn(text="答：" + b.task)])
        out = _run(brain, task="问 3", tools=self.TOOLS,
                   execute=self._execute(seen), max_steps=2)
        assert seen == [call], "同轮同参第二次不执行"
        assert out.receipts == ("r1",)
        asst, t1, t2 = brain.briefs[1].history
        assert len(asst["tool_calls"]) == 2, "assistant 消息照实带两个 tool_calls"
        assert t1["content"] == "台账里没有查到这一项。"
        assert "已执行过" in t2["content"]
        assert t2["tool_call_id"] != t1["tool_call_id"], "两条 tool 消息各配各的 id"

    def test_calls缺id_合成id并配对(self):
        seen = []
        brain = ScriptedBrain([
            Turn(calls=({"name": "x", "arguments": {}},
                        {"name": "y", "arguments": {}})),
            lambda b: Turn(text="答：" + b.task)])
        out = _run(brain, task="问 3", tools=self.TOOLS,
                   execute=self._execute(seen), max_steps=2)
        assert out.reason is None and len(seen) == 2
        asst, t1, t2 = brain.briefs[1].history
        ids = [tc["id"] for tc in asst["tool_calls"]]
        assert ids == ["call_0", "call_1"], "calls 缺 id 时按序号合成"
        assert [t1["tool_call_id"], t2["tool_call_id"]] == ids, "tool 消息同 id 配对"
