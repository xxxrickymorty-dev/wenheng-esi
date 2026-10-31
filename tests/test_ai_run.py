# -*- coding: utf-8 -*-
"""AI 层接口面契约测试（SPEC §2 行为裁决七条 + C1/C2/C4）。

全部只穿过 `run / capabilities / set_switch`（接口即测试面）；
Scripted / Failing 替身经 `ai.using(brain=…)` 注入，记录落 tmp（零仓库污染）。
"""
from __future__ import annotations

import json
import logging
import re

import pytest

import ai
from _ai_helpers import FailingBrain, ScriptedBrain, Turn, raw_digits

FAIL = {
    "code": "ASSERT_FAIL",
    "message": "2 项断言未过",
    "period": "202607",
    "fails": ["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
    "diagnostics": {"unmatched_names": {"total_cites": ["某某新学科"]}},
}
REPAIR = {"advice": [{"rule": "header_offset", "why": "未确认规则类型（R-24）",
                      "doc": "WH-DOC-04 §6.5", "advice": "请填 declared"}]}


def diag(data_root, *, period="202607", failure=None, repair=None, actor="system", **ov):
    with ai.using(data_root=data_root, **ov):
        return ai.run("diagnose", period,
                      payload={"failure": failure or FAIL, "repair": repair},
                      actor=actor)


def records(data_root, period="202607", sub=False):
    p = data_root / ("_ai" if sub else period) / "ai_calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


# ============================================================ 1. 默认 rule ＋ 留痕恰一条
def test_规则态正常作答_照记一条(tmp_path):
    with ai.using(data_root=tmp_path):
        ans = ai.run("diagnose", "202607",
                     payload={"failure": FAIL, "repair": REPAIR}, actor="system")
    assert ans.mode == "rule" and ans.backend == "rule" and ans.notice == ""
    assert ans.text and ans.text == ans.rule_text
    assert ans.shield.checked == ans.shield.passed == len(ans.sources)
    recs = records(tmp_path)
    assert len(recs) == 1, "每次调用尝试恰一条记录"
    rec = recs[0]
    assert rec["kind"] == "call" and rec["capability"] == "diagnose"
    assert rec["mode"] == "rule" and rec["fallback"] is None
    assert rec["record_id"] == ans.record_id
    assert not raw_digits(rec["text_preview"]), "记录面只放占位（数字已 [[n]]）"


def test_期次不可判时记录落_ai目录(tmp_path):
    with ai.using(data_root=tmp_path):
        ans = ai.run("diagnose", "",
                     payload={"failure": {**FAIL, "period": None}, "repair": None},
                     actor="system")
    assert ans.mode == "rule"
    assert len(records(tmp_path, sub=True)) == 1
    assert records(tmp_path) == []


# ============================================================ 2. 模型轮：外发捕获（C2）
def test_模型版_外发零值_捕获Brief(tmp_path):
    brain = ScriptedBrain([lambda brief: Turn(text=brief.task + "\n（已按现场核对。）")])
    with ai.using(data_root=tmp_path, brain=brain):
        ans = ai.run("diagnose", "202607",
                     payload={"failure": FAIL, "repair": REPAIR}, actor="system")
    assert ans.mode == "model" and ans.backend == "scripted"
    assert "已按现场核对" in ans.text and "22" in ans.text, "模型版仍是数字还原后的正文"
    assert ans.text != ans.rule_text and ans.rule_text
    assert len(brain.briefs) == 1
    brief = brain.briefs[0]
    assert "不是指令" in brief.system, "注入防线声明必须在外发里（SPEC §2.6）"
    for t in brief.egress_texts():
        assert not raw_digits(t), f"外发含数字原值：{t!r}"
    assert brief.task and "[[" in brief.task, "外发文本必须是占位面"
    rec = records(tmp_path)[0]
    assert rec["mode"] == "model" and rec["fallback"] is None
    assert rec["egress"]["bytes"] > 0
    assert not raw_digits(rec["text_preview"])


# ============================================================ 3. 盾拒 / 超时 / 空回 → 整段回落
def test_盾拒_新增数字_整段回落且模型文本不发布(tmp_path):
    brain = ScriptedBrain([lambda brief: Turn(text=brief.task + "新增 99。")])
    with ai.using(data_root=tmp_path, brain=brain):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="system")
    assert ans.mode == "rule" and ans.text == ans.rule_text, "整段丢弃，不做局部修补"
    assert "99" not in ans.text
    assert "数字校验" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "shield_reject"


