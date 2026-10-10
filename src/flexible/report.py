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

**写作位（可选，默认关）**：`WENHENG_FLEX_WRITE` 开且配云时，叙述段交给
`ai._writer`（规则稿 + 该段事实摘要 → 分析体叙述）；数字/图表/来源链一律不变，
任何校验不过整段回退规则稿。见 `.scratch/wayfinder/llm-api-jieru/dev/任务-灵活报告写作位（交接）.md`。

**逐节回调与流式**：`_generate(..., on_event=…)` 在「规划完成」「每节完成」时回调；
`generate_stream()` 是同一个核的流式包装（真实事件，不做假进度）。

🔴 三条自检在 `self_check()` 里，产出后立即跑，结果随报告一起落盘：

1. 正文里没有【手工：…】**之外**的专业判断措辞（`opinion.guard`）
2. 每个数字都能回读（`queries.trace_check`）
3. 每条待验证假设都带「来源 + 可验证方式」
"""
from __future__ import annotations

import json
import pathlib
import shutil
import time
from dataclasses import dataclass, field

from . import opinion as op
from . import planner, queries as q, spec as sp
from .datasource import DataSource, cn_name, period_label

BANNER = "内部参考 · 非报送件"
"""导出件页脚/页眉标注。从源头杜绝「分析稿被误当正式报告发出去」。"""

BANNER_NOTE = ("> **本件为内部参考，非报送件** —— 由灵活报告产线（第二条产线）生成，"
               "路径由 AI 自主规划；**不带盖章位、不作为对外报送材料**。"
               "正式对外件请用复刻报告产线（母版 704 槽位、三道闸、可签发）。")

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
    """一次灵活报告构建的共享上下文：来源/图/假设/留痕都在这几个桶里。

    「有哪些节」由 `_single_sections / _cross_sections` 返回的
    `[(标题, 构建函数)]` 决定；**大纲就是这份表的标题**——标题与正文合成
    一处编排，改节名不会再漏改大纲。
    """

    src: DataSource
    plan: dict
    chart_dir: pathlib.Path
    specs_out: list
    mode: str
    period_name: str
    blocks: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    charts: list = field(default_factory=list)
    hyps: list = field(default_factory=list)
    log: list = field(default_factory=list)
    selected: dict = field(default_factory=dict)
    metric_cn: str = ""
    cmp_rows: list = field(default_factory=list)

    def P(self, text, label, facts=()):
        return _polish(self.mode, text, label, facts=facts,
                       period=self.period_name, log=self.log)


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
def _snapshot(src: DataSource, disc: str, sources: list) -> tuple[list, float | None]:
    """当期核心指标快照（概况/落点两处共用）。返回 (kv 行, 距阈值差)。"""
    period = src.current_period()
    rows = []
    for met in ("proximity_1pct", "rank", "total_cites", "threshold_1pct", "top_papers"):
        r = q.series(src, met, disc, [period])
        sources.append(r)
        if r["points"]:
            p = r["points"][0]
            rows.append((r["metric_cn"], p["value"], p["source"]))
    tc = q.series(src, "total_cites", disc, [period])
    th = q.series(src, "threshold_1pct", disc, [period])
    sources.extend([tc, th])
    gap = (tc["points"][0]["value"] - th["points"][0]["value"]
           if tc["points"] and th["points"] else None)
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


def _rank_facts(cmp_prox: dict, cmp_papers: dict, disc: str) -> list[str]:
    facts = []
    for c in (cmp_prox, cmp_papers):
        pos = next((i for i, x in enumerate(c["rows"], 1) if x["discipline"] == disc), None)
        if pos:
            facts.append(f"{c['metric_cn']}位次：第 {pos} 位（共 {c['n']}）")
    return facts


def _render_charts(src: DataSource, plan: dict, chart_dir, specs_out, charts,
                   default_disc=None, only_scope=None) -> str:
    """按规划**逐张**出图，返回 markdown 片段。

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
        charts.append(s)
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


