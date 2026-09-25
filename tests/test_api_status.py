# -*- coding: utf-8 -*-
"""GET /api/status 的登录门与最小响应契约。"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.responses import JSONResponse  # noqa: E402
from server import config  # noqa: E402
from server import app as app_module  # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _call(user):
    return asyncio.run(app_module.api_status(_Req(user)))


def _body(response):
    assert isinstance(response, JSONResponse)
    return json.loads(response.body)


class TestApiStatus:
    def test_未登录返回401(self):
        response = _call(None)
        assert response.status_code == 401
        assert _body(response) == {"error": "未登录", "hint": "请先登录"}

    def test_guest与admin可读取最小任务标识(self, monkeypatch):
        active = {"id": "running-1", "period": "202609", "stats": {"secret": 1}}
        last = {
            "id": "done-1",
            "period": "202607",
            "stats": {"output": "C:/private/out/202607"},
            "progress": "C:/private/out/_jobs/done-1.json",
        }
        monkeypatch.setattr(app_module.jobs, "active_job", lambda: active)
        monkeypatch.setattr(app_module.jobs, "list_jobs", lambda _limit: [last])

        expected = {"active": "running-1", "last": {"id": "done-1", "period": "202607"}}
        assert _call(config.GUEST_USER) == expected
        assert _call(config.DEMO_USER) == expected

    def test_无已完成任务返回空last(self, monkeypatch):
        monkeypatch.setattr(app_module.jobs, "active_job", lambda: None)
        monkeypatch.setattr(app_module.jobs, "list_jobs", lambda _limit: [])
        assert _call(config.GUEST_USER) == {"active": None, "last": None}
