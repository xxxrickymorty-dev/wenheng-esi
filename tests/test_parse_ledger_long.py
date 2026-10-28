# -*- coding: utf-8 -*-
"""`parse_ledger.long_table()`：长表新增 `threshold_1permille` / `entered_1pct`。

这三张表（1‰ 阈值、进入前 1% 状态）原本只落 `wide/`，不在 `ledger_long.parquet` 里，
下游只能回头读宽表。本组用例钉住两件事：

  · 两个 metric **逐格等于原宽表**（不能改口径、不能丢 NaN）；
  · 新行**追加在长表末尾**、列序不变 —— 下游有按行 diff 的比对，插在中间会整片变红。

全部用构造的小 DataFrame，**不读 input/、不读 out/**，离线可跑。
"""
import pandas as pd

import parse_ledger

DISC = ["Chemistry", "Physics", "Microbiology"]
PERIODS = ["202601", "202603", "202605"]


def _wide(values):
    return pd.DataFrame(values, index=pd.Index(DISC, name="discipline"), columns=PERIODS)


def _grouped():
    """new_intl / new_cn / rank_intl / rank_cn 的形状：一行长格式。"""
    rows = []
    for d_i, d in enumerate(DISC):
        for p_i, p in enumerate(PERIODS):
            rows.append({"discipline": d, "period": p,
                         "n_inst_1pct": 100.0 + d_i + p_i,
                         "rank": 10.0 + d_i * p_i,
                         "rank_pct": 0.5 + 0.01 * p_i})
    return pd.DataFrame(rows)


#: 1‰ 阈值：带一个缺数格（Microbiology/202603），验 NaN 原样进长表。
THR_1PERMILLE = _wide([
    [83785.0, 84000.0, 84500.0],
    [20000.0, 20100.0, 20200.0],
    [9000.0, None, 9100.0],
])

#: 进入前 1% 状态：0/1。
ENTERED = _wide([[0.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]])


def _ledger(entered=None):
    return {
        "wide": {"total_cites": _wide([[300.0, 310.0, 305.0],
                                       [50.0, 55.0, 60.0],
                                       [10.0, 11.0, 12.0]]),
                 "cnci": _wide([[1.1, 1.2, 1.3], [0.9, 1.0, 1.0], [0.4, 0.5, 0.6]])},
        "new_intl": _grouped(), "new_cn": _grouped(),
        "rank_intl": _grouped(), "rank_cn": _grouped(),
        "threshold_1permille": THR_1PERMILLE,
        "entered_1pct": ENTERED if entered is None else entered,
    }


def _cell(long, metric, disc, period):
    s = long[(long.metric == metric) & (long.discipline == disc) & (long.period == period)]["value"]
    assert len(s) == 1, f"{metric}/{disc}/{period} 应恰好一行，实为 {len(s)}"
    return s.iloc[0]


def test_长表包含两个新指标():
    long = parse_ledger.long_table(_ledger())
    metrics = set(long["metric"])
    assert {"threshold_1permille", "entered_1pct"} <= metrics, sorted(metrics)
    # 老指标一个没少
    assert {"total_cites", "cnci", "n_inst_1pct", "rank", "rank_pct"} <= metrics
    assert len(long[long.metric == "threshold_1permille"]) == len(DISC) * len(PERIODS)
    assert len(long[long.metric == "entered_1pct"]) == len(DISC) * len(PERIODS)


def test_两个新指标逐格等于原宽表():
    long = parse_ledger.long_table(_ledger())
    for disc in DISC:
        for period in PERIODS:
            want = THR_1PERMILLE.loc[disc, period]
            got = _cell(long, "threshold_1permille", disc, period)
            assert (pd.isna(got) and pd.isna(want)) or got == want, \
                f"threshold_1permille {disc}/{period}: 长表 {got!r} ≠ 宽表 {want!r}"
            assert _cell(long, "entered_1pct", disc, period) == ENTERED.loc[disc, period], \
                f"entered_1pct {disc}/{period}"


def test_进入状态是bool时归一成0_1数值():
    """`entered_1pct` 若给的是 bool，长表 value 仍是 float —— 否则整列退化成 object。"""
    long = parse_ledger.long_table(_ledger(entered=ENTERED.astype(bool)))
    assert long["value"].dtype == float, long["value"].dtype
    sub = long[long.metric == "entered_1pct"]
    assert set(sub["value"]) == {0.0, 1.0}
    assert _cell(long, "entered_1pct", "Chemistry", "202605") == 1.0
    assert _cell(long, "entered_1pct", "Microbiology", "202605") == 0.0


def test_新指标追加在末尾且列序不变():
    """下游按行 diff 比对：老行必须原位不动，新行整块追加。"""
    long = parse_ledger.long_table(_ledger())
    assert list(long.columns) == ["discipline", "period", "value", "metric", "source"], list(long.columns)
    n_cells = len(DISC) * len(PERIODS)
    assert long.tail(2 * n_cells)["metric"].tolist() == \
        ["threshold_1permille"] * n_cells + ["entered_1pct"] * n_cells
    head = long.head(len(long) - 2 * n_cells)
    assert not head["metric"].isin(["threshold_1permille", "entered_1pct"]).any()
    # 宽表指标不挂 source（与老口径一致）
    assert long.tail(2 * n_cells)["source"].isna().all()