def _single_sections(c: _ReportCtx) -> list:
    """单学科诊断的节表（顺序即大纲）。"""
    disc, dcn = c.plan["disc"], cn_name(c.plan["disc"])
    period = c.src.current_period()
    prev = c.src.periods[c.src.periods.index(period) - 1]
    win = c.plan["periods"]
    c.selected = {"disc": disc, "disc_cn": dcn, "period": period, "prev": prev}

    def sec_overview() -> str:
        # 一、当期概况（每个数都走查询，带链）
        rows, gap = _snapshot(c.src, disc, c.sources)
        # 🔴 引导句走 `gap_lead`（原来三支一律「…的核心指标如下」，模板腔）
        lead = c.P(op.gap_lead(period_label(period), dcn, gap),
                   "flexible/single_trend/概况", _snapshot_facts(rows, gap))
        return lead + "\n\n" + _kv_table(rows)

    def sec_trend() -> str:
        # 二、关键指标走势（描述性，规则生成；配 spec 图）
        trend_rows = []
        for met in ("proximity_1pct", "total_cites", "papers"):
            r = q.series(c.src, met, disc, win)
            c.sources.append(r)
            if r["points"]:
                trend_rows.append(r)
        # 🔴 第一条带区间、后面两条换开头 —— 三条不能再是同一句式（rick 2026-09-21）
        desc = "\n\n".join(
            "- " + c.P(op.descriptive_trend(
                r["points"], r["metric_cn"], dcn, r.get("better", "up"),
                with_span=(i == 0)), "flexible/single_trend/趋势", _series_facts(r))
            for i, r in enumerate(trend_rows))
        return desc + _render_charts(c.src, c.plan, c.chart_dir, c.specs_out,
                                     c.charts, disc)

    def sec_rank() -> str:
        # 三、相对位次（跨学科横截面）
        cmp_prox = q.compare(c.src, "proximity_1pct", None, period)
        c.sources.append(cmp_prox)
        rank_pos = next((i for i, x in enumerate(cmp_prox["rows"], 1)
                         if x["discipline"] == disc), None)
        cmp_papers = q.compare(c.src, "papers", None, period)
        c.sources.append(cmp_papers)
        paper_pos = next((i for i, x in enumerate(cmp_papers["rows"], 1)
                          if x["discipline"] == disc), None)
        return c.P(op.rank_sentence(cmp_prox["n"], rank_pos, paper_pos, dcn),
                   "flexible/single_trend/相对位次", _rank_facts(cmp_prox, cmp_papers, disc))

    def sec_hyp() -> str:
        # 四、待验证假设（规则提出的也算假设，须标注来源）
        hyps = c.hyps
        pr = q.series(c.src, "proximity_1pct", disc, win)
        pp = q.series(c.src, "papers", disc, win)
        if pr["points"] and pp["points"] and len(pr["points"]) >= 2:
            pc = pr.get("change_pct") or 0
            paper_chg = pp["points"][-1]["value"] - pp["points"][0]["value"]
            if pc > 0 and paper_chg > 0:
                hyps.append(op.hypothesis(
                    f"{dcn}接近度的上升可能与同期发文量增加同向（本期发文量净增 "
                    f"{_fmt(paper_chg)} 篇）。",
                    f"核对台账《论文数》与《接近度》两表在 {win[0]}–{win[-1]} 的各期值，"
                    f"看两者是否同向；再查《TOP论文》看高质量产出是否同步。",
                    op.SRC_RULE))
            elif pc < 0 and paper_chg > 0:
                hyps.append(op.hypothesis(
                    f"{dcn}发文量增加但接近度下降，可能与新增论文尚处引用积累期有关。",
                    f"对比台账《论文数》增量与《总被引》增量在 {win[0]}–{win[-1]} 的错位期数；"
                    f"并可复核《CNCI》看篇均影响力是否同步变化。",
                    op.SRC_RULE))
        an = q.anomaly(c.src, period)
        c.sources.append(an)
        mine = [x for x in an["items"] if x["discipline"] == disc]
        for x in mine:
            hyps.append(op.hypothesis(
                f"{dcn}的{x['metric_cn']}在本期出现 {x['ratio']} 倍环比变动，"
                f"可能存在录入或口径调整。",
                f"回读台账《{x['source']['origin_sheet']}》{x['discipline_cn']} 行 "
                f"{x['prev']} 与 {x['period']} 两列，并与上期报告核对。", op.SRC_RULE))
        if not hyps:
            hyps.append(op.hypothesis(
                f"{dcn}在本期未出现显著异动，其接近度变化的主因未在规则层显现。",
                f"可扩展核对 {win[0]}–{win[-1]} 的《总被引》《论文数》《TOP论文》三表联合走势。",
                op.SRC_RULE))
        return ("\n".join(op.render_hypothesis(h) for h in hyps)
                + "\n\n> 上述均为**待验证假设**，不是结论。灵活报告不产出学科结论。")

    def sec_manual() -> str:
        # 五、需人工判断（专业判断一律不生成）
        return ("\n".join([
            f"- {op.manual(f'{dcn}发展力度评价')}",
            f"- {op.manual(f'{dcn}资源投入建议')}",
            "- " + op.manual("是否需要向学院核实数据口径"),
        ])
            + "\n\n> 专业判断（要不要加投入、值不值得重点建设）**不由本产线生成** —— "
              "与复刻报告同一机制，留空位由馆员填写。")

    return [("当期概况", sec_overview), ("关键指标走势", sec_trend),
            ("相对位次", sec_rank),
            ("待验证假设（规则提出，非结论）", sec_hyp),
            ("需人工判断（本产线不生成专业判断）", sec_manual)]


