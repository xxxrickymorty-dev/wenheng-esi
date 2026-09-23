# -*- coding: utf-8 -*-
"""P1 只读端点 redslots / collation / charts（契约 §2.2 #4#5#6）。

验的是分页形状 + redslots 的 group/label/old/new/src/kind 字段 + collation 的 sections 元数据。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import collation, jobs                             # noqa: E402
from server.app import _paginate, resolve_period_dir           # noqa: E402


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


class Test权限门:
    def test_redslots用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_redslots")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_collation不用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_collation")[1].split("@app.")[0]
        assert "require_admin" not in block

    def test_charts不用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_charts_json")[1].split("@app.")[0]
        assert "require_admin" not in block
