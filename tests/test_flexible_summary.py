# -*- coding: utf-8 -*-
"""flexible.summary（统计摘要 + 规则异常检测）回归。

红线第三层落点：摘要给模型看、但标 `planning_input` 不是 `quotable`；
异常检测**纯规则**（环比倍数越界 / 排名连续同向 / 接近度跨 1），
不用模型、没有幻觉空间——判据本身要钉住。

LedgerView 是 Protocol（鸭子类型），用假视图注入合成数据，不依赖真实台账。
"""
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from flexible import summary  # noqa: E402

PERIODS = ["202601", "202603", "202605", "202607"]
DISCS = ["AGRI", "BIO", "CHEM"]

# (metric, period) → {discipline: value}
_RANK = {
    "202601": {"AGRI": 110, "BIO": 48, "CHEM": 13},
    "202603": {"AGRI": 100, "BIO": 49, "CHEM": 11},
    "202605": {"AGRI": 95, "BIO": 50, "CHEM": 9},
    "202607": {"AGRI": 90, "BIO": 51, "CHEM": 7},
}
_PROX = {
    "202605": {"AGRI": 0.90, "BIO": 1.05, "CHEM": 0.50},
    "202607": {"AGRI": 0.95, "BIO": 0.98, "CHEM": 0.50},
}
_CITES = {"202605": {"AGRI": 100.0, "BIO": 40.0}, "202607": {"AGRI": 300.0, "BIO": 44.0}}


class FakeView:
    """LedgerView 协议的最小假实现：只喂 summary/anomalies 会碰到的面。"""

    periods = list(PERIODS)
    disciplines = list(DISCS)

    def current_period(self):
        return self.periods[-1]

    def cross(self, metric, period):
        if metric == "rank":
            return pd.Series(_RANK[period])
        if metric == "proximity_1pct":
            return pd.Series(_PROX.get(period, {}))
        if metric == "total_cites":
            return pd.Series(_CITES.get(period, {}))
        return pd.Series(dtype=float)

    def series(self, metric, disc):
        if metric == "rank":
            return pd.Series({p: _RANK[p][disc] for p in PERIODS})
        return pd.Series(dtype=float)

    def chain(self, metric, disc, period):
        return {"metric": metric, "discipline": disc, "period": str(period)}

    def entered_1pct(self):
        return pd.DataFrame({
            p: {d: (1 if (p == "202607" and d == "AGRI") else 0) for d in DISCS}
            for p in PERIODS})


# ---------------------------------------------------------------- summarize

def test_摘要_标记为规划依据_不可引用():
    s = summary.summarize(FakeView(), "202607")
    assert s["trust"] == "planning_input"
    assert "planning_input" in s["note"] and "不是可引用数值" in s["note"]
    assert s["period"] == "202607" and s["prev"] == "202605"
    assert s["period_label"] == "2026年7月"


def test_摘要_排名升降三分_带来源链():
    s = summary.summarize(FakeView(), "202607")
    # 202605→202607：AGRI 95→90（升）BIO 50→51（降）CHEM 9→7（升）
    assert s["rank_moves"] == {"up": 2, "down": 1, "flat": 0}
    assert s["rank_worst"][0]["discipline"] == "BIO"          # delta 最小在前
    assert s["rank_worst"][0]["delta"] == -1
    assert s["rank_best"][0]["discipline"] == "AGRI"          # delta 最大在前（+5）
    assert s["rank_best"][0]["source"] == {"metric": "rank", "discipline": "AGRI",
                                           "period": "202607"}
    assert s["n_entered_1pct"] == 1


def test_摘要_接近度涨跌榜与潜力学科():
    s = summary.summarize(FakeView(), "202607")
    assert s["prox_risers"][0]["discipline"] == "AGRI"        # +5.0pp
    assert s["prox_risers"][0]["chg_pp"] == 5.0
    assert s["prox_fallers"][0]["discipline"] == "BIO"        # -7.0pp
    # 潜力＝接近度 <1 按降序：BIO 0.98 > AGRI 0.95 > CHEM 0.50
    assert s["potential"] == ["BIO", "AGRI", "CHEM"]
    assert s["n_potential"] == 3


# ---------------------------------------------------------------- anomalies

def test_异常_环比倍数越界():
    a = summary.anomalies(FakeView(), "202607", threshold=1.5)
    jumps = [(x["discipline"], x["metric"]) for x in a["jumps"]]
    assert ("AGRI", "total_cites") in jumps                   # 100→300 比值 3
    assert ("BIO", "total_cites") not in jumps                # 40→44 比值 1.1，正常
    assert a["trust"] == "planning_input"


def test_异常_排名连续同向():
    a = summary.anomalies(FakeView(), "202607")
    st = {x["discipline"]: x for x in a["streaks"]}
    # CHEM 四期 13→11→9→7 连续同向（序列值方向持续下降）
    assert "CHEM" in st
    assert st["CHEM"]["delta_total"] == -6
    assert len(st["CHEM"]["periods"]) == 4
    assert "AGRI" in st                                        # 110→100→95→90 也连续同向


def test_异常_接近度跨越1():
    a = summary.anomalies(FakeView(), "202607")
    cross = {x["discipline"]: x for x in a["cross_1pct"]}
    assert cross["BIO"]["direction"] == "跌破100%"
    assert cross["BIO"]["from"] == 1.05 and cross["BIO"]["to"] == 0.98
    assert "AGRI" not in cross                                 # 0.90→0.95 未跨 1
    # n＝三类之和
    assert a["n"] == len(a["jumps"]) + len(a["streaks"]) + len(a["cross_1pct"])
