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

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import approval, archive, collation, config, jobs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()
    yield


app = FastAPI(title="文衡 · 学科信息参考自动化演示", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET, same_site="lax")
app.mount("/static", StaticFiles(directory=str(config.SERVER_DIR / "static")), name="static")
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
    if request.url.path.startswith("/static/"):
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
               revoked: str = "", rebuilt: str = ""):
    """**首屏 = 馆员工作台**（最新一期）。没有可对勘的期次时才退回控制台。

    2026-09-19 从「首屏=对勘本」改过来。对勘本回答的是"这份报告怎么拼出来的"
    （生产视角），而打开这个站的人要的是"这次要我做什么决定"（馆员视角）。
    对勘本 / 图册 / 档案页都还在，收进工作台底部的「审计视图」入口。
    """
    from . import workbench                                     # noqa: PLC0415
    cards = period_cards()
    if cards:
        d = resolve_period_dir(cards[0]["period"])
        if d is not None:
            return page(request, "workbench.html",
                        **workbench.build(d),
                        periods=cards, rebuilt=rebuilt,
                        flash=_flash(err, signed, revoked))
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


@app.post("/p/{period}/fill")
async def period_fill(request: Request, period: str, id: str = Form(""),
                      value: str = Form(""), back: str = Form("")):
    """在线填【手工：】项。**只写产物目录的 manual_inputs.json，台账一个字节不碰**
    —— 填的是报告，不是数据源；这正是"可溯源"与"可修改"的边界。

    走**真实表单 POST + 303 回跳**，不用 AJAX —— 栈契约（test_stack_contract）
    要求状态变更不依赖 JS 跑通，填写/存疑也是状态变更，同样适用。
    """
    from . import workbench                                     # noqa: PLC0415
    user = current_user(request)                                # 登录保护，同 _do_sign
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None or not id.strip():
        return RedirectResponse(back or "/", status_code=303)
    workbench.save_fill(d, id, value, by=user)
    return RedirectResponse(back or "/", status_code=303)


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
async def period_rebuild(request: Request, period: str, back: str = Form("")):
    """填完重出报告：把在线填的值叠加到报告初稿上。

    三件事按这个顺序做，不能乱：
      1. **先把旧成品撤到 `_superseded/`**（复用 `parse_ledger.quarantine_final_products`）
         —— 覆盖前留一份机器稿，出了问题能回滚；
      2. `fill_docx.main(..., manual_inputs=…)` 用**已解析的宽表**重出，
         不重新解析台账（重解析会把填值对应不上的风险引进来）；
      3. 只写 `out/<期次>/`，台账一个字节不碰。

    耗时约 5–15 秒（要重新插 96 张图），同步阻塞 —— uvicorn 单 worker 是
    项目既定约束（SSE + 内存态任务队列），演示时点一次等一下即可。
    """
    import parse_ledger                                         # noqa: PLC0415
    import fill_docx                                            # noqa: PLC0415
    from . import workbench                                     # noqa: PLC0415
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    fills = workbench.load_fills(d)
    if not fills:
        return RedirectResponse(_flash_back(back, "err=还没有填写内容"), status_code=303)
    parse_ledger.quarantine_final_products(d, None)
    try:
        fill_docx.main(ledger_dir=str(d), manual_inputs=fills)
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
