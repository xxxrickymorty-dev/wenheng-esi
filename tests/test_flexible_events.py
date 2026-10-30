# -*- coding: utf-8 -*-
"""事件检测（`flexible/events.py`）的验收用例。

基线是 202609 期实测的三条线（昆工 6 期 12 不动、海大从 9 追到 12、云大
202603 涨到 14 后走平），配 202609 真实学科清单做 `sets`。合成用例只用于
覆盖基线数据测不到的判据（拐点、追平后连续并列、缺期视为无数据）。
"""
from __future__ import annotations

import json

import pytest

from flexible.events import detect

PERIODS = ["202511", "202601", "202603", "202605", "202607", "202609"]

COUNTS = {
    "昆明理工大学": [12, 12, 12, 12, 12, 12],
    "海南大学": [9, 10, 11, 11, 11, 12],
    "云南大学": [13, 13, 14, 14, 14, 14],
}

#: 202609 实测：昆工 12 个学科、海大 12 个学科（海大多的那个是 Microbiology）。
KUNMING_12 = [
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
    "Computer Science", "Engineering", "Environment Ecology", "Geosciences",
    "Materials Science", "Molecular Biology & Genetics", "Pharmacology & Toxicology",
    "Plant & Animal Science",
]
HAINAN_12 = [
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Computer Science",
    "Engineering", "Environment Ecology", "Geosciences", "Materials Science",
    "Microbiology", "Pharmacology & Toxicology", "Plant & Animal Science",
    "Social Sciences, General",
]


def _sets() -> dict[str, dict[str, list[str]]]:
    """海大 202511 尚无 Microbiology，202601 起进入——即基线里那条 enter。"""
    hainan = {p: list(HAINAN_12) for p in PERIODS}
    hainan["202511"] = [d for d in HAINAN_12 if d != "Microbiology"]
    return {
        "昆明理工大学": {p: list(KUNMING_12) for p in PERIODS},
        "海南大学": hainan,
    }


def _of(events, kind):
    return [e for e in events if e["kind"] == kind]


def _one(events, **want):
    """按字段筛唯一一条；不唯一直接失败，免得断言被多条事件蒙过。"""
    hit = [e for e in events if all(e[k] == v for k, v in want.items())]
    assert len(hit) == 1, f"{want} 命中 {len(hit)} 条：{hit}"
    return hit[0]


# ------------------------------------------------------------------ 基线三条


def test_海大在202609追平昆工():
    """上期 12 > 11、本期 12 <= 12：交叉，school 记被追上的昆工。"""
    ev = _one(detect(PERIODS, COUNTS), kind="overtake", period="202609")
    assert ev["school"] == "昆明理工大学"
    assert ev["index"] == 5
    assert ev["value"] == 12
    assert ev["text"] == "6 期追平昆明理工"
    assert ev["meta"]["with"] == "海南大学"
    assert ev["meta"]["gap"] == 0
    assert ev["meta"]["loser_prev"] == 12 and ev["meta"]["winner_prev"] == 11


def test_昆工六期不变报末段持平():
    ev = _one(detect(PERIODS, COUNTS), kind="flat", school="昆明理工大学")
    assert ev["period"] == "202609"
    assert ev["index"] == 5
    assert ev["value"] == 12
    assert ev["text"] == "连续 6 期持平"
    assert ev["meta"]["run_len"] == 6 and ev["meta"]["run_start"] == 0


def test_云大202603之后走平按flat报():
    """涨到 14 后走平：末段 4 期相等 → flat（不报 inflect，判据见模块 docstring）。"""
    events = detect(PERIODS, COUNTS)
    ev = _one(events, kind="flat", school="云南大学")
    assert ev["period"] == "202609"
    assert ev["text"] == "连续 4 期持平"
    assert ev["meta"]["start_period"] == "202603"
    assert not _of(events, "inflect")                 # 步长 0 不算变号


def test_基线只出这三条():
    """不多标：无 sets 时正好 overtake 1 + flat 2，且按 index 升序。"""
    events = detect(PERIODS, COUNTS)
    assert len(events) == 3
    assert [e["index"] for e in events] == [5, 5, 5]
    assert [e["kind"] for e in events] == ["overtake", "flat", "flat"]


# ------------------------------------------------------------------ enter/exit


def test_海大202601新进微生物学():
    ev = _one(detect(PERIODS, COUNTS, _sets()), kind="enter", school="海南大学")
    assert ev["period"] == "202601"
    assert ev["index"] == 1
    assert ev["value"] == 10
    assert ev["text"] == "新进 1 个学科：微生物学"
    assert ev["meta"]["disciplines"] == ["微生物学"]
    assert ev["meta"]["stems"] == ["Microbiology"]
    assert ev["meta"]["prev_period"] == "202511"


def test_sets为空时不出enter_exit():
    events = detect(PERIODS, COUNTS)
    assert not _of(events, "enter") and not _of(events, "exit")


