# -*- coding: utf-8 -*-
"""证据账（`flexible/provenance.py`）的验收用例。

四组判据：

1. **一本账**：查询/跨校/图表/派生数都登记，每条都有 `source`；
2. **不能空过**：没有来源的数据点算坏、没有登记的数字判不过、声明的图没进账判不过；
3. **跨校不再冒充台账**：附录里显示 ESI 数据件、工作表与**实际期次**，不是破折号；
4. **路径可交接**：正文与 JSON 里不出现本机盘符或绝对路径。

纯函数用例不依赖数据；端到端用例把金标期次复制到 tmp 再跑（`out/` 只读）。
"""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from _guard_registry import skip_unless

from flexible import datasource, peers, provenance, queries, report

# ------------------------------------------------------------------ 替身

PERIOD = "202601"
DISC = "Chemistry"


def _chain(period: str = PERIOD, disc: str = DISC) -> dict:
    return {"dataset": "out/202601/ledger_long.parquet", "metric": "total_cites",
            "metric_cn": "总被引频次", "discipline": disc, "discipline_cn": "化学",
            "period": period, "origin_sheet": "总被引",
            "locator": f"总被引：化学 行 × {period} 列"}


def _series(value: float = 12345.0, *, with_source: bool = True) -> dict:
    return {"kind": "series", "metric": "total_cites", "metric_cn": "总被引频次",
            "disc": DISC, "disc_cn": "化学", "n": 1,
            "points": [{"period": PERIOD, "value": value,
                        "source": _chain() if with_source else None}]}


def _chart(name: str = "cnci__Chemistry.png") -> dict:
    return {"path": f"C:/tmp/charts/{name}", "kind": "cnci", "kind_cn": "CNCI 变化",
            "spec": {"kind": "cnci", "disc": DISC}, "periods": [PERIOD],
            "sources": [{"dataset": "out/202601/wide/cnci.parquet", "table": "cnci",
                         "origin_sheet": "CNCI", "discipline": DISC,
                         "discipline_cn": "化学", "periods": [PERIOD],
                         "locator": "CNCI：化学 202601–202601"}]}


def _peer() -> dict:
    return {
        "period": "202607", "requested_period": "202607",
        "discipline": "Plant & Animal Science", "discipline_cn": "植物与动物学",
        "rows": [{"en": "YUNNAN UNIVERSITY", "cn": "云南大学", "present": True,
                  "values": {"rank": 442.0, "papers": 1727.0, "cites": 21296.0,
                             "cites_per_paper": 12.33, "top_papers": 32.0},
                  "rank_cn": 69}],
        "source": {"dataset": "数据与复现/ESI数据/202607/Plant & Animal Science.xlsx",
                   "sheet": "植物与动物学", "period": "202607"},
    }


class _View:
    """只回答 `at` 的最小查数面（`LedgerView` 协议里的一个方法足够回读）。"""

    periods = [PERIOD]
    filled_periods = [PERIOD]
    disciplines = [DISC]

    def at(self, metric, disc, period):
        return 12345.0


def _ledger(view=None) -> provenance.Ledger:
    return provenance.Ledger(view or _View())


def _built(ledger, blocks, charts) -> dict:
    return {"blocks": list(blocks), "sources": ledger.sources_json(),
            "charts": [{"path": c} for c in charts], "ledger": ledger}


