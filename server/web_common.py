# -*- coding: utf-8 -*-
"""路由层共享小件（20261101 C8 路由分册）：各产线分册都要用的 helper、模板与单例访问口。

分册（server/routes/*.py）**不许 import server.app**（装配壳）——顶层 import 会成环。
这里几条「请求时从 server.app 现取」的访问口（late binding）不是绕圈，而是**补丁锚点**
（同 `server/guards.py::_live_guard` 的既有做法）：测试按
`monkeypatch.setattr(app_module, "resolve_period_dir" / "current_user" /
"SESSION_DB_PATH" / "_login_fails" / "_find_ledger", …)` 打补丁，路由处理函数必须经
这些访问口调用才看得见补丁。共享实现本体在 app.py 装配壳里；仅供单册用的私有
helper 不进这里（随册走）。
"""
import io
import urllib.parse

from fastapi import Request
from fastapi.responses import (FileResponse, JSONResponse,
                               StreamingResponse)
from fastapi.templating import Jinja2Templates

from . import approval, archive, config, visibility
from src import period_facts  # 期次事实：目录/盘点/并入/产物/顺延的唯一 module


# ---- 补丁锚点访问口（late binding，语义见模块 docstring）----------------------

def current_user(request: Request):
    """当前登录用户名（未登录 None）——处理函数一律经此取用。"""
    from . import app as _app                     # noqa: PLC0415
    return _app.current_user(request)


def resolve_period_dir(period):
    """期次字符串 → out/ 下的实际目录（adapter；事实在 period_facts.resolve）。"""
    from . import app as _app                     # noqa: PLC0415
    return _app.resolve_period_dir(period)


def find_ledger():
    """运行时动态监测表（母本）路径或 None——处理函数一律经此取用。"""
    from . import app as _app                     # noqa: PLC0415
    return _app._find_ledger()


def login_fails() -> dict:
    """登录失败计数表（app._login_fails 单例）——do_login 经此取用。"""
    from . import app as _app                     # noqa: PLC0415
    return _app._login_fails


def session_db_path():
    """会话库路径（票 11 单例）：生产由 lifespan 装配；测试 monkeypatch 注入 tmp。"""
    from . import app as _app                     # noqa: PLC0415
    return _app.SESSION_DB_PATH


# ---- 共享 helper（各册通用，原 app.py 定义原样迁入）--------------------------

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


def _role_of_request(request):
    return config.role_of(current_user(request) or "")


def _job_missing():
    """「任务不存在」的统一 404。"""
    return JSONResponse(
        {"error": "任务不存在", "hint": "请检查任务 ID 是否正确"}, status_code=404)


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


def _zip_response(data: bytes, filename: str):
    """日志包下载。文件名是 ASCII（中文名在部分浏览器会乱码），说明写在包内 README。"""
    return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


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


# ---- 模板（pages 册渲染登录页；装配壳往 env.globals 里注册状态口径与 asset）----

templates = Jinja2Templates(directory=str(config.SERVER_DIR / "templates"))
