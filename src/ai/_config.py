# -*- coding: utf-8 -*-
"""后端与部署配置解析（SPEC §2.5 / PLAN D3）。

- **无 key 不构造云适配器**：不配置 = 进程内规则版，物理上无法外发（演示站默认）。
- `WENHENG_AI_PROFILE=demo`：显式锁规则版（部署事实，即使机器上有 key 也不出网）。
- `WENHENG_AI_BACKEND=openai` 且 base/model/key 齐备 → `OpenAIBrain`。

环境变量（key 只从部署 env 来，不入库）：
    WENHENG_AI_BACKEND=openai
    WENHENG_AI_BASE_URL=https://api.deepseek.com/v1
    WENHENG_AI_MODEL=deepseek-flash
    WENHENG_AI_KEY=sk-…
    WENHENG_AI_TIMEOUT=30          # 单次调用秒数
    WENHENG_AI_MAX_TOKENS=2048     # 输出预算（推理型模型要留出正文余量）
    WENHENG_AI_MAX_CHARS=6000      # 外发字符上限（超过即回落，不发包）
"""
from __future__ import annotations

import logging
import os

from ._brain import OpenAIBrain, RuleBrain

log = logging.getLogger("wenheng.ai")


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _num(name: str, default, cast):
    raw = _env(name)
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        log.warning("ai 配置 %s=%r 不是数字，用默认 %r", name, raw, default)
        return default


def cloud_config() -> dict:
    """当前进程的云端配置（每次调用现读 env —— 部署事实，不是调用参数）。"""
    return {
        "backend": _env("WENHENG_AI_BACKEND", "rule").lower() or "rule",
        "profile": _env("WENHENG_AI_PROFILE").lower(),
        "base_url": _env("WENHENG_AI_BASE_URL"),
        "model": _env("WENHENG_AI_MODEL"),
        "key": _env("WENHENG_AI_KEY"),
        "timeout": _num("WENHENG_AI_TIMEOUT", 30.0, float),
        "max_tokens": _num("WENHENG_AI_MAX_TOKENS", 2048, int),
        "max_egress_chars": _num("WENHENG_AI_MAX_CHARS", 6000, int),
    }


def build_brain():
    """按部署事实装配 Brain。默认与一切不齐备的配置都落到 `RuleBrain`（回落终点）。"""
    cfg = cloud_config()
    if cfg["profile"] == "demo":
        return RuleBrain()                       # 演示站永远 rule（显式锁）
    if cfg["backend"] != "openai":
        return RuleBrain()                       # 默认 / 未配置
    if not (cfg["base_url"] and cfg["model"] and cfg["key"]):
        return RuleBrain()                       # 无 key 不构造云适配器
    return OpenAIBrain(base_url=cfg["base_url"], model=cfg["model"], key=cfg["key"],
                       timeout=cfg["timeout"], max_tokens=cfg["max_tokens"],
                       max_egress_chars=cfg["max_egress_chars"])
