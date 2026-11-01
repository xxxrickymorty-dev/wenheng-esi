# -*- coding: utf-8 -*-
"""pages 分册：登录/登出与旧页 302（20261101 C8 路由分册，从 server/app.py 迁入）。

旧站页面已逐页下线（ADR-0002）：全部 302 到新工作区 `/app/`，落点表在
`config.LEGACY_REDIRECTS`（tests/test_stack_contract.py 钉着这张表）。登录是
最后一条 no-JS 表单写路径（303 重定向）。

补丁锚点：`_login_fails` 单例与 `resolve_period_dir` 在装配壳（server.app），
经 `web_common` 的访问口在请求时现取——测试 monkeypatch 仍生效（见 web_common
模块 docstring）。
"""
import time
import urllib.parse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import config, jobs
from ..web_common import (current_user, login_fails, resolve_period_dir, templates)

router = APIRouter()


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


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, err: str = ""):
    return templates.TemplateResponse(
        request, "login.html",
        {"request": request, "err": err, "hint": config.SHOW_HINT,
         "show_hint_user": config.ADMIN_USER if config.SHOW_HINT else ""})


@router.post("/login")
async def do_login(request: Request, username: str = Form(""), password: str = Form("")):
    ip = request.client.host if request.client else "?"
    rec = login_fails().setdefault(ip, {"n": 0, "until": 0.0})
    if rec["until"] > time.time():
        return RedirectResponse("/login?err=尝试过于频繁，请稍后再试", status_code=303)
    if check_credentials(username, password):
        request.session["user"] = username
        login_fails().pop(ip, None)
        # 2026-10-12（rick）：两种角色都先落到**陈列馆首页**（看 → 问 → 做 三面模型），
        # 从陈列馆的「问文衡 →」进对话页，再从对话页「去生成台」进工作台。
        return RedirectResponse("/app/shelf/", status_code=303)
    rec["n"] += 1
    if rec["n"] >= 5:
        rec.update({"n": 0, "until": time.time() + 60})
    return RedirectResponse("/login?err=账号或密码不正确", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


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


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, err: str = "", signed: str = "",
               revoked: str = "", rebuilt: str = "", saved: str = "", p: str = ""):
    """旧首页已下线（ADR-0002 阶段 2）—— 302 到新工作区系统。

    旧工作台（workbench.html）与控制台入口都在 /app/。
    保留函数签名：老链接可能带 ?p= / ?rebuilt= 等参数，接下来丢弃即可。
    """
    return _legacy_redirect(request, "/")


@router.get("/run", response_class=HTMLResponse)
async def run_page(request: Request):
    """旧控制台已下线（ADR-0002 阶段 2）—— 302 到新工作区系统。"""
    return _legacy_redirect(request, "/run")


@router.get("/forecast", response_class=HTMLResponse)
async def forecast_page(request: Request):
    """老预测页已下线（ADR-0002 阶段 2）—— 302 到新预测台 `?view=forecast`。

    数据面（`/api/forecast/meta`、`/api/forecast/run`）不变，仍由
    `forecasting.page_context()` 供给。
    """
    return _legacy_redirect(request, "/forecast")


@router.get("/p/{period}", response_class=HTMLResponse)
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


@router.get("/p/{period}/redslots", response_class=HTMLResponse)
async def period_redslots(request: Request, period: str):
    """老红件清单页已下线（ADR-0002 阶段 2）—— 302 到新工作区。"""
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/redslots" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@router.get("/p/{period}/trace", response_class=HTMLResponse)
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


@router.get("/p/{period}/charts", response_class=HTMLResponse)
async def period_charts(request: Request, period: str):
    """老图册页已下线（ADR-0002 阶段 2）—— 302 到新工作区。"""
    gate = _legacy_login_gate(request)
    if gate:
        return gate
    d = resolve_period_dir(period)
    key = "/p/{period}/charts" if d is not None else "/"
    return _legacy_redirect(request, key,
                            period=urllib.parse.quote(d.name) if d is not None else "")


@router.get("/p/{period}/archive", response_class=HTMLResponse)
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


@router.get("/p/{period}/flexible", response_class=HTMLResponse)
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


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    """旧任务页已下线（ADR-0002 阶段 2）—— 302 到新工作区系统。"""
    return _legacy_redirect(request, "/jobs/{job_id}")


@router.get("/jobs/{job_id}/redslots", response_class=HTMLResponse)
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


@router.get("/jobs/{job_id}/charts", response_class=HTMLResponse)
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


@router.get("/jobs/{job_id}/archive", response_class=HTMLResponse)
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


@router.get("/jobs/{job_id}/collation", response_class=HTMLResponse)
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
