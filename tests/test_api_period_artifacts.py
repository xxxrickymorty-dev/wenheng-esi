# -*- coding: utf-8 -*-
"""期次产物与下载权限：guest 不可取得任何报告内容或附件。"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from server import config  # noqa: E402
from server import app as app_module  # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _body(response):
    assert isinstance(response, JSONResponse)
    return json.loads(response.body)


def _artifacts():
    return [
        {"key": "report", "name": "报告初稿_202609.docx", "url": "/p/202609/download/report"},
        {"key": "runlog", "name": "run_log.json", "url": "/p/202609/download/runlog"},
    ]


class TestPeriodArtifacts:
    def test_未登录与未知期次(self, monkeypatch, tmp_path):
        assert _body(asyncio.run(app_module.api_period_artifacts(_Req(), "202609")))["error"] == "未登录"
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: None)
        response = asyncio.run(app_module.api_period_artifacts(_Req(config.DEMO_USER), "209901"))
        assert response.status_code == 404

    def test_guest不能列产物_admin看完整产物(self, monkeypatch, tmp_path):
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: tmp_path / "202609")
        monkeypatch.setattr(app_module.jobs, "collect_period_artifacts", lambda _period: _artifacts())
        guest = asyncio.run(app_module.api_period_artifacts(_Req(config.GUEST_USER), "202609"))
        admin = asyncio.run(app_module.api_period_artifacts(_Req(config.DEMO_USER), "202609"))
        assert guest.status_code == 403
        assert admin == {"period": "202609", "artifacts": _artifacts()}

class TestDirectDownloads:
    def test_guest下载报告也在读文件前被拒绝(self, monkeypatch, tmp_path):
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: tmp_path / "202609")
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读文件")))
        response = asyncio.run(app_module.api_period_download(_Req(config.GUEST_USER), "202609", "report"))
        assert response.status_code == 403

    def test_admin可下载报告(self, monkeypatch, tmp_path):
        report = tmp_path / "报告初稿_202609.docx"
        report.write_bytes(b"report")
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: tmp_path / "202609")
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact", lambda *_args: report)
        response = asyncio.run(app_module.api_period_download(_Req(config.DEMO_USER), "202609", "report"))
        assert response.path == report

    def test_guest不能通过任务下载绕过管理员门(self, monkeypatch):
        monkeypatch.setattr(app_module.jobs, "read_job",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读任务")))
        response = asyncio.run(app_module.api_job_download(_Req(config.GUEST_USER), "job-1", "report"))
        assert response.status_code == 403

    def test_旧下载路由也在读取前拒绝guest_匿名仍跳登录(self, monkeypatch):
        monkeypatch.setattr(app_module.jobs, "read_job",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读任务")))
        monkeypatch.setattr(app_module, "resolve_period_dir",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读期次")))
        guest_period = asyncio.run(app_module.period_download(_Req(config.GUEST_USER), "202609", "report"))
        guest_job = asyncio.run(app_module.download(_Req(config.GUEST_USER), "job-1", "report"))
        anonymous = asyncio.run(app_module.period_download(_Req(), "202609", "report"))
        assert guest_period.status_code == 403
        assert guest_job.status_code == 403
        assert isinstance(anonymous, RedirectResponse) and anonymous.status_code == 303

    def test_admin保留任务下载(self, monkeypatch, tmp_path):
        report = tmp_path / "报告初稿_202609.docx"
        report.write_bytes(b"report")
        monkeypatch.setattr(app_module.jobs, "read_job", lambda _job_id: {"period": "202609"})
        monkeypatch.setattr(app_module.jobs, "resolve_artifact", lambda *_args: report)
        response = asyncio.run(app_module.api_job_download(_Req(config.DEMO_USER), "job-1", "report"))
        assert response.path == report


class TestReportDataEndpoints:
    def test_guest在读取前被各数据端点拒绝(self, monkeypatch):
        monkeypatch.setattr(app_module, "resolve_period_dir",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读期次")))
        calls = [
            lambda: app_module.api_period_facts(_Req(config.GUEST_USER), "202609"),
            lambda: app_module.api_period_collation(_Req(config.GUEST_USER), "202609"),
            lambda: app_module.api_period_charts_json(_Req(config.GUEST_USER), "202609"),
            lambda: app_module.api_forecast_choice_get(_Req(config.GUEST_USER), "202609"),
            lambda: app_module.api_ledger_sheets(_Req(config.GUEST_USER)),
            lambda: app_module.period_chart(_Req(config.GUEST_USER), "202609", "x.png"),
            lambda: app_module.period_flexible_chart(_Req(config.GUEST_USER), "202609", "trend", "x.png"),
        ]
        for call in calls:
            response = asyncio.run(call())
            assert response.status_code == 403
