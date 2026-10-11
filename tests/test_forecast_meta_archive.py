# -*- coding: utf-8 -*-
"""#5 forecast/meta recommendations + #18 archive 自动挂任务（2026-09-24 前端清单）。"""
import asyncio
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import forecasting                                # noqa: E402
from server import app as app_module                          # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


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

    def test_来源时间仅由本机工作簿与完整运行记录核实(self, tmp_path, monkeypatch):
        root = tmp_path / "wenheng"
        root.mkdir()
        monkeypatch.setattr(forecasting.config, "ROOT", root)
        workbook = root.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
        workbook.parent.mkdir()
        workbook.write_bytes(b"master")
        period_dir = root / "out" / "202609"
        period_dir.mkdir(parents=True)
        input_file = root / "input" / "202609" / "监测表.xlsx"
        input_file.parent.mkdir(parents=True)
        input_file.write_bytes(b"input")
        run_log = period_dir / "run_log.json"
        run_log.write_text(json.dumps({
            "period": "202609", "assertions_ok": True,
            "input": r"input\202609\监测表.xlsx",
        }), encoding="utf-8")
        os.utime(run_log, (1_000, 1_000))
        os.utime(input_file, (900, 900))
        os.utime(workbook, (2_000, 2_000))

        provenance = forecasting._data_provenance(period_dir)

        assert provenance["upstream_workbook"]["name"] == workbook.name
        assert provenance["upstream_workbook"]["last_modified_at"] == "1970-01-01T00:33:20Z"
        assert provenance["processed_input"] == {
            "name": "监测表.xlsx", "last_modified_at": "1970-01-01T00:15:00Z",
        }
        assert provenance["run_record_at"] == "1970-01-01T00:16:40Z"
        assert provenance["data_freshness"] == "needs_check"
        assert provenance["master_workbook_consumption_verified"] is False

    def test_绝对输入路径仍能核验处理输入更新时间(self, tmp_path, monkeypatch):
        root = tmp_path / "wenheng"
        root.mkdir()
        monkeypatch.setattr(forecasting.config, "ROOT", root)
        workbook = root.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
        workbook.parent.mkdir()
        workbook.write_bytes(b"master")
        input_file = root / "input" / "202609" / "监测表.xlsx"
        input_file.parent.mkdir(parents=True)
        input_file.write_bytes(b"input")
        period_dir = root / "out" / "202609"
        period_dir.mkdir(parents=True)
        run_log = period_dir / "run_log.json"
        run_log.write_text(json.dumps({
            "period": "202609", "assertions_ok": True,
            "input": str(input_file.resolve()),
        }), encoding="utf-8")
        os.utime(run_log, (1_000, 1_000))
        os.utime(workbook, (900, 900))
        os.utime(input_file, (2_000, 2_000))

        provenance = forecasting._data_provenance(period_dir)

        assert provenance["processed_input"] == {
            "name": "监测表.xlsx", "last_modified_at": "1970-01-01T00:33:20Z",
        }
        assert provenance["data_freshness"] == "needs_check"

    @pytest.mark.parametrize("input_value", [
        r"input\..\outside.xlsx",
        "absolute-outside",
    ])
    def test_越出input目录的路径不返回处理输入(self, input_value, tmp_path, monkeypatch):
        root = tmp_path / "wenheng"
        root.mkdir()
        monkeypatch.setattr(forecasting.config, "ROOT", root)
        workbook = root.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
        workbook.parent.mkdir()
        workbook.write_bytes(b"master")
        (root / "input").mkdir()
        outside = root / "outside.xlsx"
        outside.write_bytes(b"outside")
        period_dir = root / "out" / "202609"
        period_dir.mkdir(parents=True)
        raw_input = str(outside.resolve()) if input_value == "absolute-outside" else input_value
        run_log = period_dir / "run_log.json"
        run_log.write_text(json.dumps({
            "period": "202609", "assertions_ok": True, "input": raw_input,
        }), encoding="utf-8")
        os.utime(run_log, (1_000, 1_000))
        os.utime(workbook, (900, 900))
        os.utime(outside, (2_000, 2_000))

        provenance = forecasting._data_provenance(period_dir)

        assert provenance["processed_input"] == {"name": None, "last_modified_at": None}
        assert provenance["data_freshness"] == "unverified"

    def test_输入符号链接解析到input目录外时拒绝(self, tmp_path, monkeypatch):
        root = tmp_path / "wenheng"
        root.mkdir()
        monkeypatch.setattr(forecasting.config, "ROOT", root)
        workbook = root.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
        workbook.parent.mkdir()
        workbook.write_bytes(b"master")
        input_dir = root / "input"
        input_dir.mkdir()
        outside = root / "outside.xlsx"
        outside.write_bytes(b"outside")
        link = input_dir / "link.xlsx"
        link.write_bytes(b"link placeholder")
        period_dir = root / "out" / "202609"
        period_dir.mkdir(parents=True)
        run_log = period_dir / "run_log.json"
        run_log.write_text(json.dumps({
            "period": "202609", "assertions_ok": True,
            "input": r"input\link.xlsx",
        }), encoding="utf-8")
        os.utime(run_log, (1_000, 1_000))
        os.utime(workbook, (900, 900))
        os.utime(outside, (2_000, 2_000))
        original_resolve = pathlib.Path.resolve

        def resolve_link_to_outside(path, *args, **kwargs):
            if path == link:
                return original_resolve(outside, *args, **kwargs)
            return original_resolve(path, *args, **kwargs)

        # 模拟文件符号链接的 resolve 结果，避免测试依赖 Windows symlink 权限。
        monkeypatch.setattr(pathlib.Path, "resolve", resolve_link_to_outside)

        provenance = forecasting._data_provenance(period_dir)

        assert provenance["processed_input"] == {"name": None, "last_modified_at": None}
        assert provenance["data_freshness"] == "unverified"

    @pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows 宿主拒绝 POSIX 根绝对路径")
    def test_windows宿主拒绝POSIX根绝对路径(self):
        assert forecasting._resolve_processed_input("/tmp/input/202609/监测表.xlsx") is None

    def test_缺少或未通过的运行记录时不判断新旧(self, tmp_path, monkeypatch):
        root = tmp_path / "wenheng"
        root.mkdir()
        monkeypatch.setattr(forecasting.config, "ROOT", root)
        period_dir = root / "out" / "202609"
        period_dir.mkdir(parents=True)

        provenance = forecasting._data_provenance(period_dir)

        assert provenance["upstream_workbook"]["last_modified_at"] is None
        assert provenance["run_record_at"] is None
        assert provenance["data_freshness"] == "unverified"
        assert provenance["master_workbook_consumption_verified"] is False

        workbook = root.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
        workbook.parent.mkdir()
        workbook.write_bytes(b"master")
        run_log = period_dir / "run_log.json"
        run_log.write_text(json.dumps({
            "period": "202609", "assertions_ok": False,
            "input": r"input\202609\监测表.xlsx",
        }), encoding="utf-8")
        os.utime(run_log, (1_000, 1_000))
        os.utime(workbook, (2_000, 2_000))

        failed_run = forecasting._data_provenance(period_dir)

        assert failed_run["upstream_workbook"]["last_modified_at"] is not None
        assert failed_run["processed_input"]["last_modified_at"] is None
        assert failed_run["run_record_at"] is None
        assert failed_run["data_freshness"] == "unverified"


class TestArchive自动挂任务:
    def test_接口层会找最近任务(self, tmp_path, monkeypatch):
        from server import config
        d = tmp_path / "202609"
        d.mkdir()
        seen = {}
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: d)
        monkeypatch.setattr(app_module.jobs, "collect_period_artifacts", lambda name: [])
        monkeypatch.setattr(app_module.archive, "build",
                            lambda out_dir, job=None, artifacts=None:
                            seen.update(job=job) or {"logpack": {"key": "logpack"}})

        def _list_jobs(limit=20, period=None):
            seen["limit"] = limit
            return []
        monkeypatch.setattr(app_module.jobs, "list_jobs", _list_jobs)

        asyncio.run(app_module.api_period_archive(_Req(config.ADMIN_USER), "202609"))
        assert seen["limit"] == 50, "应自动挂该期最近一次任务（list_jobs(50)）"
        assert seen["job"] is None

        target = {"id": "j1"}
        monkeypatch.setattr(app_module.jobs, "read_job", lambda jid: target)
        asyncio.run(app_module.api_period_archive(
            _Req(config.ADMIN_USER), "202609", "j1"))
        assert seen["job"] is target, "?job= 指定的任务要传给 archive.build"

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
