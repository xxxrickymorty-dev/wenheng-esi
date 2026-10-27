# -*- coding: utf-8 -*-
"""运行档案三指标（票 06）——计划合法率 / 校验拦截率 / 单份时长。

🔴 只做数据面：口径定义＋从**既有产物**（flex_meta.json / flex_plan.json）
计算，不新埋点、不做 UI（运行档案接线等票 04/05 过审后一起做）。
口径文档：`docs/metrics-三指标口径.md`（避免以后各算各的）。

一份灵活报告（`flexible/<intent>/`）记一个样本：

- **计划合法率**：模型规划的稿里，规划未被回退的占比。
  「模型参与」＝ `flex_plan.json` 的 `fallback_reason` 非空（回退了）
  或 `backend` 非 `rule`（模型规划直接成功）；合法＝参与且未回退。
  纯规则部署（零模型参与）→ 合法率 `None`（**不适用**，不冒充 100%）。
- **校验拦截率**：首轮自检不过的占比——有重规划轨迹
  （`meta.critic.rounds ≥ 1`，含救回）或终态不过（`check.pass == False`）。
  交人率另给（`escalated`＝重规划一次后仍不过）。
- **单份时长**：`meta.elapsed`（generate 落盘时写入的秒数）的
  n / mean / p50 / max。
"""
from __future__ import annotations

import json
import pathlib


def _load(path: pathlib.Path):
    """读 JSON；坏/缺产物按缺数据算（不炸汇总）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return None


def _rate(hit: int, total: int) -> float | None:
    """率 = hit/total；分母 0 → None（口径上「不适用」）。"""
    return round(hit / total, 3) if total > 0 else None


def summarize(period_dir) -> dict:
    """汇总某期次灵活产物（`flexible/*/`）的三指标。

    没跑完的半成品目录（无 flex_meta.json）不算样本。
    返回结构 JSON 可落（运行档案直接读）。
    """
    base = pathlib.Path(period_dir) / "flexible"
    dirs = sorted(p for p in base.iterdir() if p.is_dir()) \
        if base.is_dir() else []

    plan_n = model_n = model_legal = 0
    intercepted = escalated = 0
    durations: list[float] = []
    for d in dirs:
        meta = _load(d / "flex_meta.json")
        if not isinstance(meta, dict) or not meta:
            continue                                         # 半成品：不算样本
        plan = _load(d / "flex_plan.json") or {}
        plan_n += 1
        backend = plan.get("backend")
        fallback = bool(plan.get("fallback_reason"))
        if fallback or backend not in (None, "rule"):
            model_n += 1                                     # 模型参与规划
            model_legal += int(not fallback)                 # 未回退＝合法
        check = meta.get("check") or {}
        critic = meta.get("critic") or {}
        if critic.get("rounds") or check.get("pass") is False:
            intercepted += 1                                 # 首轮被拦（含救回）
        escalated += int(bool(critic.get("escalated")))
        el = meta.get("elapsed")
        if isinstance(el, (int, float)) and el >= 0:
            durations.append(float(el))

    s = sorted(durations)
    n = len(s)
    return {
        "n": plan_n,
        "plans": {"model_n": model_n, "model_legal": model_legal,
                  "legal_rate": _rate(model_legal, model_n)},
        "checks": {"intercepted": intercepted, "escalated": escalated,
                   "intercept_rate": _rate(intercepted, plan_n),
                   "escalate_rate": _rate(escalated, plan_n)},
        "duration_sec": {"n": n,
                         "mean": round(sum(s) / n, 1) if n else None,
                         # p50 取上中位（偶数样本取右），口径见文档
                         "p50": s[n // 2] if n else None,
                         "max": s[-1] if n else None},
    }
