# -*- coding: utf-8 -*-
"""监测版生成任务（rick 2026-11-04 批，低优先）：长生成改任务制。

背景：`POST /api/monitor/report` / `/api/monitor/compare` 是同步口——
生成完才返回；供应商开启态下模型位慢（网关 20–60s），馆员端转圈等超时。
本模块把生成搬进后台线程，HTTP 口立刻回 `{job_id}`；前端轮询
`GET /api/monitor/jobs/{id}`（或 SSE `/events`）看到终态再取产物 url。

**复用既有任务制的契约形状，不另造词汇**（工程原则：优先复用）：
POST → `{job_id, url, status}`；状态沿用 `agent.states` 10 态权威里的
`running / completed / failed`；失败 `{"status": "failed", "error": 人话}`。

**不进** `out/_state` 的 jobs 表（那是流水线产线的唯一真相源）：混进去会
把监测生成记进运行档案总账（`/api/archive/ledger` 对 jobs 全量透出），
还会让 `active_job()` 把监测生成与流水线互锁。任务记录落
`monitor_data/_jobs/<id>.json`（monitor_data 本就是监测版自管目录），
原子写（`src.atomic_io`，与流水线任务记录同款）。

单飞（single-flight）：同一时刻只跑一个监测生成任务（与流水线
「一次只跑一期」同一纪律）；**同参**任务已在跑 → 复用其 job_id。
服务重启后残留的 running 记录由 `recover_stale()` 结成 failed
（守护线程随进程走了，不结掉会永远挡住新任务）。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import secrets
import threading
import time

import atomic_io
from agent import states as agent_states

from monitor import report as mr

#: 任务种类（params 形状见 routes/monitor.py 的两个任务口）
KIND_REPORT = "monitor_report"
KIND_COMPARE = "monitor_compare"

_lock = threading.Lock()


def _dir() -> pathlib.Path:
    """任务记录目录：`monitor_data/_jobs/`（跟 MONITOR_ROOT 走，测试可替身）。"""
    return pathlib.Path(mr.MONITOR_ROOT) / "_jobs"


def _path(job_id: str) -> pathlib.Path:
    return _dir() / f"{job_id}.json"


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_terminal(status) -> bool:
    """终态判定（与流水线 `server.jobs.is_terminal` 同一词汇源）。"""
    return agent_states.is_terminal(agent_states.normalize(status))


def read(job_id: str) -> dict | None:
    """读一条任务记录；没有 / 坏行 → None（与 state_store.get_job 同口径）。"""
    p = _path(str(job_id))
    if not p.is_file():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def _write(job: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    atomic_io.write_text_atomic(
        _path(job["id"]), json.dumps(job, ensure_ascii=False, indent=1))


def list_jobs(status: str | None = None) -> list[dict]:
    """任务记录（文件名序＝创建序，id 内嵌时间戳）；目录缺席 → []。"""
    d = _dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        rec = read(p.stem)
        if rec and (status is None or rec.get("status") == status):
            out.append(rec)
    return out


def any_running() -> bool:
    return any(j.get("status") == agent_states.RUNNING for j in list_jobs())


def find_running(kind: str, params: dict) -> dict | None:
    """同参任务已在跑 → 返回它（调用方直接复用 job_id，不重复起生成）。"""
    for j in list_jobs(status=agent_states.RUNNING):
        if j.get("kind") == kind and j.get("params") == params:
            return j
    return None


def create(kind: str, params: dict, actor: str = "",
           period: str = "") -> dict:
    """建一条 running 记录；另有监测任务在跑 → RuntimeError（口上转 409）。

    `params` 进记录也当幂等键：单校＝`{"school": 校名, "period": 期次}`，
    对比＝`{"schools": [去重保序], "period": 期次}`。
    """
    with _lock:
        if any_running():
            raise RuntimeError("已有监测生成任务在运行，请稍候")
        jid = time.strftime("%Y%m%d-%H%M%S") + "-m" + secrets.token_hex(2)
        job = {
            "id": jid, "kind": kind, "period": str(period or ""),
            "params": params, "actor": actor,
            "status": agent_states.RUNNING,
            "created_at": _now(), "started_at": _now(), "finished_at": None,
            "url": None, "error": None,
        }
        _write(job)
        return job


def launch(job: dict, fn, to_url) -> threading.Thread:
    """起守护线程跑 `fn()`，终点写回记录；返回线程（测试可 join）。

    失败语义（供应商强制语义，rick 2026-11-04）：`AIRequiredError` /
    `FileNotFoundError` 的 `str` 已是人话（位置＋原因码＋重试指引 /
    缺什么数据），原样入档；其余异常记 `类型: 摘要`。产物只在成功后
    给 url——`report.generate` / `compare.generate` 本就「解读算在
    写盘之前」，失败不落半份产物，这里没有残件可清。
    """
    jid = job["id"]

    def _work():
        try:
            path = fn()
            _finish(jid, status=agent_states.COMPLETED, url=str(to_url(path)))
        except Exception as e:                                   # noqa: BLE001
            from ai._attempt import AIRequiredError              # noqa: PLC0415
            if isinstance(e, (AIRequiredError, FileNotFoundError)):
                err = str(e)
            else:
                err = f"生成失败：{type(e).__name__}: {e}"[:300]
            _finish(jid, status=agent_states.FAILED, error=err)

    t = threading.Thread(target=_work, daemon=True, name=f"mjob-{jid}")
    t.start()
    return t


def _finish(job_id: str, *, status: str, url=None, error=None) -> None:
    with _lock:
        job = read(job_id)
        if job is None:
            return
        job["status"] = status
        job["finished_at"] = _now()
        job["url"] = url
        job["error"] = error
        _write(job)


def recover_stale() -> int:
    """把没有存活线程的 running 任务结成 failed（服务启动时调用一次）。

    routes 册 import 时调用：守护线程随进程消失，重启后 running 记录
    永远等不到终点，还会挡住新任务（单飞判据）。落 failed 不落
    cancelled——中断是意外，不是馆员主动停。返回结掉条数。
    """
    n = 0
    for j in list_jobs(status=agent_states.RUNNING):
        _finish(j["id"], status=agent_states.FAILED,
                error="服务重启，任务中断；请重新发起生成")
        n += 1
    return n
