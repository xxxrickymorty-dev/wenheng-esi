# -*- coding: utf-8 -*-
"""文衡 · 学科信息参考自动化演示站（FastAPI）。

启动（在 wenheng 目录下）：
    .venv\\Scripts\\python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8080
"""
import asyncio
import codecs
import hashlib
import io
import json
import pathlib
import re
import subprocess
import time
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response, StreamingResponse)
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import acquisition, approval, archive, collation, config, jobs, report_preview, shelf_data, shelf_preview
from . import forecasting
from .guards import admin_file_route, admin_route
from src import parse_ledger  # 成品隔离/回滚的唯一口径（FINAL_PRODUCTS / SUPERSEDED_DIR）
from .protected_static import AdminStaticFiles
from src import period as period_mod  # 期次口径唯一来源（ADR-0001：新工作区 API 也用它）
from src import forecast_choice  # 预测选模的唯一 implementation（读写/快照/留痕）
from esi_v1.data import display_name  # 学科名中文化（契约 #22）


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()
    yield


app = FastAPI(title="文衡 · 学科信息参考自动化演示", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET, same_site="lax")
app.mount("/static", AdminStaticFiles(directory=str(config.SERVER_DIR / "static"),
                                       protected_paths=("collation-demo.html",)), name="static")
# 新工作区系统（React SPA，构建产物 web/dist 入库）——见 docs/adr/0001。
# check_dir=False：干净 clone 里 dist 缺失时不要拖垮整个服务启动，让它 404 就行。
async def _shelf_guest_data():
    return await run_in_threadpool(shelf_preview.javascript_response, period_cards())


async def _shelf_admin_data():
    """每次请求均从已部署期次构建，避免把指标留在静态构建产物。"""
    return await run_in_threadpool(shelf_data.javascript_response, period_cards())


app.mount("/app", AdminStaticFiles(directory=str(config.ROOT / "web" / "dist"), html=True,
                                   check_dir=False, require_login=True,
                                   protected_paths=("shelf/data.js", "shelf/preview.js"),
                                   guest_responses={"shelf/data.js": _shelf_guest_data,
                                                    "shelf/preview.js": _shelf_guest_data},
                                   admin_responses={"shelf/data.js": _shelf_admin_data,
                                                    "shelf/preview.js": _shelf_guest_data}), name="web")
templates = Jinja2Templates(directory=str(config.SERVER_DIR / "templates"))


