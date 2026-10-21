# -*- coding: utf-8 -*-
"""证据面可见性：角色 × 证据类 × 动作的唯一表。

这是 `server/visibility.py` 的接口测试；路由/页面只是 adapter，
不应该再各自写一份“谁是 admin”的规则。
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import config, visibility                      # noqa: E402
from server import app as app_module                       # noqa: E402


def test_admin可以看和下载全部证据类():
    for evidence in visibility.EVIDENCE:
        assert visibility.allowed("admin", evidence, "see") is True
        assert visibility.allowed("admin", evidence, "download") is True


def test_操作员的证据边界():
    # 只读开放：档案、溯源、红件数据、水位、沙盘、调用留痕
    for evidence in ("archive", "trace", "redslots", "ai_calls", "water", "sandbox",
                     "report", "chart", "collation", "acquisition"):
        assert visibility.allowed("operator", evidence, "see") is True
        assert visibility.allowed("operator", evidence, "download") is True
    # 仍 admin：红件三件、运行日志、日志包、原始主台账
    for evidence in ("red_list", "red_view", "red_json", "runlog", "logpack", "ledger"):
        assert visibility.allowed("operator", evidence, "see") is False
        assert visibility.allowed("operator", evidence, "download") is False


def test_未知角色按操作员兜底():
    assert visibility.allowed("", "red_list") is False
    assert visibility.allowed("random", "red_list") is False
    assert visibility.view_allowed("", "ledger") is False


def test_页面可见性只有原始主台账是_admin():
    denied = [v for v in visibility.VIEWS if not visibility.view_allowed("operator", v)]
    assert denied == ["ledger"]
    assert visibility.view_allowed("operator", "archive") is True
    assert visibility.view_allowed("operator", "heal") is True


def test_写动作边界():
    assert visibility.action_allowed("operator", "edit") is False
    assert visibility.action_allowed("operator", "rollback") is False
    assert visibility.action_allowed("operator", "sign") is True
    assert visibility.action_allowed("operator", "run") is True
    assert visibility.action_allowed("admin", "edit") is True


def test_产物清单过滤走同一张表():
    items = [{"key": "report"}, {"key": "red_list"}, {"key": "logpack"}, {"key": "chart"}]
    assert visibility.visible("admin", items) == items
    assert [a["key"] for a in visibility.visible("operator", items)] == ["report", "chart"]


def test_capabilities是一份完整表():
    caps = visibility.capabilities("operator")
    assert set(caps) == {"views", "see", "download", "actions"}
    assert caps["views"]["ledger"] is False and caps["views"]["archive"] is True
    assert caps["see"]["red_list"] is False and caps["see"]["archive"] is True
    assert caps["download"]["logpack"] is False and caps["download"]["report"] is True
    assert caps["actions"]["sign"] is True and caps["actions"]["edit"] is False


def test_api_me带_capabilities():
    class _Req:
        def __init__(self, user):
            self.session = {"user": user} if user else {}

    operator = asyncio.run(app_module.api_me(_Req(config.OPERATOR_USER)))
    assert operator["role"] == "operator"
    assert operator["capabilities"]["views"]["ledger"] is False
    assert operator["capabilities"]["download"]["red_list"] is False

    admin = asyncio.run(app_module.api_me(_Req(config.ADMIN_USER)))
    assert admin["capabilities"]["download"]["red_list"] is True
    assert asyncio.run(app_module.api_me(_Req(None))).status_code == 401
