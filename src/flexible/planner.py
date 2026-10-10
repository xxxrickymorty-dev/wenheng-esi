# -*- coding: utf-8 -*-
"""章节规划器 —— **模型位可插拔，无模型时流程照跑**（本设计的核心主张）。

两个后端（D6 归口，2026-09-29）：

| 后端 | 行为 |
|---|---|
| `rule`（**默认**） | 纯规则挑科/挑指/挑期，**零依赖、确定性、可复现**。演示站永远用这个 |
| 云端模型 | 经 `src/ai` 的内部口出网（OpenAI 兼容，`WENHENG_AI_*` 配置）；**不合法即回退 rule**（不是报错） |

旧的 `ollama` / `http` 直连已废弃——模型出口统一走 AI 层（含数字盾），否则
「唯一模型出口」不成立。

🔴 红线落点：**模型拿不到任何数值**。
送给模型的只有 `spec.catalog()`（图型目录）、`queries.SCHEMA`（字段字典）、
`summary.summarize()`（**planning_input**，带溯源且显式标记为规划依据）——
其中出现的数字在出口处全部变成 `[[n]]` 占位符。
模型返回的**只有** 选哪个学科 / 哪个指标 / 哪几期 / 哪些图型 ——
任何越权字段（含纵轴范围）在 `_validate_plan` 里被剥掉；带新数字的输出整份回退。
"""
from __future__ import annotations

import json
import re

from . import queries as q
from . import spec as sp
from .datasource import METRICS, DataSource, cn_name, period_label

#: 演示级先做前两类意图（交接文档 §1「先做 ①②，跑通再扩」）。
INTENTS = {
    "single_trend": "单学科趋势诊断",
    "cross_compare": "多学科横向对比",
}

#: 规划的合法键（模型多给的键一律丢弃；纵轴类键在这里也进不来）
_PLAN_KEYS = ("intent", "disc", "metric", "periods", "n_periods", "charts", "title")

#: 校验点（`checks`）**不在** `_PLAN_KEYS` 里：它是规则产出的，模型给的会在
#: `_validate_plan` 被一并剥掉——否则模型会专挑容易过的校验点。


def checks_for(intent: str) -> list[dict]:
    """本意图的校验点清单（确定性、可复现；键仅 `kind` / `target` / `expect`）。

    三条锚点（spec §实现决策）：
    - `source_trace`：数据点与来源**双向**对得上；
    - `spec_query_match`：图（spec）声明与实际执行一致；
    - `outline_match`：声明清单（章节 / 图表）与实际产出一致。
    """
    checks = [
        {"kind": "source_trace", "target": "all_points", "expect": "bidirectional"},
        {"kind": "spec_query_match", "target": "charts", "expect": "declared==executed"},
        {"kind": "outline_match", "target": "sections", "expect": "declared==emitted"},
    ]
    if intent == "cross_compare":
        # 横版图多（4–5 张），图表清单单独核一遍
        checks.append({"kind": "outline_match", "target": "charts",
                       "expect": "declared==emitted"})
    return checks

_PLAN_SYSTEM = (
    "你是学科分析报告的**章节规划器**。你只决定「写哪个学科、配哪些图」这几个选择，"
    "不要输出任何数字、不要计算、不要给纵轴范围。"
    "所有数字都已替换为 [[n]] 占位标记：不要改写、不要删除、也不要新增任何数字与标记。"
    "只输出一个 JSON 对象，键仅允许：" + "、".join(_PLAN_KEYS) + "。"
    "其中 charts 是数组，元素形如 {\"kind\": \"图型名\", \"disc\": \"学科英文名\"}。"
)


def resolve_disc(src: DataSource, disc) -> str | None:
    """把用户给的学科（英文规范名 / 中文名 / 空）解析成英文名。

    未知学科 → `ValueError`（人话提示可选名单）——静默忽略正是 2026-09-29 的投诉源头。
    """
    if disc is None:
        return None
    s = str(disc).strip()
    if not s:
        return None
    if s in src.disciplines:
        return s
    for d in src.disciplines:
        if cn_name(d) == s:
            return d
    raise ValueError("学科「" + s + "」不在监测名单内；可选：" +
                     "、".join(cn_name(d) for d in src.disciplines))


