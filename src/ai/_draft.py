# -*- coding: utf-8 -*-
"""构建器 → 核心的内部稿（私有，不进对外面）。

每个能力一个构建器：把「规则版正文 + 逐数字来源 + 外发面」备好，交核心统一
过盾、走模型轮、定稿、留痕。构建器自己不做回落、不发包、不落盘。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._types import Source


@dataclass(frozen=True)
class RuleDraft:
    """- `rule_protected` 与 `mapping` 编号对齐；模型版用同一张 mapping 还原。
    - `task` / `evidence` 是**外发面**（已占位化）；`rule_protected` 只给 RuleBrain
      （回落终点）用，外发适配器不发它。
    - `fact_keys`：属于「本期事实」的编号（qa 越题判定：模型版至少引用 1 条）。
    """

    rule_text: str
    rule_protected: str
    mapping: dict
    sources: tuple[Source, ...]
    parts: tuple = ()
    task: str = ""
    evidence: tuple[str, ...] = ()
    fact_keys: frozenset = field(default_factory=frozenset)
