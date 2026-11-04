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
- `brain` 缺省走部署装配（`_config.build_brain()`）；写作位创写传专用适配器
  （专用模型与预算在调用方装配，边界只负责用它——向后兼容，其余调用不动）。
- `attempted=False`（规则部署）不算失败：`reason=None`、`text`＝规则物；
  只有真实模型的失败才带回落码。
- 供应商强制语义（rick 2026-11-04）：部署配置非规则版（`strict_enabled()`）
  时，各回落点**不许拿规则物顶包**——能整单失败的抛 `AIRequiredError`，
  只能逐位失败的以失败态表达；记录面照记（审计不丢）。
- 盾拒恢复一轮（实验分支 exp/dsh-recovery：dsh 式协议闭合）：真模型校验失败且本
  attempt 尚未恢复过时，不立即回落——把上一稿的未标记数字隐去为 ▇（[[n]] 标记
  原样保留、至多引用前 1200 字符），以一条零数字的用户反馈进 history 重问一次；
  恢复后再盾拒按原样回落（detail/notice 口径不变），每个 attempt 至多恢复一次。
  规则部署与 GUARD_REJECT、执行器异常路径一概不恢复。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum

from . import _brain, _config, _record, _runtime, _shield


class FallbackReason(StrEnum):
    """回落原因码。字面值是记录/界面契约（`AiRecords` 按它出中文），不许改。"""

    CALLS_UNSUPPORTED = "calls_unsupported"
    EMPTY_REPLY = "empty_reply"
    SHIELD_REJECT = "shield_reject"
    OFF_TOPIC = "off_topic"
    KEEP_BROKEN = "keep_broken"
    #: GUARD_REJECT：两处产生——政策级（调用方写记录）＋ 工具环里执行器违约
    #: （边界拦执行器返回的裸数字，2026-10-28 fc 定稿）。
    GUARD_REJECT = "guard_reject"
    RECORD_FAILED = "record_failed"


class AIRequiredError(RuntimeError):
    """供应商开启（强制模型）态下的模型位失败（rick 2026-11-04 供应商强制语义）。

    语义：添加了模型供应商＝全系统强制模型——模型位失败**不许回落规则稿
    占位**，必须以人话显式失败（能整单失败的抛本异常；只能逐位失败的
    以失败态 Answer 表达，也由本异常的文案给话）。判定「供应商开启」
    的唯一口径见 `strict_enabled()`；规则部署（默认关闭）**不抛**本异常，
    一切照旧。`reason`＝回落原因码（与 `Outcome.reason` 同一张码表），
    进文案与记录面；`what`＝模型位的人话位置（如「灵活报告规划」）。
    """

    def __init__(self, reason: str = "", what: str = ""):
        self.reason = str(reason or "unknown")
        self.what = str(what or "模型位")
        super().__init__(
            f"{self.what}失败：模型生成未成功（原因码 {self.reason}）。"
            "系统已配置模型供应商，按供应商强制语义不再回落规则稿——"
            "请重试，或检查模型服务后重试。")


def strict_enabled() -> bool:
    """「供应商开启」判定（rick 2026-11-04）：唯一口径＝**装配结果
    `brain.is_rule == False`**——即 `attempt()` 的 `attempted` 同一判据。

    实现按**部署配置**（`_config.cloud_config()`）判，与 `build_brain()`
    构造非规则适配器的条件逐条一致（非 demo 锁 + backend=openai +
    base/model/key 齐备；模型清单生效即开启）——**不读测试/脚本注入**
    （`using(brain=…)` 只影响当次调用，不代表部署事实），
    也**不发明第二个开关旋钮**（禁新 `WENHENG_AI_*` 环境变量）。
    未添加供应商（默认）→ False：规则稿直出、一切照旧。
    """
    cfg = _config.cloud_config()
    if cfg["profile"] == "demo":
        return False                      # 演示锁＝关闭（部署事实）
    if cfg["backend"] != "openai":
        return False                      # 默认 / 未配置
    return bool(cfg["base_url"] and cfg["model"] and cfg["key"])


