# -*- coding: utf-8 -*-
"""内嵌报告内容的静态资源也必须经过登录门与角色门（2026-10-11 角色改两级后）。"""
import asyncio

from server import config
from server.protected_static import AdminStaticFiles
from starlette.responses import Response


def _scope(user=None):
    return {"method": "GET", "headers": [], "path": "/", "session": {"user": user} if user else {}}


def _html_scope(user=None):
    scope = _scope(user)
    scope["headers"] = [(b"accept", b"text/html,application/xhtml+xml")]
    return scope


def _files(tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    (shelf / "index.html").write_text("public shelf", encoding="utf-8")
    (shelf / "data.js").write_text("secret", encoding="utf-8")
    (tmp_path / "collation-demo.html").write_text("secret", encoding="utf-8")
    return AdminStaticFiles(
        directory=str(tmp_path),
        protected_paths=("shelf/data.js", "collation-demo.html"),
        user_responses={"shelf/data.js": lambda: Response("window.WH_DATA={full:true}")})


def test_静态挂载根路径仍返回首页(tmp_path):
    (tmp_path / "index.html").write_text("public home", encoding="utf-8")
    files = AdminStaticFiles(directory=str(tmp_path), html=True)
    operator = asyncio.run(files.get_response(".", _scope(config.OPERATOR_USER)))
    admin = asyncio.run(files.get_response(".", _scope(config.ADMIN_USER)))
    assert operator.status_code == 200
    assert admin.status_code == 200


def test_书架页面仍可打开_数据两种角色都可读(tmp_path):
    files = _files(tmp_path)
    assert asyncio.run(files.get_response("shelf/index.html",
                                          _scope(config.OPERATOR_USER))).status_code == 200
    anonymous = asyncio.run(files.get_response("shelf/data.js", _scope()))
    operator = asyncio.run(files.get_response("shelf/data.js", _scope(config.OPERATOR_USER)))
    admin = asyncio.run(files.get_response("shelf/data.js", _scope(config.ADMIN_USER)))
    assert anonymous.status_code == 303 and anonymous.headers["cache-control"] == "no-store"
    # 2026-10-11：操作员与管理员同拿全数据（guest 预览边界取消）——绝不落回磁盘原文件。
    assert operator.status_code == 200 and b"full" in operator.body and b"secret" not in operator.body
    assert operator.headers["cache-control"] == "private, no-store"
    assert operator.headers["vary"] == "Cookie"
    assert admin.status_code == 200 and b"full" in admin.body and b"secret" not in admin.body
    assert admin.headers["cache-control"] == "private, no-store"
    assert admin.headers["vary"] == "Cookie"


def test_反斜杠与父目录绕过不能读到书架数据(tmp_path):
    files = _files(tmp_path)
    bypass = asyncio.run(files.get_response("shelf\\data.js", _scope(config.OPERATOR_USER)))
    assert b"secret" not in bypass.body                    # 归一化后仍走角色响应，不落原文件
    assert asyncio.run(files.get_response("x/../shelf/data.js",
                                          _scope(config.ADMIN_USER))).status_code == 404


def test_Windows_大小写和尾随点空格别名不能绕过(tmp_path):
    files = _files(tmp_path)
    for path in ("shelf/DATA.JS", "shelf/data.js. "):
        resp = asyncio.run(files.get_response(path, _scope(config.OPERATOR_USER)))
        assert b"secret" not in resp.body, path
    # 无角色响应的受保护文件（对勘快照）：操作员 403。
    assert asyncio.run(files.get_response("COLLATION-DEMO.HTML. ",
                                          _scope(config.OPERATOR_USER))).status_code == 403


def test_陈列馆数据按角色分别响应(tmp_path):
    (tmp_path / "shelf").mkdir()
    files = AdminStaticFiles(
        directory=str(tmp_path), protected_paths=("shelf/data.js",),
        user_responses={"shelf/data.js": lambda: Response("window.WH_DATA={full:true}")},
        admin_responses={"shelf/data.js": lambda: Response("window.WH_DATA={metrics:true}")},
    )
    anonymous = asyncio.run(files.get_response("shelf/data.js", _scope()))
    operator = asyncio.run(files.get_response("shelf/data.js", _scope(config.OPERATOR_USER)))
    admin = asyncio.run(files.get_response("shelf/data.js", _scope(config.ADMIN_USER)))
    assert anonymous.status_code == 303
    assert operator.status_code == 200 and b"full" in operator.body and b"secret" not in operator.body
    assert operator.headers["cache-control"] == "private, no-store"
    assert operator.headers["vary"] == "Cookie"
    assert admin.status_code == 200 and b"metrics" in admin.body
    assert admin.headers["cache-control"] == "private, no-store"
    assert admin.headers["vary"] == "Cookie"


def test_对勘快照同样保护(tmp_path):
    files = _files(tmp_path)
    assert asyncio.run(files.get_response("collation-demo.html",
                                          _scope(config.OPERATOR_USER))).status_code == 403


def test_登录门_导航显示请先登录页_其余请求回登录页(tmp_path):
    """`/app` 用 require_login=True：未登录的**导航**请求看到「请先登录」卡（不跳转）；
    fetch/素材等非导航请求仍 303 回 /login（前端据此识别登录态）。"""
    (tmp_path / "index.html").write_text("workspace", encoding="utf-8")
    files = AdminStaticFiles(directory=str(tmp_path), html=True, require_login=True)
    gate = asyncio.run(files.get_response(".", _html_scope()))
    body = gate.body.decode("utf-8")
    assert gate.status_code == 200
    assert "请先登录" in body and "前往登录" in body and 'href="/login"' in body
    assert gate.headers["cache-control"] == "no-store"
    # 非导航（没有 Accept: text/html）：303 回登录页；找不到的文件也不泄漏存在性
    redirect = asyncio.run(files.get_response(".", _scope()))
    assert redirect.status_code == 303 and redirect.headers["location"] == "/login"
    assert asyncio.run(files.get_response("nope.js", _scope())).status_code == 303
    for user in (config.OPERATOR_USER, config.ADMIN_USER):
        assert asyncio.run(files.get_response(".", _scope(user))).status_code == 200


def test_登录门与角色门组合_操作员与管理员都能读书架数据(tmp_path):
    (tmp_path / "shelf").mkdir()
    (tmp_path / "shelf" / "index.html").write_text("shelf", encoding="utf-8")
    (tmp_path / "shelf" / "data.js").write_text("secret", encoding="utf-8")
    files = AdminStaticFiles(
        directory=str(tmp_path), require_login=True, protected_paths=("shelf/data.js",),
        user_responses={"shelf/data.js": lambda: Response("window.WH_DATA={full:true}")},
        admin_responses={"shelf/data.js": lambda: Response("window.WH_DATA={metrics:true}")},
    )
    assert asyncio.run(files.get_response("shelf/index.html", _scope())).status_code == 303
    assert asyncio.run(files.get_response("shelf/data.js", _scope())).status_code == 303
    operator = asyncio.run(files.get_response("shelf/data.js", _scope(config.OPERATOR_USER)))
    assert operator.status_code == 200 and b"full" in operator.body and b"secret" not in operator.body
    admin = asyncio.run(files.get_response("shelf/data.js", _scope(config.ADMIN_USER)))
    assert admin.status_code == 200 and b"metrics" in admin.body
