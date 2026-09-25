# -*- coding: utf-8 -*-
"""游客的单期元数据只能用于封面，不读取报告事实或任务。"""
import asyncio

from server import config
from server import app as app_module


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


def test_guest单期元数据不读取facts或任务(monkeypatch, tmp_path):
    period_dir = tmp_path / "202609"
    period_dir.mkdir()
    (period_dir / "overview_facts.json").write_text('{"coverage_window":"秘密"}', encoding="utf-8")
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: period_dir)
    monkeypatch.setattr(app_module.json, "loads", lambda *_args: (_ for _ in ()).throw(AssertionError("不应读 facts")))
    monkeypatch.setattr(app_module.jobs, "list_jobs", lambda *_args: (_ for _ in ()).throw(AssertionError("不应读任务")))

    response = asyncio.run(app_module.api_period_detail(_Req(config.GUEST_USER), "202609"))
    assert set(response) == {"period", "label", "no", "total", "palette"}
    assert response["period"] == "202609"
    assert "秘密" not in str(response)
