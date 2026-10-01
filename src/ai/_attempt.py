# -*- coding: utf-8 -*-
"""模型调用边界（私有）：盾保护 → 端口 → 校验 → 还原/回落。

能力口、内部口、写作位、规划器共用这一处语义：回落码、`mode` 口径、egress 口径
只有这份实现。边界**不写留痕**——记录面是调用方的政策（记什么文本、失败是否降级），
写口归 `_record.Recorder`。

约定：
- `mapping` 传入 → `task` 视为调用方已保护面（能力口，编号以调用方为准）；
  不传 → 边界自行对 `task` 过盾（写作位 / 规划器）。
- `rule_protected` 缺省 → 用保护后的 task：规则适配器原样交回，仍走「回落＝
  同一端口的另一个适配器」（SPEC §3）。
- `attempted=False`（规则部署）不算失败：`reason=None`、`text`＝规则物；
  只有真实模型的失败才带回落码。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from . import _brain, _config, _shield


class FallbackReason(StrEnum):
    """回落原因码。字面值是记录/界面契约（`AiRecords` 按它出中文），不许改。"""

    CALLS_UNSUPPORTED = "calls_unsupported"
    EMPTY_REPLY = "empty_reply"
    SHIELD_REJECT = "shield_reject"
    #: 政策级：由调用方写入记录，边界不产生。
    OFF_TOPIC = "off_topic"
    KEEP_BROKEN = "keep_broken"
    GUARD_REJECT = "guard_reject"
    RECORD_FAILED = "record_failed"


def brain_error(code) -> str:
    """动态回落码：`brain_error:<code>`（code＝BrainError.code 或异常类名）。"""
    return f"brain_error:{code}"


@dataclass(frozen=True)
class Outcome:
    """一次模型尝试的定型结果（边界 → 调用方）。

    - `text`＝可用文本（模型候选已还原 / 规则部署的规则物；失败为 None）；
    - `candidate_protected`＝通过校验的占位面候选（`_used_sources` 按它排来源）；
    - `attempted`＝配置了真实模型（False＝规则部署，不是失败）；
    - `shield`＝本次尝试的校验计数（失败 passed=0，明细在 `detail`）。
    """

    text: str | None = None
    candidate_protected: str = ""
    attempted: bool = False
    backend: str = "rule"
    reason: str | None = None
    detail: dict | None = None
    protected: str = ""
    shield: dict = field(default_factory=dict)
    egress: dict = field(default_factory=dict)
    notice: str = ""
    elapsed_ms: int = 0


def _reason_text(e) -> str:
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:80]


def attempt(task, *, system: str, ability: str, anchored: bool = True, evidence=(),
            tools=(), rule_protected: str | None = None, mapping: dict | None = None,
            allow_substrings=()) -> Outcome:
    """执行一次调用尝试。运行期故障不抛（以 Outcome 表达）。"""
    brain = _config.build_brain()
    attempted = not getattr(brain, "is_rule", False)
    t0 = time.time()

    if mapping is None:
        protected, mapping = _shield.protect(str(task or ""))
    else:
        protected = str(task or "")
    if rule_protected is None:
        rule_protected = protected

    brief = _brain.Brief(ability=ability, system=system, task=protected,
                         evidence=tuple(evidence), tools=tuple(tools),
                         rule_protected=rule_protected)
    egress = {"items": 1 + len(evidence) + (1 if tools else 0),
              "bytes": brief.egress_bytes()}

    def done(**kw) -> Outcome:
        return Outcome(attempted=attempted, backend=getattr(brain, "name", "rule"),
                       protected=protected, egress=egress,
                       elapsed_ms=int((time.time() - t0) * 1000), **kw)

    try:
        turn = brain.think(brief)
    except _brain.BrainError as e:
        return done(reason=brain_error(getattr(e, "code", type(e).__name__)),
                    shield={"checked": len(mapping), "passed": 0},
                    notice=f"模型调用失败（{_reason_text(e)}）。已回退规则版，内容与规则库一致。")
    except Exception as e:                                     # noqa: BLE001
        return done(reason=brain_error(type(e).__name__),
                    shield={"checked": len(mapping), "passed": 0},
                    notice=f"模型调用失败（{_reason_text(e)}）。已回退规则版，内容与规则库一致。")

    note = turn.note or ""
    candidate = turn.text if not turn.calls else None

    if turn.calls:
        return done(
            reason=FallbackReason.CALLS_UNSUPPORTED,
            shield={"checked": len(mapping), "passed": 0},
            notice=("模型请求了工具，但本轮未开放工具调用。已回退规则版，内容与规则库一致。"
                    if attempted else note))

    if candidate is None or not candidate.strip():
        if not attempted:
            # 规则物为空（如规划器没传规则稿）：不是失败，也没有可用文本。
            return done(text=(candidate or ""), shield={"checked": 0, "passed": 0}, notice=note)
        return done(reason=FallbackReason.EMPTY_REPLY,
                    shield={"checked": len(mapping), "passed": 0},
                    notice=(note or "模型未返回正文。已回退规则版，内容与规则库一致。"))

    if anchored:
        ok, detail = _shield.validate(candidate, mapping)
    else:
        probe = candidate
        for s in allow_substrings:
            probe = probe.replace(s, "")
        ok, detail = _shield.validate_free(probe, mapping)
    if not ok:
        return done(reason=FallbackReason.SHIELD_REJECT, detail=detail,
                    shield={"checked": len(mapping), "passed": 0},
                    notice=(("模型输出未通过数字校验，已回退规则版，内容与规则库一致。"
                             if attempted else "") or note))

    return done(text=_shield.restore(candidate, mapping),
                candidate_protected=candidate,
                shield={"checked": len(mapping), "passed": len(mapping)},
                notice=note)