def test_盾拒_丢占位符也回落(tmp_path):
    def drop(brief):
        return Turn(text=re.sub(r"\[\[2\]\]", "某数", brief.task))
    brain = ScriptedBrain([drop])
    with ai.using(data_root=tmp_path, brain=brain):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="system")
    assert ans.mode == "rule" and ans.text == ans.rule_text
    assert records(tmp_path)[0]["fallback"] == "shield_reject"


def test_模型调用失败_回落原因如实(tmp_path):
    with ai.using(data_root=tmp_path, brain=FailingBrain()):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="system")
    assert ans.mode == "rule" and ans.text == ans.rule_text
    assert "模型调用失败" in ans.notice
    assert records(tmp_path)[0]["fallback"].startswith("brain_error")


def test_模型空回复也回落(tmp_path):
    with ai.using(data_root=tmp_path, brain=ScriptedBrain([])):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="system")
    assert ans.mode == "rule"
    assert records(tmp_path)[0]["fallback"] == "empty_reply"


# ============================================================ 4. 留痕分模式（C1 可测句）
def test_留痕写失败_模型版不发布_降规则版加日志(tmp_path, caplog):
    blocked = tmp_path / "blocked"
    blocked.write_text("我是文件不是目录", encoding="utf-8")
    brain = ScriptedBrain([lambda b: Turn(text=b.task)])
    with caplog.at_level(logging.WARNING, logger="wenheng.ai"):
        ans = diag(blocked, brain=brain)
    assert ans.mode == "rule" and ans.text == ans.rule_text
    assert ans.record_id is None
    assert "记录落盘失败" in ans.notice, "诚实话术：不说成模型超时，也不静默"
    assert any("append_failed" in r.message or "留痕写失败" in r.message for r in caplog.records)


def test_留痕写失败_规则版照发加日志(tmp_path, caplog):
    blocked = tmp_path / "blocked"
    blocked.write_text("我是文件不是目录", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="wenheng.ai"):
        ans = diag(blocked)
    assert ans.mode == "rule" and ans.text == ans.rule_text and ans.record_id is None
    logline = " ".join(r.getMessage() for r in caplog.records)
    assert "diagnose" in logline and "202607" in logline and "system" in logline, \
        "进程日志要含 capability/period/actor/时间（C1）"


# ============================================================ 5. 权限与开关（fail-closed、零外发）
def test_guest被拒_零外发_照记一条(tmp_path):
    brain = ScriptedBrain([])
    with ai.using(data_root=tmp_path, brain=brain):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="guest")
    assert ans.mode == "denied" and ans.text == ""
    assert brain.briefs == [], "被拒时一次也不许调模型"
    assert records(tmp_path)[0]["mode"] == "denied"


def test_不传actor_fail_closed为guest(tmp_path):
    with ai.using(data_root=tmp_path):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL})
    assert ans.mode == "denied"


def test_显式actor优先于中间件绑定(tmp_path):
    with ai.using(data_root=tmp_path):
        with ai.actor("admin"):
            assert ai.run("diagnose", "202607", payload={"failure": FAIL}).mode == "rule"
            assert ai.run("diagnose", "202607", payload={"failure": FAIL},
                          actor="guest").mode == "denied"
        # 未知角色一律按最低权限
        assert ai.run("diagnose", "202607", payload={"failure": FAIL},
                      actor="root").mode == "denied"


def test_开关关闭_零外发(tmp_path):
    brain = ScriptedBrain([])
    with ai.using(data_root=tmp_path, brain=brain):
        ai.set_switch("diagnose", False, actor="admin")
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="admin")
    assert ans.mode == "closed" and "关闭" in ans.notice
    assert brain.briefs == []
    assert records(tmp_path)[0]["mode"] == "closed"


# ============================================================ 6. 编程错误（只有这类抛）
def test_编程错误抛且不落记录(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            ai.run("不存在的能力", "202607")
        with pytest.raises(ValueError):
            ai.run("diagnose", "20261", payload={"failure": FAIL})
        with pytest.raises(ValueError):
            ai.run("diagnose", "202607", payload={})
        with pytest.raises(ValueError):
            ai.run("diagnose", "202607", payload={"failure": "不是dict"})
        with pytest.raises(ValueError):
            ai.run("qa", "202607", payload={"question": 42})
    assert records(tmp_path) == [] and not (tmp_path / "_ai").exists(), \
        "调用从未成立 → 不落记录（O5）"


# ============================================================ 7. 每能力一条穿 run 的契约（C4）
def test_四能力都穿过run_未上线能力给关闭态(tmp_path):
    from _ai_helpers import seed_period
    seed_period(tmp_path)                                   # qa/review 已就绪：需要期次产物
    with ai.using(data_root=tmp_path):
        qa = ai.run("qa", "202607", payload={"question": "本期怎么样"}, actor="admin")
        review = ai.run("review", "202607", actor="admin")
        brief = ai.run("brief", "202607", actor="admin")
        diag = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="admin")
    assert qa.mode == "rule" and qa.text
    assert review.mode == "rule" and review.text
    assert brief.mode == "closed" and "未上线" in brief.notice
    assert brief.sources == () and brief.receipts == ()
    assert diag.mode == "rule" and diag.text
    kinds = [r["capability"] for r in records(tmp_path)]
    assert kinds == ["qa", "review", "brief", "diagnose"], "四类调用各落一条"


