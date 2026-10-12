# -*- coding: utf-8 -*-
"""取数规划器（票 02：规则路径）——问句 → QueryPlan（引擎白名单规格列表）。

口径（红线落点）：规划器的输出**只有名字**（指标/学科/形状），没有任何数值；
**期次不进规划**（窗口由编排口确定性给定；"最近六期"= 视图期次轴的最后六列，
与 _qa v1 台账段同口径）。模型路径（票 03）在 `plan()` 上叠 ModelPlanner 适配器；
本模块现在只有 RulePlanner——**无模型也能跑**（演示站规则锁照旧）。

当前规则（与 _qa v1 的台账段口径一一对应，2026-10-11 rick 定）：

- 点到学科 + 点到指标 → 该科该指标的近六期序列（每科一条 `series`）；
- 点到学科 + 问「进入/退出/入榜/进榜」→ 进出前 1% 事件（`events`）；
- 没点学科、点到排名指标、问到云大/我校/学校 → 云大整体排名序列（`overall_rank`）。
"""
from __future__ import annotations

#: 指标关键词（按具体到宽泛排序）→ 引擎规范名。**顺序即优先级**：
#: 「1‰ / 千分之一」必须在「阈值」之前，否则「前 1‰ 阈值」会被误判成前 1% 阈值；
#: 排名关键词放最后（与 v1「先指标表、后排名表」的判定顺序一致）。
_METRIC_KW = (
    ("千分之一", "threshold_1permille"),
    ("1‰", "threshold_1permille"),
    ("接近度", "proximity_1pct"),
    ("论文数", "papers"),
    ("论文量", "papers"),
    ("发文量", "papers"),
    ("发文", "papers"),
    ("被引", "total_cites"),
    ("CNCI", "cnci"),
    ("cnci", "cnci"),
    ("阈值", "threshold_1pct"),
    ("顶尖", "top_papers"),
    ("国内排名", "rank_cn"),
    ("国际排名", "rank_intl"),
)

#: 问「进出」的关键词（v1 同款）。
_EVENT_KW = ("进入", "退出", "入榜", "进榜")

#: 云大整体排名的问法关键词（v1 同款）。
_YND_KW = ("云大", "我校", "学校", "云南大学", "全校")


def metric_hit(question):
    """问句里的指标关键词 → 引擎规范名；没有 → None。"""
    q = str(question or "")
    for kw, key in _METRIC_KW:
        if kw in q:
            return key
    return None


def rule_specs(question, discs=()) -> list:
    """规则规划：问句 + 问到的学科（en 名单）→ spec 列表（与 v1 台账段一一对应）。"""
    q = str(question or "")
    specs = []
    metric = metric_hit(q)
    if discs and metric:
        specs += [{"op": "series", "metric": metric, "disc": d, "span": "recent"}
                  for d in discs]
    if discs and any(kw in q for kw in _EVENT_KW):
        specs += [{"op": "events", "disc": d} for d in discs]
    if (not discs and metric in ("rank_cn", "rank_intl")
            and any(kw in q for kw in _YND_KW)):
        specs.append({"op": "overall_rank", "span": "recent"})
    return specs


def plan(question, *, discs=(), history=()) -> dict:
    """问句 → QueryPlan。规则路径（票 02）；模型路径（票 03）落在这个接口上。"""
    return {"specs": rule_specs(question, discs), "origin": "rule", "note": ""}
