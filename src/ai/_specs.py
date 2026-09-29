# -*- coding: utf-8 -*-
"""能力注册表（数据；SPEC §1：能力 ∈ {qa, review, diagnose, brief}，polish 留位）。

新增能力＝这里加一行 + 一个构建器；对外接口、调用方、测试面零变化。
`stage`：ready（可用）/ planned（未上线 → `run` 返回 mode=closed 的说明文案）。
`min_role`：路由已放行的门以内的最低角色（模块只收紧，不放松；未登录路由本就不放行）。
`no_data_notice`：该期产物缺失/坏时的兜底人话（unavailable）。
"""
from __future__ import annotations

from dataclasses import dataclass

ABILITY_IDS = ("qa", "review", "diagnose", "brief")


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    stage: str            # ready | planned
    min_role: str
    default_enabled: bool
    payload_fields: tuple  # 必填字段名（None = 不要求 payload）
    no_data_notice: str = ""


CAPABILITIES: tuple[Capability, ...] = (
    Capability("qa", "问文衡", "ready", "admin", True, ("question",),
               "该期数据暂不可用，无法作答。"),
    Capability("review", "复核参谋", "ready", "admin", True, (),
               "该期数据暂不可用，无法给出复核建议。"),
    Capability("diagnose", "诊断参谋", "ready", "admin", True, ("failure",),
               "本次无法给出建议，请人工核对台账与规则库。"),
    Capability("brief", "期次导读", "planned", "admin", False, ()),
)

_BY_ID = {c.id: c for c in CAPABILITIES}

PLANNED_NOTICE = "该功能尚未上线。"
CLOSED_NOTICE = "此功能已由管理员关闭；数据与报告不受影响。"
DENIED_NOTICE = "此功能仅管理员可用。"
UNAVAILABLE_NOTICE = "该期数据暂不可用，无法作答。"


def get(capability: str) -> Capability:
    """未知能力 → ValueError（编程错误；SPEC §2：只有这类抛）。"""
    if capability not in _BY_ID:
        raise ValueError(f"未知能力：{capability!r}，可选：{', '.join(ABILITY_IDS)}")
    return _BY_ID[capability]
