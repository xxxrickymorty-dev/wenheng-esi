# -*- coding: utf-8 -*-
"""本期任务视图（票 06）：第一屏「我现在该做什么」的三步状态。

**事实在 `period_facts`，这里只做形状 adapter。** 三步（取数 → 核对并并入 →
一键生成）的判据、期次选择、顺延规则都属于 `period_facts`；对话首屏的 JSON
形状（steps/ stuck / prev）留在这里，避免把 UI 契约塞进事实 module。
"""
from __future__ import annotations

import period_facts

#: 仓库根（wenheng/）；兼容旧导入。
REPO_ROOT = period_facts.REPO_ROOT

#: 三步（顺序即展示顺序；键是稳定标识）。
STEPS = period_facts.STEPS

#: 下一期 / 上一期：双月序列，旧导入继续可用。
next_period = period_facts.next_period
prev_period = period_facts.prev_period
known_periods = period_facts.known_periods


def scan(*, repo_root=None, filled=None, status=None) -> dict | None:
    """本期任务扫描：`period_facts.current` 的 JSON 形状。

    没有任何期次痕迹 → None（界面退回普通问候，不编）；签发状态由 server
    经 `status=` 注入，本模块不 import server。
    """
    f = period_facts.current(repo_root=repo_root, filled=filled, status=status)
    return f.as_home() if f is not None else None
