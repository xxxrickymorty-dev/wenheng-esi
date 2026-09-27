# -*- coding: utf-8 -*-
"""路由守卫装饰器：`require_admin` / `require_admin_file` 的判别只写一次。

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

from starlette.responses import Response


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
