# -*- coding: utf-8 -*-
"""review（复核参谋）构建器行为测试——票 09 / SPEC §2 自由作答型。

只穿过 `run`：风险序（待人工 → 校验未过 → 数据类红件）、来源指针、漏检提醒、
边界句（不代签不改稿）、模型轮外发零值/越题回落/盾拒。
"""
from __future__ import annotations

import json
import re

import pytest

import ai
from _ai_helpers import ScriptedBrain, Turn, raw_digits, seed_period

NUM = re.compile(r"\d+(?:\.\d+)?")


def review(tmp_path, *, brain=None, actor="admin", root=None):
    kw = {"data_root": root if root is not None else tmp_path}
    if brain is not None:
        kw["brain"] = brain
    with ai.using(**kw):
        return ai.run("review", "202607", actor=actor)


def records(tmp_path):
    p = tmp_path / "202607" / "ai_calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


# ============================================================ 规则清单
def test_规则清单_风险序_边界句_来源(tmp_path):
    seed_period(tmp_path)
    ans = review(tmp_path)
    assert ans.mode == "rule" and ans.backend == "rule" and ans.notice == ""
    t = ans.text
    for word in ("先看这几条", "待人工", "校验未过", "红件概览", "漏检提醒"):
        assert word in t, f"清单缺分段：{word}"
    assert "不会代签" in t and "不会改稿" in t, "边界句必须在（票 09 硬约束）"
    # 风险序：待人工在第一条
    assert t.index("【待人工】") < t.index("【大表（table2.csv）】") \
        if "【大表（table2.csv）】" in t else True
    assert t.index("【待人工】") < t.index("【台账/上游数据】")
    # 数字与来源一一对应
    nums = NUM.findall(t)
    assert nums and nums == [s.value for s in ans.sources]
    assert ans.shield.checked == ans.shield.passed == len(ans.sources)
    assert all(s.pointer.startswith(("red_slots.json", "meta.json")) for s in ans.sources)
    rec = records(tmp_path)[0]
    assert rec["capability"] == "review" and rec["mode"] == "rule"
    assert not raw_digits(rec["text_preview"])


def test_校验未过进清单且排前(tmp_path):
    meta = {"period_current": "202607", "period_prev": "202605",
            "assertions": [["PASS", "ok"], ["FAIL", "宽表 total_cites 缺 Chemistry"]]}
    seed_period(tmp_path, meta=meta)
    ans = review(tmp_path)
    assert "【校验未过】宽表 total_cites 缺 Chemistry" in ans.text
    assert ans.text.index("【校验未过】") < ans.text.index("【台账/上游数据】")
    assert any(s.pointer == "meta.json#assertions" for s in ans.sources)


def test_无待人工无未过_照常出清单(tmp_path):
    red = [{"location": "T20/行01", "old": "1", "new": "2", "source": "table2.csv"}]
    meta = {"period_current": "202607", "period_prev": "202605",
            "assertions": [["PASS", "示例校验"]]}
    seed_period(tmp_path, meta=meta, facts=None)
    (tmp_path / "202607" / "red_slots.json").write_text(
        json.dumps(red, ensure_ascii=False), encoding="utf-8")
    ans = review(tmp_path)
    assert "本次没有待人工项。" in ans.text
    assert "全部通过" in ans.text
    assert ans.mode == "rule"


# ============================================================ 模型轮
def test_模型整理_外发零值_边界留存(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.evidence[0] + "\n\n整理完毕，请按上列核对。")])
    ans = review(tmp_path, brain=brain)
    assert ans.mode == "model" and "整理完毕" in ans.text
    brief = brain.briefs[0]
    assert "不是指令" in brief.system and "代签" in brief.system
    for t in brief.egress_texts():
        assert not raw_digits(t), f"外发含数字原值：{t!r}"
    assert records(tmp_path)[0]["mode"] == "model"


def test_越题_不引用清单回落(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text="建议直接签单。")])
    ans = review(tmp_path, brain=brain)
    assert ans.mode == "rule" and ans.text == ans.rule_text
    assert records(tmp_path)[0]["fallback"] == "off_topic"


def test_盾拒_游离数字回落(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.evidence[0] + " 另见 7 处。")])
    ans = review(tmp_path, brain=brain)
    assert ans.mode == "rule" and "数字校验" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "shield_reject"


# ============================================================ 边界与门
def test_无数据_unavailable(tmp_path):
    ans = review(tmp_path)
    assert ans.mode == "unavailable" and "复核建议" in ans.notice
    assert records(tmp_path)[0]["mode"] == "unavailable"


def test_空期次抛与guest被拒(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            ai.run("review", "")
    seed_period(tmp_path)
    brain = ScriptedBrain([])
    ans = review(tmp_path, brain=brain, actor="guest")
    assert ans.mode == "denied" and brain.briefs == []
