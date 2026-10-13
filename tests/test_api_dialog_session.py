# -*- coding: utf-8 -*-
"""会话（票 11）· S2 契约：`POST /api/dialog/turn` 的 session 收发 + `GET /api/dialog/session/{id}`。

外部行为：无 session → 建新会话并回 `session_id`；带 session → 历史从库读（不取 body）、
本回合续写、槽位随会话落库；GET 仅 owner（404/403 与既有口径一致）。
会话库注入 tmp（monkeypatch 模块属性），不碰真 `out/_sessions/`；AI 走替身（不出网、不落账）。
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                    # noqa: E402

from server import app as app_module, config                     # noqa: E402
import session_store as store                                    # noqa: E402


class _ReqJson:                                                  # 与 test_api_dialog 同款直调姿势
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self._body = body or {}

    async def json(self):
        return self._body


def call(user, body):
    return asyncio.run(app_module.api_dialog_turn(_ReqJson(user, body)))


def call_get(user, session_id):
    return asyncio.run(app_module.api_dialog_session(_ReqJson(user), session_id))


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    """会话库一律 tmp（测试绝不碰真 out/_sessions/）；期次表给空（不读真台账）。"""
    monkeypatch.setattr(app_module, "SESSION_DB_PATH", tmp_path / "sessions.sqlite")
    import taskview
    monkeypatch.setattr(taskview, "known_periods", lambda: [])


@pytest.fixture()
def fake_ai(monkeypatch):
    """dialog 能力替身：固定答复，把每轮 payload 记下来供断言。"""
    from ai import _types
    seen = []

    def fake_run(cap, period, *, payload=None, actor=None):
        seen.append({"cap": cap, "payload": payload, "actor": actor})
        return _types.Answer(mode="rule", backend="rule", text="收到，我先记下。",
                             data={"case": "no_period", "period": "", "intent": ""})

    monkeypatch.setattr("ai.run", fake_run)
    return seen


# ============================================================ 1. turn 建会话 / 续写
def test_无session_建新会话并落两回合(fake_ai):
    r = call(config.ADMIN_USER, {"text": "你好"})
    sid = r["session_id"]
    assert sid.startswith("s-"), "响应带本回合的会话 id"
    got = store.load(app_module.SESSION_DB_PATH, sid, config.ADMIN_USER)
    assert [t["who"] for t in got["turns"]] == ["me", "wh"]
    assert got["turns"][0]["text"] == "你好"
    assert got["turns"][1]["text"] == r["text"] == "收到，我先记下。"
    assert got["slots"] == r["slots"]


def test_带session_历史从库读_不取body(fake_ai):
    r1 = call(config.ADMIN_USER, {"text": "帮我做 9 月的报告"})
    sid = r1["session_id"]
    r2 = call(config.ADMIN_USER, {"text": "再出一次", "session": sid,
                                  "history": [{"who": "me", "text": "这条不该被用"}]})
    assert r2["session_id"] == sid, "续写同一会话"
    hist = fake_ai[-1]["payload"]["history"]
    assert [h["text"] for h in hist] == ["帮我做 9 月的报告", "收到，我先记下。"]
    assert "不该被用" not in str(hist), "带会话时忽略 body 历史（库里才是真历史）"
    got = store.load(app_module.SESSION_DB_PATH, sid, config.ADMIN_USER)
    assert [t["who"] for t in got["turns"]] == ["me", "wh", "me", "wh"]


def test_历史截断口径_最近8条每条200字(fake_ai):
    sid = call(config.ADMIN_USER, {"text": "第一句"})["session_id"]
    for i in range(8):
        call(config.ADMIN_USER, {"text": f"第{i + 2}句", "session": sid})
    call(config.ADMIN_USER, {"text": "长" * 300, "session": sid})
    call(config.ADMIN_USER, {"text": "再问一句", "session": sid})
    hist = fake_ai[-1]["payload"]["history"]
    assert len(hist) == 8, "只取最近 8 条"
    assert all(len(h["text"]) <= 200 for h in hist)
    assert any(h["text"] == "长" * 200 for h in hist), "超长截到 200 字"
    assert hist[-1] == {"who": "wh", "text": "收到，我先记下。"}


def test_槽位随会话落库(fake_ai):
    r = call(config.ADMIN_USER, {"text": "做 7 月的报告",
                                 "slots": {"period": "202607", "intent": "出报告"}})
    sid = r["session_id"]
    body = call_get(config.ADMIN_USER, sid)
    assert body["slots"] == {"period": "202607", "intent": "出报告"}
    assert body["slots"] == r["slots"]


# ============================================================ 2. GET 回读与权限
def test_GET回读_形状(fake_ai):
    r = call(config.ADMIN_USER, {"text": "你好"})
    body = call_get(config.ADMIN_USER, r["session_id"])
    assert set(body) == {"id", "slots", "turns"}
    assert body["id"] == r["session_id"]
    assert [t["who"] for t in body["turns"]] == ["me", "wh"]
    assert all(set(t) == {"who", "text", "ts"} for t in body["turns"])


def test_GET他人会话403(fake_ai):
    sid = call(config.ADMIN_USER, {"text": "你好"})["session_id"]
    assert call_get(config.OPERATOR_USER, sid).status_code == 403


def test_GET不存在或形状非法404():
    assert call_get(config.ADMIN_USER, "s-20260101-01234567").status_code == 404
    assert call_get(config.ADMIN_USER, "乱七八糟").status_code == 404


def test_匿名401():
    assert call_get(None, "s-20260101-01234567").status_code == 401


def test_操作员可建自己的会话_他人读不到(fake_ai):
    r = call(config.OPERATOR_USER, {"text": "你好"})
    assert r["session_id"].startswith("s-")
    assert call_get(config.OPERATOR_USER, r["session_id"])["id"] == r["session_id"]
    assert call_get(config.ADMIN_USER, r["session_id"]).status_code == 403


# ============================================================ 3. turn 带 session 的两种拒绝
def test_turn带他人session403(fake_ai):
    sid = call(config.ADMIN_USER, {"text": "你好"})["session_id"]
    r = call(config.OPERATOR_USER, {"text": "偷看", "session": sid})
    assert r.status_code == 403


def test_turn带不存在session404(fake_ai):
    r = call(config.ADMIN_USER, {"text": "你好", "session": "s-20260101-01234567"})
    assert r.status_code == 404


def test_未装配会话库_不落库不炸(monkeypatch, fake_ai):
    """直调处理函数的测试（没跑 lifespan）＝未装配：会话收发优雅降级，不写任何东西。"""
    monkeypatch.setattr(app_module, "SESSION_DB_PATH", None)
    r = call(config.ADMIN_USER, {"text": "你好"})
    assert r["session_id"] == ""
    assert call_get(config.ADMIN_USER, "s-20260101-01234567").status_code == 404


# ============================================================ 4. 路由契约
def test_路由存在且带登录门():
    src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/dialog/session/{session_id}")' in src
    assert "@user_route" in src.split('@app.get("/api/dialog/session/{session_id}")')[1][:200]
