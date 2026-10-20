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
    r = asyncio.run(app_module.api_ai_capabilities(_ReqJson(config.ADMIN_USER)))
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
        _ReqJson(config.ADMIN_USER, {"capability": "qa", "enabled": False})))
    assert ok == {"ok": True, "capability": "qa", "enabled": False}
    assert calls == {"capability": "qa", "enabled": False, "actor": "admin"}

    bad = asyncio.run(app_module.api_ai_switch(
        _ReqJson(config.ADMIN_USER, {"capability": "占卜", "enabled": True})))
    assert bad.status_code == 400

    # 防御：即便守卫放行，模块侧权限不足也要映射 403（正常路径到不了）
    monkeypatch.setattr(app_module, "require_admin", lambda request: None)
    monkeypatch.setattr(app_module, "current_user", lambda request: "someone")
    denied = asyncio.run(app_module.api_ai_switch(
        _ReqJson("someone", {"capability": "qa", "enabled": True})))
    assert denied.status_code == 403


def test_capabilities放行操作员_switch仍admin门():
    """2026-10-11：能力表是只读，操作员可读；开关是写口，仍只管理员。"""
    operator_caps = asyncio.run(app_module.api_ai_capabilities(_ReqJson(config.OPERATOR_USER)))
    assert "capabilities" in operator_caps
    assert asyncio.run(app_module.api_ai_capabilities(_ReqJson(None))).status_code == 401
    for user, code in ((config.OPERATOR_USER, 403), (None, 401)):
        assert asyncio.run(app_module.api_ai_switch(_ReqJson(user))).status_code == code


def test_ai_calls只回摘要并按新到旧(monkeypatch, tmp_path):
    import json as _json
    d = tmp_path / "202607"
    d.mkdir()
    rows = [
        {"kind": "switch", "capability": "qa", "from": True, "to": False},          # 审计行：滤掉
        {"kind": "call", "record_id": "ai-qa-1", "ts": "2026-09-29T10:00:00",
         "capability": "qa", "mode": "model", "backend": "openai:m", "fallback": None,
         "shield": {"checked": 5, "passed": 5}, "tools": [], "question": "q1",
         "elapsed_ms": 2000, "text_preview": "不该透出"},
        "{坏行不炸}",
        {"kind": "call", "record_id": "ai-review-2", "ts": "2026-09-29T11:00:00",
         "capability": "review", "mode": "rule", "backend": "rule",
         "fallback": "empty_reply", "shield": {"checked": 2, "passed": 2},
         "tools": [{"tool": "x"}], "question": "", "elapsed_ms": 4000},
    ]
    (d / "ai_calls.jsonl").write_text(
        "\n".join(_json.dumps(r, ensure_ascii=False) if isinstance(r, dict) else r for r in rows),
        encoding="utf-8")
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: d if p == "202607" else None)

    r = asyncio.run(app_module.api_period_ai_calls(_ReqJson(config.ADMIN_USER), "202607"))
    assert [c["record_id"] for c in r["calls"]] == ["ai-review-2", "ai-qa-1"], "新→旧，坏行与审计行跳过"
    assert "text_preview" not in r["calls"][0], "只回摘要"
    assert r["calls"][0]["n_tools"] == 1 and r["calls"][0]["fallback"] == "empty_reply"
    assert r["stats"] == {"n": 2, "model": 1, "fallback": 1, "avg_sec": 3.0,
                          "last_ts": "2026-09-29T11:00:00"}
    op = asyncio.run(app_module.api_period_ai_calls(
        _ReqJson(config.OPERATOR_USER), "202607"))
    assert isinstance(op, dict), "2026-10-20 起调用留痕对操作员只读开放"
    assert "text_preview" not in op["calls"][0], "操作员也只回摘要"
