# -*- coding: utf-8 -*-
"""注入边缘（C4）：actor 哨兵与 `using()` 覆盖。

- 解析序：**显式非 None ＞ contextvar（server 中间件一次绑定）＞ fail-closed `"guest"`**（SPEC §1）。
- `using(**overrides)` 给测试/脚本注入 brain / data_root / records / settings（SPEC §3 C4）；
  生产不用它——生产装配走默认值（演示站规则锁＝装配差异，不是代码分支）。
"""
from __future__ import annotations

import contextlib
import contextvars

#: 角色等级：admin ⊇ operator ⊇ guest；`system` 供流水线内部调用（flow 诊断）。
#: `operator`＝操作员（评委，2026-10-11 角色改两级后接入：可查数据、不可用写作类能力）。
#: `guest` 不再是站点角色，只作**未知角色的 fail-closed 哨兵**（最低权限）。
ROLE_RANK = {"guest": 0, "operator": 1, "admin": 2, "system": 3}
FAIL_CLOSED_ROLE = "guest"

_actor_var: contextvars.ContextVar = contextvars.ContextVar("wenheng_ai_actor", default=None)
_overrides_var: contextvars.ContextVar = contextvars.ContextVar("wenheng_ai_overrides", default=None)


def normalize_role(role) -> str:
    r = str(role) if role is not None else ""
    return r if r in ROLE_RANK else FAIL_CLOSED_ROLE


def resolve_actor(explicit) -> str:
    """显式非 None ＞ contextvar ＞ fail-closed。"""
    if explicit is not None:
        return normalize_role(explicit)
    bound = _actor_var.get()
    if bound is not None:
        return normalize_role(bound)
    return FAIL_CLOSED_ROLE


@contextlib.contextmanager
def actor(role):
    """绑定身份（HTTP 中间件一处；测试可显式用）。"""
    token = _actor_var.set(role)
    try:
        yield
    finally:
        _actor_var.reset(token)


@contextlib.contextmanager
def using(**overrides):
    """测试/脚本注入口：brain / data_root / records / settings / inventory 覆盖
    （可嵌套，内层优先）。

    `inventory` 是 dialog 的盘点替身（callable：期次 → Inventory/dict/None；
    不注入则走 `src/inventory.scan` 真实现）。"""
    merged = dict(_overrides_var.get() or {})
    merged.update(overrides)
    token = _overrides_var.set(merged)
    try:
        yield
    finally:
        _overrides_var.reset(token)


def overrides() -> dict:
    return dict(_overrides_var.get() or {})
