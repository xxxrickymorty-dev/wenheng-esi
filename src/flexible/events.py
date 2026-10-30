# -*- coding: utf-8 -*-
"""图上该标哪个点——从多条时序里挑出五类「值得标」的事件。

背景
----
`src/charts.py` 现在把每张图的每个数值点都标满，读者看不出重点。要做的是先算
「哪几个点重要」，再只标那几个。本模块只管**前半截**：给定多期计数，返回事件
列表（期次 + 下标 + 值 + 一句短语），画图由别人接线。

纯函数：不读文件、不写文件、不看时间、不用随机数、不看字典插入顺序（所有遍历
都先 `sorted`）。同一输入必得同一输出。

判据（五类，只看相邻点，不拟合、不预测、不算相关系数）
------------------------------------------------------
1. **enter**：`sets[校]` 里某学科本期在、上期不在。同一校同一期合并成**一条**，
   `text` 形如「新进 2 个学科：微生物学、地球科学」，最多列 2 个，多的用「等」。
   `sets=None` 不出这类；某期在 `sets[校]` 里缺键＝**无数据**，跳过（不猜）。
2. **exit**：反向（上期在、本期不在），合并规则同上，动词换成「退出」。
3. **overtake**：两条序列在同一期交叉——上期 A > B 且本期 A <= B（或反向）。
   一律以**被追上的那方**填 `school`（它才是图上要标「被追平」的那条线），
   `value` 取它的本期值。判据要求上期**严格**领先，所以「追平后连续并列」
   只报第一期，不会每期刷一条。
4. **flat**：尾部连续 ≥3 期相等的那一段，只报**末段**——中间的旧平台不报
   （它已经被后面的走势取代，标在图上只是噪声）。
5. **inflect**：相邻两步异号，且两段步长绝对值都 ≥1（0 与 ±0.5 这类不构成拐点）。
   事件记在**掉头后的那一期**（不是极值期），极值期放 `meta.peak_index`。
   因此「涨到顶后走平」属 flat 不属 inflect——步长为 0 不算变号，这是有意的：
   平稳期的末日不是拐点，平台的末段才是可以标的东西。

出错不炸
--------
本模块是报告流程里的辅助步骤，输入坏了不能把整份报告带崩。期次与计数长度
不一致、结构不对、期次重复，一律**返回空列表**并把原因放进返回值的 `meta`
（`Events` 是 `list` 子类，`== []` 成立，多挂一个 `meta` 属性）：

```python
res = detect(periods, counts)
if res.meta.get("error"):
    ...  # 图上不标事件，照常出图
```

`text` 长度
-----------
四类（overtake / flat / inflect / exit 之外的三类与 exit 的常规形）控制在 10 字
以内；**enter / exit 因要列举学科会超**（题面示例本身 15 字），只保证最多
2 个学科 + 「等」。
"""
from __future__ import annotations

import pathlib
import sys

try:                                     # 仓库惯例：pytest 的 pythonpath 已含 src
    from discipline_list import cn_of
except ImportError:                      # 作为包被导入或独立跑脚本时兜底
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from discipline_list import cn_of

#: 事件排序用：同一 index 上先标「结构变化」，再标「走势变化」。
KIND_ORDER: dict[str, int] = {"enter": 0, "exit": 1, "overtake": 2, "flat": 3, "inflect": 4}

#: 持平判定：连续多少期相等才算「平」。
FLAT_MIN = 3


class Events(list):
    """事件列表（`list[dict]` 的子类），额外挂 `meta` 说明本次调用的问题。

    正常时与普通 list 无异；输入坏时为空且 `meta["error"]` 有中文原因。
    """

    def __init__(self, items=(), meta: dict | None = None) -> None:
        super().__init__(items)
        self.meta: dict = dict(meta or {})


