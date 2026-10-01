# -*- coding: utf-8 -*-
"""预测章模型说明句：纯函数分档 + `build(forecast=…)` 组装。

守卫的是 rick 2026-09-23 的定稿样式：
  有 forecast_charts.json（V1 推荐模型结果）→ 模型名 + 两线交叉期 + 结论年份**必须**
  出现在段落里；缺预测图 → 段落退回 `【手工：…】` 槽（可复现性优先）。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                   # noqa: E402

import period                                                   # noqa: E402
import sentences                                                # noqa: E402

#: 与 out/202609 同型的最小 facts（只保留 build() 会读的键）
FACTS = {
    "best_1permille": {"discipline": "Plant & Animal Science", "prox_pct": 56.74,
                       "prox_prev_pct": 55.13},
    "top2_prox_change": [("Plant & Animal Science", 48.39), ("Engineering", 40.40)],
    "worst_cn_rank": {"discipline": "Materials Science", "drop": 2, "rank": 181},
    "any_1permille": False,
    "permille_years_est": 5,
    "n_disc_1pct": 14,
    "prev_label": "2026年7月",
    "rank_intl_now": 973, "rank_intl_prev": 995, "rank_intl_delta": 22,
    "rank_cn_inst_now": 154, "rank_cn_inst_delta": 1,
    "rank_cn_uni_now": 128, "rank_cn_uni_delta": 2,
    "top_papers_now": 291, "top_papers_prev": 274, "top_papers_delta": 17,
    "top3_groups": [(44, ["Chemistry"])],
    "rank_up": 7, "rank_down": 8, "rank_flat": 7,
    "coverage_window": "2016.1.1-2026.6.30",
    "top2_not_entered": [
        {"discipline": "Molecular Biology & Genetics", "prox_pct": 88.01, "chg": 3.51,
         "prox_tail": [0.7326, 0.745, 0.7718, 0.7809, 0.8093, 0.845, 0.8801]},
        {"discipline": "Physics", "prox_pct": 81.21, "chg": 6.08,
         "prox_tail": [0.6506, 0.6411, 0.6696, 0.6972, 0.7036, 0.7513, 0.8121]},
    ],
}

#: 与 out/202609/forecast_charts.json 同型（模型不同名 / 同名各一组）
FORECAST = [
    {"index": 1, "subject": "分子生物学与遗传学", "task": "citation",
     "model": "季节性ETS模型", "first_crossing": 202709},
    {"index": 1, "subject": "分子生物学与遗传学", "task": "rank",
     "model": "阻尼Holt模型", "first_crossing": 202705},
    {"index": 2, "subject": "物理学", "task": "citation",
     "model": "经验贝叶斯状态空间模型", "first_crossing": 202801},
    {"index": 2, "subject": "物理学", "task": "rank",
     "model": "经验贝叶斯状态空间模型", "first_crossing": 202711},
]


class Test纯函数:
    def test_同名模型用得到预测显示(self):
        s = sentences._cross_clauses("经验贝叶斯状态空间模型", "经验贝叶斯状态空间模型",
                                     202801, 202711)
        assert "得到的预测显示" in s
        assert "2028年1月" in s and "2027年11月" in s

    def test_不同模型用分别对两个指标预测(self):
        s = sentences._cross_clauses("季节性ETS模型", "阻尼Holt模型", 202709, 202705)
        assert "分别对被引频次、国内排名进行预测" in s
        assert "2027年9月" in s and "2027年5月" in s

    def test_交叉期缺失不硬编日期(self):
        s = sentences._cross_clauses("A模型", "A模型", None, None)
        assert "尚未" in s and "年" not in s.split("尚未")[1]

    def test_结论年份取较晚交叉期(self):
        assert sentences._eta_goal(202705, 202709) == "可能将在2027年前后实现"
        assert sentences._eta_goal(None, None) == "【手工：预计时间（两线交叉点）】"

    def test_跨年结论用年底至次年初(self):
        assert sentences._eta_expect(202711, 202801) == "有望在2027年底至2028年初进入ESI前1%"
        assert sentences._eta_expect(202705, 202709) == "有望在2027年前后进入ESI前1%"

    def test_趋势措辞按连涨分档(self):
        assert sentences._prox_phrases([0.7, 0.72, 0.75])[0] == "一直呈稳步上升趋势"
        assert sentences._prox_phrases([0.7, 0.69, 0.75])[0] == "呈波动上升趋势"
        assert sentences._prox_phrases([0.7, 0.69, 0.68])[0] == "呈波动趋势"
        assert sentences._prox_phrases([]) == (None, None)


class Test段落组装:
    def test_有预测元数据时填满模型说明(self):
        texts = sentences.build(FACTS, "202609", "202607", forecast=FORECAST)
        fc1, fc2 = texts["forecast_p1"], texts["forecast_p2"]
        assert "【手工" not in fc1 and "【手工" not in fc2
        assert "季节性ETS模型" in fc1 and "阻尼Holt模型" in fc1
        assert "88.01%" in fc1 and "2027年9月" in fc1 and "2027年5月" in fc1
        assert "经验贝叶斯状态空间模型" in fc2 and "2028年1月" in fc2
        assert "2027年底至2028年初" in fc2

    def test_缺预测元数据时保留手工槽(self):
        texts = sentences.build(FACTS, "202609", "202607")
        assert "【手工：趋势描述】" in texts["forecast_p1"]
        assert "【手工：预计时间（两线交叉点）】" in texts["forecast_p1"]
        assert "【手工：发展力度评价】" in texts["forecast_p2"]

    def test_缺prox尾迹时保留手工槽(self):
        facts = {**FACTS, "top2_not_entered": [
            {k: v for k, v in FACTS["top2_not_entered"][0].items() if k != "prox_tail"},
            {k: v for k, v in FACTS["top2_not_entered"][1].items() if k != "prox_tail"},
        ]}
        texts = sentences.build(facts, "202609", "202607", forecast=FORECAST)
        assert "【手工：趋势描述】" in texts["forecast_p1"]

    def test_封面期号走period唯一口径(self):
        """期号数学只允许在 `period.issue_of` 一处；句层不许再写第二套。"""
        assert sentences.build(FACTS, "202607", "202605")["cover_issue"] \
            == "2026年第4期（总第38期）"
        assert sentences.build(FACTS, "202601", "202511")["cover_issue"] \
            == "2026年第1期（总第35期）"

    def test_早于锚点不给假期号(self):
        with pytest.raises(period.PeriodBeforeAnchor):
            sentences.build(FACTS, "201903", "201901")
