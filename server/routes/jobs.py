# -*- coding: utf-8 -*-
"""jobs 分册：生成任务产线（20261101 C8 路由分册，从 server/app.py 迁入）。

建任务 / 进度 / 产物 / 下载 / 重跑 / SSE 事件流，以及老任务页保留的
`/jobs/{job_id}/download/{key}` 文件口（对话前门的三件套链接走这里）。
任务记录的读写全部经 `server.jobs` 模块属性（`jobs.read_job` 等）——
测试按模块对象打补丁，搬家不影响。
"""
import asyncio
import codecs
import json
import pathlib
import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from .. import acquisition, approval, archive, config, jobs
from ..guards import admin_route, user_file_route, user_route
from ..web_common import (_job_missing, _operator_download_guard,
                          _role_of_request, _serve_artifact,
                          _visible_artifacts, current_user, period_cards)
from src import ledger as ledger_mod  # 动态监测表（母本）路径唯一口径（2026-10-13：input/ 只放母本）

router = APIRouter()


@router.get("/api/archive/ledger")
@user_route
async def api_archive_ledger(request: Request):
    """运行档案总账：每一次运行一行（期次 / 状态 / 签发 / 时间 / 产物）。

    《运行档案-静态稿（20261102）》要的是「全部期次的留痕总账」，单期详情仍走
    `GET /api/periods/{period}/archive`（前端 `?view=archive&one=<期次>`）。
    本口只透传任务记录与签单记录里**已有**的字段：没有 finished_at 就用 created_at，
    没有产物字段就留空串——不推算、不补零，前端据此显示「—」。
    """
    cards = {c["period"]: c for c in period_cards()}
    rows = []
    for j in jobs.list_jobs(limit=500):
        pid = j.get("out_period") or j.get("period") or ""
        card = cards.get(pid) or {}
        rows.append({
            "id": j.get("id") or "",
            "period": pid,
            "status": j.get("status") or "",
            "at": j.get("finished_at") or j.get("created_at") or "",
            "artifact": "报告" if j.get("stats") else "",
            "approval": card.get("status") or "",
            "signed_at": card.get("signed_at") or "",
        })
    # 有成品但没有运行记录的期次也要露一行（静态稿里 202603 就是这种）：
    # 它签过单，只是这一库没有它的任务记录——留白比不出现更诚实。
    seen = {r["period"] for r in rows}
    for pid, card in cards.items():
        if pid in seen:
            continue
        rows.append({
            "id": "", "period": pid, "status": "", "at": "", "artifact": "",
            "approval": card.get("status") or "",
            "signed_at": card.get("signed_at") or "",
        })
    rows.sort(key=lambda r: (r["period"], r["at"]), reverse=True)
    return {"rows": rows, "periods": len({r["period"] for r in rows if r["period"]})}


@router.get("/api/jobs/{job_id}/approval")
@user_route
async def api_approval(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    rec = approval.read(out_dir)
    rec["status"] = approval.status(out_dir, rec)
    return rec


@router.get("/api/jobs/{job_id}/progress")
@user_route
async def api_job_progress(request: Request, job_id: str):
    """任务潜布：parse progress.jsonl -> events + 每步耗时。

    与档案页同口径：复用 `archive.waterfall`（start/收工配对、
    累计 elapsed 转本步耗时、orphan 标注）。数字只来自后端。

    直跑路径（一键出报告.bat）没有 progress.jsonl：missing=true 降级，不 500。
    """
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    prog = pathlib.Path(job.get("progress") or "")
    missing = bool(prog) and not prog.exists()
    events = jobs.read_progress(job)
    wf = archive.waterfall(events)
    return {
        "job_id": job_id,
        "status": job.get("status", ""),
        "events": events,
        "waterfall": wf,
        # 「完成」汇总单列（不进 waterfall 数组）——混进去会让合计翻倍
        "summary": archive.waterfall_summary(events),
        "total_sec": round(sum(r["sec"] for r in wf), 1),
        "missing": missing,
        "note": ("本次运行没有 progress.jsonl（不是由演示站发起的，"
                 "例如一键出报告.bat 直跑）") if missing else "",
    }


@router.post("/api/jobs")
@user_route
async def api_create_job(request: Request,
                         period: str = Form(""),
                         file: UploadFile = File(None),
                         backtest: str = Form("0")):
    period = (period or "").strip()
    busy = jobs.active_job()
    if busy:
        return JSONResponse({"error": f"已有任务运行中（{busy['period']}），请稍候"}, status_code=409)
    dest = None
    if file is not None and file.filename:
        if not file.filename.lower().endswith(".xlsx"):
            return JSONResponse({"error": "只支持 .xlsx 数据表文件"}, status_code=400)
        if not jobs.PERIOD_RE.match(period):
            return JSONResponse({"error": "请填写 6 位期次（如 202609），文件统一存为当期核对副本"}, status_code=400)
        data = await file.read()
        if len(data) > 50 * 1024 * 1024:
            return JSONResponse({"error": "文件超过 50MB"}, status_code=400)
        # 上传的表＝该期的数据表：落当期核对副本位（out/_acquisition/<期次>/监测表.xlsx），
        # 不再进 input/（2026-10-13 起 input/ 只放母本）。
        dest = acquisition.copy_path(period)
        # file.read() 会让出事件循环；恢复后重新检查，避免两个并发上传写同一文件。
        busy = jobs.active_job()
        if busy:
            return JSONResponse({"error": f"已有任务正在运行（{busy['period']}），请稍候"}, status_code=409)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    else:
        if not jobs.PERIOD_RE.match(period):
            return JSONResponse({"error": "请先填写期次"}, status_code=400)
        dest = ledger_mod.runtime_path(config.ROOT)
        if not dest.exists():
            return JSONResponse({"error": f"input/{ledger_mod.LEDGER_NAME} 不存在（请把母本放入 input/）"},
                                status_code=404)
    busy = jobs.active_job()
    if busy:
        return JSONResponse({"error": f"已有任务运行中（{busy['period']}），请稍候"}, status_code=409)
    try:
        job = jobs.create_job(period, dest, current_user(request), backtest=(backtest == "1"))
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"job_id": job["id"], "url": f"/jobs/{job['id']}"}