# ---- 静态资源不能被浏览器自作主张缓存（2026-09-17）----------------------------
# 踩过的坑：当年改完 collation.js（现已删，2026-09-24 并入离线快照内联）重启服务、
# curl 也验过服务器发的是新文件，但页面上就是没变化。原因是 StaticFiles
# **只发 etag/last-modified、不发 Cache-Control**，
# 浏览器于是套用「启发式新鲜度」（约等于距上次修改时间的 10%）—— 旧 JS 在本地缓存里
# 能活好几个小时，**期间根本不回服务器问**。表现出来就是「功能好像没做」。
# 双保险：① 模板里的 URL 带 `?v=<指纹>`，资源一变 URL 就变，缓存必然失效；
# ② 静态响应一律 no-cache，即便有人手写了个不带版本的地址，也必须回源校验。
@app.middleware("http")
async def _static_revalidate(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith(("/static/", "/app/")):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


_ASSET_STAMP = {}


def asset(name):
    """静态资源 URL，带按（体积, 修改时间）算出的版本号。`name` 是 `/static/` 下的相对路径。

    文件不在就退化成不带版本号的地址 —— 宁可 404 让人看见，也不要编个假版本号。
    """
    p = config.SERVER_DIR / "static" / name
    try:
        st = p.stat()
        key = (st.st_size, st.st_mtime_ns)
    except OSError:
        return f"/static/{name}"
    hit = _ASSET_STAMP.get(name)
    if hit is None or hit[0] != key:
        tag = hashlib.sha1(f"{key[0]}:{key[1]}".encode()).hexdigest()[:10]
        hit = (key, tag)
        _ASSET_STAMP[name] = hit
    return f"/static/{name}?v={hit[1]}"


templates.env.globals["asset"] = asset

# ---- 状态口径注入模板（2026-09-15）------------------------------------------
# 唯一来源是 `src/agent/states.py`。模板里**不要再写** {'done':'完成', ...} 这类
# 字面量字典——那正是旧 4 态与 10 态各说各话的来源。
templates.env.globals.update(
    status_label=jobs.status_label,          # {{ status_label(job.status) }}
    status_labels=config.STATUS_LABELS,      # JS 用：window.__STATUS_LABELS__
    terminal_states=sorted(jobs.TERMINAL),
)

_login_fails = {}


def current_user(request: Request):
    return request.session.get("user")


def require_admin(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录", "hint": "请先登录"}, status_code=401)
    if config.role_of(user) != "admin":
        return JSONResponse({"error": "需要管理员权限", "hint": "游客不能执行此操作"}, status_code=403)
    return user


def require_admin_file(request: Request):
    """附件与图沿用旧的未登录跳转，guest 明确拒绝。"""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if config.role_of(user) != "admin":
        return JSONResponse({"error": "需要管理员权限", "hint": "游客不能查看报告内容"}, status_code=403)
    return user


def _signed_report_download_guard(out_dir, key: str):
    """报告初稿只允许管理员下载当前指纹有效的已签发版本。"""
    if key != "report" or approval.status(out_dir) == "signed":
        return None
    return JSONResponse({"error": "报告未签发或签发已失效，不能下载"}, status_code=403)


def _period_missing():
    """API 侧「期次不存在」的统一 404（老路由仍是 303，两种口径都在 tests 里钉着）。"""
    return JSONResponse(
        {"error": "期次不存在", "hint": "请先在控制台上传台账生成该期次"}, status_code=404)


def _job_missing():
    """「任务不存在」的统一 404。"""
    return JSONResponse(
        {"error": "任务不存在", "hint": "请检查任务 ID 是否正确"}, status_code=404)


def _serve_artifact(*, out_dir, key, pack_job, resolve):
    """产物 / 日志包下载共段：logpack → 签发门 → 文件流。四条下载路由共用。

    `resolve` 是产物适配器（期次路由用 `resolve_period_artifact`，任务路由用
    `resolve_artifact`）；缺产物统一 404。路由间的 303/404 差异由调用方决定。
    """
    if key == archive.LOGPACK_KEY:
        data, name = archive.pack(out_dir, pack_job)
        return _zip_response(data, name)
    report_guard = _signed_report_download_guard(out_dir, key)
    if report_guard:
        return report_guard
    path = resolve()
    if not path:
        return JSONResponse({"error": "产物不存在"}, status_code=404)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


def _legacy_admin_gate(request):
    """旧页面先按身份分流，游客请求不探测期次或任务是否存在。"""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if config.role_of(user) != "admin":
        return RedirectResponse("/app/shelf/", status_code=303)
    return None


def _legacy_redirect(request, key, **fmt):
    """老路由 302 的统一出口：仅管理员可进入对应的新工作台。

    未登录的访问与旧页面一样落到 /login（303）——新站只认 /api/me 的 401，
    老 URL 的闸得在老站这一侧关住。
    """
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    target = config.LEGACY_REDIRECTS[key]
    if fmt:
        target = target.format(**fmt)
    return RedirectResponse(target, status_code=302)


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
    if check_credentials(username, password):
        request.session["user"] = username
        _login_fails.pop(ip, None)
        target = "/app/shelf/" if config.role_of(username) == "guest" else "/"
        return RedirectResponse(target, status_code=303)
    rec["n"] += 1
    if rec["n"] >= 5:
        rec.update({"n": 0, "until": time.time() + 60})
    return RedirectResponse("/login?err=账号或密码不正确", status_code=303)


def check_credentials(username: str, password: str) -> bool:
    """登录口令校验：admin（demo）与只读游客（guest）各一套。

    ⚠ 2026-09-24 修：此前只放行 demo，`config.GUEST_USER/GUEST_PASS` 定义了却登不进来
    （游客角色只能靠打桩验，演示时也没法真登）。`role_of` 早就认 guest，缺的就是这道口。
    """
    return ((username == config.DEMO_USER and password == config.DEMO_PASS)
            or (username == config.GUEST_USER and password == config.GUEST_PASS))


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------- 页面 ----------------
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


def _zip_response(data: bytes, filename: str):
    """日志包下载。文件名是 ASCII（中文名在部分浏览器会乱码），说明写在包内 README。"""
    return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/", response_class=HTMLResponse)

async def home(request: Request, err: str = "", signed: str = "",
               revoked: str = "", rebuilt: str = "", saved: str = "", p: str = ""):
    """旧首页已下线（ADR-0002 阶段 2）—— 302 到新工作区系统。

    旧工作台（workbench.html）与控制台入口都在 /app/。
    保留函数签名：老链接可能带 ?p= / ?rebuilt= 等参数，接下来丢弃即可。
    """
    return _legacy_redirect(request, "/")


@app.get("/run", response_class=HTMLResponse)


async def run_page(request: Request):
    """旧控制台已下线（ADR-0002 阶段 2）—— 302 到新工作区系统。"""
    return _legacy_redirect(request, "/run")


@app.get("/forecast", response_class=HTMLResponse)
async def forecast_page(request: Request):
    """老预测页已下线（ADR-0002 阶段 2）—— 302 到新预测台 `?view=forecast`。

    数据面（`/api/forecast/meta`、`/api/forecast/run`）不变，仍由
    `forecasting.page_context()` 供给。
    """
    return _legacy_redirect(request, "/forecast")


@app.get("/p/{period}", response_class=HTMLResponse)
async def period_collation(request: Request, period: str,
                           err: str = "", signed: str = "", revoked: str = ""):
    """老对勘本已下线（ADR-0002 阶段 2）—— 302 到新工作区阅读视图。

    非法/不存在的期次落回新站首页（保留旧「回落首页」语义）。
    """
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/redslots", response_class=HTMLResponse)
async def period_redslots(request: Request, period: str):
    """老红件清单页已下线（ADR-0002 阶段 2）—— 302 到新工作区。"""
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/redslots" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/trace", response_class=HTMLResponse)
async def period_trace(request: Request, period: str):
    """老逐格溯源页已下线（ADR-0002 阶段 2）—— 302 到新工作区。

    数据等价物走 `GET /api/periods/{period}/trace`（现场真读台账，同一套
    `workbench.trace` 装配）。
    """
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/trace" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


def _find_ledger(period_dir):
    """按期次找台账：input/<六位期次>/监测表.xlsx。找不到返回 None（页面降级说明）。"""
    # ⚠ period_dir 常是完整路径（C:\...\out\202607），从**目录名**取期次，
    #   从头匹配整条路径永远 None —— 这个 bug 刚刚让 trace 页空跑了一回。
    name = pathlib.Path(period_dir).name
    m = re.match(r"^(\d{6})", name)
    if not m:
        return None
    p = config.INPUT_DIR / m.group(1) / "监测表.xlsx"
    return p if p.exists() else None


@app.get("/p/{period}/charts", response_class=HTMLResponse)
async def period_charts(request: Request, period: str):
    """老图册页已下线（ADR-0002 阶段 2）—— 302 到新工作区。"""
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/charts" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


# ============================ 灵活报告（第二条产线）============================
# 口径见 `评审文档/19-双模式报告设计方案v1（权威口径）`。
# 🔴 复刻路径**完全不受影响**：这些路由只读 `out/<期次>/`、只写
#    `out/<期次>/flexible/`，与复刻报告的产物（报告初稿 / red_slots / charts）互不重叠。
# ⚠ 2026-09-21 合入 V1 预测模块（PR #1）时这一整块被对方那份 app.py 覆盖掉了，
#    靠 `tests/test_stack_contract.py::test_状态变更都走表单POST而非AJAX` 抓回来。
#    删任何一条 `/p/{period}/*` 路由前，先想清楚工作台首屏的入口会不会变成 404。

def _flex_ctx(d, intent=None, flash=None):
    """灵活报告页上下文。"""
    import flexible.report as flex_report                           # noqa: PLC0415
    from flexible import mdview, planner, spec                     # noqa: PLC0415
    reports = flex_report.list_reports(d)
    cur = next((r for r in reports if r["intent"] == intent), None) or \
        (reports[0] if reports else None)
    body = None
    if cur:
        md = pathlib.Path(cur["path"]).read_text(encoding="utf-8")
        imgmap = {n: f"/p/{d.name}/flexible/chart/{cur['intent']}/"
                     + urllib.parse.quote(n)
                  for n in (cur.get("meta", {}).get("charts") or [])}
        body = mdview.render(md, img_map=imgmap)
    return {"period_dir": d.name, "reports": reports, "cur": cur, "body": body,
            "intents": [{"id": k, "cn": v} for k, v in planner.INTENTS.items()],
            "chart_catalog": spec.catalog(), "flash": flash}


@app.get("/p/{period}/flexible", response_class=HTMLResponse)

async def period_flexible(request: Request, period: str, intent: str = "",
                          err: str = "", ok: str = ""):
    """老灵活报告页已下线（ADR-0002 第二轮）—— 302 到分析台（灵活报告是其中一块）。

    保留函数签名：老链接可能带 `?intent=` / `?err=` / `?ok=`，接下来丢弃即可。
    🔴 **图表路由 `/p/{period}/flexible/chart/*` 与 JSON API 不动**——
       新站分析台的 body_html 直接引用那些图地址（契约 #21）。
    """
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/flexible" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/flexible/chart/{intent}/{name}")
@admin_file_route
async def period_flexible_chart(request: Request, period: str,
                                intent: str, name: str):
    """灵活报告的图。**与复刻图分开解析** —— 归到 `flexible/<intent>/charts/` 下。"""
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    p = jobs.resolve_flex_chart(d, intent, name)
    if p is None:
        raise HTTPException(status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/p/{period}/archive", response_class=HTMLResponse)

async def period_archive(request: Request, period: str):
    """老运行档案页已下线（ADR-0002 第二轮）—— 302 到新档案视图。

    数据等价物走 `GET /api/periods/{period}/archive`（契约 #18）；
    下载端点 `/p/{period}/download/logpack` 保留（§六 保留项）。
    """
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/archive" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/chart/{rel:path}")
@admin_file_route
async def period_chart(request: Request, period: str, rel: str):
    """图表原图（只读）。`rel` 是 `red_slots.json` 里 `source` 去掉 `charts/` 的部分。

    越界请求由 `jobs.resolve_chart` 挡住——这条路由直接服务磁盘文件，
    少一道检查就能读到 `server/.env`，别在这里省事。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    p = jobs.resolve_chart(d, rel)
    if not p:
        return JSONResponse({"error": "图表不存在"}, status_code=404)
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


@app.get("/p/{period}/download/{key}")
@admin_file_route
async def period_download(request: Request, period: str, key: str):
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    return _serve_artifact(out_dir=d, key=key, pack_job=None,
                           resolve=lambda: jobs.resolve_period_artifact(period, key))


@app.get("/jobs/{job_id}", response_class=HTMLResponse)

async def job_page(request: Request, job_id: str):
    """旧任务页已下线（ADR-0002 阶段 2）—— 302 到新工作区系统。"""
    return _legacy_redirect(request, "/jobs/{job_id}")

@app.get("/jobs/{job_id}/redslots", response_class=HTMLResponse)

async def redslots_page(request: Request, job_id: str):
    """旧任务红件清单已下线—— 302 到新工作区（动态填任务的期次）。"""
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/app/", status_code=302)
    period = urllib.parse.quote(job.get("out_period") or job["period"])
    return _legacy_redirect(request, "/jobs/{job_id}/redslots", period=period)

@app.get("/jobs/{job_id}/charts", response_class=HTMLResponse)

async def charts_page(request: Request, job_id: str):
    """旧任务图册已下线—— 302 到新工作区（动态填任务的期次）。"""
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/app/", status_code=302)
    period = urllib.parse.quote(job.get("out_period") or job["period"])
    return _legacy_redirect(request, "/jobs/{job_id}/charts", period=period)

@app.get("/jobs/{job_id}/archive", response_class=HTMLResponse)

async def job_archive(request: Request, job_id: str):
    """老任务档案页已下线（ADR-0002 第二轮）—— 302 到新档案视图（动态填任务的期次）。"""
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/app/", status_code=302)
    period = urllib.parse.quote(job.get("out_period") or job["period"])
    return _legacy_redirect(request, "/jobs/{job_id}/archive", period=period)


@app.get("/jobs/{job_id}/collation", response_class=HTMLResponse)

async def collation_page(request: Request, job_id: str,
                         err: str = "", signed: str = "", revoked: str = ""):
    """旧任务对勘本已下线—— 302 到新工作区（动态填任务的期次）。"""
    gate = _legacy_admin_gate(request)
    if gate:
        return gate
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/app/", status_code=302)
    period = urllib.parse.quote(job.get("out_period") or job["period"])
    return _legacy_redirect(request, "/jobs/{job_id}/collation", period=period)

@app.get("/api/jobs/{job_id}/approval")
@admin_route
async def api_approval(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    rec = approval.read(out_dir)
    rec["status"] = approval.status(out_dir, rec)
    return rec


@app.get("/api/jobs/{job_id}/progress")
@admin_route
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


# ---------------- API ----------------

@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/status")
@admin_route
async def api_status(request: Request):
    """工作区任务入口：只提供前端跳转所需的任务标识，不暴露落盘记录。"""
    active = jobs.active_job()
    last = next((j for j in jobs.list_jobs(20) if j.get("stats")), None)
    return {
        "active": (active or {}).get("id"),
        "last": ({"id": last.get("id"), "period": last.get("period")}
                 if last else None),
    }


def _period_label(period: str) -> str:
    """期次文案走 src/period.py（口径唯一来源）；算不出总期号时退回期次名，不编假期号。"""
    try:
        _idx, total = period_mod.issue_of(period)
        return f"第 {total} 期 · {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        return period


def _period_has_data(period: str) -> bool:
    """「期次认得出」的宽松口径：取数状态或投喂副本已存在（还没出稿也算）。

    与 /api/periods 的补录、单期详情的宽松判定同一口径——取数台接手的期次，
    它的空产物 / 空回滚列表要回 200 空数组，而不是 404（404 会在页面控制台报错）。
    """
    m = re.match(r"^(\d{6})", period or "")
    if not m:
        return False
    pid = m.group(1)
    return (acquisition.load(pid) is not None
            or (config.INPUT_DIR / pid / "监测表.xlsx").exists())


def _acquisition_only_periods(known: set[str]) -> list[dict]:
    """还没出稿、但取数已经有动静的期次：有取数状态，或投喂副本已就位。

    取数台接手「未出稿的当期」——这些期次不在 period_cards（那要 red_slots.json），
    列表里单独补进来（状态按「未签发」显示，出稿后由 period_cards 接管）。
    """
    extra = set(acquisition.periods())
    if config.INPUT_DIR.exists():
        for d in config.INPUT_DIR.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{6}", d.name) and (d / "监测表.xlsx").exists():
                extra.add(d.name)
    return [{"period": p, "label": _period_label(p), "signed": False,
             "status": "unsigned", "generated": False,
             "url": "/p/" + urllib.parse.quote(p)}
            for p in sorted(extra - known, reverse=True)]


@app.get("/api/periods")
@admin_route
async def api_periods(request: Request):
    """期次列表（新工作区系统 /app 的数据源）——与首屏印记链同源（period_cards）。

    期次文案走 src/period.py（口径唯一来源）；带后缀目录（如 202605_复现）算不出
    总期号时退回目录名，不编假期号。另补「未出稿但取数在途」的期次（见上）。
    """
    out = []
    seen = set()
    for c in period_cards():
        out.append({"period": c["period"], "label": _period_label(c["period"]),
                    "signed": c["status"] == "signed", "status": c["status"],
                    "generated": True, "url": c["url"]})
        seen.add(c["period"])
    out.extend(_acquisition_only_periods(seen))
    out.sort(key=lambda item: item["period"], reverse=True)
    return {"periods": out}


@app.get("/api/me")
async def api_me(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录", "hint": "请先登录"}, status_code=401)
    return {"name": user, "role": config.role_of(user)}


@app.get("/api/periods/{period}")
@admin_route
async def api_period_detail(request: Request, period: str):
    """单期详情：三步条＝①取数 ②核对并并入 ③生成（ADR-0004）。

    未出稿但取数已有动静的期次（有取数状态、或投喂副本已就位）也返回详情——
    「先取数、后生成」的工作流需要它们在台面上；三步的判定不出数字。
    """
    m = re.match(r"^(\d{6})", period or "")
    pid = m.group(1) if m else period
    d = resolve_period_dir(period)
    acq = acquisition.load(pid)
    has_input = (config.INPUT_DIR / pid / "监测表.xlsx").exists()
    if d is None and acq is None and not has_input:
        return _period_missing()
    try:
        no, total = period_mod.issue_of(period)
        label = f"第 {total} 期 \u00b7 {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        no, total, label = None, None, period
    window = ""
    if d is not None:
        facts = d / "overview_facts.json"
        if facts.exists():
            try:
                window = json.loads(facts.read_text(encoding="utf-8")).get("coverage_window", "")
            except (OSError, json.JSONDecodeError):
                pass
    totals = (acq or {}).get("totals") or {}
    verified = totals.get("verified") if isinstance(totals.get("verified"), int) else None
    expected = totals.get("expected") if isinstance(totals.get("expected"), int) else None
    copy_state = ((acq or {}).get("copy") or {}).get("state") or "none"
    if acq is not None:
        fetch_ok = (isinstance(verified, int) and isinstance(expected, int)
                    and expected > 0 and verified >= expected)
        merge_ok = copy_state == "merged"
    elif has_input:
        fetch_ok = merge_ok = True          # 历史期次按老路：数据已在（没有取数记录可考）
    else:
        fetch_ok = merge_ok = False
    generated_ok = bool(d is not None and (d / "red_slots.json").exists())
    steps = {"fetch": fetch_ok, "merge": merge_ok, "generate": generated_ok}
    last = next(iter(jobs.list_jobs(limit=30, period=pid)), None)
    return {
        "period": pid, "label": label, "no": no, "total": total,
        "window": window, "palette": config.PALETTE, "steps": steps,
        "acquisition": {"started": acq is not None, "verified": verified,
                        "expected": expected, "copy": copy_state},
        "lastJob": {"id": last["id"], "status": last["status"],
                    "created_at": last.get("created_at")} if last else None,
    }


@app.get("/api/periods/{period}/acquisition")
@admin_route
async def api_period_acquisition(request: Request, period: str):
    """自动取数台状态（只读）。没有取数记录时 started=false——界面显示「还没开始」，不编数据。

    状态由取数流程写入 `out/_acquisition/<期次>.json`（人触发；见 ADR-0004）。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    state = acquisition.load(period)
    if state is None:
        return {"period": period, "started": False}
    return {"period": period, "started": True, **state}

