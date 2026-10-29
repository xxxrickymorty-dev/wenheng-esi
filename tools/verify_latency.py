# -*- coding: utf-8 -*-
"""核验时长度量：从「报告出稿」到「签单」隔了多久。

**只读工具，不进流水线、不重出报告、不写 `out/`。**

为什么量这个
────────────────────────────────────────────────────────────────
红件清单的用法是「打开初稿，逐条对 source」。签单离出稿越远，签单时打开的
就越可能不是同一份稿（重跑过、补过图、改过表）。这个工具把间隔摆出来，让
「签得快」和「签得久」都可见 —— 它只报事实，不设通过线。

数据源（**按可用性降级，并把用了哪一档写进报告**）
────────────────────────────────────────────────────────────────
出稿时刻：
    1. `run_log.json` 里的时间字段（`finished_at` / `generated_at` / `created_at` /
       `at`；或 `started_at` + `elapsed_sec` 现算）
    2. 报告初稿 docx 的 mtime
    3. 都没有 → 「无出稿时间」
签单时刻：
    1. `approval.json` 的 `signed_at`
    2. `approval.json` 的 `history` 里最后一条 `action == "sign"` 的 `at`
    3. 都没有 / `signed` 不为真 → 「未签单」

⚠ 事实记录（2026-10-29 实测）：`run_log.json` 目前**没有**任何时间字段，只有
`elapsed_sec`；因此现实中日期间隔一律走 docx mtime 那一档。

用法：
    python tools/verify_latency.py                 # 最新一期
    python tools/verify_latency.py --period 202609
    python tools/verify_latency.py --all
    python tools/verify_latency.py --all --json

退出码：0 正常（未签单不算错误，照实打印）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "out"
DOCX_GLOB = "报告初稿_*.docx"

#: run_log.json 里可能表示「跑完时刻」的键，按优先级
RUN_LOG_TIME_KEYS = ("finished_at", "generated_at", "created_at", "at")

#: 退而求其次：开始时刻 + 耗时
RUN_LOG_START_KEY = "started_at"
RUN_LOG_ELAPSED_KEY = "elapsed_sec"

#: 间隔显示口径：不足这个小时数按小时写，否则按天写
HOURS_THRESHOLD = 48.0

UNSIGNED = "未签单"
NO_DRAFT = "无出稿时间"


# ---------------------------------------------------------------- 解析
def parse_time(value) -> datetime | None:
    """容错解析：`2026-10-17 13:51:33` / ISO8601 / 带时区 / 空值。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def draft_time(period_dir: pathlib.Path) -> tuple[datetime | None, str]:
    """→ (时刻, 来源说明)。"""
    log = _read_json(period_dir / "run_log.json")
    if isinstance(log, dict):
        for key in RUN_LOG_TIME_KEYS:
            got = parse_time(log.get(key))
            if got:
                return got, f"run_log.{key}"
        start = parse_time(log.get(RUN_LOG_START_KEY))
        elapsed = log.get(RUN_LOG_ELAPSED_KEY)
        if start and isinstance(elapsed, (int, float)):
            return start + timedelta(seconds=float(elapsed)), \
                f"run_log.{RUN_LOG_START_KEY}+{RUN_LOG_ELAPSED_KEY}"

    docs = sorted(period_dir.glob(DOCX_GLOB))
    if docs:
        # 同一期可能留了多份初稿，取最新那份的 mtime
        newest = max(docs, key=lambda p: p.stat().st_mtime)
        return datetime.fromtimestamp(newest.stat().st_mtime), "docx mtime"

    return None, ""


def sign_time(period_dir: pathlib.Path) -> tuple[datetime | None, str]:
    """→ (签单时刻, 备注)。没签单返回 (None, 原因)。"""
    path = period_dir / "approval.json"
    if not path.is_file():
        return None, "无 approval.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return None, "approval.json 解析失败"
    if data.get("signed") is not True:
        return None, "approval.signed 不为真"
    got = parse_time(data.get("signed_at"))
    if got:
        return got, ""
    hist = data.get("history")
    if isinstance(hist, list):
        stamps = [parse_time(h.get("at")) for h in hist
                  if isinstance(h, dict) and h.get("action") == "sign"]
        stamps = [s for s in stamps if s]
        if stamps:
            return max(stamps), "取自 history.sign.at"
    return None, "approval.json 无可用时间字段"


def format_gap(hours: float) -> str:
    return f"{hours:.1f} 小时" if abs(hours) < HOURS_THRESHOLD else f"{hours / 24:.1f} 天"


