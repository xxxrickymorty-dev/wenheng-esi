# -*- coding: utf-8 -*-
"""对话前门（票 01）· S2 契约：`POST /api/dialog/turn`。

外部行为：一轮对话 = 答复字段面（Answer）+ 合并后的槽位；只走 admin 门；
空话 400；能力关闭 409；参数/角色都原样交给 `ai.run`。
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ai                                                       # noqa: E402
from server import app as app_module, config                    # noqa: E402


class _ReqJson:
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self._body = body or {}

    async def json(self):
        return self._body


def call(user, body):
    return asyncio.run(app_module.api_dialog_turn(_ReqJson(user, body)))


# ============================================================ 1. 一轮对话的字段面
def test_一轮对话_答复与槽位(monkeypatch, tmp_path):
    from ai import _types
    fake = _types.Answer(mode="rule", backend="rule", text="我按「数据截至 2026-09」理解 → 期次 202609。",
                         rule_text="…", shield=_types.Shield(3, 3), record_id="rec-1",
                         data={"case": "period", "period": "202609", "intent": "出报告"})
    seen = {}

    def fake_run(cap, period, *, payload=None, actor=None):
        seen.update(cap=cap, period=period, payload=payload, actor=actor)
        return fake

    monkeypatch.setattr("ai.run", fake_run)
    r = call(config.DEMO_USER, {"text": "帮我做9月份的报告",
                                "slots": {"period": "", "intent": ""}})
    assert r["text"] == fake.text and r["record_id"] == "rec-1"
    assert r["slots"] == {"period": "202609", "intent": "出报告"}
    assert seen == {"cap": "dialog", "period": "", "payload": {"text": "帮我做9月份的报告"},
                    "actor": "admin"}, "路由只做转译：一句话 + 槽位期次原样交给 ai.run"


def test_槽位合并_解析到才覆盖_其余不变(monkeypatch):
    from ai import _types

    def make(period, intent):
        return _types.Answer(mode="rule", backend="rule", text="…",
                             data={"case": "period", "period": period, "intent": intent})

    monkeypatch.setattr("ai.run", lambda *a, **k: make("202605", ""))
    r = call(config.DEMO_USER, {"text": "再出 202605 的",
                                "slots": {"period": "202609", "intent": "出报告"}})
    assert r["slots"] == {"period": "202605", "intent": "出报告"}, "只改期次，意图不变"

    monkeypatch.setattr("ai.run", lambda *a, **k: make("", ""))
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


# ============================================================ 2. 真跑一轮（路由 → ai.run → 留痕）
def test_真跑一轮_答复期次槽与留痕(tmp_path):
    with ai.using(data_root=tmp_path):
        r = call(config.DEMO_USER, {"text": "帮我做9月份的报告"})
    assert "数据截至 2026-09" in r["text"] and "202609" in r["text"]
    assert r["slots"]["period"] == "202609"
    assert (tmp_path / "202609" / "ai_calls.jsonl").exists(), "这轮对话进运行档案"


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
