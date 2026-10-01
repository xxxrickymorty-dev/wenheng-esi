# -*- coding: utf-8 -*-
"""留痕：`ai_calls.jsonl`（只追加；schema 带版本号与追加位，SPEC §2.2 / C1 / C3）。

记录面纪律（C2）：只放占位或 digest —— 与 trace.py 同源（台账明细不出内网），
再加一条 AI 专有规则：**模型版发布以记录成功为前提**（写失败信号回传给 `run`）。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import secrets
import time

from . import _runtime

#: 记录 schema 版本；追加字段向后兼容，不原地改旧行。
SCHEMA = 1

#: 数据根缺省值：仓库内 `out/`。解析只在本模块（`data_root`）一处做。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "out"


def data_root() -> pathlib.Path:
    """当前数据根：`using(data_root=…)` 覆盖优先，否则仓库 `out/`。"""
    ov = _runtime.overrides()
    return pathlib.Path(ov.get("data_root") or DEFAULT_DATA_ROOT)

#: 记录里 `text` 面的截断长度（占位面，已无数字原值）。
TEXT_PREVIEW = 600
#: 记录里问句截断长度。
QUESTION_PREVIEW = 200


def digest(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def make_record_id(capability: str, now: float | None = None) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return f"ai-{capability}-{ts}-{secrets.token_hex(2)}"


def call_path(root, period: str | None):
    """落点：`out/<期次>/ai_calls.jsonl`；期次不可判 → `out/_ai/ai_calls.jsonl`。"""
    root = pathlib.Path(root)
    if period:
        return root / str(period) / "ai_calls.jsonl"
    return root / "_ai" / "ai_calls.jsonl"


def switch_path(root):
    """开关审计落点：`out/_ai/ai_calls.jsonl`（与无期次调用同文件，kind 区分）。"""
    return pathlib.Path(root) / "_ai" / "ai_calls.jsonl"


def build_call(*, record_id: str, ts: str, period: str, capability: str, actor: str,
               mode: str, backend: str, fallback: str | None, shield: dict,
               receipts, question: str, text_protected: str,
               egress_items: int, egress_bytes: int, elapsed_ms: int,
               extra: dict | None = None) -> dict:
    """一条调用记录。`text_protected` 已过盾（数字为 [[n]] 占位）；`extra` 为追加位。"""
    rec = {
        "schema": SCHEMA,
        "kind": "call",
        "record_id": record_id,
        "ts": ts,
        "period": period or None,
        "capability": capability,
        "actor": actor,
        "mode": mode,
        "backend": backend,
        "fallback": fallback,
        "shield": dict(shield),
        "tools": [r.as_record() for r in receipts],
        "question": question[:QUESTION_PREVIEW],
        "egress": {"items": egress_items, "bytes": egress_bytes},
        "elapsed_ms": elapsed_ms,
        "text_sha256": hashlib.sha256(text_protected.encode("utf-8")).hexdigest(),
        "text_preview": text_protected[:TEXT_PREVIEW],
    }
    if extra:
        rec.update(extra)
    return rec


def append(path, rec: dict) -> bool:
    """追加一行。返回是否写成功 —— 写失败不抛（调用方按模式决定是否降级）。"""
    path = pathlib.Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return True
    except OSError:
        return False


def build_switch(*, ts: str, actor: str, capability: str, from_, to) -> dict:
    """开关变更审计行（C3：落 `out/_ai/ai_calls.jsonl`，kind=switch）。"""
    return {"schema": SCHEMA, "kind": "switch", "ts": ts, "actor": actor,
            "capability": capability, "from": bool(from_), "to": bool(to)}


def process_log_line(logger, capability: str, period: str, actor: str, reason: str) -> None:
    """规则版照发但留痕失败时，进程日志一行（C1 可测句：含 capability/period/actor/时间）。"""
    logger.warning("ai 留痕写失败（%s）：capability=%s period=%s actor=%s ts=%s",
                   reason, capability, period or "-", actor, time.strftime("%Y-%m-%dT%H:%M:%S"))


class Recorder:
    """`ai_calls.jsonl` 的唯一写口：调用记录与开关审计；路径解析也只在这里。

    - 调用记录落 `out/<期次>/ai_calls.jsonl`；期次不可判落 `out/_ai/`；
    - 开关审计恒落 `out/_ai/`（kind=switch）；
    - 写失败不抛：`call()` 返回 None、`switch()` 返回 False，由调用方定政策
      （能力口：模型版降级规则版；写作位：产出不受影响）。
    """

    def __init__(self, root, *, period: str = "", actor=None):
        self.root = pathlib.Path(root)
        self.period = period or ""
        self.actor = _runtime.resolve_actor(actor)

    @classmethod
    def for_period(cls, period, actor=None) -> "Recorder":
        """按当前数据根（`using(data_root=…)` 覆盖感知）建写口。"""
        return cls(data_root(), period=period, actor=actor)

    def call(self, *, capability: str, mode: str, backend: str, fallback: str | None,
             shield: dict, text_protected: str, question: str = "", label=None,
             egress_items: int = 0, egress_bytes: int = 0, receipts=(),
             elapsed_ms: int = 0, fallback_detail=None) -> str | None:
        """记一条调用；成功返回 record_id，写失败返回 None。"""
        rid = make_record_id(capability)
        rec = build_call(
            record_id=rid, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), period=self.period,
            capability=capability, actor=self.actor, mode=mode, backend=backend,
            fallback=fallback, shield=dict(shield or {}), receipts=receipts,
            question=question, text_protected=text_protected,
            egress_items=int(egress_items or 0), egress_bytes=int(egress_bytes or 0),
            elapsed_ms=int(elapsed_ms or 0),
            extra={"fallback_detail": fallback_detail} if fallback_detail else None)
        if label is not None:
            rec["label"] = str(label)
        return rid if append(call_path(self.root, self.period), rec) else None

    def switch(self, *, capability: str, from_, to) -> bool:
        """记一条开关审计；写失败返回 False（开关本身已生效）。"""
        audit = build_switch(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), actor=self.actor,
                             capability=capability, from_=from_, to=to)
        return append(switch_path(self.root), audit)


def tmp_path(path) -> pathlib.Path:
    """同目录临时名（原子写用；同目录保证 os.replace 原子性）。"""
    return pathlib.Path(path).with_name(
        f"{pathlib.Path(path).name}.tmp-{os.getpid()}-{secrets.token_hex(3)}")


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """原子写：tmp（同目录）+ os.replace；失败清理 tmp，目标文件保持旧内容。"""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path(path)
    try:
        with open(tmp, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