# ================================================================ 1. 一本账
class Test一本账:
    def test_四类证据都登记且都有来源(self):
        led = _ledger()
        sec = led.section("学科概况")
        r = sec.query(_series())
        sec.chart(_chart())
        sec.derive("距 1% 阈值差", 1621.0, inputs=(r,))
        led.section("跨校对比").peer(_peer())

        items = led.sources_json()
        kinds = {x["kind"] for x in items}
        assert {"series", "chart", "derived", "peers"} <= kinds
        for item in items:
            src = item.get("source") or {}
            assert src.get("dataset"), item
            assert src.get("locator") or src.get("origin_sheet"), item

    def test_派生数有第一类条目(self):
        led = _ledger()
        sec = led.section("学科概况")
        r = sec.query(_series())
        sec.derive("距 1% 阈值差", 1621.0, inputs=(r,))
        derived = [x for x in led.sources_json() if x["kind"] == "derived"]
        assert len(derived) == 1
        assert derived[0]["value"] == 1621.0
        assert "距 1% 阈值差" in derived[0]["source"]["locator"]
        assert "派生" in led.appendix_markdown()

    def test_图表登记带真实图源(self):
        led = _ledger()
        sec = led.section("学科概况")
        sec.chart(_chart())
        led.check(declared_charts=[{"path": "x/cnci__Chemistry.png"}])
        charts = [x for x in led.sources_json() if x["kind"] == "chart"]
        assert charts[0]["file"] == "charts/cnci__Chemistry.png"
        assert charts[0]["sources"][0]["origin_sheet"] == "CNCI"
        assert charts[0]["source"]["dataset"] == "out/202601/wide/cnci.parquet"


# ================================================================ 2. 不能空过
class Test不能空过:
    def test_没有来源的数据点算坏(self):
        view = _View()
        got = queries.trace_check(view, _series(with_source=False))
        assert got["checked"] == 1 and got["bad"] == 1, got
        assert "没有来源链" in got["misses"][0]

    def test_没有登记的数字判不过(self):
        led = _ledger()
        sec = led.section("学科概况")
        sec.query(_series())
        sec.chart(_chart())
        c = report.self_check("# 标题\n\n正文", _View(),
                              _built(led, [("一、学科概况", "总被引 99,999 次")],
                                     ["charts/cnci__Chemistry.png"]))
        assert not c["pass"], c
        assert c["coverage"]["uncovered"] == [{"section": "学科概况",
                                               "value": "99,999"}]

    def test_本节没登记的数字不能用别节的账顶替(self):
        led = _ledger()
        led.section("学科概况").query(_series())
        led.section("学术影响力").chart(_chart("cnci__Chemistry.png"))
        c = report.self_check(
            "# 标题\n\n正文", _View(),
            _built(led, [("一、学科概况", "总被引 12,345 次"),
                         ("二、学术影响力", "篇均被引 3.06 次")],
                   ["charts/cnci__Chemistry.png"]))
        assert not c["pass"], c
        assert c["coverage"]["uncovered"] == [{"section": "学术影响力",
                                               "value": "3.06"}]

    def test_声明了图但没进账判不过(self):
        led = _ledger()
        led.section("学科概况").query(_series())
        c = report.self_check("# 标题\n\n正文", _View(),
                              _built(led, [("一、学科概况", "总被引 12,345 次")],
                                     ["charts/not_registered.png"]))
        assert not c["charts"]["ok"] and not c["pass"], c
        assert "not_registered.png" in c["charts"]["missing"]

    def test_只有空查询不能冒充通过(self):
        """0/0 全对的老毛病：查询条目在、却一个点都没回读 → 判不过。"""
        led = _ledger()
        sec = led.section("学科概况")
        empty = {"kind": "series", "metric": "cnci", "metric_cn": "CNCI",
                 "disc": DISC, "disc_cn": "化学", "n": 0, "points": [],
                 "source": _chain()}
        sec.query(empty, allow_empty=True)
        sec.chart(_chart())
        c = report.self_check("# 标题\n\n正文", _View(),
                              _built(led, [], ["charts/cnci__Chemistry.png"]))
        assert not c["trace_ok"] and not c["pass"], c
        assert c["trace"]["entries"] == 1 and c["trace"]["checked"] == 0

    def test_登记齐了才判过(self):
        led = _ledger()
        sec = led.section("学科概况")
        sec.query(_series())
        sec.chart(_chart())
        c = report.self_check("# 标题\n\n正文", _View(),
                              _built(led, [("一、学科概况", "总被引 12,345 次")],
                                     ["charts/cnci__Chemistry.png"]))
        assert c["pass"], c
        assert c["trace"]["checked"] == 1 and c["trace"]["bad"] == 0
        assert c["evidence"]["query"] == 1 and c["evidence"]["chart"] == 1


