# -*- coding: utf-8 -*-
"""契约 #22：接口层学科名中文化（facts / forecast board）。

只动接口响应——磁盘产物（`overview_facts.json` / `预测选模与过线.md`）保持英文，
逐格溯源链不断；前端因此能删掉自己的两处名字桥（`Report.tsx` / `Forecast.tsx`）。
"""
import copy
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _guard_registry import skip_unless                          # noqa: E402
from server.app import _localize_facts                           # noqa: E402
from server.forecasting import _board_row, board_context         # noqa: E402

#: 与 out/202607/overview_facts.json 同型的最小样本（只保留本契约会碰的键）
FACTS = {
    "n_disc_1pct": 14,
    "top3_by_top_papers": [["Chemistry", 44], ["Materials Science", 36],
                           ["Plant & Animal Science", 29]],
    "best_1permille": {"discipline": "Plant & Animal Science",
                       "prox_pct": 55.13, "prox_prev_pct": 53.62},
    "top2_prox_change": [["Engineering", 33.87], ["Plant & Animal Science", 33.3]],
    "worst_cn_rank": {"discipline": "Pharmacology & Toxicology", "drop": 4, "rank": 139},
    "top3_groups": [[44, ["Chemistry"]], [36, ["Materials Science"]],
                    [29, ["Engineering", "Plant & Animal Science"]]],
    "top2_not_entered": [
        {"discipline": "Molecular Biology & Genetics", "prox_pct": 84.5, "chg": 3.57},
        {"discipline": "Physics", "prox_pct": 75.13, "chg": 4.77},
    ],
    "coverage_window": "2016.1.1-2026.4.30",
    "prev_label": "2026年5月",
}


class TestFacts中文化:
    def test_五处展示位换中文(self):
        out = _localize_facts(copy.deepcopy(FACTS))
        assert out["best_1permille"]["discipline"] == "植物与动物学"
        assert out["worst_cn_rank"]["discipline"] == "药理学与毒理学"
        assert [d["discipline"] for d in out["top2_not_entered"]] == \
            ["分子生物学与遗传学", "物理学"]
        assert out["top3_by_top_papers"][0] == ["化学", 44]
        assert out["top3_groups"][2] == [29, ["工程学", "植物与动物学"]]
        assert out["top2_prox_change"][0] == ["工程学", 33.87]

    def test_未知名原样保留(self):
        out = _localize_facts({"best_1permille": {"discipline": "某某新学科", "prox_pct": 1.0}})
        assert out["best_1permille"]["discipline"] == "某某新学科"

    def test_缺键不炸(self):
        assert _localize_facts({}) == {}

    def test_数字与其它键不动(self):
        out = _localize_facts(copy.deepcopy(FACTS))
        assert out["n_disc_1pct"] == 14
        assert out["best_1permille"]["prox_pct"] == 55.13
        assert out["top3_by_top_papers"][0][1] == 44
        assert out["coverage_window"] == "2016.1.1-2026.4.30"


class TestBoard中文化:
    def test_board行学科换中文(self):
        cells = ["Molecular Biology & Genetics", "季节性ETS模型", "1.91%", "2.10%",
                 "84.50%", "100%", "15.50%", "是", "84.50%", "202707", "202801", ""]
        row = _board_row(cells)
        assert row["subject"] == "分子生物学与遗传学"
        assert row["model"] == "季节性ETS模型"
        assert row["prox"] == 84.5

    def test_真md的学科全出中文(self):
        md = REPO / "out" / "202607" / "预测选模与过线.md"
        if not md.exists():
            skip_unless("out/202607 无预测选模与过线.md（产物不入库，属正常）",
                        lambda: md.exists())
        ctx = board_context("202607")
        subs = ([r["subject"] for r in ctx["routes"]["citation"]]
                + [r["subject"] for r in ctx["routes"]["rank"]])
        assert subs, "选模表应有两条路线的学科"
        assert all(not any(ch.isascii() and ch.isalpha() for ch in s) for s in subs), subs
