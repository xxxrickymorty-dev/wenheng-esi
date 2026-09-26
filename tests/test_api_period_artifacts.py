# -*- coding: utf-8 -*-
"""期次产物与下载权限：guest 不可取得任何报告内容或附件。"""
import asyncio
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from server import approval  # noqa: E402
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


def _write_signed_report(out_dir):
    ok, _record = approval.sign(
        out_dir,
        "管理员",
        {"period": out_dir.name, "counts": {"manual": 0}, "assertions": {"fail": 0}},
    )
    assert ok


_DOWNLOAD_ROUTES = (
    "period_download",
    "api_period_download",
    "download",
    "api_job_download",
)


def _prepare_download_context(monkeypatch, tmp_path):
    period = "202609"
    out_dir = tmp_path / period
    out_dir.mkdir()
    report = out_dir / "报告初稿_202609.docx"
    report.write_bytes(b"private report bytes")
    runlog = out_dir / "run_log.json"
    runlog.write_bytes(b'{"ok":true}')
    job = {"id": "job-1", "period": "202607", "out_period": period}
    monkeypatch.setattr(app_module.config, "OUT_DIR", tmp_path)
    monkeypatch.setattr(
        app_module, "resolve_period_dir",
        lambda requested: out_dir if requested == period else None,
    )
    monkeypatch.setattr(
        app_module.jobs, "read_job",
        lambda job_id: job if job_id == job["id"] else None,
    )
    monkeypatch.setattr(app_module.jobs, "collect_period_artifacts", lambda _period: _artifacts())
    monkeypatch.setattr(app_module.jobs, "collect_artifacts", lambda _job: _artifacts())
    monkeypatch.setattr(app_module.archive, "pack", lambda *_args: (b"zip-bytes", "runpack.zip"))
    return period, out_dir, report, runlog


def _call_download(route_name, user, key, period="202609", job_id="job-1"):
    identifier = job_id if route_name in ("download", "api_job_download") else period
    route = getattr(app_module, route_name)
    return asyncio.run(route(_Req(user), identifier, key))


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
    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_admin未签发报告四条路由均返回403且不解析附件(
        self, route_name, monkeypatch, tmp_path,
    ):
        _period, _out_dir, _report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        unexpected = lambda *_args: (_ for _ in ()).throw(AssertionError("未签发时不应解析附件"))
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact", unexpected)
        monkeypatch.setattr(app_module.jobs, "resolve_artifact", unexpected)

        response = _call_download(route_name, config.DEMO_USER, "report")

        assert response.status_code == 403
        assert _body(response) == {"error": "报告未签发或签发已失效，不能下载"}
        assert b"private report bytes" not in response.body

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_admin有效签发报告四条路由均可下载(self, route_name, monkeypatch, tmp_path):
        _period, out_dir, report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        _write_signed_report(out_dir)

        response = _call_download(route_name, config.DEMO_USER, "report")

        assert response.path == report

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_admin过期签发报告四条路由均返回403(self, route_name, monkeypatch, tmp_path):
        _period, out_dir, report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        _write_signed_report(out_dir)
        report.write_bytes(b"changed report bytes")

        response = _call_download(route_name, config.DEMO_USER, "report")

        assert response.status_code == 403
        assert _body(response) == {"error": "报告未签发或签发已失效，不能下载"}

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_未签发不影响runlog附件(self, route_name, monkeypatch, tmp_path):
        _period, _out_dir, _report, runlog = _prepare_download_context(monkeypatch, tmp_path)

        response = _call_download(route_name, config.DEMO_USER, "runlog")

        assert response.path == runlog

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_logpack不受报告签发门影响(self, route_name, monkeypatch, tmp_path):
        _prepare_download_context(monkeypatch, tmp_path)

        response = _call_download(route_name, config.DEMO_USER, app_module.archive.LOGPACK_KEY)

        assert response.status_code == 200
        assert response.media_type == "application/zip"
        assert response.headers["content-disposition"] == 'attachment; filename="runpack.zip"'

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_未知期次任务仍保留原404或重定向(self, route_name, monkeypatch, tmp_path):
        _prepare_download_context(monkeypatch, tmp_path)

        response = _call_download(
            route_name,
            config.DEMO_USER,
            "report",
            period="209901",
            job_id="missing-job",
        )

        if route_name == "period_download" or route_name == "download":
            assert isinstance(response, RedirectResponse)
            assert response.status_code == 303
        else:
            assert response.status_code == 404

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    @pytest.mark.parametrize("user", [None, config.GUEST_USER], ids=["anonymous", "guest"])
    def test_非管理员认证响应与先认证顺序不变(
        self, route_name, user, monkeypatch, tmp_path,
    ):
        _prepare_download_context(monkeypatch, tmp_path)
        unexpected = lambda *_args: (_ for _ in ()).throw(AssertionError("认证前不应读期次或任务"))
        monkeypatch.setattr(app_module, "resolve_period_dir", unexpected)
        monkeypatch.setattr(app_module.jobs, "read_job", unexpected)

        response = _call_download(route_name, user, "report")

        if user is None and route_name in ("period_download", "download"):
            assert isinstance(response, RedirectResponse)
            assert response.status_code == 303
        else:
            expected_status = 401 if user is None else 403
            assert response.status_code == expected_status

    def test_guest下载报告也在读文件前被拒绝(self, monkeypatch, tmp_path):
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: tmp_path / "202609")
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读文件")))
        response = asyncio.run(app_module.api_period_download(_Req(config.GUEST_USER), "202609", "report"))
        assert response.status_code == 403

    def test_admin可下载报告(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "202609"
        out_dir.mkdir()
        report = out_dir / "报告初稿_202609.docx"
        report.write_bytes(b"report")
        _write_signed_report(out_dir)
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: out_dir)
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact", lambda *_args: report)
        response = asyncio.run(app_module.api_period_download(_Req(config.DEMO_USER), "202609", "report"))
        assert response.path == report

    def test_admin下载签发后已变更的报告返回403(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "202609"
        out_dir.mkdir()
        report = out_dir / "报告初稿_202609.docx"
        report.write_bytes(b"signed report")
        _write_signed_report(out_dir)
        report.write_bytes(b"changed report")
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: out_dir)
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact", lambda *_args: report)

        response = asyncio.run(app_module.api_period_download(_Req(config.DEMO_USER), "202609", "report"))

        assert response.status_code == 403
        assert _body(response) == {"error": "报告未签发或签发已失效，不能下载"}

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
        out_dir = tmp_path / "202609"
        out_dir.mkdir()
        report = out_dir / "报告初稿_202609.docx"
        report.write_bytes(b"report")
        _write_signed_report(out_dir)
        monkeypatch.setattr(app_module.config, "OUT_DIR", tmp_path)
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
