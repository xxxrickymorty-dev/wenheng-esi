# -*- coding: utf-8 -*-
"""多校多学科面板（`flexible/panel.py`）的验收用例。

基线全部来自 202609 期真实数据（2026-10-30 只读探测，见 `tmp/panel_probe.py`），
不是手写的期望值：昆工 6 期 12 不动、海大 9→12、云大 13→14 后走平。

分层：
- **纯函数**（`_window` / `_pick_disciplines`）永远可跑，不碰数据；
- **数据驱动**：ESI 数据不在仓库里（`.gitignore`），缺数据时按 `skip_unless` 登记跳过。
  整模块共用一个 `full` 夹具，只跑一次满 6 期的扫描（约 20s），其余用例吃缓存。
"""
from __future__ import annotations

import pytest

from _guard_registry import skip_unless

from discipline_list import DISCIPLINES
from flexible import panel as panel_mod
from flexible import peers
from flexible.panel import panel

PERIODS = ["202511", "202601", "202603", "202605", "202607", "202609"]

#: 202609 实测：昆工 12 个学科，比「共同 10 个」多的两个是临床医学与分子生物学与遗传学。
KUNMING_ONLY = ["Clinical Medicine", "Molecular Biology & Genetics"]
HAINAN_ONLY = ["Microbiology", "Social Sciences, General"]

COMMON_10 = [
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Computer Science",
    "Engineering", "Environment Ecology", "Geosciences", "Materials Science",
    "Pharmacology & Toxicology", "Plant & Animal Science",
]


def _esi_ready() -> bool:
    """窗口首末两期的学科表都在，才认为 ESI 数据可用。"""
    root = peers.ESI_ROOT
    return ((root / "202511" / "Clinical Medicine.xlsx").is_file()
            and (root / "202609" / "Clinical Medicine.xlsx").is_file())


@pytest.fixture(scope="module")
def full():
    """6 期 × 3 校满窗口。整个模块只算这一次。"""
    if not _esi_ready():
        skip_unless("ESI数据 202511/202609 的学科表缺失", _esi_ready)
    return panel(["昆明理工大学", "海南大学", "云南大学"], period_end="202609", n=6)


def _counts(result, cn: str) -> list:
    return next(s["counts"] for s in result["schools"] if s["cn"] == cn)


def _school(result, cn: str) -> dict:
    return next(s for s in result["schools"] if s["cn"] == cn)


# ------------------------------------------------------------------ 纯函数


def test_窗口_只走prev_before链_回溯不到就停():
    avail = ["201903", "201905", "202607", "202609"]
    # 起点就是最早一期：往前取不到，窗口就一期，不编造期次
    assert panel_mod._window(avail, "201903", 6) == ["201903"]
    # 双月出刊：202607 的上一期是 202605 而不是日历上的 202606，这里用真实序列验证跳期
    assert panel_mod._window(avail, "202609", 2) == ["202607", "202609"]
    # n 大于可用期数：不补空位，窗口自然变短
    assert panel_mod._window(avail, "202609", 9) == ["201903", "201905", "202607", "202609"]


def test_学科参数_中英都认_顺序规范():
    assert panel_mod._pick_disciplines(None) == list(DISCIPLINES)
    assert panel_mod._pick_disciplines(["临床医学"]) == ["Clinical Medicine"]
    assert panel_mod._pick_disciplines("化学、工程学") == ["Chemistry", "Engineering"]
    # 输出按 DISCIPLINES 的字母序，与入参顺序无关（确定性）
    assert panel_mod._pick_disciplines(["工程学", "化学"]) == ["Chemistry", "Engineering"]


def test_学科参数_写错就报错_不猜():
    with pytest.raises(ValueError, match="不认识的学科"):
        panel_mod._pick_disciplines(["临床"])          # 简称不算，不做模糊
    with pytest.raises(ValueError, match="为空"):
        panel_mod._pick_disciplines([])


def test_期次写错就报错_不静默回退():
    with pytest.raises(ValueError, match="没有 202610"):
        panel(["昆明理工大学"], period_end="202610")
    with pytest.raises(ValueError, match="n 至少为 1"):
        panel(["昆明理工大学"], period_end="202609", n=0)


# ------------------------------------------------------------------ 基线


def test_六期窗口与三校上榜数(full):
    assert full["periods"] == PERIODS
    assert full["missing"] == []
    assert full["period_end"] == "202609"
    assert _counts(full, "昆明理工大学") == [12] * 6
    assert _counts(full, "海南大学") == [9, 10, 11, 11, 11, 12]
    assert _counts(full, "云南大学") == [13, 13, 14, 14, 14, 14]
    assert all(s["status"] == "ok" for s in full["schools"])
    assert all(s["match"] == "map" for s in full["schools"])


