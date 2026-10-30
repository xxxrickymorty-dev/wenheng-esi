# -*- coding: utf-8 -*-
"""路由守卫装饰器：`require_admin` / `require_admin_file` / `require_user` /
`require_user_file` 的判别只写一次（后两者 2026-10-11 角色改两级后新增：
已登录即可，管理员与操作员都放行）。

用法（**必须夹在 `@app.xxx(...)` 与 `async def handler(...)` 之间**——
FastAPI 注册的是装饰后的包装函数；放在 `@app.xxx` 上面会把原函数注册进去、
守卫永远不执行）：

    @app.get("/api/periods")
    @admin_route
    async def api_periods(request: Request):
        ...  # 这里不再需要 isinstance 判别

语义与原来的手写判别完全一致：守卫函数仍返回「用户名或响应」——装饰器把响应
直接返回，用户名放行。直接调用（测试的既有姿势）拿到 401/403/303 响应对象。

两处细节别动：
  · `functools.wraps`：路由顺序测试读 `endpoint.__name__`；
  · 守卫在**请求时**从 `server.app` 现取（late binding）：测试里
    `monkeypatch.setattr(app_module, "require_admin", ...)` 仍然生效。
"""
from __future__ import annotations

import functools

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response


def current_user(request: Request):
    """当前登录用户名（未登录为 None）——全系统只有这一处判据。

    2026-10-25 从 `server/app.py` 下沉：路由外迁到 `server/routes/*` 之后，新模块不能
    顶层 `from ..app import current_user`（那会形成 `app → routes → app` 循环导入）。
    它是纯 HTTP 层判据，与守卫同族，放这里最合适。
    """
    return request.session.get("user")


def _period_missing():
    """API 侧「期次不存在」的统一 404（老路由仍是 303，两种口径都在 tests 里钉着）。

    同 `current_user`：2026-10-25 从 `server/app.py` 下沉，供路由组使用，理由相同。
    """
    return JSONResponse(
        {"error": "期次不存在", "hint": "请先在控制台上传台账生成该期次"}, status_code=404)


def _live_guard(name):
    from . import app as app_module
    return getattr(app_module, name)


def _denied(guard_name, request):
    denial = _live_guard(guard_name)(request)
    return denial if isinstance(denial, Response) else None


def _make_async(fn, guard_name):
    @functools.wraps(fn)
    async def wrapper(request, *args, **kwargs):
        denial = _denied(guard_name, request)
        return denial if denial is not None else await fn(request, *args, **kwargs)
    return wrapper


def _make_sync(fn, guard_name):
    @functools.wraps(fn)
    def wrapper(request, *args, **kwargs):
        denial = _denied(guard_name, request)
        return denial if denial is not None else fn(request, *args, **kwargs)
    return wrapper


def _decorator(guard_name):
    import inspect

    def decorate(fn):
        return _make_async(fn, guard_name) if inspect.iscoroutinefunction(fn) \
            else _make_sync(fn, guard_name)
    return decorate


admin_route = _decorator("require_admin")
admin_file_route = _decorator("require_admin_file")
#: 只读端点/文件口：已登录即可（管理员与操作员都放行）——2026-10-11 角色改两级后新增。
user_route = _decorator("require_user")
user_file_route = _decorator("require_user_file")
