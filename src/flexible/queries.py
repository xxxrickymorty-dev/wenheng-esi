# -*- coding: utf-8 -*-
"""LLM 拿数的**唯一入口**（结构化查询，白名单）。

红线落点：LLM 的输出类型里没有「数字」这个物种。
它只能发 **JSON 查询**（白名单 schema），数值一律由本模块从**只读视图**取出、
随**来源链**一起返回。因此「AI 生成报告的数字可靠吗」这个问题在本架构里
不是一个承诺，而是一个可验证的结构事实。

工具（演示级）：

| 工具 | 回答什么 | 对应分析意图 |
|---|---|---|
| `series` | 某学科某指标的期次序列（可指定期） | ① 单学科趋势诊断 |
| `at` | 某学科某指标**某一期**的单值 | 问「某期某数」 |
| `compare` | 某期某指标跨学科横截面（可只取前 k） | ② 多学科横向对比 |
| `delta` | 某学科某指标两期的差与变化率 | 环比/两期对比 |
| `events` | 学科进出 ESI 前 1% 的事件 | 进出榜排查 |
| `overall_rank` | 云大整体排名的期次序列 | 学校排名走势 |
| `anomaly` | 异常/突变清单（规则判定） | ④ 异常/突变排查 |
| `scope` | 统计摘要（供规划） | 规划依据（**非可引用数值**） |

数据面只认 `LedgerView` 协议（`DataSource`＝parquet 产物 / `WorkbookView`＝监测表直读）。
`SCHEMA` 是发给模型的**唯一**工具说明；`execute()` 是唯一执行入口，
未在白名单里的 kind / metric / 学科 / 期次一律拒绝——与 `agent/tools.py`
「主干不可被模型扩展」是同一道闸。
"""
from __future__ import annotations

import pandas as pd

from . import datasource as ds
from .datasource import METRICS, LedgerView, cn_name, period_label

#: 允许的分析意图（演示级先做 ①②，③④ 已可查询，章节骨架后续补）
INTENTS = ("single_trend",)

#: 发给模型的工具说明。**不含任何数值**，只有字段字典与可查询范围。
SCHEMA = {
    "kind": ["series", "at", "compare", "delta", "events", "overall_rank",
             "anomaly", "scope"],
    "metrics": {k: {"cn": v["cn"], "better": v["better"]} for k, v in METRICS.items()},
    "args": {
        "series": {"metric": "指标名", "disc": "学科英文名", "periods": "期次列表（可省=全部）"},
        "at": {"metric": "指标名", "disc": "学科英文名", "period": "一个期次"},
        "compare": {"metric": "指标名", "discs": "学科英文名列表（可省=全部）",
                    "period": "期次", "top": "只取前 k（可省）"},
        "delta": {"metric": "指标名", "disc": "学科英文名", "period": "本期次",
                  "prev": "对比期（可省=严格上一期）"},
        "events": {"disc": "学科英文名（可省=全部）"},
        "overall_rank": {"periods": "期次列表（可省=全部）"},
        "anomaly": {"period": "期次（可省=当期）", "threshold": "突变倍数阈值（默认 1.5）"},
        "scope": {"period": "期次（可省=当期）"},
    },
    "note": "本表只描述可查询范围；返回值中的每个数字都带 source 来源链。",
}


class QueryError(Exception):
    """查询被拒（未在白名单内 / 参数非法）。"""


def _clean_periods(src: LedgerView, periods=None) -> list[str]:
    allp = src.periods
    if not periods:
        return allp
    out = []
    for p in periods:
        p = str(p)
        if p not in allp:
            raise QueryError(f"期次 {p} 不在数据范围内（{allp[0]}–{allp[-1]}）")
        out.append(p)
    return sorted(set(out))


def _check_metric(metric: str) -> str:
    if metric not in METRICS:
        raise QueryError(f"指标 {metric!r} 不在白名单内：{sorted(METRICS)}")
    return metric


# ------------------------------------------------------------------ ① 序列
def series(src: LedgerView, metric: str, disc: str, periods=None) -> dict:
    """某学科某指标的期次序列。

    返回 `points` 里每一项都带来源链；`delta_*` 是**由点数算出的**，
    同样附链（指向首末两点）。
    """
    metric = _check_metric(metric)
    if disc not in src.disciplines:
        raise QueryError(f"学科 {disc!r} 不在名单内：{src.disciplines}")
    ps = _clean_periods(src, periods)
    s = src.series(metric, disc)
    keep = [p for p in ps if p in s.index]
    pts = [{"period": p, "value": float(s.loc[p]), "source": src.chain(metric, disc, p)}
           for p in keep]
    res = {
        "kind": "series", "metric": metric, "metric_cn": METRICS[metric]["cn"],
        "disc": disc, "disc_cn": cn_name(disc), "better": METRICS[metric]["better"],
        "n": len(pts), "points": pts,
    }
    if len(pts) >= 2:
        v0, v1 = pts[0]["value"], pts[-1]["value"]
        res["change"] = round(v1 - v0, 6)
        res["change_pct"] = round((v1 - v0) / v0 * 100, 2) if v0 else None
        res["from_period"], res["to_period"] = pts[0]["period"], pts[-1]["period"]
    return res