def test_末期满血交集十个学科(full):
    assert full["common"] == COMMON_10
    assert full["summary"]["common_count"] == 10


def test_各自另有的学科(full):
    assert full["only"]["昆明理工大学"] == KUNMING_ONLY
    assert full["only"]["海南大学"] == HAINAN_ONLY
    # 云大 14 个学科里，不在共同 10 个中的是这四个
    assert full["only"]["云南大学"] == [
        "Clinical Medicine", "Mathematics", "Microbiology", "Social Sciences, General"]


def test_学科进出(full):
    haikou = _school(full, "海南大学")
    assert [(e["period"], e["disc"]) for e in haikou["entered"]] == [
        ("202601", "Microbiology"),
        ("202603", "Pharmacology & Toxicology"),
        ("202609", "Geosciences"),
    ]
    assert haikou["exited"] == []
    assert _school(full, "昆明理工大学")["entered"] == []


def test_事件_海大末期满血追平昆工(full):
    overtakes = [e for e in full["events"] if e["kind"] == "overtake"]
    assert len(overtakes) == 1
    ev = overtakes[0]
    assert (ev["school"], ev["period"], ev["index"], ev["value"]) == ("昆明理工大学", "202609", 5, 12)
    assert ev["meta"]["with"] == "海南大学"
    assert ev["meta"]["gap"] == 0
    # 事件由 events.detect 算出，不是模型写的
    assert full["events"].meta == {}


def test_事件_昆工六期持平(full):
    flat = [e for e in full["events"] if e["kind"] == "flat" and e["school"] == "昆明理工大学"]
    assert len(flat) == 1
    assert flat[0]["meta"]["run_len"] == 6


def test_网格全量_摘要只给数字(full):
    # 前端要的那份：期末 × 学科，长 12
    assert len(full["grid"]["sets"]["昆明理工大学"]["202609"]) == 12
    assert set(full["grid"]["counts"]) == {"昆明理工大学", "海南大学", "云南大学"}
    # 进模型的那份：不含矩阵
    assert "grid" not in full["summary"]
    assert set(full["summary"]) == {"periods", "schools", "common_count", "events"}


def test_确定性_除生成时间外两次一致(full):
    again = panel(["昆明理工大学", "海南大学", "云南大学"], period_end="202609", n=6)
    a, b = dict(full), dict(again)
    a.pop("source"), b.pop("source")
    assert a == b
    assert again["source"]["period"] == "202609"


def test_取数走缓存_第二次不重新读表(full):
    before = panel_mod._rows.cache_info()
    panel(["昆明理工大学", "海南大学"], period_end="202609", n=2)
    assert panel_mod._rows.cache_info().hits > before.hits


# ------------------------------------------------------------------ 三态


def test_校名查不到_该校absent_其余照常(full):
    got = panel(["昆明理工大学", "昆明学院", "海南大学"], period_end="202609", n=6)
    absent = _school(got, "昆明学院")
    assert absent["status"] == "absent"
    assert absent["match"] == "absent"
    assert absent["counts"] == [None] * 6          # 不是 0：名字没对上就不替它下结论
    assert "整校未进入 ESI" in absent["note"]
    # 其余两校的数字与基线逐期一致，没被拖下水
    assert _counts(got, "昆明理工大学") == _counts(full, "昆明理工大学")
    assert _counts(got, "海南大学") == _counts(full, "海南大学")
    assert got["common"] == full["common"]


def test_校名对上多家_该校error_其余照常(full):
    got = panel(["昆明理工大学", "DALI", "海南大学"], period_end="202609", n=6)
    bad = _school(got, "DALI")
    assert bad["status"] == "error"
    assert bad["counts"] == [None] * 6
    assert "对上了多家机构" in bad["note"]
    assert _counts(got, "昆明理工大学") == _counts(full, "昆明理工大学")
    # 出错的学校不进事件：一条假的「连续 6 期持平」比没有事件更糟
    assert all(e["school"] != "DALI" for e in got["events"])


# ------------------------------------------------------------------ 小窗口


def test_小窗口两期(full):
    got = panel(["昆明理工大学", "海南大学"], period_end="202609", n=2)
    assert got["periods"] == ["202607", "202609"]
    assert _counts(got, "海南大学") == [11, 12]
    assert got["only"]["海南大学"] == ["Microbiology", "Social Sciences, General"]


def test_学科过滤_只看一个学科(full):
    got = panel(["昆明理工大学", "海南大学", "云南大学"],
                disciplines=["临床医学"], period_end="202609", n=2)
    assert got["disciplines"] == ["Clinical Medicine"]
    assert _counts(got, "昆明理工大学") == [1, 1]
    assert _counts(got, "海南大学") == [0, 0]
    assert _counts(got, "云南大学") == [1, 1]
    assert got["common"] == []
