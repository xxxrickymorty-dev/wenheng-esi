# -*- coding: utf-8 -*-
"""写作/润色位的部署门禁：开关 × 模型可达，**只在这里判一次**。

- 两个位各有一个部署开关（默认关；演示站不依赖模型）：
  写作位 `WENHENG_FLEX_WRITE`、润色位 `WENHENG_FLEX_POLISH`。
- `model`＝配置里能构造出非规则适配器（不探活、不出网）。
- `available`＝开关开且模型可达。`server` 的按钮状态、`flexible/report` 的
  模式判定、写作/润色位自身的入口检查都走这一条判据——需求方别再各判一份，
  否则会出现「按钮放行、出稿时落 off」这类静默不一致。
- 写作位有**专用模型与预算**（2026-10-14 判断草稿规格）：`WENHENG_FLEX_MODEL`
  （缺省 reasoner 级）+ 超时 180s / 输出 8000——慢写不牵动对话/规划的快模型，
  装配口是 `flex_brain()`（注入优先，只有这里读写作位预算）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_ON = ("1", "on", "true", "yes")
_OFF = ("0", "off", "false", "no")

#: 位 → 环境开关名。加新位先登记在这里。
ENV = {"write": "WENHENG_FLEX_WRITE", "polish": "WENHENG_FLEX_POLISH"}

#: 写作位专用模型变量；未设取 reasoner 级默认（对话/规划仍走 `WENHENG_AI_MODEL` 快模型）。
ENV_MODEL = "WENHENG_FLEX_MODEL"
DEFAULT_MODEL = "deepseek-reasoner"

#: 写作位专用预算：单次调用超时（秒）/ 输出 token 上限；与其它能力的 30s 级预算解耦。
FLEX_TIMEOUT = 180.0
FLEX_MAX_TOKENS = 8000


@dataclass(frozen=True)
class WritingState:
    """一个位的门禁状态：`available`＝enabled and model。"""

    position: str
    enabled: bool
    model: bool

    @property
    def available(self) -> bool:
        return self.enabled and self.model

    def as_dict(self) -> dict:
        """HTTP 形状（契约 #21）：`{enabled, available}`。"""
        return {"enabled": self.enabled, "available": self.available}


def enabled(position: str, default: bool = False) -> bool:
    """部署开关；未设取 `default`（默认关）。"""
    v = os.environ.get(ENV[position], "").strip().lower()
    if v in _ON:
        return True
    if v in _OFF:
        return False
    return default


def model_reachable() -> bool:
    """模型位是否可用：配了云（非规则版）即视为可用；不探活、不出网。"""
    from . import _config                                          # noqa: PLC0415

    return not getattr(_config.build_brain(), "is_rule", True)


def flex_model() -> str:
    """写作位模型名：`WENHENG_FLEX_MODEL` 覆盖，未设取 reasoner 级默认。"""
    return os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL


def flex_brain():
    """写作位专用模型装配：`using(brain=…)` 注入优先，否则云配置 + 写作位模型与预算。

    - 可达面与 `model_reachable` 同源（配了云才有非规则适配器；不探活、不出网）；
    - 未配云 / `profile=demo` / 无 key → `RuleBrain`（写作位不可用，调用方回退安全值）；
    - 与 `_config.build_brain()` 的唯一差别：**只有这里**把模型换成 `flex_model()`、
      预算换成 `FLEX_TIMEOUT / FLEX_MAX_TOKENS`——对话/规划的快模型与既有预算不动。
    """
    from . import _brain, _config, _runtime                        # noqa: PLC0415

    override = _runtime.overrides().get("brain")
    if override is not None:
        return override
    cfg = _config.cloud_config()
    if cfg["profile"] == "demo" or cfg["backend"] != "openai":
        return _brain.RuleBrain()
    if not (cfg["base_url"] and cfg["key"]):
        return _brain.RuleBrain()                                  # 无 key 不构造云适配器
    return _brain.OpenAIBrain(base_url=cfg["base_url"], model=flex_model(),
                              key=cfg["key"], timeout=FLEX_TIMEOUT,
                              max_tokens=FLEX_MAX_TOKENS,
                              max_egress_chars=cfg["max_egress_chars"])


def writing_state(position: str = "write", *, default: bool = False) -> WritingState:
    """一个位的完整门禁状态。未知位是编程错误（抛 ValueError）。"""
    if position not in ENV:
        raise ValueError(f"未知写作位：{position!r}（允许：{sorted(ENV)}）")
    return WritingState(position=position, enabled=enabled(position, default),
                        model=model_reachable())