# ================================================================ 3. 跨校来源
class Test跨校来源:
    def test_附录显示真实数据件工作表与期次(self):
        led = _ledger()
        led.section("跨校对比").peer(_peer())
        row = next(ln for ln in led.appendix_markdown().splitlines()
                   if "外部数据" in ln)
        assert "数据与复现/ESI数据/202607/Plant & Animal Science.xlsx" in row
        assert "植物与动物学" in row and "202607" in row
        assert "—" not in row, "跨校行不该再出现破折号"

    def test_自检认得跨校条目(self):
        led = _ledger()
        led.section("学科概况").query(_series())
        led.section("跨校对比").peer(_peer())
        led.section("学科概况").chart(_chart())
        c = report.self_check(
            "# 标题\n\n正文", _View(),
            {"blocks": [("一、学科概况", "总被引 12,345 次")],
             "sources": led.sources_json(), "charts": [{"path": "x/cnci__Chemistry.png"}],
             "ledger": led, "selected": {"peers": ["昆明理工大学"]}})
        assert c["peer"] == {"expected": True, "n": 1, "ok": True}, c


# ================================================================ 4. 相对路径
class Test路径可交接:
    @pytest.mark.parametrize("path", [
        "C:/Users/x/Desktop/wenheng/out/202607/ledger_long.parquet",
        "C:/tmp/flex_abc/202607/wide/cnci.parquet",
        "/srv/wenheng/out/202607/ledger_long.parquet",
    ])
    def test_仓外路径还原成逻辑路径(self, path):
        got = datasource.relative_path(path)
        assert not got.startswith(("/", "C:")) and ":" not in got
        assert got.startswith("out/")

    def test_来源链不含盘符(self, tmp_path):
        d = tmp_path / "202601"
        (d / "wide").mkdir(parents=True)
        import pandas as pd
        pd.DataFrame([{"discipline": DISC, "period": PERIOD, "value": 1.0,
                       "metric": "papers", "source": None}]).to_parquet(
                           d / "ledger_long.parquet")
        pd.DataFrame({PERIOD: [1.0]}, index=[DISC]).to_parquet(
            d / "wide" / "total_cites.parquet")
        view = datasource.DataSource(d)
        ch = view.chain("papers", DISC, PERIOD)
        assert ch["dataset"] == "out/202601/ledger_long.parquet", ch
        assert "C:" not in ch["dataset"] and not ch["dataset"].startswith("/")

    def test_监测表适配器的来源链也不含盘符(self):
        """`LedgerView` 的另一个适配器（监测表直读）同一条规矩。"""
        from conftest import REPO
        xlsx = REPO / "out" / "_acquisition" / "202609" / "监测表.xlsx"
        if not xlsx.is_file():
            skip_unless("out/_acquisition/202609/监测表.xlsx 缺失",
                        lambda: xlsx.is_file())
        from flexible.workbook import WorkbookView
        ch = WorkbookView(xlsx).chain("papers", DISC, "202609")
        assert ch["dataset"].startswith("out/"), ch
        assert "C:" not in ch["dataset"] and not ch["dataset"].startswith("/")


# ================================================================ 5. 端到端
def _period_dir():
    from conftest import REPO
    outs = [p for p in (REPO / "out").glob("20*")
            if p.is_dir() and (p / "ledger_long.parquet").is_file()]
    gold = [p for p in outs if p.name == "202607"]
    return (gold or outs or [None])[0]


