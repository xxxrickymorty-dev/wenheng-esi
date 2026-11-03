# -*- coding: utf-8 -*-
"""qa 金问集评测的**纯逻辑**单测（票 A）：schema 校验 / 期望值运行时解值 / judge 判定。

真网关评测是手动工具（见 `tools/qa_eval.py` docstring——按例计费，不进 pytest 收集）；
这里只测不触网的部分：金问集文件本身的合法性、假 view / 假 Answer 走 resolve 与 judge。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import qa_eval

CASES = json.loads(pathlib.Path(qa_eval.CASES_PATH).read_text(encoding="utf-8"))


class FakeView:
    """`LedgerView` 最小替身：只够 `queries.at` 走通（不触真台账）。"""

    disciplines = ["Chemistry", "Physics"]
    periods = ["202605", "202607", "202609"]

    def at(self, metric, disc, period):                        # noqa: ARG002
        return {"proximity_1pct": 6.760561, "papers": 2590.0,
                "rank_intl": 552.0}.get(metric)

    def chain(self, metric, disc, period):
        return {"origin_sheet": "接近度", "discipline": disc,
                "discipline_cn": "化学", "period": period}


def _case(**kw):
    base = {"id": "t1", "group": "g", "question": "化学的接近度是多少", "period": "202609",
            "expect": {"values": [{"metric": "proximity", "disc": "Chemistry"}]}}
    base.update(kw)
    return base


def _answer(mode="model", text="", receipts=()):
    return SimpleNamespace(mode=mode, text=text, receipts=receipts)


# ================================================================ schema 校验
class TestSchema:
    def test_真实金问集合法(self):
        assert qa_eval.validate_cases(CASES) == []

    def test_缺字段_坏期次_坏expect都被指出(self):
        bad = [{"id": "", "group": "", "question": "  ", "period": "abc", "expect": []}]
        errs = qa_eval.validate_cases(bad)
        assert any("缺 id" in e for e in errs)
        assert any("period" in e for e in errs)
        assert any("expect" in e for e in errs)
        assert any("缺 question" in e for e in errs)

    def test_例数越界与组不足两例(self):
        few = [_case(id="c0", group="甲"), _case(id="c1", group="乙")]
        errs = qa_eval.validate_cases(few)
        assert any("不足 2 例" in e for e in errs)
        assert any("例数 40" in e for e in qa_eval.validate_cases(few * 20))

    def test_未知指标别名与未知工具被指出(self):
        bad = _case(expect={"values": [{"metric": "h_index", "disc": "Chemistry"}],
                             "ops": ["drop_table"]})
        errs = qa_eval.validate_cases([bad] * 25)
        assert any("MODEL_METRICS" in e for e in errs)
        assert any("ops" in e for e in errs)

    def test_history形状校验(self):
        bad = _case(history=[{"who": "robot", "text": "…"}], expect={})
        errs = qa_eval.validate_cases([bad] * 25)
        assert any("history" in e for e in errs)
        good = _case(history=[{"who": "me", "text": "化学的接近度是多少"}],
                     expect={})
        ok = [good] + [_case(id=f"o{i}", expect={}) for i in range(24)]
        assert qa_eval.validate_cases(ok) == []


# ================================================================ 运行时解值
class TestResolve:
    def test_别名解值_格式化与证据同口径(self):
        rows = qa_eval.resolve_values(FakeView(), _case())
        assert rows == [{"metric": "proximity", "disc": "Chemistry", "period": "202609",
                         "want": "676.06", "why": ""}], "接近度＝比值×100 两位小数"

    def test_整数指标不带千分位(self):
        case = _case(expect={"values": [{"metric": "papers", "disc": "Chemistry"}]})
        (row,) = qa_eval.resolve_values(FakeView(), case)
        assert row["want"] == "2590"

    def test_排名指标整数面_与证据渲染同口径(self):
        case = _case(expect={"values": [{"metric": "rank_intl", "disc": "Chemistry"}]})
        (row,) = qa_eval.resolve_values(FakeView(), case)
        assert row["want"] == "552", "排名是整数面（第 552 位），不是 552.00"

    def test_点名期次优先于case期次(self):
        case = _case(expect={"values": [{"metric": "papers", "disc": "Chemistry",
                                          "period": "202605"}]})
        (row,) = qa_eval.resolve_values(FakeView(), case)
        assert row["period"] == "202605" and row["want"] == "2590"

    def test_缺数_want为None并注明(self):
        class Empty(FakeView):
            def at(self, metric, disc, period):                # noqa: ARG002
                return None

        case = _case(expect={"values": [{"metric": "papers", "disc": "Chemistry"}]})
        (row,) = qa_eval.resolve_values(Empty(), case)
        assert row["want"] is None and row["why"]

    def test_越权学科_查询被拒_want为None并注明(self):
        case = _case(expect={"values": [{"metric": "papers", "disc": "Astronomy"}]})
        (row,) = qa_eval.resolve_values(FakeView(), case)
        assert row["want"] is None and "QueryError" in row["why"]


# ================================================================ judge 判定
class TestJudge:
    def test_值含_mode对_即过(self):
        rows = qa_eval.resolve_values(FakeView(), _case())
        ok, reasons = qa_eval.judge(_case(), _answer(text="化学的接近度为 676.06%。"), rows)
        assert ok and reasons == []

    def test_值缺失_计FAIL并注明(self):
        rows = qa_eval.resolve_values(FakeView(), _case())
        ok, reasons = qa_eval.judge(_case(), _answer(text="答非所问。"), rows)
        assert not ok and any("676.06" in r for r in reasons)

    def test_mode不对_计FAIL(self):
        ok, reasons = qa_eval.judge(_case(expect={}), _answer(mode="failed"))
        assert not ok and any("failed" in r for r in reasons)

    def test_ops按回执工具名判_拒答回执也算(self):
        case = _case(expect={"ops": ["query_series"]})
        ok, _ = qa_eval.judge(case, _answer(
            receipts=[SimpleNamespace(tool="query_series", refused=True)]))
        assert ok, "越权学科的 refused 回执同样满足 ops"
        ok2, reasons2 = qa_eval.judge(case, _answer(receipts=[]))
        assert not ok2 and any("query_series" in r for r in reasons2)

    def test_解不出值_计FAIL并带原因(self):
        rows = [{"metric": "proximity", "disc": "Chemistry", "period": "202609",
                 "want": None, "why": "该期无数据"}]
        ok, reasons = qa_eval.judge(_case(), _answer(text="随便答的。"), rows)
        assert not ok and any("解不出" in r and "该期无数据" in r for r in reasons)
