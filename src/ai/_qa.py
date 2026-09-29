# -*- coding: utf-8 -*-
"""qa 构建器（问文衡；SPEC §4 步骤 2 的构建器半边）。

规则版：报告同款句骨架 `sentences.build()` 出段 → 问句检索排序（命中段排前；
问句为空＝全部段；无命中＝前 3 段）→ 命中段文本即规则版正文。

三处口径（2026-09-29 修，rick 实问暴露）：
- **检索**：中文 2–4 字滑窗 + 报告别名（热点论文/高被引 → 顶尖论文），
  不再要求问句里带空格（旧版整句无空格＝零命中）；
- **手工槽**：`out/<期次>/manual_inputs.json` 里馆员已填的值回填 `【手工：X】`；
  未填的槽位**整句丢掉**——不把裸占位符端给读者，也不让模型看见；
- **证据**：模型轮看**全量段**（命中段排前），规则版仍只出命中段——
  问「热点论文」这类报告里有、命中算法可能够不着的题，模型也能找到段落作答。

来源登记：问句里的数字 → `question`；事实段里的数字 → 按值匹配 `overview_facts.json`
的具体键（product 指针），匹配不到的（句骨架里算出来的期号等）降到段落级指针。
"""
from __future__ import annotations

import json
import pathlib
import re

from . import _shield
from ._draft import RuleDraft
from ._types import Source

#: 检索词里没有信息量的常见词（切词后过滤）。
_STOP = {"什么", "多少", "几门", "几个", "哪些", "这期", "本期", "请问", "怎么", "如何",
         "情况", "数量", "是多少", "有没有", "云南大学", "我校"}

#: 报告口径别名：题目里的近义说法 → 扩成报告用词（只扩检索词，不改原文）。
_ALIAS = {
    "热点论文": "顶尖论文", "高被引论文": "顶尖论文", "高被引": "顶尖论文", "顶刊": "顶尖论文",
    "百分之一": "前 1%", "前1%": "前 1%", "千分之一": "1‰",
}


def _load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _terms(question: str) -> list:
    """问句 → 检索词：空格词 + 中文 2–4 字滑窗（过滤停用词），并做别名扩展。"""
    q = str(question)
    for src, dst in _ALIAS.items():
        if src in q:
            q = q + " " + dst
    terms = set()
    for w in re.split(r"[，。？、！；：\s]+", q):
        w = w.strip()
        if len(w) < 2 or w in _STOP:
            continue
        terms.add(w)
        for n in (2, 3, 4):
            for i in range(len(w) - n + 1):
                g = w[i:i + n]
                if g not in _STOP:
                    terms.add(g)
    return sorted(terms)


def _match(texts: dict, question: str) -> dict:
    """命中按分数降序（长词权重高）；无命中取前 3 段（与旧版行为一致）。"""
    if not question:
        return dict(texts)
    terms = _terms(question)
    scored = {}
    for k, v in texts.items():
        hay = f"{k}\n{v}"
        score = sum(len(t) for t in terms if t in hay)
        if score > 0:
            scored[k] = score
    if scored:
        return {k: texts[k] for k in sorted(scored, key=lambda x: -scored[x])}
    return dict(list(texts.items())[:3])


def _manual_values(root, period) -> dict:
    """馆员已填的手工槽：`{"<段key>": {字段: 值}}`（文件键形如 `正文/p4::学科数`）。"""
    mi = _load_json(pathlib.Path(root) / str(period) / "manual_inputs.json",
                    default={}) or {}
    out: dict = {}
    for key, item in mi.items():
        if "::" not in str(key):
            continue
        sec, field = str(key).split("::", 1)
        sec = sec.split("/")[-1]
        val = item.get("value") if isinstance(item, dict) else item
        if val not in (None, ""):
            out.setdefault(sec, {})[field] = str(val)
    return out


def _apply_manual(text: str, values: dict) -> str:
    """`【手工：X】` → 已填值；未填的槽位**整句丢掉**（不给读者/模型看裸占位符）。"""
    if "【手工：" not in text:
        return text
    kept = []
    for s in re.split(r"(?<=[。；])", text):
        fields = re.findall(r"【手工：([^】]+)】", s)
        if not fields:
            kept.append(s)
            continue
        if any(f not in values for f in fields):
            continue                                    # 有没填的槽 → 整句不要
        kept.append(re.sub(r"【手工：([^】]+)】", lambda m: values[m.group(1)], s))
    return "".join(kept)


