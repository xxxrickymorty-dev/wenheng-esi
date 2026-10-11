# -*- coding: utf-8 -*-
"""期次产物与下载权限（2026-10-11 角色改两级后）：

- 管理员：完整产物与全部下载口；
- 操作员：只读放行普通产物与下载，**红件三件 + 运行日志 + 日志包不可见、不可下载**；
- 匿名：401 / 303 先于任何读取。
"""
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
        {"key": "table2", "name": "table2.csv", "url": "/p/202609/download/table2"},
        {"key": "red_list", "name": "红色件清单.md", "url": "/p/202609/download/red_list"},
        {"key": "red_json", "name": "red_slots.json", "url": "/p/202609/download/red_json"},
        {"key": "runlog", "name": "run_log.json", "url": "/p/202609/download/runlog"},
    ]


def _operator_artifacts():
    return [a for a in _artifacts()
            if a["key"] not in ("red_list", "red_json", "runlog")]


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

#: 只管理员可用的任务下载口（文件与 API 两条）。
_JOB_DOWNLOAD_ROUTES = ("download", "api_job_download")


def _prepare_download_context(monkeypatch, tmp_path):
    period = "202609"
    out_dir = tmp_path / period
    out_dir.mkdir()
    report = out_dir / "报告初稿_202609.docx"
    report.write_bytes(b"private report bytes")
    runlog = out_dir / "run_log.json"
    runlog.write_bytes(b'{"ok":true}')
    (out_dir / "table2.csv").write_bytes(b"discipline,papers\n")
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
    identifier = job_id if route_name in _JOB_DOWNLOAD_ROUTES else period
    route = getattr(app_module, route_name)
    return asyncio.run(route(_Req(user), identifier, key))


class TestPeriodArtifacts:
    def test_未登录与未知期次(self, monkeypatch, tmp_path):
        assert _body(asyncio.run(app_module.api_period_artifacts(_Req(), "202609")))["error"] == "未登录"
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: None)
        response = asyncio.run(app_module.api_period_artifacts(_Req(config.ADMIN_USER), "209901"))
        assert response.status_code == 404

    def test_操作员看不到红件与运行日志_admin看完整产物(self, monkeypatch, tmp_path):
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: tmp_path / "202609")
        monkeypatch.setattr(app_module.jobs, "collect_period_artifacts", lambda _period: _artifacts())
        operator = asyncio.run(app_module.api_period_artifacts(_Req(config.OPERATOR_USER), "202609"))
        admin = asyncio.run(app_module.api_period_artifacts(_Req(config.ADMIN_USER), "202609"))
        assert operator == {"period": "202609", "artifacts": _operator_artifacts()}
        assert admin == {"period": "202609", "artifacts": _artifacts()}

    def test_任务产物清单同样按角色过滤(self, monkeypatch):
        monkeypatch.setattr(app_module.jobs, "read_job", lambda _job_id: {"id": "job-1"})
        monkeypatch.setattr(app_module.jobs, "collect_artifacts", lambda _job: _artifacts())
        operator = asyncio.run(app_module.api_artifacts(_Req(config.OPERATOR_USER), "job-1"))
        admin = asyncio.run(app_module.api_artifacts(_Req(config.ADMIN_USER), "job-1"))
        assert operator["artifacts"] == _operator_artifacts()
        assert admin["artifacts"] == _artifacts()


