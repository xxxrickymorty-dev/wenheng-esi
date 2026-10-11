# -*- coding: utf-8 -*-
"""GET /api/periods/{period} 单期元数据（契约 §2.2 #2）。

验的是组装逻辑：resolve_period_dir + period_mod.issue_of + steps 三步 + lastJob。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import config, jobs                               # noqa: E402
from server import app as app_module                          # noqa: E402
from server.app import resolve_period_dir                     # noqa: E402
import period as period_mod                                   # noqa: E402


class TestResolvePeriodDir:
    def test_202607存在(self):
        d = resolve_period_dir("202607")
        assert d is not None and d.name.startswith("202607")

    def test_不存在返回None(self):
        assert resolve_period_dir("209901") is None

    def test_非法格式返回None(self):
        assert resolve_period_dir("abc") is None
        assert resolve_period_dir("") is None


class TestPeriodMeta:
    def test_202607有期号和标签(self):
        no, total = period_mod.issue_of("202607")
        assert no is not None and total is not None
        label = period_mod.label("202607")
        assert "2026" in label

    def test_window来自overview_facts(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        facts = d / "overview_facts.json"
        if not facts.exists():
            return
        data = json.loads(facts.read_text(encoding="utf-8"))
        assert "coverage_window" in data

    def test_steps_generated为True(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        assert (d / "red_slots.json").exists()

    def test_palette是三色(self):
        assert set(config.PALETTE.keys()) == {"primary", "deep", "lift"}


def _prepare_old_period_job(tmp_path, monkeypatch):
    out_root = tmp_path / "out"
    input_root = tmp_path / "input"
    jobs_root = out_root / "_jobs"
    period_dir = out_root / "202607"
    period_dir.mkdir(parents=True)
    (period_dir / "red_slots.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "OUT_DIR", out_root)
    monkeypatch.setattr(config, "INPUT_DIR", input_root)
    monkeypatch.setattr(config, "JOBS_DIR", jobs_root)

    for day in range(1, 31):
        jobs.write_job({
            "id": f"new-{day:02d}",
            "period": "202609",
            "status": "completed",
            "created_at": f"2026-09-{day:02d} 10:00:00",
        })
    jobs.write_job({
        "id": "old-202607-01",
        "period": "202607",
        "status": "completed",
        "created_at": "2026-07-01 10:00:00",
    })
    jobs.write_job({
        "id": "old-202607-02",
        "period": "202607",
        "status": "warned",
        "created_at": "2026-07-20 10:00:00",
    })
    return jobs_root


def test_period_detail_finds_latest_old_job_outside_global_limit(
    tmp_path, monkeypatch
):
    _prepare_old_period_job(tmp_path, monkeypatch)
    # 2026-10-11：单期详情是只读屏，守卫改 require_user（管理员与操作员都放行）。
    monkeypatch.setattr(app_module, "require_user", lambda _request: "rick")

    response = asyncio.run(
        app_module.api_period_detail(object(), "202607")
    )

    assert response["lastJob"] == {
        "id": "old-202607-02",
        "status": "warned",
        "created_at": "2026-07-20 10:00:00",
    }


def test_list_jobs_default_remains_global_latest_limit(tmp_path, monkeypatch):
    _prepare_old_period_job(tmp_path, monkeypatch)

    latest = jobs.list_jobs(30)

    assert len(latest) == 30
    assert [job["id"] for job in latest] == [
        f"new-{day:02d}" for day in range(30, 0, -1)
    ]
