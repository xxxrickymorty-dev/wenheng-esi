# -*- coding: utf-8 -*-
"""R2-4【S1】1‰ 进入时间的三态：已进入 / 有年数 / 估不出。

红队第二轮（`docs/reviews/2026-10-28-ADR0014-对抗性审查-第二轮.md` R2-4）：
`permille_years_est` 用 `-(-(100 - prox) // growth)` 估年数，`prox` 略超 100 时
`0.5 // 30.0 → 0.0`、取负成 **-0.0**；而 `sentences.build` 用 `if years:` 判定，
`-0.0` 是假 → 同一段里前半句说「其中已有学科进入前1‰」，后半句说「尚难估算」。

修法：`prox >= 100` 直接给 `None`（表示「已进入」，不是「算不出」），句子按
`is not None` 三态分流。
"""
import math
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                   # noqa: E402

import compute                                                  # noqa: E402
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


class Test年数估算:
    def test_已进入前千分之一给None而不是负数(self):
        """`prox=105, prev=100`：学科已进入，年数没有意义。"""
        assert compute.permille_years(105, 100) is None

    def test_略超100不再产出负零(self):
        """旧写法在这里给 `-0.0`（`0.5 // 30.0 → 0.0` 再取负），而 `-0.0` 是假值。"""
        assert compute.permille_years(100.5, 95.0) is None

    def test_永不返回负零(self):
        for prox, prev in [(99.9, 99.5), (99.99, 99.0), (50.0, 49.9),
                           (100.0, 100.0), (105.0, 100.0), (56.74, 55.13)]:
            y = compute.permille_years(prox, prev)
            assert y is None or math.copysign(1.0, y) > 0, f"{prox}/{prev} → {y!r}"

    @pytest.mark.parametrize("prox, prev, want", [
        (56.74, 55.13, 5.0),        # (100-56.74)/9.66 = 4.48 → 5 年（202609 实测口径）
        (99.9, 99.4, 1.0),          # 0.1/3.0 → 1 年
    ])
    def test_未进入时仍按上期增速外推(self, prox, prev, want):
        assert compute.permille_years(prox, prev) == want

    def test_没增速或没上期值给None(self):
        assert compute.permille_years(56.74, None) is None
        assert compute.permille_years(56.74, 56.74) is None     # 增速 0
        assert compute.permille_years(56.74, 56.73) is None     # 增速 0.06 百分点/年 < 0.1


class Test正文三态:
    def _p2(self, prox, years):
        facts = {**FACTS,
                 "best_1permille": {"discipline": "Plant & Animal Science",
                                    "prox_pct": prox,
                                    "prox_prev_pct": prox - 1.0},
                 "permille_years_est": years}
        return sentences.build(facts, "202609", "202607")["p2"]

    def test_已进入时不说尚难估算(self):
        """要求的那一条：prox=105, prev=100 → 正文出现「已进入」、不出现「尚难估算」。"""
        p2 = self._p2(105.0, compute.permille_years(105.0, 100.0))
        assert "已进入" in p2, p2
        assert "尚难估算" not in p2, p2

    def test_有年数时说年数(self):
        p2 = self._p2(99.9, 1.0)
        assert "预计还需要1.0年左右" in p2, p2
        assert "已进入" not in p2 and "尚难估算" not in p2

    def test_估不出时才说尚难估算(self):
        p2 = self._p2(56.74, None)
        assert "尚难估算" in p2, p2
        assert "已进入" not in p2

    def test_年数为0也当有值(self):
        """`if years:` 的坑：0.0 是假值，会被说成「尚难估算」—— 0 年也是答案。"""
        p2 = self._p2(99.0, 0.0)
        assert "预计还需要0.0年左右" in p2, p2
        assert "尚难估算" not in p2
