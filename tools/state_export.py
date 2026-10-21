# -*- coding: utf-8 -*-
"""把状态库反向导出成原格式文件（ADR-0012 决定 10：回退与审计用）。

- 只写 `out/<期次>/approval.json`、`review.json` 与 `manual_inputs.json`（原子写）；
- **幂等**：同库导出两次字节一致；**不删库、不删文件**（回退时旧文件可能残留，以库为准）；
  填写按库里的 rowid 序落盘，键序与迁移前那份文件相同——`manual_inputs.json` 是逐字节可比的；
- 不写 `审批记录.md`：它是签/撤时顺手导出的产物，不由本工具重造。

用法（在 `wenheng/` 下；也可 `uv run python -m tools.state_export`）：

    uv run python tools\\state_export.py                 # 导出库里所有期次
    uv run python tools\\state_export.py --period 202607
    uv run python tools\\state_export.py --root out/_state/attic   # 导到别处看/比对
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import atomic_io, state_store  # noqa: E402

APPROVAL_NAME = "approval.json"
REVIEW_NAME = "review.json"
FILLS_NAME = "manual_inputs.json"


def _dump(obj) -> str:
    """与 `approval.json` 历史写法同口径（indent=1、中文不转义、无尾换行）。"""
    return json.dumps(obj, ensure_ascii=False, indent=1)


def export_period(out_dir, db_path) -> list[str]:
    """导出一期；返回结果行。没有该期状态时一行都不写。"""
    out_dir = pathlib.Path(out_dir)
    period = out_dir.name
    lines = []

    rec = state_store.get_approval(db_path, period)
    if rec is None:
        lines.append(f"{period} · 审批：库里没有，跳过")
    else:
        atomic_io.write_text_atomic(out_dir / APPROVAL_NAME, _dump(rec))
        lines.append(f"{period} · 审批：导出 {len(rec.get('history') or [])} 条历史")

    reviews = state_store.get_reviews(db_path, period)
    if not reviews:
        lines.append(f"{period} · 复核：库里为空，未写 {REVIEW_NAME}")
    else:
        atomic_io.write_text_atomic(out_dir / REVIEW_NAME, _dump(reviews))
        lines.append(f"{period} · 复核：导出 {len(reviews)} 处存疑")

    fills = state_store.get_fills(db_path, period)
    if not fills:
        lines.append(f"{period} · 填写：库里为空，未写 {FILLS_NAME}")
    else:
        # 与旧 `workbench.save_fill` 的写法同口径（indent=1、中文不转义、无尾换行；
        # 换行为平台翻译，`atomic_io` 默认 newline=None）→ 与迁移前那份文件逐字节可比。
        atomic_io.write_text_atomic(out_dir / FILLS_NAME, _dump(fills))
        lines.append(f"{period} · 填写：导出 {len(fills)} 处填写")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="把状态库导出回 approval.json / review.json / manual_inputs.json")
    ap.add_argument("--root", default=str(ROOT), help="仓库根（默认本文件上一层）")
    ap.add_argument("--db", default=None, help="状态库路径（默认 out/_state/wenheng.sqlite）")
    ap.add_argument("--period", default=None, help="只导这一期（目录名）")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root).resolve()
    db = pathlib.Path(args.db) if args.db else state_store.db_path(out_root=root)
    if not db.is_file():
        print(f"[跳过] 状态库不存在：{db}")
        return 0
    periods = [args.period] if args.period else state_store.periods(db)
    if not periods:
        print(f"[跳过] 库里没有任何期次：{db}")
        return 0

    print(f"状态库：{db}")
    for period in periods:
        out_dir = root / "out" / period
        for line in export_period(out_dir, db):
            print("  " + line)
    print(f"完成：{len(periods)} 期导出到 {root / 'out'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
