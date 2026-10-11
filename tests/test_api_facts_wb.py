# -*- coding: utf-8 -*-
"""测试 facts + workbench 端点。"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _guard_registry import skip_unless                         # noqa: E402
from server import approval, workbench                          # noqa: E402
from server.app import resolve_period_dir                       # noqa: E402
from server import app as app_module, config                    # noqa: E402


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


class TestFacts:
    def test_202607有overview_facts(self, repo):
        outs = sorted((repo / "out").glob("20*/overview_facts.json")) if (repo / "out").exists() else []
        if not outs:
            skip_unless("out/ 无 overview_facts.json", lambda: bool(list((repo / "out").glob("20*/overview_facts.json"))))
        import json
        data = json.loads(outs[-1].read_text(encoding="utf-8"))
        assert "rank_intl_now" in data
        assert "top_papers_now" in data
        assert "coverage_window" in data

    def test_facts路由是GET_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/facts")' in src

    def test_facts放行操作员_匿名401(self):
        # 不存在的期次回 404——若门没放行会是 403（2026-10-11 起只读端点对操作员放行）。
        assert asyncio.run(app_module.api_period_facts(
            _Req(config.OPERATOR_USER), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_facts(
            _Req(None), "199901")).status_code == 401


class TestWorkbench:
    def test_workbench_build返回dict(self, repo):
        d = resolve_period_dir("202607")
        if d is None:
            skip_unless("out/202607 不存在", lambda: (repo / "out" / "202607").is_dir())
        rec = approval.read(d)
        data = workbench.build(d, approval=rec)
        assert "todo" in data
        assert "fills_list" in data
        assert "pending" in data
        assert "traceable" in data
        assert "n_filled" in data

    def test_workbench路由是GET_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/workbench")' in src

    def test_workbench放行操作员_匿名401(self):
        assert asyncio.run(app_module.api_period_workbench(
            _Req(config.OPERATOR_USER), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_workbench(
            _Req(None), "199901")).status_code == 401
