# -*- coding: utf-8 -*-
"""统计摘要 + 异常检测（**规则实现，不用模型**）。

红线的第三层落点：摘要层**要给**模型看 —— 否则规划会退化成瞎猜。
但它被显式标记为 `planning_input`（规划依据），不是 `quotable`（可引用数值）：
正文里的数字仍须走 `queries.series/compare` 单独取、单独带链。

异常检测用**纯规则**：环比倍数越界 / 排名连续同向 / 接近度跌破 1。
不需要模型判断，也就没有模型的幻觉空间。
"""
from __future__ import annotations

import pandas as pd

from . import datasource as ds
from .datasource import METRICS, DataSource, cn_name, period_label

#: 摘要里各字段的可信等级。`planning_input` = 只许 LLM 用来规划，不许直接写进正文。
TRUST = "planning_input"


def _f(v):
    return None if v is None or pd.isna(v) else float(v)


def summarize(src: DataSource, period: str) -> dict:
    """本期摘要：可供规划器挑选「写哪些学科、盯哪些异常」。"""
    period = str(period)
    prev = ds.prev_period(src.periods, period)
    ent = src.entered_1pct()
    n_entered = int(ent[period].sum()) if period in ent.columns else None

    # 排名升降分布（国内排名口径）
    rank = src.cross("rank", period)
    rprev = src.cross("rank", prev) if prev else pd.Series(dtype=float)
    up = down = flat = 0
    movers = []
    if prev:
        for d in rank.index:
            if d not in rprev.index:
                continue
            dlt = float(rprev.loc[d]) - float(rank.loc[d])     # 正=上升
            if dlt > 0:
                up += 1
            elif dlt < 0:
                down += 1
            else:
                flat += 1
            movers.append({"discipline": d, "discipline_cn": cn_name(d),
                           "delta": int(dlt), "rank": int(rank.loc[d]),
                           "source": src.chain("rank", d, period)})
    movers.sort(key=lambda x: x["delta"])

    # 接近度变化（涨/跌最大的学科）
    prox = src.cross("proximity_1pct", period)
    pprev = src.cross("proximity_1pct", prev) if prev else pd.Series(dtype=float)
    prox_moves = []
    if prev:
        for d in prox.index:
            if d not in pprev.index:
                continue
            a, b = float(pprev.loc[d]), float(prox.loc[d])
            prox_moves.append({"discipline": d, "discipline_cn": cn_name(d),
                               "chg_pp": round((b - a) * 100, 2), "value": round(b, 4),
                               "source": src.chain("proximity_1pct", d, period)})
        prox_moves.sort(key=lambda x: -x["chg_pp"])

    # 潜力学科（接近度 < 1，按接近度降序）—— 判据与 forecast_select.potential_disciplines 同口径
    potential = sorted([d for d in prox.index if float(prox.loc[d]) < 1.0],
                       key=lambda d: -float(prox.loc[d]))

    return {
        "kind": "scope",
        "trust": TRUST,
        "note": "本摘要为**规划依据**（planning_input），不是可引用数值；"
                "正文数字须走 queries.series / compare 单独取并附来源链。",
        "period": period, "period_label": period_label(period), "prev": prev,
        "n_disciplines": int(len(src.disciplines)),
        "n_entered_1pct": n_entered,
        "rank_moves": {"up": up, "down": down, "flat": flat},
        "rank_worst": movers[:3],
        "rank_best": movers[::-1][:3],
        "prox_risers": prox_moves[:3],
        "prox_fallers": prox_moves[::-1][:3],
        "potential": potential[:6],
        "n_potential": len(potential),
        "available_periods": [src.periods[0], src.periods[-1], len(src.periods)],
        "metrics": {k: v["cn"] for k, v in METRICS.items()},
    }


def anomalies(src: DataSource, period: str, threshold: float = 1.5) -> dict:
    """异常检测（规则）：环比倍数越界 + 排名连续同向 + 接近度跨越 1 的边界。"""
    from . import queries as q
    jumps = q.anomaly(src, period=period, threshold=threshold)

    # 排名连续同向（连续 3 期同向 = 趋势性异常，比单期跳变更值得写）
    streaks = []
    for d in src.disciplines:
        s = src.series("rank", d)
        if len(s) < 4:
            continue
        tail = s.tail(4)
        vals = [float(v) for v in tail.values]
        dl = [vals[i + 1] - vals[i] for i in range(3)]
        if all(x > 0 for x in dl) or all(x < 0 for x in dl):
            streaks.append({
                "discipline": d, "discipline_cn": cn_name(d),
                "direction": "持续上升" if dl[0] > 0 else "持续下降",
                "delta_total": int(dl[-1] + dl[-2] + dl[-3]),
                "periods": [str(p) for p in tail.index],
                "source": src.chain("rank", d, str(tail.index[-1])),
            })
    streaks.sort(key=lambda x: -abs(x["delta_total"]))

    # 接近度跨过 1.0（进/出前 1% 的信号）
    cross_1 = []
    prev = ds.prev_period(src.periods, period)
    if prev:
        cur, old = src.cross("proximity_1pct", period), src.cross("proximity_1pct", prev)
        for d in cur.index:
            if d not in old.index:
                continue
            a, b = float(old.loc[d]), float(cur.loc[d])
            if (a - 1.0) * (b - 1.0) < 0:
                cross_1.append({"discipline": d, "discipline_cn": cn_name(d),
                                "from": round(a, 4), "to": round(b, 4),
                                "direction": "升过100%" if b > a else "跌破100%",
                                "source": src.chain("proximity_1pct", d, period)})

    return {"kind": "anomaly", "trust": TRUST, "period": period, "prev": prev,
            "threshold": threshold,
            "jumps": jumps["items"], "streaks": streaks, "cross_1pct": cross_1,
            "n": len(jumps["items"]) + len(streaks) + len(cross_1),
            "note": "全部为**规则判定**，供规划挑题；写进正文时须另走查询取数并附链。"}
