# -*- coding: utf-8 -*-
"""灵活报告编排：规划 → 查询 → 数字回填骨架 → spec 出图 → 产出 md。

流程（全部可回放）：

    planner.build()          选科/选指/选期/选图型   ← 模型位可插拔，rule 为默认
      ↓
    queries.execute()        取数（**唯一**的数字来源，逐点带来源链）
      ↓
    opinion.descriptive_*()  描述性判断（规则生成，不经模型）
      ↓
    spec.make()              JSON spec → 复用 charts.py 排版设施出图
      ↓
    渲染 md                  内部参考件（页脚标注，不带盖章位）

**写作位（配好即默认启用，2026-10-14 票 04）**：`WENHENG_FLEX_WRITE` 开且配云时，
描述节交给 `ai._writer.write`（规则稿 + 事实摘要 → 分析体叙述）、末两节交给
`ai._writer.compose`（节主题 + 事实摘要 → 判断草稿，待审线 `==…==` 自标＋兜底补标）；
数字/图表/来源链一律不变，任何校验不过整段回退（描述节 → 规则稿；判断节 → `【手工：】`空位）。
`polish=False` 是显式关闭路径。见 `.scratch/flexible-writing/spec.md`。

**逐节回调与流式**：`_generate(..., on_event=…)` 在「规划完成」「每节完成」时回调；
`generate_stream()` 是同一个核的流式包装（真实事件，不做假进度）。

🔴 自检在 `self_check()` 里，产出后立即跑，结果随报告一起落盘：

1. 判断句都带了标记（`opinion.judgement_leaks`；`==…==` 待审线或 `【手工：…】`空位除外）
2. 每个数字都能回读（查询/跨校/图表/派生数都登记在 `provenance` 的一本账上；
   `queries.trace_check` 逐点回读，正文里没登记的数字同样判不过）
3. 至少有一张图（空图分析稿不算完整稿）
"""
from __future__ import annotations

import json
import pathlib
import shutil
import time
from dataclasses import dataclass, field

from . import opinion as op
from . import planner, provenance as pv, queries as q, spec as sp
from .datasource import METRICS, DataSource, cn_name, period_label

BANNER = "内部参考 · 非报送件"
"""导出件页脚/页眉标注。从源头杜绝「分析稿被误当正式报告发出去」。"""

MARK_LEGEND = ("细下划线的句子＝**待审句**，需馆员拍板；拍板线下完成。")
"""待审线图例。2026-10-15（rick）：报告内不再重复「内部参考·非报送」声明——
页面导语已承担该声明，下载件（html/docx）由各自页脚标注；正文只留这一行图例，
仅当本稿走写作位（`mode == "write"`）时附上——规则版没有待审线，不摆空图例。"""

#: 章节序号（灵活报告节数有限，够用即可）
_CN_NUM = "一二三四五六七八九十"


def _dir_for(out_dir, intent: str) -> pathlib.Path:
    return pathlib.Path(out_dir) / "flexible" / intent


def _fmt(v) -> str:
    if isinstance(v, (int, float)):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.4g}"
    return str(v)


def _kv_table(rows: list[tuple]) -> str:
    out = ["| 指标 | 数值 | 来源（台账工作表：定位） |", "|---|---:|---|"]
    for name, val, chain in rows:
        out.append(f"| {name} | {_fmt(val)} | `{chain['origin_sheet']}`："
                   f"{chain['locator'].split('：', 1)[-1]} |")
    return "\n".join(out)


def _numbered(labels: list[str]) -> list[str]:
    return [f"{_CN_NUM[i]}、{lab}" for i, lab in enumerate(labels)]


@dataclass
class _ReportCtx:
    """一次灵活报告构建的共享上下文。

    「有哪些节」由 `_single_sections` 返回的 `[(标题, 构建函数)]` 决定；
    **大纲就是这份表的标题**——标题与正文合成一处编排，改节名不会再漏改大纲。

    **一本账**：数字与图不再散在多个桶里，全部经 `ledger`（`provenance`）登记；
    节的正文、附录、自查、`flex_sources.json` 读的是同一本账。
    """

    src: DataSource
    plan: dict
    chart_dir: pathlib.Path
    specs_out: list
    mode: str
    period_name: str
    ledger: pv.Ledger
    blocks: list = field(default_factory=list)
    log: list = field(default_factory=list)
    selected: dict = field(default_factory=dict)
    pool: list = field(default_factory=list)
    """全篇事实摘要（各节已算过的数据点，人话一行一条）——判断节创写的输入之一。"""
    backstop_n: int = 0
    """兜底补标累计句数（判断节；透明计数进 check 与 write 摘要）。"""

    def P(self, text, label, facts=()):
        return _polish(self.mode, text, label, facts=facts,
                       period=self.period_name, log=self.log)

    def J(self, what: str, topic: str, safe: str, facts=()) -> str:
        """判断节创写（票 04）：主题＋事实摘要 → 判断草稿；失败/未开 → 安全值（空位）。"""
        if self.mode != "write" or not topic:
            return safe
        got, n = _compose(topic, safe, facts=facts, period=self.period_name,
                          label=f"flexible/{self.plan['intent']}/{what}", log=self.log)
        self.backstop_n += n
        return got


def _collect(sections, on_section=None, on_outline=None) -> list:
    """按节表逐节构建：先发大纲（编号后），再逐节出正文并回调。"""
    titles = _numbered([t for t, _ in sections])
    if on_outline:
        on_outline(titles)
    blocks = []
    for (_, fn), title in zip(sections, titles):
        body = fn()
        blocks.append((title, body))
        if on_section:
            on_section(title, body)
    return blocks


