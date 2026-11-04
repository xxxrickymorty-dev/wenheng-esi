# -*- coding: utf-8 -*-
"""留痕：`ai_calls.jsonl`（只追加；schema 带版本号与追加位，SPEC §2.2 / C1 / C3）。

记录面纪律（C2）：只放占位或 digest —— 与 trace.py 同源（台账明细不出内网），
再加一条 AI 专有规则：**模型版发布以记录成功为前提**（写失败信号回传给 `run`）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import secrets
import time

from . import _runtime
from ._types import Receipt

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


# ---------------------------------------------------------------- 确定性工具调用收口（C4）
def tool_receipt(tool: str, label: str, args, summary: str, *,
                 ok: bool, t0: float, refused: bool = False) -> Receipt:
    """确定性工具调用的回执（双面，C2）。唯一出口——`tool_call` 收口与各调用方共用。

    `t0` 是调用方取的 `time.perf_counter()` 起点（把真实工具调用包住）；
    `args` 只进 `args_digest`（记录面）；`summary` 是界面面人话（一句以内）——
    数字只许用对话界面已显示的盘点件数这类，不放任何报告数值（回执红线）。
    """
    return Receipt(tool=tool, label=label, args_digest=digest(args),
                   summary=summary, elapsed_ms=int((time.perf_counter() - t0) * 1000),
                   ok=ok, refused=refused)


def trace_event(*, step: int = 1, tool: str, label: str, summary: str,
                ok: bool = True, refused: bool = False, ms: int = 0) -> dict:
    """「工具调用」轨迹一条的标准形状（2026-10-29）：唯一手写处。

    事件只放**本就给界面看**的东西（工具名、中文摘要、耗时、成没成）——
    不放模型原文、不放台账数值。
    """
    return {"step": int(step), "tool": str(tool), "label": str(label),
            "summary": str(summary), "ok": bool(ok),
            "refused": bool(refused), "ms": int(ms)}


def emit_trace(receipt, *, step: int = 1, tool: str = "", label: str = "") -> None:
    """回执 → 界面「工具调用」轨迹一条。旁路：回调异常不挡主流程（`_runtime.trace`）。

    回执按鸭子类型读——写作位边界允许执行器返回非 Receipt（测试替身回裸串），
    缺 attr 时用 `tool` / `label` 兜底。
    """
    _runtime.trace(trace_event(
        step=step,
        tool=str(getattr(receipt, "tool", "") or tool),
        label=str(getattr(receipt, "label", "") or label),
        summary=str(getattr(receipt, "summary", "") or ""),
        ok=bool(getattr(receipt, "ok", True)),
        refused=bool(getattr(receipt, "refused", False)),
        ms=int(getattr(receipt, "elapsed_ms", 0) or 0)))


def scan_summary(inv, period: str = "") -> str:
    """盘点回执的人话摘要（工具声明的一部分，**单处定义**）：
    `_dialog` 规则轮与 `_dialog_kernel` 内核轮共用——同一工具同一摘要。
    """
    if not inv:
        return "该期数据状态在这里看不到"
    n_missing = int(inv.get("n_missing") or 0)
    missing = f"，缺 {n_missing} 件" if n_missing else ""
    return (f"盘点 · {inv.get('period') or period}"
            f"（必需件 {int(inv.get('n_pieces') or 0)} 件{missing}）")


def product_summary(has) -> str:
    """产物核对回执的人话摘要（单处定义，同上）。"""
    return "该期已有成品" if has else "该期暂无成品"


class tool_call:
    """确定性工具调用的上下文收口（C4）：计时＋回执＋（可选）轨迹一处出。

    用法（with 包住真实调用，退出后取 `.receipt`）：

        with _record.tool_call("product_status", "产物核对",
                               {"period": p.period}) as tc:
            has = _products_exist(root, p.period)
            tc.finish(_record.product_summary(has))
        rcpts.append(tc.receipt)

    - 摘要在 `finish()` 给一次（文案按工具单处定义，见 `scan_summary` 等）；
    - `trace=True` 时退出即发轨迹一条（内核工具轮要；规则轮回执只进
      `Answer.receipts`、不发轨迹——与现状逐字一致）；
    - `ok=False` 表「查了但没查到/看不到」，与 `refused`（越权拒答）分开；
    - with 体内异常照常外抛（旧样板同样不出回执），不留半张回执。
    """

    def __init__(self, tool: str, label: str, args, *, trace: bool = False):
        self.tool = tool
        self.label = label
        self.args = args
        self._trace = trace
        self._t0 = 0.0
        self._receipt: Receipt | None = None

    def __enter__(self) -> "tool_call":
        self._t0 = time.perf_counter()
        return self

    def finish(self, summary: str, *, ok: bool = True, refused: bool = False) -> None:
        """给一次摘要并定型回执（with 体内对真实调用包完后调用）。"""
        self._receipt = tool_receipt(self.tool, self.label, self.args, summary,
                                     ok=ok, t0=self._t0, refused=refused)

    @property
    def receipt(self) -> Receipt:
        if self._receipt is None:
            # finish 没调（异常/编程错误）：照实出一张失败回执，不让旁路面炸掉。
            self._receipt = tool_receipt(self.tool, self.label, self.args,
                                         "这次没查成", ok=False, t0=self._t0)
        return self._receipt

    def __exit__(self, exc_type, exc, tb) -> bool:                 # noqa: ARG002
        if self._trace:
            emit_trace(self.receipt)
        return False


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
             elapsed_ms: int = 0, fallback_detail=None, plan=None) -> str | None:
        """记一条调用；成功返回 record_id，写失败返回 None。

        `plan`（票 04）：规划摘要（origin/specs/note）——追加字段，旧读者忽略。
        """
        rid = make_record_id(capability)
        extra: dict = {}
        if fallback_detail:
            extra["fallback_detail"] = fallback_detail
        if plan:
            extra["plan"] = plan
        rec = build_call(
            record_id=rid, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), period=self.period,
            capability=capability, actor=self.actor, mode=mode, backend=backend,
            fallback=fallback, shield=dict(shield or {}), receipts=receipts,
            question=question, text_protected=text_protected,
            egress_items=int(egress_items or 0), egress_bytes=int(egress_bytes or 0),
            elapsed_ms=int(elapsed_ms or 0),
            extra=extra or None)
        if label is not None:
            rec["label"] = str(label)
        return rid if append(call_path(self.root, self.period), rec) else None

    def switch(self, *, capability: str, from_, to) -> bool:
        """记一条开关审计；写失败返回 False（开关本身已生效）。"""
        audit = build_switch(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), actor=self.actor,
                             capability=capability, from_=from_, to=to)
        return append(switch_path(self.root), audit)


def aggregate_calls(root=None) -> dict:
    """聚合全部调用记录（`GET /api/ai/call-stats` 的数据面，2026-11-04）。

    扫 `<root>/*/ai_calls.jsonl`（`_ai/` 同 glob 覆盖；只算 `kind="call"`，
    开关审计 kind=switch 不算；坏行/坏文件跳过不炸）。口径：

    - `model`＝模型轮成功（mode=model）；
    - `failed`＝模型轮回落（mode=fallback，dialog 内核轮记录面）——
      原因码进 `labels[].fallback`；
    - `rule`＝其余（纯规则轮、关闭态等），保证 total ＝ 三者之和。

    `label` 缺失的记录（qa / dialog 这类不带 label 的能力）按 `capability`
    归组。labels 按 total 降序、同名按字典序——确定性输出。
    没有任何记录 → 全零结构，不报错。
    """
    root = pathlib.Path(root or data_root())
    modes = {"model": 0, "rule": 0, "failed": 0}
    labels: dict[str, dict] = {}
    total = 0
    for path in sorted(root.glob("*/ai_calls.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("kind") != "call":
                continue
            total += 1
            mode = str(rec.get("mode") or "")
            key = ("model" if mode == "model"
                   else "failed" if mode == "fallback" else "rule")
            modes[key] += 1
            name = str(rec.get("label") or rec.get("capability") or "(未标注)")
            bucket = labels.setdefault(name, {"label": name, "total": 0,
                                              "model": 0, "rule": 0, "failed": 0,
                                              "fallback": {}})
            bucket["total"] += 1
            bucket[key] += 1
            if key == "failed":
                fb = str(rec.get("fallback") or "(未知)")
                bucket["fallback"][fb] = bucket["fallback"].get(fb, 0) + 1
    out_labels = sorted(labels.values(),
                        key=lambda b: (-b["total"], b["label"]))
    for bucket in out_labels:
        bucket["fallback"] = dict(sorted(bucket["fallback"].items(),
                                         key=lambda kv: (-kv[1], kv[0])))
    return {"total": total, "modes": modes, "labels": out_labels}


def _atomic_io():
    """公用原子写模块（`src/atomic_io.py`）。两种导入姿势都盖住：

    仓里既有 `from src.ai import …`（仓库根在 sys.path），也有 `from ai import …`
    （src/ 自己在 sys.path 上），所以这里不用相对导入。
    """
    try:
        import atomic_io                                        # noqa: PLC0415
    except ImportError:                                         # 只有仓库根在 sys.path
        from src import atomic_io                               # noqa: PLC0415
    return atomic_io


def tmp_path(path) -> pathlib.Path:
    """同目录临时名（原子写用；同目录保证 os.replace 原子性）。"""
    return _atomic_io().tmp_path(path)


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """原子写（薄封装 `src/atomic_io.py::write_text_atomic`）。

    **保留 `newline="\\n"`**：`out/_ai/settings.json` 历来是 LF，换行翻译一开就成了字节回归。
    """
    _atomic_io().write_text_atomic(path, text, encoding=encoding, newline="\n")
