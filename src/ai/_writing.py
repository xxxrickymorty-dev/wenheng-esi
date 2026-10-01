# -*- coding: utf-8 -*-
"""写作/润色位的部署门禁：开关 × 模型可达，**只在这里判一次**。

- 两个位各有一个部署开关（默认关；演示站不依赖模型）：
  写作位 `WENHENG_FLEX_WRITE`、润色位 `WENHENG_FLEX_POLISH`。
- `model`＝配置里能构造出非规则适配器（不探活、不出网）。
- `available`＝开关开且模型可达。`server` 的按钮状态、`flexible/report` 的
  模式判定、写作/润色位自身的入口检查都走这一条判据——需求方别再各判一份，
  否则会出现「按钮放行、出稿时落 off」这类静默不一致。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_ON = ("1", "on", "true", "yes")
_OFF = ("0", "off", "false", "no")

#: 位 → 环境开关名。加新位先登记在这里。
ENV = {"write": "WENHENG_FLEX_WRITE", "polish": "WENHENG_FLEX_POLISH"}


@dataclass(frozen=True)
class WritingState:
    """一个位的门禁状态：`available`＝enabled and model。"""

    position: str
    enabled: bool
    model: bool

    @property
    def available(self) -> bool:
        return self.enabled and self.model

    def as_dict(self) -> dict:
        """HTTP 形状（契约 #21）：`{enabled, available}`。"""
        return {"enabled": self.enabled, "available": self.available}


def enabled(position: str, default: bool = False) -> bool:
    """部署开关；未设取 `default`（默认关）。"""
    v = os.environ.get(ENV[position], "").strip().lower()
    if v in _ON:
        return True
    if v in _OFF:
        return False
    return default


def model_reachable() -> bool:
    """模型位是否可用：配了云（非规则版）即视为可用；不探活、不出网。"""
    from . import _config                                          # noqa: PLC0415

    return not getattr(_config.build_brain(), "is_rule", True)


def writing_state(position: str = "write", *, default: bool = False) -> WritingState:
    """一个位的完整门禁状态。未知位是编程错误（抛 ValueError）。"""
    if position not in ENV:
        raise ValueError(f"未知写作位：{position!r}（允许：{sorted(ENV)}）")
    return WritingState(position=position, enabled=enabled(position, default),
                        model=model_reachable())
