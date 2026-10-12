# -*- coding: utf-8 -*-
"""对话前门（票 01/02）· S2 契约：`POST /api/dialog/turn`。

外部行为：一轮对话 = 答复字段面（Answer）+ 合并后的槽位 + 盘点
（`inventory` / `verdict` / `actions`）；只走 admin 门；空话 400；能力关闭 409；
参数/角色都原样交给 `ai.run`。盘点替身经 `ai.using(inventory=…)` 注入。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ai                                                       # noqa: E402
from server import app as app_module, config                    # noqa: E402

_LABELS = (("monitor", "监测表"), ("esi", "ESI 原始包"),
           ("papers", "顶尖论文清单"), ("incites", "InCites 快照"))


class _ReqJson:
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self._body = body or {}

    async def json(self):
        return self._body


def call(user, body):
    return asyncio.run(app_module.api_dialog_turn(_ReqJson(user, body)))


def fake_inventory(period, *, released=True, missing=(), fallback=""):
    pieces = [{"key": k, "label": lb,
               "state": "missing" if k in missing else "ok",
               "note": "未到（随发布）" if (k in missing and not released) else ""}
              for k, lb in _LABELS]
    return {"period": period, "released": released, "pieces": pieces,
            "n_pieces": len(pieces), "n_missing": len(missing), "fallback": fallback}


# ============================================================ 1. 一轮对话的字段面
def test_一轮对话_答复槽位与盘点都透出(tmp_path):
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "做 7 月的报告"})
    assert "数据截至 2026-07" in r["text"] and r["record_id"]
    assert r["slots"] == {"period": "202607", "intent": "出报告"}
    assert r["verdict"] == "ready"
    assert r["inventory"]["n_missing"] == 0 and r["inventory"]["released"] is True
    assert r["actions"] == [{"kind": "goto", "view": "acquire", "period": "202607",
                             "text": "去核对 ▸"}]


def test_参数与角色原样交给能力口(monkeypatch):
    from ai import _types
    fake = _types.Answer(mode="rule", backend="rule", text="…",
                         data={"case": "period", "period": "202605", "intent": ""})
    seen = {}

    def fake_run(cap, period, *, payload=None, actor=None):
        seen.update(cap=cap, period=period, payload=payload, actor=actor)
        return fake

    monkeypatch.setattr("ai.run", fake_run)
    r = call(config.ADMIN_USER, {"text": "再出 202605 的",
                                "slots": {"period": "202609", "intent": "出报告"}})
    assert r["slots"] == {"period": "202605", "intent": "出报告"}, "只改期次，意图不变"
    assert seen == {"cap": "dialog", "period": "202609",
                    "payload": {"text": "再出 202605 的"}, "actor": "admin"}
    assert r["verdict"] == "" and r["inventory"] is None and r["actions"] == []


def test_槽位合并_解析到才覆盖_其余不变(monkeypatch):
    from ai import _types
    fake = _types.Answer(mode="rule", backend="rule", text="…",
                         data={"case": "no_period", "period": "", "intent": ""})
    monkeypatch.setattr("ai.run", lambda *a, **k: fake)
    r = call(config.ADMIN_USER, {"text": "你好", "slots": {"period": "202609", "intent": ""}})
    assert r["slots"] == {"period": "202609", "intent": ""}, "没解析到就不动槽位"


def test_槽位期次非法形状_丢弃不猜(monkeypatch):
    from ai import _types
    seen = {}

    def fake_run(cap, period, *, payload=None, actor=None):
        seen["period"] = period
        return _types.Answer(mode="rule", backend="rule", text="…",
                             data={"case": "no_period", "period": "", "intent": ""})

    monkeypatch.setattr("ai.run", fake_run)
    r = call(config.ADMIN_USER, {"text": "你好", "slots": {"period": "2026-09"}})
    assert seen["period"] == "", "非法期次不进能力口"
    assert r["slots"] == {"period": "", "intent": ""}


# ============================================================ 2. 票 02：盘点走 API
def test_九月未发布_盘点与两条路从API出(tmp_path):
    inv = fake_inventory("202609", released=False,
                         missing=("papers", "incites"), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "帮我做9月份的报告"})
    assert r["slots"]["period"] == "202609"
    assert r["verdict"] == "unpublished"
    assert r["inventory"]["n_missing"] == 2 and r["inventory"]["n_pieces"] == 4
    assert {"kind": "send", "text": "改做 202607 的"} in r["actions"]
    assert "这一期数据还没到" in r["text"], "停下反问（不触发流水线——本路由无任何生成副作用）"


def test_改做202607的_槽位改期次其余不变(tmp_path):
    invs = {"202607": fake_inventory("202607", released=True)}
    with ai.using(data_root=tmp_path, inventory=lambda p: invs.get(p)):
        r = call(config.ADMIN_USER, {"text": "改做 202607 的",
                                    "slots": {"period": "202609", "intent": "出报告"}})
    assert r["slots"] == {"period": "202607", "intent": "出报告"}
    assert r["verdict"] == "ready"


def test_九月已发布缺件_给补件入口(tmp_path):
    inv = fake_inventory("202609", released=True, missing=("papers",), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "帮我做9月份的报告"})
    assert r["verdict"] == "missing"
    assert {"kind": "goto", "view": "acquire", "period": "202609",
            "text": "去取数台 ▸"} in r["actions"]


def test_响应不露文件路径(tmp_path):
    inv = fake_inventory("202609", released=False,
                         missing=("papers", "incites"), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "帮我做9月份的报告"})
    blob = json.dumps(r, ensure_ascii=False)
    for leak in ("input/", ".xlsx", ".csv", "数据与复现"):
        assert leak not in blob


def test_盘点不到_如实说并指路生成台(tmp_path):
    """替身盘点 None（如演示站没有台账）→ 有期次就如实说 + 指路生成台，不再只回一句理解。"""
    with ai.using(data_root=tmp_path, inventory=lambda p: None):
        r = call(config.ADMIN_USER, {"text": "帮我做 9 月的报告"})
    assert r["slots"]["period"] == "202609"
    assert r["verdict"] == "" and r["inventory"] is None
    assert "看不到" in r["text"] and r["actions"][0]["view"] == "workbench"


# ============================================================ 2b. 票 03：核对门
def test_核完了继续_进入出稿(tmp_path):
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "核完了，继续",
                                    "slots": {"period": "202607", "intent": "出报告"}})
    assert "核对通过" in r["text"] and "开始出稿" in r["text"]
    assert r["run"] == {"period": "202607", "auto": True, "intent": "single_trend"}
    assert r["slots"] == {"period": "202607", "intent": "出报告"}, "槽位不动"


def test_未核对就出稿_拦住并指回核对(tmp_path):
    inv = fake_inventory("202611", released=False,
                         missing=("papers", "incites"), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "出稿",
                                    "slots": {"period": "202611", "intent": "出报告"}})
    assert "先别出稿" in r["text"]
    assert r["run"] is None
    assert {"kind": "goto", "view": "acquire", "period": "202611",
            "text": "去核对 ▸"} in r["actions"]


def test_产物已在_先问一次(tmp_path):
    (tmp_path / "202607").mkdir()
    (tmp_path / "202607" / "red_slots.json").write_text("[]", encoding="utf-8")
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "核完了，继续", "slots": {"period": "202607"}})
    assert "已经有产物" in r["text"]
    assert r["run"] == {"period": "202607", "auto": False, "intent": "single_trend"}
    assert {"kind": "run", "period": "202607", "text": "覆盖重出"} in r["actions"]


# ============================================================ 2c. 票 07：两意图（写报告 / 查数据）
def test_查数据_服务器按意图调qa(monkeypatch, tmp_path):
    from ai import _types
    calls = []
    qa_answer = _types.Answer(
        mode="rule", backend="rule", text="化学的接近度约 89.5[[1]]。",
        rule_text="化学的接近度约 89.5。",
        sources=(_types.Source(index=1, kind="product",
                               pointer="overview_facts.json#matrix.chem",
                               label="本期事实", detail="d", value="89.5"),),
        shield=_types.Shield(1, 1), record_id="r-qa")

    def fake_run(cap, period, *, payload=None, actor=None):
        calls.append((cap, period, payload))
        if cap == "dialog":
            return _types.Answer(mode="rule", backend="rule", text="",
                                 data={"case": "period", "period": "202607", "intent": "",
                                       "kind": "query"})
        return qa_answer

    monkeypatch.setattr("ai.run", fake_run)
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: tmp_path / p)
    r = call(config.ADMIN_USER, {"text": "查一下化学的接近度", "slots": {"period": "202607"}})
    assert r["kind"] == "query" and r["answer"] is not None
    assert r["answer"]["text"].startswith("化学的接近度") and r["answer"]["record_id"] == "r-qa"
    assert r["slots"] == {"period": "202607", "intent": ""}, "期次解析与槽位共享"
    assert r["run"] is None, "查数据不出稿"
    assert calls == [("dialog", "202607", {"text": "查一下化学的接近度"}),
                     ("qa", "202607", {"question": "查一下化学的接近度"})], \
        "两意图经同一端点：服务器按意图调 ai.run(\"qa\", …)，问句原样"


def test_查数据_没期次_先要期次不调qa(monkeypatch):
    from ai import _types
    called = []

    def fake_run(cap, period, *, payload=None, actor=None):
        called.append(cap)
        return _types.Answer(mode="rule", backend="rule", text="查哪一期？……",
                             data={"case": "no_period", "period": "", "intent": "",
                                   "kind": "query"})

    monkeypatch.setattr("ai.run", fake_run)
    r = call(config.ADMIN_USER, {"text": "查一下化学的接近度"})
    assert r["kind"] == "query" and r["answer"] is None
    assert called == ["dialog"], "没期次不猜：先反问"
    assert "查哪一期" in r["text"]


def test_查数据_没产物_先提示出稿(monkeypatch, tmp_path):
    from ai import _types

    def fake_run(cap, period, *, payload=None, actor=None):
        assert cap == "dialog", "没产物就不该调 qa"
        return _types.Answer(mode="rule", backend="rule", text="",
                             data={"case": "period", "period": "202607", "intent": "",
                                   "kind": "query"})

    monkeypatch.setattr("ai.run", fake_run)
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: None)
    r = call(config.ADMIN_USER, {"text": "查一下化学的接近度", "slots": {"period": "202607"}})
    assert r["kind"] == "query" and r["answer"] is None
    assert "出稿" in r["text"], "没产物给出稿提示（不 404，聊天里说清楚）"


def test_查数据_qas开关关闭_照旧说已关闭(monkeypatch, tmp_path):
    from ai import _types

    def fake_run(cap, period, *, payload=None, actor=None):
        if cap == "dialog":
            return _types.Answer(mode="rule", backend="rule", text="",
                                 data={"case": "period", "period": "202607", "intent": "",
                                       "kind": "query"})
        return _types.Answer(mode="closed", backend="rule",
                             notice="此功能已由管理员关闭；数据与报告不受影响。")

    monkeypatch.setattr("ai.run", fake_run)
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: tmp_path / p)
    r = call(config.ADMIN_USER, {"text": "查一下化学的接近度", "slots": {"period": "202607"}})
    assert r["kind"] == "query" and r["answer"]["mode"] == "closed"
    assert "管理员关闭" in r["answer"]["notice"], "关了照旧说「已关闭」（不 409，聊天里说清楚）"


def test_含糊_两选项与槽位从API出(tmp_path):
    with ai.using(data_root=tmp_path, inventory=lambda p: None):
        r = call(config.ADMIN_USER, {"text": "看看 9 月"})
    assert r["kind"] == "unclear"
    assert r["slots"]["period"] == "202609"
    texts = [a["text"] for a in r["actions"]]
    assert "做 202609 的报告" in texts and "查 202609 的数据" in texts
    assert r["run"] is None and r["answer"] is None


def test_写报告轮_kind为report(tmp_path):
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "做 7 月的报告"})
    assert r["kind"] == "report" and r["answer"] is None


# ============================================================ 2d. 票 05：覆盖确认（口径 A）
def test_覆盖确认_回合本身不执行任何东西(tmp_path):
    """第一次点不执行：回合只是「问一次」——产物原封不动、不开任务（执行只在人确认后）。

    唯一允许的新增是这一轮的**留痕**（`ai_calls.jsonl`，每轮对话都记）；产物一个字节不动。
    """
    pdir = tmp_path / "202607"
    pdir.mkdir()
    (pdir / "red_slots.json").write_text("[]", encoding="utf-8")
    before = {p.name: p.stat().st_mtime_ns for p in pdir.iterdir()}
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.ADMIN_USER, {"text": "核完了，继续", "slots": {"period": "202607"}})
    assert r["run"] == {"period": "202607", "auto": False, "intent": "single_trend"}
    assert not any(k.startswith("job") for k in r), "回合不替人开跑：开跑是确认后的显式动作"
    after = {p.name: p.stat().st_mtime_ns for p in pdir.iterdir()}
    assert set(after) <= set(before) | {"ai_calls.jsonl"}, "回合不该产生任何产物"
    for name, mtime in before.items():
        assert after[name] == mtime, f"{name} 被动过了——「问一次」本身不该动产物"


# ============================================================ 2e. 票 06：本期任务（空态第一屏）
def test_本期任务_形状与门(monkeypatch):
    """空态第一屏：三步状态从既有产物判（服务器注入 taskview.scan 与签发核实）。"""
    fake = {"period": "202611", "released": False, "n_missing": 4,
            "steps": [{"key": k, "done": False} for k in ("acquire", "merge", "generate")],
            "stuck": "acquire", "prev": {"period": "202609", "status": "signed"}}
    import taskview
    monkeypatch.setattr(taskview, "scan", lambda **kw: fake)
    r = asyncio.run(app_module.api_dialog_home(_ReqJson(config.ADMIN_USER)))
    assert r["period"] == "202611" and r["stuck"] == "acquire"
    assert [s["key"] for s in r["steps"]] == ["acquire", "merge", "generate"]
    assert r["released"] is False and r["n_missing"] == 4
    assert r["prev"] == {"period": "202609", "status": "signed"}
    # 2026-10-11：空态是只读，操作员同看（同形状）；匿名 401。
    r_op = asyncio.run(app_module.api_dialog_home(_ReqJson(config.OPERATOR_USER)))
    assert r_op["period"] == "202611" and r_op["stuck"] == "acquire"
    assert asyncio.run(app_module.api_dialog_home(_ReqJson(None))).status_code == 401


def test_本期任务_扫描拿不到_给空形状(monkeypatch):
    import taskview
    monkeypatch.setattr(taskview, "scan", lambda **kw: None)
    r = asyncio.run(app_module.api_dialog_home(_ReqJson(config.ADMIN_USER)))
    assert r == {"period": "", "released": False, "n_missing": 0,
                 "steps": [], "stuck": "", "prev": None}


# ============================================================ 3. 参数与权限
def test_空话400(monkeypatch):
    monkeypatch.setattr("ai.run", lambda *a, **k: None)
    r = call(config.ADMIN_USER, {"text": "   "})
    assert r.status_code == 400


def test_操作员可用_匿名不可用(tmp_path):
    """2026-10-12：出报告对操作员开放——报告意图照常盘点（不再说「操作员只读」）；匿名 401。"""
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.OPERATOR_USER, {"text": "做 7 月的报告"})
    assert "操作员只读" not in r["text"] and "盘点 · 202607" in r["text"]
    assert r["slots"]["period"] == "202607", "期次槽位照常亮起"
    assert call(None, {"text": "做 7 月的报告"}).status_code == 401


def test_能力关闭映射409(monkeypatch):
    from ai import _types
    fake = _types.Answer(mode="closed", backend="rule", notice="此功能已由管理员关闭；数据与报告不受影响。")
    monkeypatch.setattr("ai.run", lambda *a, **k: fake)
    r = call(config.ADMIN_USER, {"text": "做9月的报告"})
    assert r.status_code == 409


def test_路由存在且带登录门():
    src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/dialog/turn")' in src
    assert "@user_route" in src.split('@app.post("/api/dialog/turn")')[1][:200]