# ---------------------------------------------------------------- ③ 单值
def at(src: LedgerView, metric: str, disc: str, period: str) -> dict:
    """某学科某指标的**一个期次**取值；该期无数据 → `value=None`（如实，不猜）。"""
    metric = _check_metric(metric)
    if disc not in src.disciplines:
        raise QueryError(f"学科 {disc!r} 不在名单内：{src.disciplines}")
    period = str(period)
    if period not in [str(p) for p in src.periods]:
        raise QueryError(f"期次 {period} 不在数据范围内（{src.periods[0]}–{src.periods[-1]}）")
    v = src.at(metric, disc, period)
    res = {"kind": "at", "metric": metric, "metric_cn": METRICS[metric]["cn"],
           "disc": disc, "disc_cn": cn_name(disc),
           "period": period, "period_label": period_label(period),
           "value": None if v is None else float(v), "source": None}
    if v is None:
        res["note"] = f"{cn_name(disc)}在 {period} 该指标无数据。"
    else:
        res["source"] = src.chain(metric, disc, period)
    return res


# ------------------------------------------------------------ ② 横向对比
def compare(src: LedgerView, metric: str, discs=None, period=None, top=None) -> dict:
    """某一期某指标的跨学科横截面（按「好」的方向排序；`top` 只取前 k）。"""
    metric = _check_metric(metric)
    period = str(period or src.current_period())
    if period not in src.periods:
        raise QueryError(f"期次 {period} 不在数据范围内")
    cross = src.cross(metric, period)
    if discs:
        unknown = [d for d in discs if d not in cross.index]
        if unknown:
            raise QueryError(f"学科 {unknown} 在该期 %s 上无数据" % period)
        cross = cross[[d for d in discs if d in cross.index]]
    better = METRICS[metric]["better"]
    # 「好」在前：rank 类越小越好 → 升序；其余越大越好 → 降序。
    # （别写成 `better != "down"`：那会把接近度最差的学科排到第一，方向刚好反。）
    asc = better == "down"
    ordered = cross.sort_values(ascending=asc)
    if top is not None:
        try:
            k = int(top)
        except (TypeError, ValueError):
            raise QueryError(f"top 必须是整数（收到 {top!r}）") from None
        if k < 1:
            raise QueryError(f"top 必须 ≥1（收到 {top!r}）")
        ordered = ordered.head(k)
    return {
        "kind": "compare", "metric": metric, "metric_cn": METRICS[metric]["cn"],
        "period": period, "period_label": period_label(period), "better": better,
        "n": int(len(ordered)),
        "rows": [{"discipline": d, "discipline_cn": cn_name(d), "value": float(v),
                  "source": src.chain(metric, d, period)} for d, v in ordered.items()],
    }


# ------------------------------------------------------------ ④ 两期差/比
def delta(src: LedgerView, metric: str, disc: str, period: str, prev=None) -> dict:
    """某学科某指标：本期 vs 上一期（或指定期）的差与变化率。

    两期都取到才给 `diff`/`ratio_pct`；任一缺数 → 相应字段 None + note
    （缺数是事实，不抛；期次本身不在有数据范围内才抛）。
    """
    metric = _check_metric(metric)
    if disc not in src.disciplines:
        raise QueryError(f"学科 {disc!r} 不在名单内：{src.disciplines}")
    filled = [str(p) for p in src.filled_periods]
    period = str(period)
    if period not in filled:
        raise QueryError(f"期次 {period} 无数据（有数据范围：{filled[0]}–{filled[-1]}）")
    if prev is None:
        prev = ds.prev_period(filled, period)
        if prev is None:
            raise QueryError(f"{period} 之前没有可比期次")
    prev = str(prev)
    if prev not in filled:
        raise QueryError(f"对比期 {prev} 无数据（有数据范围：{filled[0]}–{filled[-1]}）")
    cur_v, old_v = src.at(metric, disc, period), src.at(metric, disc, prev)
    res = {"kind": "delta", "metric": metric, "metric_cn": METRICS[metric]["cn"],
           "disc": disc, "disc_cn": cn_name(disc),
           "period": period, "period_label": period_label(period),
           "prev": prev, "prev_label": period_label(prev),
           "value": None if cur_v is None else float(cur_v),
           "prev_value": None if old_v is None else float(old_v),
           "diff": None, "ratio_pct": None, "source": None, "source_prev": None}
    if cur_v is not None:
        res["source"] = src.chain(metric, disc, period)
    if old_v is not None:
        res["source_prev"] = src.chain(metric, disc, prev)
    if cur_v is None or old_v is None:
        missing = "、".join(p for p, v in ((period, cur_v), (prev, old_v)) if v is None)
        res["note"] = f"{cn_name(disc)}在 {missing} 无数据，无法比较。"
        return res
    res["diff"] = round(float(cur_v) - float(old_v), 6)
    res["ratio_pct"] = (round(res["diff"] / float(old_v) * 100, 2)
                        if float(old_v) else None)
    return res


