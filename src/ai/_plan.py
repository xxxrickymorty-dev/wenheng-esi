# -*- coding: utf-8 -*-
"""取数规划器（票 02 规则路径 + 票 03 模型路径）——问句 → QueryPlan（引擎白名单规格）。

口径（红线落点）：规划器的输出**只有名字**（指标/学科/形状），没有任何数值；
**期次不进规划**（窗口由编排口确定性给定；"最近六期"= 视图期次轴的最后六列，
与 _qa v1 台账段同口径）。

策略（v1，2026-10-12 定）：**规则先算**——规则给出规格时直接用（模型不参与：
省一次调用、行为稳定）；规则为空时才问模型（若配了真模型）：合法 JSON 才用，
否则回落规则。演示站规则锁（`WENHENG_AI_PROFILE=demo`）下模型路径不触发——
**无模型也能跑**。

模型面（票 03）：
- 经 `_attempt` 统一边界（盾保护 + 校验 + 回落语义；先例 `flexible/planner.py`）；
- **规划面词汇零数字**：模型只认无数字别名（`proximity` → `proximity_1pct`…），
  别名表在 `MODEL_METRICS` 一处维护——防盾占位往返的碎边界；
- 越权键 / 未知 op / 带数字 → **整份回退**规则；非法值项（未知别名/学科）丢弃；
- 问句与上文都不指向任何学科时不猜学科（提示词写明，校验按白名单收口）。

规则（与 _qa v1 的台账段口径一一对应，2026-10-11 rick 定）：

- 点到学科 + 点到指标 → 该科该指标的近六期序列（每科一条 `series`）；
- 点到学科 + 问「进入/退出/入榜/进榜」→ 进出前 1% 事件（`events`）；
- 没点学科、点到排名指标、问到云大/我校/学校 → 云大整体排名序列（`overall_rank`）。

few-shot 例子库（票 04）：`plan_examples.json`（问句 → 规格对，规划面词汇）；
起步全量/关键词检索，不引向量库（加缝须等第二个检索器出现）。
"""
from __future__ import annotations

import json
import pathlib

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


# ================================================================ 模型面（票 03）

#: 规划面词汇：**无数字别名** → 引擎规范名（模型面零数字；规则面直接用规范名）。
MODEL_METRICS = (
    ("proximity", "proximity_1pct", "接近度"),
    ("threshold", "threshold_1pct", "前 1% 被引阈值"),
    ("threshold_permille", "threshold_1permille", "前 1‰ 被引阈值"),
    ("total_cites", "total_cites", "总被引频次"),
    ("papers", "papers", "论文数"),
    ("cnci", "cnci", "CNCI"),
    ("top_papers", "top_papers", "顶尖论文"),
    ("rank_cn", "rank_cn", "国内排名"),
    ("rank_intl", "rank_intl", "国际排名"),
)

#: 别名 → 规范名。
_ALIAS = {alias: canon for alias, canon, _cn in MODEL_METRICS}

#: 模型输出的键白名单（多一个键＝越权，整份回退）。
_ALLOWED_TOP_KEYS = frozenset({"specs"})
_ALLOWED_SPEC_KEYS = frozenset({"op", "metric", "disc", "span"})

_PLAN_SYSTEM = (
    "你是文衡（图书馆双月报告系统）的**取数规划器**。"
    "你只把问题翻译成对台账的查询规格：不回答、不解释、不计算。"
    "所有数字都已替换为 [[n]] 占位标记：不要新增、删除或改写任何数字与标记。"
    "只输出一个 JSON 对象，形如 {\"specs\": [...]}；每个规格只允许键 "
    "op / metric / disc / span。op 仅允许 series / events / overall_rank；"
    "metric 只能从「可选指标」里选；disc 只能从「可选学科」里选；span 为 recent 或 all。"
    "只有问题或对话上文明确指向某学科时才给该学科的规格；拿不准就不给。"
)