# ------------------------------------------------------------------ 自动取数台 · 写动作（X3）
# 全部由**人按键**触发（R-1）：这里是拉起 `tools/acquire.py` 的**非交互执行口**，
# 进度由取数流程写回 `out/_acquisition/<期次>.json`，前端轮询读取。不做任何数据加工。
def _acq_acquire_py():
    return config.ROOT / "tools" / "acquire.py"


def _acq_op_running(period: str):
    """正在跑的取数任务；超过 1 小时没动静视作已死（放行新任务）。"""
    st = acquisition.load(period) or {}
    op = st.get("op") or {}
    if op.get("state") != "running":
        return None
    try:
        age = time.time() - acquisition.state_path(period).stat().st_mtime
    except OSError:
        age = 0
    return None if age > 3600 else op


def _acq_spawn(period: str, action: str, extra: list | None = None):
    """拉起一个取数任务（detached）——先占位写「正在跑」，再起进程。"""
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    running = _acq_op_running(period)
    if running:
        return JSONResponse({"error": "有一项取数任务还在跑，等它完成再试。",
                             "hint": running.get("note", "")}, status_code=409)
    st = acquisition.load(period) or {}
    st["op"] = {"kind": action if action != "fetch" else "fetch", "state": "running",
                "note": "刚排上队，正在开始", "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    acquisition.write_state(period, st)
    log = config.OUT_DIR / "_acquisition" / f"{period}-{action}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8",
               "PYTHONUNBUFFERED": "1"}
        subprocess.Popen(  # noqa: S603 — 固定脚本路径 + 期次已校验，无注入面
            [str(config.PYTHON), str(_acq_acquire_py()), action, period, *(extra or [])],
            cwd=str(config.ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
    return {"ok": True, "started": True, "log": log.name}


@app.post("/api/periods/{period}/acquisition/start")
@admin_route
async def api_acq_start(request: Request, period: str):
    """开始取数（按 9 组下载；完成后自动建监测表）。"""
    return _acq_spawn(period, "fetch")


@app.post("/api/periods/{period}/acquisition/retry")
@admin_route
async def api_acq_retry(request: Request, period: str):
    """断组重试：只重下指定的组（body: {"group": "esi-papers"}）。"""
    try:
        body = await request.json()
    except Exception:                                                # noqa: BLE001
        body = {}
    group = str((body or {}).get("group", "")).strip()
    return _acq_spawn(period, "fetch", ["--groups", group] if group else [])


@app.post("/api/periods/{period}/acquisition/copy")
@admin_route
async def api_acq_copy(request: Request, period: str):
    """重建本期监测表（核对用副本）；主台账不碰。"""
    return _acq_spawn(period, "copy")


@app.post("/api/periods/{period}/acquisition/merge")
@admin_route
async def api_acq_merge(request: Request, period: str):
    """把已核对副本并入主台账（写前备份 + 写后五查）。"""
    return _acq_spawn(period, "merge")


@app.post("/api/periods/{period}/acquisition/preflight")
@admin_route
async def api_acq_preflight(request: Request, period: str):
    """开始前检查：取数专用浏览器是否开着、两家网站是否已登录。同步跑（几秒）。"""
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    r = subprocess.run(  # noqa: S603 — 同上
        [str(config.PYTHON), str(_acq_acquire_py()), "preflight", period],
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)
    st = acquisition.load(period) or {}
    pf = st.get("preflight") or {}
    return {"ok": r.returncode == 0, "preflight": pf}



@app.get("/api/periods/{period}/artifacts")
@admin_route
async def api_period_artifacts(request: Request, period: str):
    """按期次列运行产物，仅管理员可读。"""
    d = resolve_period_dir(period)
    if d is None:
        if not _period_has_data(period):
            return _period_missing()
        return {"period": period, "artifacts": []}      # 还没出稿：产物为空，如实说
    return {"period": d.name, "artifacts": jobs.collect_period_artifacts(d.name)}


@app.get("/api/periods/{period}/download/{key}")
@admin_route
async def api_period_download(request: Request, period: str, key: str):
    """期次产物下载仅管理员可读。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    return _serve_artifact(out_dir=d, key=key, pack_job=None,
                           resolve=lambda: jobs.resolve_period_artifact(d.name, key))


def _paginate(items, limit, offset):
    """统一分页：?limit=&offset= -> {rows, total, limit, offset, has_more}"""
    total = len(items)
    offset = max(0, offset)
    limit = min(max(1, limit), 500)
    rows = items[offset:offset + limit]
    return {"rows": rows, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + limit < total}


@app.post("/api/periods/{period}/sign")
@admin_route
async def api_period_sign_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    note = str(body.get("note", ""))
    manual_ack = bool(body.get("known", body.get("manual_ack", False)))
    # 闸门加一道「已填未写入」：填了值但还没重出报告时，签的就是一份不含填值的稿。
    # 拦下来让馆员先重出——审核台会在签单前自动做这件事，这里兜直接调接口的手。
    from . import workbench                                    # noqa: PLC0415
    pending = [f for f in workbench.build(d).get("fills_list", []) if f.get("state") == "pending"]
    if pending:
        return JSONResponse(
            {"error": f"还有 {len(pending)} 处填写没有写进报告，先重出再签单",
             "hint": "点「保存并重出报告」把填值写进报告，再签单"},
            status_code=409)
    ok, res = approval.sign(d, current_user(request), collation.build(d), note=note, manual_ack=manual_ack)
    if not ok:
        return JSONResponse({"error": str(res), "hint": "请先解决闸门拒绝的原因"}, status_code=409)
    return {"status": approval.status(d, res), "fingerprint": approval.fingerprint(d)}


@app.get("/api/periods/{period}/forecast-choice")
@admin_route
async def api_forecast_choice_get(request: Request, period: str):
    """读回请求期次的预测模型选择，仅管理员可读。

    ⚠️ 这条是 **GET**（2026-09-24 修）：此前被误挂成 `@app.post`，又注册在下面的
    `api_route(methods=["GET","POST"])` 之前——FastAPI 按注册顺序匹配，POST 会被这条
    抢先接走，导致「保存选择」永远只读回、不落盘。改装饰器前先想一遍注册顺序。"""
    if not _forecast_choice_period_is_safe(period):
        return JSONResponse({"error": "期次格式无效"}, status_code=400)
    entry = forecast_choice.read_entry(
        period, choices_dir=config.FORECAST_CHOICES_DIR, out_dir=config.OUT_DIR)
    return {"period": period, "choice": entry["choice"],
            "by": entry["by"], "at": entry["at"]}


def _forecast_choice_period_is_safe(period):
    """允许 YYYYMM 及带原样后缀的期次名，不让请求值拼出子路径。"""
    return bool(re.fullmatch(r"\d{6}(?:_[\w-]+)?", period or ""))


#: 兼容别名：形状统计的唯一实现在 `forecast_choice.count`（tests 仍从本 module 取用）。
_count_forecast_choice = forecast_choice.count


@app.api_route("/api/periods/{period}/forecast-choice", methods=["GET", "POST"])
@admin_route
async def api_forecast_choice(request: Request, period: str):
    if request.method == "GET":
        return await api_forecast_choice_get(request, period)
    if not _forecast_choice_period_is_safe(period):
        return JSONResponse({"error": "期次格式无效"}, status_code=400)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "请求必须是合法 JSON 对象"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "请求必须是合法 JSON 对象"}, status_code=400)
    choice = body.get("choice")
    if not isinstance(choice, dict):
        return JSONResponse(
            {"error": "choice 必须是 {路线: {学科: 模型名}}",
             "hint": '例：{"citation": {"物理学": "SARIMA模型"}}'}, status_code=400)
    candidate_subjects = (set(forecasting.page_context().get("subjects") or [])
                          if choice else set())
    ok, error = forecast_choice.validate(choice, subjects=candidate_subjects)
    if not ok:
        return JSONResponse({"error": error}, status_code=400)
    forecast_choice.write_entry(period, choice, by=current_user(request), at=forecast_choice.now(),
                                choices_dir=config.FORECAST_CHOICES_DIR)
    n_subjects, n_routes = forecast_choice.count(choice)
    resp = {"ok": True, "saved": n_subjects,
            "path": f"_forecast_choices/{period}.json"}
    if n_routes is not None:
        resp["saved_routes"] = n_routes
    return resp


@app.post("/api/periods/{period}/revoke")
@admin_route
async def api_period_revoke_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    note = str(body.get("note", ""))
    ok, res = approval.revoke(d, current_user(request), note=note)
    if not ok:
        return JSONResponse({"error": str(res), "hint": "请先解决闸门拒绝的原因"}, status_code=409)
    return {"status": approval.status(d, res)}


@app.post("/api/periods/{period}/fill")
@admin_route
async def api_period_fill_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    items = body.get("items") or {}
    if not isinstance(items, dict):
        return JSONResponse({"error": "items 必须是 {todo_id: value}", "hint": "例：{'T01_r9c3': '33.87'}"}, status_code=400)
    from . import workbench                                     # noqa: PLC0415
    n = 0
    for todo_id, value in items.items():
        if str(todo_id).strip():
            workbench.save_fill(d, str(todo_id), str(value), by=current_user(request))
            n += 1
    return {"ok": True, "saved": n}


@app.post("/api/periods/{period}/flag")
@admin_route
async def api_period_flag_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    loc = str(body.get("loc", "")).strip()
    if not loc:
        return JSONResponse({"error": "loc 不能为空", "hint": "例：T01/r9c3"}, status_code=400)
    from . import workbench                                     # noqa: PLC0415
    r = workbench.toggle_flag(d, loc, by=current_user(request))
    return {"ok": True, "loc": r["loc"], "state": r["state"], "n_doubt": r["n_doubt"]}


@app.post("/api/periods/{period}/rebuild")
@admin_route
async def api_period_rebuild_json(request: Request, period: str):
    """填完重出（JSON 版）——与表单版同一套三步。

    ① 先存 body.items 里的填值（可空，用已落盘的）
    ② 旧成品撤到 _superseded/（覆盖前留机器稿，能回滚）
    ③ fill_docx 用已解析宽表重出，不重新解析台账
    转 2-15 秒（重插 96 张图），同步阻塞 —— uvicorn 单 worker 是项目既定约束。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    items = body.get("items") or {}
    if not isinstance(items, dict):
        return JSONResponse({"error": "items 必须是 {todo_id: value}", "hint": "可省略，用已落盘的填值"}, status_code=400)
    import fill_docx                                        # noqa: PLC0415
    import parse_ledger                                     # noqa: PLC0415
    from . import workbench                                 # noqa: PLC0415
    for todo_id, value in items.items():                    # ① 先存
        if str(todo_id).strip():
            workbench.save_fill(d, str(todo_id), str(value), by=current_user(request))
    fills = workbench.load_fills(d)
    if not fills:                                           # ② 没内容就不动产物
        return JSONResponse({"error": "还没有填写内容", "hint": "先在工作台填值再重出"}, status_code=409)
    t0 = time.time()
    parse_ledger.quarantine_final_products(d, None)
    try:
        fill_docx.main(ledger_dir=str(d), manual_inputs=fills)  # ③ 重出
    except Exception as e:                                  # noqa: BLE001
        return JSONResponse({"error": f"重出失败：{type(e).__name__}", "hint": str(e)[:200]}, status_code=500)
    n = sum(1 for v in fills.values() if str(v.get("value") or "").strip())
    docx = next((p.name for p in d.glob("报告初稿_*.docx")), "")
    return {"ok": True, "rebuilt": n, "period": d.name, "docx": docx,
            "elapsed": round(time.time() - t0, 1)}


def _discipline_cn(name):
    """学科英文名 → 中文展示名（契约 #22）；未知名字原样返回（不猜、不丢）。"""
    return display_name(name) if isinstance(name, str) else name


def _localize_facts(facts: dict) -> dict:
    """契约 #22：facts 里展示用的学科名就地换中文。

    只动接口响应——磁盘产物 `overview_facts.json` 保持英文，逐格溯源链不断。
    换的是五处展示位（前端据此删掉自己的名字桥）：
    `best_1permille` / `worst_cn_rank` / `top2_not_entered[].discipline`，以及并列组
    `top3_by_top_papers[][0]`、`top3_groups[][1][]`（名字在固定位置，只能就地换）；
    顺带 `top2_prox_change[][0]`（同类展示位，避免下一个用它的页面再踩英文）。
    """
    for key in ("best_1permille", "worst_cn_rank"):
        item = facts.get(key)
        if isinstance(item, dict) and "discipline" in item:
            item["discipline"] = _discipline_cn(item["discipline"])
    for item in facts.get("top2_not_entered") or []:
        if isinstance(item, dict) and "discipline" in item:
            item["discipline"] = _discipline_cn(item["discipline"])
    for key in ("top3_by_top_papers", "top2_prox_change"):
        rows = facts.get(key)
        if isinstance(rows, list):
            facts[key] = [[_discipline_cn(r[0]), *r[1:]]
                          if isinstance(r, (list, tuple)) and r else r for r in rows]
    groups = facts.get("top3_groups")
    if isinstance(groups, list):
        facts["top3_groups"] = [
            [r[0], [_discipline_cn(d) for d in r[1]]]
            if isinstance(r, (list, tuple)) and len(r) >= 2 and isinstance(r[1], (list, tuple))
            else r
            for r in groups]
    return facts


@app.get("/api/periods/{period}/facts")
@admin_route
async def api_period_facts(request: Request, period: str):
    """读数带数据：overview_facts.json + meta.json 摘要，仅管理员可读。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    facts_file = d / "overview_facts.json"
    meta_file = d / "meta.json"
    if not facts_file.exists():
        return JSONResponse({"error": "该期次尚无 overview_facts.json", "hint": "请先跑一次生成流水线"}, status_code=404)
    try:
        facts = json.loads(facts_file.read_text(encoding="utf-8"))
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": f"数据读取失败：{exc}"}, status_code=500)
    facts = _localize_facts(facts)
    assertions = meta.get("assertions") or []
    n_fail = sum(1 for a in assertions if isinstance(a, (list, tuple)) and a and a[0] != "PASS")
    # 顶尖论文历期序列（纯序列化 meta；空值＝未来期空列，滤掉）——契约 #19
    trend = {k: v for k, v in (meta.get("top_total_by_period") or {}).items()
             if isinstance(v, (int, float))}
    return {
        "period": meta.get("period_current", ""),
        "period_prev": meta.get("period_prev", ""),
        "facts": facts,
        "trend": trend,
        "assertions": {"total": len(assertions), "fail": n_fail},
        "missing": meta.get("missing", []),
    }


@app.get("/api/periods/{period}/workbench")
@admin_route
async def api_period_workbench(request: Request, period: str):
    """工作台全量数据：todo/fills/pending/approval。admin 可读。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    from . import workbench, approval as _appr               # noqa: PLC0415
    rec = _appr.read(d)
    data = workbench.build(d, approval=rec)
    data["approvalStatus"] = _appr.status(d, rec)
    return data


@app.get("/api/periods/{period}/report-preview")
@admin_route
async def api_period_report_preview(request: Request, period: str):
    """审核台用：把这一期的试排报告（docx）拆成可渲染的块 + 在线填空字段。

    只读产物；不重算任何数字。没出稿时 404，让前端给出「去生成」的下一步。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    data = await run_in_threadpool(report_preview.build, d)
    if not data.get("docx"):
        return JSONResponse(
            {"error": "这一期还没有出稿", "hint": "先在生成台生成这一期，再回来审核"},
            status_code=404)
    return data


@app.get("/api/periods/{period}/report-image/{rid}")
@admin_route
async def api_period_report_image(request: Request, period: str, rid: str):
    """报告预览里的插图（按 docx 内部 rId 取，只读、不落盘）。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    hit = await run_in_threadpool(report_preview.image, d, rid)
    if hit is None:
        return JSONResponse({"error": "图片不存在"}, status_code=404)
    blob, ctype = hit
    return Response(content=blob, media_type=ctype,
                    headers={"Cache-Control": "no-cache"})


_TRACE_CATS = ("bigtable", "charts", "province", "matrix", "texts")


def _rel_path(p):
    """绝对路径 -> 仓库相对（跨机器可读；API 不回服务器目录结构）。

    转不了（不在仓库内）就只回文件名。
    """
    try:
        return str(pathlib.Path(p).resolve().relative_to(config.ROOT)).replace("\\", "/")
    except (ValueError, OSError, TypeError):
        return pathlib.Path(str(p)).name


def _sanitize_paths(obj, keys):
    """把 dict 里指定键的路径值换成仓库相对形式（原对象不改）。"""
    if not isinstance(obj, dict):
        return obj
    out = dict(obj)
    for k in keys:
        if out.get(k):
            out[k] = _rel_path(out[k])
    if isinstance(out.get("stats"), dict):          # 嵌套的 stats 里也有 input
        out["stats"] = _sanitize_paths(out["stats"], keys)
    return out


@app.get("/api/periods/{period}/archive")
@admin_route
async def api_period_archive(request: Request, period: str, job: str = ""):
    """期次运行档案 JSON（契约 §2.2 #18）—— 状态机回放 + 瀑布 + 审计 + 日志包清单。

    与档案页同源（`archive.build`）。**自动挂该期最近一次任务**
    （否则 replay 只能是空链、waterfall 无事件）；`?job=<id>` 可指定某次运行。
    安全：**不回服务器绝对路径**；日志包下载走保留的 `/p/{period}/download/logpack`。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    if job:
        target = jobs.read_job(job)
        if target is None:
            return _job_missing()
    else:
        target = next((j for j in jobs.list_jobs(50)
                       if d.name in (j.get("period"), j.get("out_period"))), None)
    q = urllib.parse.quote(d.name)
    view = archive.build(d, job=target, artifacts=jobs.collect_period_artifacts(d.name))
    view.pop("out_dir", None)                                  # 不回绝对路径
    view.pop("progress_path", None)
    # job/stats/run_log 里还有 input/progress/console 等本机路径：转仓库相对
    _path_keys = ("input", "progress", "console", "run_dir", "out_dir")
    view["job"] = _sanitize_paths(view.get("job"), _path_keys)
    view["stats"] = _sanitize_paths(view.get("stats"), _path_keys)
    view["run_log"] = _sanitize_paths(view.get("run_log"), _path_keys)
    view["download_base"] = f"/p/{q}"
    view["logpack_url"] = f"/p/{q}/download/{view['logpack']['key']}"
    return view


@app.get("/api/periods/{period}/trace")
@admin_route
async def api_period_trace(request: Request, period: str, cat: str = "bigtable",
                           limit: int = 60, offset: int = 0):
    """逐格溯源 JSON。现场真读台账（与老站同源）。

    cat 选类别：bigtable/charts/province/matrix/texts；
    limit/offset 分页（大件不一次性塞满，契约 §3）。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    if cat not in _TRACE_CATS:
        cat = "bigtable"
    ledger = _find_ledger(d)
    if ledger is None:
        empty = {k: 0 for k in _TRACE_CATS}
        return {"period": d.name, "ledger": "", "ledger_ok": False,
                "ledger_error": "本地未找到台账 input/<期次>/监测表.xlsx",
                "n": 0, "cat": cat, "counts": empty,
                "rows": [], "total": 0, "limit": limit, "offset": offset,
                "has_more": False, "cols": [], "discs": [], "review": {}}
    from . import workbench                                  # noqa: PLC0415
    data = workbench.trace(d, ledger, prev=None)
    counts = {k: len(data.get(k) or []) for k in _TRACE_CATS}
    page = _paginate(data.get(cat) or [], limit, offset)
    return {
        "period": d.name,
        "ledger": pathlib.Path(ledger).name,
        "ledger_ok": True,
        "n": data.get("n", 0),
        "cat": cat,
        "counts": counts,
        "rows": page["rows"],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
        "has_more": page["has_more"],
        "cols": data.get("cols", []),
        "discs": data.get("discs", []),
        "review": workbench.load_review(d),
    }


@app.get("/api/periods/{period}/redslots")
@admin_route
async def api_period_redslots(request: Request, period: str,
                              limit: int = 50, offset: int = 0):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    raw = []
    rp = d / "red_slots.json"
    if rp.exists():
        try:
            raw = json.loads(rp.read_text(encoding="utf-8")) or []
        except (OSError, json.JSONDecodeError):
            raw = []
    rows = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        loc = str(s.get("location", ""))
        new_p = str(s.get("new", ""))
        src = str(s.get("source", ""))
        group = loc.split("/")[0] if "/" in loc else loc
        if loc.startswith("T01/r"):
            group = "大表数值"
        elif loc.startswith("T0") or loc.startswith("T1"):
            group = loc.split("/")[0]
        kind = "chart" if (new_p.startswith("[图]") or ("图" in loc and loc.startswith("综述/"))) else (
            "cell" if loc.startswith("T") and "/" in loc else "text")
        rows.append({"group": group, "label": loc,
                     "old": str(s.get("old_full") or s.get("old", "")),
                     "new": str(s.get("new_full") or new_p),
                     "src": src, "kind": kind})
    page = _paginate(rows, limit, offset)
    page["count"] = page["total"]
    return page


@app.get("/api/periods/{period}/collation")
@admin_route
async def api_period_collation(request: Request, period: str,
                               limit: int = 50, offset: int = 0,
                               full: bool = False):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    data = collation.build(d)
    sections = [{"id": s["id"], "name": s["name"], "note": s.get("note", ""),
                 "count": s.get("count", 0), "text": s.get("text", 0),
                 "cell": s.get("cell", 0), "chart": s.get("chart", 0),
                 "manual": s.get("manual", 0),
                 "slots": s.get("slots", [])}
                for s in data.get("sections", [])]
    all_slots = []
    for s in data.get("sections", []):
        for it in s.get("slots", []):
            all_slots.append({"section": s["id"], **it})
    if full:
        return {"sections": sections, "rows": all_slots,
                "total": len(all_slots), "period": data.get("period", ""),
                "assertions": data.get("assertions", {})}
    page = _paginate(all_slots, limit, offset)
    page["sections"] = [{k: v for k, v in s.items() if k != "slots"} for s in sections]
    page["period"] = data.get("period", "")
    page["assertions"] = data.get("assertions", {})
    return page


@app.get("/api/periods/{period}/charts")
@admin_route
async def api_period_charts_json(request: Request, period: str,
                                 limit: int = 50, offset: int = 0):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    q = urllib.parse.quote(d.name)
    items = []
    for it in jobs.list_charts(d):
        items.append({"name": it["name"], "group": it["group"],
                      "url": f"/p/{q}/chart/" + urllib.parse.quote(it["rel"])})
    return _paginate(items, limit, offset)


@app.get("/api/ledger/sheets")
@admin_route
async def api_ledger_sheets(request: Request, period: str = ""):
    import openpyxl                                        # noqa: PLC0415
    m = jobs.PERIOD_RE.match(period or "")
    if m:
        lp = config.INPUT_DIR / m.group(0) / "监测表.xlsx"
    else:
        lp = None
        for d in sorted(config.INPUT_DIR.glob("*/监测表.xlsx"), reverse=True):
            lp = d
            break
    if lp is None or not lp.exists():
        return JSONResponse({"error": "台账文件不存在", "hint": "请先在控制台上传监测表.xlsx"}, status_code=404)
    try:
        wb = openpyxl.load_workbook(str(lp), read_only=True, data_only=True)
    except Exception as exc:                               # noqa: BLE001
        return JSONResponse({"error": f"台账读取失败：{exc}"}, status_code=500)
    sheets = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(max_row=2, values_only=True)
        header = next(rows, ()) or ()
        cols = [str(c).strip() if c is not None else "" for c in header]
        periods = [c for c in cols[1:] if c and c[0].isdigit() and len(c) == 6]
        sheets.append({
            "name": ws.title,
            "columns": cols[:20],
            "n_columns": len(cols),
            "periods": periods[:30],
            "n_periods": len(periods),
        })
    wb.close()
    return {"file": lp.name, "sheets": sheets, "n_sheets": len(sheets)}


def _answer_response(ans):
    """Answer → HTTP（#9/#27 共用）：无数据 404、权限 403、关闭 409、其余原样 JSON。"""
    if ans.mode == "unavailable":
        return JSONResponse({"error": ans.notice,
                             "hint": "请先跑一次生成流水线"}, status_code=404)
    if ans.mode == "denied":
        return JSONResponse({"error": ans.notice}, status_code=403)
    if ans.mode == "closed":
        return JSONResponse({"error": ans.notice}, status_code=409)
    return ans.as_dict()


@app.post("/api/analyze")
@admin_route
async def api_analyze(request: Request):
    """问文衡（qa 能力）**薄适配**（SPEC §4 步骤 2）：调用方只认 Answer 字段面，
    不知道盾、回落、工具、留痕、开关任何一件。

    请求 `{period, question}`（旧版 `scope` 遗留字段被忽略——问句匹配在模块内）；
    响应＝`Answer.as_dict()`（`mode/backend/text/rule_text/notice/sources/shield/record_id`）。
    该期无产物 → 404（前端按「尚未出稿」处理）；能力被管理员关闭 → 409。
    """
    body = await request.json()
    period = str(body.get("period", "")).strip()
    question = str(body.get("question", "")).strip()
    d = resolve_period_dir(period) if period else None
    if d is None:
        return _period_missing()
    import ai                                                     # noqa: PLC0415
    ans = await run_in_threadpool(ai.run, "qa", period,
                                  payload={"question": question},
                                  actor=config.role_of(current_user(request) or ""))
    return _answer_response(ans)


@app.post("/api/periods/{period}/review-advice")
@admin_route
async def api_period_review_advice(request: Request, period: str):
    """复核参谋（review 能力；契约 #27）**薄适配**：调用方只认 Answer 字段面。

    只读红件清单/校验结果给核对建议（来源＝红件条目或校验记录）；
    **不代签、不改稿**——采纳/忽略只是界面指引，由前端自己存。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    import ai                                                     # noqa: PLC0415
    ans = await run_in_threadpool(ai.run, "review", period,
                                  actor=config.role_of(current_user(request) or ""))
    return _answer_response(ans)


@app.get("/api/ai/capabilities")
@admin_route
async def api_ai_capabilities(request: Request):
    """能力开关表（契约 #28）：分析台「问文衡」的开关读它；纯读配置，无副作用。"""
    import ai                                                     # noqa: PLC0415
    rows = [c.as_dict() for c in
            ai.capabilities(config.role_of(current_user(request) or ""))]
    return {"capabilities": rows}


@app.get("/api/periods/{period}/ai-calls")
@admin_route
async def api_period_ai_calls(request: Request, period: str, limit: int = 100):
    """问答与模型调用记录（契约 #30；票 06 块）：只读 `out/<期次>/ai_calls.jsonl`。

    记录面照留痕纪律：只返回摘要（问题占位面、模式、后端、回落原因、盾计数、
    工具条数、耗时），**不返回回答正文与提示词**；坏行跳过，不猜。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    path = d / "ai_calls.jsonl"
    calls = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") != "call":
                continue
            calls.append({
                "record_id": r.get("record_id") or "",
                "ts": r.get("ts") or "",
                "capability": r.get("capability") or "",
                "mode": r.get("mode") or "",
                "backend": r.get("backend") or "",
                "fallback": r.get("fallback"),
                "shield": r.get("shield") or {"checked": 0, "passed": 0},
                "n_tools": len(r.get("tools") or []),
                "question": r.get("question") or "",
                "elapsed_ms": int(r.get("elapsed_ms") or 0),
            })
    limit = max(1, min(int(limit or 100), 500))
    calls = calls[-limit:][::-1]                                  # 新 → 旧
    n_fb = sum(1 for c in calls if c["fallback"])
    stats = {
        "n": len(calls),
        "model": sum(1 for c in calls if c["mode"] == "model"),
        "fallback": n_fb,
        "avg_sec": round(sum(c["elapsed_ms"] for c in calls) / len(calls) / 1000, 1) if calls else 0,
        "last_ts": calls[0]["ts"] if calls else "",
    }
    return {"period": period, "calls": calls, "stats": stats}


@app.post("/api/ai/switch")
@admin_route
async def api_ai_switch(request: Request):
    """能力开关唯一写口（契约 #29）：管理员一键关闭「问文衡」；数字与报告不受影响。"""
    body = await request.json()
    capability = str(body.get("capability") or "").strip()
    enabled = bool(body.get("enabled"))
    import ai                                                     # noqa: PLC0415
    try:
        await run_in_threadpool(ai.set_switch, capability, enabled,
                                actor=config.role_of(current_user(request) or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except PermissionError as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    return {"ok": True, "capability": capability, "enabled": enabled}


@app.get("/api/forecast/board")
@admin_route
async def api_forecast_board(request: Request, period: str = ""):
    """预测台「学科板」（契约 #20）—— 解析预测选模与过线.md 的两张表。

    不重算；缺文件时返回空板 + note（不 500）。`?period=` 可指定，
    默认取最新有该文件的期次。
    """
    if period and resolve_period_dir(period) is None:
        return _period_missing()
    return forecasting.board_context(period or None)


@app.get("/api/periods/{period}/flexible")
@admin_route
async def api_period_flexible(request: Request, period: str, intent: str = ""):
    """灵活报告 JSON（契约 #21①）：列已生成 + 当前稿的 body_html。

    body_html 用**后端同一个 mdview.render**（图已指向
    `/p/<期次>/flexible/chart/<intent>/<name>`）——前端不引 md 渲染器。
    未生成过的期次返回空列表 + cur=null + body_html=""，不 500。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    ctx = _flex_ctx(d, intent or None)
    return {
        "period": ctx["period_dir"],
        "intents": ctx["intents"],
        "reports": [{"intent": r["intent"], "title": r["title"], "meta": r["meta"]}
                    for r in ctx["reports"]],
        "cur": (ctx["cur"] or {}).get("intent") or None,
        "body_html": ctx["body"] or "",
    }


@app.post("/api/periods/{period}/flexible")
@admin_route
async def api_period_flexible_generate(request: Request, period: str):
    """生成一份灵活报告（契约 #21②）—— 同步几秒。

    只写 `out/<期次>/flexible/`（产物目录），台账一字节不碰。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    intent = str(body.get("intent") or "").strip()
    disc = str(body.get("disc") or "").strip() or None
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}",
                             "hint": "可选：" + "、".join(flex_planner.INTENTS)}, status_code=400)
    import flexible.report as flex_report                           # noqa: PLC0415
    t0 = time.time()
    try:
        r = flex_report.generate(d, intent, disc=disc)
    except Exception as e:                                          # noqa: BLE001
        return JSONResponse({"error": f"生成失败：{type(e).__name__}", "hint": str(e)[:200]}, status_code=500)
    return {"ok": True, "intent": intent, "elapsed": round(time.time() - t0, 1),
            "n_charts": r.get("n_charts"), "backend": (r.get("plan") or {}).get("backend", "")}


@app.get("/api/forecast/meta")
@admin_route
async def api_forecast_meta(request: Request):
    return forecasting.page_context()


@app.post("/api/forecast/run")
@admin_route
async def api_forecast_run(request: Request):
    try:
        payload = await request.json()
        # 五模型滚动回测属于 CPU 密集型同步计算，放进线程池，避免卡住
        # 同一进程里的页面、探活和任务进度请求。
        return await run_in_threadpool(forecasting.run, payload)
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # 模型收敛或数据错误必须显式显示，不能返回半份结果
        return JSONResponse({"error": f"预测运行失败：{exc}"}, status_code=500)


@app.post("/api/jobs")
@admin_route
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
            return JSONResponse({"error": "仅支持 .xlsx 台账文件"}, status_code=400)
        if not jobs.PERIOD_RE.match(period):
            return JSONResponse({"error": "请填写 6 位期次（如 202609），文件名统一存为监测表.xlsx"}, status_code=400)
        data = await file.read()
        if len(data) > 50 * 1024 * 1024:
            return JSONResponse({"error": "文件超过 50MB"}, status_code=400)
        dest = config.INPUT_DIR / period / "监测表.xlsx"
        # file.read() 会让出事件循环；恢复后必须再次确认，才能碰已有输入文件。
        busy = jobs.active_job()
        if busy:
            return JSONResponse({"error": f"已有任务运行中（{busy['period']}），请稍候"}, status_code=409)
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
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"job_id": job["id"], "url": f"/jobs/{job['id']}"}


