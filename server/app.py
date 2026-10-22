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
import threading
import time
import urllib.parse
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response, StreamingResponse)
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import (acquisition, approval, archive, artifacts, collation, config, datapack, jobs,
               report_preview, shelf_data, shelf_preview, visibility)
from . import forecasting
from .guards import admin_route, user_file_route, user_route
from starlette.background import BackgroundTask
from src import parse_ledger  # 成品隔离/回滚的唯一口径（FINAL_PRODUCTS / SUPERSEDED_DIR）
from .protected_static import AdminStaticFiles
from src import period as period_mod  # 期次口径唯一来源（ADR-0001：新工作区 API 也用它）
from src import period_facts  # 期次事实：目录/盘点/并入/产物/顺延的唯一 module
from src import ledger as ledger_mod  # 动态监测表（母本）路径唯一口径（2026-10-13：input/ 只放母本）
from src import forecast_choice  # 预测选模的唯一 implementation（读写/快照/留痕）
from src import session_store  # 会话库（票 11）——对话前门会话的服务端持久化
from src import state_store      # 系统状态库：/api/status 报「能不能写」（ADR-0012 决定 7）
from esi_v1.data import display_name  # 学科名中文化（契约 #22）


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()
    # 会话库（票 11）：生产装配路径（`out/_sessions/sessions.sqlite`）。
    # 直调处理函数的测试不跑 lifespan → SESSION_DB_PATH 保持 None → 不落库、绝不碰真数据。
    global SESSION_DB_PATH
    SESSION_DB_PATH = session_store.store_path(config.ROOT)
    yield


app = FastAPI(title="文衡 · 学科信息参考自动化演示", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET, same_site="lax")
app.mount("/static", AdminStaticFiles(directory=str(config.SERVER_DIR / "static"),
                                       protected_paths=("collation-demo.html",)), name="static")
# 新工作区系统（React SPA，构建产物 web/dist 入库）——见 docs/adr/0001。
# check_dir=False：干净 clone 里 dist 缺失时不要拖垮整个服务启动，让它 404 就行。
async def _shelf_preview_data():
    """封面/目录/名词解释基础投影（两种角色同份；不涉指标数字）。"""
    return await run_in_threadpool(shelf_preview.javascript_response, period_cards())


async def _shelf_full_data():
    """每次请求均从已部署期次构建，避免把指标留在静态构建产物。

    2026-10-11 起两种角色（管理员/操作员）同拿全数据——guest 预览边界已取消。
    """
    return await run_in_threadpool(shelf_data.javascript_response, period_cards())


app.mount("/app", AdminStaticFiles(directory=str(config.ROOT / "web" / "dist"), html=True,
                                   check_dir=False, require_login=True,
                                   protected_paths=("shelf/data.js", "shelf/preview.js"),
                                   user_responses={"shelf/data.js": _shelf_full_data,
                                                   "shelf/preview.js": _shelf_preview_data}),
          name="web")
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
        return JSONResponse({"error": "需要管理员权限",
                             "hint": "操作员只读，此操作仅管理员可用"}, status_code=403)
    return user


def require_user(request: Request):
    """已登录即可（管理员与操作员都放行）——只读端点用。"""
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录", "hint": "请先登录"}, status_code=401)
    return user


def require_admin_file(request: Request):
    """附件与图沿用旧的未登录跳转；操作员按只读放行的口不用它。"""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if config.role_of(user) != "admin":
        return JSONResponse({"error": "需要管理员权限",
                             "hint": "操作员只读，此文件仅管理员可下载"}, status_code=403)
    return user


def require_user_file(request: Request):
    """文件口：已登录即可（管理员与操作员都放行）；未登录照旧 303 去登录页。"""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


#: 兼容旧导入：真正的规则在 `server.visibility`，这里只是清单投影的别名。
OPERATOR_HIDDEN_KEYS = visibility.ADMIN_ONLY


def _role_of_request(request):
    return config.role_of(current_user(request) or "")


def _visible_artifacts(items, role):
    """产物清单的 adapter：规则在 `visibility`，这里不重写 key 判断。"""
    return visibility.visible(role, items)


def _operator_download_guard(role, key):
    """下载口 adapter：红件/日志包/主台账的允许与否由 visibility 决定。"""
    if not visibility.allowed(role, key, "download"):
        return JSONResponse({"error": "需要管理员权限",
                             "hint": "操作员只读，此文件仅管理员可下载"}, status_code=403)
    return None


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


def _legacy_login_gate(request):
    """旧页面只关未登录这一道门；已登录（管理员/操作员）放行到新工作区。

    隐藏屏（红件/溯源/运行档案）的可见性由新工作区的路由守卫表达，
    这里不再按角色分流（2026-10-11 角色改两级后）。
    """
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return None


def _legacy_redirect(request, key, **fmt):
    """老路由 302 的统一出口：已登录用户可进入对应的新工作台。

    未登录的访问与旧页面一样落到 /login（303）——新站只认 /api/me 的 401，
    老 URL 的闸得在老站这一侧关住。
    """
    gate = _legacy_login_gate(request)
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
         "show_hint_user": config.ADMIN_USER if config.SHOW_HINT else ""})


@app.post("/login")
async def do_login(request: Request, username: str = Form(""), password: str = Form("")):
    ip = request.client.host if request.client else "?"
    rec = _login_fails.setdefault(ip, {"n": 0, "until": 0.0})
    if rec["until"] > time.time():
        return RedirectResponse("/login?err=尝试过于频繁，请稍后再试", status_code=303)
    if check_credentials(username, password):
        request.session["user"] = username
        _login_fails.pop(ip, None)
        # 2026-10-12（rick）：两种角色都先落到**陈列馆首页**（看 → 问 → 做 三面模型），
        # 从陈列馆的「问文衡 →」进对话页，再从对话页「去生成台」进工作台。
        return RedirectResponse("/app/shelf/", status_code=303)
    rec["n"] += 1
    if rec["n"] >= 5:
        rec.update({"n": 0, "until": time.time() + 60})
    return RedirectResponse("/login?err=账号或密码不正确", status_code=303)


def check_credentials(username: str, password: str) -> bool:
    """登录口令校验：管理员与操作员（评委）各一套。

    ⚠ 2026-10-02：口令不再有内置默认值——没配口令（空）一律拒绝，空口令登不进来。
    ⚠ 2026-10-11：guest 角色取消，改为「操作员」；两套口令见 config。
    """
    if not username or not password:
        return False
    return bool(
        (config.ADMIN_PASS and username == config.ADMIN_USER and password == config.ADMIN_PASS)
        or (config.OPERATOR_PASS and username == config.OPERATOR_USER
            and password == config.OPERATOR_PASS)
    )


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
    for name in sorted(period_facts.product_periods(config.OUT_DIR, allow_suffix=True),
                       reverse=True):
        d = config.OUT_DIR / name
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
    """期次字符串 → out/ 下的实际目录（adapter；事实在 period_facts.resolve）。"""
    return period_facts.resolve(period, config.OUT_DIR)


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
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/redslots", response_class=HTMLResponse)
async def period_redslots(request: Request, period: str):
    """老红件清单页已下线（ADR-0002 阶段 2）—— 302 到新工作区。"""
    gate = _legacy_login_gate(request)
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
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/trace" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


def _find_ledger():
    """运行时动态监测表（母本）：`input/云大全学科排名、阈值动态检测表.xlsx`。

    2026-10-13 起 input/ 只放母本（不再有 `input/<期次>/监测表.xlsx`）；
    母本含全部期次，逐格溯源/表页按页面期次消费。找不到返回 None（页面降级说明）。
    """
    p = ledger_mod.runtime_path(config.ROOT)
    return p if p.exists() else None


@app.get("/p/{period}/charts", response_class=HTMLResponse)
async def period_charts(request: Request, period: str):
    """老图册页已下线（ADR-0002 阶段 2）—— 302 到新工作区。"""
    gate = _legacy_login_gate(request)
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

def _flex_ctx(d, intent=None, flash=None, variant=None):
    """灵活报告页上下文。`variant="rule"` 时正文取规则稿留底（report.rule.md）。"""
    import flexible.report as flex_report                           # noqa: PLC0415
    from flexible import mdview, planner, spec                     # noqa: PLC0415
    reports = flex_report.list_reports(d)
    cur = next((r for r in reports if r["intent"] == intent), None) or \
        (reports[0] if reports else None)
    body = None
    variant = (variant or "").strip()
    if cur:
        md_path = pathlib.Path(cur["path"])
        rule_path = md_path.parent / "report.rule.md"
        if variant == "rule" and rule_path.is_file():
            md_path = rule_path
        md = md_path.read_text(encoding="utf-8")
        imgmap = {n: f"/p/{d.name}/flexible/chart/{cur['intent']}/"
                     + urllib.parse.quote(n)
                  for n in (cur.get("meta", {}).get("charts") or [])}
        body = mdview.render(md, img_map=imgmap)
    return {"period_dir": d.name, "reports": reports, "cur": cur, "body": body,
            "variant": variant if (cur and variant == "rule"
                                   and (pathlib.Path(cur["path"]).parent
                                        / "report.rule.md").is_file()) else "",
            "has_rule": bool(cur and cur.get("has_rule")),
            "intents": [{"id": k, "cn": v} for k, v in planner.INTENTS.items()],
            "chart_catalog": spec.catalog(), "flash": flash,
            "disciplines": _flex_disciplines(d),
            "write": _flex_write_state()}


