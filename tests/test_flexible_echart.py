# -*- coding: utf-8 -*-
"""ECharts 数据 payload（`flexible/echart.py`）的验收用例。

判据：
1. **数据对齐**：payload 的点与 `charts.py` PNG 出口同源同窗（同读一张
   parquet、同一种 ×100 / 差分换算）；
2. **红线**：payload 结构上没有轴范围字段（min/max/ylim…）；
3. **回落安全**：图型不支持 / 数据不可得 → None（上层回落 PNG，不编数据）。

前一组用例需要 `out/202609` 数据（资源缺席才跳过，带探针复核）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _guard_registry import skip_unless

from flexible import echart

REPO = pathlib.Path(__file__).resolve().parent.parent
D202609 = REPO / "out" / "202609"
SOURCES = D202609 / "flexible" / "single_trend" / "flex_sources.json"


def _charts():
    entries = json.loads(SOURCES.read_text(encoding="utf-8"))
    return [e for e in entries if e.get("kind") == "chart"]


def _probe() -> bool:
    return D202609.is_dir() and SOURCES.is_file()


class Test数据对齐:
    def test_四种单学科图全出payload(self):
        if not _probe():
            skip_unless("out/202609 灵活稿数据缺失", _probe)
        payloads = echart.payloads_for(_charts(), D202609)
        kinds = {p["kind"] for p in payloads.values()}
        assert kinds == {"cites_threshold", "cnci", "rank_pct", "cites_permille"}

    def test_payload与账本数字一致(self):
        if not _probe():
            skip_unless("out/202609 灵活稿数据缺失", _probe)
        payloads = echart.payloads_for(_charts(), D202609)
        srcs = json.loads(SOURCES.read_text(encoding="utf-8"))
        # cites_threshold 的 cites 序列末点 = 账本「总被引」条目的当期值
        ct = next(p for p in payloads.values() if p["kind"] == "cites_threshold")
        cites_entry = next(e for e in srcs
                           if e.get("metric") == "total_cites" and e.get("section") == "学科概况")
        last = max(cites_entry["points"], key=lambda x: x["period"])
        assert ct["series"][0]["data"][-1] == pytest.approx(last["value"])

    def test_payload无轴范围字段(self):
        """🔴 红线：payload 结构上不存在轴范围字段（同 spec.py 的闸）。"""
        if not _probe():
            skip_unless("out/202609 灵活稿数据缺失", _probe)
        forbidden = {"min", "max", "ylim", "ymin", "ymax", "range", "limits"}
        for p in echart.payloads_for(_charts(), D202609).values():
            assert not (set(p) & forbidden), p


class Test回落安全:
    def test_未知图型返回None(self):
        assert echart.payload_for({"kind": "nope", "periods": ["202609"]},
                                  D202609) is None

    def test_空窗口返回None(self):
        assert echart.payload_for({"kind": "cnci", "periods": []},
                                  D202609) is None

    def test_payloads_for兼容flex_sources形状(self):
        if not _probe():
            skip_unless("out/202609 灵活稿数据缺失", _probe)
        payloads = echart.payloads_for(_charts(), D202609)
        assert payloads, "chart_kind/file 形状也能出 payload"
        assert all(name.endswith(".png") for name in payloads)
