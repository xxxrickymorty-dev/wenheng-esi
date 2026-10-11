# -*- coding: utf-8 -*-
"""契约 #21：灵活报告两口（2026-09-24 前端清单）。"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as appmod, config                      # noqa: E402
from server.app import _flex_ctx, resolve_period_dir          # noqa: E402


class _Req:
    def __init__(self, user=None, body=None):
        self.session = {"user": user} if user else {}
        self.body = body

    async def json(self):
        return self.body


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

    def test_读口放行操作员_写口仍admin(self):
        """2026-10-11：GET 读口对操作员放行（404＝门放行后未找到期次）；POST 生成口仍只管理员。"""
        assert asyncio.run(appmod.api_period_flexible(
            _Req(config.OPERATOR_USER), "199901")).status_code == 404
        assert asyncio.run(appmod.api_period_flexible(_Req(None), "199901")).status_code == 401
        assert asyncio.run(appmod.api_period_flexible_generate(
            _Req(config.OPERATOR_USER), "202609")).status_code == 403
        assert asyncio.run(appmod.api_period_flexible_generate(_Req(None), "202609")).status_code == 401

    def test_POST只写flexible目录(self, tmp_path, monkeypatch):
        """生成只动 out/<期次>/flexible/；config.INPUT_DIR 被触碰即失败。"""
        seen = {}
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)

        class _BombPath:
            def __truediv__(self, other):
                raise AssertionError("生成不应触碰 input/ 或台账")
        monkeypatch.setattr(appmod.config, "INPUT_DIR", _BombPath())

        import flexible.report as flex_report
        monkeypatch.setattr(
            flex_report, "generate",
            lambda d, intent, **k: seen.update(dir=d, intent=intent)
            or {"n_charts": 1, "plan": {"backend": "rule"}})
        r = asyncio.run(appmod.api_period_flexible_generate(
            _Req(config.ADMIN_USER, {"intent": "single_trend"}), "202609"))
        assert r["ok"] is True
        assert seen == {"dir": tmp_path, "intent": "single_trend"}

    def test_未知意图400(self, tmp_path, monkeypatch):
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)
        r = asyncio.run(appmod.api_period_flexible_generate(
            _Req(config.ADMIN_USER, {"intent": "不存在的意图"}), "202609"))
        assert r.status_code == 400
        assert "未知意图" in json.loads(r.body)["error"]


class Test流式与润色两口:
    """契约 #21③/#21④（2026-09-29 流式对话框 + AI 润色按钮）。"""

    def test_路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/flexible/stream")' in src
        assert '@app.post("/api/periods/{period}/flexible/polish")' in src

    def test_新两口也要管理员(self):
        for fn in (appmod.api_period_flexible_stream, appmod.api_period_flexible_polish):
            assert asyncio.run(fn(_Req(config.OPERATOR_USER), "202609")).status_code == 403
            assert asyncio.run(fn(_Req(None), "202609")).status_code == 401
        assert asyncio.run(appmod.api_period_flexible_stop(
            _Req(config.OPERATOR_USER, {"run": "x"}), "202609")).status_code == 403

    def test_停止键_首行带run令牌_喊停后终态stopped(self, tmp_path, monkeypatch):
        """停止键（契约 #21⑤）：流首行带 run 令牌；「停止」端点喊停 →
        下一次事件点收手，终态事件是 `stopped`（原流里送出）。"""
        import flexible.report as flex_report
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)

        def fake(d, intent, *, should_stop=None, **k):               # noqa: ARG001
            yield {"event": "status", "stage": "planning"}
            for i in range(100):
                if should_stop is not None and should_stop():
                    yield {"event": "stopped"}
                    return
                yield {"event": "section", "title": f"节{i}", "body": ""}
            yield {"event": "done"}

        monkeypatch.setattr(flex_report, "generate_stream", fake)
        r = asyncio.run(appmod.api_period_flexible_stream(
            _Req(config.ADMIN_USER, {"intent": "single_trend"}), "202609"))
        assert r.media_type.startswith("application/x-ndjson")

        async def consume():
            it = r.body_iterator
            first = await it.__anext__()
            rec = json.loads(first if isinstance(first, str) else first.decode("utf-8"))
            assert rec["event"] == "status" and rec["run"], "首行必须带 run 令牌（停止键要用）"
            resp = await appmod.api_period_flexible_stop(
                _Req(config.ADMIN_USER, {"run": rec["run"]}), "202609")
            assert resp["ok"] is True
            last = None
            n = 0
            async for chunk in it:
                last = json.loads(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
                n += 1
                if last["event"] in ("stopped", "done") or n > 60:
                    break
            return last

        last = asyncio.run(consume())
        assert last is not None and last["event"] == "stopped", "停止后的终态"

    def test_停一个不存在的run给人话(self, tmp_path, monkeypatch):
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)
        r = asyncio.run(appmod.api_period_flexible_stop(
            _Req(config.ADMIN_USER, {"run": "不存在的令牌"}), "202609"))
        assert r["ok"] is False and "没有可停的" in r["error"]

    def test_流式口一行一个事件(self, tmp_path, monkeypatch):
        import flexible.report as flex_report
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)
        monkeypatch.setattr(flex_report, "generate_stream",
                            lambda d, intent, **k: iter([
                                {"event": "status", "stage": "planning"},
                                {"event": "plan", "title": "t", "outline": ["一、本期概览"]},
                                {"event": "done", "elapsed": 1.0}]))
        r = asyncio.run(appmod.api_period_flexible_stream(
            _Req(config.ADMIN_USER, {"intent": "single_trend"}), "202609"))
        assert r.media_type.startswith("application/x-ndjson")

        async def consume():
            out = []
            async for c in r.body_iterator:
                out.append(c)
            return out

        raw = b"".join(x if isinstance(x, bytes) else x.encode("utf-8")
                       for x in asyncio.run(consume())).decode("utf-8")
        lines = [json.loads(x) for x in raw.splitlines() if x.strip()]
        assert [l["event"] for l in lines] == ["status", "plan", "done"]

    def test_润色没开写作位给409(self, tmp_path, monkeypatch):
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)
        p = tmp_path / "flexible" / "single_trend"
        p.mkdir(parents=True)
        (p / "flex_plan.json").write_text("{}", encoding="utf-8")
        r = asyncio.run(appmod.api_period_flexible_polish(
            _Req(config.ADMIN_USER, {"intent": "single_trend"}), "202609"))
        assert r.status_code == 409
        assert "写作位" in json.loads(r.body)["error"]

    def test_润色没有这稿给400(self, tmp_path, monkeypatch):
        monkeypatch.setattr(appmod, "resolve_period_dir", lambda period: tmp_path)
        r = asyncio.run(appmod.api_period_flexible_polish(
            _Req(config.ADMIN_USER, {"intent": "single_trend"}), "202609"))
        assert r.status_code == 400