def _flex_disciplines(d) -> list[dict]:
    """监测学科清单（下拉用）：`[{en, cn}]`；数据缺时不报错、回空表。"""
    try:
        from flexible.datasource import DataSource, cn_name         # noqa: PLC0415
        src = DataSource(d)
        return [{"en": x, "cn": cn_name(x)} for x in src.disciplines]
    except Exception:                                                # noqa: BLE001
        return []


def _flex_write_state() -> dict:
    """写作位（AI 润色）的部署状态：开关开了且配了云才算可用（判据在 `ai._writing`）。"""
    try:
        from ai import _writing                                      # noqa: PLC0415
        return _writing.writing_state("write").as_dict()
    except Exception:                                                # noqa: BLE001
        return {"enabled": False, "available": False}


@app.get("/p/{period}/flexible", response_class=HTMLResponse)

async def period_flexible(request: Request, period: str, intent: str = "",
                          err: str = "", ok: str = ""):
    """老灵活报告页已下线（ADR-0002 第二轮）—— 302 到分析台（灵活报告是其中一块）。

    保留函数签名：老链接可能带 `?intent=` / `?err=` / `?ok=`，接下来丢弃即可。
    🔴 **图表路由 `/p/{period}/flexible/chart/*` 与 JSON API 不动**——
       新站分析台的 body_html 直接引用那些图地址（契约 #21）。
    """
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/flexible" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/flexible/chart/{intent}/{name}")
@user_file_route
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


@app.get("/p/{period}/flexible/{intent}/report.html")
@user_file_route
async def period_flexible_report(request: Request, period: str, intent: str):
    """灵活报告整篇下载（rick 2026-09-29：出稿后「下载报告」）。

    返回的是**单文件**版：下载时把页内相对路径的图**即时内联**成 `data:` URI
    （`mdview.inline_images`）——离开 `charts/` 目录也带图；磁盘原件一个字节不动
    （旧稿也立刻生效，不必重出）。页内图在生成期已内联的新稿走同一函数，幂等。
    """
    if not re.fullmatch(r"[a-z0-9_]+", intent or ""):
        raise HTTPException(status_code=404)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    p = d / "flexible" / intent / "report.html"
    if not p.exists():
        raise HTTPException(status_code=404)
    import flexible.mdview as flex_mdview                            # noqa: PLC0415
    text = flex_mdview.inline_images(p.read_text(encoding="utf-8"), base_dir=p.parent)
    fn = urllib.parse.quote(f"灵活报告_{period}_{intent}.html")
    return Response(text, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-cache",
                             "Content-Disposition": f"attachment; filename*=utf-8''{fn}"})


