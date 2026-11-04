# -*- coding: utf-8 -*-
"""跨校单学科对比（school_compare，2026-11-04 rick 定）的测试。

- 取数：`peers.compare_multi`（一科 × 多校，不强制云大；未上榜＝无数据）；
- 规划：`planner` 的 school_compare 分支（规则、确定性）；
- 账本：内嵌 payload 随 chart 条目走 + 轴范围红线拒收。
数据驱动用例一律 `_guard_registry.skip_unless`（探针可调用）。
"""
from __future__ import annotations

import pytest

from _guard_registry import skip_unless


def _esi_ready() -> bool:
    from flexible import peers
    return peers.fetch is not None and (peers.ESI_ROOT / "202607").is_dir()


# ============================================================ 取数层
class TestCompareMulti:
    def test_不强制云大_顺序即所给顺序(self):
        if not _esi_ready():
            skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                        lambda: _esi_ready())
        data = peers_multi(["贵州大学", "广西大学"])
        assert [r["cn"] for r in data["rows"]] == ["贵州大学", "广西大学"]
        assert all(r["present"] for r in data["rows"])
        assert "ynu" not in data, "多校版不注入云大键"

    def test_未上榜校给无数据行(self):
        if not _esi_ready():
            skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                        lambda: _esi_ready())
        data = peers_multi(["贵州大学", "云南中医药大学"])
        absent = [r for r in data["rows"] if not r["present"]]
        assert len(absent) == 1 and absent[0]["cn"] == "云南中医药大学"
        assert all(v is None for v in absent[0]["values"].values()), \
            "无数据行的指标值一律 None（不许猜数）"

    def test_重复校名去重保序(self):
        if not _esi_ready():
            skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                        lambda: _esi_ready())
        data = peers_multi(["贵州大学", "贵州大学、昆明理工大学"])
        assert [r["cn"] for r in data["rows"]] == ["贵州大学", "昆明理工大学"]

    def test_compare形状兼容_ynu键与table档位(self):
        if not _esi_ready():
            skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                        lambda: _esi_ready())
        from flexible import peers
        data = peers.compare("202607", "Plant & Animal Science", ["贵州大学"])
        assert data["rows"][0]["cn"] == "云南大学"
        assert data["rows"][0]["match"] == "table"
        assert data["requested"] == ["贵州大学"], "requested 不含云大"


def peers_multi(queries):
    from flexible import peers
    return peers.compare_multi("202607", "Plant & Animal Science", queries)


# ============================================================ 规划层
class TestSchoolCompare规划:
    def _src(self):
        from conftest import REPO

        def _period_dir():
            outs = [p for p in (REPO / "out").glob("20*") if p.is_dir()]
            gold = [p for p in outs
                    if p.name == "202607" and (p / "ledger_long.parquet").is_file()]
            if gold:
                return gold[0]
            ok = [p for p in outs if (p / "ledger_long.parquet").is_file()]
            return ok[0] if ok else None

        d = _period_dir()
        if d is None:
            return None
        from flexible.datasource import DataSource
        return DataSource(d)          # 只读；规划不写盘

    def test_规则规划_图型与标题(self):
        src = self._src()
        if src is None:
            skip_unless("out/ 下无含 ledger_long.parquet 的期次产物",
                        lambda: False)
            return
        from flexible import planner
        plan = planner.build(src, "school_compare", disc="Plant & Animal Science",
                             peers=["贵州大学", "广西大学"])
        assert plan["intent"] == "school_compare"
        assert plan["backend"] == "rule"
        assert [c["kind"] for c in plan["charts"]] == [
            "schools_rank", "schools_cites", "schools_per"]
        assert "植物与动物学" in plan["title"]
        assert plan["peers"] == ["贵州大学", "广西大学"]

    def test_未给学科_人话报错(self):
        src = self._src()
        if src is None:
            skip_unless("out/ 下无含 ledger_long.parquet 的期次产物",
                        lambda: False)
            return
        from flexible import planner
        with pytest.raises(ValueError, match="需要先选定学科"):
            planner.build(src, "school_compare")

    def test_未登记意图仍拒(self):
        from flexible import planner
        with pytest.raises(ValueError, match="未登记的意图"):
            planner.build(None, "cross_compare")


# ============================================================ 账本与渲染层
class Test内嵌Payload红线:
    def test_合法payload透传(self):
        from flexible import echart
        p = {"kind": "schools_rank", "type": "bar", "cats": ["甲", "乙"],
             "series": [{"name": "全球位次", "data": [1, 2], "dash": False}],
             "invert": True, "fmt": "int"}
        got = echart.payload_for({"kind": "chart", "payload": p}, None)
        assert got == p

    def test_带轴范围字段即拒(self):
        from flexible import echart
        bad = {"kind": "x", "type": "bar", "cats": ["甲"],
               "series": [{"name": "s", "data": [1]}],
               "yaxis": {"min": 0, "max": 10}}
        assert echart.payload_for({"kind": "chart", "payload": bad}, None) is None
        bad2 = {"kind": "x", "type": "bar", "cats": ["甲"],
                "series": [{"name": "s", "data": [1], "scale": True}]}
        assert echart.payload_for({"kind": "chart", "payload": bad2}, None) is None

    def test_账本payload随chart条目走(self):
        from flexible import provenance as pv
        led = pv.Ledger(None)
        chart = {"kind": "schools_rank", "kind_cn": "全球位次对比",
                 "path": "C:/tmp/charts/schools_rank.png",
                 "spec": {"kind": "schools_rank", "disc": "Chemistry"},
                 "periods": ["202607"],
                 "sources": [{"dataset": "x.xlsx", "origin_sheet": "化学",
                              "period": "202607", "discipline": "Chemistry",
                              "locator": "化学：全球位次对比（202607）"}],
                 "payload": {"kind": "schools_rank", "type": "bar",
                             "cats": ["甲"], "series": [], "fmt": "int"}}
        led.section("指标对比").chart(chart)
        entry = [e for e in led.sources_json() if e.get("kind") == "chart"][0]
        assert entry["payload"]["kind"] == "schools_rank"

    def test_渲染层无轴范围字段(self):
        from flexible import mdview
        js = mdview._INIT_JS
        assert "scale:true" in js.replace(" ", "")
        assert "min:" not in js and "max:" not in js
        assert "dec2" in js, "篇均被引格式"
