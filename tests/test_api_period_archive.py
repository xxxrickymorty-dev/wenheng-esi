# -*- coding: utf-8 -*-
"""GET /api/periods/{period}/archive 运行档案 JSON（契约 §2.2 #16）。

与档案页同源（archive.build）；安全要求：不回服务器绝对路径。
另锁一个 2026-09-24 修的既有 bug：期次上下文的「对勘本」产物链接
原拼成 /p/{期次}/collation（无此路由）→ 现指回 /p/{期次}。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import archive, config, jobs                       # noqa: E402
from server.app import resolve_period_dir                      # noqa: E402
from server import app as app_module                           # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


class Test产物链接修复:
    def test_期次上下文对勘本链接指回期次页(self, repo):
        d = resolve_period_dir("202607")
        if d is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
        arts = jobs.collect_period_artifacts(d.name)
        coll = next((a for a in arts if a["key"] == "collation"), None)
        if coll is None:
            return
        assert coll["url"] == "/p/202607", f"got {coll['url']}"
        assert coll["url"] != "/p/202607/collation"


class TestArchive组装:
    def test_build含六块(self, repo):
        d = resolve_period_dir("202607")
        if d is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
        view = archive.build(d, job=None,
                             artifacts=jobs.collect_period_artifacts(d.name))
        for k in ("period", "waterfall", "replay", "audit", "env", "logpack", "artifacts"):
            assert k in view, k
        assert view["logpack"]["key"] == "logpack"

    def test_接口层剥掉绝对路径(self, tmp_path, monkeypatch):
        d = tmp_path / "202609"
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: d)
        monkeypatch.setattr(app_module.jobs, "list_jobs", lambda *a, **k: [])
        monkeypatch.setattr(app_module.jobs, "collect_period_artifacts", lambda name: [])
        raw = {"out_dir": "C:/abs/out", "progress_path": "C:/abs/p.jsonl",
               "job": {"input": "C:/abs/input/监测表.xlsx"}, "stats": {}, "run_log": {},
               "logpack": {"key": "logpack"}}
        monkeypatch.setattr(app_module.archive, "build", lambda *a, **k: dict(raw))
        view = asyncio.run(app_module.api_period_archive(_Req(config.ADMIN_USER), "202609"))
        assert "out_dir" not in view and "progress_path" not in view
        assert view["job"]["input"] == "监测表.xlsx", "绝对路径必须转仓库相对/文件名"
        assert view["download_base"] == "/p/202609"
        assert view["logpack_url"] == "/p/202609/download/logpack"


class Test权限:
    def test_操作员可读_匿名401(self):
        """2026-10-20 决赛证据面：运行档案对操作员只读开放（写口仍 admin）。"""
        if resolve_period_dir("202609") is None:
            from _guard_registry import skip_unless
            skip_unless("out/202609 不存在", lambda: resolve_period_dir("202609") is not None)
        view = asyncio.run(app_module.api_period_archive(
            _Req(config.OPERATOR_USER), "202609"))
        assert isinstance(view, dict) and view["period"] == "202609"
        assert asyncio.run(app_module.api_period_archive(
            _Req(None), "202609")).status_code == 401

    def test_路由是GET(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/archive")' in src
