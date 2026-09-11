# -*- coding: utf-8 -*-
"""文衡 · 学科信息参考自动化演示站（FastAPI）。

启动（在 wenheng 目录下）：
    .venv\\Scripts\\python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8080
"""
import asyncio
import codecs
import io
import json
import pathlib
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import config, jobs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()
    yield


app = FastAPI(title="文衡 · 学科信息参考自动化演示", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET, same_site="lax")
app.mount("/static", StaticFiles(directory=str(config.SERVER_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(config.SERVER_DIR / "templates"))

_login_fails = {}


def current_user(request: Request):
    return request.session.get("user")


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise PermissionError
    return user


def page(request: Request, name: str, **ctx):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ctx.update({"request": request, "user": user})
    return templates.TemplateResponse(request, name, ctx)


@app.on_event("startup")
async def _startup():
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()


# ---------------- 认证 ----------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, err: str = ""):
    return templates.TemplateResponse(
        request, "login.html",
        {"request": request, "err": err, "hint": config.SHOW_HINT,
         "show_hint_user": config.DEMO_USER if config.SHOW_HINT else ""})


@app.post("/login")
async def do_login(request: Request, username: str = Form(""), password: str = Form("")):
    ip = request.client.host if request.client else "?"
    rec = _login_fails.setdefault(ip, {"n": 0, "until": 0.0})
    if rec["until"] > time.time():
        return RedirectResponse("/login?err=尝试过于频繁，请稍后再试", status_code=303)
    if username == config.DEMO_USER and password == config.DEMO_PASS:
        request.session["user"] = username
        _login_fails.pop(ip, None)
        return RedirectResponse("/", status_code=303)
    rec["n"] += 1
    if rec["n"] >= 5:
        rec.update({"n": 0, "until": time.time() + 60})
    return RedirectResponse("/login?err=账号或密码不正确", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------- 页面 ----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    periods = []
    if config.INPUT_DIR.exists():
        for p in sorted(config.INPUT_DIR.glob("*/监测表.xlsx"), reverse=True):
            if jobs.PERIOD_RE.match(p.parent.name):
                periods.append({"period": p.parent.name,
                                "mtime": time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    recent = [{"id": j["id"], "period": j["period"], "status": j["status"],
               "created_at": j["created_at"], "elapsed": (j.get("stats") or {}).get("elapsed_sec")}
              for j in jobs.list_jobs(8)]
    last = next((j for j in jobs.list_jobs(20) if j.get("stats")), None)
    return page(request, "index.html", periods=periods, steps=config.STEPS,
                recent=recent, active=jobs.active_job(),
                last_stats=(last or {}).get("stats"), last_period=(last or {}).get("period"),
                public_url=config.PUBLIC_URL,
                reference_exists=bool(config.REFERENCE_DOCX and pathlib.Path(config.REFERENCE_DOCX).exists()),
                engine={"pipeline": config.PIPELINE.exists(), "master": config.MASTER.exists(),
                        "python": pathlib.Path(config.PYTHON).exists()})


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    return page(request, "job.html", job=job, job_json=json.dumps(job, ensure_ascii=False),
                steps=config.STEPS, events=jobs.read_progress(job),
                artifacts=jobs.collect_artifacts(job), terminal=job["status"] in jobs.TERMINAL)


@app.get("/jobs/{job_id}/redslots", response_class=HTMLResponse)
async def redslots_page(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    p = config.OUT_DIR / (job.get("out_period") or job["period"]) / "red_slots.json"
    slots = []
    if p.exists():
        try:
            slots = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            slots = []
    stats = {}
    for s in slots:
        loc = s.get("location", "")
        group = loc.split("/")[0] if "/" in loc else loc
        if loc.startswith("T01/r"):
            group = "大表数值格"
        elif loc.startswith("T0") or loc.startswith("T1"):
            group = loc.split("/")[0]
        stats[group] = stats.get(group, 0) + 1
    return page(request, "redslots.html", job=job, slots=slots,
                groups=sorted(stats.items(), key=lambda kv: -kv[1]))


# ---------------- API ----------------

@app.get("/healthz")
async def healthz():
    return {"ok": True, "pipeline": config.PIPELINE.exists(),
            "jobs_dir": str(config.JOBS_DIR)}


@app.get("/api/status")
async def api_status():
    active = jobs.active_job()
    last = next((j for j in jobs.list_jobs(20) if j.get("stats")), None)
    return {"active": (active or {}).get("id"), "last": last}


@app.post("/api/jobs")
async def api_create_job(request: Request,
                         period: str = Form(""),
                         file: UploadFile = File(None),
                         backtest: str = Form("0")):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    period = (period or "").strip()
    dest = None
    if file is not None and file.filename:
        if not file.filename.lower().endswith(".xlsx"):
            return JSONResponse({"error": "仅支持 .xlsx 台账文件"}, status_code=400)
        if not jobs.PERIOD_RE.match(period):
            return JSONResponse({"error": "请填写 6 位期次（如 202609），文件名统一存为监测表.xlsx"}, status_code=400)
        data = await file.read()
        if len(data) > 50 * 1024 * 1024:
            return JSONResponse({"error": "文件超过 50MB"}, status_code=400)
        dest = config.INPUT_DIR / period / "监测表.xlsx"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    else:
        if not jobs.PERIOD_RE.match(period):
            return JSONResponse({"error": "请选择或填写期次"}, status_code=400)
        dest = config.INPUT_DIR / period / "监测表.xlsx"
        if not dest.exists():
            return JSONResponse({"error": f"input/{period}/监测表.xlsx 不存在，请先上传"}, status_code=404)
    busy = jobs.active_job()
    if busy:
        return JSONResponse({"error": f"已有任务运行中（{busy['period']}），请稍候"}, status_code=409)
    try:
        job = jobs.create_job(period, dest, current_user(request), backtest=(backtest == "1"))
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"job_id": job["id"], "url": f"/jobs/{job['id']}"}


@app.get("/api/jobs/{job_id}")
async def api_job(request: Request, job_id: str):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return job


@app.get("/api/jobs/{job_id}/artifacts")
async def api_artifacts(request: Request, job_id: str):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return {"job": job, "artifacts": jobs.collect_artifacts(job)}


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


def _flush(state):
    if state.get("buf"):
        line, state["buf"] = state["buf"], ""
        if line.strip():
            return [line]
    return []


@app.get("/api/jobs/{job_id}/events")
async def api_events(request: Request, job_id: str):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    async def gen():
        prog = pathlib.Path(job.get("progress", ""))
        console = pathlib.Path(job.get("console", ""))
        ps, cs = {}, {}
        last_ping = time.time()
        yield _sse("status", json.dumps(job, ensure_ascii=False))
        while True:
            if await request.is_disconnected():
                break
            for line in _tail(prog, ps):
                yield _sse("progress", line)
            for line in _tail(console, cs):
                yield _sse("log", json.dumps({"line": line}, ensure_ascii=False))
            cur = jobs.read_job(job_id)
            if cur and cur.get("status") in jobs.TERMINAL:
                for line in _flush(ps):
                    yield _sse("progress", line)
                for line in _flush(cs):
                    yield _sse("log", json.dumps({"line": line}, ensure_ascii=False))
                yield _sse("status", json.dumps(cur, ensure_ascii=False))
                break
            if time.time() - last_ping > 15:
                yield ": ping\n\n"
                last_ping = time.time()
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ---------------- 下载 / 二维码 ----------------

@app.get("/jobs/{job_id}/download/{key}")
async def download(request: Request, job_id: str, key: str):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    path = jobs.resolve_artifact(job, key)
    if not path:
        return JSONResponse({"error": "产物不存在"}, status_code=404)
    return FileResponse(path, filename=path.name,
                        media_type="application/octet-stream")


@app.get("/qr.png")
async def qr(request: Request):
    url = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    try:
        import qrcode
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="image/png")
    except Exception:  # noqa: BLE001
        return JSONResponse({"url": url}, status_code=200)