@app.get("/api/jobs/{job_id}")
@admin_route
async def api_job(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    # 契约 §2.3：失败态给结构化的「缺什么」，不让前端解析断言文本
    if job.get("missing"):
        job["ok"] = False
    return job


@app.get("/api/jobs/{job_id}/artifacts")
@admin_route
async def api_artifacts(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    return {"job": job, "artifacts": jobs.collect_artifacts(job)}


@app.get("/api/jobs/{job_id}/download/{key}")
@admin_route
async def api_job_download(request: Request, job_id: str, key: str):
    """任务产物与日志包只属于管理员运行工作区。"""
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _serve_artifact(out_dir=out_dir, key=key, pack_job=job,
                           resolve=lambda: jobs.resolve_artifact(job, key))


@app.post("/api/jobs/{job_id}/rerun")
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


# ---------------- 回滚到上一版（票 07） ----------------

def _rollback_dir(period: str):
    """回滚只认两件事：期次名合法 + 期次目录里有 _superseded/。

    与 resolve_period_dir 不同：**允许当前没有成品**——重跑失败之后回来回滚，正是主场景。
    """
    if not jobs.PERIOD_DIR_RE.match(period or ""):
        return None
    d = config.OUT_DIR / period
    if d.is_dir() and (d / parse_ledger.SUPERSEDED_DIR).is_dir():
        return d
    return None


def _rollback_points(out_dir: pathlib.Path):
    """列回滚点（新→旧）：只列真带成品的留档目录（下划线开头的是标记文件）。"""
    sup = out_dir / parse_ledger.SUPERSEDED_DIR
    points = []
    for d in sorted((p for p in sup.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        files = sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.startswith("_"))
        if files:
            points.append({"id": d.name, "files": files})
    return points


@app.get("/api/periods/{period}/rollback-points")
@admin_route
async def api_rollback_points(request: Request, period: str):
    out_dir = _rollback_dir(period)
    if not out_dir:
        if not _period_has_data(period):
            return JSONResponse({"error": "这一期没有可回滚的留档"}, status_code=404)
        return {"period": period, "points": []}         # 还没出稿：没有留档可回滚
    return {"period": period, "points": _rollback_points(out_dir)}


@app.post("/api/periods/{period}/rollback")
@admin_route
async def api_rollback(request: Request, period: str):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    point = str((body or {}).get("point") or "")
    out_dir = _rollback_dir(period)
    if not out_dir:
        return JSONResponse({"error": "这一期没有可回滚的留档"}, status_code=404)
    busy = jobs.active_job()
    if busy:
        return JSONResponse({"error": f"已有任务运行中（{busy['period']}），回滚会跟它打架，请稍候"},
                            status_code=409)
    points = _rollback_points(out_dir)
    if not points:
        return JSONResponse({"error": "没有可回滚的版本（每次重跑/重出都会把旧版留档）"}, status_code=404)
    target = next((p for p in points if p["id"] == point), None) if point else points[0]
    if not target:
        return JSONResponse({"error": "指定的回滚点不存在"}, status_code=404)
    src = out_dir / parse_ledger.SUPERSEDED_DIR / target["id"]
    # 先把当前成品撤进新的留档目录——让「回滚」本身也能再回滚
    quarantined = parse_ledger.quarantine_final_products(out_dir)
    restored = []
    for name in target["files"]:
        p = src / name
        if p.is_file():
            p.replace(out_dir / name)
            restored.append(name)
    try:
        (src / "_已回滚.txt").write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}：这一版成品已回滚到 {period} 期目录；"
            f"回滚前的成品另存了新留档目录。\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return {"ok": True, "period": period, "point": target["id"],
            "restored": restored, "pre_rollback_quarantined": quarantined}


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


@app.get("/api/jobs/{job_id}/events")
@admin_route
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


# ---------------- 下载 / 二维码 ----------------

@app.get("/jobs/{job_id}/download/{key}")
@admin_file_route
async def download(request: Request, job_id: str, key: str):
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _serve_artifact(out_dir=out_dir, key=key, pack_job=job,
                           resolve=lambda: jobs.resolve_artifact(job, key))


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
