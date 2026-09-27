# -*- coding: utf-8 -*-
"""契约 #21：灵活报告两口（2026-09-24 前端清单）。"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as appmod, config                      # noqa: E402
from server.app import _flex_ctx, resolve_period_dir          # noqa: E402


class _Req:
    def __init__(self, user=None):
        self.session = {"user": user} if user else {}


def _ctx_or_skip():
    d = resolve_period_dir("202607")
    if d is None:
        from _guard_registry import skip_unless
        skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
    ctx = _flex_ctx(d, None)
    if not ctx["reports"]:
        from _guard_registry import skip_unless
        skip_unless("out/202607/flexible 无报告",
                    lambda: bool(list((d / "flexible").glob("*/report.md"))))
    return d, ctx


class TestFlexible组装:
    def test_列已生成两份(self):
        _d, ctx = _ctx_or_skip()
        ids = {r["intent"] for r in ctx["reports"]}
        assert "single_trend" in ids and "cross_compare" in ids

    def test_intents是中文对(self):
        _d, ctx = _ctx_or_skip()
        assert ctx["intents"] == [
            {"id": "single_trend", "cn": "单学科趋势诊断"},
            {"id": "cross_compare", "cn": "多学科横向对比"},
        ]

    def test_body_html指向保留的图表路由(self):
        _d, ctx = _ctx_or_skip()
        body = ctx["body"] or ""
        assert "/p/202607/flexible/chart/" in body, body[:120]
        assert "C:" not in body, "body_html 不许带本机路径"

    def test_meta带前端要的键(self):
        _d, ctx = _ctx_or_skip()
        m = ctx["reports"][0]["meta"]
        for k in ("generated_at", "n_charts", "backend", "selected", "charts"):
            assert k in m, k


class Test路由与权限:
    def test_GET路由(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/flexible")' in src

    def test_POST路由(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/flexible")' in src

    def test_两口都用require_admin(self):
        for fn in (appmod.api_period_flexible, appmod.api_period_flexible_generate):
            assert asyncio.run(fn(_Req(config.GUEST_USER), "202609")).status_code == 403
            assert asyncio.run(fn(_Req(None), "202609")).status_code == 401

    def test_POST只写flexible目录(self):
        """生成只动 out/<期次>/flexible/ —— 源码层确认没碰 input/ 或台账。"""
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_flexible_generate")[1].split("@app.")[0]
        assert "flex_report.generate" in block
        assert "INPUT_DIR" not in block and "监测表" not in block

    def test_未知意图400(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_flexible_generate")[1].split("@app.")[0]
        assert "INTENTS" in block and "400" in block
