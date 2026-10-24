# -*- coding: utf-8 -*-
"""AI 问数引擎 —— 自然语言 → 白名单查询规格 → SQL 执行 → 图表建议。

红线（spec 2026-10-12 LLM侧架构，四不变量）：
1. **模型的输出类型里没有数值**：规划器只产「查询规格」（指标名/学科名/期次枚举，
   全部来自白名单，零数字 token）；离线规则规划器是默认适配器（演示站规则锁形态），
   模型规划器（可选）经 `src.ai._attempt` 统一边界接入——本模块不直接调模型。
2. **值只从一条缝进来**：SQL 由本引擎按规格**参数化拼装**（列名来自白名单字典、
   参数一律 `?` 占位），执行于只读连接；计划面与值面之间没有第三条路。
3. **离线兜底＝同端口的另一个适配器**：`plan()` 纯规则、零依赖，离线可跑；
   `plan_with_model()` 有云配置时走模型规划（越权/带数字 → 整份回退 rule）。
4. **留痕**：每次查询由调用方经 `aiqa_db.log_qa` 落 `qa_log`。

对外三口：
    plan(question, con)          -> {"specs": [...], "origin": "rule", "note": str}
    execute(con, specs)          -> {"rows": [...], "columns": [...], "note": str}
    suggest_chart(specs, rows)   -> {"kind": "bar|pie|line|table", "x": ..., "y": [...]}
"""
from __future__ import annotations

import re

try:                                       # 包内导入（server / src.ai 路径）
    from . import aiqa_db
except ImportError:                        # 直接以 src/ 为 sys.path 的脚本
    import aiqa_db

# ---------------------------------------------------------------- 白名单

#: 指标别名（中文问法 → 白名单指标名）。
_METRIC_ALIAS = {
    "总被引": "total_cites", "总被引频次": "total_cites", "被引": "total_cites",
    "被引频次": "total_cites", "引用": "total_cites", "引用频次": "total_cites",
    "论文": "papers", "论文数": "papers", "发文": "papers", "发文量": "papers",
    "cnci": "cnci", "学科规范化的引文影响力": "cnci",
    "接近度": "proximity_1pct", "前1%接近度": "proximity_1pct",
    "esipref1接近度": "proximity_1pct",
    "阈值": "threshold_1pct", "前1%阈值": "threshold_1pct",
    "被引阈值": "threshold_1pct", "前百分之一阈值": "threshold_1pct",
    "顶尖论文": "top_papers", "顶尖论文数": "top_papers",
    "热点论文": "top_papers", "高被引论文": "top_papers", "高被引": "top_papers",
    "千分之一阈值": "threshold_1permille", "前1‰阈值": "threshold_1permille",
    "千分位": "permille_rank",
    "国内排名": "rank", "排名": "rank",
    "国际排名": "rank_intl", "世界排名": "rank_intl",
    "百分位": "rank_pct", "排名百分位": "rank_pct",
    "前1%机构数": "n_inst_1pct", "机构数": "n_inst_1pct",
    "篇均被引": "avg_cites",
}

#: 白名单 SQL 列（report_table2 的列 → 中文名）。问数大表面。
_TABLE2_COLS = {
    "papers": "论文数", "cnci": "CNCI", "total_cites": "总被引频次",
    "thr_1pct": "前1%阈值", "thr_1pct_gap": "前1%阈值差",
    "thr_1permille": "前1‰阈值", "permille_rank": "千分位",
    "top_papers": "顶尖论文数",
}

#: 规格类型白名单。
_KINDS = ("series", "compare", "at", "overview", "table2")

_PERIOD_RE = re.compile(r"20\d{4}")


def _disc_map(con) -> dict[str, str]:
    """中文名 → 英文规范名（含英文名自身）。"""
    m = {}
    for r in con.execute(
            "SELECT discipline, discipline_cn FROM dim_discipline ORDER BY ord"):
        m[r[1]] = r[0]
        m[r[0]] = r[0]
    # 常见简称
    m.update({"化学": "Chemistry", "数学": "Mathematics", "物理": "Physics",
              "工程": "Engineering", "工程学": "Engineering",
              "材料": "Materials Science", "材料科学": "Materials Science",
              "农学": "Agricultural Sciences", "计算机": "Computer Science",
              "临床": "Clinical Medicine", "临床医学": "Clinical Medicine",
              "地球科学": "Geosciences", "社科": "Social Sciences, general",
              "社会科学": "Social Sciences, general", "免疫": "Immunology",
              "微生物": "Microbiology", "微生物学": "Microbiology"})
    return m


def _metric_of(text: str) -> str | None:
    """问句 → 指标（按别名长度降序做包含，防「前1%阈值」被「阈值」截胡）。"""
    low = text.lower()
    for k in sorted(_METRIC_ALIAS, key=len, reverse=True):
        if k in low or k in text:
            return _METRIC_ALIAS[k]
    return None


