# -*- coding: utf-8 -*-
"""构建器 → 核心的内部稿（私有，不进对外面）。

每个能力一个构建器：把「规则版正文 + 逐数字来源 + 外发面」备好，交核心统一
过盾、走模型轮、定稿、留痕。构建器自己不做回落、不发包、不落盘。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._numbered import NumberedText


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
    """parts → `(rule_text, NumberedText)`。

    编号与来源注册在同一遍扫描里完成（不变量唯一实现见 `_numbered`）：
    `attr(kind, pos, value)` 解析非 fixed 行的来源，返回 `(kind, pointer, label, detail)`。
    """
    lines = [ln for p in parts for ln in p.lines]
    kinds = [k for p in parts for k in p.kinds]

    def register(ti, pos, value):
        kind = kinds[ti] if ti < len(kinds) else {}
        if kind.get("src") == "fixed":
            return {"kind": kind["kind"], "pointer": kind["pointer"],
                    "label": kind.get("label", ""), "detail": kind.get("detail", ""),
                    "fact": True}
        if attr is None:
            raise ValueError("非 fixed 行缺少来源解析器（attr）")
        skind, pointer, label, detail = attr(kind, pos, value)
        return {"kind": skind, "pointer": pointer, "label": label,
                "detail": detail, "fact": True}

    number = NumberedText.of(lines, register)
    return "\n".join(lines), number


@dataclass(frozen=True)
class RuleDraft:
    """- `number` 是不变量所有者：`mapping / sources / fact_keys` 都由它出。
    - `rule_protected` 是规则的**发布面**：diagnose/review 为整篇保护面；
      qa 只含命中段（模型版用同一张 mapping 还原、RuleBrain 也吃它）。
    - `task` / `evidence` 是**外发面**（已占位化）。
    - `data`：能力专属的**结构化结果**（dialog 的期次/意图槽位；核心不解释它，
      只交给 `Answer.data`）；`record_period`：本次调用改记到哪一期（空＝用调用期次）。
    """

    rule_text: str
    number: NumberedText
    rule_protected: str
    parts: tuple = ()
    task: str = ""
    evidence: tuple[str, ...] = ()
    data: dict | None = None
    record_period: str = ""
    #: 规划摘要（票 04：进留痕——"模型选了哪些查询、规划来自模型还是规则"）。
    plan: dict | None = None
    #: 工具回执（receipts-lite，2026-10-26 fc 审查定）：确定性工具调用的双面凭据
    #: （`Receipt`），只由 dialog 出（内核轮在前、规则轮在后）；其余能力恒空。
    receipts: tuple = ()

    @property
    def mapping(self) -> dict:
        return self.number.mapping

    @property
    def sources(self) -> tuple:
        return self.number.sources

    @property
    def fact_keys(self) -> frozenset:
        return self.number.fact_keys
