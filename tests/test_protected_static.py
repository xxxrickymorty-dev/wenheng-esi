# -*- coding: utf-8 -*-
"""内嵌报告内容的静态资源也必须经过管理员门。"""
import asyncio

from server import config
from server.protected_static import AdminStaticFiles


def _scope(user=None):
    return {"method": "GET", "headers": [], "session": {"user": user} if user else {}}


def _files(tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    (shelf / "index.html").write_text("public shelf", encoding="utf-8")
    (shelf / "data.js").write_text("secret", encoding="utf-8")
    (tmp_path / "collation-demo.html").write_text("secret", encoding="utf-8")
    return AdminStaticFiles(directory=str(tmp_path),
                            protected_paths=("shelf/data.js", "collation-demo.html"))


def test_书架页面仍可打开_数据仅管理员可读(tmp_path):
    files = _files(tmp_path)
    assert asyncio.run(files.get_response("shelf/index.html", _scope(config.GUEST_USER))).status_code == 200
    anonymous = asyncio.run(files.get_response("shelf/data.js", _scope()))
    guest = asyncio.run(files.get_response("shelf/data.js", _scope(config.GUEST_USER)))
    assert anonymous.status_code == 303 and anonymous.headers["cache-control"] == "no-store"
    assert guest.status_code == 403 and guest.headers["cache-control"] == "no-store"
    assert asyncio.run(files.get_response("shelf/data.js", _scope(config.DEMO_USER))).status_code == 200


def test_反斜杠与父目录绕过不能读到书架数据(tmp_path):
    files = _files(tmp_path)
    assert asyncio.run(files.get_response("shelf\\data.js", _scope(config.GUEST_USER))).status_code == 403
    assert asyncio.run(files.get_response("x/../shelf/data.js", _scope(config.DEMO_USER))).status_code == 404


def test_对勘快照同样保护(tmp_path):
    files = _files(tmp_path)
    assert asyncio.run(files.get_response("collation-demo.html", _scope(config.GUEST_USER))).status_code == 403
