# -*- coding: utf-8 -*-
"""GET /api/jobs/{job_id}/progress 任务瀑布 JSON（契约 §2.2 #15）。

与档案页同口径：archive.waterfall 把 progress.jsonl 事件转成每步耗时。
"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import archive, config, jobs                       # noqa: E402
from server import app as app_module                           # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _sample_events():
    return [
        {"ts": "10:00:00", "step": "parse", "name": "解析台账", "status": "start", "detail": "", "elapsed": 0.0},
        {"ts": "10:00:00", "step": "parse", "name": "解析台账", "status": "warn", "detail": "撤下旧成品", "elapsed": 0.2},
        {"ts": "10:00:01", "step": "parse", "name": "解析台账", "status": "done", "detail": "当期 202607", "elapsed": 0.4},
        {"ts": "10:00:01", "step": "compute", "name": "计算大表与概述", "status": "start", "detail": "", "elapsed": 0.4},
        {"ts": "10:00:03", "step": "compute", "name": "计算大表与概述", "status": "done", "detail": "22 学科", "elapsed": 2.9},
    ]


class Test瀑布口径:
    def test_每步耗时是收工减开工(self):
        rows = archive.waterfall(_sample_events())
        by = {r["step"]: r for r in rows}
        assert by["parse"]["sec"] == 0.4
        assert by["compute"]["sec"] == 2.5

    def test_状态取收工事件(self):
        rows = archive.waterfall(_sample_events())
        by = {r["step"]: r for r in rows}
        assert by["parse"]["status"] == "done"
        assert by["parse"]["detail"] == "当期 202607"

    def test_只有开工没收工标orphan(self):
        ev = [{"ts": "10:00", "step": "docx", "name": "填充报告", "status": "start", "elapsed": 3.0}]
        rows = archive.waterfall(ev)
        assert rows[0]["orphan"] is True and rows[0]["sec"] == 0.0

    def test_完成汇总不进步骤数组(self):
        """「完成」只有收工、elapsed=总时长，不是一步——不进 waterfall 数组
        （混进去合计翻倍 96.5→193.0，2026-09-24 前端实报）；单列 waterfall_summary。"""
        ev = [
            {"ts": "10:00", "step": "charts", "name": "图表渲染", "status": "start", "elapsed": 66.4},
            {"ts": "10:00:26", "step": "charts", "name": "图表渲染", "status": "done", "elapsed": 93.3},
            {"ts": "10:00:26", "step": "done", "name": "完成", "status": "done",
             "detail": "全链路 96.5 秒", "elapsed": 96.5},
        ]
        rows = archive.waterfall(ev)
        assert [r["step"] for r in rows] == ["charts"]        # 无「完成」伪步骤
        assert round(sum(r["sec"] for r in rows), 1) == 26.9  # 合计不翻倍
        s = archive.waterfall_summary(ev)
        assert s["sec"] == 96.5 and s["name"] == "完成" and "96.5" in s["detail"]

    def test_无完成事件时summary为None(self):
        assert archive.waterfall_summary(_sample_events()) is None

    def test_同秒步骤按事件顺序不按名字(self):
        """同一秒开工的四步：parse → compute → forecast → province（执行序）。
        旧实现按名字排会把 compute 排到 parse 前（2026-09-24 前端实报）。"""
        ev = []
        for st in ("parse", "compute", "forecast", "province"):
            ev.append({"ts": "10:00:00", "step": st, "name": st, "status": "start",
                       "elapsed": 0.0})
            ev.append({"ts": "10:00:01", "step": st, "name": st, "status": "done",
                       "elapsed": 1.0})
        rows = archive.waterfall(ev)
        assert [r["step"] for r in rows] == ["parse", "compute", "forecast", "province"]

    def test_空事件返回空(self):
        assert archive.waterfall([]) == []
        assert archive.waterfall(None) == []


class Test真实任务:
    def test_真实job的progress可解析(self, repo):
        cands = sorted((repo / "out" / "_jobs").glob("*/job.json"))
        if not cands:
            from _guard_registry import skip_unless
            skip_unless("out/_jobs 无任务", lambda: bool(list((repo / "out" / "_jobs").glob("*/job.json"))))
        job = jobs.read_job(cands[-1].parent.name)
        events = jobs.read_progress(job)
        if events:
            rows = archive.waterfall(events)
            assert len(rows) > 0
            assert all("sec" in r and "step" in r for r in rows)


class Test路由与权限:
    def test_路由是GET_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/jobs/{job_id}/progress")' in src

    def test_用require_admin(self):
        assert asyncio.run(app_module.api_job_progress(
            _Req(config.GUEST_USER), "jid")).status_code == 403
        assert asyncio.run(app_module.api_job_progress(_Req(None), "jid")).status_code == 401

    def test_复用archive_waterfall不重造轮子(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_job_progress")[1].split("@app.")[0]
        assert "archive.waterfall" in block

    def test_missing降级不500(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_job_progress")[1].split("@app.")[0]
        assert '"missing": missing' in block and '"note"' in block
