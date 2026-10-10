# -*- coding: utf-8 -*-
"""对话前门（票 01/02）：期次识别 + 盘点（缝 S1，穿过 `src/ai` 能力口）。

外部行为：说一句话 → 应答里**先说出理解**（数据截至 2026-09 → 期次 202609）；
盘点四件（监测表 / ESI 原始包 / 顶尖论文清单 / InCites 快照）→ 缺就停 + 两条路、
齐就给「去核对」；每轮进 `ai_calls`（Recorder）；非 admin 不可用；**不触网**
（对话能力不做模型轮——注入的替身一次都不该被调用）。

盘点在本层经 `using(inventory=…)` 注入替身（真实现在 `src/inventory.py`，
S2 契约级验证）；今天可注入 `payload["today"]`，测试与挂钟无关。
"""
from __future__ import annotations

import json

import pytest

import ai
from _ai_helpers import ScriptedBrain

TODAY = "2026-10-10"

_LABELS = (("monitor", "监测表"), ("esi", "ESI 原始包"),
           ("papers", "顶尖论文清单"), ("incites", "InCites 快照"))


class _Bomb:
    """被调用即炸的 brain：证明对话能力零外发。"""

    name = "bomb"
    is_rule = False

    def think(self, brief):                                       # noqa: ARG002
        raise AssertionError("对话前门不该触网/问模型")


def fake_inventory(period, *, released=True, missing=(), fallback=""):
    pieces = [{"key": k, "label": lb,
               "state": "missing" if k in missing else "ok",
               "note": "未到（随发布）" if (k in missing and not released) else ""}
              for k, lb in _LABELS]
    return {"period": period, "released": released, "pieces": pieces,
            "n_pieces": len(pieces), "n_missing": len(missing), "fallback": fallback}


FULL_202607 = fake_inventory("202607")


def run_dialog(text, *, root, period="", actor="admin", today=TODAY, inventory=None, **ov):
    """`inventory=None` → 注入「没有盘点」的替身（票 01 行为；绝不读真台账）。"""
    with ai.using(data_root=root, inventory=(lambda _p: inventory), **ov):
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
    assert ans.data["case"] == "period" and ans.data["period"] == "202609"
    assert ans.data["intent"] == "出报告"
    assert ans.data["verdict"] == "" and ans.data["inventory"] is None
    assert ans.data["actions"] == []


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


# ============================================================ 3. 盘点（票 02）
def test_盘点未发布_停下给两条路(tmp_path):
    inv = fake_inventory("202609", released=False,
                         missing=("papers", "incites"), fallback="202607")
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, inventory=inv)
    assert "盘点 · 202609（必需件 4 件）" in ans.text
    assert "✗ 顶尖论文清单 · 缺" in ans.text and "✗ InCites 快照 · 缺" in ans.text
    assert "这一期数据还没到" in ans.text and "2 件没到" in ans.text
    assert "202607（数据截至 2026-07）" in ans.text
    assert ans.data["verdict"] == "unpublished"
    assert ans.data["actions"] == [{"kind": "send", "text": "改做 202607 的"},
                                   {"kind": "dismiss", "text": "先等等"}]
    got = ans.data["inventory"]
    assert got["released"] is False and got["n_missing"] == 2 and got["fallback"] == "202607"


def test_盘点已发布缺件_停下并给补件入口(tmp_path):
    inv = fake_inventory("202609", released=True, missing=("papers",), fallback="202607")
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, inventory=inv)
    assert "还差 1 件" in ans.text
    assert ans.data["verdict"] == "missing"
    assert {"kind": "goto", "view": "acquire", "period": "202609",
            "text": "去取数台 ▸"} in ans.data["actions"]
    assert {"kind": "send", "text": "改做 202607 的"} in ans.data["actions"]


def test_盘点四件齐_给去核对(tmp_path):
    ans = run_dialog("做 7 月的报告", root=tmp_path, inventory=FULL_202607)
    assert "✓ 监测表 · 已有" in ans.text and "✓ InCites 快照 · 已有" in ans.text
    assert "数据齐" in ans.text and "去核对" in ans.text
    assert ans.data["verdict"] == "ready"
    assert ans.data["actions"] == [{"kind": "goto", "view": "acquire", "period": "202607",
                                    "text": "去核对 ▸"}]


def test_盘点应答不露文件路径(tmp_path):
    for inv in (fake_inventory("202609", released=False,
                               missing=("papers", "incites"), fallback="202607"),
                fake_inventory("202609", released=True, missing=("papers",), fallback="202607"),
                FULL_202607):
        text = run_dialog("帮我做9月份的报告", root=tmp_path, inventory=inv).text
        for leak in ("input/", ".xlsx", ".csv", "数据与复现"):
            assert leak not in text, f"界面不露技术路径：{leak}"


