# -*- coding: utf-8 -*-
"""演示站 · 馆员工作台的数据装配（2026-09-19）。

设计前提（grill-me 定案，改这里前先读一遍）
------------------------------------------------------------------
1. **不判"对错"，只说"可溯源"**。系统里没有 ground truth（人工原件只有 1–4 期，
   且那 4 期自身还有笔误），所以顶部写的不是"已核对 N 格"，而是
   "N 个数字全部可回查到台账"—— 这句是真的，且当场能点开验证。
2. **待拍板只收"不处理报告就出不来或不该出"的那批**（约 20 条），不是全部 354 条。
   239 个大表格子 + 99 张图的正确状态是"已可溯源、要查随时能点开"，把它们塞进
   待办清单，等于把"已完成"和"待处理"混在一起——那正是"找不到重点"的根源。
3. 本模块**只读**。在线填的内容由别的模块写 `out/<期次>/manual_inputs.json`，
   **台账一个字节都不碰**（改了就破溯源）。
"""
from __future__ import annotations

import json
import pathlib
import re

#: 「待补数据」—— 这三张表**不在** red_slots.json 里：它们母版即空、数据在台账外，
#: 机器压根没动过，所以只能列成静态清单。格数不写死（省表/矩阵的规模会变），
#: 写死了就是下一个"编出来的数"。
PENDING_TABLES = (
    {"id": "T19", "title": "云南省高校学科对比表",
     "why": "母版即空，数据不在台账里，需馆员从外部贴入"},
    {"id": "T20", "title": "学科 × 高校矩阵表",
     "why": "同上，母版即空"},
    {"id": "T21", "title": "顶尖论文清单",
     "why": "母版清单复用，本期需换成当期数据"},
)

#: 需要人工**确认**（不是填）的结构性项：这些填错整份报废
_CONFIRM_PREFIX = ("封面/",)
_CONFIRM_SOURCE = ("期次参数",)

_HAND = re.compile(r"【手工：([^】]*)】")


def _slots(out_dir):
    p = pathlib.Path(out_dir) / "red_slots.json"
    if not p.exists():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def _todo_from_slot(row, idx):
    """把一个槽位里的【手工：…】标记拆成若干条待办（按**处**不是按槽位）。"""
    # ⚠ 必须在**全文**上探测：red_slots 的 new 被截断到 50 字，只扫 new 会漏判
    text = row.get("new_full") or row.get("new") or ""
    where = row.get("location") or "?"
    out = []
    for i, m in enumerate(_HAND.finditer(text), 1):
        hint = (m.group(1) or "").strip()
        out.append({
            "id": f"fill-{idx}-{i}",
            "kind": "fill",                 # 可以且应该在线填
            "title": hint or "待人工填写",
            "where": where,
            "source": row.get("source") or "",
        })
    return out


def build(out_dir, period=None, approval=None):
    """装配一屏所需的一切。返回 dict（纯读，不写任何文件）。"""
    rows = _slots(out_dir)
    period = period or pathlib.Path(out_dir).name

    traced = sum(1 for r in rows if (r.get("source") or "").strip())

    todo = []
    for i, r in enumerate(rows):
        todo += _todo_from_slot(r, i)

    # 结构性项：期次 / 封面年月 —— 不填错就行，但要人看一眼
    for i, r in enumerate(rows):
        loc = r.get("location") or ""
        src = r.get("source") or ""
        if loc.startswith(_CONFIRM_PREFIX) or any(k in src for k in _CONFIRM_SOURCE):
            value = (r.get("new") or "").strip()
            # 标题带上位置与现值，而不是笼统的"期次/封面"——
            # 三条确认项长得不一样（封面期数 / 封面年月 / 大表列名），
            # 写笼统了人不知道要看哪个。
            todo.append({
                "id": f"confirm-{i}",
                "kind": "confirm",
                "title": f"{loc}：{value}" if value else f"{loc}（空）",
                "where": loc or "封面",
                "value": value,
                "source": src,
            })

    pending = [dict(t) for t in PENDING_TABLES]

    return {
        "period": period,
        "period_dir": pathlib.Path(out_dir).name,
        "traceable": {"n": len(rows), "with_source": traced},
        "todo": todo,
        "todo_fill": [t for t in todo if t["kind"] == "fill"],
        "todo_confirm": [t for t in todo if t["kind"] == "confirm"],
        "pending": pending,
        "approval": approval or {},
        # 二级入口（审计视图）：给工程/评委深挖用，不占首屏
        "audit_links": [
            {"label": "对勘本（正文级对照）", "href": f"/p/{period}"},
            {"label": "红色件清单", "href": f"/p/{period}/redslots"},
            {"label": "图表图册", "href": f"/p/{period}/charts"},
            {"label": "运行档案", "href": f"/p/{period}/archive"},
        ],
    }
