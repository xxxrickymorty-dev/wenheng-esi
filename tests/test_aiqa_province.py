# -*- coding: utf-8 -*-
"""AI 问数 · 省域高校对比 / 云大排名两类问法（2026-10 新增）。

覆盖五件事：
1. 建库后 `province_fact` / `ynd_rank_series` 非空，行数与源 parquet 一致；
2. 「云南大学和昆明理工大学的论文量对比」答案含两校名 + 两数，且**逐格**与
   `province.parquet` 一致（6 指标 × 9 高校全查）；
3. 「云南大学最新国际排名」的数与 `ynd_rank.parquet` 同 period 的值一致；
4. 不认识的问法优雅回退（不抛异常）；原有 5 种问法不退化的冒烟；
5. 只读红线：`aiqa_sql` 的 UPDATE/DELETE 被拒、只读连接写库报错。

数据面：`out/<期次>/wide/*.parquet` 不入库，缺数据时按仓库惯例 `skip_unless`
登记探针（探针说文件其实在 → 会话收尾判失败，防"路径写错静默跳过"）。
"""
from __future__ import annotations

import pathlib
import shutil
import sqlite3

import pandas as pd
import pytest

from _guard_registry import skip_unless

import aiqa_db
import aiqa_engine

REPO = pathlib.Path(__file__).resolve().parents[1]
PERIOD = "202607"
SRC_WIDE = REPO / "out" / PERIOD / "wide"

#: 宽表行索引 → 省域指标白名单键（与 `aiqa_db._PROVINCE_METRICS` 同序，测试独立写死
#: 一份，防止实现里悄悄改名还对得上）。
_ROWS = [
    ("论文量（篇）", "pv_papers"),
    ("被引频次（次）", "pv_cites"),
    ("顶尖论文（篇）", "pv_top_papers"),
    ("高被引论文（篇）", "pv_hi_cited"),
    ("热点论文（篇）", "pv_hot_papers"),
    ("研究前沿（篇）", "pv_research_fronts"),
]


def _need(name: str) -> pathlib.Path:
    p = SRC_WIDE / name
    if not p.is_file():
        skip_unless(f"out/{PERIOD}/wide/{name} 不在（产物不入库，属正常）",
                    lambda: p.is_file())
    return p


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """在仓库内的临时根下建一份独立问数库（不碰共享 out/_aidata）。

    只拷当期产物的**只读副本**（台账长表 / 大表 / 概述 / 两张新宽表），
    让 `verify()` 与原有 5 种问法都能在这个孤立根里跑通。
    """
    prov_p, ynd_p = _need("province.parquet"), _need("ynd_rank.parquet")
    out_src = REPO / "out" / PERIOD
    root = tmp_path_factory.mktemp("aiqa_prov") / "repo"
    wide = root / "out" / PERIOD / "wide"
    wide.mkdir(parents=True)
    shutil.copy2(prov_p, wide / "province.parquet")
    shutil.copy2(ynd_p, wide / "ynd_rank.parquet")
    for name in ("ledger_long.parquet", "table2.csv", "overview_facts.json"):
        f = out_src / name
        if not f.is_file():
            skip_unless(f"out/{PERIOD}/{name} 不在（产物不入库，属正常）",
                        lambda f=f: f.is_file())
        shutil.copy2(f, root / "out" / PERIOD / name)
    m = aiqa_db.build(root, out_period=PERIOD)
    return root, m


def _ask(root, question):
    con = aiqa_db.connect_ro(root)
    try:
        p = aiqa_engine.plan(question, con)
        result = aiqa_engine.execute(con, p["specs"])
        return (p, result, aiqa_engine.render_text(con, question, result),
                aiqa_engine.suggest_chart(con, p["specs"], result))
    finally:
        con.close()


# ---------------------------------------------------------------- 1. 建库计数

