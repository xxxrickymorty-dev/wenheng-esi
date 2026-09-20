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

🔴 三条自检在 `self_check()` 里，产出后立即跑，结果随报告一起落盘：

1. 正文里没有【手工：…】**之外**的专业判断措辞（`opinion.guard`）
2. 每个数字都能回读（`queries.trace_check`）
3. 每条待验证假设都带「来源 + 可验证方式」
"""
from __future__ import annotations

import json
import pathlib
import time

from . import opinion as op
from . import planner, queries as q, spec as sp
from .datasource import DataSource, cn_name, period_label

BANNER = "内部参考 · 非报送件"
"""导出件页脚/页眉标注。从源头杜绝「分析稿被误当正式报告发出去」。"""

BANNER_NOTE = ("> **本件为内部参考，非报送件** —— 由灵活报告产线（第二条产线）生成，"
               "路径由 AI 自主规划；**不带盖章位、不作为对外报送材料**。"
               "正式对外件请用复刻报告产线（母版 704 槽位、三道闸、可签发）。")


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


# ------------------------------------------------------------------ 单学科诊断
def _render_charts(src: DataSource, plan: dict, chart_dir, specs_out, charts,
                   default_disc=None) -> str:
    """按规划**逐张**出图，返回 markdown 片段。

    🔴 这里曾经硬编码只认 3 个图型（cites_threshold / papers_delta / rank_pct）。
    真实模型一旦选了别的（实测 qwen2.5:3b 选了 `overview_1permille` + `cnci`），
    一张图都不出 —— 而正文和自检照常报"通过"。图型清单以 `spec.KINDS` 为准，
    这里不许再列白名单。
    """
    out = []
    for c in plan["charts"]:
        kind = c.get("kind")
        if kind not in sp.KINDS:
            continue
        scope = sp.KINDS[kind]["disc_scope"]
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


def _build_single_trend(src: DataSource, plan: dict, chart_dir, specs_out) -> dict:
    disc = plan["disc"]
    dcn = cn_name(disc)
    period = src.current_period()
    prev = src.periods[src.periods.index(period) - 1]
    win = plan["periods"]

    blocks, sources, charts = [], [], []

    # ── 一、当期概况（每个数都走查询，带链）
    rows, pts = [], []
    for met in ("proximity_1pct", "rank", "total_cites", "threshold_1pct", "top_papers"):
        r = q.series(src, met, disc, [period])
        sources.append(r)
        if r["points"]:
            p = r["points"][0]
            rows.append((r["metric_cn"], p["value"], p["source"]))
            pts.append(p)
    gap = None
    tc = q.series(src, "total_cites", disc, [period])
    th = q.series(src, "threshold_1pct", disc, [period])
    if tc["points"] and th["points"]:
        gap = tc["points"][0]["value"] - th["points"][0]["value"]
    if gap is None:
        lead = f"{period_label(period)}，{dcn}的核心指标如下。"
    elif gap < 0:
        lead = (f"{period_label(period)}，{dcn}的核心指标如下；"
                f"总被引距 1% 阈值还差 **{_fmt(abs(gap))}**。")
    else:
        lead = (f"{period_label(period)}，{dcn}的核心指标如下；"
                f"总被引已超 1% 阈值 **{_fmt(gap)}**。")
    blocks.append(("一、当期概况", lead + "\n\n" + _kv_table(rows)))

    # ── 二、关键指标走势（描述性，规则生成；配 spec 图）
    trend_rows = []
    for met in ("proximity_1pct", "total_cites", "papers"):
        r = q.series(src, met, disc, win)
        sources.append(r)
        if r["points"]:
            trend_rows.append(r)
    desc = "\n\n".join(
        "- " + op.descriptive_trend(r["points"], r["metric_cn"], dcn, r.get("better", "up"))
        for r in trend_rows)
    body = desc + _render_charts(src, plan, chart_dir, specs_out, charts, disc)
    blocks.append(("二、关键指标走势", body))

    # ── 三、相对位次（跨学科横截面）
    cmp_prox = q.compare(src, "proximity_1pct", None, period)
    sources.append(cmp_prox)
    rank_pos = next((i for i, x in enumerate(cmp_prox["rows"], 1)
                     if x["discipline"] == disc), None)
    cmp_papers = q.compare(src, "papers", None, period)
    sources.append(cmp_papers)
    paper_pos = next((i for i, x in enumerate(cmp_papers["rows"], 1)
                      if x["discipline"] == disc), None)
    hard = next((i for i, x in enumerate(cmp_prox["rows"], 1)
                 if disc == x["discipline"]), None)
    txt = (f"在本期 {cmp_prox['n']} 个学科中，{dcn}的{cmp_prox['metric_cn']}"
           f"排第 **{rank_pos}** 位"
           + (f"（共 {cmp_prox['n']} 个学科）" if rank_pos else "")
           + f"；论文数排第 **{paper_pos}** 位。")
    if hard:
        near = cmp_prox["rows"][rank_pos - 1] if rank_pos else None
        _ = near
    blocks.append(("三、相对位次", txt))

    # ── 四、待验证假设（规则提出的也算假设，须标注来源）
    hyps = []
    pr = q.series(src, "proximity_1pct", disc, win)
    pp = q.series(src, "papers", disc, win)
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
    an = q.anomaly(src, period)
    sources.append(an)
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
    blocks.append(("四、待验证假设（规则提出，非结论）",
                   "\n".join(op.render_hypothesis(h) for h in hyps)
                   + "\n\n> 上述均为**待验证假设**，不是结论。灵活报告不产出学科结论。"))

    # ── 五、需人工判断（专业判断一律不生成）
    blocks.append(("五、需人工判断（本产线不生成专业判断）",
                   "\n".join([
                       f"- {op.manual(f'{dcn}发展力度评价')}",
                       f"- {op.manual(f'{dcn}资源投入建议')}",
                       "- " + op.manual("是否需要向学院核实数据口径"),
                   ])
                   + "\n\n> 专业判断（要不要加投入、值不值得重点建设）**不由本产线生成** —— "
                     "与复刻报告同一机制，留空位由馆员填写。"))
    return {"blocks": blocks, "sources": sources, "charts": charts, "hyps": hyps,
            "selected": {"disc": disc, "disc_cn": dcn, "period": period, "prev": prev}}


# ------------------------------------------------------------------ 横向对比
def _build_cross_compare(src: DataSource, plan: dict, chart_dir, specs_out) -> dict:
    period = src.current_period()
    met = plan.get("metric") or "proximity_1pct"
    blocks, sources, charts = [], [], []

    sc = q.scope(src, period)
    sources.append(sc)
    n_ent = sc["n_entered_1pct"]
    blocks.append(("一、本期概览",
                   f"{period_label(period)}，云南大学共 **{n_ent}** 个学科进入 ESI 全球前 1%"
                   f"（占 22 个监测学科的 {n_ent / 22 * 100:.0f}%）；"
                   f"另有 **{sc['n_potential']}** 个学科尚未进入、列为潜力学科。"))

    cmp_r = q.compare(src, met, None, period)
    sources.append(cmp_r)
    top = cmp_r["rows"][:3]
    tail = cmp_r["rows"][-3:]
    body = (f"本期 {cmp_r['n']} 个学科的{cmp_r['metric_cn']}排序如下"
            f"（{'由低到高' if cmp_r['better'] == 'down' else '由高到低'}，好在前）。\n\n"
            + "| 位次 | 学科 | 数值 | 来源 |\n|---:|---|---:|---|\n"
            + "\n".join(f"| {i} | {x['discipline_cn']} | {_fmt(x['value'])} | "
                        f"`{x['source']['origin_sheet']}` |"
                        for i, x in enumerate(cmp_r["rows"][:8], 1))
            + f"\n\n（末 3 位：{'、'.join(x['discipline_cn'] for x in tail)}）")
    body += _render_charts(src, plan, chart_dir, specs_out, charts)
    blocks.append(("二、横向对比", body))

    # 梯队划分（规则）
    rows = cmp_r["rows"]
    if met == "proximity_1pct":
        entered = [x for x in rows if float(x["value"]) >= 1.0]
        near = [x for x in rows if 0.5 <= float(x["value"]) < 1.0]
        far = [x for x in rows if float(x["value"]) < 0.5]
        blocks.append(("三、梯队分布",
                       f"- **已进入前 1%**（接近度 ≥ 100%）：{len(entered)} 个 —— "
                       f"{'、'.join(x['discipline_cn'] for x in entered) or '无'}\n"
                       f"- **接近但未进入**（50%–100%）：{len(near)} 个 —— "
                       f"{'、'.join(x['discipline_cn'] for x in near) or '无'}\n"
                       f"- **距离较远**（<50%）：{len(far)} 个\n\n"
                       f"> 梯队边界为**规则阈值**（100% / 50%），仅用于分档排序，不构成学科评价。"))

    hyps = []
    an = q.anomaly(src, period)
    sources.append(an)
    for x in an["items"][:3]:
        hyps.append(op.hypothesis(
            f"{x['discipline_cn']}的{x['metric_cn']}本期为 {x['ratio']} 倍环比变动，"
            f"其动因可能与口径或录入有关。",
            f"回读台账《{x['source']['origin_sheet']}》{x['discipline_cn']} 行 "
            f"{x['prev']}/{x['period']} 两列并与上期报告对照。", op.SRC_RULE))
    if not hyps:
        hyps.append(op.hypothesis(
            "本期各学科指标未见规则层可识别的显著异动。",
            f"可放宽异常阈值后复查 {period} 与前期的环比分布。", op.SRC_RULE))
    blocks.append(("四、待验证假设（规则提出，非结论）",
                   "\n".join(op.render_hypothesis(h) for h in hyps)
                   + "\n\n> 上述均为**待验证假设**，不是结论。"))
    blocks.append(("五、需人工判断（本产线不生成专业判断）",
                   "\n".join(["- " + op.manual("重点建设学科建议"),
                              "- " + op.manual("潜力学科培育优先级"),
                              "- " + op.manual("向学院核实的口径问题")])
                   + "\n\n> 专业判断不由本产线生成，留空位由馆员填写。"))
    return {"blocks": blocks, "sources": sources, "charts": charts, "hyps": hyps,
            "selected": {"metric": met, "metric_cn": cmp_r["metric_cn"],
                         "period": period, "prev": sc["prev"]}}


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


def generate(out_dir, intent: str = "single_trend", *, backend=None,
             disc=None, metric=None, n_periods=None) -> dict:
    """产出灵活报告。返回产物路径与自检结果。

    🔴 `out_dir` 是**期次目录**（`out/202607`）。产物一律落在
    `out/<期次>/flexible/<intent>/` 下，**不触碰**该期次的复刻报告产物。
    """
    src = DataSource(out_dir)
    plan = planner.build(src, intent, backend=backend, disc=disc, metric=metric,
                         n_periods=n_periods)
    d = _dir_for(out_dir, intent)
    chart_dir = d / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    specs_out: list[dict] = []
    built = (_build_single_trend(src, plan, chart_dir, specs_out)
             if intent == "single_trend" else
             _build_cross_compare(src, plan, chart_dir, specs_out))

    meta = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "intent": intent, "backend": plan["backend"]}
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
    return {"report": str(d / "report.md"), "dir": str(d), "plan": plan,
            "check": check, "n_charts": len(built["charts"]),
            "selected": built["selected"]}


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
            except Exception:                                    # noqa: BLE001
                m = {}
        out.append({"intent": d.name, "path": str(md), "dir": str(d),
                    "meta": m, "title": planner.INTENTS.get(d.name, d.name),
                    "mtime": md.stat().st_mtime})
    return out


# ------------------------------------------------------------------ 命令行
def main(argv=None):
    """CLI：`python src/flexible/report.py [期次目录] [意图] [后端] [学科]`。

    例：
        python src/flexible/report.py out/202607 single_trend rule
        python src/flexible/report.py out/202607 cross_compare rule
        WENHENG_LLM_BACKEND=ollama python src/flexible/report.py out/202607 single_trend
    """
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    out_dir = argv[0] if argv else "out/202607"
    intent = argv[1] if len(argv) > 1 else "single_trend"
    backend = argv[2] if len(argv) > 2 else None
    disc = argv[3] if len(argv) > 3 else None
    r = generate(out_dir, intent, backend=backend, disc=disc)
    print(f"[灵活报告] {planner.INTENTS.get(intent, intent)} → {r['report']}")
    print(f"  规划后端：{r['plan']['backend']}"
          + (f"（{r['plan']['fallback_reason']}）" if r["plan"].get("fallback_reason") else ""))
    print(f"  产出图 {r['n_charts']} 张；自检 {'通过 ✅' if r['check']['pass'] else '未通过 ❌'}")
    t = r["check"]["trace"]
    print(f"  数字可回溯：{t['ok']}/{t['checked']}"
          + (f"（异常 {t['bad']}）" if t["bad"] else ""))
    return 0 if r["check"]["pass"] else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    sys.exit(main())
