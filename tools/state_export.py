# -*- coding: utf-8 -*-
"""把状态库反向导出成原格式文件（ADR-0012 决定 10：回退与审计用）。

- 只写 `out/<期次>/approval.json`、`review.json` 与 `manual_inputs.json`（原子写）；
- **导出件跟着真相源走**：库里**有**该记录 → 写；库里**没有** → 把残留的过期导出件**删掉**
  （留着会被下一次翻到的人当真相）。三类同一口径；除这三件外**一个文件都不碰**；
- **幂等**：同库导出两次字节一致；**不删库**；状态库不存在 → 一件都不删（无从判断，
  宁可留着也不误删）；填写按库里的 rowid 序落盘，键序与迁移前那份文件相同
  ——`manual_inputs.json` 是逐字节可比的；
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


def _drop_export(out_dir, name, period, label, lines) -> None:
    """库里没有这份状态 → 移除残留导出件（不存在则什么都不做）。

    🔴 导出件是「旧真相」：库里已经没有的签单/存疑/填值还留在目录里，下一个翻到它的人就会
    把它当真相。所以这里的口径是「没有就删」，而不是「没有就不写」。删的是**这一个文件名**，
    同目录的其他产物（`审批记录.md` / `red_slots.json` / `table2.csv` …）一律不碰。
    """
    path = pathlib.Path(out_dir) / name
    if not path.exists():
        lines.append(f"{period} · {label}：库里没有，无 {name}（无需删除）")
        return
    try:
        path.unlink()
    except OSError as exc:                       # 文件被占用：如实报，不装作删了
        lines.append(f"{period} · {label}：库里没有，删除过期导出 {name} 失败：{exc}")
        return
    lines.append(f"{period} · {label}：库里没有，已删除过期导出 {name}")


def export_period(out_dir, db_path) -> list[str]:
    """导出一期；返回结果行。库里没有的记录 → 删掉对应的过期导出件。"""
    out_dir = pathlib.Path(out_dir)
    period = out_dir.name
    lines = []

    # 库不存在时读口一律返回「没有」（`get_approval` → None / `get_reviews` → `{}`），
    # 这时候删文件等于凭「没库」把导出件全清掉——刚 clone、库还没建就会中招。所以先拦住。
    if not pathlib.Path(db_path).is_file():
        lines.append(f"{period} · 状态库不存在，未导出也未删除任何文件")
        return lines

    rec = state_store.get_approval(db_path, period)
    if rec is None:
        _drop_export(out_dir, APPROVAL_NAME, period, "审批", lines)
    else:
        atomic_io.write_text_atomic(out_dir / APPROVAL_NAME, _dump(rec))
        lines.append(f"{period} · 审批：导出 {len(rec.get('history') or [])} 条历史")

    reviews = state_store.get_reviews(db_path, period)
    if not reviews:
        _drop_export(out_dir, REVIEW_NAME, period, "复核", lines)
    else:
        atomic_io.write_text_atomic(out_dir / REVIEW_NAME, _dump(reviews))
        lines.append(f"{period} · 复核：导出 {len(reviews)} 处存疑")

    fills = state_store.get_fills(db_path, period)
    if not fills:
        _drop_export(out_dir, FILLS_NAME, period, "填写", lines)
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