# ------------------------------------------------------------------ 横向对比
def _cross_sections(c: _ReportCtx) -> list:
    """横向对比的节表（顺序即大纲；指定学科/指标决定动态节）。"""
    src, plan = c.src, c.plan
    period = src.current_period()
    met = plan.get("metric") or "proximity_1pct"
    disc = plan.get("disc")
    dcn = cn_name(disc) if disc else ""
    win = plan.get("periods") or src.filled_periods[-7:]
    c.selected = {"metric": met}

    def sec_overview() -> str:
        # 一、本期概览
        sc = q.scope(src, period)
        c.sources.append(sc)
        c.selected.update({"period": period, "prev": sc["prev"]})
        n_ent = sc["n_entered_1pct"]
        cmp_n = len(src.disciplines)      # 🔴 别写死 22（学科数会变）
        lead = (f"{period_label(period)}，云南大学共 **{n_ent}** 个学科进入 ESI 全球前 1%"
                f"（占 {cmp_n} 个监测学科的 {n_ent / cmp_n * 100:.0f}%）；"
                f"另有 **{sc['n_potential']}** 个学科尚未进入、列为潜力学科。")
        return c.P(lead, "flexible/cross_compare/概览",
                   [f"进入前1%学科数：{n_ent}", f"监测学科数：{cmp_n}",
                    f"潜力学科数：{sc['n_potential']}"])

    def sec_anchor() -> str:
        # 指定学科锚定 · 落点（rick 2026-09-29：指定了学科就得围着它写）
        rows, gap = _snapshot(src, disc, c.sources)
        cmp_prox = q.compare(src, "proximity_1pct", None, period)
        c.sources.append(cmp_prox)
        pos1 = next((k for k, x in enumerate(cmp_prox["rows"], 1)
                     if x["discipline"] == disc), None)
        cmp_papers = q.compare(src, "papers", None, period)
        c.sources.append(cmp_papers)
        pos2 = next((k for k, x in enumerate(cmp_papers["rows"], 1)
                     if x["discipline"] == disc), None)
        lead2 = c.P(op.gap_lead(period_label(period), dcn, gap),
                    "flexible/cross_compare/落点", _snapshot_facts(rows, gap))
        return (lead2 + "\n\n" + _kv_table(rows) + "\n\n"
                + op.rank_sentence(cmp_prox["n"], pos1, pos2, dcn))

    def sec_trend() -> str:
        lines = []
        for j, met2 in enumerate(("proximity_1pct", "total_cites", "papers")):
            r = q.series(src, met2, disc, win)
            c.sources.append(r)
            if not r["points"]:
                continue
            lines.append("- " + c.P(op.descriptive_trend(
                r["points"], r["metric_cn"], dcn, r.get("better", "up"),
                with_span=(j == 0)), "flexible/cross_compare/走势", _series_facts(r)))
        return "\n\n".join(lines) + _render_charts(
            src, plan, c.chart_dir, c.specs_out, c.charts, disc, only_scope="single")

    def sec_compare() -> str:
        # 横向对比（全池表 + 总览图）
        cmp_r = q.compare(src, met, None, period)
        c.sources.append(cmp_r)
        c.metric_cn = cmp_r["metric_cn"]
        c.cmp_rows = cmp_r["rows"]
        tail = cmp_r["rows"][-3:]
        body = (f"本期 {cmp_r['n']} 个学科的{cmp_r['metric_cn']}排序如下"
                f"（{'由低到高' if cmp_r['better'] == 'down' else '由高到低'}，好在前）。\n\n"
                + "| 位次 | 学科 | 数值 | 来源 |\n|---:|---|---:|---|\n"
                + "\n".join(f"| {k} | {'**' if x['discipline'] == disc else ''}"
                            f"{x['discipline_cn']}{'**' if x['discipline'] == disc else ''} | "
                            f"{_fmt(x['value'])} | `{x['source']['origin_sheet']}` |"
                            for k, x in enumerate(cmp_r["rows"][:8], 1))
                + f"\n\n（末 3 位：{'、'.join(x['discipline_cn'] for x in tail)}）")
        return body + _render_charts(src, plan, c.chart_dir, c.specs_out, c.charts, disc,
                                     only_scope=("overview" if disc else None))

    def sec_tier() -> str:
        # 梯队划分（规则）
        rows = c.cmp_rows
        entered = [x for x in rows if float(x["value"]) >= 1.0]
        near = [x for x in rows if 0.5 <= float(x["value"]) < 1.0]
        far = [x for x in rows if float(x["value"]) < 0.5]
        extra = ""
        if disc:
            tier = "已进入前 1% 一档" if any(x["discipline"] == disc for x in entered) else (
                "接近但未进入一档" if any(x["discipline"] == disc for x in near)
                else "距离较远一档")
            extra = f"\n- **{dcn}** 位于「{tier}」。"
        return (f"- **已进入前 1%**（接近度 ≥ 100%）：{len(entered)} 个 —— "
                f"{'、'.join(x['discipline_cn'] for x in entered) or '无'}\n"
                f"- **接近但未进入**（50%–100%）：{len(near)} 个 —— "
                f"{'、'.join(x['discipline_cn'] for x in near) or '无'}\n"
                f"- **距离较远**（<50%）：{len(far)} 个" + extra
                + "\n\n> 梯队边界为**规则阈值**（100% / 50%），仅用于分档排序，不构成学科评价。")

    def sec_hyp() -> str:
        # 待验证假设（锚定稿优先该学科）
        an = q.anomaly(src, period)
        c.sources.append(an)
        pool = [x for x in an["items"] if x["discipline"] == disc] if disc else an["items"]
        hyps = c.hyps
        for x in (pool or an["items"])[:3]:
            hyps.append(op.hypothesis(
                f"{x['discipline_cn']}的{x['metric_cn']}本期为 {x['ratio']} 倍环比变动，"
                f"其动因可能与口径或录入有关。",
                f"回读台账《{x['source']['origin_sheet']}》{x['discipline_cn']} 行 "
                f"{x['prev']}/{x['period']} 两列并与上期报告对照。", op.SRC_RULE))
        if disc and not [x for x in an["items"] if x["discipline"] == disc]:
            hyps.insert(0, op.hypothesis(
                f"{dcn}在本期未出现规则层可识别的显著异动，其接近度变化的主因未在规则层显现。",
                f"可扩展核对 {win[0]}–{win[-1]} 的《总被引》《论文数》《TOP论文》三表联合走势。",
                op.SRC_RULE))
        if not hyps:
            hyps.append(op.hypothesis(
                "本期各学科指标未见规则层可识别的显著异动。",
                f"可放宽异常阈值后复查 {period} 与前期的环比分布。", op.SRC_RULE))
        return ("\n".join(op.render_hypothesis(h) for h in hyps)
                + "\n\n> 上述均为**待验证假设**，不是结论。")

    def sec_manual() -> str:
        return ("\n".join(["- " + op.manual("重点建设学科建议"),
                           "- " + op.manual("潜力学科培育优先级"),
                           "- " + op.manual("向学院核实的口径问题")])
                + "\n\n> 专业判断不由本产线生成，留空位由馆员填写。")

    sections = [("本期概览", sec_overview)]
    if disc:
        sections += [(f"{dcn} · 当期落点", sec_anchor), (f"{dcn} · 近 7 期走势", sec_trend)]
    sections.append(("横向对比", sec_compare))
    if met == "proximity_1pct":
        sections.append(("梯队分布", sec_tier))
    sections += [("待验证假设（规则提出，非结论）", sec_hyp),
                 ("需人工判断（本产线不生成专业判断）", sec_manual)]
    return sections


