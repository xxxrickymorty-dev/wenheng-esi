# -*- coding: utf-8 -*-
"""qa 构建器（问文衡；SPEC §4 步骤 2 的构建器半边）。

规则版：报告同款句骨架 `sentences.build()` 出段 → 按问句拆词打分排序（命中段排前；
问句为空＝全部段；有问句但无命中＝前 3 段）→ 段文本即规则版正文。

来源登记：问句里的数字 → `question`；事实段里的数字 → 按值匹配 `overview_facts.json`
的具体键（product 指针），匹配不到的（句骨架里算出来的期号等）降到段落级指针。

D2 的接线半边（`/api/analyze` 薄适配、契约字段面、e2e）等 X2 会话停手后接；
`sentences.build` 本体按 D6 收编搬入，届时删旧模块（replace, don't layer）。
"""
from __future__ import annotations

import json
import pathlib

from . import _shield
from ._draft import RuleDraft
from ._types import Source


def _load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _match(texts: dict, question: str) -> dict:
    """问句拆词匹配（与 `/api/analyze` 现状同法）：命中按分数降序，无命中取前 3 段。"""
    if not question:
        return dict(texts)
    q_words = [w for w in question.replace("，", " ").replace("。", " ").replace("？", " ").split()
               if len(w) >= 2]
    scored = {}
    for k, v in texts.items():
        score = sum(1 for w in q_words if w in k or w in v)
        if score > 0:
            scored[k] = (score, v)
    if scored:
        return {k: v for k, (_, v) in sorted(scored.items(), key=lambda x: -x[1][0])}
    return dict(list(texts.items())[:3])


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

    texts = sentences.build(facts, p_cur, p_prev)
    question = str(payload.get("question") or "").strip()
    texts = _match(texts, question)

    # 外发面与编号：问句切词在前，事实段在后；共用一套连续编号。
    section_keys = list(texts.keys())
    chunks = [question] + [texts[k] for k in section_keys]
    protected, mapping = _shield.protect_chunks(chunks)

    frames_chars = len(question)          # 题面（含数字）也占位外发，SPEC §2.1
    task = protected[0]
    if not task:                          # 无问句：给模型一个明确的概述任务
        task = "（未提供具体问题）请依据参考数据概述本期要点。"

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
                sources.append(_source_for(facts_idx, m.group(0), k, section_keys[ci - 1]))
                fact_keys.add(k)
    assert k == len(mapping), "编号与保护映射必须对齐"

    return RuleDraft(
        rule_text="\n\n".join(texts[k] for k in section_keys),
        rule_protected="\n\n".join(protected[1:]),
        mapping=mapping,
        sources=tuple(sources),
        parts=(),
        task=task,
        evidence=tuple(protected[1:]),
        fact_keys=frozenset(fact_keys),
    )