def _rule_plan(src: DataSource, intent: str, *, disc=None, metric=None,
               periods=None, n_periods=None) -> dict:
    """规则规划：确定性挑科/挑指/挑期。`disc` 已经 `resolve_disc` 过。"""
    period = src.current_period()
    # 🔴 窗口取**有数据**的期次（`filled_periods`），末期占位列（202609 未发布）不算进去，
    #    否则「7 期」与图上实际画出的期数对不上、差分图还会多算一格。
    filled = src.filled_periods
    prev = filled[filled.index(period) - 1]
    n = int(n_periods or 7)
    win = filled[-n:]

    if intent == "single_trend":
        if not disc:
            # 挑「离过线最近的潜力学科」——决策上最有用，且完全确定性
            pot = [d for d in src.disciplines
                   if (src.at("proximity_1pct", d, period) or 0) < 1.0]
            disc = max(pot, key=lambda d: src.at("proximity_1pct", d, period) or 0) \
                if pot else src.disciplines[0]
        charts = [
            {"kind": "cites_threshold", "disc": disc,
             "why": "被引频次与 1% 阈值同图，直接看追赶态势"},
            {"kind": "papers_delta", "disc": disc, "why": "新增发文量看投入力度"},
            {"kind": "rank_pct", "disc": disc, "why": "国内外排名百分位看相对位次"},
        ]
        return {"intent": intent, "disc": disc, "metric": "proximity_1pct",
                "periods": win, "charts": charts,
                "title": f"{cn_name(disc)}发展态势诊断"}

    if intent == "cross_compare":
        met = metric or "proximity_1pct"
        charts = []
        if disc:
            # 指定了学科：锚定两张该学科的图（走势节），其余总览图做全池参照
            charts += [
                {"kind": "cites_threshold", "disc": disc,
                 "why": "被引频次与 1% 阈值同图，看追赶态势"},
                {"kind": "rank_pct", "disc": disc,
                 "why": "国内外排名百分位看相对位次"},
            ]
        charts += [
            {"kind": "overview_1pct", "why": "22 学科与 1% 基线的距离一览"},
            {"kind": "overview_1permille", "why": "已进 1% 学科与 1‰ 的差距"},
        ]
        title = (f"{cn_name(disc)} · 学科横向对比（{period_label(period)}，"
                 f"{METRICS[met]['cn']}）" if disc else
                 f"学科横向对比（{period_label(period)}，{METRICS[met]['cn']}）")
        return {"intent": intent, "disc": disc, "metric": met, "periods": win,
                "charts": charts, "title": title}

    raise ValueError(f"未登记的意图 {intent!r}（允许：{sorted(INTENTS)}）")


# ------------------------------------------------------------------ 模型后端
def _model_prompt(src: DataSource, intent: str, target=None) -> str:
    """给模型的提示。**不含任何数值** —— 只有字段字典、图型目录与规划依据摘要。"""
    sc = q.scope(src, src.current_period())
    payload = {
        "意图": {intent: INTENTS[intent]},
        "可选学科": src.disciplines,
        "可选指标": {k: v["cn"] for k, v in METRICS.items()},
        "可选图型": [{"kind": c["kind"], "cn": c["cn"],
                     "semantics": c["semantic"]} for c in sp.catalog()],
        "规划依据_摘要": {
            "period": sc["period"], "prev": sc["prev"],
            "n_entered_1pct": sc["n_entered_1pct"],
            "rank_moves": sc["rank_moves"],
            "potential_first": sc["potential"][:3],
            "prox_risers": [x["discipline"] for x in sc["prox_risers"]],
            "trust": sc["trust"],
        },
    }
    if target:
        payload["用户指定学科"] = {
            "en": target, "cn": cn_name(target),
            "硬约束": "单学科类图只能用这个学科；若给标题，标题必须含该学科中文名；不得另选学科",
        }
    return (
        "你是学科分析报告的**章节规划器**。你只决定「写哪个学科、配哪些图」这几个选择，"
        "不要输出任何数字、不要计算、不要给纵轴范围。\n"
        "只输出一个 JSON 对象，键仅允许：" + "、".join(_PLAN_KEYS) + "。\n"
        "其中 charts 是数组，元素形如 {\"kind\": \"图型名\", \"disc\": \"学科英文名\"}。\n"
        + ("🔴 用户已指定学科：单学科类图（disc_scope=single）的 disc 只许填它，"
           "标题必须含它。\n" if target else "")
        + "\n可用信息（其中『规划依据_摘要』仅供挑选方向，不是可引用数值）：\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
        + "\n\n直接输出 JSON："
    )


def _brain_plan(src, intent, target=None):
    """经 AI 层模型边界问云端（盾保护 + 校验）。返回 `(规划 JSON | None, 原因, 后端名)`。"""
    from ai import _attempt                                         # noqa: PLC0415

    res = _attempt.attempt(_model_prompt(src, intent, target), system=_PLAN_SYSTEM,
                           ability="flex-plan", anchored=False,
                           allow_substrings=tuple(sp.KINDS))
    if not res.attempted:
        return None, None, ""                                       # 规则部署：用规则规划
    if res.text is None:
        return None, res.reason, ""
    return _parse_json(res.text), None, res.backend


def _parse_json(raw: str) -> dict | None:
    """从模型输出里取出第一个 JSON 对象（模型常带解释文字或 ``` 围栏）。"""
    if not raw:
        return None
    s = raw.strip()
    s = s.replace("```json", "```")
    if "```" in s:                       # 取围栏内容
        parts = s.split("```")
        if len(parts) >= 3:
            s = parts[1]
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        got = json.loads(s[i:j + 1])
    except Exception:                                            # noqa: BLE001
        return None
    return got if isinstance(got, dict) else None


