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
import time
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import approval, archive, collation, config, jobs
from . import forecasting
from src import period as period_mod  # 期次口径唯一来源（ADR-0001：新工作区 API 也用它）


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()
    yield


app = FastAPI(title="文衡 · 学科信息参考自动化演示", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET, same_site="lax")
app.mount("/static", StaticFiles(directory=str(config.SERVER_DIR / "static")), name="static")
# 新工作区系统（React SPA，构建产物 web/dist 入库）——见 docs/adr/0001。
# check_dir=False：干净 clone 里 dist 缺失时不要拖垮整个服务启动，让它 404 就行。
app.mount("/app", StaticFiles(directory=str(config.ROOT / "web" / "dist"), html=True,
                              check_dir=False), name="web")
templates = Jinja2Templates(directory=str(config.SERVER_DIR / "templates"))


# ---- 静态资源不能被浏览器自作主张缓存（2026-09-17）----------------------------
# 踩过的坑：改完 collation.js/collation.css 重启服务、curl 也验过服务器发的是新文件，
# 但页面上就是没变化。原因是 StaticFiles **只发 etag/last-modified、不发 Cache-Control**，
# 浏览器于是套用「启发式新鲜度」（约等于距上次修改时间的 10%）—— 旧 JS 在本地缓存里
# 能活好几个小时，**期间根本不回服务器问**。表现出来就是「功能好像没做」。
# 双保险：① 模板里的 URL 带 `?v=<指纹>`，资源一变 URL 就变，缓存必然失效；
# ② 静态响应一律 no-cache，即便有人手写了个不带版本的地址，也必须回源校验。
@app.middleware("http")
async def _static_revalidate(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith(("/static/", "/app/")):
        resp.headers["Cache-Control"] = "no-cache"
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


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise PermissionError
    return user


def require_admin(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if config.role_of(user) != "admin":
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
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
    # 图表槽位就地铺图：`source` 是 `charts/<学科>/<图>.png`。能在磁盘上解析出真图才给地址
    # （与红件清单页同一套 `resolve_chart` 守卫——安全不能只在图册页好用、在对勘本漏掉）。
    # 解析不出就留空，前端退回纯文件名，绝不显示一个坏图。
    n_pic = 0
    for sec in data.get("sections") or []:
        for it in sec.get("slots") or []:
            if it.get("kind") != "chart":
                continue
            src = str(it.get("source") or "")
            if src.startswith("charts/"):
                rel = src[len("charts/"):]
                if jobs.resolve_chart(out_dir, rel):
                    it["chartUrl"] = f"/p/{q}/chart/" + urllib.parse.quote(rel)
                    n_pic += 1
    data["chartPics"] = n_pic
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
        crumbs.append({"label": "运行档案", "href": f"/jobs/{job['id']}/archive", "download": False})
        crumbs.append({"label": "图表图册", "href": f"/jobs/{job['id']}/charts", "download": False})
        crumbs.append({"label": "红色件清单", "href": f"/jobs/{job['id']}/redslots", "download": False})
        crumbs.append({"label": "下载报告初稿", "href": f"/jobs/{job['id']}/download/report", "download": True})
    else:
        crumbs.append({"label": "发起任务 / 历史任务", "href": "/run", "download": False})
        crumbs.append({"label": "运行档案", "href": f"/p/{q}/archive", "download": False})
        crumbs.append({"label": "图表图册", "href": f"/p/{q}/charts", "download": False})
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
    # 图槽位：`source` 是 `charts/<学科>/<图名>.png`。能解析出真实文件才给预览地址——
    # 解析失败（文件缺失 / 路径越界）就不给，前端退回纯文本，绝不显示一个坏图。
    for s in slots:
        src = s.get("source") or ""
        if isinstance(src, str) and src.startswith("charts/"):
            rel = src[len("charts/"):]
            if jobs.resolve_chart(out_dir, rel):
                s["chart_url"] = f"/p/{q}/chart/" + urllib.parse.quote(rel)
    if job:
        back_url = f"/jobs/{job['id']}/collation"
        download_url = f"/jobs/{job['id']}/download/red_list"
    else:
        back_url = f"/p/{q}"
        download_url = f"/p/{q}/download/red_list"
    # 图册入口：清单页里 99 张图夹在 240 条表数值后面、位置字段还写着「正文」，
    # 不另给入口就没人找得到。这里与搜索框并列摆一个直达按钮。
    charts_url = f"/jobs/{job['id']}/charts" if job else f"/p/{q}/charts"
    return page(request, "redslots.html", job=job or {}, period=out_dir.name,
                slots=slots, groups=sorted(stats.items(), key=lambda kv: -kv[1]),
                backUrl=back_url, downloadUrl=download_url, chartsUrl=charts_url)


def _charts_page(request, out_dir, job=None):
    """图表图册：把 charts/ 下的期次图平铺展示，打开就能看全。

    与红件清单页的分工：清单页是「逐条审计」（354 条，图只占 99 条，夹在表数值后面，
    得先筛），图册页是「一眼看全」（99 张图按学科分组平铺）。两个入口都给。
    """
    q = urllib.parse.quote(out_dir.name)
    groups = {}
    for it in jobs.list_charts(out_dir):
        it["url"] = f"/p/{q}/chart/" + urllib.parse.quote(it["rel"])
        groups.setdefault(it["group"], []).append(it)
    view = {
        "period": out_dir.name,
        "job": job or {},
        "total": sum(len(v) for v in groups.values()),
        "groups": sorted(groups.items()),
        "backUrl": f"/jobs/{job['id']}/collation" if job else f"/p/{q}",
        "redUrl": f"/jobs/{job['id']}/redslots" if job else f"/p/{q}/redslots",
    }
    return page(request, "charts.html", **view)


def _archive_page(request, out_dir, job=None):
    """运行档案页（SRS R-21）：状态机回放 + 任务瀑布 + 产物 + 日志包下载。

    期次入口与任务入口共用，差别只有三处：下载链接指哪儿、面包屑、
    以及有没有 job 上下文（控制台输出与状态链都挂在任务上）。
    """
    q = urllib.parse.quote(out_dir.name)
    if job:
        base, crumbs = f"/jobs/{job['id']}", [
            {"label": f"← 返回任务 {job['id']}", "href": f"/jobs/{job['id']}", "download": False},
            {"label": "对勘本", "href": f"/jobs/{job['id']}/collation", "download": False},
            {"label": "图表图册", "href": f"/jobs/{job['id']}/charts", "download": False},
            {"label": "红色件清单", "href": f"/jobs/{job['id']}/redslots", "download": False},
        ]
        artifacts = jobs.collect_artifacts(job)
    else:
        base, crumbs = f"/p/{q}", [
            {"label": "发起任务 / 历史任务", "href": "/run", "download": False},
            {"label": f"{out_dir.name} 期对勘本", "href": f"/p/{q}", "download": False},
            {"label": "图表图册", "href": f"/p/{q}/charts", "download": False},
            {"label": "红色件清单", "href": f"/p/{q}/redslots", "download": False},
        ]
        artifacts = jobs.collect_period_artifacts(out_dir.name)
    view = archive.build(out_dir, job=job, artifacts=artifacts)
    # 用 update 而不是 `page(..., **view, period=…)`：view 自带 period/job，
    # 关键字重复传会直接 TypeError——这类错只在打开页面时才现形。
    view.update({"job": job or {}, "download_base": base, "crumbs": crumbs})
    return page(request, "archive.html", **view)


def _zip_response(data: bytes, filename: str):
    """日志包下载。文件名是 ASCII（中文名在部分浏览器会乱码），说明写在包内 README。"""
    return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


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
async def home(request: Request, err: str = "", signed: str = "",
               revoked: str = "", rebuilt: str = "", saved: str = "", p: str = ""):
    """**首屏 = 馆员工作台**（最新一期，可用 `?p=<期次>` 切换）。没有可对勘的期次时才退回控制台。

    2026-09-19 从「首屏=对勘本」改过来。对勘本回答的是"这份报告怎么拼出来的"
    （生产视角），而打开这个站的人要的是"这次要我做什么决定"（馆员视角）。
    对勘本 / 图册 / 档案页都还在，收进工作台底部的「审计视图」入口。

    ⚠ 期次原先写死取最新一期（rick：「为什么标题栏 202607 常驻」）——
    现在按 `?p=` 切换，切换器渲染在标题栏右侧。
    """
    from . import workbench                                     # noqa: PLC0415
    cards = period_cards()
    if cards:
        want = p or cards[0]["period"]
        d = resolve_period_dir(want) or resolve_period_dir(cards[0]["period"])
        if d is not None:
            return page(request, "workbench.html",
                        **workbench.build(d),
                        periods=cards, current=d.name, rebuilt=rebuilt, saved=saved,
                        flash=_flash(err, signed, revoked))
    return page(request, "index.html", **_run_ctx())


@app.get("/run", response_class=HTMLResponse)
async def run_page(request: Request):
    """控制台：选期次 / 上传台账 / 一键生成 + 最近任务。"""
    return page(request, "index.html", **_run_ctx())


@app.get("/forecast", response_class=HTMLResponse)
async def forecast_page(request: Request):
    """V1双路线预测工作台；只读派生数据，不修改台账或既有报告。"""
    return page(request, "forecast.html", **forecasting.page_context())


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


@app.get("/p/{period}/trace", response_class=HTMLResponse)
async def period_trace(request: Request, period: str):
    """逐格溯源（354 那个数字的落点）。

    **现场真读台账**（`workbench.trace` → `parse_ledger.load_ledger`），
    不拿宽表 parquet 自证 —— 同源自证差异恒为 0，看起来严谨实际什么都没验。
    加载 7MB 台账约 2–4 秒，换来的是"每个数字当场对给你看"。
    """
    from . import workbench                                     # noqa: PLC0415
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    ledger = _find_ledger(d)
    data = workbench.trace(d, ledger, prev=None) if ledger else {
        "bigtable": [], "charts": [], "texts": [], "n": 0,
        "ledger": "（本地未找到台账 input/<期次>/监测表.xlsx）"}
    review = workbench.load_review(d)
    return page(request, "trace.html", period_dir=d.name, **data,
                review=review, audit_base=f"/p/{urllib.parse.quote(d.name)}")


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


async def _collect_fills(request):
    """把表单里的填写项收成一个 dict。

    两种形状都认：
      · `v:<todo_id>=<值>` —— 工作台的**批量表单**（一次提交全部，取代逐条刷新）
      · `id=<todo_id>&value=<值>` —— 单条，旧形状，e2e 与外部调用还在用
    返回 `(items, back)`。
    """
    form = await request.form()
    items = {k[2:]: str(v) for k, v in form.items() if k.startswith("v:")}
    if form.get("id"):
        items[str(form["id"])] = str(form.get("value") or "")
    return items, str(form.get("back") or "")


@app.post("/p/{period}/fill")
async def period_fill(request: Request, period: str):
    """在线填【手工：】项。**只写产物目录的 manual_inputs.json，台账一个字节不碰**
    —— 填的是报告，不是数据源；这正是"可溯源"与"可修改"的边界。

    走**真实表单 POST + 303 回跳**，不用 AJAX —— 栈契约（test_stack_contract）
    要求状态变更不依赖 JS 跑通，填写/存疑也是状态变更，同样适用。
    """
    from . import workbench                                     # noqa: PLC0415
    user = current_user(request)                                # 登录保护，同 _do_sign
    items, back = await _collect_fills(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse(back or "/", status_code=303)
    n = 0
    for todo_id, value in items.items():
        if todo_id.strip():
            workbench.save_fill(d, todo_id, value, by=user)
            n += 1
    return RedirectResponse(_flash_back(back or "/", f"saved={n}"), status_code=303)


@app.post("/p/{period}/flag")
async def period_flag(request: Request, period: str, loc: str = Form(""), back: str = Form("")):
    """大表格子**只能存疑，不能改**（数字来自台账，改了就破溯源）。
    存疑是记一笔"这格我不认"，签单闸门会看到它。同样走表单 POST + 303。"""
    from . import workbench                                     # noqa: PLC0415
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None or not loc.strip():
        return RedirectResponse(back or "/", status_code=303)
    workbench.toggle_flag(d, loc, by=user)
    return RedirectResponse(back or "/", status_code=303)


def _flash_back(back, qs):
    """把提示参数拼进回跳 URL 的**问号位置**。

    🔴 不能写成 `back + "?err=…"`：back 常带锚点（`/#todo-panel`），
    拼完是 `/#todo-panel?err=…` —— query 在 fragment 后面，浏览器**整段忽略**，
    于是"保存失败"这类提示永远不会出现，页面看着像没反应（2026-09-20 实测）。
    正确形状：`/?err=…#todo-panel`。
    """
    base, _, frag = (back or "/").partition("#")
    if not base:
        base = "/"
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{qs}" + (f"#{frag}" if frag else "")


@app.post("/p/{period}/rebuild")
async def period_rebuild(request: Request, period: str):
    """填完重出报告：把在线填的值叠加到报告初稿上。

    三件事按这个顺序做，不能乱：
      1. **先把表单里的填写项存下来** —— 工作台把「保存」和「重出」放在同一个表单里，
         用户点「填完重出」时那些改动还没落盘，不先存就等于白填（2026-09-20 发现）；
      2. **再把旧成品撤到 `_superseded/`**（复用 `parse_ledger.quarantine_final_products`）
         —— 覆盖前留一份机器稿，出了问题能回滚；
      3. `fill_docx.main(..., manual_inputs=…)` 用**已解析的宽表**重出，
         不重新解析台账（重解析会把填值对应不上的风险引进来）。

    耗时约 2–15 秒（要重新插 96 张图），同步阻塞 —— uvicorn 单 worker 是
    项目既定约束（SSE + 内存态任务队列），演示时点一次等一下即可。
    """
    import parse_ledger                                         # noqa: PLC0415
    import fill_docx                                            # noqa: PLC0415
    from . import workbench                                     # noqa: PLC0415
    user = current_user(request)
    items, back = await _collect_fills(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    for todo_id, value in items.items():                        # ① 先存
        if todo_id.strip():
            workbench.save_fill(d, todo_id, value, by=user)
    fills = workbench.load_fills(d)
    if not fills:                                               # ② 没内容就不动产物
        return RedirectResponse(_flash_back(back, "err=还没有填写内容"), status_code=303)
    parse_ledger.quarantine_final_products(d, None)
    try:
        fill_docx.main(ledger_dir=str(d), manual_inputs=fills)  # ③ 重出
    except Exception as e:                                      # noqa: BLE001
        return RedirectResponse(
            _flash_back(back, f"err=重出失败：{type(e).__name__}"), status_code=303)
    n = sum(1 for v in fills.values() if str(v.get("value") or "").strip())
    return RedirectResponse(_flash_back(back, f"rebuilt={n}"), status_code=303)


@app.get("/p/{period}/charts", response_class=HTMLResponse)
async def period_charts(request: Request, period: str):
    """图表图册：99 张期次图按学科平铺，打开即看全（不用在清单页里筛）。"""
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    return _charts_page(request, d)


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
    """灵活报告：列出该期次已生成的分析稿，并内联展示最新一份。"""
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    # `ok` 是生成成功的回执（非错误），单独放一格，不复用 err
    flash = {**_flash(err=err), "ok": ok} if (err or ok) else None
    return page(request, "flexible.html", **_flex_ctx(d, intent or None, flash),
                active_period=d.name)


@app.post("/p/{period}/flexible")
async def period_flexible_generate(request: Request, period: str):
    """生成一份灵活报告。

    登记进 `POST_ALLOWED_SUFFIX` 时回答的三问（`tests/test_stack_contract.py`）：
      ① 真实表单 POST + 303 回跳（不依赖 JS）；
      ② 有登录校验（未登录 → /login）；
      ③ **写 `out/<期次>/flexible/`（产物目录），台账一个字节不碰**。
    """
    import flexible.report as flex_report                           # noqa: PLC0415
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    intent = str(form.get("intent") or "single_trend")
    backend = str(form.get("backend") or "") or None
    disc = str(form.get("disc") or "") or None
    back = f"/p/{urllib.parse.quote(d.name)}/flexible"
    try:
        r = flex_report.generate(d, intent, backend=backend, disc=disc)
    except Exception as e:                                          # noqa: BLE001
        return RedirectResponse(
            f"{back}?err={urllib.parse.quote('生成失败：' + type(e).__name__)}",
            status_code=303)
    c = r["check"]
    msg = (f"已生成：{r['plan']['backend']} 后端，{r['n_charts']} 张图，"
           f"数字可回溯 {c['trace']['ok']}/{c['trace']['checked']}")
    # 🔴 锚点拼在 query **之后**（`?ok=…#flex-report`）—— query 拼到锚点后面
    #    会被浏览器整段忽略（本仓库在这条上踩过两次，见 tests）。
    return RedirectResponse(
        f"{back}?ok={urllib.parse.quote(msg)}#flex-report", status_code=303)


@app.get("/p/{period}/flexible/chart/{intent}/{name}")
async def period_flexible_chart(request: Request, period: str,
                                intent: str, name: str):
    """灵活报告的图。**与复刻图分开解析** —— 归到 `flexible/<intent>/charts/` 下。"""
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    p = jobs.resolve_flex_chart(d, intent, name)
    if p is None:
        raise HTTPException(status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/p/{period}/archive", response_class=HTMLResponse)
async def period_archive(request: Request, period: str):
    """期次运行档案（无需任务上下文也能回放）。"""
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    return _archive_page(request, d)


@app.get("/p/{period}/chart/{rel:path}")
async def period_chart(request: Request, period: str, rel: str):
    """图表原图（只读）。`rel` 是 `red_slots.json` 里 `source` 去掉 `charts/` 的部分。

    越界请求由 `jobs.resolve_chart` 挡住——这条路由直接服务磁盘文件，
    少一道检查就能读到 `server/.env`，别在这里省事。
    """
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    p = jobs.resolve_chart(d, rel)
    if not p:
        return JSONResponse({"error": "图表不存在"}, status_code=404)
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


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
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    if key == archive.LOGPACK_KEY:
        data, name = archive.pack(d, None)
        return _zip_response(data, name)
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
                artifacts=jobs.collect_artifacts(job), terminal=jobs.is_terminal(job["status"]))


@app.get("/jobs/{job_id}/redslots", response_class=HTMLResponse)
async def redslots_page(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _redslots_page(request, out_dir, job=job)


@app.get("/jobs/{job_id}/charts", response_class=HTMLResponse)
async def charts_page(request: Request, job_id: str):
    """任务图册：与期次图册同一视图，多一层任务面包屑。"""
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _charts_page(request, out_dir, job=job)


@app.get("/jobs/{job_id}/archive", response_class=HTMLResponse)
async def job_archive(request: Request, job_id: str):
    """任务运行档案：比期次档案多出控制台输出与状态链上下文。"""
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _archive_page(request, out_dir, job=job)


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
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
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


@app.get("/api/periods")
async def api_periods(request: Request):
    """期次列表（新工作区系统 /app 的数据源）——与首屏印记链同源（period_cards）。

    期次文案走 src/period.py（口径唯一来源）；带后缀目录（如 202605_复现）算不出
    总期号时退回目录名，不编假期号。
    """
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    out = []
    for c in period_cards():
        try:
            _idx, total = period_mod.issue_of(c["period"])
            label = f"第 {total} 期 · {period_mod.label(c['period'])}"
        except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
            label = c["period"]
        out.append({"period": c["period"], "label": label,
                    "signed": c["status"] == "signed", "status": c["status"],
                    "url": c["url"]})
    return {"periods": out}


@app.get("/api/me")
async def api_me(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"name": user, "role": config.role_of(user)}


@app.get("/api/periods/{period}")
async def api_period_detail(request: Request, period: str):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    try:
        no, total = period_mod.issue_of(period)
        label = f"第 {total} 期 \u00b7 {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        no, total, label = None, None, period
    window = ""
    facts = d / "overview_facts.json"
    if facts.exists():
        try:
            window = json.loads(facts.read_text(encoding="utf-8")).get("coverage_window", "")
        except (OSError, json.JSONDecodeError):
            pass
    m = re.match(r"^(\d{6})", d.name)
    pid = m.group(1) if m else period
    ledger_ok = (config.INPUT_DIR / pid / "台账.xlsx").exists()
    generated_ok = (d / "red_slots.json").exists()
    steps = {"ledger": ledger_ok, "input": ledger_ok, "generated": generated_ok}
    last = next((j for j in jobs.list_jobs(30) if j.get("period") == pid), None)
    return {
        "period": pid, "label": label, "no": no, "total": total,
        "window": window, "palette": config.PALETTE, "steps": steps,
        "lastJob": {"id": last["id"], "status": last["status"],
                    "created_at": last.get("created_at")} if last else None,
    }


def _paginate(items, limit, offset):
    """统一分页：?limit=&offset= -> {rows, total, limit, offset, has_more}"""
    total = len(items)
    offset = max(0, offset)
    limit = min(max(1, limit), 500)
    rows = items[offset:offset + limit]
    return {"rows": rows, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + limit < total}


@app.post("/api/periods/{period}/sign")
async def api_period_sign_json(request: Request, period: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    body = await request.json()
    note = str(body.get("note", ""))
    manual_ack = bool(body.get("known", body.get("manual_ack", False)))
    ok, res = approval.sign(d, guard, collation.build(d), note=note, manual_ack=manual_ack)
    if not ok:
        return JSONResponse({"error": str(res)}, status_code=409)
    return {"status": approval.status(d, res), "fingerprint": approval.fingerprint(d)}


@app.post("/api/periods/{period}/forecast-choice")
async def api_forecast_choice(request: Request, period: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    body = await request.json()
    choice = body.get("choice")
    if not isinstance(choice, dict):
        return JSONResponse({"error": "choice 必须是 {学科: 模型名}"}, status_code=400)
    out = d / "forecast_choice.json"
    rec = {"choice": choice, "by": guard, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "saved": len(choice), "path": str(out.name)}


@app.post("/api/periods/{period}/revoke")
async def api_period_revoke_json(request: Request, period: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    body = await request.json()
    note = str(body.get("note", ""))
    ok, res = approval.revoke(d, guard, note=note)
    if not ok:
        return JSONResponse({"error": str(res)}, status_code=409)
    return {"status": approval.status(d, res)}


@app.post("/api/periods/{period}/fill")
async def api_period_fill_json(request: Request, period: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    body = await request.json()
    items = body.get("items") or {}
    if not isinstance(items, dict):
        return JSONResponse({"error": "items 必须是 {todo_id: value}"}, status_code=400)
    from . import workbench                                     # noqa: PLC0415
    n = 0
    for todo_id, value in items.items():
        if str(todo_id).strip():
            workbench.save_fill(d, str(todo_id), str(value), by=guard)
            n += 1
    return {"ok": True, "saved": n}


@app.post("/api/periods/{period}/flag")
async def api_period_flag_json(request: Request, period: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    body = await request.json()
    loc = str(body.get("loc", "")).strip()
    if not loc:
        return JSONResponse({"error": "loc 不能为空"}, status_code=400)
    from . import workbench                                     # noqa: PLC0415
    r = workbench.toggle_flag(d, loc, by=guard)
    return {"ok": True, "loc": r["loc"], "state": r["state"], "n_doubt": r["n_doubt"]}


@app.get("/api/periods/{period}/redslots")
async def api_period_redslots(request: Request, period: str,
                              limit: int = 50, offset: int = 0):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
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
async def api_period_collation(request: Request, period: str,
                               limit: int = 50, offset: int = 0):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    data = collation.build(d)
    sections = [{"id": s["id"], "name": s["name"], "note": s.get("note", ""),
                 "count": s.get("count", 0), "text": s.get("text", 0),
                 "cell": s.get("cell", 0), "chart": s.get("chart", 0),
                 "manual": s.get("manual", 0)}
                for s in data.get("sections", [])]
    all_slots = []
    for s in data.get("sections", []):
        for it in s.get("slots", []):
            all_slots.append({"section": s["id"], **it})
    page = _paginate(all_slots, limit, offset)
    page["sections"] = sections
    page["period"] = data.get("period", "")
    page["assertions"] = data.get("assertions", {})
    return page


@app.get("/api/periods/{period}/charts")
async def api_period_charts_json(request: Request, period: str,
                                 limit: int = 50, offset: int = 0):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    d = resolve_period_dir(period)
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    q = urllib.parse.quote(d.name)
    items = []
    for it in jobs.list_charts(d):
        items.append({"name": it["name"], "group": it["group"],
                      "url": f"/p/{q}/chart/" + urllib.parse.quote(it["rel"])})
    return _paginate(items, limit, offset)


@app.get("/api/ledger/sheets")
async def api_ledger_sheets(request: Request, period: str = ""):
    if not current_user(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    import openpyxl                                        # noqa: PLC0415
    m = jobs.PERIOD_RE.match(period or "")
    if m:
        lp = config.INPUT_DIR / m.group(0) / "台账.xlsx"
    else:
        lp = None
        for d in sorted(config.INPUT_DIR.glob("*/台账.xlsx"), reverse=True):
            lp = d
            break
    if lp is None or not lp.exists():
        return JSONResponse({"error": "台账文件不存在"}, status_code=404)
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


@app.post("/api/analyze")
async def api_analyze(request: Request):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    body = await request.json()
    period = str(body.get("period", "")).strip()
    scope = str(body.get("scope", "")).strip()
    d = resolve_period_dir(period) if period else None
    if d is None:
        return JSONResponse({"error": "期次不存在"}, status_code=404)
    facts_file = d / "overview_facts.json"
    meta_file = d / "meta.json"
    if not facts_file.exists():
        return JSONResponse({"error": "该期次尚无 overview_facts.json"}, status_code=404)
    try:
        facts = json.loads(facts_file.read_text(encoding="utf-8"))
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": f"数据读取失败：{exc}"}, status_code=500)
    # 硬约束：LLM 不进数据路径。text 由 sentences.build() 组装。
    import sentences                                      # noqa: PLC0415
    import local_llm                                      # noqa: PLC0415
    P = meta.get("period_current") or period
    Q = meta.get("period_prev") or ""
    texts = sentences.build(facts, P, Q)
    # scope 过滤：空=全部；否则只取匹配 key 的段落
    if scope:
        texts = {k: v for k, v in texts.items() if scope in k or k in scope}
    # 数字防护盾：protect() 把数字换成占位符，shields 记录映射
    shields = []
    for key, t in texts.items():
        protected, mapping = local_llm.protect(t)
        shields.append({
            "key": key,
            "n_numbers": len(mapping),
            "protected_len": len(protected),
        })
    return {"period": P, "prev": Q, "text": texts, "shields": shields,
            "n_sections": len(texts), "backend": "sentences"}


@app.get("/api/forecast/meta")
async def api_forecast_meta(request: Request):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    return forecasting.page_context()


@app.post("/api/forecast/run")
async def api_forecast_run(request: Request):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
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
async def api_create_job(request: Request,
                         period: str = Form(""),
                         file: UploadFile = File(None),
                         backtest: str = Form("0")):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
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
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    # 契约 §2.3：失败态给结构化的「缺什么」，不让前端解析断言文本
    if job.get("missing"):
        job["ok"] = False
    return job


@app.get("/api/jobs/{job_id}/artifacts")
async def api_artifacts(request: Request, job_id: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    job = jobs.read_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return {"job": job, "artifacts": jobs.collect_artifacts(job)}


@app.post("/api/jobs/{job_id}/rerun")
async def api_rerun_job(request: Request, job_id: str):
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
    user = guard
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
    guard = require_admin(request)
    if isinstance(guard, JSONResponse):
        return guard
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
async def download(request: Request, job_id: str, key: str):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/", status_code=303)
    if key == archive.LOGPACK_KEY:
        out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
        data, name = archive.pack(out_dir, job)
        return _zip_response(data, name)
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