def measure(period: str, period_dir: pathlib.Path) -> dict:
    """一期 → 一行事实。所有分支都给结论，不跳过任何一期。"""
    draft, draft_src = draft_time(period_dir)
    signed, sign_note = sign_time(period_dir)

    row = {
        "period": period,
        "draft_at": draft.strftime("%Y-%m-%d %H:%M:%S") if draft else "",
        "draft_source": draft_src or NO_DRAFT,
        "signed_at": signed.strftime("%Y-%m-%d %H:%M:%S") if signed else "",
        "gap_hours": None,
        "gap_text": "",
        "status": "",
        "note": "",
    }
    if signed is None:
        row["status"] = UNSIGNED
        row["note"] = sign_note
        return row
    if draft is None:
        row["status"] = NO_DRAFT
        row["note"] = "签单了但找不到出稿时刻，无法算间隔"
        return row

    hours = (signed - draft).total_seconds() / 3600.0
    row["gap_hours"] = round(hours, 2)
    row["gap_text"] = format_gap(hours)
    if hours < 0:
        row["status"] = "倒挂"
        row["note"] = "签单时刻早于出稿时刻（可能是签单后又重出了稿）"
    else:
        row["status"] = "已签单"
        row["note"] = sign_note
    return row


def render(rows: list[dict]) -> str:
    head = f"{'期次':<8}{'出稿时刻':<21}{'出稿来源':<13}{'签单时刻':<21}{'间隔':<11}备注"
    lines = ["== 核验时长度量（出稿 → 签单）==", "", head, "-" * 100]
    for r in rows:
        draft = r["draft_at"] or NO_DRAFT
        source = r["draft_source"]
        signed = r["signed_at"] or r["status"]
        gap = r["gap_text"] or "-"
        note = r["note"]
        if r["status"] == UNSIGNED:
            note = f"{UNSIGNED}：{r['note']}"
        lines.append(f"{r['period']:<8}{draft:<21}{source:<14}{signed:<21}{gap:<11}{note}")
    lines.append("-" * 100)

    signed = [r for r in rows if r["signed_at"]]
    inverted = [r["period"] for r in rows if r["status"] == "倒挂"]
    unsigned = [r["period"] for r in rows if r["status"] == UNSIGNED]
    lines.append(f"共 {len(rows)} 期，有签单记录 {len(signed)} 期，未签单 {len(unsigned)} 期"
                 + (f"（{', '.join(unsigned)}）" if unsigned else ""))
    if inverted:
        lines.append(f"其中倒挂 {len(inverted)} 期（{', '.join(inverted)}）："
                     "签单时刻早于当前初稿的 mtime，说明签单后又重出过稿")
    vals = [r["gap_hours"] for r in signed if r["gap_hours"] is not None and r["gap_hours"] >= 0]
    if vals:
        lines.append(f"正间隔区间：{format_gap(min(vals))} ~ {format_gap(max(vals))}"
                     f"；中位数 {format_gap(sorted(vals)[len(vals) // 2])}")
    lines.append("")
    lines.append("出稿时刻来源：run_log 时间字段优先，缺则降级为 docx mtime（「出稿来源」列已注明）。")
    return "\n".join(lines)


def periods_of(args) -> list[str]:
    if args.all:
        names = sorted(p.parent.name for p in OUT_ROOT.glob(f"*/{DOCX_GLOB}"))
        names += [p.parent.name for p in OUT_ROOT.glob("*/approval.json")]
        found = sorted({n for n in names})
        if not found:
            raise SystemExit(f"out/ 下没有可度量的期次：{OUT_ROOT}")
        return found
    if args.period:
        return list(args.period)
    names = sorted(p.parent.name for p in OUT_ROOT.glob(f"*/{DOCX_GLOB}"))
    if not names:
        raise SystemExit(f"out/ 下没有报告初稿：{OUT_ROOT}")
    return [names[-1]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核验时长度量（只读）")
    ap.add_argument("--period", action="append", default=[], help="期次，可重复")
    ap.add_argument("--all", action="store_true", help="扫 out/*/")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    rows, missing = [], []
    for period in periods_of(args):
        d = OUT_ROOT / period
        if not d.is_dir():
            missing.append(period)
            continue
        rows.append(measure(period, d))

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(render(rows))
    if missing:
        print(f"\nout/ 下没有这些期次目录：{', '.join(missing)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