# ------------------------------------------------------------ ⑤ 进出前 1%
def events(src: LedgerView, disc=None) -> dict:
    """学科进出 ESI 前 1% 的事件（《学科进入时间》流水；无流水时按 0/1 矩阵跳变推导）。

    `disc` 省 → 全部学科。`in_since`：自台账最早一期就在前 1% 内的学科 → 首期。
    """
    if disc is not None and disc not in src.disciplines:
        raise QueryError(f"学科 {disc!r} 不在名单内：{src.disciplines}")
    try:
        ent = src.entered_1pct()
    except KeyError:
        ent = None
    in_since, derived = {}, []
    if ent is not None and not getattr(ent, "empty", True):
        ent = ent.astype(float)
        cols = [str(c) for c in ent.columns]
        for d in ent.index:
            row = ent.loc[d]
            if len(cols) and float(row.iloc[0]) == 1.0:
                in_since[str(d)] = cols[0]
            for i in range(1, len(cols)):
                a, b = float(row.iloc[i - 1]), float(row.iloc[i])
                if a != b:
                    derived.append((cols[i], str(d), "in" if b == 1.0 else "out"))
    try:
        raw = list(src.entry_events() or [])
    except KeyError:
        raw = []
    items = []
    for p, d, kind in (raw or derived):
        d, p, kind = str(d), str(p), str(kind)
        if disc is not None and d != disc:
            continue
        items.append({
            "period": p, "type": kind, "discipline": d, "discipline_cn": cn_name(d),
            "source": {"kind": "ledger_cell", "origin_sheet": "学科进入时间",
                       "discipline": d, "discipline_cn": cn_name(d), "period": p,
                       "locator": f"学科进入时间：{cn_name(d)} {p}（流水账）"},
        })
    items.sort(key=lambda x: (x["period"], x["discipline"]))
    if disc is not None:
        in_since = {k: v for k, v in in_since.items() if k == disc}
    return {"kind": "events", "disc": disc, "disc_cn": cn_name(disc) if disc else "",
            "n": len(items), "events": items, "in_since": in_since,
            "note": "规则判定；『自最早一期起在线』记在 in_since。"}


# ------------------------------------------------------------ ⑥ 云大整体排名
def overall_rank(src: LedgerView, periods=None) -> dict:
    """云大整体排名的期次序列（《云大ESI排名》表；rank_intl / rank_cn / rank_cn_uni）。"""
    try:
        df = src.ynd_rank()
    except KeyError as e:
        raise QueryError(f"数据缺少《云大ESI排名》表：{e}") from e
    if df is None or getattr(df, "empty", True):
        raise QueryError("《云大ESI排名》表为空")
    ps = _clean_periods(src, periods)
    by_period = {str(p): row for p, row in df.iterrows()}
    pts = []
    for p in ps:
        row = by_period.get(p)
        if row is None:
            continue
        pts.append({
            "period": p,
            "rank_intl": _val(row.get("rank_intl")),
            "rank_cn": _val(row.get("rank_cn")),
            "rank_cn_uni": _val(row.get("rank_cn_uni")),
            "source": {"kind": "ledger_cell", "origin_sheet": "云大ESI排名",
                       "discipline": "云南大学", "discipline_cn": "云南大学", "period": p,
                       "locator": f"云大ESI排名：云南大学 行 × {p} 列"},
        })
    return {"kind": "overall_rank", "n": len(pts), "points": pts,
            "note": "云大整体排名（《云大ESI排名》表）。"}


def _val(x):
    """数值或 None（NaN/坏 → None）。"""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