def _build(c: _ReportCtx, on_section=None, on_outline=None) -> dict:
    """按 intent 取节表 → 逐节构建 → 返回既有形状的 built dict。"""
    sections = (_single_sections(c) if c.plan["intent"] == "single_trend"
                else _cross_sections(c))
    c.blocks = _collect(sections, on_section, on_outline)
    selected = dict(c.selected)
    if c.plan["intent"] != "single_trend":
        selected["metric_cn"] = c.metric_cn
    return {"blocks": c.blocks, "sources": c.sources, "charts": c.charts,
            "hyps": c.hyps, "write_log": c.log, "selected": selected}


# ------------------------------------------------------------------ 渲染
def _render(plan: dict, built: dict, meta: dict) -> str:
    L = [f"# {plan.get('title') or '灵活分析稿'}", "",
         BANNER_NOTE, "",
         f"> 期次：**{period_label(built['selected']['period'])}**"
         + (f"（上期 {period_label(built['selected']['prev'])}）"
            if built['selected'].get('prev') else ""),
         f"> 意图：{planner.INTENTS[plan['intent']]}"
         f"　｜　规划后端：**{plan['backend']}**"
         + (f"（{plan['fallback_reason']}）" if plan.get("fallback_reason") else ""),
         f"> 生成时间：{meta['generated_at']}", ""]
    if plan.get("fallback_reason"):
        L.insert(4, f"> ⚠ 规划回退：{plan['fallback_reason']}")
    L += ["---", ""]
    for title, body in built["blocks"]:
        L += [f"## {title}", "", body, ""]
    L += ["---", "## 本稿如何产生（可验证的架构主张）", "",
          "本件里的**每一个数字**都只经过这一条路径：",
          "",
          "1. 规划器只决定「写哪个学科、配哪些图」——它的输出里**没有数字这个物种**；",
          "2. 数值由查询工具从 `ledger_long.parquet` 取出，逐点附**来源链**；",
          "3. 图上每个点由引擎按 JSON spec 渲染，**模型不接触坐标**；",
          "4. 模型如给出图表声明，只允许 `invert` / `include` / `zero_base` 这类**语义**参数，"
          "轴范围永远由数据决定（代码里没有「纵轴上下界」这个字段）。",
          "",
          f"因此模型在本产线里的输出只有三种：**查询、图表声明、待验证假设**。"
          f"（设计口径见 `评审文档/19` §2.2）", ""]
    # 来源链附录
    L += ["---", "## 附：数据来源链", "",
          "| # | 查询 | 指标 | 学科 | 期次 | 台账工作表 |", "|---:|---|---|---|---|---|"]
    n = 0
    for r in built["sources"]:
        if not isinstance(r, dict) or "kind" not in r:
            continue
        n += 1
        first = (r.get("points") or r.get("rows") or r.get("items") or [{}])[0]
        ch = first.get("source") or {}
        L.append(f"| {n} | {r['kind']} | {ch.get('metric_cn') or r.get('metric_cn') or '—'} | "
                 f"{ch.get('discipline_cn') or r.get('disc_cn') or '（全学科）'} | "
                 f"{ch.get('period') or r.get('period') or '—'} | "
                 f"{ch.get('origin_sheet') or '（派生）'} |")
    L += ["", f"共 {n} 条查询；每条查询的**每个数据点**都带独立来源链"
              f"（见 `flex_sources.json`，逐点 `{'{'}dataset, metric, discipline, period, "
              f"origin_sheet{'}'}`）。", ""]
    L += ["---", f"*{BANNER}｜灵活报告产线｜不带盖章位*", ""]
    return "\n".join(L)


