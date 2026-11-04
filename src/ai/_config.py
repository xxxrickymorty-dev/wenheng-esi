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
    WENHENG_AI_MAX_TOKENS=4096     # 输出预算（qa 长答案要留足，避免被截断）
    WENHENG_AI_MAX_CHARS=20000     # 外发字符上限（超过即回落，不发包）；
                                   # qa 全量证据单轮实测约 8K 字符，留 2.5 倍余量；
                                   # 单位是字符不是字节
"""
from __future__ import annotations

import logging
import os

from ._brain import RuleBrain, make_brain

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


def _env_config() -> dict:
    """只读环境变量的那份配置（界面上「服务器部署配置」那一行用的就是它）。"""
    return {
        "backend": _env("WENHENG_AI_BACKEND", "rule").lower() or "rule",
        "profile": _env("WENHENG_AI_PROFILE").lower(),
        "base_url": _env("WENHENG_AI_BASE_URL"),
        "model": _env("WENHENG_AI_MODEL"),
        "key": _env("WENHENG_AI_KEY"),
        # 协议（2026-11-04）：.env 部署配置固定 OpenAI Chat Completions；
        # 清单里的供应商各自带协议（三选，见 _models.PROTOCOLS）
        "protocol": "openai",
        "timeout": _num("WENHENG_AI_TIMEOUT", 30.0, float),
        "max_tokens": _num("WENHENG_AI_MAX_TOKENS", 4096, int),
        "max_egress_chars": _num("WENHENG_AI_MAX_CHARS", 20000, int),
    }


def cloud_config() -> dict:
    """当前生效的云端配置（每次调用现读 —— 部署事实，不是调用参数）。

    两条来源，优先级从高到低：
    1. **运行期模型清单**（`out/_ai/models.json` 的当前项，界面上可切）——
       只补地址/型号/key/自定义头（headers，票 4），超时与预算仍由环境变量定；
    2. **环境变量**（`.env`，运维改）。
    `WENHENG_AI_PROFILE=demo` 仍然一票否决：演示锁规则版时清单不生效（不出网）。
    """
    cfg = _env_config()
    if cfg["profile"] == "demo":
        return cfg
    try:
        from . import _models                                       # noqa: PLC0415

        picked = _models.active_credentials()
    except Exception as e:                                          # noqa: BLE001
        log.warning("模型清单读取异常，按部署配置继续：%s", e)
        picked = None
    if picked:
        cfg.update({"backend": "openai", "base_url": picked["base_url"],
                    "model": picked["model"], "key": picked["key"],
                    "protocol": picked.get("protocol") or "openai",
                    "headers": picked.get("headers") or {},
                    "source": f"清单：{picked['label']}"})
    return cfg


def build_brain():
    """按部署事实装配 Brain。默认与一切不齐备的配置都落到 `RuleBrain`（回落终点）。

    测试/脚本可用 `ai.using(brain=…)` 覆盖（此处显式尊重；模型边界的内部口 `ai._attempt` 也走这里）。
    """
    from . import _runtime                                         # noqa: PLC0415

    override = _runtime.overrides().get("brain")
    if override is not None:
        return override
    cfg = cloud_config()
    if cfg["profile"] == "demo":
        return RuleBrain()                       # 演示站永远 rule（显式锁）
    if cfg["backend"] != "openai":
        return RuleBrain()                       # 默认 / 未配置
    if not (cfg["base_url"] and cfg["model"] and cfg["key"]):
        return RuleBrain()                       # 无 key 不构造云适配器
    return make_brain(base_url=cfg["base_url"], model=cfg["model"], key=cfg["key"],
                      protocol=cfg.get("protocol") or "openai",
                      timeout=cfg["timeout"], max_tokens=cfg["max_tokens"],
                      max_egress_chars=cfg["max_egress_chars"],
                      extra_headers=cfg.get("headers") or None)
