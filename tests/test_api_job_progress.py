# -*- coding: utf-8 -*-
"""GET /api/jobs/{job_id}/progress 任务瀑布 JSON（契约 §2.2 #15）。

与档案页同口径：archive.waterfall 把 progress.jsonl 事件转成每步耗时。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import archive, jobs                              # noqa: E402


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

    def test_完成汇总行不计入合计(self):
        """「完成」只有收工、elapsed=总时长，不是一步——sec 记 0 并标 summary，
        否则合计翻倍（96.5→193.0，2026-09-24 前端实报）。"""
        ev = [
            {"ts": "10:00", "step": "charts", "name": "图表渲染", "status": "start", "elapsed": 66.4},
            {"ts": "10:00:26", "step": "charts", "name": "图表渲染", "status": "done", "elapsed": 93.3},
            {"ts": "10:00:26", "step": "done", "name": "完成", "status": "done", "elapsed": 96.5},
        ]
        rows = archive.waterfall(ev)
        by = {r["step"]: r for r in rows}
        assert by["done"]["summary"] is True
        assert by["done"]["sec"] == 0.0
        # 合计＝各步之和（26.9），不再把总时长算进去翻倍
        assert round(sum(r["sec"] for r in rows), 1) == 26.9

    def test_普通行都带summary字段(self):
        rows = archive.waterfall(_sample_events())
        assert all("summary" in r for r in rows)
        assert not any(r["summary"] for r in rows)

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
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_job_progress")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_复用archive_waterfall不重造轮子(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_job_progress")[1].split("@app.")[0]
        assert "archive.waterfall" in block

    def test_missing降级不500(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_job_progress")[1].split("@app.")[0]
        assert '"missing": missing' in block and '"note"' in block
