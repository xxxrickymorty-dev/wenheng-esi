# -*- coding: utf-8 -*-
"""台账镜像（SQLite，票 01）：确定性重建 / 只读消费 / 与 ledger_long 同口径。

- 单测全注入（合成行 → 建库 → 读回）；不读真母本；
- 数据守卫集成：真母本在才跑（`_guard_registry.skip_unless` 登记探针）。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ledger as ledger_mod                                      # noqa: E402
import ledger_mirror                                             # noqa: E402
from _guard_registry import skip_unless                          # noqa: E402

ROWS = [
    ("Chemistry", "201903", "total_cites", "", 13423.0),
    ("Chemistry", "201905", "total_cites", "", 15000.0),
    ("Chemistry", "201903", "rank", "rank_cn", 12.0),
    ("Physics", "201903", "total_cites", "", 8000.0),
    ("Physics", "201905", "total_cites", "", None),
]


def _r6(v):
    if v is None:
        return None
    f = float(v)
    return None if f != f else round(f, 6)


def _s(v):
    return "" if v is None or v != v else str(v)


# ============================================================ 1. 单测（全注入）
def test_写库读回_期次升序与切窗(tmp_path):
    db = tmp_path / "m.sqlite"
    meta = ledger_mirror.write_facts(db, ROWS)
    assert int(meta["n_facts"]) == 5
    assert ledger_mirror.series(db, "Chemistry", "total_cites") == \
        [("201903", 13423.0), ("201905", 15000.0)]
    assert ledger_mirror.series(db, "Chemistry", "total_cites", period_max="201903") == \
        [("201903", 13423.0)]
    assert ledger_mirror.series(db, "Chemistry", "rank", source="rank_cn") == \
        [("201903", 12.0)]
    assert ledger_mirror.series(db, "Nope", "total_cites") == []


def test_确定性_同输入同内容哈希(tmp_path):
    a = ledger_mirror.write_facts(tmp_path / "a.sqlite", ROWS)
    b = ledger_mirror.write_facts(tmp_path / "b.sqlite", list(reversed(ROWS)))
    assert a["content_sha256"] == b["content_sha256"], "输入顺序不影响内容"
    assert ledger_mirror.content_hash(tmp_path / "a.sqlite") == a["content_sha256"]
    c = ledger_mirror.write_facts(tmp_path / "c.sqlite",
                                  ROWS + [("Chemistry", "201907", "total_cites", "", 1.0)])
    assert c["content_sha256"] != a["content_sha256"]


def test_空输入_可建可校验(tmp_path):
    db = tmp_path / "empty.sqlite"
    meta = ledger_mirror.write_facts(db, [])
    assert meta["n_facts"] == "0" and ledger_mirror.series(db, "X", "y") == []
    assert ledger_mirror.verify(db)["ok"] is True


def test_缺库校验_如实报(tmp_path):
    out = ledger_mirror.verify(tmp_path / "nope.sqlite")
    assert out["ok"] is False and "不存在" in out["reason"]


# ============================================================ 2. 数据守卫集成
def test_真母本_建库校验并与ledger_long逐行一致(tmp_path):
    lp = ledger_mod.runtime_path(REPO)
    if not lp.is_file():
        skip_unless("缺母本（馆员数据不入库，属正常）", lambda: lp.is_file())
    db = tmp_path / "real.sqlite"
    meta = ledger_mirror.build(db, ledger_path=lp)
    assert int(meta["n_facts"]) > 0
    assert ledger_mirror.verify(db, ledger_path=lp)["ok"] is True, \
        "同母本重建应同内容（确定性）"

    def _longs():
        return sorted(p for p in (REPO / "out").glob("*/ledger_long.parquet")
                      if p.parent.name[:4].isdigit())

    longs = _longs()
    if not longs:
        skip_unless("缺 out/<期次>/ledger_long.parquet（产物不入库）", lambda: bool(_longs()))
    import pandas as pd                                           # noqa: PLC0415

    ll = pd.read_parquet(longs[-1])
    ll_max = max(str(p) for p in ll["period"])
    want = {(str(r[0]), str(r[1]), str(r[2]), _s(r[3]), _r6(r[4]))
            for r in ll[["discipline", "period", "metric", "source", "value"]]
            .itertuples(index=False, name=None)}
    got = {(d, p, m, _s(s), _r6(v)) for d, p, m, s, v in ledger_mirror.rows(db)
           if p <= ll_max}
    assert got == want, "镜像行 ≡ ledger_long 行（按期次子集，同口径不复制）"


# ============================================================ 3. 白名单视图（票 02）
VIEW_ROWS = [
    ("Chemistry", "201903", "total_cites", "", 100.0),
    ("Chemistry", "201905", "total_cites", "", 200.0),
    ("Chemistry", "201905", "rank", "rank_cn", 5.0),
    ("Chemistry", "201905", "rank", "rank_intl", 50.0),
    ("Chemistry", "201907", "rank", "rank_cn", 4.0),
    ("Chemistry", "201907", "cnci", "", None),
    ("Physics", "201903", "total_cites", "", 7.0),
    ("Physics", "201905", "total_cites", "", None),
]


def _view_db(tmp_path, name="views.sqlite"):
    db = tmp_path / name
    ledger_mirror.write_facts(db, VIEW_ROWS)
    return db


def test_视图注册表_四视图齐全且口径写清():
    assert set(ledger_mirror.VIEWS) == {"periods", "series", "at", "latest"}
    for name, spec in ledger_mirror.VIEWS.items():
        assert callable(spec["fn"]) and spec["fn"].__name__ == name
        assert spec["doc"].strip(), name
        for p in spec["params"]:
            assert p["name"] and p["doc"].strip(), (name, p)
            assert p["required"] or "default" in p, (name, p["name"])
    series_params = {p["name"]: p for p in ledger_mirror.VIEWS["series"]["params"]}
    assert "period_max" in series_params
    assert "period <= period_max" in series_params["period_max"]["doc"], "切窗语义要写清"
    listed = ledger_mirror.describe_views()
    assert [v["name"] for v in listed] == list(ledger_mirror.VIEWS)
    assert all("fn" not in v and v["doc"] for v in listed)


def test_视图periods_降序与空(tmp_path):
    db = _view_db(tmp_path)
    assert ledger_mirror.periods(db) == ["201907", "201905", "201903"]
    empty = tmp_path / "empty.sqlite"
    ledger_mirror.write_facts(empty, [])
    assert ledger_mirror.periods(empty) == []


def test_视图at_全指标与来源键(tmp_path):
    db = _view_db(tmp_path)
    assert ledger_mirror.at(db, "Chemistry", "201905") == {
        "total_cites": 200.0, "rank@rank_cn": 5.0, "rank@rank_intl": 50.0}
    assert ledger_mirror.at(db, "Chemistry", "201907") == {
        "rank@rank_cn": 4.0, "cnci": None}, "空值不填充也不丢行"
    assert ledger_mirror.at(db, "Physics", "201905") == {"total_cites": None}
    assert ledger_mirror.at(db, "Nope", "201905") == {}


def test_视图latest_口径与空(tmp_path):
    db = _view_db(tmp_path)
    assert ledger_mirror.latest(db) == "201907"
    assert ledger_mirror.latest(db, "total_cites") == "201905", "201907 没有该指标"
    assert ledger_mirror.latest(db, "rank", source="rank_cn") == "201907"
    assert ledger_mirror.latest(db, "rank", source="rank_intl") == "201905"
    assert ledger_mirror.latest(db, "cnci") is None, "有期次但值全空 → 不算"
    assert ledger_mirror.latest(db, "nope") is None
    assert ledger_mirror.latest(db, source="rank_cn") == "201907"
    empty = tmp_path / "empty.sqlite"
    ledger_mirror.write_facts(empty, [])
    assert ledger_mirror.latest(empty) is None


def test_真数据_视图与ledger_long同题同值(tmp_path):
    lp = ledger_mod.runtime_path(REPO)
    if not lp.is_file():
        skip_unless("缺母本（馆员数据不入库，属正常）", lambda: lp.is_file())

    def _longs():
        return sorted(p for p in (REPO / "out").glob("*/ledger_long.parquet")
                      if p.parent.name[:4].isdigit())

    longs = _longs()
    if not longs:
        skip_unless("缺 out/<期次>/ledger_long.parquet（产物不入库）", lambda: bool(_longs()))
    import pandas as pd                                           # noqa: PLC0415

    db = tmp_path / "real_views.sqlite"
    ledger_mirror.build(db, ledger_path=lp)

    ll = pd.read_parquet(longs[-1])[
        ["discipline", "period", "metric", "source", "value"]]
    ll_max = max(str(p) for p in ll["period"])

    # periods：按产物期次切窗后 ≡ 产物期次集合（降序）
    want_periods = sorted({str(p) for p in ll["period"]}, reverse=True)
    assert [p for p in ledger_mirror.periods(db) if p <= ll_max] == want_periods

    # series：产物里每个 (学科, 指标, 来源) 组合逐列同题同值（period <= 切窗）
    want_series = {}
    for d, p, m, s, v in ll.itertuples(index=False, name=None):
        want_series.setdefault((str(d), str(m), _s(s)), {})[str(p)] = _r6(v)
    for (d, m, s), vals in want_series.items():
        got = ledger_mirror.series(db, d, m, source=s, period_max=ll_max)
        assert [(p, _r6(v)) for p, v in got] == sorted(vals.items()), (d, m, s)

    # at：取产物首末期次，全学科整期 ≡ parquet 同题同值
    for period in (want_periods[-1], ll_max):
        want_at = {}
        for d, p, m, s, v in ll.itertuples(index=False, name=None):
            if str(p) == period:
                key = f"{m}@{_s(s)}" if _s(s) else str(m)
                want_at.setdefault(str(d), {})[key] = _r6(v)
        for d, expected in want_at.items():
            got = {k: _r6(v) for k, v in ledger_mirror.at(db, d, period).items()}
            assert got == expected, (period, d)
