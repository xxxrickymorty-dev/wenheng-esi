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
from server.app import require_admin, require_user           # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


class TestRoleOf:
    """2026-10-11 角色改两级：admin / operator（guest 取消，未知一律按操作员兜底）。"""

    def test_admin是admin(self):
        assert config.role_of(config.ADMIN_USER) == "admin"

    def test_操作员是operator(self):
        assert config.role_of(config.OPERATOR_USER) == "operator"

    def test_未知用户默认operator(self):
        assert config.role_of("random") == "operator"

    def test_空用户名是operator(self):
        assert config.role_of("") == "operator"


class TestRequireAdmin:
    def test_未登录_401(self):
        r = require_admin(_Req(None))
        assert isinstance(r, JSONResponse)
        assert r.status_code == 401

    def test_操作员_403(self):
        r = require_admin(_Req(config.OPERATOR_USER))
        assert isinstance(r, JSONResponse)
        assert r.status_code == 403

    def test_admin_通过(self):
        r = require_admin(_Req(config.ADMIN_USER))
        assert r == config.ADMIN_USER


class TestRequireUser:
    """只读端点门：已登录即可（管理员与操作员都放行）。"""

    def test_未登录_401(self):
        r = require_user(_Req(None))
        assert isinstance(r, JSONResponse)
        assert r.status_code == 401

    def test_操作员通过(self):
        assert require_user(_Req(config.OPERATOR_USER)) == config.OPERATOR_USER

    def test_admin通过(self):
        assert require_user(_Req(config.ADMIN_USER)) == config.ADMIN_USER


class TestLogin口令:
    """2026-10-11 角色改两级后：管理员与操作员各一套口令，登录都落工作区。"""

    def test_admin可登(self):
        from server.app import check_credentials
        assert check_credentials(config.ADMIN_USER, config.ADMIN_PASS)

    def test_操作员可登(self):
        from server.app import check_credentials
        assert check_credentials(config.OPERATOR_USER, config.OPERATOR_PASS)

    def test_错口令与陌生账号不可登(self):
        from server.app import check_credentials
        assert not check_credentials(config.ADMIN_USER, "wrong")
        assert not check_credentials(config.OPERATOR_USER, "wrong")
        assert not check_credentials("random", "random")
        assert not check_credentials("", "")

    def test_两角色登录都落陈列馆(self, monkeypatch):
        """2026-10-12：登录先落陈列馆首页（看 → 问 → 做）；工作区从对话页「去生成台」进。"""
        class LoginRequest:
            client = type("Client", (), {"host": "test"})()

            def __init__(self):
                self.session = {}

        monkeypatch.setattr(app_module, "_login_fails", {})
        operator_request = LoginRequest()
        admin_request = LoginRequest()
        operator = asyncio.run(app_module.do_login(
            operator_request, config.OPERATOR_USER, config.OPERATOR_PASS))
        admin = asyncio.run(app_module.do_login(
            admin_request, config.ADMIN_USER, config.ADMIN_PASS))
        assert operator.headers["location"] == "/app/shelf/"
        assert admin.headers["location"] == "/app/shelf/"


class TestAdmin写端点上锁:
    """写动作：操作员 403 / 匿名 401（判别统一由 @admin_route 承担）。"""

    def test_forecast_run用require_admin(self):
        assert asyncio.run(app_module.api_forecast_run(
            _Req(config.OPERATOR_USER))).status_code == 403
        assert asyncio.run(app_module.api_forecast_run(_Req(None))).status_code == 401

    def test_create_job用require_admin(self):
        assert asyncio.run(app_module.api_create_job(
            _Req(config.OPERATOR_USER))).status_code == 403
        assert asyncio.run(app_module.api_create_job(_Req(None))).status_code == 401

    def test_sign用require_admin(self):
        assert asyncio.run(app_module.api_period_sign_json(
            _Req(config.OPERATOR_USER), "202609")).status_code == 403

    def test_rollback用require_admin(self):
        assert asyncio.run(app_module.api_rollback(
            _Req(config.OPERATOR_USER), "202609")).status_code == 403


class Test只读端点放行操作员:
    """只读端点：操作员放行（拿不到管理员门，404/正常体即证明门放行）。"""

    def test_api_periods放行(self):
        body = asyncio.run(app_module.api_periods(_Req(config.OPERATOR_USER)))
        assert isinstance(body, dict) and "periods" in body
        assert asyncio.run(app_module.api_periods(_Req(None))).status_code == 401

    def test_api_me角色如实(self):
        me = asyncio.run(app_module.api_me(_Req(config.OPERATOR_USER)))
        assert me["name"] == config.OPERATOR_USER and me["role"] == "operator"
        assert asyncio.run(app_module.api_me(_Req(None))).status_code == 401

    def test_api_period_detail放行(self):
        # 不存在的期次应回「期次不存在」404——若门没放行会是 403。
        assert asyncio.run(app_module.api_period_detail(
            _Req(config.OPERATOR_USER), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_detail(
            _Req(None), "199901")).status_code == 401

    def test_api_job与events放行(self):
        assert asyncio.run(app_module.api_job(
            _Req(config.OPERATOR_USER), "nonexistent")).status_code == 404
        assert asyncio.run(app_module.api_events(
            _Req(config.OPERATOR_USER), "nonexistent")).status_code == 404

    def test_api_approval放行(self):
        assert asyncio.run(app_module.api_approval(
            _Req(config.OPERATOR_USER), "nonexistent")).status_code == 404


class TestPalette:
    def test_palette三色与G陈列馆同值(self):
        assert config.PALETTE["primary"] == "#B8422C"
        assert config.PALETTE["deep"] == "#8A2A18"
        assert config.PALETTE["lift"] == "#D65A38"
