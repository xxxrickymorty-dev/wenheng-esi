# -*- coding: utf-8 -*-
"""forecast 分册：预测台数据面（20261101 C8 路由分册，从 server/app.py 迁入）。

学科板（契约 #20）、模型元信息与运行口；老预测页的 302 在 pages 册。
选模口径的唯一实现在 `src/forecast_choice` 与 `server/forecasting`。
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import forecasting
from ..guards import _period_missing, admin_route, user_route
from ..web_common import resolve_period_dir

router = APIRouter()


@router.get("/api/forecast/board")
@user_route
async def api_forecast_board(request: Request, period: str = ""):
    """预测台「学科板」（契约 #20）—— 解析预测选模与过线.md 的两张表。

    不重算；缺文件时返回空板 + note（不 500）。`?period=` 可指定，
    默认取最新有该文件的期次。
    """
    if period and resolve_period_dir(period) is None:
        return _period_missing()
    return forecasting.board_context(period or None)


@router.get("/api/forecast/meta")
@user_route
async def api_forecast_meta(request: Request):
    return forecasting.page_context()


@router.post("/api/forecast/run")
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