class TestDirectDownloads:
    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_admin未签发报告四条路由均返回403且不解析附件(
        self, route_name, monkeypatch, tmp_path,
    ):
        _period, _out_dir, _report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        unexpected = lambda *_args: (_ for _ in ()).throw(AssertionError("未签发时不应解析附件"))
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact", unexpected)
        monkeypatch.setattr(app_module.jobs, "resolve_artifact", unexpected)

        response = _call_download(route_name, config.ADMIN_USER, "report")

        assert response.status_code == 403
        assert _body(response) == {"error": "报告未签发或签发已失效，不能下载"}
        assert b"private report bytes" not in response.body

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_admin有效签发报告四条路由均可下载(self, route_name, monkeypatch, tmp_path):
        _period, out_dir, report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        _write_signed_report(out_dir)

        response = _call_download(route_name, config.ADMIN_USER, "report")

        assert response.path == report

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_admin过期签发报告四条路由均返回403(self, route_name, monkeypatch, tmp_path):
        _period, out_dir, report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        _write_signed_report(out_dir)
        report.write_bytes(b"changed report bytes")

        response = _call_download(route_name, config.ADMIN_USER, "report")

        assert response.status_code == 403
        assert _body(response) == {"error": "报告未签发或签发已失效，不能下载"}

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_未签发不影响runlog附件(self, route_name, monkeypatch, tmp_path):
        _period, _out_dir, _report, runlog = _prepare_download_context(monkeypatch, tmp_path)

        response = _call_download(route_name, config.ADMIN_USER, "runlog")

        assert response.path == runlog

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_logpack不受报告签发门影响(self, route_name, monkeypatch, tmp_path):
        _prepare_download_context(monkeypatch, tmp_path)

        response = _call_download(route_name, config.ADMIN_USER, app_module.archive.LOGPACK_KEY)

        assert response.status_code == 200
        assert response.media_type == "application/zip"
        assert response.headers["content-disposition"] == 'attachment; filename="runpack.zip"'

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_未知期次任务仍保留原404或重定向(self, route_name, monkeypatch, tmp_path):
        _prepare_download_context(monkeypatch, tmp_path)

        response = _call_download(
            route_name,
            config.ADMIN_USER,
            "report",
            period="209901",
            job_id="missing-job",
        )

        if route_name in ("period_download", "download"):
            assert isinstance(response, RedirectResponse)
            assert response.status_code == 303
        else:
            assert response.status_code == 404

    @pytest.mark.parametrize("route_name", _DOWNLOAD_ROUTES)
    def test_匿名认证响应与先认证顺序不变(self, route_name, monkeypatch, tmp_path):
        _prepare_download_context(monkeypatch, tmp_path)
        unexpected = lambda *_args: (_ for _ in ()).throw(AssertionError("认证前不应读期次或任务"))
        monkeypatch.setattr(app_module, "resolve_period_dir", unexpected)
        monkeypatch.setattr(app_module.jobs, "read_job", unexpected)

        response = _call_download(route_name, None, "report")

        if route_name in ("period_download", "download"):
            assert isinstance(response, RedirectResponse)
            assert response.status_code == 303
        else:
            assert response.status_code == 401

    def test_操作员下载红件与日志包在读文件前被拒(self, monkeypatch, tmp_path):
        _prepare_download_context(monkeypatch, tmp_path)
        unexpected = lambda *_args: (_ for _ in ()).throw(AssertionError("拦截前不应读期次"))
        monkeypatch.setattr(app_module, "resolve_period_dir", unexpected)
        for key in ("red_list", "red_json", "runlog", app_module.archive.LOGPACK_KEY):
            for route_name in ("period_download", "api_period_download"):
                response = _call_download(route_name, config.OPERATOR_USER, key)
                assert response.status_code == 403, (route_name, key)

    def test_操作员可下载普通产物(self, monkeypatch, tmp_path):
        _period, out_dir, report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        _write_signed_report(out_dir)

        for route_name in ("period_download", "api_period_download"):
            response = _call_download(route_name, config.OPERATOR_USER, "report")
            assert response.path == report, route_name

    def test_操作员可下载大表csv(self, monkeypatch, tmp_path):
        _period, out_dir, _report, _runlog = _prepare_download_context(monkeypatch, tmp_path)
        for route_name in ("period_download", "api_period_download"):
            response = _call_download(route_name, config.OPERATOR_USER, "table2")
            assert response.path == out_dir / "table2.csv", route_name

    def test_admin可下载报告(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "202609"
        out_dir.mkdir()
        report = out_dir / "报告初稿_202609.docx"
        report.write_bytes(b"report")
        _write_signed_report(out_dir)
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: out_dir)
        monkeypatch.setattr(app_module.jobs, "resolve_period_artifact", lambda *_args: report)
        response = asyncio.run(app_module.api_period_download(_Req(config.ADMIN_USER), "202609", "report"))
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

        response = asyncio.run(app_module.api_period_download(_Req(config.ADMIN_USER), "202609", "report"))

        assert response.status_code == 403
        assert _body(response) == {"error": "报告未签发或签发已失效，不能下载"}

    def test_操作员不能走任务下载口(self, monkeypatch):
        """任务下载口（旧/新两条）仍只管理员——操作员 403，不读任务。"""
        monkeypatch.setattr(app_module.jobs, "read_job",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读任务")))
        response = asyncio.run(app_module.api_job_download(_Req(config.OPERATOR_USER), "job-1", "report"))
        assert response.status_code == 403
        legacy = asyncio.run(app_module.download(_Req(config.OPERATOR_USER), "job-1", "report"))
        assert legacy.status_code == 403

    def test_匿名旧下载路由仍跳登录(self, monkeypatch):
        monkeypatch.setattr(app_module.jobs, "read_job",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读任务")))
        monkeypatch.setattr(app_module, "resolve_period_dir",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读期次")))
        anonymous = asyncio.run(app_module.period_download(_Req(), "202609", "report"))
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
        response = asyncio.run(app_module.api_job_download(_Req(config.ADMIN_USER), "job-1", "report"))
        assert response.path == report


class TestReportDataEndpoints:
    def test_操作员读前被拒的只剩台账(self, monkeypatch):
        monkeypatch.setattr(app_module, "resolve_period_dir",
                            lambda *_args: (_ for _ in ()).throw(AssertionError("不应读期次")))
        response = asyncio.run(app_module.api_ledger_sheets(_Req(config.OPERATOR_USER)))
        assert response.status_code == 403

    def test_操作员放行只读数据端点(self, monkeypatch, tmp_path):
        """不存在的期次回 404——若门没放行会是 403（2026-10-11 起只读端点对操作员放行）。"""
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda _period: None)
        calls = [
            lambda: app_module.api_period_facts(_Req(config.OPERATOR_USER), "199901"),
            lambda: app_module.api_period_collation(_Req(config.OPERATOR_USER), "199901"),
            lambda: app_module.api_period_charts_json(_Req(config.OPERATOR_USER), "199901"),
            lambda: app_module.period_chart(_Req(config.OPERATOR_USER), "199901", "x.png"),
        ]
        for call in calls:
            assert asyncio.run(call()).status_code == 404
        # 预测选择是纯读（不查产物目录）：拿到条目形状即证明门已放行。
        choice = asyncio.run(app_module.api_forecast_choice_get(
            _Req(config.OPERATOR_USER), "199901"))
        assert choice["period"] == "199901"
        # 灵活报告的图在缺期次时落回首页（303）——同样证明门已放行。
        flexible = asyncio.run(app_module.period_flexible_chart(
            _Req(config.OPERATOR_USER), "199901", "trend", "x.png"))
        assert flexible.status_code == 303