def _periods_in(text: str, filled: list[str]) -> list[str]:
    """问句里的期次（YYYYMM）；「最新/当期/最新一期」→ 最新有数据期。"""
    if any(w in text for w in ("最新", "当期", "本期", "最近一期", "最近")):
        return [filled[-1]] if filled else []
    found = [p for p in _PERIOD_RE.findall(text) if p in filled]
    # 2026年7月 形态
    for y, m in re.findall(r"(20\d\d)年(\d{1,2})月", text):
        p = f"{y}{int(m):02d}"
        if p in filled:
            found.append(p)
    return sorted(set(found))


# ============================================================ 规划器（规则版）

def plan(question: str, con) -> dict:
    """规则规划器：问句 → 白名单查询规格（零数字出口；期次走确定性解析）。"""
    q = str(question or "").strip()
    filled = aiqa_db.view_periods(con)
    discs = _disc_map(con)
    # 学科命中：按名字长度降序（「生物学与生物化学」优先于「化学」……但中文别名
    # 都是短词，直接全表扫）
    hit_discs = [en for cn, en in discs.items() if len(cn) >= 2 and cn in q]
    # 去重保序（英文名自身也会命中）
    seen: set = set()
    hit_discs = [d for d in hit_discs if not (d in seen or seen.add(d))]
    periods = _periods_in(q, filled)
    metric = _metric_of(q)

    specs: list[dict] = []
    note = ""

    if not q:
        return {"specs": [], "origin": "rule", "note": "空问题"}

    # ① 概述类：「多少个学科进入前1%」「整体情况」
    if not metric and not hit_discs and any(
            w in q for w in ("多少个", "几门", "几个", "概况", "整体", "总体")):
        specs.append({"kind": "overview", "period": periods[-1] if periods else
                      (filled[-1] if filled else "")})
        return {"specs": specs, "origin": "rule", "note": "概述"}

    # ② 学科×指标：单学科 → series / at；多学科或「排名/对比」→ compare
    if metric and hit_discs:
        ps = periods or [filled[-1]] if filled else []
        if len(hit_discs) == 1 and ("趋势" in q or "走势" in q or "变化" in q
                                    or "历期" in q or "以来" in q or not periods):
            specs.append({"kind": "series", "metric": metric,
                          "disc": hit_discs[0],
                          "period_max": ps[-1] if periods else None})
        elif len(hit_discs) == 1 and periods:
            specs.append({"kind": "at", "metric": metric, "disc": hit_discs[0],
                          "period": periods[-1]})
        else:
            specs.append({"kind": "compare", "metric": metric,
                          "discs": hit_discs,
                          "period": periods[-1] if periods else
                          (filled[-1] if filled else "")})
        return {"specs": specs, "origin": "rule", "note": ""}

    # ③ 指标无学科：「哪几个学科论文最多」→ compare 全学科 top
    if metric and not hit_discs:
        m_top = None
        mt = re.search(r"前\s*(\d{1,2})\s*名", q)
        if mt:
            m_top = min(int(mt.group(1)), 22)
        specs.append({"kind": "compare", "metric": metric, "discs": None,
                      "period": periods[-1] if periods else
                      (filled[-1] if filled else ""), "top": m_top})
        return {"specs": specs, "origin": "rule", "note": ""}

    # ④ 学科无指标：给该学科当期大表整行
    if hit_discs and not metric:
        specs.append({"kind": "table2", "discs": hit_discs,
                      "period": periods[-1] if periods else
                      (filled[-1] if filled else "")})
        return {"specs": specs, "origin": "rule", "note": ""}

    note = "没认出指标或学科；可问「化学的总被引趋势」「202607 论文数前 5 名」"
    return {"specs": [], "origin": "rule", "note": note}


# ============================================================ 执行器（参数化 SQL）

_EXEC_COLS = {"papers", "cnci", "total_cites", "thr_1pct", "thr_1pct_gap",
              "thr_1permille", "permille_rank", "top_papers"}


def _table2_join(period: str, discs: list[str] | None) -> tuple[str, list]:
    """大表查询（列白名单内、参数化）。"""
    where = ["period=?"]
    args: list = [period]
    if discs:
        where.append(f"discipline IN ({','.join('?' * len(discs))})")
        args += discs
    sql = ("SELECT period, discipline, rank_cn_change, papers, cnci, total_cites,"
           " thr_1pct, thr_1pct_gap, thr_1permille, permille_rank, top_papers,"
           " prox_change FROM report_table2 WHERE "
           + " AND ".join(where) + " ORDER BY total_cites DESC")
    return sql, args


