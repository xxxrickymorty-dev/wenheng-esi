# -*- coding: utf-8 -*-
"""自动取数台（X2）：取数状态的**只读**读取。

状态文件由取数流程写入 `out/_acquisition/<期次>.json`（人触发；工具化后由取数工具回填）。
写路径的纪律见 ADR-0004：建副本 → 馆员核对 → 并入台账；运行期流水线对主台账仍只读。

形状（与前端 `AcquisitionState` 对齐，字段只增不改；缺字段前端按「未就绪」显示）：
    {
      "period": "202611",
      "updated_at": "2026-11-27T10:42:00+08:00",
      "data_period": {"esi": "2026 年 11 月", "incites": "2026-10-31"},
      "preflight": {"browser": "ok", "esi": "ok", "incites": "ok"},      # ok / bad / waiting
      "capabilities": {"start": true, "retry": true, "merge": true},    # 工具接入后为 true
      "groups": [ {"id": "esi-institutions", "source": "esi", "index": 1, "title": "全球机构总表",
                   "state": "done", "verified": 1, "downloaded": 1,
                   "files": [{"name": "Institutions.xlsx", "label": "全球机构总表", "state": "ok"}]} ],
      "totals": {"groups": 9, "expected": 64, "verified": 64, "downloaded": 64, "failed": 0},
      "copy": {"state": "review", "path": "input/202611/监测表.xlsx",
               "built_at": "...", "merged_at": null},                    # none / review / merged
      "review": {"sheets": [{"name": "总被引", "added": "202611 列",
                             "content": "22 个学科各一格", "source": "ESI"}]}
    }

文件缺失或损坏一律返回 None——界面显示「还没开始」，**不编数据**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

#: 取数状态目录（与 `out/_jobs`、`out/_forecast_choices` 同级的内部目录）
STATE_DIR = config.OUT_DIR / "_acquisition"

_PERIOD_RE = re.compile(r"^\d{6}$")


def state_path(period: str) -> Path:
    return STATE_DIR / f"{period}.json"


def load(period: str) -> dict | None:
    """读一期取数状态；没有/读不动就 None。"""
    if not _PERIOD_RE.match(period or ""):
        return None
    try:
        data = json.loads(state_path(period).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["period"] = period
    return data


def periods() -> list[str]:
    """有取数状态的期次（新→旧）。"""
    if not STATE_DIR.exists():
        return []
    found = [p.stem for p in STATE_DIR.glob("*.json") if _PERIOD_RE.match(p.stem)]
    return sorted(found, reverse=True)
