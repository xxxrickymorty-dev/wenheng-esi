# -*- coding: utf-8 -*-
"""报告插图 ↔ 图册图位（2026-10-28 rick 裁决：审核台正文也换同源交互图）。

两条断言守两件事：
1. `chart_map` 只收**逐字节对上**的图（同字节必同一张；对不上如实不给）；
2. `/api/periods/<p>/charts-data` 把图册数据与这张映射一起交出去——
   前端靠它把正文里的 PNG 换成 ECharts，映射缺席时页面自然保留原图。

口径：映射只增解释，不改任何数字；`report_map` 的值是（组, 文件名），
同一张 `rank_pct.png` 在 22 个学科组各有副本，所以必须带组名。
"""
from __future__ import annotations

import asyncio
import hashlib
import pathlib
import sys

from _guard_registry import skip_unless

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import config                                     # noqa: E402
from server import report_preview                             # noqa: E402
from server import app as app_module                          # noqa: E402
from server.app import resolve_period_dir                     # noqa: E402


def _period_with_products():
    """取一个有产物的期次（开发机上通常有；一个都没有就跳过，不造假数据）。"""
    for p in ("202609", "202607", "202605", "202603", "202601"):
        d = resolve_period_dir(p)
        if d is not None and (d / "charts").is_dir():
            return p, d
    return None, None


class _Req:
    """最小 Request 替身：直接调处理函数时只用到 session。"""

    def __init__(self, user):
        self.session = {"user": user}


def test_映射的每一格都真的对得上字节():
    _, d = _period_with_products()
    if d is None:
        skip_unless("开发机上没有带 charts/ 的期次（馆员数据不入库，属正常）",
                    lambda: _period_with_products()[1] is not None)
    m = report_preview.chart_map(d)
    assert m, "有产物就该有映射（报告里的图就是 charts/ 里那批 PNG）"
    by_hash = {}
    for f in (d / "charts").rglob("*.png"):
        by_hash[hashlib.sha256(f.read_bytes()).hexdigest()] = (f.parent.name, f.name)
    data = report_preview.load(d)
    for rid, slot in list(m.items())[:20]:
        blob = data["images"][rid][0]
        want = by_hash[hashlib.sha256(blob).hexdigest()]
        assert (slot["group"], slot["name"]) == want, "映射必须与字节哈希一致，不许按顺序猜"


def test_接口把图册数据与映射一起给():
    period, d = _period_with_products()
    if d is None:
        skip_unless("开发机上没有带 charts/ 的期次（馆员数据不入库，属正常）",
                    lambda: _period_with_products()[1] is not None)
    out = asyncio.run(app_module.api_period_charts_data(_Req(config.OPERATOR_USER), period))
    from fastapi.responses import JSONResponse

    assert not isinstance(out, JSONResponse), "有产物就不该回错误响应"
    assert "report_map" in out and out["report_map"], "映射要随图册数据一起出去"
    assert "disciplines" in out or "rank_pct" in out, "同时得是图册同源数据"


def test_没有期次回404而不是空数据():
    out = asyncio.run(app_module.api_period_charts_data(_Req(config.OPERATOR_USER), "209901"))
    from fastapi.responses import JSONResponse

    assert isinstance(out, JSONResponse) and out.status_code == 404
