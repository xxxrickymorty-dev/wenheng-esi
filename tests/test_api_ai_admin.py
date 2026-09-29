# -*- coding: utf-8 -*-
"""D5（2026-09-29）：/api/ai/capabilities + /api/ai/switch（契约 #28/#29，分析台开关用）。"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as app_module, config                    # noqa: E402


class _ReqJson:
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self._body = body or {}

    async def json(self):
        return self._body


def test_capabilities透出开关表(monkeypatch):
    from ai import _types
    fake = (_types.CapabilityInfo(id="qa", label="问文衡", stage="ready",
                                  min_role="admin", enabled=True, allowed=True),
            _types.CapabilityInfo(id="review", label="复核参谋", stage="ready",
                                  min_role="admin", enabled=False, allowed=True,
                                  notice="已由管理员关闭。"))
    seen = {}

    def fake_caps(actor=None):
        seen["actor"] = actor
        return fake

    monkeypatch.setattr("ai.capabilities", fake_caps)
    r = asyncio.run(app_module.api_ai_capabilities(_ReqJson(config.DEMO_USER)))
    assert [c["id"] for c in r["capabilities"]] == ["qa", "review"]
    assert r["capabilities"][1]["enabled"] is False
    assert seen["actor"] == "admin", "用户名经 config.role_of 映射为角色"


def test_switch参数与权限映射(monkeypatch):
    calls = {}

    def fake_switch(capability, enabled, *, actor=None):
        calls.update(capability=capability, enabled=enabled, actor=actor)
        if capability == "占卜":
            raise ValueError("未知能力")
        if actor != "admin":
            raise PermissionError("仅管理员可变更能力开关")

    monkeypatch.setattr("ai.set_switch", fake_switch)

    ok = asyncio.run(app_module.api_ai_switch(
        _ReqJson(config.DEMO_USER, {"capability": "qa", "enabled": False})))
    assert ok == {"ok": True, "capability": "qa", "enabled": False}
    assert calls == {"capability": "qa", "enabled": False, "actor": "admin"}

    bad = asyncio.run(app_module.api_ai_switch(
        _ReqJson(config.DEMO_USER, {"capability": "占卜", "enabled": True})))
    assert bad.status_code == 400

    # 防御：即便守卫放行，模块侧权限不足也要映射 403（正常路径到不了）
    monkeypatch.setattr(app_module, "require_admin", lambda request: None)
    monkeypatch.setattr(app_module, "current_user", lambda request: "someone")
    denied = asyncio.run(app_module.api_ai_switch(
        _ReqJson("someone", {"capability": "qa", "enabled": True})))
    assert denied.status_code == 403


def test_两口都是admin门():
    for user, code in ((config.GUEST_USER, 403), (None, 401)):
        assert asyncio.run(app_module.api_ai_capabilities(_ReqJson(user))).status_code == code
        assert asyncio.run(app_module.api_ai_switch(_ReqJson(user))).status_code == code
