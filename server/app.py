# -*- coding: utf-8 -*-
"""文衡 · 学科信息参考自动化演示站（FastAPI）。

启动（在 wenheng 目录下）：
    .venv\\Scripts\\python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8080

本文件是**装配壳**（20261101 C8 路由分册）：app 创建、中间件、挂载、鉴权口、
startup（lifespan）与状态单例都在这里；路由按产线分册在 `server/routes/`
（acquisition / pages / periods / flexible / dialog / monitor / forecast / jobs / misc）。
分册不许 import 本模块（会成环）；跨册共享小件在 `server/web_common.py`。

仍留在本模块的东西分两类，都不是漏网之鱼：
  · **补丁锚点**：测试按 `monkeypatch.setattr(app_module, 名, …)` 打补丁
    （require_* 守卫、current_user、resolve_period_dir、_find_ledger、
    _login_fails、SESSION_DB_PATH），路由分册经 web_common 的访问口在请求时现取；
  · **兼容旧导入**：tests 按 `app_module.<名字>` 直取各分册的 handler 与私有
    helper——下面的 re-export 少一个测试就红，**不要**以「看起来没用」为由删。
"""
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import (acquisition,        # 取数台服务模块（tests 按 app_module.acquisition 打补丁）
               archive, collation, config, forecasting, jobs,
               shelf_data, shelf_preview, visibility)
from .guards import current_user
# 取数台路由组已迁到 `server/routes/acquisition.py`（任务卡 01）。下面这行把名字挂回
# `server.app`：①测试按 `app_module.<名字>` 直取下面的 handler 与私有 helper
# （卡片要求不改测试）；②`server.acquisition` 的导入顺带把 src/ 自举上 sys.path，
# 后续分册里 `src.monitor` 的裸模块导入依赖这一顺序。
# 缺一个测试就红——**不要**以「看起来没用」为由删这里的任何一项。
from .routes.acquisition import (_acq_cdp_alive, _acq_expected_data, _acq_mode,
                                 _acq_op_liveness, _acq_op_running, _acq_opened,
                                 _acq_reconcile, _acq_touched, api_acq_browser,
                                 api_acq_copy, api_acq_datapack, api_acq_merge,
                                 api_acq_open, api_acq_preflight, api_acq_retry,
                                 api_acq_start, api_acq_stop, api_period_acquisition,
                                 router as acquisition_router)
from .protected_static import AdminStaticFiles
from src import ledger as ledger_mod  # 动态监测表（母本）路径唯一口径（2026-10-13：input/ 只放母本）
from src import period_facts  # 期次事实：目录/盘点/并入/产物/顺延的唯一 module
from src import session_store  # 会话库（票 11）——对话前门会话的服务端持久化


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.recover_stale()
    # 会话库（票 11）：生产装配路径（`out/_sessions/sessions.sqlite`）。
    # 直调处理函数的测试不跑 lifespan → SESSION_DB_PATH 保持 None → 不落库、绝不碰真数据。
    global SESSION_DB_PATH
    SESSION_DB_PATH = session_store.store_path(config.ROOT)
    # 他校简报的读表缓存（阶段 2/3）：`panel()` 冷启 40 秒上下（六期 × 二十二学科），
    # 现场演示不能让人干等第一次。这里在启动时就焐热——后台线程、只读、失败不影响服务。
    # `_warm_async` 自己认 `WENHENG_PANEL_PREWARM=0` 与 pytest 两个关断位。
    try:
        from src.ai import _dialog as _dialog_mod                  # noqa: PLC0415
        _dialog_mod._warm_async()
    except Exception:                                             # noqa: BLE001
        pass                                                      # 预热失败只影响首问快慢
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

# ---------------- 路由装配（按产线分册，20261101 C8）----------------
# 分册内部的路由相对顺序与搬迁前逐条一致（forecast-choice 读口在写口之前的
# 注册顺序约束等）；各册之间路径互不重叠，汇总顺序不影响匹配。
from .routes.dialog import router as dialog_router        # noqa: E402
from .routes.flexible import router as flexible_router    # noqa: E402
from .routes.forecast import router as forecast_router    # noqa: E402
from .routes.jobs import router as jobs_router            # noqa: E402
from .routes.misc import router as misc_router            # noqa: E402
from .routes.monitor import router as monitor_router      # noqa: E402
from .routes.pages import router as pages_router          # noqa: E402
from .routes.periods import router as periods_router      # noqa: E402
from .routes.speech import router as speech_router        # noqa: E402

app.include_router(acquisition_router)
app.include_router(pages_router)
app.include_router(periods_router)
app.include_router(flexible_router)
app.include_router(dialog_router)
app.include_router(monitor_router)
app.include_router(forecast_router)
app.include_router(jobs_router)
app.include_router(misc_router)
app.include_router(speech_router)


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


from .web_common import period_cards, templates  # noqa: E402

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


