# -*- coding: utf-8 -*-
"""构建器 → 核心的内部稿（私有，不进对外面）。

每个能力一个构建器：把「规则版正文 + 逐数字来源 + 外发面」备好，交核心统一
过盾、走模型轮、定稿、留痕。构建器自己不做回落、不发包、不落盘。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._types import Source


@dataclass
class Part:
    """一个可独立成段的构建结果；`kinds[i]` 描述 `lines[i]` 的数字来源规则。

    kind 两种形态：
    - `{"src": "fixed", "kind": "product", "pointer": …, "label": …}`：整行数字都
      指向同一来源（清单类文本，如复核红件行）；
    - 其余由能力自己的 `attr(kind, pos, value)` 解析（diagnose 的 failure#/规则库）。
    """

    name: str
    lines: list = field(default_factory=list)
    kinds: list = field(default_factory=list)


def fixed(kind: str, pointer: str, label: str = "", detail: str = "") -> dict:
    """整行数字共用一个来源的 kind。"""
    return {"src": "fixed", "kind": kind, "pointer": pointer, "label": label, "detail": detail}


def assemble_parts(parts, attr=None):
    """parts → (rule_text, rule_protected, mapping, sources)。

    数字编号按整文顺序（与 `_shield.protect` 一致）；每个数字登记一条 Source。
    """
    from . import _shield                                          # noqa: PLC0415

    rule_text = "\n".join(ln for p in parts for ln in p.lines)
    protected, mapping = _shield.protect(rule_text)
    sources = []
    for part in parts:
        for line, kind in zip(part.lines, part.kinds):
            for m in _shield.NUM.finditer(line):
                k = str(len(sources) + 1)
                if kind.get("src") == "fixed":
                    skind, pointer = kind["kind"], kind["pointer"]
                    label, detail = kind.get("label", ""), kind.get("detail", "")
                else:
                    skind, pointer, label, detail = attr(kind, m.start(), m.group(0))
                sources.append(Source(index=int(k), kind=skind, pointer=pointer,
                                      label=label, detail=detail,
                                      value=mapping.get(k, m.group(0))))
    return rule_text, protected, mapping, tuple(sources)


@dataclass(frozen=True)
class RuleDraft:
    """- `rule_protected` 与 `mapping` 编号对齐；模型版用同一张 mapping 还原。
    - `task` / `evidence` 是**外发面**（已占位化）；`rule_protected` 只给 RuleBrain
      （回落终点）用，外发适配器不发它。
    - `fact_keys`：属于「本期事实」的编号（qa/review 越题判定：模型版至少引用 1 条）。
    """

    rule_text: str
    rule_protected: str
    mapping: dict
    sources: tuple[Source, ...]
    parts: tuple = ()
    task: str = ""
    evidence: tuple[str, ...] = ()
    fact_keys: frozenset = field(default_factory=frozenset)
