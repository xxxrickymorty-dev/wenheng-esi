# -*- coding: utf-8 -*-
"""AI 层测试替身与断言小工具（SPEC §3：Scripted / Failing 只进 tests，不进生产包）。"""
from __future__ import annotations

import re

from ai._brain import BrainError, Turn

__all__ = ["BrainError", "FailingBrain", "ScriptedBrain", "Turn", "brief_texts", "raw_digits"]

_MARK = re.compile(r"\[\[\d+\]\]")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def raw_digits(text: str) -> list:
    """去掉 [[n]] 占位标记后仍可见的数字串（零值外发测试用）。"""
    return _NUM.findall(_MARK.sub("", text or ""))


class ScriptedBrain:
    """按脚本回放 Turn；可选 callable（拿到 Brief 现算），并捕获每次 Brief。

    `is_rule=False` —— 走「模型轮」路径；文本合规则 mode=model，不合规则回落。
    """

    def __init__(self, turns=None, *, name="scripted"):
        self.name = name
        self.is_rule = False
        self.turns = list(turns or [])
        self.briefs = []

    def think(self, brief):
        self.briefs.append(brief)
        if not self.turns:
            return Turn(text=None)
        t = self.turns.pop(0)
        if isinstance(t, BaseException):
            raise t
        if callable(t):
            t = t(brief)
        return t


class FailingBrain:
    """永远抛 `BrainError`，专门验回落链。"""

    name = "failing"
    is_rule = False

    def __init__(self, exc=None):
        self.exc = exc or BrainError("超时")

    def think(self, brief):                                    # noqa: ARG002
        raise self.exc


def brief_texts(brief) -> tuple:
    return brief.egress_texts()