def detect(
    periods: list[str],
    counts: dict[str, list[int]],
    sets: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict]:
    """挑出值得标注的事件，按 `index` 升序返回（判据见模块 docstring）。

    参数
    ----
    periods：期次，从旧到新，形如 `["202511", ..., "202609"]`。
    counts：`{校名: 每期计数}`，每个列表与外层 `periods` 等长。
    sets：`{校名: {期次: [学科英文名]}}`，可为 None（则不出 enter / exit）。
        某校某期缺键＝该期无数据，涉及的相邻两期都不出 enter / exit。

    返回
    ----
    事件字典列表，每条形如::

        {"kind": "overtake", "school": "昆明理工大学", "period": "202609",
         "index": 5, "value": 12, "text": "6 期追平昆明理工",
         "meta": {"with": "海南大学", "gap": 0, ...}}

    输入不合法时返回空列表，原因在 `res.meta["error"]`（不抛异常）。
    """
    error = _validate(periods, counts, sets)
    if error:
        return Events([], {"error": error})
    if len(periods) < 2:                                 # 单期：没有相邻点可比
        return Events([])

    # 保持原值类型（int 还是 int，图注/JSON 里不冒 12.0）
    series = {s: list(counts[s]) for s in sorted(counts)}
    events: list[dict] = []
    events += _enter_exit(periods, series, sets)
    events += _overtakes(periods, series)
    events += _flats(periods, series)
    events += _inflects(periods, series)
    events.sort(key=lambda e: (e["index"], KIND_ORDER[e["kind"]], e["school"], e["text"]))
    return Events(events)


# --------------------------------------------------------------------- 校验


def _validate(periods, counts, sets) -> str:
    """查结构，返回中文错误说明；空串表示可用。只查不改。"""
    if not isinstance(periods, (list, tuple)):
        return "periods 必须是列表"
    if any(not isinstance(p, str) for p in periods):
        return "periods 里必须全是字符串期次"
    if len(set(periods)) != len(periods):
        return "periods 有重复期次——「上期」会指回自己"
    if not isinstance(counts, dict):
        return "counts 必须是字典"
    if any(not isinstance(k, str) for k in counts):
        return "counts 的键（校名）必须是字符串"
    for school in sorted(counts):
        row = counts[school]
        if not isinstance(row, (list, tuple)):
            return f"{school} 的计数不是列表"
        if len(row) != len(periods):
            return f"{school} 有 {len(row)} 期，periods 有 {len(periods)} 期"
        for v in row:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return f"{school} 的计数里有非数值：{v!r}"
    if sets is None:
        return ""
    if not isinstance(sets, dict):
        return "sets 必须是字典"
    if any(not isinstance(k, str) for k in sets):
        return "sets 的键（校名）必须是字符串"
    for school in sorted(sets):
        per = sets[school]
        if not isinstance(per, dict):
            return f"{school} 的 sets 不是 {{期次: [学科]}} 字典"
        for key in sorted(per, key=str):
            if not isinstance(per[key], (list, tuple)):
                return f"{school} {key} 的学科不是列表"
    return ""


# --------------------------------------------------------------------- 文本


def _short(name: str) -> str:
    """图注里的短校名：去掉「大学/学院/学校」后缀，其余原样（不猜简称）。"""
    for suffix in ("大学", "学院", "学校"):
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            return name[: -len(suffix)]
    return name


def _cn_key(stem: str) -> tuple[str, str]:
    """学科排序键：先中文名，再英文原名（同名也不乱）。"""
    return (cn_of(stem), stem)


def _label(verb: str, stems: list[str]) -> str:
    """「新进 2 个学科：微生物学、地球科学」——最多列 2 个，多的用「等」。"""
    shown = "、".join(cn_of(s) for s in stems[:2])
    if len(stems) > 2:
        shown += "等"
    return f"{verb} {len(stems)} 个学科：{shown}"


# --------------------------------------------------------------------- 五类


