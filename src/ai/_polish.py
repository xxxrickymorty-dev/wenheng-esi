# -*- coding: utf-8 -*-
"""内部润色位（flexible 语言润色；D6 收编，SPEC「列后露成 polish 能力」）。

- 开关：`WENHENG_FLEX_POLISH`（默认**关**——演示站必须不依赖模型）；
- 无云配置（规则版）时直接原样返回，不探活、不出网；
- 只碰措辞、不碰数字：文本先过盾，候选占位符一个不少一个不多才还原；
- 失败/盾未过/不许动的标记被弄坏 → **原样返回**（润色不是产出步骤：不报错、不降级标记）。
"""
from __future__ import annotations

import logging

from . import _writing

LOG = logging.getLogger(__name__)

ENV_ON = _writing.ENV["polish"]

SYSTEM = (
    "你是中文公文写作助手。任务：在不改变事实含义的前提下，把给定段落润色得更通顺、"
    "更符合中文报告语体。[[n]] 是数字占位标记：必须原样保留、每个恰好出现一次；"
    "严禁新增、删除或改写任何数字与标记；不要添加评论、标题或解释，只输出润色后的整段文字。"
)


def enabled(default: bool = False) -> bool:
    """润色是否开启。默认**关**（演示站必须不依赖模型）。判据在 `_writing`。"""
    return _writing.enabled("polish", default)


def rewrite(text: str, *, keep=("【手工：", "待验证假设")) -> str:
    """润色一段文字；任何失败都返回原文。只给纯叙述段落用。"""
    if not text or not text.strip():
        return text
    if not enabled():
        return text
    from . import _attempt                                         # noqa: PLC0415

    res = _attempt.attempt(text, system=SYSTEM, ability="polish", anchored=True)
    if not res.attempted:
        return text                                                # 规则部署：原文照发
    if res.text is None:
        LOG.warning("润色未生效（%s），原样返回", res.reason)
        return text
    out = res.text
    for tag in keep:
        if tag in text and tag not in out:
            return text
    return out
