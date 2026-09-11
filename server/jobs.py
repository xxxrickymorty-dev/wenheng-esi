# -*- coding: utf-8 -*-
"""文衡演示站任务管理：创建任务 → 子进程跑流水线 → JSONL 进度 + 控制台日志。

约定：单机单任务（一次只跑一期，约 15–20 秒）；uvicorn 单 worker。
"""
import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import secrets
import time

from . import config

TERMINAL = {"done", "warn", "failed", "interrupted"}
PERIOD_RE = re.compile(r"^\d{6}$")
_running: set = set()


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def job_dir(job_id):
    return config.JOBS_DIR / job_id


def read_job(job_id):
    p = job_dir(job_id) / "job.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_job(job):
    d = job_dir(job["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")


def list_jobs(limit=20):
    jobs = []
    if config.JOBS_DIR.exists():
        for d in config.JOBS_DIR.iterdir():
            j = read_job(d.name)
            if j:
                jobs.append(j)
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs[:limit]


def active_job():
    for jid in list(_running):
        j = read_job(jid)
        if j and j.get("status") not in TERMINAL:
            return j
    return None


def recover_stale():
    """服务重启后，把没有存活进程的 running 任务标为中断。"""
    if not config.JOBS_DIR.exists():
        return
    for d in config.JOBS_DIR.iterdir():
        j = read_job(d.name)
        if j and j.get("status") == "running":
            j["status"] = "interrupted"
            j["finished_at"] = _now()
            write_job(j)


def create_job(period, input_path, actor, backtest=False):
    if not PERIOD_RE.match(period):
        raise ValueError("期次格式应为 6 位数字，如 202609")
    if active_job():
        raise RuntimeError("已有任务正在运行")
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    d = job_dir(jid)
    d.mkdir(parents=True, exist_ok=True)
    job = {
        "id": jid, "period": period, "input": str(input_path), "actor": actor,
        "backtest": bool(backtest), "status": "running",
        "created_at": _now(), "started_at": _now(), "finished_at": None,
        "exit_code": None, "progress": str(d / "progress.jsonl"),
        "console": str(d / "console.log"),
    }
    write_job(job)
    _running.add(jid)
    asyncio.create_task(_run(job))
    return job


async def _run(job):
    jid = job["id"]
    d = job_dir(jid)
    console = d / "console.log"
    env = os.environ.copy()
    env["WENHENG_PROGRESS_FILE"] = str(d / "progress.jsonl")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if config.REFERENCE_DOCX:
        env["WENHENG_REFERENCE_DOCX"] = config.REFERENCE_DOCX
    cmd = [config.PYTHON, str(config.PIPELINE), job["input"]]
    if job.get("backtest"):
        cmd.append("--backtest")

    code, err = None, None
    try:
        with open(console, "wb") as f:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(config.ROOT), env=env,
                stdout=f, stderr=asyncio.subprocess.STDOUT)
            code = await proc.wait()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        code = -1

    if code == 0:
        status = "done"
    elif code == 1:
        status = "warn"  # 断言未过：仍产出初稿，需馆员复核
    else:
        status = "failed"

    job = read_job(jid) or job
    job.update({"status": status, "exit_code": code, "finished_at": _now()})
    if err:
        job["error"] = err

    # 流水线按期次自动检测输出目录（可能与上传目录名不同）
    try:
        t_start = dt.datetime.strptime(job["started_at"], "%Y-%m-%d %H:%M:%S").timestamp() - 10
    except (KeyError, ValueError):
        t_start = 0
    fresh_logs = [p for p in config.OUT_DIR.glob("*/run_log.json")
                  if p.stat().st_mtime >= t_start]
    if fresh_logs:
        newest = max(fresh_logs, key=lambda p: p.stat().st_mtime)
        job["out_period"] = newest.parent.name
        try:
            job["stats"] = json.loads(newest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    write_job(job)
    _running.discard(jid)


def collect_artifacts(job):
    """可下载产物：key → 路径（全部位于 out/<period>/）。

    只列出本任务运行后新生成的产物（防止展示上一次运行的残留文件）。
    """
    out = config.OUT_DIR / (job.get("out_period") or job["period"])
    try:
        t_start = dt.datetime.strptime(job["started_at"], "%Y-%m-%d %H:%M:%S").timestamp() - 10
    except (KeyError, ValueError):
        t_start = 0

    def fresh(path):
        return bool(path) and path.exists() and path.stat().st_mtime >= t_start

    report = next((p for p in out.glob("报告初稿_*.docx") if fresh(p)), None) if out.exists() else None
    diff = next((p for p in out.glob("对照差异报告*.md") if fresh(p)), None) if out.exists() else None
    table = [
        ("report", "报告初稿（Word）", report, True),
        ("red_list", "红色件清单（Markdown）", out / "红色件清单.md", True),
        ("red_view", "红色件清单（在线查看）", None, True),
        ("diff", "对照差异报告（金样回测）", diff, False),
        ("forecast", "预测回测报告", out / "预测回测报告.md", False),
        ("table2", "大表数据（CSV）", out / "table2.csv", False),
        ("red_json", "红色件审计明细（JSON）", out / "red_slots.json", False),
        ("runlog", "运行日志（JSON）", out / "run_log.json", False),
    ]
    items = []
    for key, label, path, primary in table:
        if key == "red_view":
            if fresh(out / "red_slots.json"):
                items.append({"key": key, "label": label, "name": "红色件清单",
                              "size": None, "url": f"/jobs/{job['id']}/redslots",
                              "primary": primary})
            continue
        if fresh(path):
            items.append({"key": key, "label": label, "name": path.name,
                          "size": path.stat().st_size,
                          "url": f"/jobs/{job['id']}/download/{key}",
                          "primary": primary})
    return items


def resolve_artifact(job, key):
    for a in collect_artifacts(job):
        if a["key"] == key and key != "red_view":
            p = config.OUT_DIR / (job.get("out_period") or job["period"]) / a["name"]
            if p.exists():
                return p
    return None


def read_progress(job):
    p = pathlib.Path(job.get("progress", ""))
    if not p or not p.exists():
        return []
    events = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
