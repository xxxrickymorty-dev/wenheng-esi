# -*- coding: utf-8 -*-
"""内部润色位（flexible 语言润色；D6 收编，SPEC「列后露成 polish 能力」）。

- 开关：`WENHENG_FLEX_POLISH`（默认**关**——演示站必须不依赖模型）；
- 无云配置（规则版）时直接原样返回，不探活、不出网；
- 只碰措辞、不碰数字：文本先过盾，候选占位符一个不少一个不多才还原；
- 失败/盾未过/不许动的标记被弄坏 → **原样返回**（润色不是产出步骤：不报错、不降级标记）。
"""
from __future__ import annotations

import logging
import os

LOG = logging.getLogger(__name__)

ENV_ON = "WENHENG_FLEX_POLISH"

SYSTEM = (
    "你是中文公文写作助手。任务：在不改变事实含义的前提下，把给定段落润色得更通顺、"
    "更符合中文报告语体。[[n]] 是数字占位标记：必须原样保留、每个恰好出现一次；"
    "严禁新增、删除或改写任何数字与标记；不要添加评论、标题或解释，只输出润色后的整段文字。"
)


def enabled(default: bool = False) -> bool:
    """润色是否开启。默认**关**（演示站必须不依赖模型）。"""
    v = os.environ.get(ENV_ON, "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    return default


def rewrite(text: str, *, keep=("【手工：", "待验证假设")) -> str:
    """润色一段文字；任何失败都返回原文。只给纯叙述段落用。"""
    if not text or not text.strip():
        return text
    if not enabled():
        return text
    from . import _llm                                             # noqa: PLC0415

    out, info = _llm.think(text, system=SYSTEM, ability="polish", anchored=True)
    if out is None:
        LOG.warning("润色未生效（%s），原样返回", info.get("reason"))
        return text
    for tag in keep:
        if tag in text and tag not in out:
            return text
    return out
