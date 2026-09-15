# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 状态机（WH-DOC-03 §6.3；WH-DOC-02 R-13）。

设计文档要求**恰好 10 个状态**。此前 `server/jobs.py` 只用了 4 个终态
（`done` / `warn` / `failed` / `interrupted`），命名也与文档对不上
（`done` ≠ `Completed`）。本模块是**权威定义**，`flow.py` 与演示站都从此处取，
不要在别处再写一份字面量。

不变式（HLD §2 N4 / 架构设计 §4.7）：
  · 状态迁移**只追加**——每次迁移写一行 `state_history.jsonl`，不覆盖历史；
  · 终态集合固定为 {completed, warned, escalated, failed, cancelled}；
  · 终态可重跑，但必须**新建运行**，旧运行档案不动。
"""
from __future__ import annotations

PENDING = "pending"
RUNNING = "running"
RETRYING = "retrying"
STALLED = "stalled"
WAITING_APPROVAL = "waiting_approval"
COMPLETED = "completed"
WARNED = "warned"
ESCALATED = "escalated"
FAILED = "failed"
CANCELLED = "cancelled"

#: 文档要求的 10 个状态（顺序即生命周期顺序）
STATES: tuple[str, ...] = (
    PENDING, RUNNING, RETRYING, STALLED, WAITING_APPROVAL,
    COMPLETED, WARNED, ESCALATED, FAILED, CANCELLED,
)

#: 终态：进入后不再自动迁移（重跑 = 新建运行）
TERMINAL: frozenset[str] = frozenset({COMPLETED, WARNED, ESCALATED, FAILED, CANCELLED})

#: 合法迁移表。键=当前状态，值=可迁移到的状态集合。
TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({RUNNING, CANCELLED, STALLED}),
    RUNNING: frozenset({RETRYING, STALLED, WAITING_APPROVAL,
                        COMPLETED, WARNED, ESCALATED, FAILED, CANCELLED}),
    RETRYING: frozenset({RUNNING, ESCALATED, FAILED, STALLED, CANCELLED}),
    STALLED: frozenset({RUNNING, FAILED, CANCELLED}),
    WAITING_APPROVAL: frozenset({COMPLETED, FAILED, CANCELLED}),
    COMPLETED: frozenset(),
    WARNED: frozenset(),
    ESCALATED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}

#: 中文名（看板与报告用）
LABELS: dict[str, str] = {
    PENDING: "待运行",
    RUNNING: "运行中",
    RETRYING: "自愈重试中",
    STALLED: "停滞",
    WAITING_APPROVAL: "待签单",
    COMPLETED: "已完成",
    WARNED: "完成（有告警）",
    ESCALATED: "已升级（待人工）",
    FAILED: "失败",
    CANCELLED: "已取消",
}


class IllegalTransition(ValueError):
    """非法状态迁移：from→to 不在 TRANSITIONS 里。"""


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, frozenset())


def check_transition(src: str, dst: str) -> None:
    """不合法就抛。编排器每次迁移前必须调用——静默迁移是审计事故。"""
    if src not in STATES:
        raise IllegalTransition(f"未知源状态：{src!r}")
    if dst not in STATES:
        raise IllegalTransition(f"未知目标状态：{dst!r}")
    if not can_transition(src, dst):
        raise IllegalTransition(f"非法迁移：{src} → {dst}")


def is_terminal(status: str) -> bool:
    return status in TERMINAL


# ---------------------------------------------------------------- 旧名兼容
#: 演示站 2026-09-15 之前用的是 `done / warn / failed / interrupted` 这套。
#: `out/_jobs/` 下的历史 `job.json` 里存的还是旧值，读盘时要能认。
#: `interrupted`（服务重启中断）映射到 `failed`——10 态里没有它，
#: 且语义上属"意外终止"而非"主动取消"。
LEGACY: dict[str, str] = {
    "done": COMPLETED,
    "warn": WARNED,
    "failed": FAILED,
    "interrupted": FAILED,
    "running": RUNNING,
    "pending": PENDING,
}


def normalize(status: str) -> str:
    """把历史/别名状态归一为 10 态之一。认不出的原样返回——不静默吞掉。"""
    if not status:
        return status
    return LEGACY.get(status, status)


def label(status: str) -> str:
    """中文显示名。新旧名都能吃。"""
    return LABELS.get(normalize(status), status)
