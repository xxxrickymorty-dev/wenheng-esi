# -*- coding: utf-8 -*-
"""Brain 端口（唯一接缝，内部）与规则适配器（SPEC §3）。

- 端口判据（D-ports）：只有「跨网络、不受控、且真实适配器 ≥2」的依赖才开端口；
  云模型满足（rule 生产 / openai 生产 / 测试替身），其余依赖（工具/台账/记录）并入内部。
- **回落＝同一端口的另一个适配器**：`RuleBrain` 是默认、演示站与一切回落的终点；
  两条路共享盾、白名单、留痕与标注，机械上不易分叉。
- `OpenAIBrain` 列后（D3，等 key）；Scripted/Failing 只进 tests。
"""
from __future__ import annotations

from dataclasses import dataclass


class BrainError(RuntimeError):
    """模型适配器的**可回落**失败：超时 / 连不上 / 限额 / 协议坏。"""


@dataclass(frozen=True)
class Brief:
    """模块 → 端口。这就是「外发」的全部（最小外发，I5）：静态纪律提示 + 受保护文本
    （数字已变 [[n]] 占位）+ 只读工具规格 + 回执摘要（已占位化）。台账原值与来源映射不出模块。
    """

    ability: str
    system: str
    task: str
    step: int = 1
    max_steps: int = 1
    evidence: tuple[str, ...] = ()
    tools: tuple[dict, ...] = ()

    def egress_texts(self) -> tuple[str, ...]:
        """外发面的全部文本（供预算度量与「零数字」测试）。"""
        import json                                            # noqa: PLC0415

        out = [self.ability, self.system, self.task, *self.evidence]
        if self.tools:
            out.append(json.dumps([dict(t) for t in self.tools], ensure_ascii=False, sort_keys=True))
        return tuple(out)

    def egress_bytes(self) -> int:
        return sum(len(t.encode("utf-8")) for t in self.egress_texts())


@dataclass(frozen=True)
class Turn:
    """端口 → 模块：候选正文（含 [[n]]）或工具调用；二选一。"""

    text: str | None = None
    calls: tuple[dict, ...] = ()
    note: str = ""


class RuleBrain:
    """规则适配器：进程内、确定性、**演示站永远走它**（无 key 物理上无法外发）。

    它不做业务逻辑——只是把构建器已拼好的规则版原文原样交回（回落物先存在，D-ports O3）。
    """

    name = "rule"
    is_rule = True

    def think(self, brief: Brief) -> Turn:                     # noqa: ARG002
        return Turn(text=brief.task)