def _validate_plan(src: DataSource, got: dict, intent: str, fallback: dict,
                   target=None) -> dict:
    """把模型输出**清洗成合法规划**：越权键剥掉、非法值回退。

    🔴 这里没有「纵轴范围」这条路可走：`_PLAN_KEYS` 里根本没有它，
    而 charts 元素只认 `kind` / `disc` 两个键，多给的一律丢弃。
    用户指定学科（`target`）时：单学科图一律强制该学科、标题必须含它；
    横版未指定学科时：丢弃单学科图、标题走规则（防「工程学学科分析报告」式错位）。
    """
    clean = {k: got[k] for k in _PLAN_KEYS if k in got}
    # 纵轴类键若出现，直接整份丢弃（宁可回退 rule，也不接受越权规划）
    for k in got:
        if sp.is_forbidden_key(k):
            return fallback | {"fallback_reason": f"模型给出越权键 {k!r}，已回退规则规划"}
    clean["intent"] = intent

    charts = []
    for c in (clean.get("charts") or []):
        if not isinstance(c, dict) or c.get("kind") not in sp.KINDS:
            continue
        kind = c["kind"]
        if sp.KINDS[kind]["disc_scope"] == "single":
            if intent == "cross_compare" and not target:
                continue                     # 未指定学科 → 横版只留总览图
            disc = target or c.get("disc")
            if disc not in src.disciplines:
                if target:
                    disc = target
                else:
                    continue
        else:
            disc = None
        charts.append({"kind": kind, "disc": disc,
                       "why": str(c.get("why", ""))[:80]})
    if not charts:
        return fallback | {"fallback_reason": "模型未给出任何合法图型，已回退规则规划"}
    # 🔴 必须写回！否则返回的是模型原始 charts（非法学科/未知图型全漏出去）——
    #    这类失效不抛异常，只有逐项回读才发现。
    clean["charts"] = charts

    if intent == "single_trend":
        d = target or clean.get("disc") or fallback.get("disc")
        if d not in src.disciplines:
            d = fallback.get("disc")
        for c in charts:
            if sp.KINDS[c["kind"]]["disc_scope"] == "single" and not c["disc"]:
                c["disc"] = d
        clean["disc"] = d
    else:
        clean["disc"] = target or None

    clean["metric"] = clean.get("metric") if clean.get("metric") in METRICS \
        else fallback.get("metric")

    n = clean.get("n_periods")
    clean["n_periods"] = n if isinstance(n, int) and 2 <= n <= 30 else 7
    clean["periods"] = src.filled_periods[-clean["n_periods"]:]

    if intent == "cross_compare":
        if target:
            title = _clean_title(clean.get("title"), target, fallback.get("title"))
            if cn_name(target) not in title:
                title = fallback.get("title")
        else:
            title = fallback.get("title")    # 全池稿标题走规则，不让模型说成单科报告
    else:
        title = _clean_title(clean.get("title"), clean.get("disc"),
                             fallback.get("title"))
    clean["title"] = title
    return clean


def _clean_title(title, disc, fallback_title):
    """标题归一：模型爱把学科写成英文（实测给出 "Agricultural Sciences学科趋势分析"）。

    ① 把标题里出现的学科英文名换成中文规范名；② 一个中文都没有 → 直接用规则标题。
    """
    if not title:
        return fallback_title
    # 🔴 先判「有没有中文」再替换：反过来的话 `Trend of Engineering`
    #    替换成 `Trend of 工程学` 就含中文了，反而躲过这条判据。
    if not re.search(r"[一-鿿]", title):
        return fallback_title
    if disc and disc in title:
        title = title.replace(disc, cn_name(disc))
    return title[:60]


# ------------------------------------------------------------------ 主入口
def build(src: DataSource, intent: str = "single_trend", *,
          disc=None, metric=None, n_periods=None) -> dict:
    """产出章节规划：默认规则；配了云才问模型（不合法/失败一律回退规则）。

    `disc` 收英文规范名或中文名；未知学科直接 `ValueError`（不再静默忽略）。
    """
    if intent not in INTENTS:
        raise ValueError(f"未登记的意图 {intent!r}（允许：{sorted(INTENTS)}）")

    target = resolve_disc(src, disc)
    fallback = _rule_plan(src, intent, disc=target, metric=metric, n_periods=n_periods)
    fallback["backend"] = "rule"
    fallback["fallback_reason"] = None

    got, reason, backend_name = _brain_plan(src, intent, target)
    if got is None:
        if reason is not None:                        # 规则部署 reason=None（不是失败）
            fallback["fallback_reason"] = "云端模型不可用或未通过校验，已回退规则规划"
        fallback["checks"] = checks_for(intent)       # 两条路径都要带校验点
        return fallback
    plan = _validate_plan(src, got, intent, fallback, target)
    plan["backend"] = backend_name if plan.get("fallback_reason") is None else "rule"
    plan["checks"] = checks_for(intent)               # 规则产出，模型给的在上面已被剥
    return plan