def _fact_index(facts: dict) -> dict:
    """overview_facts.json → {数字串: [键路径, ...]}（按值匹配来源；字符串里的数字也索引）。

    值级指针只在**唯一命中**时使用；多个字段同值（或单字数字）时降段落级——
    宁可粗一点，不可指错（R-3：qa 数字到格后置）。
    """
    idx: dict = {}

    def add(value_str: str, path: str):
        idx.setdefault(value_str, []).append(path)

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, bool) or obj is None:
            return
        elif isinstance(obj, (int, float)):
            for variant in {str(obj), f"{obj:g}", f"{obj:.2f}", f"{obj:.1f}"}:
                add(variant, path)
        elif isinstance(obj, str):
            for m in _shield.NUM.finditer(obj):
                add(m.group(0), path)

    walk(facts, "")
    return idx


def _source_for(facts_idx: dict, num: str, index: int, section_key: str) -> Source:
    paths = facts_idx.get(num) or []
    if len(paths) == 1 and len(num) >= 2:
        path = paths[0]
        return Source(index=index, kind="product",
                      pointer=f"overview_facts.json#{path}",
                      label=f"本期事实 · {path}",
                      detail="overview_facts.json（本期派生事实）", value=num)
    return Source(index=index, kind="product",
                  pointer=f"overview_facts.json#{section_key}",
                  label=f"本期事实 · 段落 {section_key}",
                  detail="数字属于该段正文；未唯一对应到 facts 字段（或由句骨架推导）",
                  value=num)


def build(root, period, payload) -> RuleDraft:
    """期次产物 + 问句 → RuleDraft。产物缺失/坏了 → 抛异常（核心按 unavailable 处理）。"""
    d = pathlib.Path(root) / str(period)
    facts = _load_json(d / "overview_facts.json")
    if not isinstance(facts, dict) or not facts:
        raise FileNotFoundError(f"该期没有可用的 overview_facts.json：{d}")
    meta = _load_json(d / "meta.json", default={}) or {}
    p_cur = str(meta.get("period_current") or period)
    p_prev = str(meta.get("period_prev") or "")
    if not p_prev:
        raise ValueError(f"meta.json 缺 period_prev（无法生成 {period} 对比句）：{d}")

    import sentences                                                # noqa: PLC0415

    values = _manual_values(root, period)
    texts_all = {k: _apply_manual(v, values.get(k, {}))
                 for k, v in sentences.build(facts, p_cur, p_prev).items()}

    question = str(payload.get("question") or "").strip()
    matched = _match(texts_all, question)
    # 证据＝命中段优先 + 其余段（模型可自找）；规则版＝命中段。
    ordered = list(matched) + [k for k in texts_all if k not in matched]
    chunks = [question] + [texts_all[k] for k in ordered]
    protected, mapping = _shield.protect_chunks(chunks)

    task = protected[0]
    if not task:                          # 无问句：给模型一个明确的概述任务
        task = "（未提供具体问题）请依据参考数据概述本期要点。"

    matched_set = set(matched)
    facts_idx = _fact_index(facts)
    sources = []
    fact_keys = set()
    k = 0
    for ci, chunk in enumerate(chunks):
        for m in _shield.NUM.finditer(chunk):
            k += 1
            if ci == 0:
                sources.append(Source(index=k, kind="fact", pointer="question",
                                      label="来自提问", detail="提问中出现的数字",
                                      value=m.group(0)))
            else:
                sources.append(_source_for(facts_idx, m.group(0), k, ordered[ci - 1]))
                fact_keys.add(k)
    assert k == len(mapping), "编号与保护映射必须对齐"

    return RuleDraft(
        rule_text="\n\n".join(texts_all[k] for k in matched),
        rule_protected="\n\n".join(protected[1 + i]
                                   for i, key in enumerate(ordered) if key in matched_set),
        mapping=mapping,
        sources=tuple(sources),
        parts=(),
        task=task,
        evidence=tuple(protected[1:]),
        fact_keys=frozenset(fact_keys),
    )