# ------------------------------------------------------------------ 单学科诊断
def _snapshot(src: DataSource, disc: str, sec: pv.Section) -> tuple[list, float | None]:
    """当期核心指标快照（概况/落点两处共用）。返回 (kv 行, 距阈值差)。

    `sec` 是本节账本把手：查询与派生差都登记，正文里每个数都能回读。
    """
    period = src.current_period()
    rows = []
    got = {}
    for met in ("proximity_1pct", "rank", "total_cites", "threshold_1pct", "top_papers"):
        r = sec.query(q.series(src, met, disc, [period]))
        got[met] = r
        if r["points"]:
            p = r["points"][0]
            rows.append((r["metric_cn"], p["value"], p["source"]))
    tc, th = got["total_cites"], got["threshold_1pct"]
    gap = (tc["points"][0]["value"] - th["points"][0]["value"]
           if tc["points"] and th["points"] else None)
    if gap is not None:
        sec.derive("距 1% 阈值差", gap, inputs=(tc, th), unit="次", period=period)
    return rows, gap


def _snapshot_facts(rows: list, gap) -> list[str]:
    facts = [f"{name}：{_fmt(val)}" for name, val, _ in rows]
    if gap is not None:
        facts.append("距 1% 阈值：" + (f"高出 {_fmt(gap)} 次" if gap >= 0
                                       else f"还差 {_fmt(abs(gap))} 次"))
    return facts


def _series_facts(r: dict) -> list[str]:
    if not r.get("points"):
        return []
    vs = "、".join(_fmt(p["value"]) for p in r["points"])
    return [f"{r['metric_cn']}：{vs}（{r['points'][0]['period']}–{r['points'][-1]['period']}）"]


def _render_charts(src: DataSource, plan: dict, chart_dir, specs_out, sec: pv.Section,
                   default_disc=None, only_scope=None, only_kinds=None) -> str:
    """按规划**逐张**出图，登记进本节账本，返回 markdown 片段。

    🔴 这里曾经硬编码只认 3 个图型（cites_threshold / papers_delta / rank_pct）。
    真实模型一旦选了别的（实测 qwen2.5:3b 选了 `overview_1permille` + `cnci`），
    一张图都不出 —— 而正文和自检照常报"通过"。图型清单以 `spec.KINDS` 为准，
    这里不许再列白名单。

    `only_scope`：只渲染某类图（锚定稿把单学科图放走势节、总览图放对比节）。
    """
    out = []
    for c in plan["charts"]:
        kind = c.get("kind")
        if kind not in sp.KINDS:
            continue
        if only_kinds and kind not in only_kinds:
            continue
        scope = sp.KINDS[kind]["disc_scope"]
        if only_scope and scope != only_scope:
            continue
        if scope == "single":
            disc = c.get("disc") or default_disc
            if not disc:
                continue
            s = sp.make(src, {"kind": kind, "disc": disc}, chart_dir)
        else:
            s = sp.make(src, {"kind": kind}, chart_dir)
        specs_out.append(s)
        sec.chart(s)
        # 🔴 相对路径以 **report.md 所在目录** 为锚（产物结构 = <intent>/report.md
        #    + <intent>/charts/*.png）。写成 `../charts/` 会指到 flexible/charts/
        #    这个不存在的目录 —— 图片全断链，且不抛异常，只有打开看才发现。
        out.append(f"\n\n![{s['kind_cn']}](charts/{pathlib.Path(s['path']).name})\n\n"
                   f"*{c.get('why') or s['kind_cn']}*")
    return "".join(out)


def _polish(mode, text: str, label: str = "", *, facts=(), period: str = "",
            log: list | None = None) -> str:
    """写作/润色位。`mode ∈ {"off","polish","write"}`；假值 → 原样返回，不碰模型。

    - `write`：规则稿 + 事实摘要 → 分析体叙述（`ai._writer`；守卫在 flexible 侧通过
      `veto` 传入——ai 层不 import flexible）。
    - `polish`：旧润色位（只顺措辞），行为不变。
    任何失败都返回原文（写作/润色不是产出步骤）。
    """
    if not text or mode in (None, False, "off"):
        return text
    try:
        if mode == "write":
            from ai import _writer                                     # noqa: PLC0415
            st: dict = {}
            got = _writer.write(text, facts=facts, period=period, label=label,
                                veto=lambda t: bool(op.guard(t)), status=st)
            if log is not None:
                log.append({"label": label, "fallback": st.get("fallback"),
                            "changed": got != text})
            return got
        from . import polish as _p                                      # noqa: PLC0415
        return _p.rewrite(text)
    except Exception:                                                   # noqa: BLE001
        return text


def _compose(topic: str, safe: str, *, facts=(), period: str = "", label: str = "",
             log: list | None = None) -> tuple[str, int]:
    """判断节创写（票 04）：节主题＋事实摘要 → 判断草稿；返回 (文本, 兜底补标句数)。

    - 模型自标待审线为主；漏标句由 `opinion.backfill_marks` 确定性补标并计数；
    - `veto`＝标记完备性复查：**补标后仍有漏标**（如标记语法损坏）→ 整节回退安全值；
    - 任何失败都返回安全值（`【手工：】`空位），不抛。
    """
    if not topic:
        return safe, 0
    try:
        from ai import _writer                                     # noqa: PLC0415

        def _veto(t: str) -> bool:
            fixed, _ = op.backfill_marks(t)
            return bool(op.judgement_leaks(fixed))

        st: dict = {}
        got = _writer.compose(topic, facts=facts, safe=safe, period=period, label=label,
                              veto=_veto, status=st)
        if st.get("mode") == "model":
            got, n = op.backfill_marks(got)
            if log is not None:
                log.append({"label": label, "fallback": None, "changed": True, "backstop": n})
            return got, n
        if log is not None:
            log.append({"label": label, "fallback": st.get("fallback"), "changed": False,
                        "backstop": 0})
        return safe, 0
    except Exception:                                                   # noqa: BLE001
        return safe, 0


