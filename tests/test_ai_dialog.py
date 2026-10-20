# -*- coding: utf-8 -*-
"""对话前门（票 01/02）：期次识别 + 盘点（缝 S1，穿过 `src/ai` 能力口）。

外部行为：说一句话 → 应答里**先说出理解**（数据截至 2026-09 → 期次 202609）；
盘点四件（动态监测表 / ESI 原始包 / 顶尖论文清单 / InCites 快照）→ 缺就停 + 两条路、
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

_LABELS = (("monitor", "动态监测表"), ("esi", "ESI 原始包"),
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


def run_dialog(text, *, root, period="", actor="admin", today=TODAY, inventory=None,
               history=None, periods=None, **ov):
    """`inventory=None` → 注入「没有盘点」的替身（票 01 行为；绝不读真台账）。
    `history`＝对话上文（追问解指代用，2026-10-12）。
    `periods`＝服务端注入的已知期次（降序；「最新的」解析用，2026-10-13 票 10）。"""
    payload = {"text": text, "today": today, "history": history or []}
    if periods is not None:
        payload["periods"] = periods
    with ai.using(data_root=root, inventory=(lambda _p: inventory), **ov):
        return ai.run("dialog", period, payload=payload, actor=actor)


def records(root, period):
    p = root / period / "ai_calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


# ============================================================ 1. 先说出理解 + 槽位
def test_九月报告_先说出理解_期次槽亮起(tmp_path):
    ans = run_dialog("帮我做 9 月的报告", root=tmp_path)
    assert ans.mode == "rule" and ans.backend == "rule" and ans.notice == ""
    assert "数据截至 2026-09" in ans.text, "应答必须先说出理解（期次只有一个含义：数据截止月）"
    assert "202609" in ans.text
    assert ans.data["case"] == "period" and ans.data["period"] == "202609"
    assert ans.data["intent"] == "出报告"
    assert ans.data["verdict"] == "" and ans.data["inventory"] is None
    # 盘点不到（替身 None）→ 如实说 + 指路生成台（2026-10-11：不再只回一句理解）
    assert "看不到" in ans.text and ans.data["actions"][0]["view"] == "workbench"


def test_带期次槽位_怎么不做_不再反问期次(tmp_path):
    """2026-10-11 rick 实问：说过「9 月的报告」，再问「怎么不做」被反问「没听出是哪一期」。"""
    ans = run_dialog("怎么不做", root=tmp_path, period="202609")
    assert "我还没听出是哪一期" not in ans.text, "槽位期次带过轮：不反问"
    assert "接着 202609" in ans.text and ans.data["period"] == "202609"


def test_带期次槽位_短应诺_按推进走(tmp_path):
    """「对啊」这类短应诺 → 沿用槽位期次走推进，不再反问期次。"""
    ans = run_dialog("对啊", root=tmp_path, period="202609")
    assert "我还没听出是哪一期" not in ans.text
    assert ans.data["kind"] == "proceed"


def test_追问_有对话上文_当查数据走(tmp_path):
    """2026-10-12 rick 实问「这是几月的」：解析不出意图但有上文 → 当追问走 qa，
    不再回「我还没听出是哪一期」。"""
    history = [{"who": "me", "text": "查工程学的接近度，最新一期的"},
               {"who": "wh", "text": "工程学最新一期（2026 年第 5 期）的 ESI 前 1% 接近度为 746.57%…"}]
    ans = run_dialog("这是几月的", root=tmp_path, period="202609", history=history)
    assert ans.data["kind"] == "query"
    assert "我还没听出是哪一期" not in ans.text
    # 没有上文的同句仍按老规矩反问（首问不猜）
    first = run_dialog("这是几月的", root=tmp_path, period="202609")
    assert "我还没听出是哪一期" in first.text


def test_操作员报告意图_照常走盘点(tmp_path):
    """2026-10-12：出报告对操作员开放——报告意图与管理员同路（盘点照常，不再说「只读」）。"""
    inv = {"period": "202607", "released": True,
           "pieces": [{"key": k, "label": lb, "state": "ok", "note": ""} for k, lb in
                      (("monitor", "动态监测表"), ("esi", "ESI 原始包"),
                       ("papers", "顶尖论文清单"), ("incites", "InCites 快照"))],
           "n_pieces": 4, "n_missing": 0, "fallback": ""}
    ans = run_dialog("帮我做 7 月的报告", root=tmp_path, inventory=inv)
    assert "操作员只读" not in ans.text
    assert "盘点 · 202607" in ans.text and "数据齐" in ans.text
    assert ans.data["verdict"] == "ready"
    # 查数据不受影响（照旧路由）
    q = run_dialog("查一下化学的接近度", root=tmp_path, period="202607")
    assert q.data["kind"] == "query"


def test_已出过稿_先问覆盖不报缺件(tmp_path):
    """2026-10-11 rick 实问：9 月已出过稿——不报「还差几件」，先问一次覆盖。"""
    d = tmp_path / "202609"
    d.mkdir()
    (d / "red_slots.json").write_text("[]", encoding="utf-8")
    ans = run_dialog("帮我做 9 月的报告", root=tmp_path)
    assert "已经出过稿" in ans.text and "覆盖重出" in ans.text
    assert ans.data["run"] == {"period": "202609", "auto": False, "intent": "single_trend"}
    assert [a["text"] for a in ans.data["actions"]] == [
        "看这一期怎么做的", "打开报告", "覆盖重出", "保留，我先看看旧的"]
    assert ans.data["actions"][0] == {"kind": "goto", "view": "archive",
                                      "period": "202609", "text": "看这一期怎么做的"}


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


# ============================================================ 2b. 最新期次（票 10，2026-10-13）
PERIODS = ["202609", "202607", "202605"]


def test_最新的_带上文_落最近期次不再复读(tmp_path):
    """rick 截图实问：「查一下化学的接近度」→反问→「最新的」→复读同一句（死循环）。"""
    ans = run_dialog("最新的", root=tmp_path, periods=PERIODS,
                     history=[{"who": "me", "text": "查一下化学的接近度"}])
    assert ans.data["case"] == "period" and ans.data["period"] == "202609"
    assert ans.data["kind"] == "query"
    assert "查哪一期" not in ans.text, "不再复读反问"


def test_查最新一期_直接带期次(tmp_path):
    ans = run_dialog("查最新一期的化学接近度", root=tmp_path, periods=PERIODS)
    assert ans.data["kind"] == "query" and ans.data["period"] == "202609"


def test_做最新的报告_走报告路(tmp_path):
    inv = fake_inventory("202609", released=True)
    ans = run_dialog("做最新的报告", root=tmp_path, periods=PERIODS, inventory=inv)
    assert ans.data["period"] == "202609" and ans.data["verdict"] == "ready"
    assert "盘点 · 202609" in ans.text


def test_最新的_没表态_给两个出路(tmp_path):
    ans = run_dialog("最新的", root=tmp_path, periods=PERIODS)
    assert ans.data["kind"] == "unclear" and ans.data["period"] == "202609"
    texts = [a["text"] for a in ans.data["actions"]]
    assert "做 202609 的报告" in texts and "查 202609 的数据" in texts


def test_最新的_没期次列表_如实说不猜(tmp_path):
    ans = run_dialog("最新的", root=tmp_path)
    assert ans.data["case"] == "latest" and ans.data["period"] == ""
    assert "看不到" in ans.text and "查哪一期" not in ans.text


def test_最近六期_不进最新(tmp_path):
    """序列问法（最近六期 / 最近几期 / 最新的几期）不是「最新一期」——不触发 latest。"""
    for text in ("化学的接近度最近六期怎么变的", "最近几期化学的接近度", "最新的几期呢"):
        ans = run_dialog(text, root=tmp_path, periods=PERIODS,
                         history=[{"who": "me", "text": "查一下化学的接近度"}])
        assert ans.data["case"] == "no_period", text
        assert ans.data["period"] == "", text
    # 反问写明最近期次 + 候选（不再裸复读）
    ans = run_dialog("化学的接近度最近六期怎么变的", root=tmp_path, periods=PERIODS,
                     history=[{"who": "me", "text": "查一下化学的接近度"}])
    assert "最近有效期次是 202609" in ans.text
    assert {"kind": "send", "text": "查最新的"} in ans.data["actions"]


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


def test_盘点已发布缺件_直接放行给去核对(tmp_path):
    """2026-10-13 rick 定：已并入期次直接放行——原始件缺不缺不卡「补件」
    （部署演示环境没有 数据与复现/，评委流程不能被堵）。缺件照旧在盘点块里如实显示。"""
    inv = fake_inventory("202609", released=True, missing=("papers",), fallback="202607")
    ans = run_dialog("帮我做9月份的报告", root=tmp_path, inventory=inv)
    assert ans.data["verdict"] == "ready"
    assert "可以出稿" in ans.text and "✗ 顶尖论文清单 · 缺" in ans.text
    assert {"kind": "goto", "view": "acquire", "period": "202609",
            "text": "去核对 ▸"} in ans.data["actions"]
    assert {"kind": "send", "text": "核完了，继续"} in ans.data["actions"]


def test_盘点四件齐_给去核对(tmp_path):
    ans = run_dialog("做 7 月的报告", root=tmp_path, inventory=FULL_202607)
    assert "✓ 动态监测表 · 已有" in ans.text and "✓ InCites 快照 · 已有" in ans.text
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
    assert ans.data["run"] == {"period": "202607", "auto": True, "intent": "single_trend"}
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


def test_出稿缺件_已并入直接放行(tmp_path):
    """已并入期次缺原始件也放行（rick 2026-10-13 定）；「先别出稿」只留给未发布期次。"""
    inv = fake_inventory("202609", released=True, missing=("papers",), fallback="202607")
    ans = run_dialog("出稿", root=tmp_path, period="202609", inventory=inv)
    assert "核对通过" in ans.text and "开始出稿" in ans.text
    assert ans.data["run"] == {"period": "202609", "auto": True, "intent": "single_trend"}


def test_出稿_产物已在_先问一次不自动跑(tmp_path):
    (tmp_path / "202607").mkdir()
    (tmp_path / "202607" / "red_slots.json").write_text("[]", encoding="utf-8")
    inv = fake_inventory("202607", released=True)
    ans = run_dialog("核完了，继续", root=tmp_path, period="202607", inventory=inv)
    assert "已经有产物" in ans.text and "覆盖" in ans.text
    assert ans.data["run"] == {"period": "202607", "auto": False, "intent": "single_trend"}, \
        "产物已在：先问一次，绝不自动覆盖"
    assert {"kind": "goto", "view": "archive", "period": "202607",
            "text": "看这一期怎么做的"} in ans.data["actions"]
    assert {"kind": "goto", "view": "report", "period": "202607",
            "text": "打开报告"} in ans.data["actions"]
    assert {"kind": "run", "period": "202607", "text": "覆盖重出"} in ans.data["actions"]
    assert {"kind": "dismiss", "text": "保留，我先看看旧的"} in ans.data["actions"]


def test_没期次就出稿_先要期次(tmp_path):
    ans = run_dialog("出稿", root=tmp_path, period="", inventory=None)
    assert "还差一个期次" in ans.text
    assert ans.data["act"] == "proceed" and ans.data["run"] is None


# ============================================================ 3c. 两意图路由（票 07）
def test_路由_写报告(tmp_path):
    ans = run_dialog("帮我做9月份的报告", root=tmp_path)
    assert ans.data["kind"] == "report"


def test_路由_查数据_句中期次(tmp_path):
    ans = run_dialog("202607 数学进 1% 了吗", root=tmp_path)
    assert ans.data["kind"] == "query"
    assert ans.data["period"] == "202607"


def test_路由_查数据_期次从槽位来(tmp_path):
    ans = run_dialog("查一下化学的接近度", root=tmp_path, period="202607")
    assert ans.data["kind"] == "query"
    assert ans.data["verdict"] == "" and ans.data["inventory"] is None
    assert ans.data["run"] is None and ans.data["actions"] == []


def test_查数据不盘点_盘点只属于写报告链路(tmp_path):
    seen = []

    def pick(period):
        seen.append(period)
        return fake_inventory(period)

    with ai.using(data_root=tmp_path, inventory=pick):
        ans = ai.run("dialog", "202607",
                     payload={"text": "查一下化学的接近度", "today": TODAY}, actor="admin")
    assert ans.data["kind"] == "query"
    assert seen == [], "查数据不该触发盘点（件在不在是写报告链路的事）"


def test_路由_推进(tmp_path):
    inv = fake_inventory("202607", released=True)
    ans = run_dialog("核完了，继续", root=tmp_path, period="202607", inventory=inv)
    assert ans.data["kind"] == "proceed"


def test_路由_含糊_停下给两个选项(tmp_path):
    ans = run_dialog("看看 9 月", root=tmp_path)
    assert ans.data["kind"] == "unclear"
    assert ans.data["period"] == "202609"
    assert "拿不准" in ans.text and "202609" in ans.text
    texts = [a["text"] for a in ans.data["actions"]]
    assert "做 202609 的报告" in texts
    assert "查 202609 的数据" in texts
    assert {a["kind"] for a in ans.data["actions"]} == {"send", "dismiss"}


def test_路由_含糊_怎么样_不猜(tmp_path):
    ans = run_dialog("202607 怎么样", root=tmp_path)
    assert ans.data["kind"] == "unclear"
    assert ans.data["period"] == "202607"
    texts = [a["text"] for a in ans.data["actions"]]
    assert "做 202607 的报告" in texts and "查 202607 的数据" in texts


def test_路由_含糊不触发盘点与出稿(tmp_path):
    ans = run_dialog("看看 9 月", root=tmp_path, inventory=FULL_202607)
    assert ans.data["kind"] == "unclear"
    assert ans.data["verdict"] == "" and ans.data["inventory"] is None
    assert ans.data["run"] is None


def test_查数据_弱信号也算(tmp_path):
    ans = run_dialog("高被引论文有几篇", root=tmp_path, period="202607")
    assert ans.data["kind"] == "query"


def test_含糊_选项发回自己能再路由(tmp_path):
    """选项文本＝要点回去的那句话：点‘做…报告’回写报告、点‘查…数据’回查数据。"""
    q = run_dialog("看看 9 月", root=tmp_path)
    opt = {a["text"] for a in q.data["actions"]}
    report = run_dialog("做 202609 的报告", root=tmp_path)
    query = run_dialog("查 202609 的数据", root=tmp_path)
    assert "做 202609 的报告" in opt and report.data["kind"] == "report"
    assert "查 202609 的数据" in opt and query.data["kind"] == "query"


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


# ============================================================ 8. 内核缺席（票 03）：行为逐字不变
def test_内核缺席_指代句_照旧反问与候选(tmp_path):
    """无 key（内核不启）：「上上期呢」仍走原规则——反问写明最近期次 + 「查最新的」候选。"""
    ans = run_dialog("上上期呢", root=tmp_path, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的化学接近度"}])
    assert ans.data["case"] == "no_period" and ans.data["period"] == ""
    assert ans.data["kind"] == "query"
    assert "最近有效期次是 202609" in ans.text
    assert {"kind": "send", "text": "查最新的"} in ans.data["actions"]
    assert "kernel" not in ans.data, "未启用＝不留内核记录面"
    recs = records(tmp_path, "_ai")
    assert recs[0]["mode"] == "rule" and recs[0]["fallback"] is None


def test_内核缺席_报告指代句_照旧反问(tmp_path):
    ans = run_dialog("做上上期的报告", root=tmp_path, periods=PERIODS,
                     history=[{"who": "me", "text": "做 202609 的报告"}])
    assert "我还没听出是哪一期" in ans.text and ans.data["period"] == ""


def test_内核缺席_注入的brain一次都不问(tmp_path):
    """对话能力 modeled=False：即使注入非规则 brain，内核不启时也零外发（briefs 空）。"""
    brain = ScriptedBrain([])
    ans = run_dialog("上上期呢", root=tmp_path, brain=brain, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的化学接近度"}])
    assert brain.briefs == [], "内核不启＝零外发"
    assert ans.mode == "rule" and ans.backend == "rule"
    assert "kernel" not in ans.data
