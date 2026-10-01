# -*- coding: utf-8 -*-
"""流水线产物在 server 侧的唯一读取面：red_slots / meta / facts / table2 / 断言计数。

页面（工作台、对勘本、审核台、运行档案、书架）只从这里取数；字段回落、类型守卫、
计数口径、槽位分类都只在这里一份——此前 8 个读取点各写各的，口径微调必然漂移。

约定：
- 缺文件 / 坏 JSON / 形状不对 → 空容器（`[]` / `{}`），**不抛、不记日志**；
  页面各自已有空态，读取层再抛只会让一个坏文件打翻整页。
- `slot_text(full=True)`＝全文语义（`new_full → new`）；`full=False`＝预览语义（`new`，
  50 字截断值，给只需要短值的页面如逐格溯源）。
- `assertion_counts` 是**严格口径**：凡不是 `["PASS", ...]` 的条目一律计 fail
  （含空元素 / 畸形），签单闸门取安全侧。
"""
from __future__ import annotations

import csv
import json
import pathlib


def read_json(path):
    """读对象 JSON；缺文件 / 坏 JSON / 顶层不是 dict → None。"""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_slots(out_dir) -> list:
    """`red_slots.json` → 合法行（dict）列表；缺 / 坏 / 非 list → []。"""
    p = pathlib.Path(out_dir) / "red_slots.json"
    try:
        rows = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def read_meta(out_dir) -> dict:
    """`meta.json` → dict；缺 / 坏 → {}。"""
    return read_json(pathlib.Path(out_dir) / "meta.json") or {}


def read_facts(out_dir) -> dict:
    """`overview_facts.json` → dict；缺 / 坏 → {}。"""
    return read_json(pathlib.Path(out_dir) / "overview_facts.json") or {}


def read_table2(out_dir) -> list:
    """`table2.csv` → 行 dict 列表（utf-8-sig）；缺 / 坏 → []。"""
    p = pathlib.Path(out_dir) / "table2.csv"
    try:
        with p.open(encoding="utf-8-sig", newline="") as f:
            return [dict(r) for r in csv.DictReader(f)]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def assertion_counts(meta) -> dict:
    """机器断言计数（口径唯一）→ `{"total", "fail"}`；`pass = total - fail`。"""
    assertions = (meta or {}).get("assertions") if isinstance(meta, dict) else None
    if not isinstance(assertions, list):
        return {"total": 0, "fail": 0}
    fail = sum(1 for a in assertions
               if not (isinstance(a, (list, tuple)) and a and a[0] == "PASS"))
    return {"total": len(assertions), "fail": fail}


def slot_text(slot, key: str, *, full: bool = True) -> str:
    """槽位文本。`full=True` 优先全文键（`<key>_full → <key>`）；`False` 只取预览键。"""
    if not isinstance(slot, dict):
        return ""
    if full:
        value = slot.get(f"{key}_full") or slot.get(key) or ""
    else:
        value = slot.get(key) or ""
    return str(value)


def slot_kind(slot) -> str:
    """槽位类型：chart（new 以 `[图]` 开头）/ cell（`T##/r#c#`）/ text。

    统一前 app 认 `综述/…图`（现数据里已无此形态的正片槽）、collation 认
    `正文/…图`（会把「正文/图片行距」误判成图）——以 `[图]` 占位为准，两页同口径。
    """
    loc = str(slot.get("location") or "") if isinstance(slot, dict) else ""
    if slot_text(slot, "new", full=False).startswith("[图]"):
        return "chart"
    if loc.startswith("T") and "/" in loc:
        return "cell"
    return "text"