def _enter_exit(periods: list[str], series: dict, sets) -> list[dict]:
    """enter / exit：本期学科集合相对上期的增减，同一校同一期合并成一条。"""
    if not sets:
        return []
    out: list[dict] = []
    for school in sorted(sets):
        if school not in series:                        # 没有计数就没有 value，不猜
            continue
        per = sets[school]
        for i in range(1, len(periods)):
            prev = per.get(periods[i - 1])
            cur = per.get(periods[i])
            if prev is None or cur is None:              # 缺期＝无数据，不出事件
                continue
            before, now = set(prev), set(cur)
            for kind, verb, diff in (("enter", "新进", now - before),
                                     ("exit", "退出", before - now)):
                if not diff:
                    continue
                stems = sorted(diff, key=_cn_key)
                out.append({
                    "kind": kind,
                    "school": school,
                    "period": periods[i],
                    "index": i,
                    "value": series[school][i],
                    "text": _label(verb, stems),
                    "meta": {
                        "disciplines": [cn_of(s) for s in stems],
                        "stems": stems,
                        "prev_period": periods[i - 1],
                        "prev_count": len(before),
                        "count": len(now),
                    },
                })
    return out


def _overtakes(periods: list[str], series: dict) -> list[dict]:
    """overtake：两条序列在同一期交叉，school 填被追上的那方（只认严格领先→不领先）。"""
    names = sorted(series)
    out: list[dict] = []
    for ai, a in enumerate(names):
        for b in names[ai + 1:]:
            sa, sb = series[a], series[b]
            for i in range(1, len(periods)):
                a0, a1, b0, b1 = sa[i - 1], sa[i], sb[i - 1], sb[i]
                if a0 > b0 and a1 <= b1:                 # a 领先 → 被追平/反超
                    loser, winner, l0, l1, w0, w1 = a, b, a0, a1, b0, b1
                elif b0 > a0 and b1 <= a1:
                    loser, winner, l0, l1, w0, w1 = b, a, b0, b1, a0, a1
                else:
                    continue
                gap = w1 - l1
                head = f"{i + 1} 期追平{_short(loser)}" if gap == 0 \
                    else f"{i + 1} 期反超{_short(loser)}"
                out.append({
                    "kind": "overtake",
                    "school": loser,
                    "period": periods[i],
                    "index": i,
                    "value": l1,
                    "text": head,
                    "meta": {
                        "with": winner,
                        "loser_prev": l0,
                        "winner_prev": w0,
                        "loser_now": l1,
                        "winner_now": w1,
                        "gap": gap,
                    },
                })
    return out


def _flats(periods: list[str], series: dict) -> list[dict]:
    """flat：尾部连续 ≥3 期相等，只报末段（中间平台不报）。"""
    out: list[dict] = []
    for school in sorted(series):
        v = series[school]
        j = len(v) - 1
        while j > 0 and v[j - 1] == v[j]:                # 往回找末段的起点
            j -= 1
        run = len(v) - j
        if run < FLAT_MIN:
            continue
        out.append({
            "kind": "flat",
            "school": school,
            "period": periods[-1],
            "index": len(v) - 1,
            "value": v[-1],
            "text": f"连续 {run} 期持平",
            "meta": {"run_len": run, "run_start": j, "start_period": periods[j]},
        })
    return out


def _inflects(periods: list[str], series: dict) -> list[dict]:
    """inflect：相邻两步异号且 |步长| 都 ≥1，记在掉头后的那一期。"""
    out: list[dict] = []
    for school in sorted(series):
        v = series[school]
        for k in range(2, len(v)):
            prev_step = v[k - 1] - v[k - 2]
            step = v[k] - v[k - 1]
            if abs(prev_step) < 1 or abs(step) < 1:      # 平稳 / 微小抖动不算拐点
                continue
            if (prev_step > 0) == (step > 0):            # 同向＝延续，不是拐点
                continue
            out.append({
                "kind": "inflect",
                "school": school,
                "period": periods[k],
                "index": k,
                "value": v[k],
                "text": f"{k + 1} 期转跌" if step < 0 else f"{k + 1} 期转涨",
                "meta": {
                    "prev_step": prev_step,
                    "step": step,
                    "peak_index": k - 1,
                    "peak_period": periods[k - 1],
                },
            })
    return out