@app.get("/p/{period}/flexible/{intent}/report.docx")
@user_file_route
async def period_flexible_report_docx(request: Request, period: str, intent: str):
    """灵活报告 DOCX 下载（2026-10-15，rick：给 docx 方便馆员修改）。

    磁盘上有且不比 `report.md` 旧 → 直接发；否则**现场转换**（不落盘）——
    旧稿即刻可用，不必重出。页脚标注「内部参考 · 非报送件」（doc19 导出规格）。
    """
    if not re.fullmatch(r"[a-z0-9_]+", intent or ""):
        raise HTTPException(status_code=404)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    md_p = d / "flexible" / intent / "report.md"
    dx_p = d / "flexible" / intent / "report.docx"
    if not md_p.exists():
        raise HTTPException(status_code=404)
    if dx_p.exists() and dx_p.stat().st_mtime >= md_p.stat().st_mtime:
        data = dx_p.read_bytes()
    else:
        def _convert():
            import flexible.docxview as flex_docx                    # noqa: PLC0415
            return flex_docx.build(md_p.read_text(encoding="utf-8"), base_dir=md_p.parent)
        data = await run_in_threadpool(_convert)
    fn = urllib.parse.quote(f"灵活报告_{period}_{intent}.docx")
    return Response(data, media_type=(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers={"Cache-Control": "no-cache",
                 "Content-Disposition": f"attachment; filename*=utf-8''{fn}"})


@app.get("/p/{period}/archive", response_class=HTMLResponse)

async def period_archive(request: Request, period: str):
    """老运行档案页已下线（ADR-0002 第二轮）—— 302 到新档案视图。

    数据等价物走 `GET /api/periods/{period}/archive`（契约 #18）；
    下载端点 `/p/{period}/download/logpack` 保留（§六 保留项）。
    """
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/archive" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@app.get("/p/{period}/chart/{rel:path}")
@user_file_route
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
@user_file_route
async def period_download(request: Request, period: str, key: str):
    guard = _operator_download_guard(_role_of_request(request), key)
    if guard:
        return guard
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
    gate = _legacy_login_gate(request)
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
    gate = _legacy_login_gate(request)
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
    gate = _legacy_login_gate(request)
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
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    job = jobs.read_job(job_id)
    if not job:
        return RedirectResponse("/app/", status_code=302)
    period = urllib.parse.quote(job.get("out_period") or job["period"])
    return _legacy_redirect(request, "/jobs/{job_id}/collation", period=period)

@app.get("/api/jobs/{job_id}/approval")
@user_route
async def api_approval(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    out_dir = config.OUT_DIR / (job.get("out_period") or job["period"])
    rec = approval.read(out_dir)
    rec["status"] = approval.status(out_dir, rec)
    return rec


@app.get("/api/jobs/{job_id}/progress")
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


# ---------------- API ----------------

@app.get("/healthz")
async def healthz():
    return {"ok": True}


#: 状态库只读降级时给馆员看的话（页面原文）。技术细节只进服务端日志：
#: 这两句里不出现库名、版本号、迁移之类的字眼，只说「现在怎么样 + 找谁」。
STATE_DB_TOO_NEW = "本机数据存储版本比程序新，已进入只读模式，请联系管理员。"
STATE_DB_UNREADABLE = "本机数据存储打不开，保存类操作已暂停，请联系管理员。"


def _state_db_status() -> dict:
    """`/api/status` 的 `state_db`：本机状态库现在能不能写（ADR-0012 决定 7 的告警数据源）。

    库不存在＝正常（还没签过单），**这里绝不建库**——`state_store.health()` 只连已存在的文件。
    降级分两种：版本比程序新（能读、不能写）与库打不开；两种都给一句人话，页面据此挂横幅。
    """
    try:
        h = state_store.health(jobs.state_db_path())
    except OSError:                      # 路径本身读不了（权限/被占）：如实报，不装作健康
        return {"ok": False, "schema_version": 0,
                "code_schema_version": state_store.SCHEMA_VERSION,
                "degraded": True, "message": STATE_DB_UNREADABLE}
    degraded = bool(h.get("degraded"))
    too_new = degraded and (h.get("schema_version") or 0) > (h.get("code_version") or 0)
    return {
        "ok": not degraded,
        "schema_version": h.get("schema_version") or 0,
        "code_schema_version": h.get("code_version") or 0,
        "degraded": degraded,
        "message": (STATE_DB_TOO_NEW if too_new else STATE_DB_UNREADABLE) if degraded else "",
    }


@app.get("/api/status")
@user_route
async def api_status(request: Request):
    """工作区任务入口：只提供前端跳转所需的任务标识，不暴露落盘记录。

    `state_db`（2026-10-22 加）：本机数据存储能不能写——库版本比程序新时只能只读，
    页面据此挂一条常驻告警（写入会失败，得先让馆员知道为什么）。既有字段一个不动。
    """
    active = jobs.active_job()
    last = next((j for j in jobs.list_jobs(20) if j.get("stats")), None)
    return {
        "active": (active or {}).get("id"),
        "last": ({"id": last.get("id"), "period": last.get("period")}
                 if last else None),
        "state_db": _state_db_status(),
    }


def _period_label(period: str) -> str:
    """期次文案走 src/period.py（口径唯一来源）；算不出总期号时退回期次名，不编假期号。"""
    try:
        _idx, total = period_mod.issue_of(period)
        return f"第 {total} 期 · {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        return period


def _period_has_data(period: str) -> bool:
    """「期次认得出」的宽松口径：取数状态或当期核对副本已存在（还没出稿也算）。

    与 /api/periods 的补录、单期详情的宽松判定同一口径——取数台接手的期次，
    它的空产物 / 空回滚列表要回 200 空数组，而不是 404（404 会在页面控制台报错）。
    """
    m = re.match(r"^(\d{6})", period or "")
    if not m:
        return False
    pid = m.group(1)
    acq = acquisition.load(pid)
    return period_facts.has_data(period, out_root=config.OUT_DIR, acquisition=acq,
                                 copy_exists=acquisition.copy_path(pid).exists())


def _acquisition_only_periods(known: set[str]) -> list[dict]:
    """还没出稿、但取数已经有动静的期次：有取数状态，或当期核对副本已就位。

    取数台接手「未出稿的当期」——这些期次不在 period_cards（那靠 red_slots.json），
    列表里单独补进来（状态按「未签发」显示，出稿后由 period_cards 接管）。
    ⚠️ 「只是点过一次重新检查」的期次不算（那种状态里连文件都没有）：只在 `started`
    （确实取到过文件）或有核对副本时才进列表——否则列表会多出一个点进去就 404 的空期次。
    """
    extra = {p for p in acquisition.periods() if _acq_touched(p) or _acq_opened(p)}
    acq_root = config.OUT_DIR / "_acquisition"
    if acq_root.is_dir():
        for d in acq_root.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{6}", d.name) \
                    and acquisition.copy_path(d.name).exists():
                extra.add(d.name)
    return [{"period": p, "label": _period_label(p), "signed": False,
             "status": "unsigned", "generated": False,
             "url": "/p/" + urllib.parse.quote(p)}
            for p in sorted(extra - known, reverse=True)]


@app.get("/api/periods")
@user_route
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
    role = config.role_of(user)
    return {"name": user, "role": role,
            "capabilities": visibility.capabilities(role)}


@app.get("/api/periods/{period}")
@user_route
async def api_period_detail(request: Request, period: str):
    """单期详情：三步条＝①取数 ②核对并并入 ③生成（ADR-0004）。

    未出稿但取数已有动静的期次（有取数状态、或当期核对副本已就位）也返回详情——
    「先取数、后生成」的工作流需要它们在台面上；三步的判定不出数字。
    """
    m = re.match(r"^(\d{6})", period or "")
    pid = m.group(1) if m else period
    acq = acquisition.load(pid)
    has_input = acquisition.copy_path(pid).exists()
    f = period_facts.facts(period, out_root=config.OUT_DIR, acquisition=acq,
                           copy_exists=has_input)
    if not f.has_data:
        return _period_missing()
    d = f.dir
    try:
        no, total = period_mod.issue_of(period)
        label = f"第 {total} 期 \u00b7 {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        no, total, label = None, None, period
    window = ""
    if d is not None:
        window = artifacts.read_facts(d).get("coverage_window", "")
    totals = (acq or {}).get("totals") or {}
    verified = totals.get("verified") if isinstance(totals.get("verified"), int) else None
    expected = totals.get("expected") if isinstance(totals.get("expected"), int) else None
    copy_state = ((acq or {}).get("copy") or {}).get("state") or "none"
    steps = {"fetch": f.acquire_ok, "merge": f.merge_ok, "generate": f.generate_ok}
    last = next(iter(jobs.list_jobs(limit=30, period=pid)), None)
    return {
        "period": pid, "label": label, "no": no, "total": total,
        "window": window, "palette": config.PALETTE, "steps": steps,
        "task": f.as_home(),
        "acquisition": {"started": acq is not None, "verified": verified,
                        "expected": expected, "copy": copy_state},
        "lastJob": {"id": last["id"], "status": last["status"],
                    "created_at": last.get("created_at")} if last else None,
    }


def _acq_expected_data(period: str) -> dict:
    """这一期**本该**对应哪一档数据：ESI 发布月＝期次当月；InCites 快照按 SNAP_MAP 解析。"""
    from src import acquisition_state as _st                          # noqa: PLC0415
    y, m = period[:4], int(period[4:6])
    try:
        snap = _st.resolve_snapshot(period, _st.INCITES_ROOT_DEFAULT) or ""
    except Exception:                                                # noqa: BLE001
        snap = ""
    return {"esi": f"{y} 年 {m} 月", "incites": str(snap)}


def _acq_reconcile(period: str, state: dict) -> dict:
    """要求期次 vs **实际下到哪一期**（票 03）。

    ESI/InCites 的导出接口没有期次参数——抓的是**当前发布**；所以对账是唯一能发现
    「拿当期数据冒充往期」的地方。状态里的 data_period/snapshot 是取数当时从网站页面读到的。
    还没取到任何文件时 `ok=true`（无可对账），免得开新一期就先弹「数据期对不上」。
    """
    exp = _acq_expected_data(period)
    act = state.get("data_period") or {}
    actual = {"esi": str(act.get("esi") or ""), "incites": str(state.get("snapshot") or "")}
    # 还没取到任何文件（开新一期/刚检查过）：无可对账，别报「对不上」吓人
    if not actual["esi"] and not actual["incites"]:
        return {"expected": exp, "actual": actual, "ok": True}
    ok = bool(actual["esi"]) and actual["esi"] == exp["esi"] \
        and (not exp["incites"] or actual["incites"] == exp["incites"])
    return {"expected": exp, "actual": actual, "ok": ok}


def _acq_touched(period: str) -> bool:
    """这一期有没有**取数动静**（不只是点过一次「重新检查」）。

    只检查过的状态里只有 `{period, preflight}`——没有 groups/totals/copy。
    用它把「点过一次检查的空期次」从期次列表和「往期」判据里排除掉。
    """
    st = acquisition.load(period) or {}
    return bool(st.get("groups") or st.get("totals") or st.get("copy"))


def _acq_opened(period: str) -> bool:
    """这一期是不是**开新一期**登记出来的空壳（票 05）。

    空壳只落了 preflight、没有取数动静，按 `_acq_touched` 本不算；但既已登记就该出现在
    期次列表里（否则 `?period=` 深链会被前端「列表没有就退回首期」冲掉）。用独立标记
    `opened` 区分于「只点过一次重新检查」的临时状态，且**不**计入 `_acq_touched`——
    否则「开一期新」会把当前期误判成「往期只读」。
    """
    return bool((acquisition.load(period) or {}).get("opened"))


def _acq_mode(period: str) -> str:
    """`collect`＝当期可取；`readonly`＝往期档案只读（票 03）。

    判据是**真取过**：比它更新的期次里只要有一期有取数动静（`_acq_touched`），它就是往期
    （ESI/InCites 不提供历史数据，对往期重取只会把当期数据写进往期目录）。
    ⚠️ 只看"有没有状态文件"不够——**点一次「重新检查」也会落个状态文件**，那不算取过。
    """
    try:
        if any(p > period and _acq_touched(p) for p in acquisition.periods()):
            return "readonly"
    except Exception:                                                # noqa: BLE001
        pass
    return "collect"


@app.get("/api/periods/{period}/acquisition")
@user_route
async def api_period_acquisition(request: Request, period: str):
    """自动取数台状态（只读）。没有取数记录时 started=false——界面显示「还没开始」，不编数据。

    状态由取数流程写入 `out/_acquisition/<期次>.json`（人触发；见 ADR-0004）。
    另附 `mode`（当期可取 / 往期只读）与 `reconcile`（要求期次 vs 实际数据期，票 03）。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    mode = _acq_mode(period)
    state = acquisition.load(period)
    if state is None:
        return {"period": period, "started": False, "mode": mode}
    lv = _acq_op_liveness(period, state)          # 只读判断：前端据此显示「疑似中断」
    if lv is not None:
        state = {**state, "op": {**(state.get("op") or {}), "liveness": lv}}
    return {"period": period, "started": True, "mode": mode,
            "reconcile": _acq_reconcile(period, state), **state}


# ------------------------------------------------------------------ 自动取数台 · 写动作（X3）
# 全部由**人按键**触发（R-1）：这里是拉起 `tools/acquire.py` 的**非交互执行口**，
# 进度由取数流程写回 `out/_acquisition/<期次>.json`，前端轮询读取。不做任何数据加工。
def _acq_acquire_py():
    return config.ROOT / "tools" / "acquire.py"


def _acq_op_liveness(period: str, st: dict) -> str | None:
    """正在跑的任务现在算不算活着（**只读判断，不改状态**）：

    - `alive`：有 pid 且进程在；或没有 pid 但状态文件 15 分钟内动过（启动窗口/旧状态）；
    - `dead`：有 pid 但进程没了（暴死/被强杀）；
    - `stale`：没有 pid 且超过 15 分钟没动静（ADR-0010 之前留下的旧僵尸）；
    - 非 running → None。

    GET 只把它算出来展示（`op.liveness`）；**自动结清**发生在写动作路径（`_acq_op_running`）。
    """
    op = st.get("op") or {}
    if op.get("state") != "running":
        return None
    pid = op.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        return "alive" if acquisition.pid_alive(pid) else "dead"
    try:
        age = time.time() - acquisition.state_path(period).stat().st_mtime
    except OSError:
        age = 0
    return "alive" if age <= acquisition.OP_STALE_SECONDS else "stale"


def _acq_op_running(period: str):
    """正在跑的取数任务；**判活＝进程在不在**（`op.pid`），无 pid 的旧状态回退 15 分钟时间口径。

    ADR-0010（2026-10-19）：此前只看「状态文件 1 小时内有改动」——进程暴死后要干等
    1 小时才放行（2026-10-17 实测）。现在判活落在 `_acq_op_liveness`；`dead`/`stale` 时
    **在这里（写动作路径；GET 不改状态）**把 `op` 落 `failed` 并放行新任务。
    """
    st = acquisition.load(period) or {}
    lv = _acq_op_liveness(period, st)
    if lv is None:
        return None
    if lv == "alive":
        return st.get("op") or {}
    why = "任务进程已退出" if lv == "dead" else "太久没有动静"
    st["op"] = {**(st.get("op") or {}), "state": "failed",
                "note": f"上次运行中断：{why}",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        acquisition.write_state(period, st)
    except OSError:
        pass
    return None


def _acq_kill_tree(pid: int) -> bool:
    """把取数任务**连它的子进程**一起停掉（Windows `taskkill /T /F`；POSIX 杀进程组）。"""
    import os
    import signal
    if os.name == "nt":
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S603
                               capture_output=True, text=True, timeout=30)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False


def _acq_spawn(period: str, action: str, extra: list | None = None):
    """拉起一个取数任务（detached）——先占位写「正在跑」，再起进程。"""
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    running = _acq_op_running(period)
    if running:
        return JSONResponse({"error": "有一项下载数据任务还在跑，等它完成再试。",
                             "hint": running.get("note", "")}, status_code=409)
    st = acquisition.load(period) or {}
    st["op"] = {"kind": action if action != "fetch" else "fetch", "state": "running",
                "note": "刚排上队，正在开始", "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    acquisition.write_state(period, st)
    log = config.OUT_DIR / "_acquisition" / f"{period}-{action}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    import os
    with open(log, "a", encoding="utf-8") as fh:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8",
               "PYTHONUNBUFFERED": "1"}
        subprocess.Popen(  # noqa: S603 — 固定脚本路径 + 期次已校验，无注入面
            [str(config.PYTHON), str(_acq_acquire_py()), action, period, *(extra or [])],
            cwd=str(config.ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env,
            # POSIX：自成进程组，「停止下载」才能连子进程一起停（Windows 用 taskkill /T）
            start_new_session=(os.name != "nt"))
    return {"ok": True, "started": True, "log": log.name}


#: 「取数专用浏览器」＝独立 profile + CDP 9222 的 Chrome；取数脚本靠附着它工作。
#: **凭证靠 Chrome 自己记住，系统从不碰账号密码**（`src`/`tools` 侧红线；首次需人工登录一次）。
def _acq_chrome_exe():
    """找本机 Chrome（装在哪都行）；找不到返回 None。"""
    import os
    cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(str(pathlib.Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    for p in cands:
        if pathlib.Path(p).exists():
            return p
    return None


def _acq_cdp_responds() -> bool:
    """9222 有没有**能应答 CDP 版本 JSON**的浏览器（不管是谁的）。"""
    import json as _json
    import urllib.request as _urlreq
    for url in ("http://127.0.0.1:9222", "http://localhost:9222"):
        try:
            with _urlreq.urlopen(url + "/json/version", timeout=2) as r:
                if r.status == 200 and _json.loads(r.read()).get("Browser"):
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _acq_cdp_alive() -> bool:
    """「下载数据专用浏览器」在跑：①9222 应答 CDP 版本 JSON **且** ②端口占用者命令行带专用 profile。

    只看①会被任意占 9222 的进程骗过（2026-10-17 实测：opencode 会话遗留的无头 Edge 也开 9222，
    `/json/version` 照样 200 → 曾被当成「已经在跑」→ 永远不开登录窗口）。认主口径见
    `src/acquisition_state.cdp_browser_ours`。
    """
    return _acq_cdp_responds() and acquisition.cdp_browser_ours()


def _acq_kill_profile_chrome(profile: pathlib.Path) -> int:
    """关掉占着这个 profile 的 Chrome 进程。

    同一个 profile 只能有一个浏览器实例：**先跑起来的那个没带调试端口时，后起的进程会
    把 URL 转交给它、自己不开端口**——那样 9222 永远起不来（2026-10-15 实测）。
    只关"命令行里带这个 profile"的进程，不碰用户其它 Chrome 窗口；登录态存在 profile 里，重开还在。
    """
    ps = ("$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\"; "
          "$hit = $p | Where-Object { $_.CommandLine -like '*" + str(profile) + "*' }; "
          "$n = @($hit).Count; "
          "$hit | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
          "$n")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=40)
        return int((r.stdout or "0").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


@app.post("/api/acquisition/browser")
@user_route
async def api_acq_browser(request: Request):
    """把「下载数据专用浏览器」拉起来（独立 profile `~/.chrome-clarivate` + CDP 9222）。

    已经在跑就不重复起。**只负责开窗**——登录仍由人（或 Chrome 记住的凭据）完成。
    9222 被**别的**程序占着时明确报错、不硬开（新开的 Chrome 抢不到端口，白弹窗还误导）。
    """
    if _acq_cdp_alive():
        return {"ok": True, "started": False, "already": True,
                "note": "下载数据专用浏览器已经在跑。"}
    if _acq_cdp_responds():
        owner = acquisition.cdp_listener_cmdline()[:120]
        return {"ok": False, "started": False, "already": False,
                "note": "9222 端口被别的程序占着（不是下载数据专用浏览器），"
                        f"先关掉占用它的浏览器/程序再试。占用者命令行：{owner}"}
    exe = _acq_chrome_exe()
    if not exe:
        return {"ok": False, "started": False, "already": False,
                "note": "没找到 Chrome（装一个，或把 chrome.exe 的路径告诉我）。"}
    profile = acquisition.CDP_PROFILE_DIR
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "started": False, "already": False, "note": f"准备 profile 目录失败：{e}"}
    # 同一 profile 只能一个实例：先把"没带调试端口"的那个收掉，否则新进程只转交 URL、不开 9222
    closed = _acq_kill_profile_chrome(profile)
    if closed:
        time.sleep(1.5)
    try:
        subprocess.Popen(  # noqa: S603 —— 固定路径 + 固定参数，无外部输入
            [exe, "--remote-debugging-port=9222", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check",
             # 入口与取数脚本一致（不是站点根）：ESI 走 legacy Indicators；InCites 走
             # `/#/analysis/0/organization`（NG InCites SPA）——站点根会落到别的产品入口，
             # 实测会显示 No Subscription Found（2026-10-16）
             "https://esi.clarivate.com/IndicatorsAction.action?app=esi&Init=Yes",
             "https://incites.clarivate.com/#/analysis/0/organization"],
            cwd=str(config.ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"ok": False, "started": False, "already": False, "note": f"浏览器没起来：{e}"}
    return {"ok": True, "started": True, "already": False, "closed": closed,
            "note": "已打开下载数据专用浏览器；首次使用需要在这个窗口里登录 ESI / InCites 一次。"}


def _acq_data_block(period: str):
    """取数前「数据期」校验（票 04）：**明确判定未更新**时拦下，读不到就放行。

    判据来自最近一次 preflight（`state.preflight.data`）：要求期次 vs 网站数据集更新日。
    宁可放行也不要因网络/登录抖动把取数锁死——真正的不发车由前端「开始前检查」先挡一遍。
    """
    st = acquisition.load(period) or {}
    data = (st.get("preflight") or {}).get("data") or {}
    if data.get("ok") is False:
        return JSONResponse({"error": data.get("note") or "这一期的数据还没更新。",
                             "hint": "等网站更新后再取。"}, status_code=409)
    return None


@app.post("/api/periods/{period}/acquisition/start")
@user_route
async def api_acq_start(request: Request, period: str):
    """开始取数（按 9 组下载；完成后自动建当期核对副本）。"""
    blocked = _acq_data_block(period)
    if blocked:
        return blocked
    return _acq_spawn(period, "fetch")


@app.post("/api/periods/{period}/acquisition/open")
@user_route
async def api_acq_open(request: Request, period: str):
    """开新一期（票 05）：登记期次、落一个只含 preflight 的空状态——**不 scan、不取数**。

    期次须是六位 `YYYYMM` 且月份是双月（1/3/5/7/9/11，见 `forecast_select.next_periods`）。
    空壳只占位（`preflight` 全 waiting + `opened` 痕迹），进期次列表；真正的取数仍要点
    「开始取数」走开始前检查（票 04 的数据期校验在那时把关）。**不碰** `out/<期次>/`、台账。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return JSONResponse({"error": "期次要六位数字（如 202611）。",
                             "hint": "格式 YYYYMM。"}, status_code=400)
    if int(period[4:6]) not in (1, 3, 5, 7, 9, 11):
        return JSONResponse({"error": f"{period} 不是双月期次。",
                             "hint": "期次是每年的 1 / 3 / 5 / 7 / 9 / 11 月。"}, status_code=400)
    st = acquisition.load(period) or {}
    st.setdefault("preflight", {"browser": "waiting", "esi": "waiting", "incites": "waiting"})
    st["opened"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": current_user(request) or ""}
    acquisition.write_state(period, st)
    return {"ok": True, "period": period, "opened": st["opened"]}


@app.post("/api/periods/{period}/acquisition/retry")
@user_route
async def api_acq_retry(request: Request, period: str):
    """断组重试：只重下指定的组（body: {"group": "esi-papers"}）。"""
    blocked = _acq_data_block(period)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:                                                # noqa: BLE001
        body = {}
    group = str((body or {}).get("group", "")).strip()
    return _acq_spawn(period, "fetch", ["--groups", group] if group else [])


@app.post("/api/periods/{period}/acquisition/copy")
@user_route
async def api_acq_copy(request: Request, period: str):
    """重建当期核对副本（`out/_acquisition/<期次>/监测表.xlsx`）；主台账不碰。"""
    return _acq_spawn(period, "copy")


@app.post("/api/periods/{period}/acquisition/merge")
@user_route
async def api_acq_merge(request: Request, period: str):
    """把已核对副本并入主台账（写前备份 + 写后五查）。

    并入是**全系统唯一会改台账的动作**，守卫用**数据条件**、不靠界面在哪个视图（2026-10-16 票 02）：
    副本状态不是「待核对」就直接 409 说清原因（已并入 → "无需再并"），不再起一个注定被拒的任务。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    st = acquisition.load(period) or {}
    copy_state = (st.get("copy") or {}).get("state")
    if copy_state != "review":
        if copy_state == "merged":
            merged_at = (st.get("copy") or {}).get("merged_at") or "时间未记"
            msg = f"本期已并入台账（{merged_at}），无需再并。"
        else:
            msg = "还没有本期核对副本——先在下载数据台下载并核对，再并入。"
        return JSONResponse({"error": msg, "state": copy_state}, status_code=409)
    return _acq_spawn(period, "merge", ["--by", current_user(request) or ""])


@app.post("/api/periods/{period}/acquisition/preflight")
@user_route
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


@app.post("/api/periods/{period}/acquisition/stop")
@user_route
async def api_acq_stop(request: Request, period: str):
    """停止正在跑的下载数据任务（2026-10-19 晚，ADR-0010「落地补记」；静态稿已过审）。

    语义是**停止（可续）**、不是终止：已下载的文件保留，「继续下载」只补缺的。
    正在跑 → 连子进程一起停掉后落 `failed`（note 前缀「已停止」）；
    本来就是中断的僵尸 → 如实结清（「上次运行中断：…」）；没有在跑的任务 → 409、不写状态。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    st = acquisition.load(period)
    if st is None:
        return _period_missing()
    lv = _acq_op_liveness(period, st)
    if lv is None:
        return JSONResponse({"error": "现在没有在跑的下载任务。",
                             "hint": "要下载请回到取数核验页点「继续下载」。"}, status_code=409)
    stopped = False
    pid = (st.get("op") or {}).get("pid")
    if lv == "alive" and isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        stopped = _acq_kill_tree(pid)
        time.sleep(0.6)                      # 等进程树退干净，免得它再回写一次状态
    st["op"] = {**(st.get("op") or {}), "state": "failed",
                "note": "已停止（人工）——已下载的文件保留，可继续下载补缺的",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    acquisition.write_state(period, st)
    return {"ok": True, "stopped": stopped, "liveness": lv, "op": st["op"]}


@app.get("/api/periods/{period}/acquisition/datapack")
@user_route
async def api_acq_datapack(request: Request, period: str, source: str = ""):
    """已下载数据打包下载（2026-10-19 馆员需求；rick 定「拆两个包、两个按钮」）。

    `source=esi`    → `数据与复现/ESI数据/<期次>/`（十余 MB）
    `source=incites` → 当期 `incites/<快照>/`（150–300 MB，包里最大头）
    只读打包：不写 out/、不碰台账；zip 落**系统临时目录**、响应结束即删（见 `server/datapack.py`）。
    该来源没下载过 → 404；`source` 非法 → 400。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    if source not in ("esi", "incites"):
        return JSONResponse({"error": "要下哪一路数据？这个包分两路：ESI 和 InCites。",
                             "hint": "地址上带 ?source=esi 或 ?source=incites。"}, status_code=400)
    st = acquisition.load(period) or {}
    snapshot = (st.get("snapshot")
                or acquisition.resolve_snapshot(period, acquisition.INCITES_ROOT_DEFAULT))
    esi_dir = acquisition.ESI_ROOT_DEFAULT / period
    inc_dir = (acquisition.INCITES_ROOT_DEFAULT / snapshot) if snapshot else None
    if source == "esi":
        if not esi_dir.is_dir():
            return JSONResponse({"error": "这一期还没有下载过 ESI 数据。",
                                 "hint": "先在取数核验里下载好，再来打包。"}, status_code=404)
    elif not (inc_dir and inc_dir.is_dir()):
        return JSONResponse({"error": "这一期还没有下载过 InCites 数据。",
                             "hint": "先在取数核验里下载好，再来打包。"}, status_code=404)
    totals = st.get("totals") or {}
    readme = datapack.build_readme(period=period, snapshot=snapshot,
                                   verified=totals.get("verified"),
                                   expected=totals.get("expected"),
                                   esi_dir=esi_dir if source == "esi" else None,
                                   incites_dir=inc_dir if source == "incites" else None)
    import os
    import tempfile
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"wenheng-{source}-data-{period}-{stamp}.zip"   # ASCII 包名（个别浏览器中文名乱码）
    tmp = pathlib.Path(tempfile.gettempdir()) / f".wenheng-datapack-{source}-{period}-{os.getpid()}-{stamp}"
    try:
        await run_in_threadpool(datapack.pack, tmp, period=period,
                                esi_dir=esi_dir if source == "esi" else None,
                                incites_dir=inc_dir if source == "incites" else None,
                                readme=readme)
    except datapack.EmptyPack:
        return JSONResponse({"error": "这一路还没有下载过数据。",
                             "hint": "先在取数核验里下载好，再来打包。"}, status_code=404)
    return FileResponse(tmp, filename=name, media_type="application/zip",
                        background=BackgroundTask(tmp.unlink, missing_ok=True))


@app.get("/api/periods/{period}/artifacts")
@user_route
async def api_period_artifacts(request: Request, period: str):
    """按期次列运行产物；操作员看不到红件三件与运行日志（2026-10-11 角色分级）。"""
    d = resolve_period_dir(period)
    if d is None:
        if not _period_has_data(period):
            return _period_missing()
        return {"period": period, "artifacts": []}      # 还没出稿：产物为空，如实说
    return {"period": d.name,
            "artifacts": _visible_artifacts(jobs.collect_period_artifacts(d.name),
                                            _role_of_request(request))}


@app.get("/api/periods/{period}/download/{key}")
@user_route
async def api_period_download(request: Request, period: str, key: str):
    """期次产物下载；操作员只读，红件/日志包类键仅管理员可下载。"""
    guard = _operator_download_guard(_role_of_request(request), key)
    if guard:
        return guard
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
@user_route
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
@user_route
async def api_forecast_choice_get(request: Request, period: str):
    """读回请求期次的预测模型选择，仅管理员可读。

    `applied`＝**上次出稿实际用的选择**（当期产物的出稿快照，只读）——前端拿它和已保存的
    `choice` 比值：不一致＝改选还没进报告（2026-10-16 加，rick 要求说清「报告还是旧的」）；
    没有该文件（没出过稿的老期次）→ null，前端不显示提示。

    ⚠️ 这条是 **GET**（2026-09-24 修）：此前被误挂成 `@app.post`，又注册在下面的
    `api_route(methods=["GET","POST"])` 之前——FastAPI 按注册顺序匹配，POST 会被这条
    抢先接走，导致「保存选择」永远只读回、不落盘。改装饰器前先想一遍注册顺序。"""
    if not _forecast_choice_period_is_safe(period):
        return JSONResponse({"error": "期次格式无效"}, status_code=400)
    entry = forecast_choice.read_entry(
        period, choices_dir=config.FORECAST_CHOICES_DIR, out_dir=config.OUT_DIR)
    return {"period": period, "choice": entry["choice"],
            "by": entry["by"], "at": entry["at"],
            "applied": forecast_choice.read_applied(period, out_dir=config.OUT_DIR)}


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
@user_route
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
    for key in ("top2_not_entered", "not_entered"):
        for item in facts.get(key) or []:
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
@user_route
async def api_period_facts(request: Request, period: str):
    """读数带数据：overview_facts.json + meta.json 摘要，仅管理员可读。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    if not (d / "overview_facts.json").exists():
        return JSONResponse({"error": "该期次尚无 overview_facts.json", "hint": "请先跑一次生成流水线"}, status_code=404)
    facts = artifacts.read_facts(d)
    meta = artifacts.read_meta(d)
    facts = _localize_facts(facts)
    # 顶尖论文历期序列（纯序列化 meta；空值＝未来期空列，滤掉）——契约 #19
    trend = {k: v for k, v in (meta.get("top_total_by_period") or {}).items()
             if isinstance(v, (int, float))}
    return {
        "period": meta.get("period_current", ""),
        "period_prev": meta.get("period_prev", ""),
        "facts": facts,
        "trend": trend,
        "assertions": artifacts.assertion_counts(meta),
        "missing": meta.get("missing", []),
    }


@app.get("/api/periods/{period}/water")
@user_route
async def api_period_water(request: Request, period: str):
    """学科水位（只读）：从 matrix.json 的「云大」列取接近度，给首屏水尺。

    `prox`＝被引 ÷ 1% 阈值的百分数点值（100＝刚好到线）；`state`：
    `in`＝已在 ESI 前 1% 榜内、`near`≥80%、`far`<80%。只读产物，不重算口径。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    return {"period": period, **period_facts.water_rows(d / "matrix.json")}


@app.get("/api/sandbox/heal")
@user_route
async def api_sandbox_heal(request: Request):                      # noqa: ARG001
    """自愈沙盘故事卡（只读）：读 tmp/_heal_sandbox/story.json。

    沙盘只碰副本；原件与脏件哈希由 tools/heal_sandbox.py 记录。没跑过就
    返回 available=false，界面给一条「先跑哪条命令」，不编故事。
    """
    path = pathlib.Path(__file__).resolve().parent.parent / "tmp" / "_heal_sandbox" / "story.json"
    if not path.exists():
        return {"available": False, "hint": "先跑一次自愈沙盘工具，刷新本页"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "hint": "沙盘故事卡读不出来，重跑一次自愈沙盘工具"}
    return {"available": True, **data}


@app.get("/api/sandbox/migrate")
@user_route
async def api_sandbox_migrate(request: Request):                    # noqa: ARG001
    """换馆沙盘故事卡（只读）：读 tmp/_migration_sandbox/readiness.json。"""
    path = pathlib.Path(__file__).resolve().parent.parent / "tmp" / "_migration_sandbox" / "readiness.json"
    if not path.exists():
        return {"available": False, "hint": "先跑一次换馆沙盘工具，刷新本页"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "hint": "换馆故事卡读不出来，重跑一次换馆沙盘工具"}
    return {"available": True, **data}


@app.get("/api/periods/{period}/workbench")
@user_route
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
@user_route
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
@user_route
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

    转不了（不在仓库内 / 跨平台遗留的 Windows 路径）就只回文件名。
    2026-10-13 实踩：Linux 上读到历史任务记录里的 `C:\\...` 时，`Path.resolve()`
    把它当**相对名**解析，`relative_to(ROOT)` 反而"成功"，绝对路径就漏进了 archive
    响应（e2e「archive 不回绝对路径」在服务器上 FAIL）——带盘符且不在本仓下的一律
    只回文件名。
    """
    s = str(p)
    if pathlib.PureWindowsPath(s).drive and not s.startswith(str(config.ROOT)):
        return s.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        return str(pathlib.Path(s).resolve().relative_to(config.ROOT)).replace("\\", "/")
    except (ValueError, OSError, TypeError):
        return s.replace("\\", "/").rsplit("/", 1)[-1]


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
@user_route
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
    role = _role_of_request(request)
    artifacts = jobs.collect_period_artifacts(d.name)
    if role != "admin":
        artifacts = _visible_artifacts(artifacts, role)
    view = archive.build(d, job=target, artifacts=artifacts)
    view.pop("out_dir", None)                                  # 不回绝对路径
    view.pop("progress_path", None)
    # job/stats/run_log 里还有 input/progress/console 等本机路径：转仓库相对
    _path_keys = ("input", "progress", "console", "run_dir", "out_dir")
    view["job"] = _sanitize_paths(view.get("job"), _path_keys)
    view["stats"] = _sanitize_paths(view.get("stats"), _path_keys)
    view["run_log"] = _sanitize_paths(view.get("run_log"), _path_keys)
    view["download_base"] = f"/p/{q}"
    # 操作员只读证据面，但红件/运行日志/日志包仍按 2026-10-11 政策只给管理员。
    # 不给链接，避免页面上出现一点就 403 的按钮；决定走 visibility。
    view["logpack_url"] = (f"/p/{q}/download/{view['logpack']['key']}"
                           if visibility.allowed(role, "logpack", "download") else "")
    return view


@app.get("/api/periods/{period}/trace")
@user_route
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
    ledger = _find_ledger()
    if ledger is None:
        empty = {k: 0 for k in _TRACE_CATS}
        return {"period": d.name, "ledger": "", "ledger_ok": False,
                "ledger_error": f"本地未找到动态监测表 input/{ledger_mod.LEDGER_NAME}",
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
@user_route
async def api_period_redslots(request: Request, period: str,
                              limit: int = 50, offset: int = 0):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    rows = []
    for s in artifacts.read_slots(d):
        loc = str(s.get("location", ""))
        src = str(s.get("source", ""))
        group = loc.split("/")[0] if "/" in loc else loc
        if loc.startswith("T01/r"):
            group = "大表数值"
        elif loc.startswith("T0") or loc.startswith("T1"):
            group = loc.split("/")[0]
        rows.append({"group": group, "label": loc,
                     "old": artifacts.slot_text(s, "old"),
                     "new": artifacts.slot_text(s, "new"),
                     "src": src, "kind": artifacts.slot_kind(s)})
    page = _paginate(rows, limit, offset)
    page["count"] = page["total"]
    return page


@app.get("/api/periods/{period}/outline")
@user_route
async def api_period_outline(request: Request, period: str):
    """②选材 · 报告大纲（**只读**，最省版）。

    只由产物推导：章节 + 每节的就绪态 / 数据来源 / 槽位数（按 `red_slots.json` 的 location 分组）。
    **不写任何文件、不改出稿**——这一屏只记"本轮办哪些节"，出稿一律全出、母版不动。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    locs = [str(s.get("location", "")) for s in artifacts.read_slots(d)]

    def has(name: str) -> bool:
        return (d / name).exists()

    def n_tables(*tids: str) -> int:
        pfx = tuple(f"{t}/" for t in tids)
        return sum(1 for x in locs if x.startswith(pfx))

    def n_body(*keys: str) -> int:
        want = {"正文/" + k for k in keys}
        return sum(1 for x in locs if x in want)

    pred = [f"T{i:02d}" for i in range(3, 19)]          # T03–T18：预测章 16 张学科表
    # 正文槽位按章归位（图/表也算，唯「图片行距」是版式、不归章）
    s1 = n_body("p1", "p2", "p3", "p4", "1%接近度图（新）", "1‰潜力图", "排名情况图（第4期格式·带数据表）")
    s2 = n_tables("T01", "T20") + n_body(
        "trend", "situation_head", "situation", "table2_title", "发展趋势图（第4期格式·带数据表）")
    s3 = n_tables(*pred, "T17") + n_body("forecast_p1", "forecast_p2")
    s4 = n_tables("T19") + n_body("province_p")
    s5 = n_body("top_section", "顶尖论文·学科分布", "顶尖论文·年代分布",
                "学院贡献度饼图（被引频次）", "学院贡献度饼图（发文量）",
                "学院顶尖论文发文量与被引频次统计表")
    # 附录《我校顶尖论文清单》：由馆员清单另填（不进红件槽位）——看清单在不在
    inv = []
    for base in (d.parent / "_acquisition" / d.name, config.ROOT / "数据与复现"):
        try:
            inv += [p.name for p in base.glob(f"*{d.name}*清单*")]
        except OSError:
            pass
    return {
        "period": d.name,
        # 版式类槽位（如「图片行距」）不归章——单列出来，别让各节相加对不上总数
        "slotsTotal": len(locs),
        "slotsUnassigned": len(locs) - (s1 + s2 + s3 + s4 + s5),
        "sections": [
            {"id": "s0", "label": "封面 · 名词解释", "ready": True,
             "source": "母版固定（名词解释不填）", "slots": 0},
            {"id": "s1", "label": "一 概述", "ready": has("overview_facts.json"),
             "source": "overview_facts.json · sentences.py 句骨架", "slots": s1},
            {"id": "s2", "label": "二 我校学科发展情况", "ready": has("table2.csv"),
             "source": "table2.csv · matrix.json", "slots": s2,
             "subs": [{"id": "s2.t1", "label": "大表数值", "ready": has("table2.csv"),
                       "slots": n_tables("T01")},
                      {"id": "s2.t20", "label": "学科×高校矩阵", "ready": has("matrix.json"),
                       "slots": n_tables("T20")},
                      {"id": "s2.trend", "label": "发展趋势 · 态势统计", "ready": has("matrix.json"),
                       "slots": n_body("trend", "situation_head", "situation")}]},
            {"id": "s3", "label": "三 我校潜力学科趋势预测", "ready": has("forecast_charts.json"),
             "source": "forecast_charts.json · 预测选模", "slots": s3,
             "subs": [{"id": "s3.tabs", "label": "学科表 ×16", "ready": has("forecast_charts.json"),
                       "slots": n_tables(*pred, "T17")},
                      {"id": "s3.charts", "label": "模型预测图 ×4 · 说明句", "ready": has("forecast_charts.json"),
                       "slots": n_body("forecast_p1", "forecast_p2")}]},
            {"id": "s4", "label": "四 云南省主要高校学科发展基本情况", "ready": has("province.json"),
             "source": "college_stats.json · province.json", "slots": s4},
            {"id": "s5", "label": "五 我校顶尖论文清单（附录）", "ready": bool(inv),
             "source": "馆员清单（本科目另填）", "slots": s5},
        ],
    }


@app.get("/api/periods/{period}/collation")
@user_route
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
@user_route
async def api_period_charts_json(request: Request, period: str,
                                 limit: int = 50, offset: int = 0):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    q = urllib.parse.quote(d.name)
    labels = _forecast_chart_labels(d)
    items = []
    for it in jobs.list_charts(d):
        items.append({"name": it["name"], "group": it["group"],
                      "label": labels.get(it["name"], ""),
                      "url": f"/p/{q}/chart/" + urllib.parse.quote(it["rel"])})
    return _paginate(items, limit, offset)


def _forecast_chart_labels(period_dir):
    """预测图的读得懂的名字：`forecast_3_cites.png` → 「免疫学 · 被引频次与阈值（预测图）」。

    源＝本期 `forecast_charts.json`（出图时写定）；缺文件/字段就留空，不猜（前端回落文件名）。
    2026-10-16 加：未进 1% 的全部学科都出图后，图册里再显示裸文件名就太难认了。
    """
    mp = pathlib.Path(period_dir) / "forecast_charts.json"
    try:
        charts = json.loads(mp.read_text(encoding="utf-8")).get("charts", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    labels = {}
    for c in charts:
        if not isinstance(c, dict):
            continue
        png, subject, kind = c.get("png"), c.get("subject"), c.get("kind")
        if isinstance(png, str) and isinstance(subject, str) and kind in ("cites", "rank"):
            metric = "被引频次与阈值" if kind == "cites" else "国内排名与机构数"
            labels[png] = f"{subject} · {metric}（预测图）"
    return labels


@app.get("/api/ledger/sheets")
@admin_route
async def api_ledger_sheets(request: Request, period: str = ""):
    import openpyxl                                        # noqa: PLC0415
    # 2026-10-13 起只有一份动态监测表（母本，含全部期次）；period 参数保留仅为 API 兼容。
    lp = ledger_mod.runtime_path(config.ROOT)
    if not lp.exists():
        return JSONResponse({"error": "动态监测表不在",
                             "hint": f"请把母本放到 input/{ledger_mod.LEDGER_NAME}"},
                            status_code=404)
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
@user_route
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
@user_route
async def api_ai_capabilities(request: Request):
    """能力开关表（契约 #28）：分析台「问文衡」的开关读它；纯读配置，无副作用。"""
    import ai                                                     # noqa: PLC0415
    rows = [c.as_dict() for c in
            ai.capabilities(config.role_of(current_user(request) or ""))]
    return {"capabilities": rows}


@app.get("/api/periods/{period}/ai-calls")
@user_route
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
                "label": r.get("label") or "",
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


#: 会话库路径（票 11）：生产由 lifespan 装配（`out/_sessions/sessions.sqlite`）；
#: None＝未装配——直调处理函数的测试不落库、绝不碰真数据；测试 monkeypatch 注入 tmp。
SESSION_DB_PATH = None


@app.post("/api/dialog/turn")
@user_route
async def api_dialog_turn(request: Request):
    """对话前门一轮（契约 #33，票 01–07）：一句话 → 路由（两意图）+ 应答 + 槽位 + 盘点。

    请求 `{text, slots:{period,intent}, history, session}`（slots/history/session 可省；
    期次形状非法按未设处理，不猜）。
    应答＝Answer 字段面 + `kind`（`report/query/proceed/unclear`/空：票 07 路由）
    + `slots`（本轮解析到的才覆盖，其余不变）+ 盘点三件：`verdict`（unpublished/missing/ready/空）、
    `inventory`（四件清单）、`actions`（改做/去取数台/去核对/覆盖重出/先等等）
    + `run`（出稿意图）+ `answer`（查数据：qa 能力的 Answer；其余为 null）
    + `session_id`（票 11：本回合的会话 id——续聊把它回传）。
    **会话（票 11）**：带 `session` → 校验归属、历史从会话库读（截断口径与现状一致）、
    回合追加进库；无 → 建新会话；他人会话 403、不存在 404。
    **两意图**：写报告与现有链路不变；查数据由**本路由**按意图调 `ai.run("qa", …)`
    ——对话能力只做路由，模型出口仍只有 `src/ai` 一处。
    解析与盘点走 `src/ai` 的 dialog 能力口（规则版离线可跑）；
    每轮对话的留痕复用 `ai_calls`（不新开账本）。空话 400；非 admin 401/403。
    """
    body = await request.json()
    payload, status = await _dialog_turn_impl(body, current_user(request) or "")
    if status == 200:
        return payload
    return JSONResponse(payload, status_code=status)


async def _dialog_turn_impl(body: dict, user: str, progress=None) -> tuple:
    """对话前门一轮的**共享内核**（同步口 #33 / 流口 #37 共用；2026-10-14 票 12）。

    返回 `(payload, status)`；`progress`（可选）在真实编排点收阶段码：
    「理解」（进对话能力前）/「查数」（进问答能力前）——规则模式如实少事件，不演。
    """
    def _prog(code):
        if progress is not None:
            try:
                progress(code)
            except Exception:                                     # noqa: BLE001
                pass

    text = str(body.get("text") or "").strip()
    if not text:
        return {"error": "请先说一句话"}, 400
    slots = body.get("slots") if isinstance(body.get("slots"), dict) else {}
    period = str(slots.get("period") or "").strip()
    if period and not re.fullmatch(r"\d{6}", period):
        period = ""                                   # 形状不合法就丢弃，不猜
    intent = str(slots.get("intent") or "").strip()[:20]
    # 会话（票 11）：有 session → 归属校验 + 历史从库读；无 → 本回合结束时建新会话。
    session_id = str(body.get("session") or "").strip()
    stored_turns = None
    if session_id:
        if SESSION_DB_PATH is None:
            return {"error": "会话不存在"}, 404
        try:
            stored = await run_in_threadpool(session_store.load,
                                             SESSION_DB_PATH, session_id, user)
        except (ValueError, KeyError):
            return {"error": "会话不存在"}, 404
        except PermissionError:
            return {"error": "会话不属于当前用户"}, 403
        stored_turns = stored["turns"]
    # 对话上文（2026-10-12 rick 实问「这是几月的」）：追问要靠上文解指代——
    # 只收 me/wh 的文本，条数与长度都截断（外发面另有 6000 字符上限兜底）。
    # 带会话时改从库读（票 11），口径同上：最近 8 条、每条 200 字。
    history = []
    if stored_turns is not None:
        for t in stored_turns[-8:]:
            snippet = str(t.get("text") or "").strip()[:200]
            if snippet:
                history.append({"who": t["who"], "text": snippet})
    else:
        for item in (body.get("history") if isinstance(body.get("history"), list) else [])[-8:]:
            if not isinstance(item, dict):
                continue
            who = "me" if item.get("who") == "me" else "wh"
            snippet = str(item.get("text") or "").strip()[:200]
            if snippet:
                history.append({"who": who, "text": snippet})
    # 「最新的」解析（2026-10-13，票 10）：注入已知期次（降序）——「最近有效期次」
    # 与「本期」同源口径（taskview.known_periods：母本有效期次 ∪ out ∪ 取数在途）。
    import taskview                                               # noqa: PLC0415
    periods = await run_in_threadpool(taskview.known_periods)
    import ai                                                     # noqa: PLC0415
    actor = config.role_of(user)
    # 2026-10-12：操作员也有出报告/审批——报告流程两种角色一致（readonly 注入已取消）。
    _prog("理解")                                                 # 票 12：进对话能力前
    ans = await run_in_threadpool(ai.run, "dialog", period,
                                  payload={"text": text, "history": history,
                                           "periods": periods}, actor=actor)
    if ans.mode in ("closed", "denied", "unavailable"):
        r = _answer_response(ans)
        return json.loads(r.body), r.status_code
    turn = ans.data or {}
    resp = ans.as_dict()
    resp["kind"] = str(turn.get("kind") or "")
    resp["slots"] = {"period": str(turn.get("period") or period),
                     "intent": str(turn.get("intent") or intent)}
    resp["verdict"] = str(turn.get("verdict") or "")
    resp["inventory"] = turn.get("inventory") if isinstance(turn.get("inventory"), dict) else None
    resp["actions"] = turn.get("actions") if isinstance(turn.get("actions"), list) else []
    # 出稿意图（票 03）：{period, auto}——auto=False 表示产物已在、先问一次；
    # 真正的开跑由前端拿它调既有开跑口（对话只做指挥，不替人按按钮）。
    resp["run"] = turn.get("run") if isinstance(turn.get("run"), dict) else None
    # 查数据（票 07）：dialog 只判意图；回答由**服务器**按意图调 qa 能力。
    # 没产物先提示出稿；qa 关闭照旧说「已关闭」——都在聊天里说清楚，不 404/409 摔出去。
    resp["answer"] = None
    if resp["kind"] == "query":
        target = resp["slots"]["period"]
        if target:
            if resolve_period_dir(target) is None:
                resp["text"] = "这一期还没有可用产物——先出稿，才有得查。"
            else:
                _prog("查数")                                     # 票 12：进问答能力前
                qa_ans = await run_in_threadpool(
                    ai.run, "qa", target,
                    payload={"question": text, "history": history}, actor=actor)
                resp["answer"] = qa_ans.as_dict()
    # 会话落库（票 11）：回合完成后追加「用户话＋文衡回复文本」，槽位整存；
    # 无 session 时此刻建新会话。落库失败不挡这一轮（聊天照常，只是这轮不持久化）。
    if SESSION_DB_PATH is not None:
        try:
            if not session_id:
                session_id = await run_in_threadpool(
                    session_store.create, SESSION_DB_PATH, user)
            await run_in_threadpool(session_store.append, SESSION_DB_PATH,
                                    session_id, "me", text, user=user)
            reply = str(resp.get("text") or "").strip()
            if not reply and isinstance(resp.get("answer"), dict):
                reply = str(resp["answer"].get("text") or "").strip()
            if reply:
                await run_in_threadpool(session_store.append, SESSION_DB_PATH,
                                        session_id, "wh", reply, user=user)
            await run_in_threadpool(session_store.save_slots, SESSION_DB_PATH,
                                    session_id, resp["slots"], user=user)
        except Exception:                                     # noqa: BLE001
            session_id = ""
    resp["session_id"] = session_id
    return resp, 200


#: 阶段文案（票 12）：阶段码 → 人话。规则模式如实少事件（不演）。
_STAGE_TEXT = {
    "理解": "正在理解这句话…",
    "查数": "正在查台账…",
    "model:dialog": "正在理解这句话…（模型兜底）",
    "model:qa-plan": "正在规划查哪些数…",
    "model:qa": "正在写答案…",
    "model:polish": "正在润色…",
    "model:qa-polish": "正在润色…",
}


@app.post("/api/dialog/turn/stream")
@user_route
async def api_dialog_turn_stream(request: Request):
    """对话前门一轮·**阶段进度流**（契约 #37，2026-10-14 票 12）：NDJSON 一行一事件。

    `stage×N → done(payload)`（payload 与 #33 响应同形状）；失败 → `error`（不断流）。
    **不流正文**——数字必须先过「数字盾」；阶段发生在真实节点（不造假进度）。
    请求体与 #33 完全一致。"""
    body = await request.json()
    user = current_user(request) or ""

    async def gen():
        q: asyncio.Queue = asyncio.Queue()
        result: dict = {}
        loop = asyncio.get_running_loop()

        def _put(code):
            # 进度可能来自线程池线程（_attempt 在 run_in_threadpool 里跑）——必须跨线程投递
            loop.call_soon_threadsafe(q.put_nowait, ("stage", code))

        async def _worker():
            try:
                import ai                                         # noqa: PLC0415
                with ai.using(progress=_put):
                    result["payload"], result["status"] = await _dialog_turn_impl(
                        body, user, progress=_put)
            except Exception as e:                                # noqa: BLE001
                result["error"] = f"{type(e).__name__}: {e}"
            finally:
                q.put_nowait(("end", None))

        task = asyncio.create_task(_worker())
        try:
            while True:
                kind, item = await q.get()
                if kind == "end":
                    break
                yield json.dumps({"event": "stage", "stage": item,
                                  "text": _STAGE_TEXT.get(item, "处理中…")},
                                 ensure_ascii=False) + "\n"
        finally:
            await task
        if result.get("status", 200) != 200 or "payload" not in result:
            payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
            yield json.dumps({"event": "error",
                              "error": payload.get("error") or result.get("error") or "未知错误",
                              "status": int(result.get("status") or 500)},
                             ensure_ascii=False) + "\n"
        else:
            yield json.dumps({"event": "done", "payload": result["payload"]},
                             ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/dialog/session/{session_id}")
@user_route
async def api_dialog_session(request: Request, session_id: str):
    """会话回读（契约 #36，票 11）：刷新/换设备带 URL `?s=<id>` 即恢复。

    仅 owner：不存在 404、他人会话 403（与既有口径一致）；形状非法按不存在处理。
    """
    if SESSION_DB_PATH is None:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    user = current_user(request) or ""
    try:
        data = await run_in_threadpool(session_store.load, SESSION_DB_PATH, session_id, user)
    except (ValueError, KeyError):
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "会话不属于当前用户"}, status_code=403)
    return {"id": data["id"], "slots": data["slots"], "turns": data["turns"]}


@app.get("/api/dialog/home")
@user_route
async def api_dialog_home(request: Request):                      # noqa: ARG001
    """对话前门·空态「本期任务」（契约 #35，票 06）：三步状态从既有产物判，只读不新算。

    本期＝最新一个有内容的期次（台账有效期次 ∪ 出过稿的产物 ∪ 取数四件已齐）；三步全成且已签发 → 顺延下一期。
    签发状态在 server 层核实（`src/taskview` 不 import server）；扫描拿不到 → 空形状
    （界面退回普通问候，不编）。
    """
    import taskview                                               # noqa: PLC0415

    def _status(period: str) -> str:
        return approval.status(config.OUT_DIR / period)

    data = await run_in_threadpool(taskview.scan, status=_status)
    if data is None:
        return {"period": "", "released": False, "n_missing": 0,
                "steps": [], "stuck": "", "prev": None}
    return data


@app.get("/api/forecast/board")
@user_route
async def api_forecast_board(request: Request, period: str = ""):
    """预测台「学科板」（契约 #20）—— 解析预测选模与过线.md 的两张表。

    不重算；缺文件时返回空板 + note（不 500）。`?period=` 可指定，
    默认取最新有该文件的期次。
    """
    if period and resolve_period_dir(period) is None:
        return _period_missing()
    return forecasting.board_context(period or None)


@app.get("/api/periods/{period}/flexible")
@user_route
async def api_period_flexible(request: Request, period: str, intent: str = "",
                              variant: str = ""):
    """灵活报告 JSON（契约 #21①）：列已生成 + 当前稿的 body_html + 下拉清单。

    body_html 用**后端同一个 mdview.render**（图已指向
    `/p/<期次>/flexible/chart/<intent>/<name>`）——前端不引 md 渲染器。
    `variant=rule`：看写作位留底的规则稿（`report.rule.md`）。
    未生成过的期次返回空列表 + cur=null + body_html=""，不 500。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    ctx = _flex_ctx(d, intent or None, variant=variant or None)
    return {
        "period": ctx["period_dir"],
        "intents": ctx["intents"],
        "reports": [{"intent": r["intent"], "title": r["title"], "meta": r["meta"],
                     "has_rule": bool(r.get("has_rule"))}
                    for r in ctx["reports"]],
        "cur": (ctx["cur"] or {}).get("intent") or None,
        "variant": ctx.get("variant") or "",
        "has_rule": bool(ctx.get("has_rule")),
        "disciplines": ctx.get("disciplines") or [],
        "write": ctx.get("write") or {"enabled": False, "available": False},
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
    peers = body.get("peers")
    if isinstance(peers, str):
        peers = peers.split(",")
    peers = [str(x).strip() for x in (peers or []) if str(x).strip()]
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}",
                             "hint": "可选：" + "、".join(flex_planner.INTENTS)}, status_code=400)
    import flexible.report as flex_report                           # noqa: PLC0415
    t0 = time.time()
    try:
        r = flex_report.generate(d, intent, disc=disc, peers=peers)
    except ValueError as e:
        return JSONResponse({"error": str(e)[:200],
                             "hint": "学科请从名单中选择（支持中文名）"}, status_code=400)
    except Exception as e:                                          # noqa: BLE001
        return JSONResponse({"error": f"生成失败：{type(e).__name__}", "hint": str(e)[:200]}, status_code=500)
    return {"ok": True, "intent": intent, "elapsed": round(time.time() - t0, 1),
            "n_charts": r.get("n_charts"), "backend": (r.get("plan") or {}).get("backend", "")}


def _flex_stream_line(ev: dict, d, intent: str) -> str:
    """流式事件 → 一行 NDJSON。section 的正文 md 在此渲成 html（图指服务端路由）。"""
    if ev.get("event") == "section":
        import re                                                    # noqa: PLC0415
        from flexible import mdview                                  # noqa: PLC0415
        names = [p.split("/")[-1]
                 for p in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", ev.get("body") or "")]
        imgmap = {n: f"/p/{d.name}/flexible/chart/{intent}/"
                     + urllib.parse.quote(n) for n in names}
        html = mdview.render(ev["body"], img_map=imgmap)
        return json.dumps({"event": "section", "title": ev["title"], "html": html},
                          ensure_ascii=False) + "\n"
    body = {k: v for k, v in ev.items() if k != "event"}
    return json.dumps({"event": ev.get("event"), **body},
                      ensure_ascii=False, default=str) + "\n"


#: 正在跑的流式出稿（run 令牌 → 停止事件）。停止键（契约 #21⑤）用；
#: 跑完/出错/停掉即从表里摘除——不在的令牌＝没有可停的。
_flex_stops: dict[str, threading.Event] = {}


@app.post("/api/periods/{period}/flexible/stream")
@user_route
async def api_period_flexible_stream(request: Request, period: str):
    """流式生成（契约 #21③）：一行一个事件 `status → plan → section×N → done/error/stopped`。

    事件发生在**真实节点**（规划完成、每节完成），不做假进度；
    前端用 `fetch` 逐行读取（后端不引 SSE 库，NDJSON 更省）。
    首行（status）带 `run` 令牌——停止键（#21⑤）拿它喊停。

    2026-10-12（rick 定案）：出报告对操作员开放——本口与 `/stop` 从 admin 放开
    （对话前门两段式的第一段；取数/回滚/润色等仍 admin）。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    intent = str(body.get("intent") or "").strip()
    disc = str(body.get("disc") or "").strip() or None
    peers = body.get("peers")
    if isinstance(peers, str):
        peers = peers.split(",")
    peers = [str(x).strip() for x in (peers or []) if str(x).strip()]
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}",
                             "hint": "可选：" + "、".join(flex_planner.INTENTS)}, status_code=400)
    import flexible.report as flex_report                           # noqa: PLC0415

    token = uuid.uuid4().hex[:12]
    stop = threading.Event()
    _flex_stops[token] = stop

    def gen():
        try:
            first = True
            for ev in flex_report.generate_stream(d, intent, disc=disc,
                                                  should_stop=stop.is_set,
                                                  peers=peers):
                line = _flex_stream_line(ev, d, intent)
                if first:                                # 首行带令牌（停止键要用）
                    rec = json.loads(line)
                    rec["run"] = token
                    line = json.dumps(rec, ensure_ascii=False) + "\n"
                    first = False
                yield line
        finally:
            _flex_stops.pop(token, None)

    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/periods/{period}/flexible/stop")
@user_route
async def api_period_flexible_stop(request: Request, period: str):   # noqa: ARG001
    """停止出稿（契约 #21⑤）：对正在流式生成的那一次喊停。

    下一次事件点收手，终态事件 `stopped` 从**原流**里送出（不落产物）；
    流已结束/令牌不在 → `{ok: false}` + 人话（不是错误）。
    2026-10-12：与 `/stream` 同档——操作员出报告要能停（rick 定案）。
    """
    body = await request.json()
    token = str(body.get("run") or "")
    ev = _flex_stops.get(token)
    if ev is None:
        return {"ok": False, "error": "这次出稿已经结束（或找不到），没有可停的。"}
    ev.set()
    return {"ok": True}


@app.post("/api/periods/{period}/flexible/polish")
@admin_route
async def api_period_flexible_polish(request: Request, period: str):
    """AI 润色（写作位，契约 #21④）：按已出稿的规划重出稿，只重写叙述段。

    数字、图表、来源链一律不变；任何段失败都保留规则稿。首次润色时把当前
    规则稿留底为 `report.rule.md`（界面可对照）。写作位没开或没配云 → 409。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    intent = str(body.get("intent") or "").strip()
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}"}, status_code=400)
    plan_path = d / "flexible" / intent / "flex_plan.json"
    if not plan_path.is_file():
        return JSONResponse({"error": "还没有这份稿，先「生成分析稿」再来润色。"},
                            status_code=400)
    from ai import _writing                                         # noqa: PLC0415
    if not _writing.writing_state("write").available:
        return JSONResponse({"error": "写作位未开启（部署开关未设或未配云端模型）。"},
                            status_code=409)
    import flexible.report as flex_report                           # noqa: PLC0415
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        plan = None
    t0 = time.time()
    try:
        r = flex_report.generate(d, intent, plan=plan, write=True)
    except Exception as e:                                           # noqa: BLE001
        return JSONResponse({"error": f"润色失败：{type(e).__name__}",
                             "hint": str(e)[:200]}, status_code=500)
    return {"ok": True, "intent": intent, "elapsed": round(time.time() - t0, 1),
            "mode": r.get("mode"), "write": r.get("write"),
            "backend": (r.get("plan") or {}).get("backend", "")}


@app.get("/api/forecast/meta")
@user_route
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


@app.get("/api/jobs/{job_id}")
@user_route
async def api_job(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    # 契约 §2.3：失败态给结构化的「缺什么」，不让前端解析断言文本
    if job.get("missing"):
        job["ok"] = False
    return job


@app.get("/api/jobs/{job_id}/artifacts")
@user_route
async def api_artifacts(request: Request, job_id: str):
    job = jobs.read_job(job_id)
    if not job:
        return _job_missing()
    return {"job": job,
            "artifacts": _visible_artifacts(jobs.collect_artifacts(job),
                                            _role_of_request(request))}


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


# ---------------- 下载 / 二维码 ----------------

@app.get("/jobs/{job_id}/download/{key}")
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