def self_check(report_md: str, src: DataSource, built: dict) -> dict:
    """四条自检。任一项不过 → 报告里会明确写出来（不隐藏）。

    🔴 `has_charts` 这条是真实模型跑出来的：qwen2.5:3b 选了 `overview_1permille`+
    `cnci`，旧代码只认 3 个硬编码图型 → **0 张图**，而当时自检照样判"通过"
    （`0/0 全对`的老毛病）。没有图的分析稿不能算"完整"。
    """
    bad_words = op.guard(report_md)
    trace = {"checked": 0, "ok": 0, "bad": 0, "misses": []}
    for r in built["sources"]:
        if isinstance(r, dict) and "kind" in r:
            t = q.trace_check(src, r)
            trace["checked"] += t["checked"]
            trace["ok"] += t["ok"]
            trace["bad"] += t["bad"]
            trace["misses"] += t["misses"]
    hyp_ok = all(h.get("text") and h.get("verify") and h.get("source")
                 for h in built["hyps"])
    n_charts = len(built["charts"])
    return {
        "no_professional_judgement": not bad_words,
        "professional_hits": bad_words[:3],
        "trace": trace,
        "trace_ok": trace["bad"] == 0,
        "hypotheses_complete": hyp_ok,
        "has_charts": n_charts >= 1,
        "n_charts": n_charts,
        "pass": (not bad_words) and trace["bad"] == 0 and hyp_ok and n_charts >= 1,
    }