def test_new_tables_row_counts_match_parquet(built):
    root, m = built
    prov = pd.read_parquet(SRC_WIDE / "province.parquet")
    ynd = pd.read_parquet(SRC_WIDE / "ynd_rank.parquet")

    con = aiqa_db.connect_ro(root)
    try:
        n_prov = con.execute("SELECT COUNT(*) FROM province_fact").fetchone()[0]
        n_uni = con.execute(
            "SELECT COUNT(DISTINCT university) FROM province_fact").fetchone()[0]
        n_ynd = con.execute("SELECT COUNT(*) FROM ynd_rank_series").fetchone()[0]
        n_dim = con.execute(
            "SELECT COUNT(*) FROM dim_province_metric").fetchone()[0]
    finally:
        con.close()

    # 宽表是「指标 × 高校」矩阵，落库 melt 成长表：6×9
    assert n_prov == prov.shape[0] * prov.shape[1] == 54
    assert n_uni == prov.shape[1] == 9
    assert n_dim == prov.shape[0] == 6
    assert n_ynd == len(ynd) == 20

    assert str(n_prov) == m["n_province"]
    assert str(n_ynd) == m["n_ynd_rank"]
    assert m["missing_sources"] == ""

    v = aiqa_db.verify(root)
    assert v["ok"] is True, v
    assert v["n_province"] == n_prov and v["n_ynd_rank"] == n_ynd


# ---------------------------------------------------------------- 2. 省域对比

def test_province_compare_cell_by_cell(built):
    root, _ = built
    prov = pd.read_parquet(SRC_WIDE / "province.parquet")

    # 逐格比对：6 指标 × 9 高校，一格不落
    con = aiqa_db.connect_ro(root)
    try:
        for label, key in _ROWS:
            for uni in prov.columns:
                got = con.execute(
                    "SELECT value FROM province_fact "
                    "WHERE period=? AND university=? AND metric=?",
                    (PERIOD, uni, key)).fetchone()
                assert got is not None, f"缺格：{uni} / {label}"
                assert got[0] == pytest.approx(float(prov.at[label, uni])), \
                    f"格不一致：{uni} / {label}"
    finally:
        con.close()

    q = "云南大学和昆明理工大学的论文量对比"
    plan, result, answer, chart = _ask(root, q)

    assert plan["specs"] and plan["specs"][0]["kind"] == "province_compare"
    assert plan["specs"][0]["metric"] == "pv_papers"
    assert chart["kind"] == "bar"

    v_ynd = float(prov.at["论文量（篇）", "云南大学"])
    v_kust = float(prov.at["论文量（篇）", "昆明理工大学"])

    assert "云南大学" in answer and "昆明理工大学" in answer
    assert f"{v_ynd:,.0f}" in answer          # 13,940
    assert f"{v_kust:,.0f}" in answer         # 19,259
    assert f"{v_ynd:,.0f}" != f"{v_kust:,.0f}"

    # 行集里的数也必须逐格对得上（不是只有渲染字符串对）
    items = {it["university"]: it["value"] for it in result["rows"][0]["items"]}
    assert items["云南大学"] == pytest.approx(v_ynd)
    assert items["昆明理工大学"] == pytest.approx(v_kust)
    assert len(items) == 2


def test_province_rank_question_covers_all_universities(built):
    """「云南高校论文量排名」→ 9 所全给，且降序；数逐格来自 parquet。"""
    root, _ = built
    prov = pd.read_parquet(SRC_WIDE / "province.parquet")
    _, result, answer, chart = _ask(root, "云南高校论文量排名")
    items = result["rows"][0]["items"]
    assert chart["kind"] == "bar"
    assert len(items) == len(prov.columns)
    vals = [it["value"] for it in items]
    assert vals == sorted(vals, reverse=True)
    for it in items:
        assert it["value"] == pytest.approx(
            float(prov.at["论文量（篇）", it["university"]]))
    assert "昆明理工大学" in answer and "云南财经大学" in answer


# ---------------------------------------------------------------- 3. 云大排名