# -------------------------------------------------------------- ⑥ 异常
def anomaly(src: LedgerView, period=None, threshold: float = 1.5) -> dict:
    """异常/突变清单：环比倍数越界的学科（**规则判定，不用模型**）。

    判据（刻意保守，宁缺勿滥）：相邻期比值 > threshold 或 < 1/threshold，
    且两期都有数（缺数不算突变，那叫数据缺口）。
    """
    period = str(period or src.current_period())
    if period not in src.periods:
        raise QueryError(f"期次 {period} 不在数据范围内")
    prev = ds.prev_period(src.periods, period)
    if prev is None:
        return {"kind": "anomaly", "period": period, "prev": None, "n": 0, "items": []}
    items = []
    for metric in ("total_cites", "papers", "proximity_1pct", "top_papers"):
        cur = src.cross(metric, period)
        old = src.cross(metric, prev)
        for d in cur.index:
            if d not in old.index:
                continue
            a, b = float(old.loc[d]), float(cur.loc[d])
            if b == 0 or a == 0:
                continue                          # 0 不能做比值（0→x 不是突变，是首现）
            ratio = b / a
            if ratio > threshold or ratio < 1.0 / threshold:
                items.append({
                    "discipline": d, "discipline_cn": cn_name(d),
                    "metric": metric, "metric_cn": METRICS[metric]["cn"],
                    "period": period, "prev": prev,
                    "prev_value": a, "value": b, "ratio": round(ratio, 3),
                    "source": src.chain(metric, d, period),
                    "source_prev": src.chain(metric, d, prev),
                })
    items.sort(key=lambda x: -abs(x["ratio"] - 1.0))
    return {"kind": "anomaly", "period": period, "prev": prev,
            "threshold": threshold, "n": len(items), "items": items,
            "note": "规则判定（相邻期比值越界），**规划依据**，不是可引用结论。"}


# -------------------------------------------------------------- 摘要（规划依据）
def scope(src: LedgerView, period=None) -> dict:
    """统计摘要：给规划器判断「本期该写哪些学科/哪些异常」。

    🔴 明确标记为 **planning_input（规划依据）**，不是可引用数值 ——
    正文里的数字仍须走 `series` / `compare` 单独取，并带来源链。
    """
    from . import summary as summ
    period = str(period or src.current_period())
    return summ.summarize(src, period)


# ------------------------------------------------------------------ 执行入口
def execute(src: LedgerView, kind: str, **kwargs) -> dict:
    """唯一的查询执行入口。kind 不在白名单 → 直接拒绝。"""
    if kind not in SCHEMA["kind"]:
        raise QueryError(f"未登记的查询类型 {kind!r}（允许：{SCHEMA['kind']}）")
    allowed = SCHEMA["args"][kind]
    unknown = set(kwargs) - set(allowed)
    if unknown:
        raise QueryError(f"{kind} 收到未声明参数：{sorted(unknown)}（允许：{sorted(allowed)}）")
    return {"series": series, "at": at, "compare": compare, "delta": delta,
            "events": events, "overall_rank": overall_rank,
            "anomaly": anomaly, "scope": scope}[kind](src, **kwargs)


# ------------------------------------------------------------------ 溯源抽查
def trace_check(src: LedgerView, result: dict) -> dict:
    """对查询结果做「来源链自洽」抽查：链里的数字能回读到同一张表。

    用于验收第 6 条（每个数字可回溯）。逐点回读，统计一致率。

    🔴 没有 `source` 的条目**算坏**，不再静默跳过——旧版跳过之后
    `checked=0` 也能让自检判过（「0/0 全对」）。链里没有 metric 的条目
    （进出事件、云大整体排名）只校验链的存在与定位，不做单格回读。
    """
    pts = list(result.get("points") or result.get("items") or result.get("rows")
               or result.get("events") or [])
    if not pts and result.get("source") is not None:
        pts = [{"value": result.get("value"), "source": result["source"]}]
    ok = bad = 0
    misses = []
    for i, it in enumerate(pts, 1):
        ch = it.get("source")
        if not ch:
            bad += 1
            misses.append(f"第 {i} 个数据点没有来源链")
            continue
        if "metric" not in ch or not isinstance(it.get("value"), (int, float)):
            if ch.get("origin_sheet") and (ch.get("locator") or ch.get("discipline")):
                ok += 1
            else:
                bad += 1
                misses.append(ch.get("locator") or f"第 {i} 个数据点来源链不完整")
            continue
        v = src.at(ch["metric"], ch["discipline"], ch["period"])
        if v is None:
            bad += 1
            misses.append(ch["locator"])
        elif abs(v - it["value"]) < 1e-6:
            ok += 1
        else:
            bad += 1
            misses.append(ch["locator"])
    return {"checked": ok + bad, "ok": ok, "bad": bad, "misses": misses[:5]}
