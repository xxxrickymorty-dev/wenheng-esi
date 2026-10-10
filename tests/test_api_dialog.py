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
        r = call(config.DEMO_USER, {"text": "做 7 月的报告"})
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
    r = call(config.DEMO_USER, {"text": "再出 202605 的",
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
    r = call(config.DEMO_USER, {"text": "你好", "slots": {"period": "202609", "intent": ""}})
    assert r["slots"] == {"period": "202609", "intent": ""}, "没解析到就不动槽位"


def test_槽位期次非法形状_丢弃不猜(monkeypatch):
    from ai import _types
    seen = {}

    def fake_run(cap, period, *, payload=None, actor=None):
        seen["period"] = period
        return _types.Answer(mode="rule", backend="rule", text="…",
                             data={"case": "no_period", "period": "", "intent": ""})

    monkeypatch.setattr("ai.run", fake_run)
    r = call(config.DEMO_USER, {"text": "你好", "slots": {"period": "2026-09"}})
    assert seen["period"] == "", "非法期次不进能力口"
    assert r["slots"] == {"period": "", "intent": ""}


# ============================================================ 2. 票 02：盘点走 API
def test_九月未发布_盘点与两条路从API出(tmp_path):
    inv = fake_inventory("202609", released=False,
                         missing=("papers", "incites"), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.DEMO_USER, {"text": "帮我做9月份的报告"})
    assert r["slots"]["period"] == "202609"
    assert r["verdict"] == "unpublished"
    assert r["inventory"]["n_missing"] == 2 and r["inventory"]["n_pieces"] == 4
    assert {"kind": "send", "text": "改做 202607 的"} in r["actions"]
    assert "这一期数据还没到" in r["text"], "停下反问（不触发流水线——本路由无任何生成副作用）"


def test_改做202607的_槽位改期次其余不变(tmp_path):
    invs = {"202607": fake_inventory("202607", released=True)}
    with ai.using(data_root=tmp_path, inventory=lambda p: invs.get(p)):
        r = call(config.DEMO_USER, {"text": "改做 202607 的",
                                    "slots": {"period": "202609", "intent": "出报告"}})
    assert r["slots"] == {"period": "202607", "intent": "出报告"}
    assert r["verdict"] == "ready"


def test_九月已发布缺件_给补件入口(tmp_path):
    inv = fake_inventory("202609", released=True, missing=("papers",), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.DEMO_USER, {"text": "帮我做9月份的报告"})
    assert r["verdict"] == "missing"
    assert {"kind": "goto", "view": "acquire", "period": "202609",
            "text": "去取数台 ▸"} in r["actions"]


def test_响应不露文件路径(tmp_path):
    inv = fake_inventory("202609", released=False,
                         missing=("papers", "incites"), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.DEMO_USER, {"text": "帮我做9月份的报告"})
    blob = json.dumps(r, ensure_ascii=False)
    for leak in ("input/", ".xlsx", ".csv", "数据与复现"):
        assert leak not in blob


def test_没注入盘点_退回票01行为(tmp_path):
    with ai.using(data_root=tmp_path, inventory=lambda p: None):
        r = call(config.DEMO_USER, {"text": "帮我做9月份的报告"})
    assert r["slots"]["period"] == "202609"
    assert r["verdict"] == "" and r["inventory"] is None and r["actions"] == []


# ============================================================ 2b. 票 03：核对门
def test_核完了继续_进入出稿(tmp_path):
    inv = fake_inventory("202607", released=True)
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.DEMO_USER, {"text": "核完了，继续",
                                    "slots": {"period": "202607", "intent": "出报告"}})
    assert "核对通过" in r["text"] and "开始出稿" in r["text"]
    assert r["run"] == {"period": "202607", "auto": True, "intent": "single_trend"}
    assert r["slots"] == {"period": "202607", "intent": "出报告"}, "槽位不动"


def test_未核对就出稿_拦住并指回核对(tmp_path):
    inv = fake_inventory("202611", released=False,
                         missing=("papers", "incites"), fallback="202607")
    with ai.using(data_root=tmp_path, inventory=lambda p: inv):
        r = call(config.DEMO_USER, {"text": "出稿",
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
        r = call(config.DEMO_USER, {"text": "核完了，继续", "slots": {"period": "202607"}})
    assert "已经有产物" in r["text"]
    assert r["run"] == {"period": "202607", "auto": False, "intent": "single_trend"}
    assert {"kind": "run", "period": "202607", "text": "覆盖重出"} in r["actions"]


# ============================================================ 3. 参数与权限
def test_空话400(monkeypatch):
    monkeypatch.setattr("ai.run", lambda *a, **k: None)
    r = call(config.DEMO_USER, {"text": "   "})
    assert r.status_code == 400


def test_非admin不可用(tmp_path):
    assert call(config.GUEST_USER, {"text": "做9月的报告"}).status_code == 403
    assert call(None, {"text": "做9月的报告"}).status_code == 401


def test_能力关闭映射409(monkeypatch):
    from ai import _types
    fake = _types.Answer(mode="closed", backend="rule", notice="此功能已由管理员关闭；数据与报告不受影响。")
    monkeypatch.setattr("ai.run", lambda *a, **k: fake)
    r = call(config.DEMO_USER, {"text": "做9月的报告"})
    assert r.status_code == 409


def test_路由存在且带admin门():
    src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/dialog/turn")' in src
    assert "@admin_route" in src.split('@app.post("/api/dialog/turn")')[1][:200]