def execute(con, specs: list[dict]) -> dict:
    """执行白名单规格 → 行集（columns + rows）。所有 SQL 参数化、列名出白名单。"""
    rows: list[dict] = []
    columns: list[str] = []
    notes: list[str] = []
    for spec in specs or []:
        kind = spec.get("kind")
        if kind not in _KINDS:
            notes.append(f"未登记的查询类型 {kind!r}")
            continue
        if kind == "series":
            metric = spec.get("metric", "")
            if metric not in {r["metric"] for r in aiqa_db.view_metrics(con)}:
                notes.append(f"指标 {metric!r} 不在白名单")
                continue
            pts = aiqa_db.view_series(con, metric, spec.get("disc", ""),
                                      period_max=spec.get("period_max"))
            rows.append({"type": "series", "metric": metric,
                         "disc": spec.get("disc", ""),
                         "points": pts})
            if not columns:
                columns = ["period", "value"]
        elif kind == "compare":
            metric = spec.get("metric", "")
            if metric not in {r["metric"] for r in aiqa_db.view_metrics(con)}:
                notes.append(f"指标 {metric!r} 不在白名单")
                continue
            period = spec.get("period") or ""
            cross = aiqa_db.view_cross(con, metric, period)
            discs = spec.get("discs")
            if discs:
                cross = [c for c in cross if c["discipline"] in discs]
            better = next((r["better"] for r in aiqa_db.view_metrics(con)
                           if r["metric"] == metric), "none")
            cross = [c for c in cross if c["value"] is not None]
            cross.sort(key=lambda c: c["value"],
                       reverse=(better != "down"))
            top = spec.get("top")
            if top:
                cross = cross[:int(top)]
            rows.append({"type": "compare", "metric": metric, "period": period,
                         "items": cross})
            if not columns:
                columns = ["discipline", "discipline_cn", "value"]
        elif kind == "at":
            metric = spec.get("metric", "")
            pts = aiqa_db.view_series(con, metric, spec.get("disc", ""),
                                      period_max=spec.get("period"))
            v = pts[-1]["value"] if pts else None
            rows.append({"type": "at", "metric": metric,
                         "disc": spec.get("disc", ""),
                         "period": spec.get("period", ""), "value": v})
            if not columns:
                columns = ["discipline", "metric", "period", "value"]
        elif kind == "overview":
            period = spec.get("period") or ""
            got = dict(con.execute(
                "SELECT key, value FROM report_overview WHERE period=?",
                (period,)).fetchall())
            rows.append({"type": "overview", "period": period, "facts": got})
            if not columns:
                columns = ["key", "value"]
        elif kind == "table2":
            period = spec.get("period") or ""
            discs = spec.get("discs")
            sql, args = _table2_join(period, discs)
            got = [dict(r) for r in con.execute(sql, args)]
            rows.append({"type": "table2", "period": period, "rows": got})
            if not columns:
                columns = list(got[0].keys()) if got else []
    return {"rows": rows, "columns": columns, "note": "；".join(notes)}


# ============================================================ 渲染与图型建议

_OVERVIEW_CN = {
    "n_disc_1pct": "进入 ESI 前 1% 学科数",
    "top_papers_now": "顶尖论文数（本期）",
    "top_papers_prev": "顶尖论文数（上期）",
    "top_papers_delta": "顶尖论文较上期",
    "rank_intl_now": "国际排名（本期）",
    "rank_intl_prev": "国际排名（上期）",
    "rank_intl_delta": "国际排名变化（升为正）",
}


def _fmt_val(metric: str, v) -> str:
    if v is None:
        return "无数据"
    if metric in ("cnci", "permille_rank", "rank_pct", "proximity_1pct"):
        return f"{v:.3f}"
    return f"{v:,.0f}"


def _metric_cn(con, metric) -> str:
    for r in aiqa_db.view_metrics(con):
        if r["metric"] == metric:
            return r["metric_cn"]
    return metric


def _disc_cn(con, disc) -> str:
    r = con.execute("SELECT discipline_cn FROM dim_discipline WHERE discipline=?",
                    (disc,)).fetchone()
    return r[0] if r else disc