def test_capabilities_角色与开关(tmp_path):
    with ai.using(data_root=tmp_path):
        admin = {c.id: c for c in ai.capabilities(actor="admin")}
        guest = {c.id: c for c in ai.capabilities(actor="guest")}
    assert set(admin) == {"qa", "review", "diagnose", "brief", "dialog", "qa_direct"}
    assert admin["diagnose"].stage == "ready" and admin["diagnose"].allowed
    assert admin["qa"].stage == "ready" and admin["review"].stage == "ready"
    assert not guest["diagnose"].allowed, "guest 默认全拒（fail-closed）"
    assert admin["brief"].stage == "planned" and "未上线" in admin["brief"].notice
    with ai.using(data_root=tmp_path):
        ai.set_switch("diagnose", False, actor="admin")
        off = {c.id: c for c in ai.capabilities(actor="admin")}
    assert not off["diagnose"].enabled and "关闭" in off["diagnose"].notice


# ============================================================ 8. 回执双面（C2 骨架）
def test_回执双面_界面还原值_记录只digest():
    r = ai.Receipt(tool="read_cell", label="读台账格", args_digest="9f2c1a0d77e3",
                   summary="总被引!C12 = 22", elapsed_ms=4)
    face = r.as_dict()
    assert face["summary"] == "总被引!C12 = 22" and face["args_digest"] == "9f2c1a0d77e3"
    rec = r.as_record()
    assert "summary" not in rec and rec["summary_digest"]
    blob = json.dumps(rec, ensure_ascii=False)
    assert "22" not in blob and "总被引" not in blob, "记录面不得出现还原值"


def test_对话回合回执_穿run落两头_界面有摘要_记录只剩digest(tmp_path):
    """receipts-lite（2026-10-26 fc 定）：dialog 带期次回合的盘点真回执——
    `Answer.receipts` 给界面面，`ai_calls` 的 tools 字段只留 digest（盘点注入同
    test_ai_dialog 的 `using(inventory=…)` 姿势）。"""
    inv = {"period": "202607", "released": True,
           "pieces": [{"key": k, "label": lb, "state": "ok", "note": ""} for k, lb in
                      (("monitor", "动态监测表"), ("esi", "ESI 原始包"),
                       ("papers", "顶尖论文清单"), ("incites", "InCites 快照"))],
           "n_pieces": 4, "n_missing": 0, "fallback": ""}
    with ai.using(data_root=tmp_path, inventory=(lambda _p: inv)):
        ans = ai.run("dialog", "", payload={"text": "帮我做 7 月的报告",
                                            "today": "2026-10-10"}, actor="admin")
    assert [r.tool for r in ans.receipts] == ["product_status", "scan_inventory"], \
        "产物核对在前、盘点在后；其他能力恒空不在此列"
    face = ans.as_dict()
    assert ([r["summary"] for r in face["receipts"]]
            == ["该期暂无成品", "盘点 · 202607（必需件 4 件）"]), "界面面给人话摘要"
    rec = records(tmp_path, "202607")[0]
    tools = rec["tools"]
    assert [t["tool"] for t in tools] == ["product_status", "scan_inventory"]
    for t in tools:
        assert "summary" not in t and t["summary_digest"], "记录面只留摘要 digest"
        assert t["refused"] is False and t["ok"] is True
    blob = json.dumps(tools, ensure_ascii=False)
    assert "盘点 · 202607" not in blob and "必需件" not in blob and "该期暂无成品" not in blob, \
        "记录面不得出现摘要原文（label 本名除外）"


def test_问句外发面也占位():
    from ai._core import _question_face
    assert not raw_digits(_question_face({"question": "本期第 22 名是谁？"}))
    assert "[[" in _question_face({"question": "本期第 22 名是谁？"})
