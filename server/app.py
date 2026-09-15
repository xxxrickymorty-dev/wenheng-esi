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
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import approval, collation, config, jobs


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

def _ledger_periods():
    """input/ 下可选的台账期次（控制台表单用）。"""
    out = []
    if config.INPUT_DIR.exists():
        for p in sorted(config.INPUT_DIR.glob("*/监测表.xlsx"), reverse=True):
            if jobs.PERIOD_RE.match(p.parent.name):
                out.append({"period": p.parent.name,
                            "mtime": time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return out


def _run_ctx():
    """控制台（发起任务）页面的上下文。"""
    recent = [{"id": j["id"], "period": j["period"], "status": j["status"],
               "created_at": j["created_at"], "elapsed": (j.get("stats") or {}).get("elapsed_sec")}
              for j in jobs.list_jobs(8)]
    last = next((j for j in jobs.list_jobs(20) if j.get("stats")), None)
    return {
        "periods": _ledger_periods(), "steps": config.STEPS,
        "recent": recent, "active": jobs.active_job(),
        "last_stats": (last or {}).get("stats"), "last_period": (last or {}).get("period"),
        "public_url": config.PUBLIC_URL,
        "reference_exists": bool(config.REFERENCE_DOCX and pathlib.Path(config.REFERENCE_DOCX).exists()),
        "engine": {"pipeline": config.PIPELINE.exists(), "master": config.MASTER.exists(),
                   "python": pathlib.Path(config.PYTHON).exists()},
    }


def period_cards():
    """可对勘的期次（out/<期次>/ 且有 red_slots.json），按新到旧，带签单状态。

    首屏的「期次印记链」就是用它渲染的——每期一枚印，签过的是朱印。
    """
    cards = []
    if not config.OUT_DIR.exists():
        return cards
    for d in config.OUT_DIR.iterdir():
        if not d.is_dir() or not jobs.PERIOD_DIR_RE.match(d.name):
            continue
        if not (d / "red_slots.json").exists():
            continue
        rec = approval.read(d)
        cards.append({
            "period": d.name,
            "url": "/p/" + urllib.parse.quote(d.name),
            "status": approval.status(d, rec),
            "signed_at": rec.get("signed_at") or "",
            "signed_actor": rec.get("actor") or "",
        })
    cards.sort(key=lambda c: c["period"], reverse=True)
    return cards


def resolve_period_dir(period):
    """期次字符串 → out/ 下的实际目录（允许 202605_复现 这类后缀）。非法或不存在返回 None。"""
    if not jobs.PERIOD_DIR_RE.match(period or ""):
        return None
    d = config.OUT_DIR / period
    if d.is_dir() and (d / "red_slots.json").exists():
        return d
    return None


def _collation_data(out_dir, job=None, flash=None, self_url=None):
    """对勘本上下文。任务入口与期次入口共用，差别只在面包屑与身份信息。

    签单/撤回统一投到 `/p/<期次>/…`：审批记录本来就按期次落盘，任务只是
    「谁跑的」这一层身份；表单目标跟着期次走，两个入口就不会各拼一套 URL。
    `self_url` 是签完单回跳的落点（首屏是 `/`，期次页是 `/p/...`）。
    """
    data = collation.build(out_dir)
    q = urllib.parse.quote(out_dir.name)
    data["live"] = True                  # 有服务端：签单可落库
    data["periodDir"] = out_dir.name
    data["periods"] = period_cards()
    data["backUrl"] = self_url or f"/p/{q}"
    data["signUrl"] = f"/p/{q}/sign"
    data["revokeUrl"] = f"/p/{q}/revoke"
    data["jobId"] = job["id"] if job else ""
    data["actor"] = (job.get("actor") if job else "") or ""
    data["status"] = (job.get("status") if job else "") or ""
    crumbs = []
    if job:
        crumbs.append({"label": f"← 返回任务 {job['id']}", "href": f"/jobs/{job['id']}", "download": False})
        crumbs.append({"label": "红色件清单", "href": f"/jobs/{job['id']}/redslots", "download": False})
        crumbs.append({"label": "下载报告初稿", "href": f"/jobs/{job['id']}/download/report", "download": True})
    else:
        crumbs.append({"label": "发起任务 / 历史任务", "href": "/run", "download": False})
        crumbs.append({"label": "红色件清单", "href": f"/p/{q}/redslots", "download": False})
        crumbs.append({"label": "下载报告初稿", "href": f"/p/{q}/download/report", "download": True})
    data["crumbs"] = crumbs
    rec = approval.read(out_dir)
    data["approval"] = rec
    data["approvalStatus"] = approval.status(out_dir, rec)
    data["flash"] = flash or {}
    return data


def _render_collation(request, out_dir, job=None, flash=None, self_url=None):
    return page(request, "collation.html", job=job or {},
                data=_collation_data(out_dir, job=job, flash=flash, self_url=self_url))


def _redslots_page(request, out_dir, job=None):
    """逐格红色件清单。任务入口与期次入口共用，只差返回/下载链接指哪儿。"""
    p = out_dir / "red_slots.json"
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
    q = urllib.parse.quote(out_dir.name)
    if job:
        back_url = f"/jobs/{job['id']}/collation"
        download_url = f"/jobs/{job['id']}/download/red_list"
    else:
        back_url = f"/p/{q}"
        download_url = f"/p/{q}/download/red_list"
    return page(request, "redslots.html", job=job or {}, period=out_dir.name,
                slots=slots, groups=sorted(stats.items(), key=lambda kv: -kv[1]),
                backUrl=back_url, downloadUrl=download_url)


def _flash(err="", signed="", revoked=""):
    return {"err": err, "signed": signed, "revoked": revoked}


def _safe_back(back, fallback):
    """只接受站内相对路径，防止被拼成开放重定向。"""
    b = (back or "").strip()
    return b if b.startswith("/") and not b.startswith("//") else fallback


def _do_sign(request, period, note, ack, back):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    ok, res = approval.sign(d, user, collation.build(d), note=note, manual_ack=bool(ack))
    target = _safe_back(back, "/p/" + urllib.parse.quote(period))
    sep = "&" if "?" in target else "?"
    if not ok:
        return RedirectResponse(f"{target}{sep}err={urllib.parse.quote(str(res))}", status_code=303)
    return RedirectResponse(f"{target}{sep}signed=1", status_code=303)


def _do_revoke(request, period, note, back):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    ok, res = approval.revoke(d, user, note=note)
    target = _safe_back(back, "/p/" + urllib.parse.quote(period))
    sep = "&" if "?" in target else "?"
    if not ok:
        return RedirectResponse(f"{target}{sep}err={urllib.parse.quote(str(res))}", status_code=303)
    return RedirectResponse(f"{target}{sep}revoked=1", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, err: str = "", signed: str = "", revoked: str = ""):
    """**首屏 = 对勘本**（最新一期）。没有可对勘的期次时才退回控制台。

    报告才是这个产品的主角，跑流水线是手段——所以控制台让位，退到 /run。
    """
    cards = period_cards()
    if cards:
        d = resolve_period_dir(cards[0]["period"])
        if d is not None:
            return _render_collation(request, d, flash=_flash(err, signed, revoked), self_url="/")
    return page(request, "index.html", **_run_ctx())


@app.get("/run", response_class=HTMLResponse)
async def run_page(request: Request):
    """控制台：选期次 / 上传台账 / 一键生成 + 最近任务。"""
    return page(request, "index.html", **_run_ctx())


@app.get("/p/{period}", response_class=HTMLResponse)
async def period_collation(request: Request, period: str,
                           err: str = "", signed: str = "", revoked: str = ""):
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    return _render_collation(request, d, flash=_flash(err, signed, revoked),
                             self_url=request.url.path)


@app.get("/p/{period}/redslots", response_class=HTMLResponse)
async def period_redslots(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    return _redslots_page(request, d)


@app.post("/p/{period}/sign")
async def period_sign(request: Request, period: str, note: str = Form(""),
                      ack: str = Form(""), back: str = Form("")):
    return _do_sign(request, period, note, ack, back)


@app.post("/p/{period}/revoke")
async def period_revoke(request: Request, period: str, note: str = Form(""),
                        back: str = Form("")):
    return _do_revoke(request, period, note, back)


@app.get("/p/{period}/download/{key}")
async def period_download(request: Request, period: str, key: str):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    if resolve_period_dir(period) is None:
        return RedirectResponse("/", status_code=303)
    path = jobs.resolve_period_artifact(period, key)
    if not path:
        return JSONResponse({"error": "产物不存在"}, status_code=404)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


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
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _redslots_page(request, out_dir, job=job)


@app.get("/jobs/{job_id}/collation", response_class=HTMLResponse)
async def collation_page(request: Request, job_id: str,
                         err: str = "", signed: str = "", revoked: str = ""):
    """对勘本：正文级「上期 → 本期」对照，与红色件清单读同一份 red_slots.json。"""
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _render_collation(request, out_dir, job=job,
                             flash=_flash(err, signed, revoked),
                             self_url=f"/jobs/{job_id}/collation")


@app.post("/jobs/{job_id}/collation/sign")
async def collation_sign(request: Request, job_id: str,
                         note: str = Form(""), ack: str = Form("")):
    """签单落库。闸门不过就拒绝，把原因回带页面上。"""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    ok, res = approval.sign(out_dir, user, collation.build(out_dir),
                            note=note, manual_ack=bool(ack))
    if not ok:
        q = urllib.parse.quote(str(res))
        return RedirectResponse(f"/jobs/{job_id}/collation?err={q}", status_code=303)
    return RedirectResponse(f"/jobs/{job_id}/collation?signed=1", status_code=303)


@app.post("/jobs/{job_id}/collation/revoke")
async def collation_revoke(request: Request, job_id: str, note: str = Form("")):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    ok, res = approval.revoke(out_dir, user, note=note)
    if not ok:
        q = urllib.parse.quote(str(res))
        return RedirectResponse(f"/jobs/{job_id}/collation?err={q}", status_code=303)
    return RedirectResponse(f"/jobs/{job_id}/collation?revoked=1", status_code=303)


@app.get("/api/jobs/{job_id}/approval")
async def api_approval(request: Request, job_id: str):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    rec = approval.read(out_dir)
    rec["status"] = approval.status(out_dir, rec)
    return rec


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


@app.post("/api/jobs/{job_id}/rerun")
async def api_rerun_job(request: Request, job_id: str):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
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
            if cur and cur.get("status") in jobs.TERMINAL:
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