def test_同期多学科合并成一条且最多列两个():
    sets = _sets()
    sets["海南大学"]["202605"] = [d for d in HAINAN_12 if d != "Microbiology"]
    events = detect(PERIODS, COUNTS, sets)
    ev = _one(events, kind="exit", school="海南大学", period="202605")
    assert ev["text"] == "退出 1 个学科：微生物学"
    assert ev["value"] == 11
    # 202607 又回来，是一条新的 enter（202609 起保持在场，不再报）
    back = _one(events, kind="enter", school="海南大学", period="202607")
    assert back["meta"]["count"] == 12 and back["value"] == 11


def test_三学科以上用等字收尾():
    counts = {"海南大学": [5, 9], "昆明理工大学": [12, 12]}
    sets = {
        "海南大学": {"202511": [], "202601": ["Chemistry", "Microbiology", "Geosciences",
                                            "Engineering"]},
        "昆明理工大学": {"202511": KUNMING_12, "202601": KUNMING_12},
    }
    ev = _one(detect(["202511", "202601"], counts, sets), kind="enter")
    assert ev["text"] == "新进 4 个学科：化学、地球科学等"    # 先中文名排序，再截两个


def test_缺期视为无数据不出event():
    """sets 里没有 202601 这一期 → 202511→202601、202601→202603 两对都不判。"""
    sets = _sets()
    del sets["海南大学"]["202601"]
    events = detect(PERIODS, COUNTS, sets)
    assert not _of(events, "enter")
    assert not _of(events, "exit")


# ------------------------------------------------------------------ 拐点/持平


def test_拐点记在掉头后那一期():
    counts = {"海大": [10, 12, 11]}
    ev = _one(detect(["202511", "202601", "202603"], counts), kind="inflect")
    assert ev["period"] == "202603" and ev["index"] == 2 and ev["value"] == 11
    assert ev["text"] == "3 期转跌"
    assert ev["meta"] == {"prev_step": 2, "step": -1, "peak_index": 1,
                          "peak_period": "202601"}

    up = _one(detect(["202511", "202601", "202603"], {"海大": [12, 10, 11]}), kind="inflect")
    assert up["text"] == "3 期转涨" and up["value"] == 11


def test_微抖动不算拐点():
    """0.5 的步子够不上 1，0 更不算变号——两种都不出 inflect。"""
    assert not _of(detect(["a", "b", "c"], {"X": [10, 10.5, 10]}), "inflect")
    assert not _of(detect(["a", "b", "c"], {"X": [10, 12, 12]}), "inflect")


def test_追平后连续并列只报一次():
    counts = {"A": [10, 10, 10, 10], "B": [9, 10, 10, 10]}
    events = _of(detect(["p1", "p2", "p3", "p4"], counts), "overtake")
    assert len(events) == 1 and events[0]["period"] == "p2"
    assert events[0]["school"] == "A" and events[0]["meta"]["gap"] == 0


def test_中间平台不报只报末段():
    """A 中间平过 3 期，末段只有 2 期平 → 一条都不报（末段不达标）。"""
    counts = {"A": [10, 10, 10, 12, 13]}
    assert not _of(detect(["p1", "p2", "p3", "p4", "p5"], counts), "flat")


def test_反超时措辞换成反超():
    counts = {"A": [10, 12], "B": [9, 13]}
    ev = _one(detect(["202511", "202601"], counts), kind="overtake")
    assert ev["school"] == "A" and ev["value"] == 12
    assert ev["text"] == "2 期反超A" and ev["meta"]["gap"] == 1


# ------------------------------------------------------------------ 不炸/确定性


@pytest.mark.parametrize("periods,counts", [
    ([], {}),
    (["202609"], {"昆工": [12]}),
    (PERIODS, {"昆工": [12, 12]}),                        # 长度不等
    (PERIODS, {"昆工": [12] * 5 + ["12"]}),               # 非数值
    (["202511", "202511"], {"昆工": [1, 2]}),             # 期次重复
    (PERIODS, {"昆工": 12}),                              # 不是列表
])
def test_坏输入返回空列表不抛异常(periods, counts):
    res = detect(periods, counts)
    assert res == [] and isinstance(res, list)


def test_长度不等时错误原因在meta里():
    res = detect(PERIODS, {"昆明理工大学": [12, 12]})
    assert res == []
    assert "2 期" in res.meta["error"] and "6 期" in res.meta["error"]


def test_单期与空输入不算错():
    assert detect([], {}).meta.get("error") is None
    assert detect(["202609"], {"昆工": [12]}).meta.get("error") is None


def test_结构错误写进meta不抛异常():
    res = detect(PERIODS, COUNTS, {"海南大学": {"202601": "Microbiology"}})
    assert res == [] and "不是列表" in res.meta["error"]
    assert detect(PERIODS, COUNTS, "sets").meta["error"] == "sets 必须是字典"


def test_同一输入十次输出完全一致():
    outs = {json.dumps(detect(PERIODS, COUNTS, _sets()), ensure_ascii=False, indent=2)
            for _ in range(10)}
    assert len(outs) == 1


def test_返回按index升序():
    idx = [e["index"] for e in detect(PERIODS, COUNTS, _sets())]
    assert idx == sorted(idx)
