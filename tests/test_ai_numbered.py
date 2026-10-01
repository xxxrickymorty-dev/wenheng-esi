# -*- coding: utf-8 -*-
"""NumberedText：编号 ↔ 来源不变量（红线 SPEC §2.1）的唯一实现。

直测不变量本身：同一遍编号+注册、发布次序取来源、重复引用、空发布面、
以及核心 FLOOR 分支（正文无数字 → 来源必须为空）。
"""
import ai
from ai import _attempt, _shield
from ai._brain import RuleBrain
from ai._numbered import NumberedText


def _reg(tag="事实", fact=True):
    def register(ti, pos, value):                            # noqa: ARG001
        return {"kind": "fact", "pointer": f"p{ti}", "label": tag,
                "detail": f"d{value}", "fact": fact}
    return register


class TestNumberedText:
    def test_编号与来源同遍对齐(self):
        nt = NumberedText.of(["共 3 项", "涨 2.5 个点"], _reg())
        assert nt.texts == ("共 [[1]] 项", "涨 [[2]] 个点")
        assert nt.mapping == {"1": "3", "2": "2.5"}
        assert [(s.index, s.value) for s in nt.sources] == [(1, "3"), (2, "2.5")]
        assert nt.protected == "共 [[1]] 项\n涨 [[2]] 个点"

    def test_事实键只收fact为真的段(self):
        def register(ti, pos, value):                        # noqa: ARG001
            return {"kind": "fact", "pointer": "q" if ti == 0 else "e", "fact": ti > 0}

        nt = NumberedText.of(["问 1 个", "答 2 个"], register)
        assert nt.fact_keys == frozenset({2})

    def test_发布次序取来源_重排不串(self):
        nt = NumberedText.of(["甲 1 乙 2"], _reg())
        used = nt.used_by("乙 [[2]] 甲 [[1]]")
        assert [s.value for s in used] == ["2", "1"]
        assert [s.index for s in used] == [1, 2]

    def test_重复引用重复登记(self):
        nt = NumberedText.of(["x 5"], _reg())
        used = nt.used_by("[[1]] 与再 [[1]]")
        assert [s.value for s in used] == ["5", "5"]

    def test_无标记发布_无来源(self):
        nt = NumberedText.of(["x 5"], _reg())
        assert nt.used_by("本次建议未通过数字校验，请直接打开台账与规则库核对。") == ()

    def test_还原(self):
        nt = NumberedText.of(["共 3 项"], _reg())
        assert nt.restore("共 [[1]] 项") == "共 3 项"

    def test_validate锚定与自由(self):
        nt = NumberedText.of(["a 1 b 2"], _reg())
        ok, detail = nt.validate("a [[1]] b [[2]]")
        assert ok and detail["missing"] == [] and detail["unknown"] == []
        ok, detail = nt.validate("a [[1]]")                 # 锚定：缺一个
        assert not ok and detail["missing"] == ["2"]
        ok, _ = nt.validate("a [[1]]", anchored=False)      # 自由：允许子集
        assert ok

    def test_盾原语与分块同源(self):
        text = "甲 1 乙 2"
        p, m = _shield.protect(text)
        pieces, m2 = _shield.protect_chunks([text])
        assert (p, m) == (pieces[0], m2)


class Test核心地板:
    def test_地板分支_正文无数字则来源为空(self, tmp_path, monkeypatch):
        """规则文本过不了盾 → 发布无数字地板：sources=()、shield 0/0（旧实现记规则稿全过）。"""
        def fake_attempt(*_a, **_k):
            return _attempt.Outcome(attempted=False,
                                    reason=_attempt.FallbackReason.SHIELD_REJECT,
                                    notice="", egress={"items": 0, "bytes": 0})
        monkeypatch.setattr(_attempt, "attempt", fake_attempt)
        with ai.using(data_root=tmp_path, brain=RuleBrain()):
            ans = ai.run("diagnose", "202607", actor="admin",
                         payload={"failure": {"code": "ASSERT_FAIL", "message": "1 项断言未过",
                                              "period": "202607", "fails": []}})
        assert ans.text and "数字校验" in ans.text      # 地板文案
        assert ans.sources == () and ans.shield.checked == 0 and ans.shield.passed == 0
