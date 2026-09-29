# -*- coding: utf-8 -*-
"""语言润色位 —— 已收编为 AI 层的内部模式（D6，2026-09-29）。

开关、盾、回落都在 `src/ai/_polish.py`；本模块只留**薄钩子**（供
`flexible/report.py` 与测试调用），Ollama 直连已废弃——模型出口统一走
OpenAI 兼容配置（`WENHENG_AI_*`）。

语义不变：润色只碰措辞、不碰数字；不可用/失败/盾未过 → **原样返回**，
不报错、不降级标记（润色不是产出步骤，演示站不依赖模型）。
"""
from __future__ import annotations

_KEEP = ("【手工：", "待验证假设")


def enabled(default: bool = False) -> bool:
    """润色开关（`WENHENG_FLEX_POLISH`，默认关）。"""
    from ai._polish import enabled as _e                            # noqa: PLC0415
    return _e(default)


def model_reachable() -> bool:
    """模型位是否可用：配了云（非规则版）即视为可用；不探活、不出网。"""
    from ai import _config                                          # noqa: PLC0415
    return not getattr(_config.build_brain(), "is_rule", True)


def rewrite(text: str, *, model=None) -> str:                       # noqa: ARG001
    """润色一段文字；任何失败都返回原文。`model` 参数留作签名兼容（已废弃）。"""
    from ai import _polish                                          # noqa: PLC0415
    return _polish.rewrite(text, keep=_KEEP)