def _single_sections(c: _ReportCtx) -> list:
    """单学科分析的节表（顺序即大纲；2026-10-20 定五节）。

    每一节从 `c.ledger.section(...)` 取一个把手：画的每个数、每张图都登记到
    同一本账。正文措辞不变，变的是「数字从哪来」有了单一检查面。
    """
    disc, dcn = c.plan["disc"], cn_name(c.plan["disc"])
    period = c.src.current_period()
    prev = c.src.periods[c.src.periods.index(period) - 1]
    win = c.plan["periods"]
    c.selected = {"disc": disc, "disc_cn": dcn, "period": period, "prev": prev,
                  "peers": list(c.plan.get("peers") or [])}

    def sec_overview() -> str:
        # 一、学科概况（每个数都走查询，带链）
        sec = c.ledger.section("学科概况")
        rows, gap = _snapshot(c.src, disc, sec)
        facts = _snapshot_facts(rows, gap)
        c.pool += facts
        lead = c.P(op.gap_lead(period_label(period), dcn, gap),
                   "flexible/single_trend/概况", facts)
        return (lead + "\n\n" + _kv_table(rows)
                + _render_charts(c.src, c.plan, c.chart_dir, c.specs_out, sec,
                                 disc, only_kinds=("cites_threshold",)))

    def sec_impact() -> str:
        # 二、学术影响力：CNCI 走势 + 篇均由总被引/发文派生
        sec = c.ledger.section("学术影响力")
        cnci = sec.query(q.series(c.src, "cnci", disc, win))
        facts = _series_facts(cnci)
        tc = sec.query(q.series(c.src, "total_cites", disc, win))
        pp = sec.query(q.series(c.src, "papers", disc, win))
        if cnci["points"]:
            last = cnci["points"][-1]
            facts.append(f"最新 CNCI：{_fmt(last['value'])}（全球平均为 1.0）")
            if tc["points"] and pp["points"] and pp["points"][-1]["value"]:
                per = sec.derive(
                    "最新篇均被引",
                    tc["points"][-1]["value"] / pp["points"][-1]["value"],
                    inputs=(tc, pp), unit="次/篇", period=pp["points"][-1]["period"])
                facts.append(f"最新篇均被引：{_fmt(per)} 次/篇")
        c.pool += facts
        lead = (f"{dcn}的 CNCI 在 {period_label(win[0])} 至 {period_label(win[-1])} 间"
                f"由 {_fmt(cnci['points'][0]['value'])} 变为 "
                f"{_fmt(cnci['points'][-1]['value'])}；CNCI 的全球平均水平恒为 1.0，"
                f"高于 1.0 表示论文影响力高于全球同类论文。"
                if cnci["points"] else f"{dcn}本期没有 CNCI 数据。")
        return (c.P(lead, "flexible/single_trend/影响力", facts)
                + _render_charts(c.src, c.plan, c.chart_dir, c.specs_out, sec,
                                 disc, only_kinds=("cnci",)))

    def sec_rank() -> str:
        # 三、学科排名：国际/国内位次与百分位
        sec = c.ledger.section("学科排名")
        ri = sec.query(q.series(c.src, "rank_intl", disc, win))
        rc = sec.query(q.series(c.src, "rank_cn", disc, win))
        rp = sec.query(q.series(c.src, "rank_intl_pct", disc, win))
        facts = _series_facts(ri) + _series_facts(rc)
        if ri["points"] and rc["points"]:
            first_i, last_i = ri["points"][0]["value"], ri["points"][-1]["value"]
            first_c, last_c = rc["points"][0]["value"], rc["points"][-1]["value"]
            pct = ""
            if rp["points"]:
                last_pct = sec.derive(
                    "最新国际排名百分位", rp["points"][-1]["value"] * 100,
                    inputs=(rp,), unit="%", period=rp["points"][-1]["period"])
                pct = f"最新国际排名百分位为 {_fmt(last_pct)}%。"
            lead = (f"{dcn}的国际排名从 {period_label(win[0])} 的第 {_fmt(first_i)} 名"
                    f"变为第 {_fmt(last_i)} 名；国内排名从第 {_fmt(first_c)} 名"
                    f"变为第 {_fmt(last_c)} 名。" + pct)
        else:
            lead = f"{dcn}本期没有可用的排名序列。"
        c.pool += facts
        return (c.P(lead, "flexible/single_trend/排名", facts)
                + _render_charts(c.src, c.plan, c.chart_dir, c.specs_out, sec,
                                 disc, only_kinds=("rank_pct",)))

    def sec_peers() -> str:
        # 四、跨校对比：同一学科，云南大学 vs 用户指定高校
        sec = c.ledger.section("跨校对比")
        requested = list(c.plan.get("peers") or [])
        if not requested:
            return ("本次未指定对标高校。请先给出高校名单（中文校名或 ESI 英文名），"
                    "例如“昆明理工大学、云南农业大学”；本节留空，不做默认名单。")
        from . import peers as peer_mod                               # noqa: PLC0415
        try:
            data = peer_mod.compare(period, disc, requested)
        except peer_mod.PeerError as e:
            return f"跨校对比未完成：{e}"
        c.selected["peers"] = data["requested"]
        c.selected["peer_source"] = data["source"]
        # 跨校数字走 ESI 机构表，不在台账查询链里；作为**第一类证据**登记
        # （kind=peers），附录因此显示真实数据件、工作表与实际期次。
        sec.peer(data)
        lines = [
            "| 高校 | 全球位次 | 国内位次 | 发文量 | 总被引 | 篇均被引 | 顶尖论文 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in data["rows"]:
            name = row["cn"] or row["en"]
            if row["en"] == data["ynu"]["en"]:
                name = f"**{name}**"
            if not row["present"]:
                lines.append(f"| {name} | — | — | — | — | — | — |")
                continue
            v = row["values"]
            lines.append(
                f"| {name} | {_fmt(v['rank'])} | {_fmt(row['rank_cn'])} | "
                f"{_fmt(v['papers'])} | {_fmt(v['cites'])} | "
                f"{_fmt(v['cites_per_paper'])} | {_fmt(v['top_papers'])} |")
        ynu = data["rows"][0]
        peers_txt = "、".join(data["requested"]) or "（未指定）"
        if data["period"] != period:
            lead = (f"{period_label(period)}的机构表尚未归档，本节采用"
                    f"{period_label(data['period'])}机构表：{dcn}学科，"
                    f"云南大学全球第 {_fmt(ynu['values']['rank'])} 位"
                    f"（大陆第 {_fmt(ynu['rank_cn'])} 位）；对标高校：{peers_txt}。")
        else:
            lead = (f"{period_label(data['period'])}机构表：{dcn}学科，"
                    f"云南大学全球第 {_fmt(ynu['values']['rank'])} 位"
                    f"（大陆第 {_fmt(ynu['rank_cn'])} 位）；对标高校：{peers_txt}。")
        c.pool += [f"{r['cn'] or r['en']}：全球第 {_fmt(r['values']['rank'])} 位"
                   for r in data["rows"] if r["present"]]
        return (c.P(lead, "flexible/single_trend/跨校", c.pool[-len(data["rows"]):])
                + "\n\n" + "\n".join(lines)
                + f"\n\n来源：`{data['source']['dataset']}`（{data['source']['sheet']}）。")

    def sec_outlook() -> str:
        # 五、学科展望：被引频次与 1‰ 阈值（规则推演，不冒充预测模型）
        sec = c.ledger.section("学科展望")
        span = c.src.filled_periods[-9:]
        tc = sec.query(q.series(c.src, "total_cites", disc, span))
        th = sec.query(q.series(c.src, "threshold_1permille", disc, span))
        chart = _render_charts(c.src, c.plan, c.chart_dir, c.specs_out, sec,
                               disc, only_kinds=("cites_permille",))
        if not tc["points"] or not th["points"]:
            return f"{dcn}暂无 1‰ 阈值数据，本节只保留被引频次走势。" + chart
        gap = th["points"][-1]["value"] - tc["points"][-1]["value"]
        first = tc["points"][0]["value"]
        last = tc["points"][-1]["value"]
        n = len(tc["points"]) - 1
        growth = (last - first) / n if n else 0
        sec.derive("距 1‰ 阈值差", gap, inputs=(tc, th), unit="次",
                   period=tc["points"][-1]["period"])
        sec.derive("外推窗口期数", n + 1, inputs=(tc,), unit="期",
                   period=tc["points"][-1]["period"])
        facts = [f"最新总被引：{_fmt(last)}", f"最新 1‰ 阈值：{_fmt(th['points'][-1]['value'])}",
                 f"距 1‰ 阈值：{_fmt(abs(gap))} 次（{'已超过' if gap <= 0 else '还差'}）"]
        base = (f"最新总被引 {_fmt(last)} 次，1‰ 阈值为 "
                f"{_fmt(th['points'][-1]['value'])} 次，"
                + ("已高出阈值" if gap <= 0 else f"还差 {_fmt(gap)} 次"))
        if gap > 0 and growth > 0:
            growth = sec.derive("窗口内平均每期净增", growth, inputs=(tc,), unit="次/期",
                                period=tc["points"][-1]["period"])
            need = int(gap / growth) + 1
            need = sec.derive("外推所需期数", need, inputs=(tc, th), unit="期",
                              period=tc["points"][-1]["period"])
            years = sec.derive("外推所需年数", need * 2 / 12, inputs=(tc, th), unit="年",
                               period=tc["points"][-1]["period"])
            tail = (base + f"；按最近 {n + 1} 期平均每期净增 {_fmt(growth)} 次测算，"
                    f"约需 {need} 期（约 {years:.1f} 年）达到 1‰ 阈值。"
                    f"这是**规则推演**，不是预测模型，仅供判断参考。")
        elif gap <= 0:
            tail = base + "；按当期数据，我校该学科被引频次已达到 1‰ 阈值。"
        else:
            tail = base + "；最近窗口内被引频次未形成净增长，暂不外推追平时间。"
        c.pool += facts
        return c.P(tail, "flexible/single_trend/展望", facts) + chart

    def sec_judge_cause() -> str:
        # 成因研判（判断草稿）：全篇事实摘要 + 该主题查询结果（本期异动）
        sec = c.ledger.section("成因研判（判断草稿）")
        sec.inherit()          # 读全篇事实摘要：数字可能来自前面各节
        facts = list(c.pool)
        an = sec.query(q.anomaly(c.src, period), allow_empty=True)
        for x in [i for i in an["items"] if i["discipline"] == disc][:3]:
            facts.append(f"{dcn}的{x['metric_cn']}本期出现 {x['ratio']} 倍环比变动"
                         f"（{x['prev']}→{x['period']}）")
        safe = "\n".join([f"- {op.manual(f'{dcn}接近度变化的主要成因')}",
                          f"- {op.manual(f'{dcn}与发文量、总被引的关联研判')}"])
        return c.J("成因研判", f"{dcn}接近度走势的成因研判", safe, facts)

    def sec_judge_advice() -> str:
        # 建议事项（判断草稿）
        sec = c.ledger.section("建议事项（判断草稿）")
        sec.inherit()
        safe = "\n".join([f"- {op.manual(f'{dcn}发展力度评价')}",
                          f"- {op.manual(f'{dcn}资源投入建议')}",
                          "- " + op.manual("是否需要向学院核实数据口径")])
        return c.J("建议事项", f"{dcn}的建议事项", safe, list(c.pool))

    return [("学科概况", sec_overview), ("学术影响力", sec_impact),
            ("学科排名", sec_rank), ("跨校对比", sec_peers),
            ("学科展望", sec_outlook),
            ("成因研判（判断草稿）", sec_judge_cause),
            ("建议事项（判断草稿）", sec_judge_advice)]


def _build(c: _ReportCtx, on_section=None, on_outline=None) -> dict:
    """取节表 → 逐节构建 → 返回既有形状的 built dict。

    `built["sources"]` 与 `built["charts"]` 都从**同一本账**读出：附录、自检、
    `flex_sources.json` 不可能再各看各的。
    """
    sections = _single_sections(c)
    c.blocks = _collect(sections, on_section, on_outline)
    return {"blocks": c.blocks, "sources": c.ledger.sources_json(),
            "charts": c.ledger.charts(), "ledger": c.ledger,
            # 票 02：锚点要比对的三样都随 built 走——specs＝实际执行的 spec 清单
            # （与 flex_specs.json 同源），plan＝含 checks 的声明（自检签名不变）。
            "specs": [s["spec"] for s in c.specs_out], "plan": dict(c.plan),
            "backstop_n": c.backstop_n, "write_log": c.log,
            "selected": dict(c.selected)}


# ------------------------------------------------------------------ 渲染
def _render(plan: dict, built: dict, meta: dict) -> str:
    # 2026-10-15（rick）：报告内不再重复「内部参考·非报送」声明（页面导语已有；
    # 下载件由 SHELL / docx 页脚标注）——正文只留待审线图例，且只在本稿走写作位时附上。
    L = [f"# {plan.get('title') or '灵活分析稿'}", ""]
    if meta.get("mode") == "write":
        L += [f"> {MARK_LEGEND}", ""]
    if plan.get("fallback_reason"):
        L += [f"> ⚠ 规划回退：{plan['fallback_reason']}", ""]
    L += [
         f"> 期次：**{period_label(built['selected']['period'])}**"
         + (f"（上期 {period_label(built['selected']['prev'])}）"
            if built['selected'].get('prev') else ""),
         f"> 意图：{planner.INTENTS[plan['intent']]}"
         f"　｜　规划后端：**{plan['backend']}**"
         + (f"（{plan['fallback_reason']}）" if plan.get("fallback_reason") else ""),
         f"> 生成时间：{meta['generated_at']}", ""]
    L += ["---", ""]
    for title, body in built["blocks"]:
        L += [f"## {title}", "", body, ""]
    L += ["---", "## 本稿如何产生（可验证的架构主张）", "",
          "本件里的**台账数字**都只经过这一条路径：",
          "",
          "1. 规划器只决定「写哪个学科、配哪些图」——它的输出里**没有数字这个物种**；",
          "2. 数值由查询工具从 `ledger_long.parquet` 取出，逐点附**来源链**；"
          "第四节「跨校对比」另取 ESI 机构表（该节已标出源文件与工作表）；",
          "3. 图上每个点由引擎按 JSON spec 渲染，**模型不接触坐标**；",
          "4. 模型如给出图表声明，只允许 `invert` / `include` / `zero_base` 这类**语义**参数，"
          "轴范围永远由数据决定（代码里没有「纵轴上下界」这个字段）。",
          "",
          "因此模型在本产线里的输出只有三种：**查询、图表声明、正文草稿**——"
          "草稿里的数字位是占位符，由工具回填、逐格可回读；"
          "馆员需拍板的判断句以细下划线标出（待审线）。"
          "（设计口径见 `评审文档/19` §2.2）", ""]
    # 来源链附录：读同一本账（查询/图表/派生/跨校都在表里，各有真实来源）
    L += ["---", "## 附：数据来源链", "", pv.ledger_of(built).appendix_markdown()]
    L += ["---", f"*{BANNER}｜灵活报告产线｜不带盖章位*", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ 校验锚点（票 02）
def _chart_tag(key: str) -> str:
    """`kind|disc` → 人话短名（misses 用；只含图型名/学科名，不含报告数值）。"""
    kind, _, disc = key.partition("|")
    return f"{kind}（{disc}）" if disc else kind


def _declared_chart_keys(plan: dict) -> list[str]:
    """计划声明的图（flex_plan.json 的 charts）→ `kind|disc` 键，保序去重。"""
    keys = [f"{c.get('kind')}|{c.get('disc') or ''}"
            for c in plan.get("charts") or [] if isinstance(c, dict)]
    return list(dict.fromkeys(keys))


def _anchor_source_trace(plan: dict, built: dict) -> dict:
    """① source_trace（all_points / bidirectional）：数据点与来源双向对得上。

    正向＝每个数据点的 `source` 四字段（dataset/metric/discipline/period）齐全，
    缺一即红。反向＝**按 metric ↔ 消费它的图**：每张声明图要消费的指标
    （`spec.KINDS[kind]["needs"]`），在来源清单里至少有一条查询条目。

    🔴 反向**不按 kind 比对**：来源条目的 kind 是查询类型（series/compare/…），
    图的 kind 是图型（cites_threshold/…）——两套词表永远匹配不上，原型
    （prototype/critic-anchors，202607 真产物）在干净产物上即误报。

    🔴 反向也**不做「来源条目必须被图消费」**这半边：概况节的接近度/名次/
    顶尖论文、影响力节的发文数等只进正文表格与导语句，本来就没有图消费
    （proximity_1pct/rank/top_papers/papers/rank_intl_pct 均无图），按此判
    会在干净产物上误报。「来源被消费」由证据账的 coverage（正文数字全覆盖，
    `provenance._coverage`）承担，这里不重复。needs 里的非台账表
    （q1q4/ynd_rank/entered_1pct）是宽表直读、不走查询链，同样不参与比对。
    """
    fwd: list[str] = []
    have: set[str] = set()
    for entry in built.get("sources") or []:
        if not isinstance(entry, dict) or entry.get("kind") not in pv.QUERY_KINDS:
            continue                                    # chart/derived/peers 无逐点链
        metric = entry.get("metric")
        if metric:
            have.add(str(metric))
        pts = [x for x in (entry.get("points") or entry.get("items")
                           or entry.get("rows") or entry.get("events") or [])
               if isinstance(x, dict)]
        if not pts and isinstance(entry.get("source"), dict):
            pts = [{"source": entry["source"]}]         # at/delta：链在顶层
        for it in pts:
            m = it.get("metric") or metric
            if m:
                have.add(str(m))
            for key in ("source", "source_prev"):
                chain = it.get(key)
                if not isinstance(chain, dict):
                    continue                            # 无链的点由 trace 判坏，不在此重复
                missing = [f for f in ("dataset", "metric", "discipline", "period")
                           if not chain.get(f)]
                if missing:
                    fwd.append(f"数据点缺出处（{'、'.join(missing)}）："
                               f"{m or '?'}·{chain.get('period') or it.get('period') or '?'}")
    needed: set[str] = set()
    for c in plan.get("charts") or []:
        meta = sp.KINDS.get((c or {}).get("kind"))
        if meta:
            needed |= {m for m in meta["needs"] if m in METRICS}
    misses = fwd + [f"声明图的指标 {m} 无来源条目" for m in sorted(needed - have)]
    return {"pass": not misses, "misses": misses}


def _anchor_spec_query(plan: dict, built: dict) -> dict:
    """② spec_query_match（charts / declared==executed）：声明 ↔ 执行记录，双向。

    声明＝计划 `charts`（落 `flex_plan.json`）；执行＝`spec.make` 实际渲染的
    spec 清单（与 `flex_specs.json` 同源，随 `built["specs"]` 进自检）。
    声明未执行、执行未声明都红。比对键＝kind+disc——两边都是图表声明、
    同一套词表（①的那种 kind 错位在这里不存在）。
    """
    declared = _declared_chart_keys(plan)
    executed = list(dict.fromkeys(
        f"{s.get('kind')}|{s.get('disc') or ''}"
        for s in built.get("specs") or [] if isinstance(s, dict)))
    dset, eset = set(declared), set(executed)
    misses = ([f"声明图未执行：{_chart_tag(x)}"
               for x in declared if x not in eset]
              + [f"执行了未声明的图：{_chart_tag(x)}"
                 for x in executed if x not in dset])
    return {"pass": not misses, "misses": misses}


def _emitted_chart_key(ch: dict) -> str:
    """一条已产出图（账本 payload 或 spec.make 结果）→ `kind|disc` 键。"""
    kind = ch.get("chart_kind") or ch.get("kind")
    if kind == "chart":                     # 账本 payload 的占位 kind，不是图型
        kind = ""
    disc = None
    if isinstance(ch.get("spec"), dict):
        disc = ch["spec"].get("disc")
    if disc is None:
        for s in ch.get("sources") or []:
            if isinstance(s, dict) and s.get("discipline"):
                disc = s["discipline"]
                break
    return f"{kind or ''}|{disc or ''}"


def _anchor_outline(plan: dict, built: dict) -> dict:
    """③ outline_match（charts / declared==emitted）：声明 ↔ 产出图表清单，双向。

    声明＝计划 `charts`；产出＝账本登记的图表文件清单（`built["charts"]`，
    与 flex_meta.json 的 charts 同源）。声明未产出、多产出未声明都红。

    🔴 2026-10-27 裁定：**撤掉 sections 维度**，收敛到图表清单。理由：计划里
    没有 sections 键——`_PLAN_KEYS` 键面冻结、模型面不扩，原型证明按 sections
    比对无从比对、恒绿（空转）；`checks` 词表 {kind,target,expect} 仍在 spec
    冻结形状内（target=charts），不引入新键。
    """
    declared = _declared_chart_keys(plan)
    emitted = list(dict.fromkeys(
        _emitted_chart_key(ch) for ch in built.get("charts") or [] if isinstance(ch, dict)))
    dset, eset = set(declared), set(emitted)
    misses = ([f"声明图未产出：{_chart_tag(x)}"
               for x in declared if x not in eset]
              + [f"多产出未声明的图：{_chart_tag(x)}"
                 for x in emitted if x not in dset])
    return {"pass": not misses, "misses": misses}


def _anchor_checks(plan: dict, built: dict) -> list[dict]:
    """执行计划里**声明过的**校验点（`plan["checks"]`，规则生成），逐条机械判定。

    校验点只由规则产出（`planner.checks_for`），这里只认 kind 分派；
    判定全部是规则比对，不经任何模型。
    """
    out = []
    for chk in plan.get("checks") or []:
        chk = chk if isinstance(chk, dict) else {}
        kind = chk.get("kind")
        if kind == "source_trace":
            res = _anchor_source_trace(plan, built)
        elif kind == "spec_query_match":
            res = _anchor_spec_query(plan, built)
        elif kind == "outline_match":
            res = _anchor_outline(plan, built)
        else:
            # 冒出未实现的 kind＝规则与实现脱节——fail-closed 宁红不放过
            # （不做「0/0 全对」）。
            res = {"pass": False, "misses": [f"未实现的校验点：{kind}"]}
        out.append({"kind": kind, "target": chk.get("target"),
                    "pass": bool(res["pass"]), "misses": res["misses"][:5]})
    return out


def self_check(report_md: str, src: DataSource, built: dict) -> dict:
    """三条自检 + 账本自查 + 计划校验点。任一项不过 → `pass` 为 False（报告里会明确写出来）。

    🔴 `has_charts` 这条是真实模型跑出来的：qwen2.5:3b 选了 `overview_1permille`+
    `cnci`，旧代码只认 3 个硬编码图型 → **0 张图**，而当时自检照样判"通过"
    （`0/0 全对`的老毛病）。没有图的分析稿不能算"完整"。

    🔴 2026-10-14 语义反转（票 03）：判断措辞不再"出现即失败"——传入的**期望是
    补标后的成稿**；`judgement_marked=False`（仍有未标记的判断句）才判不过。
    `backstop_n`＝兜底补标句数（从 built 读，透明计数、不判失败）。

    🔴 2026-10-21（证据账）：`trace` / `peer` / `has_charts` 不再各扫一遍
    `built["sources"]`——统一由 `provenance.Ledger.check` 出自同一本账；正文里
    有登记不到的数字、声明的图没进账、条目缺来源，都判不过。

    🔴 2026-10-27（票 02，校验执行声明）：计划里**声明过的校验点被真的执行**——
    三锚点（来源链双向 / 图声明↔执行 / 声明↔产出图表清单）逐条机械判定，
    明细进 `check["anchors"]`（每条 {kind, target, pass, misses}），随 check
    一起落 `flex_meta.json`；`pass`＝既有各项 AND 三锚点全过。计划经
    `built["plan"]` 进来自检（`_build` 挂入），签名不变；旧调用方的 built
    没有 plan 时无锚点可执行，语义与升级前一致（只加不改）。
    """
    leaks = op.judgement_leaks(report_md)
    backstop_n = int(built.get("backstop_n") or 0)
    ledger = pv.ledger_of(built)
    if ledger.view is None and src is not None:
        # 手工拼的旧 built 若带了真查数面，就按产线口径严判（不再走宽松适配器）。
        ledger.view, ledger.strict = src, True
    evidence = ledger.check(
        blocks=built.get("blocks") or [],
        periods=list(getattr(src, "periods", []) or []),
        declared_charts=built.get("charts") or [],
        selected=built.get("selected") or {})
    anchors = _anchor_checks(built.get("plan") or {}, built)
    return {
        "judgement_marked": not leaks,
        "judgement_leaks": leaks[:3],
        "backstop_n": backstop_n,
        **evidence,
        "anchors": anchors,
        "pass": ((not leaks) and evidence["evidence_ok"]
                 and all(a["pass"] for a in anchors)),
    }


# ------------------------------------------------------------------ 写作模式与汇总
def _resolve_write_mode(polish, write: bool) -> str:
    """`mode ∈ {"off","polish","write"}`。

    - **写作位配好即默认启用**（2026-10-14 票 04）：`WENHENG_FLEX_WRITE` 开且配了云
      → write（描述节写深 + 判断节创写）——按钮/参数不再是门槛；`write` 参数保留兼容。
    - **显式关闭路径**：`polish=False`（CLI/调用方）→ off。
    - 旧润色位保留为回退路径：写作位不可用但 `WENHENG_FLEX_POLISH` 开且配云 → polish。
    - 写作位不可用（未配云、demo 档）→ off：全篇规则稿＋空位，行为与升级前一致。
    """
    if polish is False:
        return "off"
    # 两个位的可用性判据统一在 `ai._writing`（开关 × 模型可达，一处判一次）。
    try:
        from ai import _writing                                     # noqa: PLC0415
        if _writing.writing_state("write").available:
            return "write"
    except Exception:                                                # noqa: BLE001
        pass
    try:
        from ai import _writing                                     # noqa: PLC0415
        if (polish is True or polish is None) and _writing.writing_state("polish").available:
            return "polish"
    except Exception:                                                # noqa: BLE001
        pass
    return "off"


def _write_summary(log: list, mode: str) -> dict | None:
    if mode != "write" or not log:
        return None
    fallbacks = [x for x in log if x.get("fallback")]
    return {"segments": len(log),
            "rewritten": sum(1 for x in log if x.get("changed")),
            "fallbacks": len(fallbacks),
            "reasons": sorted({str(x["fallback"]) for x in fallbacks}),
            "backstop": sum(int(x.get("backstop") or 0) for x in log)}


# ------------------------------------------------------------------ 主流程
def _generate(out_dir, intent: str = "single_trend", *, disc=None, metric=None,
              n_periods=None, polish=None, plan=None, write=False, on_event=None,
              peers=None) -> dict:
    """产出灵活报告（含逐节回调）。`on_event(kind, payload)` 用于流式包装。"""
    t0 = time.time()
    src = DataSource(out_dir)
    if plan is None:
        plan = planner.build(src, intent, disc=disc, metric=metric,
                             n_periods=n_periods, peers=peers)
    mode = _resolve_write_mode(polish, write)
    d = _dir_for(out_dir, intent)
    chart_dir = d / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # 写作位重出：给当前这份规则稿留底（首次才有，之后不覆盖）
    if mode == "write":
        rp, rr = d / "report.md", d / "report.rule.md"
        if rp.is_file() and not rr.is_file():
            shutil.copyfile(rp, rr)

    def _sec(title, body):
        if on_event:
            on_event("section", {"title": title, "body": body})

    def _outline(titles):
        if on_event:
            on_event("plan", {"intent": intent, "title": plan.get("title"),
                              "backend": plan.get("backend"),
                              "fallback_reason": plan.get("fallback_reason"),
                              "disc": plan.get("disc") or "", "mode": mode,
                              "outline": titles,
                              # 轨迹独白的数据（展示层只读，不现算）：
                              # 挑学科＝候选前三（规划那刻记）；配图＝图型与理由
                              "considered": plan.get("considered") or [],
                              "charts": [{"kind": c.get("kind"), "why": c.get("why")}
                                         for c in plan.get("charts") or []]})

    period_name = pathlib.Path(out_dir).name
    specs_out: list[dict] = []
    ctx = _ReportCtx(src=src, plan=plan, chart_dir=chart_dir, specs_out=specs_out,
                     mode=mode, period_name=period_name, ledger=pv.Ledger(src))
    built = _build(ctx, _sec, _outline)

    meta = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "intent": intent, "backend": plan["backend"], "mode": mode,
            "write": _write_summary(built.get("write_log") or [], mode)}
    md = _render(plan, built, meta)
    check = self_check(md, src, built)

    (d / "report.md").write_text(md, encoding="utf-8")
    # 独立可打开的 HTML（可导出、可离线看；不依赖任何 CDN）
    from . import mdview
    (d / "report.html").write_text(
        mdview.standalone(md, plan.get("title") or "灵活分析稿", base_dir=d),
        encoding="utf-8")
    # DOCX（2026-10-15 rick：下载报告给 docx、方便馆员修改；页脚标注一次）
    try:
        from . import docxview
        (d / "report.docx").write_bytes(docxview.build(md, base_dir=d))
    except Exception:                                              # noqa: BLE001
        pass                    # docx 失败不挡出稿；下载口有现场转换兜底（旧稿同理）
    (d / "flex_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "flex_specs.json").write_text(
        json.dumps([s["spec"] for s in specs_out], ensure_ascii=False, indent=1),
        encoding="utf-8")
    (d / "flex_sources.json").write_text(
        json.dumps(built["sources"], ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    (d / "flex_meta.json").write_text(
        json.dumps({**meta, "check": check,
                    "selected": built["selected"],
                    "n_charts": len(built["charts"]),
                    "charts": [pathlib.Path(s["path"]).name for s in built["charts"]],
                    "banner": BANNER},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    result = {"report": str(d / "report.md"), "dir": str(d), "plan": plan,
              "check": check, "n_charts": len(built["charts"]),
              "selected": built["selected"], "mode": mode,
              "elapsed": round(time.time() - t0, 1),
              "write": meta["write"]}
    if on_event:
        counts = pv.ledger_of(built).counts()
        on_event("done", {"elapsed": result["elapsed"], "n_charts": result["n_charts"],
                          "backend": plan["backend"], "mode": mode,
                          "title": plan.get("title"),
                          "check_pass": bool(check.get("pass")),
                          # 票 05：校验没过要「明说哪条没过」——自检明细随 done 走
                          # （展示层据此出人话；不把整份 check（含 misses 明细）塞进事件）。
                          # 票 03（2026-10-14）：字段面翻转——judgement_marked /
                          # judgement_leaks / backstop_n；旧两项（no_professional_judgement、
                          # hypotheses_complete）退役。
                          "check": {
                              "judgement_marked": bool(check.get("judgement_marked")),
                              "judgement_leaks": [str(x) for x in
                                                  (check.get("judgement_leaks") or [])][:3],
                              "backstop_n": int(check.get("backstop_n") or 0),
                              "trace_ok": bool(check.get("trace_ok")),
                              "trace_bad": int((check.get("trace") or {}).get("bad") or 0),
                              "has_charts": bool(check.get("has_charts")),
                          },
                          "n_sources": counts["query"] + counts["peer"],
                          "n_sections": len(built["blocks"]),
                          "write": meta["write"]})
    return result


def generate(out_dir, intent: str = "single_trend", *,
             disc=None, metric=None, n_periods=None, polish=None,
             plan=None, write=False, peers=None) -> dict:
    """产出灵活报告。返回产物路径与自检结果。

    🔴 `out_dir` 是**期次目录**（`out/202607`）。产物一律落在
    `out/<期次>/flexible/<intent>/` 下，**不触碰**该期次的复刻报告产物。

    `polish`：语言润色位（**可选**，见 `flexible/polish.py`，D6 收编为 AI 层内部模式）。
      - `None`（默认）＝按环境开关（`WENHENG_FLEX_WRITE` 优先，其次 `WENHENG_FLEX_POLISH`）；
      - `False` ＝显式关闭（全篇规则稿＋空位，不碰模型）。
    `plan`：复用已有规划（「AI 润色」重出稿时用——同大纲、同数字，只重写叙述段）。
    `write`：保留兼容参数（旧按钮/CLI 的显式触发）——2026-10-14 票 04 起，
      写作位配好即默认启用，传入与否不再改变行为。
    """
    return _generate(out_dir, intent, disc=disc, metric=metric, n_periods=n_periods,
                     polish=polish, plan=plan, write=write, peers=peers)


class _StopGeneration(Exception):
    """内部信号：should_stop 为真时从事件回调里抛出，让生成就地收手。"""


def generate_stream(out_dir, intent: str = "single_trend", *, disc=None,
                    metric=None, plan=None, write=False, should_stop=None,
                    peers=None):
    """流式产出（NDJSON 事件）：`status → plan → section×N → done`（或 `error`/`stopped`）。

    事件在**真实的节点**发出（规划完成 / 每节完成），不做假进度；
    生成在后台线程跑，本生成器只负责把事件转出来（FastAPI 同步生成器逐块发）。

    `should_stop`：可选回调（停止键喊停）——每次事件前询问，为真即收手，
    终态事件 `stopped`；**产物在收尾才写盘**，停在中途就什么都没落（图的半成品除外）。
    """
    import queue
    import threading

    yield {"event": "status", "stage": "planning"}
    q: queue.Queue = queue.Queue()

    def ev(kind, payload):
        if should_stop is not None and should_stop():
            raise _StopGeneration()
        q.put((kind, payload))

    def worker():
        try:
            _generate(out_dir, intent, disc=disc, metric=metric, plan=plan,
                      write=write, on_event=ev, peers=peers)
        except _StopGeneration:
            q.put(("stopped", {}))
        except Exception as e:                                       # noqa: BLE001
            q.put(("error", {"message": f"{type(e).__name__}：{str(e)[:160]}"}))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        kind, payload = q.get()
        yield {"event": kind, **payload}
        if kind in ("done", "error", "stopped"):
            return


def list_reports(out_dir) -> list[dict]:
    """列出某期次已生成的灵活报告（供前端/演示站展示）。"""
    base = pathlib.Path(out_dir) / "flexible"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        md, mj = d / "report.md", d / "flex_meta.json"
        if not md.is_file():
            continue
        m = {}
        if mj.is_file():
            try:
                m = json.loads(mj.read_text(encoding="utf-8"))
            except Exception:                                        # noqa: BLE001
                m = {}
        out.append({"intent": d.name, "path": str(md), "dir": str(d),
                    "meta": m, "title": planner.INTENTS.get(d.name, d.name),
                    "has_rule": (d / "report.rule.md").is_file(),
                    "mtime": md.stat().st_mtime})
    return out


# ------------------------------------------------------------------ 命令行
def main(argv=None):
    """CLI：`python src/flexible/report.py [期次目录] [意图] [学科] [write]`。

    例：
        python src/flexible/report.py out/202607 single_trend
        python src/flexible/report.py out/202607 single_trend 化学 --peers 昆明理工大学
    （规划后端不再是参数：默认规则；配了云 `WENHENG_AI_*` 时自动问模型、失败回退。）
    """
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    out_dir = argv[0] if argv else "out/202607"
    intent = argv[1] if len(argv) > 1 else "single_trend"
    disc = argv[2] if len(argv) > 2 else None
    write = len(argv) > 3 and argv[3] == "write"
    r = generate(out_dir, intent, disc=disc, write=write)
    print(f"[灵活报告] {planner.INTENTS.get(intent, intent)} → {r['report']}")
    print(f"  规划后端：{r['plan']['backend']}"
          + (f"（{r['plan']['fallback_reason']}）" if r["plan"].get("fallback_reason") else "")
          + f"　｜　写作模式：{r['mode']}")
    print(f"  产出图 {r['n_charts']} 张；自检 {'通过 ✅' if r['check']['pass'] else '未通过 ❌'}")
    t = r["check"]["trace"]
    print(f"  数字可回溯：{t['ok']}/{t['checked']}"
          + (f"（异常 {t['bad']}）" if t["bad"] else ""))
    return 0 if r["check"]["pass"] else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    sys.exit(main())
