# -*- coding: utf-8 -*-
"""POST /api/periods/{period}/rebuild 填完重出 JSON 版（契约 §2.2 #14）。

与表单版 POST /p/{period}/rebuild 同一套三步，顺序不能乱：
  ① 先存填值 -> ② 旧成品撤到 _superseded/ -> ③ fill_docx 重出
关键安全语义：**没填值时不碰产物**（在 quarantine 之前就返回）。
断言方式：spy 记录调用顺序、bomb 证明没走的路径，不看源码文本。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fill_docx, parse_ledger                                # noqa: E402
from server import config, workbench                          # noqa: E402
from server import app as app_module                          # noqa: E402


class _Req:
    def __init__(self, user=None, body=None):
        self.session = {"user": user} if user else {}
        self.body = body

    async def json(self):
        return self.body


def _admin(body=None):
    return _Req(config.ADMIN_USER, body)


def _rebuild_dir(tmp_path, monkeypatch):
    d = tmp_path / "202609"
    d.mkdir()
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: d)
    return d


class Test路由与权限:
    def test_rebuild路由是POST_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/rebuild")' in src

    def test_rebuild用require_admin(self):
        assert asyncio.run(app_module.api_period_rebuild_json(
            _Req(config.OPERATOR_USER), "202609")).status_code == 403
        assert asyncio.run(app_module.api_period_rebuild_json(
            _Req(None), "202609")).status_code == 401


class Test三步顺序:
    def test_先存再撤再重出(self, tmp_path, monkeypatch):
        _rebuild_dir(tmp_path, monkeypatch)
        calls = []
        monkeypatch.setattr(workbench, "save_fill",
                            lambda *a, **k: calls.append("save"))
        monkeypatch.setattr(workbench, "load_fills",
                            lambda _d: {"T01_r9c3": {"value": "33.87"}})
        monkeypatch.setattr(parse_ledger, "quarantine_final_products",
                            lambda *a, **k: calls.append("quarantine"))
        monkeypatch.setattr(fill_docx, "main",
                            lambda **k: calls.append("fill"))
        r = asyncio.run(app_module.api_period_rebuild_json(
            _admin({"items": {"T01_r9c3": "33.87"}}), "202609"))
        assert calls == ["save", "quarantine", "fill"], "先存填值，再撤旧成品，最后重出"
        assert r["ok"] is True

    def test_没填值时在quarantine之前返回(self, tmp_path, monkeypatch):
        _rebuild_dir(tmp_path, monkeypatch)
        touched = []
        monkeypatch.setattr(workbench, "save_fill", lambda *a, **k: None)
        monkeypatch.setattr(workbench, "load_fills", lambda _d: {})
        monkeypatch.setattr(parse_ledger, "quarantine_final_products",
                            lambda *a, **k: touched.append("quarantine"))
        r = asyncio.run(app_module.api_period_rebuild_json(_admin({}), "202609"))
        assert r.status_code == 409
        assert touched == [], "没填值必须不碰产物（在撤旧成品之前就返回）"

    def test_不重新解析台账(self, tmp_path, monkeypatch):
        """重出用已解析宽表（fill_docx.main 只收 ledger_dir），不调 load_ledger。"""
        d = _rebuild_dir(tmp_path, monkeypatch)
        seen = {}
        monkeypatch.setattr(workbench, "save_fill", lambda *a, **k: None)
        monkeypatch.setattr(workbench, "load_fills",
                            lambda _d: {"T01_r9c3": {"value": "33.87"}})
        monkeypatch.setattr(parse_ledger, "quarantine_final_products",
                            lambda *a, **k: None)

        def _no_parse(*a, **k):
            raise AssertionError("重出不应重新解析台账")
        monkeypatch.setattr(parse_ledger, "load_ledger", _no_parse)
        monkeypatch.setattr(fill_docx, "main", lambda **k: seen.update(k))
        r = asyncio.run(app_module.api_period_rebuild_json(_admin({}), "202609"))
        assert r["ok"] is True
        assert seen["ledger_dir"] == str(d)


class Test参数与错误:
    def test_items参数校验(self, tmp_path, monkeypatch):
        _rebuild_dir(tmp_path, monkeypatch)
        r = asyncio.run(app_module.api_period_rebuild_json(
            _admin({"items": "x"}), "202609"))
        assert r.status_code == 400
        assert "items" in json.loads(r.body)["error"]

    def test_返回ok与rebuilt(self, tmp_path, monkeypatch):
        _rebuild_dir(tmp_path, monkeypatch)
        monkeypatch.setattr(workbench, "save_fill", lambda *a, **k: None)
        monkeypatch.setattr(workbench, "load_fills",
                            lambda _d: {"T01_r9c3": {"value": "33.87"},
                                        "T02_r1c1": {"value": ""}})
        monkeypatch.setattr(parse_ledger, "quarantine_final_products",
                            lambda *a, **k: None)
        monkeypatch.setattr(fill_docx, "main", lambda **k: None)
        r = asyncio.run(app_module.api_period_rebuild_json(_admin({}), "202609"))
        assert r["ok"] is True and r["rebuilt"] == 1

    def test_错误体带hint(self, tmp_path, monkeypatch):
        d = _rebuild_dir(tmp_path, monkeypatch)
        monkeypatch.setattr(workbench, "save_fill", lambda *a, **k: None)
        scenarios = []

        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: None)
        scenarios.append(asyncio.run(app_module.api_period_rebuild_json(
            _admin({}), "202609")))

        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: d)
        scenarios.append(asyncio.run(app_module.api_period_rebuild_json(
            _admin({"items": "x"}), "202609")))

        monkeypatch.setattr(workbench, "load_fills", lambda _d: {})
        scenarios.append(asyncio.run(app_module.api_period_rebuild_json(
            _admin({}), "202609")))

        monkeypatch.setattr(workbench, "load_fills",
                            lambda _d: {"T01_r9c3": {"value": "33.87"}})
        monkeypatch.setattr(parse_ledger, "quarantine_final_products",
                            lambda *a, **k: None)

        def _boom(**k):
            raise RuntimeError("炸")
        monkeypatch.setattr(fill_docx, "main", _boom)
        scenarios.append(asyncio.run(app_module.api_period_rebuild_json(
            _admin({}), "202609")))

        assert [r.status_code for r in scenarios] == [404, 400, 409, 500]
        for r in scenarios:
            assert "hint" in json.loads(r.body)

    def test_无填值走409(self, tmp_path, monkeypatch):
        _rebuild_dir(tmp_path, monkeypatch)
        monkeypatch.setattr(workbench, "save_fill", lambda *a, **k: None)
        monkeypatch.setattr(workbench, "load_fills", lambda _d: {})
        r = asyncio.run(app_module.api_period_rebuild_json(_admin({}), "202609"))
        assert r.status_code == 409
        assert "还没有填写内容" in json.loads(r.body)["error"]
