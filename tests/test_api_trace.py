# -*- coding: utf-8 -*-
"""GET /api/periods/{period}/trace 逐格溯源 JSON（契约 §2.2 #13）。

验的是：workbench.trace 的装配（真读台账）+ 分页形状 + 权限门 + ledger 不回绝对路径。
"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import config, workbench                           # noqa: E402
from server import app as app_module                           # noqa: E402
from server.app import _TRACE_CATS, _paginate, _find_ledger, resolve_period_dir  # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _trace_of(period):
    d = resolve_period_dir(period)
    if d is None:
        return None, None
    ledger = _find_ledger()
    if ledger is None:
        return d, None
    return d, workbench.trace(d, ledger, prev=None)


class TestTrace装配:
    def test_trace返回五类加元数据(self, repo):
        d, data = _trace_of("202607")
        if d is None or data is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 或台账缺失", lambda: resolve_period_dir("202607") is not None)
        assert set(_TRACE_CATS) <= set(data.keys())
        assert "cols" in data and "discs" in data
        assert "n" in data

    def test_大表每行有loc和report(self, repo):
        d, data = _trace_of("202607")
        if d is None or data is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 或台账缺失", lambda: resolve_period_dir("202607") is not None)
        for rec in data["bigtable"]:
            assert "loc" in rec
            assert "report" in rec
            assert "sheet" in rec
            assert "how" in rec

    def test_图表行有loc和src(self, repo):
        d, data = _trace_of("202607")
        if d is None or data is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 或台账缺失", lambda: resolve_period_dir("202607") is not None)
        for rec in data["charts"]:
            assert "loc" in rec
            assert "src" in rec

    def test_省域行有可读label(self, repo):
        d, data = _trace_of("202607")
        if d is None or data is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 或台账缺失", lambda: resolve_period_dir("202607") is not None)
        for rec in data["province"]:
            if rec.get("label"):
                assert "·" in rec["label"] or rec["label"]


class Test分页适配:
    def test_大表可按limit分页(self, repo):
        d, data = _trace_of("202607")
        if d is None or data is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 或台账缺失", lambda: resolve_period_dir("202607") is not None)
        page = _paginate(data["bigtable"], 50, 0)
        assert page["total"] == len(data["bigtable"])
        assert len(page["rows"]) == min(50, page["total"])
        assert page["has_more"] == (page["total"] > 50)


class Test权限与安全:
    def test_trace对操作员只读开放(self):
        """2026-10-20 决赛证据面：逐格溯源只读开放；写口仍 admin。"""
        view = asyncio.run(app_module.api_period_trace(
            _Req(config.OPERATOR_USER), "202609"))
        assert isinstance(view, dict) and view["period"] == "202609" and "rows" in view
        assert asyncio.run(app_module.api_period_trace(
            _Req(None), "202609")).status_code == 401

    def test_trace路由是GET_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/trace")' in src

    def test_ledger只回文件名不回绝对路径(self, tmp_path, monkeypatch):
        """接口层只回文件名，别把服务器目录结构发给前端。"""
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: tmp_path)
        monkeypatch.setattr(app_module, "_find_ledger",
                            lambda: pathlib.Path("C:/secret/input/云大全学科排名、阈值动态检测表.xlsx"))
        monkeypatch.setattr(workbench, "trace",
                            lambda d, ledger, prev=None: {
                                "bigtable": [], "charts": [], "province": [],
                                "matrix": [], "texts": [], "n": 0,
                                "cols": [], "discs": []})
        monkeypatch.setattr(workbench, "load_review", lambda d: {})
        r = asyncio.run(app_module.api_period_trace(_Req(config.ADMIN_USER), "202609"))
        assert r["ledger"] == "云大全学科排名、阈值动态检测表.xlsx"
        assert "\\" not in r["ledger"] and "/" not in r["ledger"]

    def test_台账缺失时报500(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: tmp_path)
        monkeypatch.setattr(app_module, "_find_ledger", lambda: None)
        r = asyncio.run(app_module.api_period_trace(_Req(config.ADMIN_USER), "202609"))
        assert isinstance(r, dict)
        assert r["ledger_ok"] is False and r["ledger_error"]

    def test_cat白名单(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: tmp_path)
        monkeypatch.setattr(app_module, "_find_ledger", lambda: None)
        r = asyncio.run(app_module.api_period_trace(
            _Req(config.ADMIN_USER), "202609", "不认识的类"))
        assert r["cat"] == "bigtable"
        assert set(r["counts"]) == set(app_module._TRACE_CATS)
