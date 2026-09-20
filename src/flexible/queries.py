# -*- coding: utf-8 -*-
"""LLM 拿数的**唯一入口**（4 个结构化查询）。

红线落点：LLM 的输出类型里没有「数字」这个物种。
它只能发 **JSON 查询**（白名单 schema），数值一律由本模块从 parquet 取出、
随**来源链**一起返回。因此「AI 生成报告的数字可靠吗」这个问题在本架构里
不是一个承诺，而是一个可验证的结构事实。

四个工具（演示级）：

| 工具 | 回答什么 | 对应分析意图 |
|---|---|---|
| `series` | 某学科某指标的期次序列 | ① 单学科趋势诊断 |
| `compare` | 某期某指标跨学科横截面 | ② 多学科横向对比 |
| `anomaly` | 异常/突变清单（规则判定） | ④ 异常/突变排查 |
| `scope` | 统计摘要（供规划） | 规划依据（**非可引用数值**） |

`SCHEMA` 是发给模型的**唯一**工具说明；`execute()` 是唯一执行入口，
未在白名单里的 kind / metric / 学科 / 期次一律拒绝——与 `agent/tools.py`
「主干不可被模型扩展」是同一道闸。
"""
from __future__ import annotations

import pandas as pd

from . import datasource as ds
from .datasource import METRICS, DataSource, cn_name, period_label

#: 允许的分析意图（演示级先做 ①②，③④ 已可查询，章节骨架后续补）
INTENTS = ("single_trend", "cross_compare", "anomaly_scan", "potential_forecast")

#: 发给模型的工具说明。**不含任何数值**，只有字段字典与可查询范围。
SCHEMA = {
    "kind": ["series", "compare", "anomaly", "scope"],
    "metrics": {k: {"cn": v["cn"], "better": v["better"]} for k, v in METRICS.items()},
    "args": {
        "series": {"metric": "指标名", "disc": "学科英文名", "periods": "期次列表（可省=全部）"},
        "compare": {"metric": "指标名", "discs": "学科英文名列表（可省=全部）", "period": "期次"},
        "anomaly": {"period": "期次（可省=当期）", "threshold": "突变倍数阈值（默认 1.5）"},
        "scope": {"period": "期次（可省=当期）"},
    },
    "note": "本表只描述可查询范围；返回值中的每个数字都带 source 来源链。",
}


class QueryError(Exception):
    """查询被拒（未在白名单内 / 参数非法）。"""


def _clean_periods(src: DataSource, periods=None) -> list[str]:
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
def series(src: DataSource, metric: str, disc: str, periods=None) -> dict:
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


# ------------------------------------------------------------ ② 横向对比
def compare(src: DataSource, metric: str, discs=None, period=None) -> dict:
    """某一期某指标的跨学科横截面（按「好」的方向排序）。"""
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
    return {
        "kind": "compare", "metric": metric, "metric_cn": METRICS[metric]["cn"],
        "period": period, "period_label": period_label(period), "better": better,
        "n": int(len(ordered)),
        "rows": [{"discipline": d, "discipline_cn": cn_name(d), "value": float(v),
                  "source": src.chain(metric, d, period)} for d, v in ordered.items()],
    }


# -------------------------------------------------------------- ④ 异常
def anomaly(src: DataSource, period=None, threshold: float = 1.5) -> dict:
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
def scope(src: DataSource, period=None) -> dict:
    """统计摘要：给规划器判断「本期该写哪些学科/哪些异常」。

    🔴 明确标记为 **planning_input（规划依据）**，不是可引用数值 ——
    正文里的数字仍须走 `series` / `compare` 单独取，并带来源链。
    """
    from . import summary as summ
    period = str(period or src.current_period())
    return summ.summarize(src, period)


# ------------------------------------------------------------------ 执行入口
def execute(src: DataSource, kind: str, **kwargs) -> dict:
    """唯一的查询执行入口。kind 不在白名单 → 直接拒绝。"""
    if kind not in SCHEMA["kind"]:
        raise QueryError(f"未登记的查询类型 {kind!r}（允许：{SCHEMA['kind']}）")
    allowed = SCHEMA["args"][kind]
    unknown = set(kwargs) - set(allowed)
    if unknown:
        raise QueryError(f"{kind} 收到未声明参数：{sorted(unknown)}（允许：{sorted(allowed)}）")
    return {"series": series, "compare": compare,
            "anomaly": anomaly, "scope": scope}[kind](src, **kwargs)


# ------------------------------------------------------------------ 溯源抽查
def trace_check(src: DataSource, result: dict) -> dict:
    """对查询结果做「来源链自洽」抽查：链里的数字能回读到同一张表。

    用于验收第 6 条（每个数字可回溯）。逐点回读，统计一致率。
    """
    pts = list(result.get("points") or result.get("items") or result.get("rows") or [])
    ok = bad = 0
    misses = []
    for it in pts:
        ch = it.get("source")
        if not ch:
            continue
        v = src.at(ch["metric"], ch["discipline"], ch["period"])
        if v is None:
            bad += 1
            misses.append(ch["locator"])
        elif isinstance(it.get("value"), (int, float)) and abs(v - it["value"]) < 1e-6:
            ok += 1
        else:
            bad += 1
            misses.append(ch["locator"])
    return {"checked": ok + bad, "ok": ok, "bad": bad, "misses": misses[:5]}