def render_text(con, question, result) -> str:
    """结果 → 人话句子（模板拼装，零模型、零计算——数都来自执行器）。"""
    lines: list[str] = []
    for r in result.get("rows") or []:
        t = r.get("type")
        if t == "series":
            pts = [p for p in r["points"] if p["value"] is not None]
            if not pts:
                lines.append(f"{_disc_cn(con, r['disc'])}的"
                             f"{_metric_cn(con, r['metric'])}暂无数据。")
                continue
            first, last = pts[0], pts[-1]
            span = f"{first['period']} 至 {last['period']}" if len(pts) > 1 \
                else last["period"]
            lines.append(f"{_disc_cn(con, r['disc'])}的"
                         f"{_metric_cn(con, r['metric'])}（{span}）："
                         f"共 {len(pts)} 期，最新 {last['period']} 为 "
                         f"{_fmt_val(r['metric'], last['value'])}。")
        elif t == "compare":
            items = r.get("items") or []
            if not items:
                lines.append(f"{r['period']} 期{_metric_cn(con, r['metric'])}"
                             "无数据。")
                continue
            head = "、".join(
                f"{c['discipline_cn']} {_fmt_val(r['metric'], c['value'])}"
                for c in items[:8])
            more = f"（等共 {len(items)} 个学科）" if len(items) > 8 else ""
            lines.append(f"{r['period']} 期{_metric_cn(con, r['metric'])}：{head}{more}。")
        elif t == "at":
            lines.append(f"{_disc_cn(con, r['disc'])}在 {r['period']} 的"
                         f"{_metric_cn(con, r['metric'])}为 "
                         f"{_fmt_val(r['metric'], r.get('value'))}。")
        elif t == "overview":
            facts = r.get("facts") or {}
            for k in ("n_disc_1pct", "top_papers_now", "top_papers_delta",
                      "rank_intl_now", "rank_intl_delta"):
                if k in facts:
                    lines.append(f"{_OVERVIEW_CN.get(k, k)}：{facts[k]}")
        elif t == "table2":
            for row in (r.get("rows") or []):
                d_cn = _disc_cn(con, row.get("discipline", ""))
                lines.append(
                    f"{d_cn}（{r['period']}）：论文 {row.get('papers') or '—'}，"
                    f"总被引 {(row.get('total_cites') or 0):,}，"
                    f"CNCI {row.get('cnci') if row.get('cnci') is not None else '—'}，"
                    f"顶尖论文 {row.get('top_papers') if row.get('top_papers') is not None else '—'}，"
                    f"国内排名 {row.get('rank_cn_change') or '—'}，"
                    f"接近度变化 {row.get('prox_change') or '—'}。")
    if result.get("note"):
        lines.append(result["note"])
    if not lines:
        lines.append("没有查到匹配的数据；可问「化学的总被引趋势」"
                     "「202607 论文数前 5 名」「整体概况」。")
    return "\n".join(lines)


def suggest_chart(con, specs, result) -> dict:
    """结果形状 → 图型建议（bar / pie / line / table）。

    依据（不碰数值，只看形状）：
    - series（时间序列）→ line；
    - compare 全学科 >6 个 → bar（横向条形更易读）；≤6 个 → bar；
      问句带「占比/份额」时 → pie（占比语义）；
    - table2 / overview / at → table。
    """
    rows = result.get("rows") or []
    want_pie = any(w in str(specs) for w in ("占比", "份额", "比例"))
    for r in rows:
        t = r.get("type")
        if t == "series":
            return {"kind": "line", "x": "period",
                    "y": [f"{r['disc']}.{r['metric']}"],
                    "title": f"{_disc_cn(con, r['disc'])} · "
                             f"{_metric_cn(con, r['metric'])} 走势"}
        if t == "compare":
            n = len(r.get("items") or [])
            if want_pie and 2 <= n <= 10:
                return {"kind": "pie", "x": "discipline_cn",
                        "y": ["value"],
                        "title": f"{r['period']} 期"
                                 f"{_metric_cn(con, r['metric'])} 占比"}
            return {"kind": "bar", "x": "discipline_cn", "y": ["value"],
                    "title": f"{r['period']} 期"
                             f"{_metric_cn(con, r['metric'])}"
                             + ("（前 N 名）" if r.get("items") else "")}
    return {"kind": "table", "x": "", "y": [], "title": ""}


def to_chart_data(con, chart: dict, result) -> dict:
    """把执行结果按图型建议展开成 ECharts 就绪的 {categories, series}。

    只做形状搬运（行列转置），不做任何数值计算。
    """
    kind = chart.get("kind")
    rows = result.get("rows") or []
    out = {"kind": kind, "title": chart.get("title", ""),
           "categories": [], "series": []}
    for r in rows:
        if kind == "line" and r.get("type") == "series":
            pts = [p for p in r["points"] if p["value"] is not None]
            out["categories"] = [p["period"] for p in pts]
            out["series"].append({
                "name": f"{_disc_cn(con, r['disc'])}·"
                        f"{_metric_cn(con, r['metric'])}",
                "data": [p["value"] for p in pts]})
        elif kind in ("bar", "pie") and r.get("type") == "compare":
            items = [c for c in (r.get("items") or [])
                     if c["value"] is not None]
            out["categories"] = [c["discipline_cn"] for c in items]
            out["series"].append({
                "name": _metric_cn(con, r["metric"]),
                "data": [c["value"] for c in items]})
    return out
