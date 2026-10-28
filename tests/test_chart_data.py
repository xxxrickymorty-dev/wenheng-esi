# -*- coding: utf-8 -*-
"""图册同源导出（chart_data）测试：前端 ECharts 的数字必须与报告 PNG 同一批。

两层断言：
  · 纯函数层——×100、期次交集、NaN→null、只出 16 个详细学科，全用合成宽表钉死；
  · 台账层——out/202607 真件上，build() 的窗口与序列等价于「按 render_all 的
    原语独立重算一遍」（同源不是口号，是对得上的数）。
"""
from __future__ import annotations

import asyncio
import json
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
import period as period_mod

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


# ---------- 全图型对账（2026-10-28 前端全量 ECharts 化：每个 builder 独立重算对账） ----------

def test_full_build_keys_on_real_ledger():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    data = chart_data.build(OUT)
    assert data["schema"] == 2
    n_disc = len(data["disciplines"])
    assert n_disc == 16, n_disc
    for key in ("cnci", "papers_new", "cites_threshold", "top_papers", "q_dist"):
        assert all(key in row for row in data["disciplines"].values()), key
    ov = data["_overview"]
    for key in ("1pct", "1permille", "rank_table", "trend_table",
                "top_by_subject", "top_by_year", "college_cites", "college_papers"):
        assert key in ov, key
    # q_dist 实体名随原件外显（数据叫「全球」，图上叫「国际」）
    ents = next(iter(data["disciplines"].values()))["q_dist"]["entities"]
    assert [e["name"] for e in ents] == ["云南大学", "中国大陆", "国际"]


def test_papers_new_is_diff_of_papers_on_real_ledger():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    data = chart_data.build(OUT)
    papers = pd.read_parquet(OUT / "wide" / "papers.parquet")
    disc = "Plant & Animal Science"
    row = data["disciplines"][disc]["papers_new"]
    # 与 render_all 同一窗口口径取列，再做同一差分
    filled = period_mod.filled({"total_cites": pd.read_parquet(OUT / "wide" / "total_cites.parquet")})
    filled = [c for c in filled if c <= "202607"]
    ps = [p for p in filled[-8:] if p in papers.columns]
    want = papers.loc[disc, ps].astype(float).diff().iloc[1:]
    assert row["periods"] == [str(c) for c in want.index]
    assert row["values"] == pytest.approx(
        [None if pd.isna(x) else float(x) for x in want])


def test_overview_1pct_matches_ratio_recompute_on_real_ledger():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    data = chart_data.build(OUT)
    cites = pd.read_parquet(OUT / "wide" / "total_cites.parquet")
    thr = pd.read_parquet(OUT / "wide" / "threshold_1pct.parquet")
    ratio = (cites["202607"] / thr["202607"] * 100).dropna().sort_values()
    items = data["_overview"]["1pct"]["items"]
    assert [i["name_cn"] for i in items] == [charts._cn(d) for d in ratio.index]
    assert [i["ratio"] for i in items] == pytest.approx([float(r) for r in ratio])
    # 差距段＝到 100% 的距离，<100% 才有（clip 口径）
    assert items[-1]["gap"] == pytest.approx(max(0.0, 100 - float(ratio.iloc[-1])))


def test_trend_table_picks_match_shared_selector_on_real_ledger():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    data = chart_data.build(OUT)
    cites = pd.read_parquet(OUT / "wide" / "total_cites.parquet")
    thr = pd.read_parquet(OUT / "wide" / "threshold_1permille.parquet")
    ent = pd.read_parquet(OUT / "wide" / "entered_1pct.parquet")
    picked, periods, picks = charts.trend_picks(cites, thr, end_period="202607",
                                                n=7, top_k=4, entered=ent)
    row = data["_overview"]["trend_table"]
    assert row["periods"] == periods
    assert [s["disc"] for s in row["series"]] == picks       # 顺序＝进 1% 先后
    assert row["baseline"] == 100.0
    for s in row["series"]:
        assert len(s["values"]) == len(periods)
        assert s["color"] in chart_data.TREND_COLORS


def test_college_items_merge_small_into_other():
    stats = {"units": [
        {"unit": "A 学院", "cites": 900, "papers": 60},
        {"unit": "B 学院", "cites": 80, "papers": 8},
        {"unit": "C 中心", "cites": 10, "papers": 1},
        {"unit": "D 所", "cites": 10, "papers": 1},
    ]}
    items = chart_data._college_items(stats, "cites")
    # 1000 总量里 <1.5%（<15）的 C/D 合并，其余按原样；「其他」恒为中性灰
    assert [i["name"] for i in items] == ["A 学院", "B 学院", "其他（2 个单位）"]
    assert items[-1]["color"] == "#D9D9D9"
    assert items[-1]["value"] == pytest.approx(20.0)
    assert items[0]["pct"] == pytest.approx(90.0)     # 标签里的百分比也是画进 PNG 的数
    assert items[-1]["pct"] == pytest.approx(2.0)
    assert chart_data._college_items({"units": []}, "cites") is None
    assert chart_data._college_items(None, "cites") is None


def test_forecast_payload_skips_legacy_entries_without_series(tmp_path):
    legacy = {"charts": [
        {"png": "forecast_1_cites.png", "subject": "化学", "kind": "cites"},
        {"png": "forecast_2_cites.png", "subject": "植物与动物学", "kind": "cites",
         "series": {"hist_periods": ["202501"], "fut_periods": ["202503"],
                    "columns": [{"actual": [1.0], "fitted": [None], "future": [2.0]}]}},
    ]}
    (tmp_path / "forecast_charts.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    payload = chart_data._forecast_payload(tmp_path)
    assert set(payload) == {"forecast_2_cites"}     # 老期次条目无序列 → 不导出（前端回退 PNG）
    assert payload["forecast_2_cites"]["fut_periods"] == ["202503"]


# ---------- 接口层（契约 #38）：/api/periods/<p>/charts-data 就是 build() 的原样出口 ----------

def _api_charts_data(user, period):
    from server import app as app_module

    class _Req:
        def __init__(self, user_):
            self.session = {"user": user_} if user_ else {}

    return asyncio.run(app_module.api_period_charts_data(_Req(user), period))


def test_charts_data_endpoint_serves_build_verbatim():
    """接口里外就是 build()：同输入同 dict；NaN 一个都不许漏出 JSON。"""
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    from server import config

    body = _api_charts_data(config.OPERATOR_USER, "202607")
    assert body == chart_data.build(OUT)
    json.dumps(body, ensure_ascii=False, allow_nan=False)   # NaN → ValueError


def test_charts_data_endpoint_requires_login():
    r = _api_charts_data(None, "202607")
    assert r.status_code == 401


def test_charts_data_endpoint_unknown_period_is_404():
    from server import config

    r = _api_charts_data(config.OPERATOR_USER, "199901")
    assert r.status_code == 404


def test_college_stats_served_as_drawn_on_real_ledger():
    """学院统计必须与报告 PNG 同一批：缓存逐字优先，不许重算改分组。"""
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    data = chart_data.build(OUT)
    cached = json.loads((OUT / "college_stats.json").read_text(encoding="utf-8"))
    assert cached.get("units"), "缓存缺席时本用例没有意义（重算兜底仍由 load 承担）"
    for key, mode in (("college_cites", "cites"), ("college_papers", "papers")):
        assert data["_overview"][key]["items"] == chart_data._college_items(cached, mode)
