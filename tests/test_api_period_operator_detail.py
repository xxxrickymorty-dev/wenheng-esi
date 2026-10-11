# -*- coding: utf-8 -*-
"""操作员（只读）可以通过工作区 API 取得期次元数据（2026-10-11 角色改两级后）。"""
import asyncio

from server import config
from server import app as app_module


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def test_操作员单期元数据放行(monkeypatch):
    # 不存在的期次回 404——若门没放行会是 403。
    response = asyncio.run(app_module.api_period_detail(_Req(config.OPERATOR_USER), "199901"))
    assert response.status_code == 404


def test_操作员期次列表放行(monkeypatch):
    body = asyncio.run(app_module.api_periods(_Req(config.OPERATOR_USER)))
    assert isinstance(body, dict) and "periods" in body


def test_匿名仍401():
    assert asyncio.run(app_module.api_period_detail(_Req(), "202609")).status_code == 401
    assert asyncio.run(app_module.api_periods(_Req())).status_code == 401
