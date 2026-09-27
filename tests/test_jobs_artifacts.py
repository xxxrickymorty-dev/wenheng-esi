# -*- coding: utf-8 -*-
"""《诊断报告》进演示站产物列表（2026-09-19）。

背景：B 档把《诊断报告》改造成"按失败上下文拼装"，但演示站跑的是
`run_pipeline.py`（直跑路径，不经过 `agent/flow.py`），产物表 `_artifact_table`
里也没有它 —— 也就是说**做了但演示时看不见**。

本组测试钉三件事：
  ① 断言未过时 `run_pipeline` 真的写出 `out/<期次>/诊断报告.md`；
  ② 产物列表（任务入口 + 期次入口）收得到它，且能解析出可下载路径；
  ③ 没有诊断报告时不凭空造条目。
"""
import asyncio
import datetime as dt
import json
import pathlib
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
for p in (str(REPO), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_pipeline                                              # noqa: E402
import report_forecast                                           # noqa: E402
from server import config, jobs                                  # noqa: E402

PERIOD = "209901"          # 假期次，避免碰真实 out/202607


def _job():
    return {"id": "job-test", "period": PERIOD, "out_period": PERIOD,
            "started_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _out(tmp_path):
    d = tmp_path / PERIOD
    d.mkdir(parents=True, exist_ok=True)
    return d


def _create_isolated_job(monkeypatch, out_root, period):
    monkeypatch.setattr(config, "OUT_DIR", out_root)
    monkeypatch.setattr(config, "JOBS_DIR", out_root / "_jobs")
    monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", out_root / "_forecast_choices")
    monkeypatch.setattr(jobs, "_running", set())
    monkeypatch.setattr(jobs, "active_job", lambda: None)

    async def no_run(_job):
        return None

    monkeypatch.setattr(jobs, "_run", no_run)

    async def create():
        return jobs.create_job(period, "input.xlsx", "tester")

    return asyncio.run(create())


# ============================================================ ① 带病出稿会写诊断报告
def test_断言未过时写出诊断报告(tmp_path):
    led = {"wide": {"total_cites": pd.DataFrame(index=["Chemistry"])},
           "diagnostics": {"known_names": {"总被引": {"Chemistry"}},
                           "unknown_names": {"总被引": ["某某新学科"]}}}
    report = [("PASS", "宽表 papers 学科数=22 (实际 22)"),
              ("FAIL", "宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])")]
    p = run_pipeline._write_diagnosis(led, PERIOD, _out(tmp_path), report, 1)
    assert p and p.exists(), "断言未过必须留下诊断报告，不能只留一句 exit code"
    text = p.read_text(encoding="utf-8")
    assert "断言未过" in text
    assert "某某新学科" in text, "认不出的学科名是人工唯一能直接下手的线索"
    assert "不要拿上一版的旧报告顶上" in text, \
        '措辞不能预设「已经出稿」——缺数据时后续步骤会中断，那是预期行为'


def test_叙事层抛异常时诊断报告照写(tmp_path, monkeypatch):
    """叙事层是附赠的增强，它挂了至少要留下断言清单 —— 不能什么都不给。"""
    from agent import narrator
    monkeypatch.setattr(narrator, "compose",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸了")))
    led = {"wide": {}, "diagnostics": {}}
    report = [("FAIL", "宽表 total_cites 学科数=22 (实际 21)")]
    p = run_pipeline._write_diagnosis(led, PERIOD, _out(tmp_path), report, 1)
    assert p and p.exists()
    assert "未通过的断言" in p.read_text(encoding="utf-8")


# ============================================================ ② 产物列表收得到
def test_任务入口产物列表含诊断报告(monkeypatch, tmp_path):
    (_out(tmp_path) / "诊断报告.md").write_text("# 诊断报告\n", encoding="utf-8")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    items = jobs.collect_artifacts(_job())
    keys = [i["key"] for i in items]
    assert "diagnosis" in keys, f"产物列表没收诊断报告：{keys}"
    one = next(i for i in items if i["key"] == "diagnosis")
    assert one["url"].endswith("/download/diagnosis")


def test_期次入口产物列表也含诊断报告(monkeypatch, tmp_path):
    """首屏对勘本按期次列产物，没有任务上下文 —— 那边也要看得到。"""
    (_out(tmp_path) / "诊断报告.md").write_text("# 诊断报告\n", encoding="utf-8")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    keys = [i["key"] for i in jobs.collect_period_artifacts(PERIOD)]
    assert "diagnosis" in keys


def test_诊断报告可解析出下载路径(monkeypatch, tmp_path):
    (_out(tmp_path) / "诊断报告.md").write_text("# 诊断报告\n", encoding="utf-8")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    p = jobs.resolve_artifact(_job(), "diagnosis")
    assert p and p.exists() and p.name == "诊断报告.md"


# ============================================================ ③ 没有就不造
def test_没有诊断报告时不出现该条目(monkeypatch, tmp_path):
    _out(tmp_path)          # 空产物目录
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    assert "diagnosis" not in [i["key"] for i in jobs.collect_artifacts(_job())]


def test_诊断报告不是主产物():
    """它是"带病时的核对指引"，不该跟报告初稿并列进主产物区。"""
    from server.jobs import _artifact_table
    rows = _artifact_table(pathlib.Path("."), lambda p: False)
    d = next(r for r in rows if r[0] == "diagnosis")
    assert d[3] is False, "主产物只有报告初稿/对勘本/红色件清单"


def test_创建任务冻结请求期次配置且后续保存不改变快照(tmp_path, monkeypatch):
    out_root = tmp_path / "out"
    period = "202610"
    choices = out_root / "_forecast_choices"
    choices.mkdir(parents=True)
    primary = choices / f"{period}.json"
    original = {"choice": {"citation": {"物理学": "SARIMA模型"}},
                "by": "librarian", "at": "2026-09-27 10:00:00", "custom": "kept"}
    primary.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    legacy = out_root / period / "forecast_choice.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"choice": {"citation": {"物理学": "all"}}}),
                      encoding="utf-8")

    job = _create_isolated_job(monkeypatch, out_root, period)
    snapshot_path = pathlib.Path(job["forecast_choice_snapshot"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot_path.parent == jobs.job_dir(job["id"])
    assert snapshot["choice"] == original["choice"]
    assert snapshot["custom"] == "kept"
    assert snapshot["request_period"] == snapshot["source_period"] == period
    assert snapshot["snapshot_source"] == "primary"
    assert job["forecast_choice_source_period"] == period

    primary.write_text(json.dumps({"choice": {}, "by": "later"}), encoding="utf-8")
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["choice"] == original["choice"]


def test_创建任务按旧文件回退且无配置保存空快照(tmp_path, monkeypatch):
    out_root = tmp_path / "out"
    period = "202609"
    legacy = out_root / period / "forecast_choice.json"
    legacy.parent.mkdir(parents=True)
    legacy_record = {"choice": {"rank": {"物理学": "阻尼Holt模型"}},
                     "by": "legacy-admin", "at": "old-time"}
    legacy_text = json.dumps(legacy_record, ensure_ascii=False)
    legacy.write_text(legacy_text, encoding="utf-8")

    job = _create_isolated_job(monkeypatch, out_root, period)
    snapshot = json.loads(pathlib.Path(job["forecast_choice_snapshot"]).read_text(encoding="utf-8"))
    assert snapshot["choice"] == legacy_record["choice"]
    assert snapshot["by"] == legacy_record["by"]
    assert snapshot["snapshot_source"] == "legacy"
    assert legacy.read_text(encoding="utf-8") == legacy_text

    empty = _create_isolated_job(monkeypatch, tmp_path / "empty-out", "202611")
    empty_snapshot = json.loads(
        pathlib.Path(empty["forecast_choice_snapshot"]).read_text(encoding="utf-8"))
    assert empty_snapshot["choice"] == {}
    assert empty_snapshot["snapshot_source"] == "default"


def test_任务子进程收到私有快照路径(tmp_path, monkeypatch):
    run_job = jobs._run
    job = _create_isolated_job(monkeypatch, tmp_path / "out", "202611")
    captured = {}

    class _Proc:
        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.update(args=args, env=kwargs["env"])
        return _Proc()

    monkeypatch.setattr(jobs, "_run", run_job)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    asyncio.run(jobs._run(job))
    assert captured["env"]["WENHENG_FORECAST_CHOICE_SNAPSHOT"] == \
        job["forecast_choice_snapshot"]


def test_任务请求期次配置应用到不同的实际输出期次(tmp_path):
    request_period, output_period = "202610", "202612"
    snapshot_path = tmp_path / "_jobs" / "job-1" / "forecast_choice.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps({
        "period": request_period,
        "request_period": request_period,
        "source_period": request_period,
        "choice": {"citation": {"物理学": "SARIMA模型"}},
        "by": "librarian",
        "at": "2026-09-27 10:00:00",
        "snapshot_at": "2026-09-27 10:01:00",
        "snapshot_source": "primary",
        "snapshot_source_path": f"_forecast_choices/{request_period}.json",
    }, ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "out" / output_period

    applied = run_pipeline._apply_forecast_choice_snapshot(snapshot_path, out_dir, output_period)
    record = json.loads(applied.read_text(encoding="utf-8"))
    picked, warnings = report_forecast.load_choice(out_dir)
    assert picked == {("citation", "物理学"): "SARIMA模型"}
    assert warnings == []
    assert record["request_period"] == request_period
    assert record["source_period"] == request_period
    assert record["output_period"] == output_period
    assert record["config_updated_at"] == "2026-09-27 10:00:00"
    assert record["operator"] == "librarian"
    assert record["snapshot_at"] == "2026-09-27 10:01:00"
