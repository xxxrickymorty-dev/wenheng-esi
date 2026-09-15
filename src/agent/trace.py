# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 轨迹记录（WH-DOC-04 §4.3；WH-DOC-03 §8）。

三个文件，**只追加、绝不原地修改**：

  `agent_events.jsonl`  ts / phase / tool / args_digest / observation / decision / reason / loop
  `state_history.jsonl` ts / from / to / trigger / attempt
  `task_runs.jsonl`     step / attempt / started / finished / status / elapsed

`phase` 取值固定为 plan · act · observe · decide · escalate。
参数一律存 **digest**（sha256 前 12 位）而非原值——台账明细不得出内网
（架构设计 §5.4），轨迹文件要能安全随期归档。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time

from . import states

PHASES = ("plan", "act", "observe", "decide", "escalate")


def digest(obj, n: int = 12) -> str:
    """把任意可 JSON 化的入参压成短摘要，用于轨迹留痕。"""
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n]


class Trace:
    """一次运行的轨迹簿。所有写入失败都不得中断主流程（审计优先，但不阻塞生产）。"""

    def __init__(self, run_dir):
        self.dir = pathlib.Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "agent_events.jsonl"
        self.states_path = self.dir / "state_history.jsonl"
        self.runs_path = self.dir / "task_runs.jsonl"
        self._loop = 0
        self.last_event_at: float = time.time()

    # ---------------------------------------------------------------- 内部
    def _append(self, path: pathlib.Path, rec: dict) -> None:
        self.last_event_at = time.time()
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass          # 留痕失败不阻断生产

    # ---------------------------------------------------------------- 对外
    def event(self, phase, tool=None, args=None, observation=None,
              decision=None, reason=None, loop=None):
        """记一条 agent 事件。`args` 会被自动摘要成 digest。"""
        if phase not in PHASES:
            raise ValueError(f"非法 phase：{phase!r}，应为 {PHASES}")
        if loop is not None:
            self._loop = loop
        self._append(self.events_path, {
            "phase": phase,
            "tool": tool,
            "args_digest": digest(args) if args is not None else None,
            "observation": observation,
            "decision": decision,
            "reason": reason,
            "loop": self._loop,
        })

    def transition(self, src: str, dst: str, trigger: str, attempt: int = 1) -> None:
        """状态迁移。先校验合法性——静默迁移是审计事故。"""
        states.check_transition(src, dst)
        self._append(self.states_path, {
            "from": src, "to": dst, "trigger": trigger, "attempt": attempt,
        })

    def task_run(self, step, attempt, started, finished, status, elapsed=None):
        self._append(self.runs_path, {
            "step": step,
            "attempt": attempt,
            "started": started,
            "finished": finished,
            "status": status,
            "elapsed": round(elapsed if elapsed is not None else (finished - started), 2),
        })

    def escalate(self, reason, detail=None):
        """升级：写入 escalate 事件，供《诊断报告》组装。"""
        self.event("escalate", observation=detail, decision="escalate", reason=reason)
