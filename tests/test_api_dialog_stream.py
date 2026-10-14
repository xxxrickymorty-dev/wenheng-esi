# -*- coding: utf-8 -*-
"""对话前门·阶段进度流（契约 #37，票 12）：NDJSON 形状 / 真实节点 / 与同步口同载荷。

同步口（#33）与流口（#37）共用 `_dialog_turn_impl`——这里钉住流口的线协议。
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

import pytest                                                    # noqa: E402

import ai                                                       # noqa: E402
from server import app as app_module, config                    # noqa: E402


class _ReqJson:
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self._body = body or {}

    async def json(self):
        return self._body


async def _collect(resp):
    out = []
    async for chunk in resp.body_iterator:
        out.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
    return out


@pytest.fixture(autouse=True)
def _no_real_ledger(monkeypatch):
    import taskview
    monkeypatch.setattr(taskview, "known_periods", lambda: [])


def _events(user, body):
    resp = asyncio.run(app_module.api_dialog_turn_stream(_ReqJson(user, body)))
    lines = asyncio.run(_collect(resp))
    return [json.loads(x) for x in lines]


def test_流口_NDJSON_形状与done载荷(monkeypatch, tmp_path):
    """查数据一轮：理解 → 查数 → done(payload 与 #33 同形状)。"""
    from ai import _types
    fake = _types.Answer(mode="rule", backend="rule", text="",
                         data={"case": "period", "period": "202605", "intent": "",
                               "kind": "query"})
    calls = []

    def fake_run(cap, period, *, payload=None, actor=None):
        calls.append(cap)
        return fake

    monkeypatch.setattr("ai.run", fake_run)
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: tmp_path / p)
    with ai.using(data_root=tmp_path):
        events = _events(config.ADMIN_USER, {"text": "查一下化学的接近度"})
    assert events[0]["event"] == "stage" and events[0]["stage"] == "理解"
    assert [e["stage"] for e in events if e["event"] == "stage"] == ["理解", "查数"]
    done = events[-1]
    assert done["event"] == "done"
    assert done["payload"]["kind"] == "query"
    assert done["payload"]["slots"]["period"] == "202605"
    assert calls == ["dialog", "qa"], "两意图仍经同一端点（服务器按意图调 qa）"


def test_流口_没产物_只有理解阶段(monkeypatch, tmp_path):
    """没产物 → 不调 qa → 如实少一个阶段（不演）。"""
    from ai import _types
    fake = _types.Answer(mode="rule", backend="rule", text="",
                         data={"case": "period", "period": "202605", "intent": "",
                               "kind": "query"})
    monkeypatch.setattr("ai.run", lambda cap, period, *, payload=None, actor=None: fake)
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: None)
    with ai.using(data_root=tmp_path):
        events = _events(config.ADMIN_USER, {"text": "查一下化学的接近度"})
    stages = [e["stage"] for e in events if e["event"] == "stage"]
    assert stages == ["理解"]
    assert events[-1]["event"] == "done"
    assert "先出稿" in events[-1]["payload"]["text"]


def test_流口_空话_出error事件(monkeypatch):
    events = _events(config.ADMIN_USER, {"text": ""})
    assert events[-1]["event"] == "error" and events[-1]["status"] == 400
    assert "请先说一句话" in events[-1]["error"]
