# -*- coding: utf-8 -*-
"""证据账：一份灵活报告的每个数字、每张图，登记在**同一本账**上。

为什么要有这本账：正文里的数来自四处不同地方——台账查询（逐点带来源链）、
ESI 机构表（另一件数据源）、由查询值算出的派生数（差值、占比、篇均、外推期数）、
以及图。它们过去各自散落：查询塞进一个列表、跨校另起一条、图不进账、附录靠猜
结果形状，于是「每个数字都能回读」这句承诺没有一个单一的检查面。

本模块就是那个检查面：**一个深模块**。interface 只有「开一节、记一条、出附录、
跑自查」几个动作；各节的调用方不必知道条目怎么去重、怎么排序、怎么回读、怎么
把期次拼成区间。实现全在账本内部，查数面仍由调用方注入（`LedgerView` 协议不变），
所以 **seam** 没动：parquet 适配器与监测表适配器照旧。

这样一处改动只影响本文件（**locality**），各节只多一行登记（**leverage**）：
加一种新证据（比如将来的论文级清单）不必再改附录、自检、落盘三处。

条目四类，全部带 `source`（数据集 + 工作表/定位 + 期次）：

1. `query`：`queries` 的返回（series/compare/anomaly/…），逐点回读台账；
2. `peers`：ESI 机构表（**不是**台账），来源是数据件、工作表与**实际期次**；
3. `chart`：`spec.make` 出的图，来源是它画的那几张宽表/透视表；
4. `derived`：由上面几类算出的数（差值、占比、篇均、外推期数），来源记输入链。

「通过」判据（`Ledger.check`）：没有无来源条目、没有回读失败、没有空查询冒充通过、
声明的图都登记了、正文里每个数字都能在本节（判断节可继承整本账）找到登记值。
数字按**值**比对（含常见排版变体），不要求正文与账本同一句式。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

from . import queries as q
from .datasource import LedgerView, cn_name, relative_path

#: 账本条目的 JSON 形状（`flex_sources.json` 仍是**一个列表**，旧读者不受影响）。
QUERY_KINDS = frozenset(q.SCHEMA["kind"])

#: 数字比对用的排版变体：`_fmt`、千分位、常见小数位、`str` 都要认。
_NUM_FORMATS = ("{}", "{:g}", "{:.0f}", "{:.1f}", "{:.2f}", "{:.3f}", "{:.4f}",
                "{:,.0f}", "{:,.1f}", "{:,.2f}")

#: 期次/日期/口径写法先剥掉，剩下的才是「需要登记的数值」。
_PERIOD_TOKEN = re.compile(r"\d{6}")
_DATE_TOKEN = re.compile(r"\d{4}\s*年(?:\s*\d{1,2}\s*月)?|\d{1,2}\s*月")
_PCT_SHORTHAND = re.compile(r"(?<![\d.])1\s*[%‰]")
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w.])")
_SECTION_NUMBER = re.compile(r"^[一二三四五六七八九十]+、")


def _norm_number(token: str) -> str:
    return str(token).replace(",", "").strip()


def _variants(value) -> set[str]:
    """一个登记值在正文里可能出现的写法（含绝对值——正文常说「还差 N」）。"""
    out: set[str] = set()
    for v in (value, abs(value)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        for fmt in _NUM_FORMATS:
            try:
                out.add(_norm_number(fmt.format(f)))
            except (ValueError, TypeError):
                continue
    return out


#: 不是证据、但正文里合法出现的数值（口径常量；期次/日期另行剥掉）。
_CONSTANT_VARIANTS = _variants(1.0) | _variants(22)


@dataclass
class _Entry:
    """一条登记：对外只经 `sources_json()` / 附录 / 自查三处可见。"""

    kind: str
    section: str
    label: str = ""
    source: dict = field(default_factory=dict)
    values: list = field(default_factory=list)
    payload: dict | None = None
    file: str = ""
    allow_empty: bool = False


class Section:
    """一节手里的账本把手：本节画的每个数、每张图都从这里过。

    把手只认「结果」不认「数字」——`query` 收 `queries` 的返回，`chart` 收
    `spec.make` 的返回，`derive` 收由它们算出的值。调用方因此不可能绕开账本
    顺手打印一个数而不留痕（打印值仍在，但自查会发现它没登记）。
    """

    def __init__(self, ledger: Ledger, title: str) -> None:
        self._ledger = ledger
        self.title = title
        self.inherits = False
        """判断节读的是全篇事实摘要，数字可能来自别节——声明继承整本账。"""

    def query(self, result: dict, *, allow_empty: bool = False) -> dict:
        """登记一次查询结果并原样返回（调用方照常读 `points` / `rows`）。"""
        self._ledger._record_query(self, result, allow_empty=allow_empty)
        return result

    def chart(self, chart: dict) -> dict:
        """登记一张图并原样返回。"""
        self._ledger._record_chart(self, chart)
        return chart

    def peer(self, data: dict) -> dict:
        """登记跨校对比（ESI 机构表，非台账）并原样返回。"""
        self._ledger._record_peer(self, data)
        return data

    def derive(self, label: str, value, *, inputs=(), unit: str = "",
               period: str | None = None):
        """登记一个派生数（差值/占比/篇均/外推期数），原样返回值。

        `inputs` 传本节已登记过的查询结果——派生的来源链不是从天上掉的，
        而是「这几条台账链算出来的」。
        """
        self._ledger._record_derived(self, label, value, inputs=inputs, unit=unit,
                                     period=period)
        return value

    def inherit(self) -> None:
        """判断节声明：本节数字可来自整本账（全篇事实摘要）。"""
        self.inherits = True


class Ledger:
    """一本报告的账：开节、登记、出附录、跑自查。

    `view` 是查数面（`LedgerView`），只用于自查时逐点回读；账本自己不读文件。
    `view=None` 时是**兼容适配器**（旧调用方/手工拼的 `built` 字典）：只做形状
    转换，不做严格校验——产线路径永远带 `view`。
    """

    def __init__(self, view: LedgerView | None = None) -> None:
        self.view = view
        self.strict = view is not None
        self._entries: list[_Entry] = []
        self._sections: dict[str, Section] = {}
        self._by_result: dict[int, _Entry] = {}
        self._by_key: dict[tuple, _Entry] = {}

    # ------------------------------------------------------------ 开节
    def section(self, title: str) -> Section:
        """取一节的手把；同名节只建一次（重复进入不会多出一节）。"""
        sec = self._sections.get(title)
        if sec is None:
            sec = Section(self, title)
            self._sections[title] = sec
        return sec

    # ------------------------------------------------------------ 登记
    def _add(self, entry: _Entry) -> _Entry:
        self._entries.append(entry)
        return entry

    def _record_query(self, sec: Section, result: dict, *, allow_empty: bool) -> None:
        if not isinstance(result, dict) or "kind" not in result:
            return
        key = self._query_key(sec.title, result)
        if key in self._by_key:
            self._by_result[id(result)] = self._by_key[key]   # 派生仍能指回同一条链
            return
        source = _first_source(result)
        entry = self._add(_Entry(
            kind=str(result["kind"]), section=sec.title,
            label=_kind_label(result),
            source=dict(source or {}), values=_query_values(result),
            payload=result, allow_empty=allow_empty))
        self._by_key[key] = entry
        self._by_result[id(result)] = entry

    @staticmethod
    def _query_key(section: str, result: dict) -> tuple:
        """去重键：同节同类型同指标同学科同期次＝同一查询。"""
        pts = _items(result)
        return (section, result.get("kind"), result.get("metric"),
                result.get("disc"), result.get("period"), result.get("prev"),
                tuple(str(x.get("period")) for x in pts[:1]),
                tuple(str(x.get("discipline")) for x in pts[:1]),
                len(pts))

    def _record_chart(self, sec: Section, chart: dict) -> None:
        name = pathlib.Path(str(chart.get("path") or "")).name
        sources = [s for s in (chart.get("sources") or []) if isinstance(s, dict)]
        first = sources[0] if sources else {}
        sheet = "、".join(dict.fromkeys(
            str(s.get("origin_sheet") or "（派生）") for s in sources)) or "（派生）"
        dataset = str(first.get("dataset")
                      or ("" if self.strict else relative_path(chart.get("path") or "")))
        periods = [str(p) for p in (chart.get("periods") or [])]
        disc = chart.get("spec", {}).get("disc")
        locator = (f"{sheet}：{chart.get('kind_cn') or chart.get('kind')}"
                   f"（{_span(periods)}）")
        self._add(_Entry(
            kind="chart", section=sec.title,
            label=str(chart.get("kind_cn") or chart.get("kind") or "图"),
            source={"kind": "chart", "dataset": dataset, "origin_sheet": sheet,
                    "period": periods[-1] if periods else "",
                    "discipline": disc,
                    "discipline_cn": first.get("discipline_cn")
                                     or (cn_name(disc) if disc else "（全学科）"),
                    "locator": locator},
            payload={"kind": "chart", "chart_kind": chart.get("kind"),
                     "kind_cn": chart.get("kind_cn"), "periods": periods,
                     "file": f"charts/{name}" if name else "",
                     "sources": sources},
            file=f"charts/{name}" if name else ""))

    def _record_peer(self, sec: Section, data: dict) -> None:
        rows = data.get("rows") or []
        src = dict(data.get("source") or {})
        src.setdefault("origin_sheet", src.get("sheet") or "（派生）")
        src.setdefault("discipline", data.get("discipline"))
        src.setdefault("discipline_cn", data.get("discipline_cn"))
        src.setdefault("locator", f"{src.get('origin_sheet') or '机构表'}："
                                  f"{data.get('discipline_cn') or data.get('discipline')}"
                                  f" 机构行 × {data.get('period')}")
        values = []
        for row in rows:
            for v in (row.get("values") or {}).values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    values.append(float(v))
            if isinstance(row.get("rank_cn"), (int, float)):
                values.append(float(row["rank_cn"]))
        self._add(_Entry(
            kind="peers", section=sec.title,
            label=f"{data.get('discipline_cn') or data.get('discipline')}机构表",
            source=src, values=values,
            payload={"kind": "peers", "source": src, "n": len(rows), "rows": rows,
                     "period": data.get("period"),
                     "requested_period": data.get("requested_period"),
                     "discipline": data.get("discipline"),
                     "discipline_cn": data.get("discipline_cn")}))

    def _record_derived(self, sec: Section, label: str, value, *, inputs,
                        unit: str = "", period: str | None = None) -> None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        chain = [self._by_result[id(x)] for x in inputs if id(x) in self._by_result]
        base = chain[0].source if chain else {}
        locators = [str(e.source.get("locator") or "") for e in chain if e.source]
        when = str(period or "")
        if not when and chain:
            pts = [x for x in _items(chain[0].payload or {})
                   if isinstance(x, dict) and x.get("period")]
            if pts:
                when = str(pts[-1]["period"])
        when = when or str(base.get("period") or "")
        source = {
            "kind": "derived",
            "dataset": base.get("dataset") or ("" if self.strict else "（派生计算）"),
            "origin_sheet": "（派生）",
            "period": when,
            "discipline": base.get("discipline"),
            "discipline_cn": base.get("discipline_cn"),
            "locator": (f"（派生）{label}" + (f" = 由 {len(chain)} 条台账链算出"
                                              if chain else "")
                        + (f"；输入：{'；'.join(locators[:2])}" if locators else "")),
        }
        self._add(_Entry(
            kind="derived", section=sec.title, label=label, source=source,
            values=[float(value)],
            payload={"kind": "derived", "label": label, "value": float(value),
                     "unit": unit, "source": source}))

    # ------------------------------------------------------------ 读取
    def charts(self) -> list[dict]:
        """已登记的图（`built["charts"]` 的同一批对象，供落盘与前端清单）。"""
        out = []
        for e in self._entries:
            if e.kind == "chart" and e.payload:
                out.append({**e.payload, "path": e.file})
        return out

    def counts(self) -> dict:
        c = {"entries": len(self._entries), "query": 0, "chart": 0,
             "derived": 0, "peer": 0}
        for e in self._entries:
            key = ("peer" if e.kind == "peers"
                   else "query" if e.kind in QUERY_KINDS else e.kind)
            c[key] = c.get(key, 0) + 1
        return c

    def sources_json(self) -> list[dict]:
        """`flex_sources.json` 的内容：**一个列表**，每条都带 `source` 与所属节。"""
        out = []
        for e in self._entries:
            if e.payload is not None:
                item = dict(e.payload)
            else:
                item = {"kind": e.kind}
            item.setdefault("source", dict(e.source))
            item["section"] = e.section
            out.append(item)
        return out

    def appendix_markdown(self) -> str:
        """附录表：每一条证据一行；跨校/图表/派生也有真实数据集与工作表。"""
        lines = ["| # | 证据 | 指标 | 学科 | 期次 | 工作表 | 数据件 |",
                 "|---:|---|---|---|---|---|---|"]
        for i, e in enumerate(self._entries, 1):
            lines.append("| " + " | ".join(
                (str(i), _kind_cn(e.kind), _cell(e.label),
                 _cell(_discipline_of(e)), _cell(_period_of(e)),
                 _cell(e.source.get("origin_sheet") or "（派生）"),
                 _cell(e.source.get("dataset") or "（派生）"))) + " |")
        c = self.counts()
        lines += ["", f"共 {c['entries']} 条证据（查询 {c['query']} / 图表 {c['chart']} / "
                      f"派生 {c['derived']} / 外部数据 {c['peer']}）；每条的每个数据点都带独立"
                      f"来源链（见 `flex_sources.json`，逐点 `{{dataset, metric, discipline, "
                      f"period, origin_sheet}}`）。", ""]
        return "\n".join(lines)

    # ------------------------------------------------------------ 自查
    def check(self, *, blocks=(), periods=(), declared_charts=(), selected=None) -> dict:
        """账本自查：回读、空查询、来源、图登记、正文数字覆盖。

        返回的键与 `report.self_check` 的旧键同名（trace / trace_ok / peer /
        has_charts / n_charts），另加 `coverage` 与 `unregistered` 明细。
        """
        trace = self._trace()
        no_source = [e for e in self._entries if not _source_ok(e.source)]
        peer = self._peer(selected or {})
        charts = self._charts(declared_charts)
        coverage = self._coverage(blocks, periods)
        uncovered = coverage["uncovered"]
        # 「0/0 全对」的根治：有查询条目却一个数据点都没回读，同样判不过
        # （空查询可以是事实，但不能拿它冒充「全部可回读」）。
        vacuous = self.strict and trace["entries"] > 0 and trace["checked"] == 0
        trace_ok = (trace["bad"] == 0 and trace["no_source"] == 0 and not vacuous)
        evidence_ok = (trace_ok and not no_source and peer["ok"] and charts["ok"]
                       and charts["declared"] >= 1 and not uncovered)
        return {
            "trace": trace,
            "trace_ok": trace_ok,
            "peer": peer,
            "charts": charts,
            "has_charts": charts["declared"] >= 1,
            "n_charts": charts["declared"],
            "coverage": coverage,
            "unregistered": {
                "n": len(no_source) + len(charts["missing"]) + len(uncovered),
                "entries": [f"{e.section}：{e.label}" for e in no_source][:5],
                "charts": charts["missing"][:5],
                "numbers": uncovered[:5],
            },
            "evidence": self.counts(),
            "evidence_ok": evidence_ok,
        }

    def _trace(self) -> dict:
        trace = {"checked": 0, "ok": 0, "bad": 0, "misses": [],
                 "entries": 0, "no_source": 0, "empty": 0}
        for e in self._entries:
            if e.kind not in QUERY_KINDS:
                continue
            trace["entries"] += 1
            if not _source_ok(e.source):
                trace["no_source"] += 1
            if e.payload is None:
                continue
            if not _items(e.payload):
                if not e.allow_empty:
                    trace["empty"] += 1
                continue
            if self.view is None:
                continue
            got = q.trace_check(self.view, e.payload)
            trace["checked"] += got["checked"]
            trace["ok"] += got["ok"]
            trace["bad"] += got["bad"]
            trace["misses"] += got["misses"]
        return trace

    def _peer(self, selected: dict) -> dict:
        expected = bool(selected.get("peers"))
        rows = [e for e in self._entries if e.kind == "peers"]
        ok = (not expected) or (len(rows) == 1 and _source_ok(rows[0].source)
                                and bool(rows[0].source.get("period")))
        return {"expected": expected, "n": len(rows), "ok": ok}

    def _charts(self, declared) -> dict:
        names = []
        for c in declared or []:
            name = pathlib.Path(str((c or {}).get("path") or "")).name
            if name:
                names.append(name)
        registered = {e.file: e for e in self._entries if e.kind == "chart"}
        missing = [n for n in names if f"charts/{n}" not in registered]
        bad_source = [e.file for e in registered.values() if not _source_ok(e.source)]
        ok = not missing and not bad_source and (not self.strict or bool(names))
        return {"declared": len(names), "registered": len(registered),
                "missing": missing + bad_source, "ok": ok}

    def _coverage(self, blocks, periods) -> dict:
        if not self.strict:
            return {"checked": 0, "covered": 0, "uncovered": [], "sections": []}
        all_values: set[str] = set()
        for e in self._entries:
            for v in e.values:
                all_values |= _variants(v)
        checked = covered = 0
        uncovered = []
        sections = []
        for title, body in blocks or []:
            bare = _bare_title(str(title))
            sec = self._sections.get(bare)
            local = set(all_values) if (sec is not None and sec.inherits) else set()
            if sec is not None:
                for e in self._entries:
                    if e.section == bare:
                        for v in e.values:
                            local |= _variants(v)
            for token in _numbers(str(body), periods):
                checked += 1
                if _norm_number(token) in local or _norm_number(token) in _CONSTANT_VARIANTS:
                    covered += 1
                else:
                    uncovered.append({"section": bare, "value": token})
            if any(x["section"] == bare for x in uncovered):
                sections.append(bare)
        return {"checked": checked, "covered": covered,
                "uncovered": uncovered, "sections": sections}


# ------------------------------------------------------------------ 辅助
def ledger_of(built: dict) -> Ledger:
    """取 `built` 里的账；手工拼的旧字典走兼容适配器（不做严格校验）。"""
    led = (built or {}).get("ledger")
    if isinstance(led, Ledger):
        return led
    return _from_built(built or {})


def _from_built(built: dict) -> Ledger:
    """兼容适配器：把旧形状 `{sources, charts}` 包成一本账（能读不能严判）。"""
    led = Ledger(None)
    sec = led.section("（旧稿）")
    for r in built.get("sources") or []:
        if isinstance(r, dict) and "kind" in r:
            led._record_query(sec, r, allow_empty=True)
    for c in built.get("charts") or []:
        if isinstance(c, dict):
            led._record_chart(sec, c)
    led.strict = False
    return led


def _items(result: dict) -> list:
    return list(result.get("points") or result.get("items") or result.get("rows")
                or result.get("events") or [])


def _first_source(result: dict) -> dict | None:
    if isinstance(result.get("source"), dict):
        return result["source"]
    for it in _items(result):
        if isinstance(it.get("source"), dict):
            return it["source"]
    return None


def _kind_label(result: dict) -> str:
    if result.get("metric_cn"):
        return str(result["metric_cn"])
    return {"compare": "跨学科横截面", "anomaly": "异常清单",
            "events": "进出前 1%", "overall_rank": "云大整体排名",
            "scope": "统计摘要"}.get(str(result.get("kind")), str(result.get("kind")))


def _query_values(result: dict) -> list:
    vals = []
    for it in _items(result):
        if not isinstance(it, dict):
            continue
        for key in ("value", "prev_value", "ratio", "diff", "ratio_pct",
                    "rank_intl", "rank_cn", "rank_cn_uni"):
            v = it.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))
    return vals


def _source_ok(source: dict) -> bool:
    if not isinstance(source, dict) or not source:
        return False
    if not source.get("dataset") or source.get("dataset") == "（未登记）":
        return False
    return bool(source.get("locator") or source.get("origin_sheet"))


def _numbers(text: str, periods) -> list[str]:
    for p in periods or ():
        text = text.replace(str(p), " ")
    text = _PERIOD_TOKEN.sub(" ", text)
    text = _DATE_TOKEN.sub(" ", text)
    text = _PCT_SHORTHAND.sub(" ", text)
    return _NUMBER.findall(text)


def _bare_title(title: str) -> str:
    return _SECTION_NUMBER.sub("", title).strip()


def _span(periods: list[str]) -> str:
    ps = list(dict.fromkeys(str(p) for p in periods if str(p)))
    if not ps:
        return "—"
    return ps[0] if len(ps) == 1 else f"{ps[0]}–{ps[-1]}"


def _kind_cn(kind: str) -> str:
    return {"peers": "外部数据", "chart": "图表", "derived": "派生"}.get(kind, kind)


def _discipline_of(entry: _Entry) -> str:
    src = entry.source
    return str(src.get("discipline_cn") or src.get("discipline") or
               ("（全学科）" if entry.kind in ("compare", "anomaly", "events",
                                              "scope", "overall_rank") else "—"))


def _period_of(entry: _Entry) -> str:
    periods = []
    if entry.kind == "chart":
        periods = list((entry.payload or {}).get("periods") or [])
    elif entry.payload is not None:
        periods = [str(x.get("period")) for x in _items(entry.payload)
                   if isinstance(x, dict) and x.get("period")]
        if not periods and entry.payload.get("period"):
            periods = [str(entry.payload["period"])]
    if not periods and entry.source.get("period"):
        periods = [str(entry.source["period"])]
    return _span(periods)


def _cell(value) -> str:
    """表格单元格：竖线会截断列，换成全角；空值写破折号（不让读者以为是漏登）。"""
    s = str(value if value is not None else "").replace("|", "／").strip()
    return s or "—"
