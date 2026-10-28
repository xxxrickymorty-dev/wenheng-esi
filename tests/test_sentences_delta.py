# -*- coding: utf-8 -*-
"""R2-1【S0】下降期不许写成「增加-11篇」—— 方向词由符号决定，负号不进正文。

红队第二轮（`docs/reviews/2026-10-28-ADR0014-对抗性审查-第二轮.md` R2-1）：
`src/sentences.py` 里 p4 与 top_section 两处都写死了「较上期总数增加{delta}篇」，
202605 期 `top_papers_delta = -11`，成品 docx 里就出现了「较上期总数增加-11篇」。

同族两处一起钉：位次降幅为 0 时的「较大降幅…下降0位」、两点变动里 c2 为负的
「分别上升X%和-3.00%」。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                   # noqa: E402

import sentences                                                # noqa: E402


#: 只保留 `build()` 会读的键（形状与 out/202609 的 facts 同型；不依赖 out/）
FACTS = {
    "best_1permille": {"discipline": "Plant & Animal Science", "prox_pct": 56.74,
                       "prox_prev_pct": 55.13},
    "top2_prox_change": [("Plant & Animal Science", 48.39), ("Engineering", 40.40)],
    "worst_cn_rank": {"discipline": "Materials Science", "drop": 2, "rank": 181},
    "any_1permille": False,
    "permille_years_est": 5,
    "n_disc_1pct": 14,
    "prev_label": "2026年7月",
    "rank_intl_now": 973, "rank_intl_delta": 22,
    "rank_cn_inst_now": 154, "rank_cn_inst_delta": 1,
    "rank_cn_uni_now": 128, "rank_cn_uni_delta": 2,
    "top_papers_now": 252, "top_papers_prev": 263, "top_papers_delta": -11,
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

#: 两处调用点各一份（p4 与 top_section 的**四个**分支都要覆盖）
TEXT_KEYS = ("p4", "top_section")


class Test增减短语:
    @pytest.mark.parametrize("delta, want", [
        (-11, "减少11篇"),
        (0, "持平"),
        (14, "增加14篇"),
    ])
    def test_符号决定方向词(self, delta, want):
        assert sentences._delta_phrase(delta) == want

    def test_下降不再带负号(self):
        for delta in (-11, -1, -100):
            assert "-" not in sentences._delta_phrase(delta)[1:].lstrip("0123456789")


class Test顶尖论文段:
    """p4 与 top_section 各两分支（有/无学院统计）—— 四处都不得出「增加-」。"""

    @pytest.mark.parametrize("delta", [-11, 0, 14])
    @pytest.mark.parametrize("college", [None, {"units": [
        {"unit": "化学科学与工程学院", "papers": 44, "cites": 1200.0, "subjects": ["Chemistry"]},
        {"unit": "生命科学学院", "papers": 33, "cites": 900.0,
         "subjects": ["Plant & Animal Science"]},
        {"unit": "材料与能源学院", "papers": 27, "cites": 800.0, "subjects": ["Materials Science"]},
    ], "n_subjects": 12, "n_units": 3,
        "by_papers": [{"unit": "化学科学与工程学院", "papers": 44},
                      {"unit": "生命科学学院", "papers": 33},
                      {"unit": "材料与能源学院", "papers": 27}],
        "by_cites": [("化学科学与工程学院", 40.1), ("生命科学学院", 30.2),
                     ("材料与能源学院", 29.7)]}])
    def test_四个分支都不出现增加负号(self, delta, college):
        facts = {**FACTS, "top_papers_delta": delta}
        texts = sentences.build(facts, "202605", "202603", college=college)
        for key in TEXT_KEYS:
            assert "增加-" not in texts[key], texts[key]
            assert "增加-" not in sentences._delta_phrase(delta)

    def test_下降期写减少(self):
        texts = sentences.build({**FACTS, "top_papers_delta": -11}, "202605", "202603")
        for key in TEXT_KEYS:
            assert "较上期总数减少11篇" in texts[key], texts[key]
            assert "增加" not in texts[key].split("。")[0]

    def test_持平时不带数字(self):
        texts = sentences.build({**FACTS, "top_papers_delta": 0}, "202605", "202603")
        for key in TEXT_KEYS:
            assert "较上期总数持平" in texts[key], texts[key]
            assert "持平篇" not in texts[key]


class Test同族两处:
    def test_降幅为0时不说较大降幅也不说下降0位(self):
        facts = {**FACTS, "worst_cn_rank": {"discipline": "Materials Science",
                                            "drop": 0, "rank": 181}}
        texts = sentences.build(facts, "202605", "202603")
        for key in ("p3", "situation"):
            assert "下降0位" not in texts[key], texts[key]
            assert "较大降幅" not in texts[key], texts[key]
            assert "持平" in texts[key], texts[key]

    def test_有降幅时原句不变(self):
        """drop>0 时逐字保持旧措辞 —— 措辞档位回归靠这条不被打歪。"""
        texts = sentences.build(FACTS, "202605", "202603")
        assert "继续呈现较大降幅，该学科本期较3月下降了2位，国内排名为181。" in texts["p3"]
        assert "继续呈现排名下降现象，本期较3月下降了2位，国内排名为181。" in texts["situation"]

    @pytest.mark.parametrize("c1, c2, want", [
        (48.39, 40.40, "分别上升48.39%和40.40%"),
        (48.39, -3.0, "分别上升48.39%和下降3.00%"),
        (-1.5, -3.0, "分别下降1.50%和下降3.00%"),
    ])
    def test_两点变动按符号取词(self, c1, c2, want):
        assert sentences._pct_pair(c1, c2) == want
        facts = {**FACTS,
                 "top2_prox_change": [("Plant & Animal Science", c1), ("Engineering", c2)]}
        texts = sentences.build(facts, "202605", "202603")
        for key in ("p3", "situation"):
            assert want in texts[key], texts[key]
            assert "上升-" not in texts[key]
