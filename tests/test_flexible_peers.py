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


# ---------------------------------------------------------------- 匹配档位
def _rows_and_map():
    """当前期机构表 + 总表规范名。"""
    data = peers.fetch("202607", "Plant & Animal Science")
    tpl = peers._latest_template()
    return data["rows"], (peers._name_map(str(tpl)) if tpl else {})


def test_子串唯一命中要标成兜底():
    """'KUNMING UNIVERSITY' 只命中昆工一家 —— 唯一，但那是昆明学院。

    2026-10-30 实测的静默错数据：`present=True`、数字全是昆工的。
    唯一性不是正确性，所以必须标 `substring`，不能冒充 `map`/`table`。
    """
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    rows, nm = _rows_and_map()
    got = peers._match_ex(rows, nm, "KUNMING UNIVERSITY")
    assert got["how"] == "substring"


def test_中文全称走规范名精确匹配():
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    rows, nm = _rows_and_map()
    got = peers._match_ex(rows, nm, "大理大学")
    assert got["how"] == "map" and got["en"] == "DALI UNIVERSITY"


def test_子串对上多家必须报错不许猜():
    """'DALI' 同时对上大理工、大理大学、大连海大 —— 猜哪一家都是错数据。"""
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    rows, nm = _rows_and_map()
    with pytest.raises(peers.PeerError, match="多家机构"):
        peers._match_ex(rows, nm, "DALI")


def test_查不到时并列两种情形并给候选():
    """本地数据分不清「整校未进 ESI」与「写法不一致」，报错不许替用户下结论。"""
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    rows, nm = _rows_and_map()
    with pytest.raises(peers.PeerError) as ei:
        peers._match_ex(rows, nm, "昆明学院", sheet="Plant & Animal Science.xlsx")
    msg = str(ei.value)
    assert "整校未进入本期 ESI" in msg and "校名写法与 ESI 不一致" in msg
    assert "候选英文名" in msg and "KUNMING" in msg


def test_compare_每行带match档位():
    if not _esi_ready():
        skip_unless("ESI数据/202607 的植物与动物学机构表缺失",
                    lambda: _esi_ready())
    data = peers.compare("202607", "Plant & Animal Science",
                         ["昆明理工大学", "云南中医药大学"])
    how = {r["cn"]: r["match"] for r in data["rows"]}
    assert how["云南大学"] == "table"
    assert how["昆明理工大学"] == "map"
    assert how["云南中医药大学"] == "absent", "该学科未上榜的行也要带档位"


def test_已删除的跨学科意图不再接受():
    from flexible import planner
    with pytest.raises(ValueError, match="未登记的意图"):
        planner.build(None, "cross_compare")