def _parse_json(raw):
    """从模型输出里取出第一个 JSON 对象（照 flexible/planner 先例：去围栏）。"""
    if not raw:
        return None
    s = str(raw).strip().replace("```json", "```")
    if "```" in s:
        parts = s.split("```")
        if len(parts) >= 3:
            s = parts[1]
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        got = json.loads(s[i:j + 1])
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def _clean_specs(got, discs_ok):
    """模型规格清洗。

    越权键 / 未知 op / 顶层多余键 → `None`（整份回退）；非法值项（未知别名、名单外学科）
    丢弃；没有可用项 → `[]`（调用方回落规则）。
    """
    if not isinstance(got, dict) or set(got) - _ALLOWED_TOP_KEYS:
        return None
    raw = got.get("specs")
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - _ALLOWED_SPEC_KEYS:
            return None
        op = item.get("op")
        if op == "series":
            metric = _ALIAS.get(str(item.get("metric") or ""))
            disc = str(item.get("disc") or "")
            if not metric or disc not in discs_ok:
                continue
            span = "all" if item.get("span") == "all" else "recent"
            out.append({"op": "series", "metric": metric, "disc": disc, "span": span})
        elif op == "events":
            disc = str(item.get("disc") or "")
            if disc in discs_ok:
                out.append({"op": "events", "disc": disc})
        elif op == "overall_rank":
            out.append({"op": "overall_rank", "span": "recent"})
        else:
            return None                                    # 未登记的 op：整份回退
    return out


def _model_prompt(question, *, discs, disciplines, history):
    """发给模型的规划提示。**不含任何数值原值**（出网前还会统一过盾）。"""
    hist = []
    for item in (history or [])[-4:]:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("text") or "").strip()[:120]
        if snippet:
            hist.append(("用户" if item.get("who") == "me" else "文衡") + "：" + snippet)
    payload = {
        "问题": str(question or ""),
        "对话上文": hist or "（无）",
        "可选指标": {alias: cn for alias, _canon, cn in MODEL_METRICS},
        "可选学科": [str(d) for d in disciplines] or "（无名单）",
        "问句点到的学科": [str(d) for d in discs] or "（无）",
        "示例": [{"问": e["q"], "上文": e.get("history", []), "规格": e["specs"]}
                 for e in retrieve_examples(question)],
    }
    return ("把下面的问题翻译成查询规格（只输出 JSON）：\n"
            + json.dumps(payload, ensure_ascii=False, indent=1))


def _model_plan(question, *, discs, disciplines, history):
    """模型规划轮。经 `_attempt` 统一边界（盾保护 + 校验 + 回落语义）。

    返回 `(got | None, reason)`；规则部署（未配模型）→ `(None, "")`。
    """
    from . import _attempt                                 # noqa: PLC0415

    prompt = _model_prompt(question, discs=discs, disciplines=disciplines,
                           history=history)
    res = _attempt.attempt(prompt, system=_PLAN_SYSTEM, ability="qa-plan", anchored=False)
    if not res.attempted:
        return None, ""
    if res.text is None:
        return None, str(res.reason or "empty_reply")
    got = _parse_json(res.text)
    if got is None:
        return None, "bad_json"
    return got, ""


def plan(question, *, discs=(), history=(), disciplines=()) -> dict:
    """问句 → QueryPlan（规则先算；规则为空才问模型——v1 策略）。"""
    rule = {"specs": rule_specs(question, discs), "origin": "rule", "note": ""}
    if rule["specs"] or not str(question or "").strip():
        return rule
    got, reason = _model_plan(question, discs=discs, disciplines=disciplines,
                              history=history)
    if got is None:
        return {**rule, "note": reason}
    specs = _clean_specs(got, {str(d) for d in disciplines})
    if not specs:
        return rule
    return {"specs": specs, "origin": "model", "note": ""}


# ================================================================ 例子库（票 04）

#: 例子库文件（问句 → 规格对；规划面词汇，零数字）。
EXAMPLES_PATH = pathlib.Path(__file__).with_name("plan_examples.json")


def load_examples() -> list:
    """例子库。文件缺/坏 → `[]`（模型面退化为无例子，仍可用）。"""
    try:
        raw = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in raw if isinstance(e, dict) and e.get("q") and e.get("specs")]


def _terms(text: str) -> list:
    """检索词：中文 2–4 字滑窗（与 _qa 检索同思路，独立实现——不跨能力口借函数）。"""
    q = str(text or "")
    terms = set()
    for n in (2, 3, 4):
        for i in range(len(q) - n + 1):
            terms.add(q[i:i + n])
    return sorted(terms)


def retrieve_examples(question: str, k: int = 4) -> list:
    """关键词重叠检索（起步：库里 ≤k 条就全给；不引向量库）。"""
    lib = load_examples()
    if len(lib) <= k:
        return lib
    terms = _terms(question)
    scored = [(sum(len(t) for t in terms if t in str(e["q"])), i, e)
              for i, e in enumerate(lib)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = [e for s, _i, e in scored[:k] if s > 0]
    return top or lib[:k]
