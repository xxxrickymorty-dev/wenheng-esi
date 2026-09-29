# -*- coding: utf-8 -*-
"""文衡 AI 层 · 对外数据形状（SPEC §1 冻结）。

只有数据、没有方法（除 `as_dict()`）；调用方与 `/api/*` 只看这些字段：
徽标吃 `mode` / `backend`，角标吃 `sources`，回执条吃 `receipts`，
「看规则版」吃 `rule_text`，脚注吃 `notice`，运行档案对账吃 `record_id`。
"""
from __future__ import annotations

from dataclasses import dataclass

#: Answer.mode 取值（SPEC §1）：
#:   model      —— 模型版正文
#:   rule       —— 规则版正文（默认态，不是失败）
#:   closed     —— 能力关闭 / 未上线
#:   denied     —— 权限不足
#:   unavailable —— 该期数据不可得 / 构建失败（不构成回落循环）
MODES = ("model", "rule", "closed", "denied", "unavailable")

#: sources 指针四型（SPEC §1 / R-2/R-3）：
#:   ledger_cell —— 台账某一格
#:   product     —— 确定性产物某行/字段
#:   fact        —— 确定性事实（含规则库原文）
#:   failure     —— 失败回执字段（diagnose 用）
SOURCE_KINDS = ("ledger_cell", "product", "fact", "failure")


@dataclass(frozen=True)
class Source:
    """text / rule_text 中第 k 个数字的来源（k 从 1 起）。"""

    index: int
    kind: str
    pointer: str
    label: str = ""
    detail: str = ""
    value: str = ""

    def as_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind, "pointer": self.pointer,
                "label": self.label, "detail": self.detail, "value": self.value}


@dataclass(frozen=True)
class Receipt:
    """工具回执（双面，C2）：
    界面面 `as_dict()` 可带还原值的人话摘要；记录/出网面 `as_record()` 只有 digest。
    """

    tool: str
    label: str
    args_digest: str
    summary: str
    elapsed_ms: int = 0
    ok: bool = True
    refused: bool = False

    def as_dict(self) -> dict:
        return {"tool": self.tool, "label": self.label, "ok": self.ok,
                "summary": self.summary, "elapsed_ms": self.elapsed_ms,
                "args_digest": self.args_digest, "refused": self.refused}

    def as_record(self) -> dict:
        from . import _record                                  # noqa: PLC0415

        return {"tool": self.tool, "label": self.label, "ok": self.ok,
                "args_digest": self.args_digest, "refused": self.refused,
                "elapsed_ms": self.elapsed_ms,
                "summary_digest": _record.digest(self.summary)}


@dataclass(frozen=True)
class Shield:
    """数字盾结果。返回时恒 `passed == checked`（不过则回落，见 SPEC §2.1）。"""

    checked: int = 0
    passed: int = 0

    def as_dict(self) -> dict:
        return {"checked": self.checked, "passed": self.passed}


@dataclass(frozen=True)
class Segment:
    """逐段出处（diagnose 用；part 与 flow.py 尾注判定一一对应）。"""

    part: str
    mode: str
    notice: str = ""

    def as_dict(self) -> dict:
        return {"part": self.part, "mode": self.mode, "notice": self.notice}


@dataclass(frozen=True)
class CapabilityInfo:
    """能力开关行（`capabilities()` 的返回项）。"""

    id: str
    label: str
    stage: str            # ready | planned
    min_role: str
    enabled: bool
    allowed: bool
    notice: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "stage": self.stage,
                "min_role": self.min_role, "enabled": self.enabled,
                "allowed": self.allowed, "notice": self.notice}


@dataclass(frozen=True)
class Answer:
    """一次 `run` 的全部结果（四能力共用一张卡）。

    ⚠ `sources` 与**已发布的 `text`** 按出现次序一一对应（第 k 个数字 ↔ sources[k]）。
    锚定型能力（diagnose）`text` 与 `rule_text` 数字序列相同、一张表两用；
    自由型能力（qa）模型版可能只用相关子集——「看规则版」切换时的来源表
    由票 01/D5 的界面口径定（当前实现见 `_core._used_sources`）。
    """

    mode: str
    backend: str
    text: str = ""
    rule_text: str = ""
    notice: str = ""
    sources: tuple[Source, ...] = ()
    receipts: tuple[Receipt, ...] = ()
    shield: Shield = Shield()
    record_id: str | None = None
    segments: tuple[Segment, ...] = ()

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "backend": self.backend,
            "text": self.text,
            "rule_text": self.rule_text,
            "notice": self.notice,
            "sources": [s.as_dict() for s in self.sources],
            "receipts": [r.as_dict() for r in self.receipts],
            "shield": self.shield.as_dict(),
            "record_id": self.record_id,
            "segments": [s.as_dict() for s in self.segments],
        }
