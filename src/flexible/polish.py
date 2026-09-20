# -*- coding: utf-8 -*-
"""语言润色位（**可选**）—— 让灵活报告的措辞不那么像模板。

🔴 为什么它安全（这是本模块存在的唯一理由）：

- 润色**只碰措辞，不碰数字**。数字在送进模型前被换成 `[[n]]` 占位符，
  回来后**校验占位符一个不少、且没有冒出新数字**，才还原；否则整段**原样退回**。
  这就是 `src/local_llm.py` 里已经有的 `protect / validate / restore` 三件套 ——
  复用它，不另写一套。
- 润色**不是产出步骤**：不可用、超时、校验失败 → 一律返回原文，不报错、不降级标记。
  演示站（2核2G，无模型）永远走这条，产出的仍是规则稿。
- 润色**不碰**：表格、`【手工：…】` 空位、待验证假设的「来源」标注、来源链附录。

rick 2026-09-21：「灵活报告并不灵活，语言还是很死板」——
死板的**主因**在句式（已由 `opinion.descriptive_trend` 按数据形态分档解决，无模型也生效）；
本模块是**加分项**：模型在位时把规则稿的说法再顺一遍。
"""
from __future__ import annotations

import logging
import os

LOG = logging.getLogger(__name__)

#: 环境变量开关（演示站不设 → 永远关闭润色）
ENV_ON = "WENHENG_FLEX_POLISH"


def enabled(default: bool = False) -> bool:
    """润色是否开启。默认**关**（演示站必须不依赖模型）。"""
    v = os.environ.get(ENV_ON, "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    return default


def model_reachable() -> bool:
    """本机 Ollama 是否可用（不可用 → 润色静默跳过）。"""
    try:
        import local_llm                                        # noqa: PLC0415
        return bool(local_llm.check()[0])
    except Exception:                                           # noqa: BLE001
        return False


def rewrite(text: str, *, model=None) -> str:
    """润色一段文字。**任何异常都返回原文**，绝不把模型输出直接端上桌。

    只给纯叙述段落用；表格、含 `【手工：` 的段、假设标注段不要传进来。
    """
    if not text or not text.strip():
        return text
    if not enabled():
        return text
    try:
        import local_llm                                        # noqa: PLC0415
        out, info = local_llm.polish(text, model=model or local_llm.DEFAULT_MODEL)
    except Exception as e:                                      # noqa: BLE001
        LOG.warning("润色失败，原样返回：%s", e)
        return text
    if info.get("mode") != "polished":
        LOG.warning("润色未生效（%s），原样返回", info.get("reason"))
        return text
    # 双保险：模型若把占位符弄丢或新增了数字，local_llm 已经校验过；
    # 这里再确认一次「没把我们不许动的标记弄坏」。
    for keep in ("【手工：", "待验证假设"):
        if keep in text and keep not in out:
            return text
    return out
