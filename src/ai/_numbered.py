# -*- coding: utf-8 -*-
"""NumberedText：占位编号 ↔ 来源的**唯一 implementation**（红线 SPEC §2.1）。

红线：已发布文本里第 k 个数字 ↔ `sources[k-1]`。此前这条不变量被四份实现各扫
一遍——`_draft` 整文 protect 后再逐行 `NUM.finditer` 靠「顺序一致」隐式对齐、
`_qa` 手写 k 计数器 + 运行期 assert、`_core` 发布后再扫重排、能力各自 kinds 规则。
对齐靠约定，于是 FLOOR 分支「正文无数字、来源照记规则稿全过」无人能测。

本模块把两件事**并成同一遍扫描**：
- `NumberedText.of(texts, register)`：`texts` 是原始各段（问句/规则行/红件行…），
  编号跨段连续（委托 `_shield.numberize`，盾正则唯一一份）；
  `register(段号, 段内位置, 原值)` 返回该数字的来源字段
  `{"kind", "pointer", "label", "detail", "fact"}`——`fact`＝是否本期事实编号。
- `used_by(published_protected)`：按发布占位面里 `[[n]]` 的**出现次序**取来源；
  自由型可用相关子集、可重复引用（重复引用重复登记）。
- `restore / validate / cited_facts` 是 `_shield` 的薄委托。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import _shield
from ._types import Source


@dataclass(frozen=True)
class NumberedText:
    """一段（或数段）被保护文本 + 一条不变量。"""

    texts: tuple[str, ...]                 # 保护后的各段（含 [[n]]）
    mapping: dict                          # k(str) → 原值
    sources: tuple[Source, ...] = ()       # index=k，注册序即编号序
    fact_keys: frozenset = field(default_factory=frozenset)

    @classmethod
    def of(cls, texts, register) -> "NumberedText":
        """编号 + 来源注册同一遍完成。`register(段号, 段内位置, 原值) -> dict`。"""
        pieces, mapping, hits = _shield.numberize(texts)
        sources: list[Source] = []
        facts: set[int] = set()
        for ti, pos, k, value in hits:
            info = register(ti, pos, value) or {}
            if info.get("fact"):
                facts.add(int(k))
            sources.append(Source(index=int(k), kind=str(info.get("kind", "fact")),
                                  pointer=str(info.get("pointer", "")),
                                  label=str(info.get("label", "")),
                                  detail=str(info.get("detail", "")),
                                  value=value))
        return cls(texts=tuple(pieces), mapping=mapping,
                   sources=tuple(sources), fact_keys=frozenset(facts))

    @classmethod
    def append(cls, nt: "NumberedText", texts, register) -> "NumberedText":
        """续接编号（qa 原生工具环，2026-10-28）：新段编号从既有最大 k 续，**长在 nt 上**。

        - `mapping` 就地 update（dict 同一对象——边界在 attempt 期间持着它，执行器
          续号后模型引用新标记才不会被判「未知标记」；`draft.mapping` 引用者自动看到）；
        - `texts / sources / fact_keys` 原地替换（frozen 只锁字段绑定；append 是本
          不变量唯一授权的就地生长口——工具环发生在 attempt 期间，若返回新对象，
          续出的来源就回不到 `draft.number`，发布面「第 k 个数字 ↔ sources[k]」会断）；
          返回 `nt` 本身；
        - `register(ti, pos, value)` 的 ti 从 0 起（只计本次新段，由本方法收口换算）。
        """
        start = max((int(k) for k in nt.mapping), default=0)
        pieces, mapping, hits = _shield.numberize(texts, start=start)
        nt.mapping.update(mapping)
        sources = list(nt.sources)
        facts = set(nt.fact_keys)
        for ti, pos, k, value in hits:
            info = register(ti, pos, value) or {}
            if info.get("fact"):
                facts.add(int(k))
            sources.append(Source(index=int(k), kind=str(info.get("kind", "fact")),
                                  pointer=str(info.get("pointer", "")),
                                  label=str(info.get("label", "")),
                                  detail=str(info.get("detail", "")),
                                  value=value))
        object.__setattr__(nt, "texts", nt.texts + tuple(pieces))
        object.__setattr__(nt, "sources", tuple(sources))
        object.__setattr__(nt, "fact_keys", frozenset(facts))
        return nt

    @property
    def protected(self) -> str:
        """整篇保护面（各段换行相接）——发模型/RuleBrain 用。"""
        return "\n".join(self.texts)

    def restore(self, candidate: str) -> str:
        return _shield.restore(candidate, self.mapping)

    def validate(self, candidate: str | None, *, anchored: bool = True) -> tuple[bool, dict]:
        if anchored:
            return _shield.validate(candidate, self.mapping)
        return _shield.validate_free(candidate, self.mapping)

    def cited_facts(self, candidate: str) -> set:
        """候选里用到的、属于「本期事实」的编号（qa/review 越题判定）。"""
        return {int(k) for k in _shield.MARK.findall(candidate or "")} & set(self.fact_keys)

    def used_by(self, published_protected: str) -> tuple[Source, ...]:
        """发布占位面 → 已用来源（第 k 个 `[[n]]` ↔ 返回元组第 k 项）。"""
        by_index = {s.index: s for s in self.sources}
        out: list[Source] = []
        for i, m in enumerate(_shield.MARK.finditer(published_protected or ""), start=1):
            s = by_index.get(int(m.group(1)))
            if s is None:
                continue
            out.append(Source(index=i, kind=s.kind, pointer=s.pointer, label=s.label,
                              detail=s.detail, value=s.value))
        return tuple(out)
