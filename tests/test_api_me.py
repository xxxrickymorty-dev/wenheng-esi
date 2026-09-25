# -*- coding: utf-8 -*-
"""GET /api/me + 权限门（契约 §2.2 #1 / §4）。

仓库测试惯例是函数级（不依赖 httpx/TestClient），HTTP 级由 e2e_check.py 覆盖。
这里验的是 role_of / require_admin 的门真的门住了。
"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.responses import JSONResponse                  # noqa: E402
from server import config                                    # noqa: E402
from server import app as app_module                         # noqa: E402
from server.app import require_admin                         # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


class TestRoleOf:
    def test_demo是admin(self):
        assert config.role_of(config.DEMO_USER) == "admin"

    def test_guest是guest(self):
        assert config.role_of(config.GUEST_USER) == "guest"

    def test_未知用户默认guest(self):
        assert config.role_of("random") == "guest"

    def test_空用户名是guest(self):
        assert config.role_of("") == "guest"


class TestRequireAdmin:
    def test_未登录_401(self):
        r = require_admin(_Req(None))
        assert isinstance(r, JSONResponse)
        assert r.status_code == 401

    def test_guest_403(self):
        r = require_admin(_Req(config.GUEST_USER))
        assert isinstance(r, JSONResponse)
        assert r.status_code == 403

    def test_admin_通过(self):
        r = require_admin(_Req(config.DEMO_USER))
        assert r == config.DEMO_USER


class TestLogin口令:
    """2026-09-24 修：/login 只认 demo，guest 定义了却登不进来（前端实报）。"""

    def test_demo可登(self):
        from server.app import check_credentials
        assert check_credentials(config.DEMO_USER, config.DEMO_PASS)

    def test_guest可登(self):
        from server.app import check_credentials
        assert check_credentials(config.GUEST_USER, config.GUEST_PASS)

    def test_错口令与陌生账号不可登(self):
        from server.app import check_credentials
        assert not check_credentials(config.DEMO_USER, "wrong")
        assert not check_credentials(config.GUEST_USER, "wrong")
        assert not check_credentials("random", "random")
        assert not check_credentials("", "")

    def test_guest登录直达陈列馆_admin保持原落点(self, monkeypatch):
        class LoginRequest:
            client = type("Client", (), {"host": "test"})()

            def __init__(self):
                self.session = {}

        monkeypatch.setattr(app_module, "_login_fails", {})
        guest_request = LoginRequest()
        admin_request = LoginRequest()
        guest = asyncio.run(app_module.do_login(guest_request, config.GUEST_USER, config.GUEST_PASS))
        admin = asyncio.run(app_module.do_login(admin_request, config.DEMO_USER, config.DEMO_PASS))
        assert guest.headers["location"] == "/app/shelf/"
        assert admin.headers["location"] == "/"


class TestAdmin端点上锁:
    def test_forecast_meta用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_forecast_meta")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_forecast_run用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_forecast_run")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_create_job用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_create_job")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_api_job用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_job(")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_api_events用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_events")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_api_approval用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_approval")[1].split("@app.")[0]
        assert "require_admin" in block


class TestGuest可读端点:
    def test_api_periods已锁admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_periods")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_api_me不锁admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_me")[1].split("@app.")[0]
        assert "require_admin" not in block

    def test_api_period_detail已锁admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_detail")[1].split("@app.")[0]
        assert "require_admin" in block


class TestPalette:
    def test_palette三色与G陈列馆同值(self):
        assert config.PALETTE["primary"] == "#B8422C"
        assert config.PALETTE["deep"] == "#8A2A18"
        assert config.PALETTE["lift"] == "#D65A38"