# ------------------------------------------------------------------ 写作模式与汇总
def _resolve_write_mode(polish, write: bool) -> str:
    """`mode ∈ {"off","polish","write"}`。

    - **写作位只显式触发**：`write=True`（界面「AI 润色」按钮 / CLI `--write`）或
      `polish="write"`，且 `WENHENG_FLEX_WRITE` 开、配了云 → write。
      （部署开关只决定「按钮可不可用」；普通生成仍走规则稿——快、确定性、
       免得每次生成都自动改文风。）
    - 旧润色位沿用环境开关：`WENHENG_FLEX_POLISH` 开且配云 → polish；`polish is False` → off。
    """
    if polish is False:
        return "off"
    # 两个位的可用性判据统一在 `ai._writing`（开关 × 模型可达，一处判一次）。
    try:
        from ai import _writing                                     # noqa: PLC0415
        if (bool(write) or polish == "write") and _writing.writing_state("write").available:
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
            "reasons": sorted({str(x["fallback"]) for x in fallbacks})}


# ------------------------------------------------------------------ 主流程
def _generate(out_dir, intent: str = "single_trend", *, disc=None, metric=None,
              n_periods=None, polish=None, plan=None, write=False, on_event=None) -> dict:
    """产出灵活报告（含逐节回调）。`on_event(kind, payload)` 用于流式包装。"""
    t0 = time.time()
    src = DataSource(out_dir)
    if plan is None:
        plan = planner.build(src, intent, disc=disc, metric=metric, n_periods=n_periods)
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
                     mode=mode, period_name=period_name)
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
        mdview.standalone(md, plan.get("title") or "灵活分析稿"), encoding="utf-8")
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
        on_event("done", {"elapsed": result["elapsed"], "n_charts": result["n_charts"],
                          "backend": plan["backend"], "mode": mode,
                          "title": plan.get("title"),
                          "check_pass": bool(check.get("pass")),
                          "n_sources": len(built["sources"]),
                          "n_sections": len(built["blocks"]),
                          "write": meta["write"]})
    return result


def generate(out_dir, intent: str = "single_trend", *,
             disc=None, metric=None, n_periods=None, polish=None,
             plan=None, write=False) -> dict:
    """产出灵活报告。返回产物路径与自检结果。

    🔴 `out_dir` 是**期次目录**（`out/202607`）。产物一律落在
    `out/<期次>/flexible/<intent>/` 下，**不触碰**该期次的复刻报告产物。

    `polish`：语言润色位（**可选**，见 `flexible/polish.py`，D6 收编为 AI 层内部模式）。
      - `None`（默认）＝按环境开关（`WENHENG_FLEX_WRITE` 优先，其次 `WENHENG_FLEX_POLISH`）；
      - `True` / `False` ＝强制开（旧润色）/ 强制关。
    `plan`：复用已有规划（「AI 润色」重出稿时用——同大纲、同数字，只重写叙述段）。
    `write`：显式走写作位（界面「AI 润色」按钮；仍要求 `WENHENG_FLEX_WRITE` 开且配云）。
    """
    return _generate(out_dir, intent, disc=disc, metric=metric, n_periods=n_periods,
                     polish=polish, plan=plan, write=write)


class _StopGeneration(Exception):
    """内部信号：should_stop 为真时从事件回调里抛出，让生成就地收手。"""


def generate_stream(out_dir, intent: str = "single_trend", *, disc=None,
                    metric=None, plan=None, write=False, should_stop=None):
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
                      write=write, on_event=ev)
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
        python src/flexible/report.py out/202607 cross_compare 化学 write
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
