# -*- coding: utf-8 -*-
"""内部模型口（私有）：flexible 规划 / 内部润色等**非能力调用**的唯一出网口。

D6 收编（2026-09-29）：``flexible/planner.py``、``flexible/polish.py`` 原先各自
直连（Ollama / 任意 HTTP）——这里把它们收进同一套「配置 + 数字盾 + 回落」，
「唯一模型出口」才成立。

- 出网一律经 `_config.build_brain()`（无 key/未配置/演示锁 → 规则版，直接返回 None）。
- 发出去的内容先过盾（数字 → `[[n]]`），模型看不见任何数值。
- 候选校验：`anchored=True` 占位符一个不少一个不多（润色/改写）；`anchored=False`
  无游离数字、无未知标记即可（规划 JSON 这类生成物）。
- 失败不抛：返回 `(None, 原因)`，回落由调用方自定（规划回 rule、润色回原文）。
- 不写留痕：非能力调用的轻量口；列后露成正式能力（`polish`）时再接入 `run` 的留痕。
"""
from __future__ import annotations

from . import _brain, _config, _shield


def think(task, *, system: str, ability: str, anchored: bool = True,
          allow_substrings=()):
    """盾保护 → 模型 → 校验 → 还原。返回 `(文本 | None, 说明)`。

    `allow_substrings`：生成型输出里**合法自带数字**的固定词（如图型目录
    `overview_1permille`）——先剥掉再查游离数字，防止误判，不放松其它数字。
    """
    brain = _config.build_brain()
    if getattr(brain, "is_rule", False):
        return None, {"reason": "rule"}
    protected, mapping = _shield.protect(str(task or ""))
    brief = _brain.Brief(ability=ability, system=system, task=protected,
                         rule_protected=protected)
    try:
        turn = brain.think(brief)
    except _brain.BrainError as e:
        return None, {"reason": f"brain_error:{getattr(e, 'code', type(e).__name__)}"}
    except Exception as e:                                     # noqa: BLE001
        return None, {"reason": f"error:{type(e).__name__}"}
    if turn.calls:
        return None, {"reason": "calls_unsupported"}
    candidate = turn.text or ""
    if not candidate.strip():
        return None, {"reason": "empty_reply"}
    if anchored:
        ok, detail = _shield.validate(candidate, mapping)
    else:
        probe = candidate
        for s in allow_substrings:
            probe = probe.replace(s, "")
        ok, detail = _shield.validate_free(probe, mapping)
    if not ok:
        return None, {"reason": "shield_reject", "detail": detail}
    return _shield.restore(candidate, mapping), {"reason": None,
                                                 "backend": getattr(brain, "name", "")}
