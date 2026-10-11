# -*- coding: utf-8 -*-
"""旧页面只关未登录这一道门；已登录（管理员/操作员）都进新工作区（2026-10-11）。"""
import asyncio

from fastapi.responses import RedirectResponse

from server import app as app_module
from server import config


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _must_not_read(*_args, **_kwargs):
    raise AssertionError("匿名重定向前不应读取期次或任务")


def test_操作员旧页面直接进新工作区(monkeypatch):
    """不存在的期次落回 /app/——数据无关，只验门放行（不再分流到陈列馆）。"""
    request = _Req(config.OPERATOR_USER)
    calls = [
        lambda: app_module.home(request),
        lambda: app_module.run_page(request),
        lambda: app_module.forecast_page(request),
        lambda: app_module.period_collation(request, "199901"),
        lambda: app_module.period_redslots(request, "199901"),
        lambda: app_module.period_trace(request, "199901"),
        lambda: app_module.period_charts(request, "199901"),
        lambda: app_module.period_flexible(request, "199901"),
        lambda: app_module.period_archive(request, "199901"),
        lambda: app_module.job_page(request, "known-or-not"),
    ]
    for call in calls:
        response = asyncio.run(call())
        assert isinstance(response, RedirectResponse)
        assert response.status_code == 302
        assert response.headers["location"].startswith("/app/")


def test_匿名旧页面仍先跳登录且不探测资源(monkeypatch):
    monkeypatch.setattr(app_module, "resolve_period_dir", _must_not_read)
    monkeypatch.setattr(app_module.jobs, "read_job", _must_not_read)
    for call in (lambda: app_module.period_collation(_Req(), "202609"),
                 lambda: app_module.collation_page(_Req(), "known-or-not"),
                 lambda: app_module.redslots_page(_Req(), "known-or-not")):
        response = asyncio.run(call())
        assert isinstance(response, RedirectResponse)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_healthz不返回服务器目录():
    assert asyncio.run(app_module.healthz()) == {"ok": True}
