# -*- coding: utf-8 -*-
"""#5 forecast/meta recommendations + #18 archive 自动挂任务（2026-09-24 前端清单）。"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import forecasting                                # noqa: E402


class TestForecastMeta推荐:
    def test_page_context带推荐与基线(self):
        ctx = forecasting.page_context()
        assert "recommendations" in ctx, "契约 #16：recommendations 必须常驻"
        assert ctx.get("recommendation_baseline") == "202607"
        rec = ctx["recommendations"]
        assert set(rec.keys()) == {"citation", "rank"}
        assert all(isinstance(v, dict) and v for v in rec.values())

    def test_推荐是冻结基线不是运行时算的(self):
        """前端不写死基线表——表从后端来（写死会跟冻结口径漂移）。"""
        from esi_v1.config_v1 import BASELINE_RECOMMENDATIONS_202607
        ctx = forecasting.page_context()
        assert ctx["recommendations"] is BASELINE_RECOMMENDATIONS_202607


class TestArchive自动挂任务:
    def test_接口层会找最近任务(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_archive")[1].split("@app.")[0]
        assert "jobs.list_jobs(50)" in block
        assert "jobs.read_job(job)" in block          # ?job= 支持
        assert "job=target" in block                   # 传给 archive.build

    def test_挂任务后replay不是空链(self):
        """有任务上下文时 replay 应给出真实链（对比 job=None 的合成空链）。"""
        from server import archive, jobs
        from server.app import resolve_period_dir
        d = resolve_period_dir("202607")
        if d is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
        target = next((j for j in jobs.list_jobs(50)
                       if d.name in (j.get("period"), j.get("out_period"))), None)
        if target is None:
            from _guard_registry import skip_unless
            skip_unless("该期无历史任务", lambda: bool(jobs.list_jobs(50)))
        view = archive.build(d, job=target)
        assert view["replay"]["note"] != "无任务上下文，无法合成状态链"
        assert view["waterfall_summary"] is not None or view["waterfall"]
