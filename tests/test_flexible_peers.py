# -*- coding: utf-8 -*-
"""灵活报告·跨校对比（2026-10-20 收敛为单学科后的第四节）。"""
from __future__ import annotations

import pytest

from _guard_registry import skip_unless

from flexible import peers


def _esi_ready() -> bool:
    return (peers.ESI_ROOT / "202607" / "Plant & Animal Science.xlsx").is_file()


def test_跨校对比_云南大学与指定高校同表():
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    data = peers.compare("202607", "Plant & Animal Science",
                         ["昆明理工大学", "云南农业大学"])
    assert data["period"] == "202607"
    assert data["ynu"]["cn"] == "云南大学"
    assert data["requested"] == ["昆明理工大学", "云南农业大学"]
    names = [r["cn"] for r in data["rows"]]
    assert names[0] == "云南大学"
    assert "昆明理工大学" in names and "云南农业大学" in names
    ynu = data["rows"][0]
    assert ynu["present"] and ynu["values"]["rank"] and ynu["rank_cn"]
    assert data["source"]["dataset"].endswith("Plant & Animal Science.xlsx")
    assert data["source"]["dataset"].startswith("数据与复现/ESI数据/"), \
        "来源必须是仓库相对路径，不能把本机绝对路径写进报告"


def test_英文校名也能解析():
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    data = peers.compare("202607", "Plant & Animal Science",
                         ["YUNNAN AGRICULTURAL UNIVERSITY"])
    assert data["requested"] == ["云南农业大学"]


def test_查不到的校名给人话报错():
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    with pytest.raises(peers.PeerError, match="没找到高校"):
        peers.compare("202607", "Plant & Animal Science", ["不存在的大学"])


def test_已删除的跨学科意图不再接受():
    from flexible import planner
    with pytest.raises(ValueError, match="未登记的意图"):
        planner.build(None, "cross_compare")
