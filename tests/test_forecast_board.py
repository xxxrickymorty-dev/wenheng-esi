# -*- coding: utf-8 -*-
"""契约 #19（facts 加 trend）/ #20（forecast/board）——2026-09-24 前端清单。"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import forecasting                                # noqa: E402
from server.app import resolve_period_dir                     # noqa: E402


def _board_or_skip():
    b = forecasting.board_context("202607")
    if not b["routes"]["citation"] and not b["routes"]["rank"]:
        from _guard_registry import skip_unless
        skip_unless("out/202607 无 预测选模与过线.md",
                    lambda: bool(list((REPO / "out").glob("*/预测选模与过线.md"))))
    return b


class TestBoard解析:
    def test_两条路线各八学科(self):
        b = _board_or_skip()
        assert len(b["routes"]["citation"]) == 8, f"n={len(b['routes']['citation'])}"
        assert len(b["routes"]["rank"]) == 8

    def test_字段齐全且类型对(self):
        b = _board_or_skip()
        for row in b["routes"]["citation"] + b["routes"]["rank"]:
            for k in ("subject", "model", "fit_mape", "rolling_mape", "prox",
                      "gap", "t1", "t2", "t3", "both_under_5"):
                assert k in row, k
            assert isinstance(row["subject"], str) and row["subject"]
            assert isinstance(row["model"], str) and row["model"]
            assert row["fit_mape"] is None or isinstance(row["fit_mape"], float)
            assert isinstance(row["both_under_5"], bool)
            assert isinstance(row["t1"], str)

    def test_金银样行抽查(self):
        """Economics & Business 被引线 SARIMA、接近度 14.23%、未过线（t 全空）。"""
        b = _board_or_skip()
        rows = {r["subject"]: r for r in b["routes"]["citation"]}
        eb = rows.get("Economics & Business")
        assert eb is not None
        assert eb["model"] == "SARIMA"
        assert abs(eb["prox"] - 14.23) < 1e-9
        assert eb["t1"] == "" and eb["t2"] == "" and eb["t3"] == ""

    def test_period与window来自正文(self):
        b = _board_or_skip()
        assert b["period"] == "202607"
        assert b["window"] == "201909-202607"

    def test_缺文件返回空板不炸(self, tmp_path):
        # 直接打一个不存在期次
        b = forecasting.board_context("209901")
        assert b["routes"] == {"citation": [], "rank": []}
        assert "未找到" in b["note"]


class TestBoard路由与权限:
    def test_路由是GET_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/forecast/board")' in src

    def test_用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_forecast_board")[1].split("@app.")[0]
        assert "require_admin" in block


class TestFactsTrend:
    def test_trend是纯数值序列(self, repo):
        import json
        d = resolve_period_dir("202607")
        if d is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        trend = meta.get("top_total_by_period") or {}
        finite = {k: v for k, v in trend.items() if isinstance(v, (int, float))}
        assert finite, "meta 里没有 top_total_by_period 数值"
        assert "202607" in finite and finite["202607"] == 274.0
        assert all(isinstance(v, (int, float)) for v in finite.values())

    def test_facts端点带trend字段(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_facts")[1].split("@app.")[0]
        assert '"trend": trend' in block
        assert "top_total_by_period" in block