def test_改做那期_按新的期次盘点(tmp_path):
    seen = {}

    def pick(period):
        seen["period"] = period
        return fake_inventory(period, released=True)

    with ai.using(data_root=tmp_path, inventory=pick):
        ans = ai.run("dialog", "202609", payload={"text": "改做 202607 的", "today": TODAY},
                     actor="admin")
    assert seen["period"] == "202607", "盘点按这句话解析出的期次来（不是槽位旧期次）"
    assert ans.data["period"] == "202607" and ans.data["verdict"] == "ready"
    assert "202607" in ans.text


# ============================================================ 3b. 核对门（票 03）
def test_核完了_核对通过_进入出稿(tmp_path):
    inv = fake_inventory("202607", released=True)
    ans = run_dialog("核完了，继续", root=tmp_path, period="202607", inventory=inv)
    assert "核对通过" in ans.text and "开始出稿" in ans.text
    assert ans.data["act"] == "proceed" and ans.data["verdict"] == "ready"
    assert ans.data["run"] == {"period": "202607", "auto": True}
    assert ans.data["actions"] == []


def test_未核对就出稿_拦住并指回核对(tmp_path):
    inv = fake_inventory("202611", released=False,
                         missing=("papers", "incites"), fallback="202607")
    ans = run_dialog("出稿", root=tmp_path, period="202611", inventory=inv)
    assert "先别出稿" in ans.text and "还没核对并并入" in ans.text
    assert ans.data["act"] == "proceed" and ans.data["run"] is None
    assert {"kind": "goto", "view": "acquire", "period": "202611",
            "text": "去核对 ▸"} in ans.data["actions"]
    assert {"kind": "send", "text": "改做 202607 的"} in ans.data["actions"]


def test_出稿缺件_也拦住(tmp_path):
    inv = fake_inventory("202609", released=True, missing=("papers",), fallback="202607")
    ans = run_dialog("出稿", root=tmp_path, period="202609", inventory=inv)
    assert "先别出稿" in ans.text and ans.data["run"] is None


def test_出稿_产物已在_先问一次不自动跑(tmp_path):
    (tmp_path / "202607").mkdir()
    (tmp_path / "202607" / "red_slots.json").write_text("[]", encoding="utf-8")
    inv = fake_inventory("202607", released=True)
    ans = run_dialog("核完了，继续", root=tmp_path, period="202607", inventory=inv)
    assert "已经有产物" in ans.text and "覆盖" in ans.text
    assert ans.data["run"] == {"period": "202607", "auto": False}, \
        "产物已在：先问一次，绝不自动覆盖"
    assert {"kind": "run", "period": "202607", "text": "覆盖重出"} in ans.data["actions"]
    assert {"kind": "dismiss", "text": "保留，我先看看旧的"} in ans.data["actions"]


def test_没期次就出稿_先要期次(tmp_path):
    ans = run_dialog("出稿", root=tmp_path, period="", inventory=None)
    assert "还差一个期次" in ans.text
    assert ans.data["act"] == "proceed" and ans.data["run"] is None


# ============================================================ 4. 留痕（复用 Recorder）
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


# ============================================================ 5. 零外发 / 不触网
def test_替身注入不触网_对话不做模型轮(tmp_path):
    brain = ScriptedBrain([])
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, brain=brain)
    assert ans.mode == "rule" and ans.backend == "rule"
    assert brain.briefs == [], "对话能力 model=False：零外发"


def test_会炸的brain也照常_没配云零猜测(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, brain=_Bomb())
    assert ans.mode == "rule" and ans.data["period"] == "202609"


# ============================================================ 6. 权限与开关（既有门）
def test_非admin不可用(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, actor="guest")
    assert ans.mode == "denied" and "仅管理员" in ans.notice
    assert ans.text == "" and ans.data is None


def test_关闭即关(tmp_path):
    with ai.using(data_root=tmp_path):
        ai.set_switch("dialog", False, actor="admin")
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert ans.mode == "closed" and "关闭" in ans.notice


# ============================================================ 7. 来源（数字都有出处）
def test_应答里的数字逐条登记来源(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert ans.shield.checked == ans.shield.passed == len(ans.sources) > 0
    assert all(s.kind == "fact" and s.pointer.startswith("dialog/") for s in ans.sources)
    assert "202609" in [s.value for s in ans.sources]


def test_盘点应答的数字也有来源(tmp_path):
    inv = fake_inventory("202609", released=False,
                         missing=("papers", "incites"), fallback="202607")
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, inventory=inv)
    values = [s.value for s in ans.sources]
    assert "202607" in values and "4" in values and "2" in values


def test_坏today是编程错误_直接抛(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            ai.run("dialog", "", payload={"text": "做9月的报告", "today": "不是日期"},
                   actor="admin")