@router.get("/api/jobs/{job_id}")
@user_route
async def api_job(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    # 契约 §2.3：失败态给结构化的「缺什么」，不让前端解析断言文本
    if job.get("missing"):
        job["ok"] = False
    return job


@router.get("/api/jobs/{job_id}/artifacts")
@user_route
async def api_artifacts(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    return {"job": job,
            "artifacts": _visible_artifacts(jobs.collect_artifacts(job),
                                            _role_of_request(request))}


@router.get("/api/jobs/{job_id}/download/{key}")
@admin_route
async def api_job_download(request: Request, job_id: str, key: str):
    """任务产物与日志包只属于管理员运行工作区。"""
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _serve_artifact(out_dir=out_dir, key=key, pack_job=job,
                           resolve=lambda: jobs.resolve_artifact(job, key))


@router.post("/api/jobs/{job_id}/rerun")
@admin_route
async def api_rerun_job(request: Request, job_id: str):
    user = current_user(request)
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    input_path = pathlib.Path(job.get("input", ""))
    if not input_path.exists():
        return JSONResponse({"error": "原输入文件已不存在，请重新上传台账"}, status_code=404)
    busy = jobs.active_job()
    if busy:
        return JSONResponse({"error": f"已有任务运行中（{busy['period']}），请稍候"}, status_code=409)
    try:
        new_job = jobs.create_job(job["period"], input_path, user,
                                  backtest=job.get("backtest", False))
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"job_id": new_job["id"], "url": f"/jobs/{new_job['id']}"}


# ---------------- SSE ----------------

def _sse(event: str, payload: str) -> str:
    return f"event: {event}\ndata: {payload}\n\n"


def _tail(path: pathlib.Path, state: dict):
    """增量读取 UTF-8 文本行（多字节安全，保留未完成行）。"""
    if "decoder" not in state:
        state["decoder"] = codecs.getincrementaldecoder("utf-8")("replace")
        state["offset"] = 0
        state["buf"] = ""
    if not path or not path.exists():
        return []
    size = path.stat().st_size
    if size < state["offset"]:
        state.update({"offset": 0, "buf": ""})
    if size == state["offset"]:
        return []
    with open(path, "rb") as f:
        f.seek(state["offset"])
        data = f.read()
        state["offset"] = f.tell()
    text = state["buf"] + state["decoder"].decode(data)
    lines = text.split("\n")
    state["buf"] = lines.pop()
    return [l for l in lines if l.strip()]


@router.get("/api/jobs/{job_id}/events")
@user_route
async def api_events(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()

    async def gen():
        prog = pathlib.Path(job.get("progress", ""))
        console = pathlib.Path(job.get("console", ""))
        ps, cs = {}, {}
        last_ping = time.time()

        def flush_new():
            out = [_sse("progress", line) for line in _tail(prog, ps)]
            out += [_sse("log", json.dumps({"line": line}, ensure_ascii=False))
                    for line in _tail(console, cs)]
            return out

        # 先回放历史（进度/控制台），再发状态：终态任务必须完整回放后才允许前端关闭连接
        for ev in flush_new():
            yield ev
        cur = jobs.read_job(job_id) or job
        yield _sse("status", json.dumps(cur, ensure_ascii=False))

        while True:
            if await request.is_disconnected():
                return
            for ev in flush_new():
                yield ev
            cur = jobs.read_job(job_id)
            if cur and jobs.is_terminal(cur.get("status")):
                for ev in flush_new():
                    yield ev
                yield _sse("status", json.dumps(cur, ensure_ascii=False))
                return
            if time.time() - last_ping > 15:
                yield ": ping\n\n"
                last_ping = time.time()
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ---------------- 下载（老任务口，二维码等杂项在 misc 册） ----------------

@router.get("/jobs/{job_id}/download/{key}")
@user_file_route
async def download(request: Request, job_id: str, key: str):
    """任务产物下载（旧路由；对话前门的三件套链接走这里）。

    2026-10-12：出报告对操作员开放——与期次口（`/p/{p}/download`）同款：
    操作员只读放行，但红件/日志包类键仅管理员可下载。
    """
    guard = _operator_download_guard(_role_of_request(request), key)
    if guard:
        return guard
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _serve_artifact(out_dir=out_dir, key=key, pack_job=job,
                           resolve=lambda: jobs.resolve_artifact(job, key))
