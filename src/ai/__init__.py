# -*- coding: utf-8 -*-
"""文衡 AI 层（SPEC v1 定稿）：对外**仅**三个符号。

    run(capability, period, *, payload=None, actor=None) -> Answer
    capabilities(actor=None) -> tuple[CapabilityInfo, ...]
    set_switch(capability, enabled, *, actor=None) -> None   # 唯一写口；仅 admin

- capability ∈ {qa, review, diagnose, brief}（brief / polish 留位）；period 形如 `202607`，
  诊断允许空串（期次未判定）。
- 同步阻塞（FastAPI 侧 `to_thread`）；运行期故障不抛，只对编程错误（未知能力/坏载荷）抛。
- **禁旋钮**：没有 `backend=` / `mode=` / `model=` —— 后端与开关是部署/配置事实。
- 注入边缘（测试/脚本，C4）：`using(**overrides)` 与 `actor(role)`；
  生产装配走默认值（演示站规则锁＝无 key 不构造云适配器，物理上无法外发）。

调用方读 `Answer` 的字段（SPEC §1）：mode / backend / text / rule_text / notice /
sources / receipts / shield / record_id / segments；`Answer.as_dict()` 是 `/api/*` 的 JSON 形状。
"""
from ._core import capabilities, run, set_switch
from ._runtime import actor, using
from ._types import Answer, CapabilityInfo, Receipt, Segment, Shield, Source

__all__ = ["run", "capabilities", "set_switch"]