def test_ynd_latest_intl_rank_matches_parquet(built):
    root, _ = built
    ynd = pd.read_parquet(SRC_WIDE / "ynd_rank.parquet")

    q = "云南大学最新国际排名"
    plan, result, answer, chart = _ask(root, q)
    assert plan["specs"][0]["kind"] == "ynd_rank"
    assert plan["specs"][0]["metric"] == "rank_intl"
    assert chart["kind"] == "table"

    point = result["rows"][0]["point"]
    per = point["period"]
    row = ynd[ynd["period"].astype(str) == str(per)]
    assert len(row) == 1, f"parquet 里没有 period={per}"
    v = float(row.iloc[0]["rank_intl"])
    assert point["rank_intl"] == pytest.approx(v)
    assert f"{v:,.0f}" in answer
    assert per in answer


def test_ynd_rank_trend_is_series_and_line(built):
    root, _ = built
    ynd = pd.read_parquet(SRC_WIDE / "ynd_rank.parquet")
    _, result, answer, chart = _ask(root, "云大国内排名趋势")
    assert chart["kind"] == "line"
    pts = result["rows"][0]["points"]
    assert len(pts) == len(ynd) == 20
    # 序列逐期一致
    for p, (_i, r) in zip(pts, ynd.iterrows()):
        assert p["period"] == str(r["period"])
        assert p["rank_cn"] == pytest.approx(float(r["rank_cn"]))
    assert "202307" in answer and "202609" in answer


# ---------------------------------------------------------------- 4. 回退与不退化

@pytest.mark.parametrize("q", ["今天天气怎么样", "帮我写一首诗", "云南", "化学"])
def test_unknown_question_degrades_gracefully(built, q):
    root, _ = built
    plan, result, answer, _chart = _ask(root, q)          # 不抛异常即达标
    assert isinstance(answer, str) and answer
    if not plan["specs"]:
        assert result["rows"] == []
        assert "没有查到匹配的数据" in answer


def test_legacy_kinds_still_work(built):
    """原有 5 种问法的冒烟：规划出的 kind 不变、答案非空。

    注：`table2`/`overview` 只装建库那一期（202607），而期次轴最新是 202609，
    所以这两类在这里显式带上期次——这是改动前就有的口径，不是本次回归。
    """
    root, _ = built
    cases = {
        "化学的总被引趋势": "series",
        "化学和数学的论文数对比": "compare",
        "化学 202607": "table2",
        "202607 多少个学科进入前1%": "overview",
        "202607 论文数前 5 名": "compare",
    }
    for q, kind in cases.items():
        plan, result, answer, _ = _ask(root, q)
        kinds = [s["kind"] for s in plan["specs"]]
        assert kinds == [kind], f"{q} 规划成了 {kinds}"
        assert result["rows"], f"{q} 没有行"
        assert answer and "没有查到匹配的数据" not in answer, f"{q} → {answer}"


# ---------------------------------------------------------------- 5. 只读红线

def test_aiqa_sql_rejects_writes(built, monkeypatch):
    from server import mcp_aiqa

    root, _ = built
    monkeypatch.setattr(mcp_aiqa, "REPO", root)

    for sql in ("UPDATE qa_log SET user='x'",
                "DELETE FROM province_fact",
                "DROP TABLE province_fact",
                "INSERT INTO ynd_rank_series (period) VALUES ('209901')"):
        got = mcp_aiqa.tool_sql(sql)
        assert "error" in got, f"没拦住：{sql}"
        assert "只读" in got["error"]

    # 新表确实可查（白名单同步到位）
    ok = mcp_aiqa.tool_sql(
        "SELECT university, metric, value FROM province_fact LIMIT 3")
    assert ok["n"] == 3 and not ok.get("error")
    ok2 = mcp_aiqa.tool_sql("SELECT period, rank_intl FROM ynd_rank_series LIMIT 2")
    assert ok2["n"] == 2 and not ok2.get("error")


def test_readonly_connection_refuses_writes(built):
    root, _ = built
    con = aiqa_db.connect_ro(root)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM province_fact")
        with pytest.raises(sqlite3.OperationalError):
            con.execute("UPDATE ynd_rank_series SET rank_intl=1")
    finally:
        con.close()
