# -*- coding: utf-8 -*-
"""游客不能通过普通工作区 API 取得期次元数据。"""
import asyncio

from server import config
from server import app as app_module


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


def test_guest单期元数据在读文件前被拒绝(monkeypatch):
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda *_args: (_ for _ in ()).throw(AssertionError("不应读期次")))
    response = asyncio.run(app_module.api_period_detail(_Req(config.GUEST_USER), "202609"))
    assert response.status_code == 403


def test_guest期次列表同样被拒绝(monkeypatch):
    monkeypatch.setattr(app_module, "period_cards", lambda: (_ for _ in ()).throw(AssertionError("不应读期次")))
    response = asyncio.run(app_module.api_periods(_Req(config.GUEST_USER)))
    assert response.status_code == 403
