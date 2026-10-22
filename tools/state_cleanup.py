# -*- coding: utf-8 -*-
"""按期次清掉状态库里 **e2e 攒下的审批流水**（默认只打印，`--apply` 才落库）。

**为什么要有这个工具**：e2e 以前是「字节还原 `approval.json`」，跑崩过几次就把签/撤流水
攒在 `approval_history` 里（2026-10-22 查：202607 有 389 条，sign 195 / revoke 194，
批注多为「e2e 验收」）。演示站点开《审批记录.md》看到的就是测试痕迹。手敲 SQL 清一次不可复现，
所以收成一个可 audit 的工具：先打印将删哪些、留哪些、为什么，`--apply` 才真删。

**判据只认证据**（宁可留，不可误删——签单历史不可重建）：

1. 批注自述 `e2e` / `探针` / `probe`（历次 e2e 与探针都留了这个标记）；
2. 空批注，但与相邻（id 序前后一位）的 e2e 行**动作相反**且间隔 ≤ `PAIR_SECONDS`
   ——一签一撤的秒级成对，是 e2e 的典型形状。

其余一律保留：批注说的是人话（「彩排误触签单」「复核数据来源」）、空批注又不成对、
间隔超过窗口的疑似人手操作——**分不清就留**，报告里照实写。

`approvals` 行（这一期当前状态）只在**它自己**就是 e2e 产物时才删：`note` / `revoke_note`
非空且全部命中判据 → 最后一次签/撤是 e2e 干的，删完这一期回到「未签」。判不清就保留。

**落库后**按 `server.approval` 的口径重写《审批记录.md》（它是导出件，必须跟着库变；
`tools/state_export.py` 不写它——那份文件是签/撤时顺手导出的产物）。

用法（在 `wenheng/` 下；也可 `uv run python -m tools.state_cleanup`）：

    uv run python tools\\state_cleanup.py --period 202607            # 只看（默认 dry-run）
    uv run python tools\\state_cleanup.py --period 202607 --apply    # 真删 + 重写审批记录.md
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import approval                                       # noqa: E402
from src import state_store                                       # noqa: E402

#: e2e / 探针在批注里留的自述标记（不区分大小写）。
E2E_MARK = re.compile(r"e2e|探针|probe", re.I)
#: 「秒级成对」的窗口（一种动作到另一种动作之间）。
PAIR_SECONDS = 5


def _note(row) -> str:
    return str((row.get("payload") or {}).get("note") or "")


def _ts(row):
    try:
        return datetime.datetime.strptime(str(row.get("ts") or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _pair_twin(rows, i, marked):
    """相邻（id 序前后一位）、动作相反、间隔 ≤ PAIR_SECONDS 的 e2e 行；没有 → None。"""
    me, mine = rows[i], _ts(rows[i])
    for j in (i - 1, i + 1):
        if not 0 <= j < len(rows):
            continue
        other = rows[j]
        if other["id"] not in marked or other["action"] == me["action"]:
            continue
        theirs = _ts(other)
        if mine and theirs and abs((theirs - mine).total_seconds()) <= PAIR_SECONDS:
            return other
    return None


def classify(rows):
    """历史行分类：`[{row, delete, reason}]`。命中证据才 `delete=True`，其余保留。"""
    marked = {r["id"] for r in rows if E2E_MARK.search(_note(r))}
    out = []
    for i, row in enumerate(rows):
        note = _note(row)
        if row["id"] in marked:
            out.append({"row": row, "delete": True, "reason": f"批注自述 e2e/探针：{note}"})
            continue
        if not note.strip():
            twin = _pair_twin(rows, i, marked)
            if twin is not None:
                out.append({"row": row, "delete": True,
                            "reason": f"空批注，但与 #{twin['id']}（e2e）在 {PAIR_SECONDS}s 内成对"})
                continue
            out.append({"row": row, "delete": False, "reason": "空批注且不成对 → 保留"})
            continue
        out.append({"row": row, "delete": False, "reason": f"批注无从判定：{note}"})
    return out


def classify_approval(rec):
    """当前签单行：`(delete, reason)`。只有它自己就是 e2e 产物才删。"""
    if rec is None:
        return False, "库里没有这一期的签单行（本来就是未签）"
    marks = [str(v).strip() for v in (rec.get("note"), rec.get("revoke_note"))
             if str(v or "").strip()]
    if marks and all(E2E_MARK.search(m) for m in marks):
        return True, "签单行本身是 e2e 产物（批注：" + " / ".join(marks) + "）"
    return False, "签单行的批注不是 e2e 或为空，分不清 → 保留"


def _counts(rows) -> str:
    sign = sum(1 for r in rows if r["action"] == "sign")
    revoke = sum(1 for r in rows if r["action"] == "revoke")
    return f"{len(rows)} 条（sign {sign} / revoke {revoke}）"


def _state(rec) -> str:
    if rec is None:
        return "未签"
    return "已签" if rec.get("signed") else "未签"


def run_period(period, db, *, apply=False) -> int:
    """处理一期；返回删除的历史行数。"""
    out_dir = ROOT / "out" / period
    rec = state_store.get_approval(db, period)
    rows = state_store.list_history(db, period)
    verdicts = classify(rows)
    doomed = [v for v in verdicts if v["delete"]]
    kept = [v for v in verdicts if not v["delete"]]
    drop_rec, rec_reason = classify_approval(rec)

    print(f"\n=== {period} ===")
    print(f"  签单行：{_state(rec)}"
          + (f"（签单人 {rec.get('actor')!r}，{rec.get('signed_at')}）" if rec else "")
          + (f" → 将删除：{rec_reason}" if drop_rec else f" → 保留：{rec_reason}"))
    print(f"  历史：{_counts(rows)}")
    print(f"    将删 {_counts([v['row'] for v in doomed])}")
    print(f"    保留 {_counts([v['row'] for v in kept])}")

    print("    --- 明细（删=命中 e2e 证据 / 留=分不清或像人手点的）---")
    for v in verdicts:
        row = v["row"]
        tag = "删" if v["delete"] else "留"
        print(f"    {tag} #{row['id']:>5} {row['ts']} {row['action']:6s} "
              f"{row['actor']:6s} {v['reason']}")

    after_rec = None if drop_rec else rec
    print(f"  删后预计：历史 {_counts([v['row'] for v in kept])}；状态 {_state(after_rec)}")
    if not doomed and not drop_rec:
        print("  → 没有可删的行（已经是干净的）")
        return 0

    if not apply:
        print("  （dry-run：只打印，未落库；加 --apply 才删）")
        return 0

    removed = state_store.delete_history(db, period, [v["row"]["id"] for v in doomed])
    dropped = state_store.delete_approval(db, period) if drop_rec else False
    print(f"  已落库：删历史 {removed} 条" + ("，删签单行 1 条" if dropped else ""))
    _rewrite_record(out_dir)

    rows = state_store.list_history(db, period)
    rec = state_store.get_approval(db, period)
    print(f"  复查：历史 {_counts(rows)}；签单行 {_state(rec)}")
    return removed


def _rewrite_record(out_dir):
    """按 `server.approval` 的口径重写《审批记录.md》（导出件必须跟着库变）。"""
    if not pathlib.Path(out_dir).is_dir():
        print(f"  ⚠ {out_dir} 不存在，跳过《审批记录.md》")
        return
    rec = approval.read(out_dir)
    approval._write_record(pathlib.Path(out_dir), rec)             # noqa: SLF001 同一个口径，不另写一份渲染
    print(f"  已重写 {pathlib.Path(out_dir) / approval.RECORD_NAME}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="清掉状态库里 e2e 攒下的审批流水（默认 dry-run）")
    ap.add_argument("--period", nargs="+", required=True, help="期次（目录名，如 202607）")
    ap.add_argument("--db", default=None, help="状态库路径（默认 out/_state/wenheng.sqlite）")
    ap.add_argument("--apply", action="store_true", help="真删（默认只打印）")
    args = ap.parse_args(argv)

    db = pathlib.Path(args.db) if args.db else state_store.db_path(out_root=ROOT)
    if not db.is_file():
        print(f"[跳过] 状态库不存在：{db}")
        return 0
    print(f"状态库：{db}")
    print(f"模式：{'APPLY（会落库）' if args.apply else 'dry-run（只打印）'}")
    total = 0
    for period in args.period:
        total += run_period(period, db, apply=args.apply)
    if args.apply:
        print(f"\n合计删除历史 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
