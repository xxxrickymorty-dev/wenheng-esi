# -*- coding: utf-8 -*-
"""P1 只读端点 redslots / collation / charts（契约 §2.2 #4#5#6）。

验的是分页形状 + redslots 的 group/label/old/new/src/kind 字段 + collation 的 sections 元数据。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import collation, jobs                             # noqa: E402
from server.app import _paginate, resolve_period_dir           # noqa: E402
from server import app as app_module, config                    # noqa: E402


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


class TestPaginate:
    def test_基本分页(self):
        items = list(range(100))
        r = _paginate(items, 50, 0)
        assert r["total"] == 100
        assert len(r["rows"]) == 50
        assert r["has_more"] is True
        assert r["limit"] == 50
        assert r["offset"] == 0

    def test_最后一页(self):
        r = _paginate(list(range(100)), 50, 50)
        assert r["has_more"] is False
        assert len(r["rows"]) == 50

    def test_超出范围(self):
        r = _paginate(list(range(10)), 50, 100)
        assert r["rows"] == []
        assert r["has_more"] is False

    def test_limit上限500(self):
        r = _paginate(list(range(1000)), 9999, 0)
        assert r["limit"] == 500

    def test_负offset归零(self):
        r = _paginate(list(range(10)), 5, -3)
        assert r["offset"] == 0


class TestRedslots数据:
    def test_202607有red_slots_json(self):
        d = resolve_period_dir("202607")
        assert d is not None
        rp = d / "red_slots.json"
        assert rp.exists()
        data = json.loads(rp.read_text(encoding="utf-8"))
        assert len(data) > 0

    def test_red_slots字段有location_old_new_source(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        data = json.loads((d / "red_slots.json").read_text(encoding="utf-8"))
        first = data[0]
        assert "location" in first
        assert "old" in first
        assert "new" in first


class TestCollation:
    def test_202607_collation有sections(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        data = collation.build(d)
        assert "sections" in data
        assert len(data["sections"]) > 0
        for s in data["sections"]:
            assert "id" in s
            assert "name" in s
            assert "count" in s


class TestCharts:
    def test_202607_list_charts返回dict列表(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        items = jobs.list_charts(d)
        assert len(items) > 0
        for it in items:
            assert "name" in it
            assert "group" in it
            assert "rel" in it

    def test_预测图带读得懂的名字(self, tmp_path):
        """2026-10-16：未进 1% 全画后，图册给 forecast_*.png 配「学科 · 图别」。"""
        ov = tmp_path / "charts" / "_overview"
        ov.mkdir(parents=True)
        (ov / "forecast_3_cites.png").write_bytes(b"png")
        (tmp_path / "forecast_charts.json").write_text(json.dumps({
            "charts": [
                {"index": 3, "subject": "免疫学", "task": "citation", "kind": "cites",
                 "png": "forecast_3_cites.png"},
                {"index": 3, "subject": "免疫学", "task": "rank", "kind": "rank",
                 "png": "forecast_3_rank.png"},
                {"subject": 7, "png": None},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        labels = app_module._forecast_chart_labels(tmp_path)
        assert labels == {
            "forecast_3_cites.png": "免疫学 · 被引频次与阈值（预测图）",
            "forecast_3_rank.png": "免疫学 · 国内排名与机构数（预测图）",
        }

    def test_无预测元数据_标签留空不猜(self, tmp_path):
        assert app_module._forecast_chart_labels(tmp_path) == {}


class Test权限门:
    def test_redslots对操作员只读开放(self):
        """2026-10-20 决赛证据面：红件清单只读开放；写口仍 admin。"""
        view = asyncio.run(app_module.api_period_redslots(
            _Req(config.OPERATOR_USER), "202609"))
        assert isinstance(view, dict) and "rows" in view
        assert asyncio.run(app_module.api_period_redslots(
            _Req(None), "202609")).status_code == 401

    def test_collation放行操作员_匿名401(self):
        # 2026-10-11：对勘本是对外可见的只读屏，操作员放行（404＝门放行后未找到期次）。
        assert asyncio.run(app_module.api_period_collation(
            _Req(config.OPERATOR_USER), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_collation(
            _Req(None), "199901")).status_code == 401

    def test_charts放行操作员_匿名401(self):
        assert asyncio.run(app_module.api_period_charts_json(
            _Req(config.OPERATOR_USER), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_charts_json(
            _Req(None), "199901")).status_code == 401
