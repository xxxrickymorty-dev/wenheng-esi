# -*- coding: utf-8 -*-
"""GET /api/status 的登录门与最小响应契约（含本机数据存储能不能写）。"""
import asyncio
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.responses import JSONResponse  # noqa: E402
from server import config  # noqa: E402
from server import app as app_module  # noqa: E402
from src import state_store  # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _call(user):
    return asyncio.run(app_module.api_status(_Req(user)))


def _body(response):
    assert isinstance(response, JSONResponse)
    return json.loads(response.body)


def _isolate(monkeypatch, db):
    """把 /api/status 的状态库与任务记录都指到 tmp（不碰演示数据）。"""
    monkeypatch.setattr(app_module.jobs, "state_db_path", lambda: db)
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: None)
    monkeypatch.setattr(app_module.jobs, "list_jobs", lambda _limit: [])


def _healthy_state_db():
    """库还没建时的 state_db 形状（库不存在＝正常：还没签过单）。"""
    return {"ok": True, "schema_version": 0,
            "code_schema_version": state_store.SCHEMA_VERSION,
            "degraded": False, "message": ""}


class TestApiStatus:
    def test_未登录返回401(self):
        response = _call(None)
        assert response.status_code == 401
        assert _body(response) == {"error": "未登录", "hint": "请先登录"}

    def test_状态响应只给标识不给内部字段(self, monkeypatch, tmp_path):
        """2026-10-11：/api/status 是只读，操作员与管理员同份（stats/路径不下发）。"""
        _isolate(monkeypatch, tmp_path / "_state" / "wenheng.sqlite")
        active = {"id": "running-1", "period": "202609", "stats": {"secret": 1}}
        last = {
            "id": "done-1",
            "period": "202607",
            "stats": {"output": "C:/private/out/202607"},
            "progress": "C:/private/out/_jobs/done-1.json",
        }
        monkeypatch.setattr(app_module.jobs, "active_job", lambda: active)
        monkeypatch.setattr(app_module.jobs, "list_jobs", lambda _limit: [last])

        expected = {"active": "running-1", "last": {"id": "done-1", "period": "202607"},
                    "state_db": _healthy_state_db()}
        assert _call(config.OPERATOR_USER) == expected
        assert _call(config.ADMIN_USER) == expected

    def test_无已完成任务返回空last(self, monkeypatch, tmp_path):
        _isolate(monkeypatch, tmp_path / "_state" / "wenheng.sqlite")
        assert _call(config.ADMIN_USER) == {"active": None, "last": None,
                                            "state_db": _healthy_state_db()}


class TestStateDbStatus:
    """本机数据存储能不能写：库不存在＝正常；版本比程序新＝只读降级且给一句人话。"""

    def test_库不存在报正常且不顺手建库(self, monkeypatch, tmp_path):
        db = tmp_path / "_state" / "wenheng.sqlite"
        _isolate(monkeypatch, db)
        body = _call(config.OPERATOR_USER)
        assert body["state_db"] == _healthy_state_db()
        assert not db.exists()
        assert not db.parent.exists()          # 连目录都不建（读口不造库）

    def test_库版本高于代码报只读降级(self, monkeypatch, tmp_path):
        db = tmp_path / "_state" / "wenheng.sqlite"
        state_store.put_approval(db, "202607", {"status": "signed", "note": "探针"})
        with sqlite3.connect(str(db)) as con:
            con.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        _isolate(monkeypatch, db)

        body = _call(config.ADMIN_USER)
        sdb = body["state_db"]
        assert sdb["ok"] is False and sdb["degraded"] is True
        assert sdb["schema_version"] == 99
        assert sdb["code_schema_version"] == state_store.SCHEMA_VERSION
        # 既有字段照旧（新增字段不许挤掉它们）
        assert body["active"] is None and body["last"] is None
        # 文案是给馆员看的：不出现技术词，且说到「只读」与「找管理员」
        for word in ("sqlite", "SQLite", "schema", "迁移", "PRAGMA"):
            assert word not in sdb["message"]
        assert "只读" in sdb["message"] and "管理员" in sdb["message"]
        # 降级不拒启动、不炸请求：库还在，读仍可用
        assert state_store.health(db)["degraded"] is True

