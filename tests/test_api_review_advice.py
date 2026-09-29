# -*- coding: utf-8 -*-
"""D4（2026-09-29）：/api/periods/{period}/review-advice 薄适配（契约 #27）。"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as app_module, config                    # noqa: E402


class _ReqJson:
    def __init__(self, user):
        self.session = {"user": user}

    async def json(self):
        return {}


def test_review_advice透出Answer且参数正确(monkeypatch, tmp_path):
    from ai import _types
    fake = _types.Answer(
        mode="rule", backend="rule", text="复核清单…", rule_text="复核清单…",
        sources=(_types.Source(index=1, kind="product",
                               pointer="red_slots.json#0", value="1"),),
        shield=_types.Shield(1, 1), record_id="rec-r")
    seen = {}

    def fake_run(cap, period, *, payload=None, actor=None):
        seen.update(cap=cap, period=period, payload=payload, actor=actor)
        return fake

    monkeypatch.setattr("ai.run", fake_run)
    monkeypatch.setattr(app_module, "resolve_period_dir",
                        lambda p: tmp_path / p if p == "202607" else None)
    r = asyncio.run(app_module.api_period_review_advice(_ReqJson(config.DEMO_USER), "202607"))
    assert r["mode"] == "rule" and r["text"] == "复核清单…"
    assert r["sources"][0]["pointer"] == "red_slots.json#0"
    assert seen == {"cap": "review", "period": "202607", "payload": None, "actor": "admin"}


def test_review_advice无产物404(monkeypatch, tmp_path):
    from ai import _types
    fake = _types.Answer(mode="unavailable", backend="rule",
                         notice="该期数据暂不可用，无法给出复核建议。")
    monkeypatch.setattr("ai.run", lambda *a, **k: fake)
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: tmp_path / p)
    r = asyncio.run(app_module.api_period_review_advice(_ReqJson(config.DEMO_USER), "202607"))
    assert r.status_code == 404


def test_review_advice权限门():
    assert asyncio.run(app_module.api_period_review_advice(
        _ReqJson(config.GUEST_USER), "202607")).status_code == 403
    assert asyncio.run(app_module.api_period_review_advice(
        _ReqJson(None), "202607")).status_code == 401
