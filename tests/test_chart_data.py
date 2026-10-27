# -*- coding: utf-8 -*-
"""图册同源导出（chart_data）测试：前端 ECharts 的数字必须与报告 PNG 同一批。

两层断言：
  · 纯函数层——×100、期次交集、NaN→null、只出 16 个详细学科，全用合成宽表钉死；
  · 台账层——out/202607 真件上，build() 的窗口与序列等价于「按 render_all 的
    原语独立重算一遍」（同源不是口号，是对得上的数）。
"""
from __future__ import annotations

import pathlib
import sys

import pandas as pd
import pytest

from _guard_registry import skip_unless

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import charts
import chart_data

OUT = ROOT / "out" / "202607"


PERIODS = ["202507", "202509", "202511", "202601", "202603", "202605", "202607"]


def test_rank_pct_payload_scales_by_100_and_intersects_periods():
    disc = "Plant & Animal Science"
    # 5 期有列、7 期窗口：后两期不在 pivot 里，应被 _avail 裁掉；
    # 其中一值给 NaN，应出 null。
    avail_periods = PERIODS[:5]
    intl = pd.DataFrame([[0.29, 0.27, None, 0.25, 0.22]],
                        index=[disc], columns=avail_periods)
    cn = pd.DataFrame([[0.31, 0.29, 0.29, 0.28, 0.26]],
                      index=[disc], columns=avail_periods)
    payload = chart_data.rank_pct_payload(intl, cn, PERIODS)
    assert set(payload) == {disc}
    row = payload[disc]
    assert row["periods"] == avail_periods          # 交集，不是全窗口
    # ×100 用原始浮点（画图函数收到的就是它，前端再格式化两位小数），这里按近似比
    assert row["series"]["intl"][:2] == pytest.approx([29.0, 27.0])
    assert row["series"]["intl"][2] is None         # NaN → null
    assert row["series"]["cn"][-1] == pytest.approx(26.0)
    assert row["labels"]["intl"] == "国际排名百分位值"  # 图例逐字同 PNG
    assert row["name_cn"] == charts._cn(disc)


def test_rank_pct_payload_skips_disciplines_outside_detail_tables():
    disc = "Chemistry"
    intl = pd.DataFrame([[0.5] * 3], index=[disc, "Imaginary Field"],
                        columns=PERIODS[:3])
    cn = intl.copy()
    payload = chart_data.rank_pct_payload(intl, cn, PERIODS)
    assert set(payload) == {disc}                   # 台账里多出的学科不进图册


def test_build_matches_independent_recomputation_on_real_ledger():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    data = chart_data.build(OUT)
    # 窗口：当期往前 7 期（含当期），当期＝目录名推断
    tc = pd.read_parquet(OUT / "wide" / "total_cites.parquet")
    filled = [str(c) for c in tc.columns if str(c) <= "202607"]
    assert data["end_period"] == "202607"
    assert data["periods"] == filled[-7:]
    # 序列：与 render_all 同原语独立重算，逐学科逐点相等
    longdf = pd.read_parquet(OUT / "ledger_long.parquet")
    d = longdf[(longdf.source == "rank_intl") & (longdf.metric == "rank_pct")]
    pivot = d.pivot(index="discipline", columns="period", values="value")
    assert set(data["rank_pct"]) == set(charts.DETAIL_TABLES) & set(pivot.index)
    for disc, row in data["rank_pct"].items():
        want = [None if pd.isna(v) else float(v) * 100
                for v in pivot.loc[disc, row["periods"]].astype(float)]
        assert row["series"]["intl"] == want, disc
