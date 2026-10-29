# -*- coding: utf-8 -*-
"""按资源切分的 FastAPI 路由组（`server/app.py` 的绞杀者式外迁目标，见 `REFACTOR.md` §4）。

约定：每个模块只导出一个 `router = APIRouter()`，由 `app.include_router(...)` 挂载；
**接口路径与返回结构一律不动**。
"""