def brain_error(code) -> str:
    """动态回落码：`brain_error:<code>`（code＝BrainError.code 或异常类名）。"""
    return f"brain_error:{code}"


@dataclass(frozen=True)
class Outcome:
    """一次模型尝试的定型结果（边界 → 调用方）。

    - `text`＝可用文本（模型候选已还原 / 规则部署的规则物；失败为 None）；
    - `candidate_protected`＝通过校验的占位面候选（`_used_sources` 按它排来源）；
    - `attempted`＝配置了真实模型（False＝规则部署，不是失败）；
    - `shield`＝本次尝试的校验计数（失败 passed=0，明细在 `detail`）；
    - `receipts`＝工具环执行回执（仅成功路径带；回落为空——2026-10-28 fc 定稿）。
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
    receipts: tuple = ()


def _reason_text(e) -> str:
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:80]


#: 同参重复调用的工具消息回句（构造上零数字；不执行、不产生回执与轨迹）。
_DUP_TOOL_TEXT = ("（该查询已执行过，参数完全相同；结果见上面的同名工具消息。"
                  "请依据已有结果作答，不要再调用工具。）")


def _canon_args(args) -> str:
    """参数规范 JSON 串（去重键 + assistant 消息里 arguments 的线上格式）。"""
    return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)


def _round_items(brief: _brain.Brief) -> int:
    """单轮外发面 items 明细：基面（ability+system+task 记 1）+ 证据 + 工具 schema + 历史。"""
    return (1 + len(brief.evidence) + (1 if brief.tools else 0)
            + (1 if brief.history else 0))


#: 盾拒恢复（实验分支）：上一稿引用上限（字符）与「标记或数字」的匹配正则
#: （交替里标记在前——[[3]] 整体吃掉，段外数字才隐去）。
_HIDDEN_MAX = 1200
_MARK_OR_NUM = re.compile(r"\[\[\d+\]\]|\d+")


def _mask_digits(text: str) -> str:
    """上一稿的隐去面：[[n]] 标记原样保留，标记外数字一律 → ▇（模型只见占位面）。"""
    return _MARK_OR_NUM.sub(lambda m: m.group(0) if m.group(0).startswith("[[") else "▇",
                            str(text or ""))


def _reject_feedback(candidate: str) -> str:
    """盾拒恢复的用户反馈（零数字：[[n]] 标记之外一个阿拉伯数字都没有）。"""
    hidden = _mask_digits(candidate)
    if len(hidden) > _HIDDEN_MAX:
        hidden = hidden[:_HIDDEN_MAX] + "……"
    return ("你的上一稿未通过数字校验，已被退回。上一稿原文（未标记数字已隐去为 ▇）：\n"
            f"{hidden}\n\n请只输出回答正文本身：先直接回答所问；"
            "所有数值一律原样引用 [[n]] 标记；不要输出任何思考过程、分析或解释。")


def attempt(task, *, system: str, ability: str, anchored: bool = True, evidence=(),
            tools=(), execute=None, max_steps: int = 1,
            rule_protected: str | None = None, mapping: dict | None = None,
            allow_substrings=(), brain=None) -> Outcome:
    """执行一次调用尝试。运行期故障不抛（以 Outcome 表达）。

    `brain`：可选适配器覆盖（None＝部署装配）；写作位创写的专用模型/预算由此进入，
    本边界不读写作位配置。
    原生工具环（2026-10-31 升级为 OpenAI 官方多轮协议）：`tools` 非空且给了 `execute`
    （宿主执行器回调）时，「真模型」路径进环——think → `turn.calls` → 逐调用执行
    （结果必须是执行器侧已注册编号的占位面；裸数字即执行器违约 → GUARD_REJECT 回落）→
    assistant(tool_calls) + role:"tool" 消息追加进 `Brief.history` → 再 think；
    工具结果**不折进 evidence**（evidence 恒为首轮证据，结果只住在工具消息里）；
    末轮（step_now == steps）`Brief.tools` 物理收口为空（等价 tool_choice:"none"），
    该轮仍回 calls → CALLS_UNSUPPORTED（最后防线）；同参重复调用（工具名 + 参数规范
    JSON 串）不再执行，直接回去重句（零数字，无回执无轨迹）。`mapping` 以调用方
    持有的 dict 为准——执行器续号（`NumberedText.append` 原地生长）边界自动看到。
    无 tools / 无 execute / 规则部署的一切调用不进环，行为与从前逐字一致。
    """
    brain = _config.build_brain() if brain is None else brain
    attempted = not getattr(brain, "is_rule", False)
    if attempted:
        _runtime.progress(f"model:{ability}")   # 票 12：模型真被调用才发（规则轮不发）
    t0 = time.time()

    if mapping is None:
        protected, mapping = _shield.protect(str(task or ""))
    else:
        protected = str(task or "")
    if rule_protected is None:
        rule_protected = protected

    # 工具环只在「真模型 + 带工具 + 给了执行器」时启用；这是既有全部能力的回归线。
    tool_loop = attempted and bool(tools) and execute is not None
    steps = max(int(max_steps or 1), 1)
    receipts: list = []
    history: tuple = ()        # 原生协议轮消息（assistant tool_calls + role:"tool"）
    done_keys: set = set()     # 本次 attempt 已执行调用 (工具名, 参数规范 JSON) —— 同参去重
    step_now = 1               # 当前轮次（进 Brief.step；1 起，max_steps 轮内必须作答）
    recovered = False          # 盾拒已恢复过一轮（实验分支：每个 attempt 至多一次）
    # 末轮物理收口：tool_loop 下最后一轮 Brief.tools=()（等价 tool_choice:"none"，
    # 兼容一切 OpenAI 兼容网关）；非环路径（规则部署 / 未给执行器）与从前逐字一致。
    brief = _brain.Brief(ability=ability, system=system, task=protected,
                         step=1, max_steps=steps,
                         evidence=tuple(evidence),
                         tools=(tuple(tools) if (step_now < steps or not tool_loop) else ()),
                         rule_protected=rule_protected)
    egress = {"items": _round_items(brief), "bytes": brief.egress_bytes()}

    def done(**kw) -> Outcome:
        return Outcome(attempted=attempted, backend=getattr(brain, "name", "rule"),
                       protected=protected, egress=egress,
                       elapsed_ms=int((time.time() - t0) * 1000), **kw)

    while True:
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

        if turn.calls and tool_loop:
            if step_now >= steps:
                # 末轮仍 calls：末轮 Brief.tools 已收口为空，模型无视仍在要工具
                # → 回落（回执不发布；最后防线）。
                return done(reason=FallbackReason.CALLS_UNSUPPORTED,
                            shield={"checked": len(mapping), "passed": 0},
                            notice="模型连续请求工具未作答。已回退规则版，内容与规则库一致。")
            call_msgs: list = []
            tool_msgs: list = []
            for i, call in enumerate(turn.calls):
                name = str((call or {}).get("name") or "")
                args = (call or {}).get("arguments") or {}
                args = dict(args) if isinstance(args, dict) else {}
                cid = str((call or {}).get("id") or f"call_{i}")
                args_json = _canon_args(args)
                call_msgs.append({"id": cid, "type": "function",
                                  "function": {"name": name, "arguments": args_json}})
                key = (name, args_json)
                if key in done_keys:
                    # 同参重复：不执行、不发 receipt/trace——结果已在上一条同名工具消息里。
                    tool_msgs.append({"role": "tool", "tool_call_id": cid,
                                      "content": _DUP_TOOL_TEXT})
                    continue
                try:
                    text, receipt = execute(call)
                except Exception as e:                             # noqa: BLE001
                    return done(reason=brain_error(type(e).__name__),
                                shield={"checked": len(mapping), "passed": 0},
                                notice=(f"工具执行失败（{_reason_text(e)}）。"
                                        "已回退规则版，内容与规则库一致。"))
                receipts.append(receipt)
                # 工具调用轨迹（2026-10-29）：只报「查了什么、查到没有、用多久」——
                # 形状唯一出处 `_record.emit_trace`；执行器回执按鸭子类型读
                # （测试替身回裸串时用调用名/「查台账」兜底，与从前逐字一致）。
                _record.emit_trace(receipt, step=step_now,
                                   tool=str((call or {}).get("name") or ""),
                                   label="查台账")
                stray = _shield.visible_digits(str(text or ""))    # 内含 strip_marks
                if stray:
                    # 执行器违约（结果必须已是占位面）：防线不依赖执行器自觉。
                    return done(reason=FallbackReason.GUARD_REJECT,
                                detail={"tool": str((call or {}).get("name") or ""),
                                        "stray": stray},
                                shield={"checked": len(mapping), "passed": 0},
                                notice="工具返回文本未通过数字校验，已回退规则版，内容与规则库一致。")
                done_keys.add(key)
                tool_msgs.append({"role": "tool", "tool_call_id": cid,
                                  "content": str(text or "")})
            # 原生多轮协议：assistant(tool_calls) 一条 + 每调用一条 role:"tool"。
            history = history + ({"role": "assistant", "content": None,
                                  "tool_calls": call_msgs},) + tuple(tool_msgs)
            step_now += 1
            # 重造 Brief：结果只住在工具消息里（evidence 恒为首轮证据）、step 前进；
            # egress 按每轮 Brief 求和（history 计入外发面）。
            brief = _brain.Brief(ability=ability, system=system, task=protected,
                                 step=step_now, max_steps=steps,
                                 evidence=tuple(evidence),
                                 tools=(tuple(tools) if step_now < steps else ()),
                                 history=history,
                                 rule_protected=rule_protected)
            egress = {"items": egress["items"] + _round_items(brief),
                      "bytes": egress["bytes"] + brief.egress_bytes()}
            continue

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
        if ok:
            return done(text=_shield.restore(candidate, mapping),
                        candidate_protected=candidate,
                        shield={"checked": len(mapping), "passed": len(mapping)},
                        notice=note, receipts=tuple(receipts))
        if not (attempted and not recovered):
            # 恢复后再盾拒 / 规则部署：按原样回落（notice 口径不变）。detail 增
            # masked_head＝被拒稿的隐去面（票 C：model-visible means logged，
            # 失败尝试也可复盘，不必再抓包；stray 照旧）。
            return done(reason=FallbackReason.SHIELD_REJECT,
                        detail={**(detail or {}),
                                "masked_head": _mask_digits(candidate)[:200]},
                        shield={"checked": len(mapping), "passed": 0},
                        notice=(("模型输出未通过数字校验，已回退规则版，内容与规则库一致。"
                                 if attempted else "") or note))
        # 盾拒恢复一轮（实验分支，dsh 协议闭合）：隐去上一稿的未标记数字，
        # 以零数字反馈重问一次；成败下一轮定型（evidence/tools/step 均不变——
        # tools 取当前 Brief 的现值，末轮已收口就保持收口）。
        recovered = True
        history = history + ({"role": "user", "content": _reject_feedback(candidate)},)
        brief = _brain.Brief(ability=ability, system=system, task=protected,
                             step=step_now, max_steps=steps,
                             evidence=tuple(evidence), tools=brief.tools,
                             history=history, rule_protected=rule_protected)
        egress = {"items": egress["items"] + _round_items(brief),
                  "bytes": egress["bytes"] + brief.egress_bytes()}
