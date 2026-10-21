# -*- coding: utf-8 -*-
"""把现有 `out/*/approval.json`、`out/*/review.json`、`out/_jobs/*/job.json`
**显式**导入状态库（ADR-0012 决定 10）。

- **幂等**：库里已有该期 / 该任务 id → 跳过（不覆盖）；重复跑结果一致。
  空文件也报「空」而不是反复导入；
- **不删原文件**：迁移期两处都在，但之后**只有库是真相**（`approval.json`/`review.json`
  降为导出件，回退用 `tools/state_export.py`；`job.json` 入库后谁都不再读它）；
- 逐项打印：**导入 / 已存在跳过 / 形状非法**——隐式行为难调试，所以这里一句都不省。

用法（在 `wenheng/` 下；也可 `uv run python -m tools.state_import`）：

    uv run python tools\\state_import.py                  # 扫 out/ 下所有期次目录 + 全部任务记录
    uv run python tools\\state_import.py --period 202607  # 只导一期（任务记录仍是全量）
    uv run python tools\\state_import.py --db D:\\tmp\\x.sqlite

只写 `out/_state/wenheng.sqlite`（或 `--db` / `WENHENG_STATE_DB`），**一个字节都不碰产物与母本**。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import state_store  # noqa: E402

#: 期次目录名：`202607` / `202605_复现` / `202607_2` 都算；`_jobs`、`_archive` 不算。
PERIOD_RE = re.compile(r"^\d{6}(?:[_-].*)?$")
APPROVAL_NAME = "approval.json"
REVIEW_NAME = "review.json"
JOB_NAME = "job.json"


def _period_dirs(out_root: pathlib.Path):
    if not out_root.is_dir():
        return []
    return sorted(p for p in out_root.iterdir() if p.is_dir() and PERIOD_RE.match(p.name))


def _read_json(path: pathlib.Path):
    """读 JSON → `(obj, 问题)`；问题非空即形状非法，不猜、不落行。"""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"形状非法（{exc}）"
    return obj, ""


def _approval_record(path: pathlib.Path):
    """`approval.json` → `(含 history 的记录, 问题)`。"""
    rec, problem = _read_json(path)
    if problem:
        return None, problem
    if not isinstance(rec, dict):
        return None, "形状非法（顶层不是对象）"
    history = rec.get("history")
    if history is None:
        rec["history"] = []
    elif not isinstance(history, list) or any(not isinstance(h, dict) for h in history):
        return None, "形状非法（history 不是对象数组）"
    return rec, ""


def _review_map(path: pathlib.Path):
    """`review.json` → `({位置: {state, by, at}}, 问题)`。"""
    data, problem = _read_json(path)
    if problem:
        return None, problem
    if not isinstance(data, dict):
        return None, "形状非法（顶层不是对象）"
    for key, item in data.items():
        if not isinstance(item, dict) or not item.get("state"):
            return None, f"形状非法（{key!r} 不是 {{state, by, at}}）"
    return data, ""


def import_period(out_dir, db_path) -> list[str]:
    """导入一期；返回逐项结果行（幂等：已有则跳过、原文件不动）。"""
    out_dir = pathlib.Path(out_dir)
    period = out_dir.name
    lines = []

    approval_file = out_dir / APPROVAL_NAME
    if not approval_file.is_file():
        lines.append(f"{period} · 审批：无 {APPROVAL_NAME}，跳过")
    else:
        rec, problem = _approval_record(approval_file)
        if problem:
            lines.append(f"{period} · 审批：{problem}，未导入")
        elif state_store.get_approval(db_path, period) is not None:
            lines.append(f"{period} · 审批：已存在跳过（库里已有，不覆盖）")
        else:
            try:
                state_store.replace_approval(db_path, period, rec)
            except state_store.StoreError as exc:
                lines.append(f"{period} · 审批：写入失败（{exc}），未导入")
            else:
                lines.append(f"{period} · 审批：导入 {len(rec.get('history') or [])} 条历史")

    review_file = out_dir / REVIEW_NAME
    if not review_file.is_file():
        lines.append(f"{period} · 复核：无 {REVIEW_NAME}，跳过")
    else:
        data, problem = _review_map(review_file)
        if problem:
            lines.append(f"{period} · 复核：{problem}，未导入")
        elif not data:
            lines.append(f"{period} · 复核：空文件，无内容可导入")
        elif state_store.get_reviews(db_path, period):
            lines.append(f"{period} · 复核：已存在跳过（库里已有，不覆盖）")
        else:
            try:
                state_store.replace_reviews(db_path, period, data)
            except state_store.StoreError as exc:
                lines.append(f"{period} · 复核：写入失败（{exc}），未导入")
            else:
                lines.append(f"{period} · 复核：导入 {len(data)} 处存疑")
    return lines


def import_jobs(jobs_dir, db_path) -> list[str]:
    """把 `out/_jobs/*/job.json` 导入任务记录；返回逐项结果行（幂等：已有 id 跳过）。"""
    jobs_dir = pathlib.Path(jobs_dir)
    if not jobs_dir.is_dir():
        return ["任务记录：任务目录不存在，跳过"]
    cands = sorted(jobs_dir.glob(f"*/{JOB_NAME}"))
    if not cands:
        return ["任务记录：没有 job.json，跳过"]
    lines = []
    for path in cands:
        rec, problem = _job_record(path)
        job_id = path.parent.name
        if problem:
            lines.append(f"任务 {job_id}：{problem}，未导入")
        elif state_store.get_job(db_path, rec["id"]) is not None:
            lines.append(f"任务 {job_id}：已存在跳过（库里已有，不覆盖）")
        else:
            try:
                state_store.put_job(db_path, rec)
            except state_store.StoreError as exc:
                lines.append(f"任务 {job_id}：写入失败（{exc}），未导入")
            else:
                lines.append(f"任务 {job_id}：导入（{rec.get('status') or '无状态'} · "
                             f"{rec.get('period') or '无期次'}）")
    return lines


def _job_record(path: pathlib.Path):
    """`job.json` → `(任务记录, 问题)`；没有 id 就没法做幂等键，按形状非法处理。"""
    rec, problem = _read_json(path)
    if problem:
        return None, problem
    if not isinstance(rec, dict):
        return None, "形状非法（顶层不是对象）"
    if not rec.get("id"):
        return None, "形状非法（缺 id）"
    return rec, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把 approval.json / review.json / job.json 显式导入状态库")
    ap.add_argument("--root", default=str(ROOT), help="仓库根（默认本文件上一层）")
    ap.add_argument("--db", default=None, help="状态库路径（默认 out/_state/wenheng.sqlite）")
    ap.add_argument("--period", default=None, help="只导这一期（目录名）")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root).resolve()
    db = pathlib.Path(args.db) if args.db else state_store.db_path(out_root=root)
    out_root = root / "out"
    dirs = [out_root / args.period] if args.period else _period_dirs(out_root)
    if not dirs:
        print(f"[跳过] {out_root} 下没有期次目录")
        return 0

    print(f"状态库：{db}")
    total = 0
    for out_dir in dirs:
        if not out_dir.is_dir():
            print(f"[跳过] {out_dir} 不存在")
            continue
        for line in import_period(out_dir, db):
            print("  " + line)
            total += 1
    print(f"完成：{len(dirs)} 期 · {total} 项（审批+复核）")

    job_lines = import_jobs(out_root / "_jobs", db)
    for line in job_lines:
        print("  " + line)
    n_imported = sum(1 for line in job_lines if "：导入（" in line)
    print(f"任务记录：导入 {n_imported} 条 / 处理 {len(job_lines)} 项")
    health = state_store.health(db)
    print(f"库状态：schema {health['schema_version']}/{health['code_version']}"
          f"{' · 降级只读：' + health['note'] if health['degraded'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
