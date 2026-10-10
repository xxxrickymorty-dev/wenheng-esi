# -*- coding: utf-8 -*-
"""对话前门 v1（票 01）：期次识别（缝 S1，穿过 `src/ai` 能力口）。

外部行为：说一句话 → 应答里**先说出理解**（数据截至 2026-09 → 期次 202609）、
句柄数据（`Answer.data`）给出本轮解析的期次/意图；每轮进 `ai_calls`（Recorder）；
非 admin 不可用；**不触网**——对话能力不做模型轮（注入的替身一次都不该被调用）。

今天可注入 `payload["today"]`（ISO 日期），测试与挂钟无关；HTTP 路由不传。
"""
from __future__ import annotations

import json

import pytest

import ai
from _ai_helpers import ScriptedBrain

TODAY = "2026-10-10"


class _Bomb:
    """被调用即炸的 brain：证明对话能力零外发。"""

    name = "bomb"
    is_rule = False

    def think(self, brief):                                       # noqa: ARG002
        raise AssertionError("对话前门不该触网/问模型")


def run_dialog(text, *, root, period="", actor="admin", today=TODAY, **ov):
    with ai.using(data_root=root, **ov):
        return ai.run("dialog", period, payload={"text": text, "today": today},
                      actor=actor)


def records(root, period):
    p = root / period / "ai_calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


# ============================================================ 1. 先说出理解 + 槽位
def test_九月报告_先说出理解_期次槽亮起(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert ans.mode == "rule" and ans.backend == "rule" and ans.notice == ""
    assert "数据截至 2026-09" in ans.text, "应答必须先说出理解（期次只有一个含义：数据截止月）"
    assert "202609" in ans.text
    assert ans.data == {"case": "period", "period": "202609", "intent": "出报告"}


def test_显式期次优先_再出那期(tmp_path):
    ans = run_dialog("再出 202605 的", root=tmp_path)
    assert ans.data["period"] == "202605"
    assert "数据截至 2026-05" in ans.text and "202605" in ans.text


def test_中文月份与带年份都认(tmp_path):
    assert run_dialog("帮我做九月份的报告", root=tmp_path).data["period"] == "202609"
    assert run_dialog("做2026年9月的报告", root=tmp_path).data["period"] == "202609"
    assert run_dialog("做 7 月的报告", root=tmp_path).data["period"] == "202607"


def test_解析确定性_同一句话两次同结果(tmp_path):
    a = run_dialog("帮我做9月份的报告", root=tmp_path)
    b = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert a.data == b.data and a.text == b.text


# ============================================================ 2. 出稿月不支持 / 没听出
def test_出稿月说法_停下纠正_不设期次(tmp_path):
    ans = run_dialog("做9月出稿的报告", root=tmp_path)
    assert ans.data["case"] == "publication_month" and ans.data["period"] == ""
    assert "出稿月" in ans.text and "不是期次说法" in ans.text
    assert "202609" in ans.text and "期次 ）" not in ans.text, \
        "纠正文案里的示例期次必须完整（不能是空括号）"


def test_没听出月份_反问不含期次(tmp_path):
    ans = run_dialog("你好", root=tmp_path)
    assert ans.data["case"] == "no_period" and ans.data["period"] == ""
    assert "没听出" in ans.text and "202609" not in ans.text


# ============================================================ 3. 留痕（复用 Recorder）
def test_每轮进ai_calls_记录落解析出的期次(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    recs = records(tmp_path, "202609")
    assert len(recs) == 1 and recs[0]["capability"] == "dialog"
    assert recs[0]["record_id"] == ans.record_id
    assert recs[0]["mode"] == "rule" and recs[0]["fallback"] is None
    assert "[[1]]" in recs[0]["question"] and "9" not in recs[0]["question"], \
        "问句记录面已占位（数字不出内网）"
    assert records(tmp_path, "_ai") == [], "期次已解析出，不落 _ai"


def test_没期次的轮次_记录落ai目录(tmp_path):
    run_dialog("你好", root=tmp_path)
    assert len(records(tmp_path, "_ai")) == 1
    assert not (tmp_path / "202609").exists()


def test_每轮对话各一条_不攒账(tmp_path):
    run_dialog("帮我做9月份的报告", root=tmp_path)
    run_dialog("再出 202605 的", root=tmp_path)
    assert len(records(tmp_path, "202609")) == 1
    assert len(records(tmp_path, "202605")) == 1


# ============================================================ 4. 零外发 / 不触网
def test_替身注入不触网_对话不做模型轮(tmp_path):
    brain = ScriptedBrain([])
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, brain=brain)
    assert ans.mode == "rule" and ans.backend == "rule"
    assert brain.briefs == [], "对话能力 model=False：零外发"


def test_会炸的brain也照常_没配云零猜测(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, brain=_Bomb())
    assert ans.mode == "rule" and ans.data["period"] == "202609"


# ============================================================ 5. 权限与开关（既有门）
def test_非admin不可用(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, actor="guest")
    assert ans.mode == "denied" and "仅管理员" in ans.notice
    assert ans.text == "" and ans.data is None


def test_关闭即关(tmp_path):
    with ai.using(data_root=tmp_path):
        ai.set_switch("dialog", False, actor="admin")
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert ans.mode == "closed" and "关闭" in ans.notice


# ============================================================ 6. 来源（数字都有出处）
def test_应答里的数字逐条登记来源(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert ans.shield.checked == ans.shield.passed == len(ans.sources) > 0
    assert all(s.kind == "fact" and s.pointer.startswith("dialog/") for s in ans.sources)
    assert "202609" in [s.value for s in ans.sources]


def test_坏today是编程错误_直接抛(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            ai.run("dialog", "", payload={"text": "做9月的报告", "today": "不是日期"},
                   actor="admin")