# ---------------- 鉴权口（装配壳保留：guards 在请求时从本模块现取，见 guards.py）----------------

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


# ---------------- 补丁锚点（路由分册经 web_common 访问口在请求时现取）----------------

def resolve_period_dir(period):
    """期次字符串 → out/ 下的实际目录（adapter；事实在 period_facts.resolve）。

    实现留在这里而不是 web_common：测试按 `monkeypatch.setattr(app_module,
    "resolve_period_dir", …)` 打补丁，各分册经 `web_common.resolve_period_dir`
    在请求时现取本名，补丁因此对全部路由生效（同 guards._live_guard 的 late binding）。
    """
    return period_facts.resolve(period, config.OUT_DIR)


def _find_ledger():
    """运行时动态监测表（母本）：`input/云大全学科排名、阈值动态检测表.xlsx`。

    2026-10-13 起 input/ 只放母本（不再有 `input/<期次>/监测表.xlsx`）；
    母本含全部期次，逐格溯源/表页按页面期次消费。找不到返回 None（页面降级说明）。
    同 `resolve_period_dir`：测试打补丁的锚点，分册经 `web_common.find_ledger()` 现取。
    """
    p = ledger_mod.runtime_path(config.ROOT)
    return p if p.exists() else None


#: 会话库路径（票 11）：生产由 lifespan 装配（`out/_sessions/sessions.sqlite`）；
#: None＝未装配——直调处理函数的测试不落库、绝不碰真数据；测试 monkeypatch 注入 tmp。
SESSION_DB_PATH = None


# ---------------- 兼容旧导入：各分册 handler 与测试直取的私有 helper ----------------
# tests 按 `app_module.<名字>` 直取（卡片要求不改测试）；分册已收产线内聚，
# 这里只做名字挂回。按分册分组，勿删。

# pages 册（登录/登出 + 旧页 302）
from .routes.pages import (charts_page, check_credentials, collation_page,  # noqa: E402
                           do_login, forecast_page, home, job_archive,
                           job_page, login_page, logout, period_archive,
                           period_charts, period_collation, period_flexible,
                           period_redslots, period_trace, redslots_page,
                           run_page)

# periods 册（期次面）
from .routes.periods import (_TRACE_CATS, _acquisition_only_periods,  # noqa: E402
                             _count_forecast_choice, _forecast_chart_labels,
                             _localize_facts, _paginate, _rollback_points,
                             api_forecast_choice, api_forecast_choice_get,
                             api_period_archive, api_period_artifacts,
                             api_period_charts_data, api_period_charts_json,
                             api_period_collation, api_period_detail,
                             api_period_download, api_period_facts,
                             api_period_fill_json, api_period_flag_json,
                             api_period_outline, api_period_rebuild_json,
                             api_period_redslots, api_period_revoke_json,
                             api_period_report_image, api_period_report_preview,
                             api_period_sign_json, api_period_trace,
                             api_period_water, api_period_workbench,
                             api_periods, api_rollback, api_rollback_points,
                             period_chart, period_download)

# flexible 册（灵活报告 + 多校面板）
from .routes.flexible import (_flex_ctx, api_period_flexible,  # noqa: E402
                              api_period_flexible_generate,
                              api_period_flexible_polish,
                              api_period_flexible_stop,
                              api_period_flexible_stream,
                              api_period_panel_data, period_flexible_chart)

# dialog 册（对话 / 问文衡 / 问数 / AI 能力 / 模型清单）
from .routes.dialog import (api_ai_call_stats, api_ai_capabilities,  # noqa: E402
                            api_ai_switch,
                            api_aiqa_ask, api_aiqa_log, api_aiqa_meta,
                            api_analyze, api_dialog_home, api_dialog_session,
                            api_dialog_session_drop, api_dialog_sessions,
                            api_dialog_turn, api_dialog_turn_stream,
                            api_models, api_models_active, api_models_remove,
                            api_models_save, api_models_test,
                            api_period_ai_calls, api_period_review_advice)

# monitor 册（监测版）
from .routes.monitor import (api_monitor_compare, api_monitor_report,  # noqa: E402
                             api_monitor_schools, monitor_compare_page,
                             monitor_report_page)

# forecast 册（预测台）
from .routes.forecast import (api_forecast_board, api_forecast_meta,  # noqa: E402
                              api_forecast_run)

# jobs 册（生成任务 + SSE）
from .routes.jobs import (api_approval, api_artifacts, api_create_job,  # noqa: E402
                          api_events, api_job, api_job_download,
                          api_job_progress, api_rerun_job, download)

# misc 册（杂项：探活/状态/当前用户/沙盘/台账表页/二维码）
from .routes.misc import (api_ledger_sheets, api_me, api_sandbox_heal,  # noqa: E402
                          api_sandbox_migrate, api_status, healthz, qr)