@pytest.fixture(scope="session")
def period_copy(tmp_path_factory):
    d = _period_dir()
    if d is None:
        skip_unless("out/ 下无含 ledger_long.parquet 的期次产物",
                    lambda: _period_dir() is not None)
    tmp = tmp_path_factory.mktemp("provenance") / d.name
    tmp.mkdir()
    shutil.copyfile(d / "ledger_long.parquet", tmp / "ledger_long.parquet")
    shutil.copytree(d / "wide", tmp / "wide")
    return tmp


@pytest.fixture(scope="session")
def flex_out(period_copy):
    """出一次带跨校的单学科稿（规则后端；写作位一律不碰网络）。"""
    import ai
    from ai._brain import RuleBrain
    with ai.using(brain=RuleBrain()):
        return report.generate(period_copy, "single_trend",
                               disc="Plant & Animal Science",
                               peers=["昆明理工大学"])


class Test端到端:
    def test_自检通过且不是空过(self, flex_out):
        c = flex_out["check"]
        assert c["pass"], c
        assert c["trace"]["checked"] > 0 and c["trace"]["bad"] == 0
        assert c["coverage"]["checked"] > 0 and c["coverage"]["uncovered"] == []
        assert c["evidence"]["chart"] == c["n_charts"]
        assert c["evidence"]["peer"] == 1

    def test_报告附录跨校行显示真来源(self, flex_out):
        md = pathlib.Path(flex_out["report"]).read_text(encoding="utf-8")
        rows = [ln for ln in md.splitlines()
                if ln.startswith("|") and "外部数据" in ln]
        assert len(rows) == 1, rows
        assert "数据与复现/ESI数据/" in rows[0]
        assert "Plant & Animal Science.xlsx" in rows[0]
        assert "植物与动物学" in rows[0]
        assert flex_out["selected"]["period"] in rows[0], "应采用实际归档期次"

    def test_全部来源路径都是仓库相对(self, flex_out):
        d = pathlib.Path(flex_out["dir"])
        text = (d / "report.md").read_text(encoding="utf-8")
        assert "C:" not in text and "C:/" not in text
        items = json.loads((d / "flex_sources.json").read_text(encoding="utf-8"))
        for item in items:
            src = item.get("source") or {}
            path = str(src.get("dataset") or "")
            assert path and "C:" not in path and not path.startswith("/"), item
            assert path.startswith(("out/", "数据与复现/")), item
        for item in items:
            if item["kind"] == "peers":
                assert item["source"]["dataset"].startswith("数据与复现/ESI数据/")
                assert item["source"]["period"]
                assert item["source"]["sheet"]

    def test_图表全部进账(self, flex_out):
        d = pathlib.Path(flex_out["dir"])
        items = json.loads((d / "flex_sources.json").read_text(encoding="utf-8"))
        charts = [x for x in items if x.get("kind") == "chart"]
        assert len(charts) == flex_out["n_charts"] > 0
        assert all(x["file"].startswith("charts/") for x in charts)
        assert all(x["source"]["dataset"] for x in charts)

    def test_跨校取数失败时判不过(self, period_copy, tmp_path):
        """指定了对标高校但取数失败 → 没登记任何 peer 证据，不能报「通过」。"""
        if not peers.ESI_ROOT.is_dir():
            skip_unless("ESI数据目录缺失", lambda: peers.ESI_ROOT.is_dir())
        d = tmp_path / period_copy.name
        d.mkdir()
        shutil.copyfile(period_copy / "ledger_long.parquet", d / "ledger_long.parquet")
        shutil.copytree(period_copy / "wide", d / "wide")
        import ai
        from ai._brain import RuleBrain
        with ai.using(brain=RuleBrain()):
            r = report.generate(d, "single_trend", disc="Plant & Animal Science",
                                peers=["不存在的大学"])
        assert not r["check"]["pass"], r["check"]
        assert r["check"]["peer"]["expected"] and not r["check"]["peer"]["ok"]
