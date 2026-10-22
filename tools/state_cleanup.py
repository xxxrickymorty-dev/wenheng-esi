# -*- coding: utf-8 -*-
"""清理状态库里的审批流水：① e2e 残留（按期次删行）② 批注里的真人姓名（按词清空批注）。

两个子命令，都**默认只打印，`--apply` 才落库**：

**`e2e`（默认）**——按期次删掉 e2e 攒下的审批流水。

为什么要有这个：e2e 以前是「字节还原 `approval.json`」，跑崩过几次就把签/撤流水
攒在 `approval_history` 里（2026-10-22 查：202607 有 389 条，sign 195 / revoke 194，
批注多为「e2e 验收」）。演示站点开《审批记录.md》看到的就是测试痕迹。手敲 SQL 清一次不可复现，
所以收成一个可 audit 的工具：先打印将删哪些、留哪些、为什么，`--apply` 才真删。

判据只认证据（宁可留，不可误删——签单历史不可重建）：

1. 批注自述 `e2e` / `探针` / `probe`（历次 e2e 与探针都留了这个标记）；
2. 空批注，但与相邻（id 序前后一位）的 e2e 行**动作相反**且间隔 ≤ `PAIR_SECONDS`
   ——一签一撤的秒级成对，是 e2e 的典型形状。

其余一律保留：批注说的是人话（「彩排误触签单」「复核数据来源」）、空批注又不成对、
间隔超过窗口的疑似人手操作——**分不清就留**，报告里照实写。

`approvals` 行（这一期当前状态）只在**它自己**就是 e2e 产物时才删：`note` / `revoke_note`
非空且全部命中判据 → 最后一次签/撤是 e2e 干的，删完这一期回到「未签」。判不清就保留。

**`scrub-note`**——把批注里的真人姓名从**审计流水的源头**清掉（2026-10-22 rick 定）。

背景：202609 有一条历史批注写着「<人名>修改了学科数」，以前靠打包时
`--redact-term 词=馆员` 临时遮盖。那是**出口**的权宜，库和 `out/` 里照样是原名。
本子命令改**源头**：命中词的批注**整条清空成空串**（`note=""`，不是替换成「馆员修改了…」
——那会造出一条谁都没写过的批注），其余字段一字不动（`actor` / `at` / `action` /
`manual_ack` / `manual_open` 全留着）。**删改审计记录必须有备份与留痕**，所以 `--apply` 时：

- 先用 sqlite `backup` API 从**只读连接**做一致性副本 →
  `out/_state/backups/wenheng-<时间戳>-pre-note-scrub.sqlite`，打印路径 / 大小 / sha256 /
  `PRAGMA integrity_check`；备份失败就中止，一个字节都不改；
- 把被改行的**原始 payload**（含提升列的 ts / action / actor）存到
  `tmp/_cleanup_<期次>_note/before.json`；
- 一个短事务只改 `payload` 一列（`state_store.set_history_payload`：行数不变、提升列不变）；
- 落库后按 `server.approval` 的口径重写该期《审批记录.md》（导出件必须跟着库变）。

用法（在 `wenheng/` 下；也可 `uv run python -m tools.state_cleanup`）：

    uv run python tools\\state_cleanup.py --period 202607            # 只看（e2e 子命令是默认）
    uv run python tools\\state_cleanup.py --period 202607 --apply    # 真删 + 重写审批记录.md
    uv run python tools\\state_cleanup.py scrub-note --period 202609 --term 某某        # 先看
    uv run python tools\\state_cleanup.py scrub-note --period 202609 --term 某某 --apply
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sqlite3
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


class ScrubError(RuntimeError):
    """清批注中止（备份失败等）——调用方据此给非零退出码，不装作成功。"""


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


# --------------------------------------------------------------- 清批注里的人名
def parse_terms(raw_terms) -> list[str]:
    """`--term` 的取值：可重复给，也可逗号分隔；去空、去重、保序。"""
    terms: list[str] = []
    for raw in raw_terms or ():
        for piece in str(raw).replace("，", ",").split(","):
            piece = piece.strip()
            if piece and piece not in terms:
                terms.append(piece)
    if not terms:
        raise ScrubError("--term 至少要给一个词（例：--term 某某 或 --term 甲,乙）")
    return terms


def match_rows(rows, terms) -> list[dict]:
    """命中词的**历史行**：`[{row, note, matched}]`。

    只认 `payload.note`（条目里唯一自由文本），不碰 `actor` / `revoke_note` / 签单行——
    那是「谁签的」与另一条审计事实，本票未授权。命中即整条清空，不做局部替换。
    """
    out = []
    for row in rows:
        note = _note(row)
        matched = [t for t in terms if t and t in note]
        if matched:
            out.append({"row": row, "note": note, "matched": matched})
    return out


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_db(db, backups_dir, *, label="pre-note-scrub") -> dict:
    """sqlite `backup` API 做一致性副本（**只读连接读源**，WAL 未 checkpoint 也不会拿到半截）。

    源库用 `mode=ro` 打开：这一步不该有能力改真库。返回 `{path, size, sha256, integrity}`。
    备份不成功就不许改审计流水——调用方据此中止。
    """
    db = pathlib.Path(db).resolve()
    backups_dir = pathlib.Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"wenheng-{stamp}-{label}.sqlite"
    src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    con = sqlite3.connect(str(dest))
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    return {"path": dest, "size": dest.stat().st_size,
            "sha256": _sha256(dest), "integrity": integrity}


def write_before_json(path, period, terms, rows) -> pathlib.Path:
    """把被改行的**原始 payload** 留一份（含提升列，供人核对与万一回填）。"""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "period": str(period),
        "terms": list(terms),
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": [{"id": r["id"], "ts": r["ts"], "action": r["action"],
                  "actor": r["actor"], "payload": r["payload"]} for r in rows],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def run_scrub(period, db, terms, *, apply=False) -> int:
    """清一期批注里的指定词；返回将被改 / 已改的行数（`apply=False` 时是「将改」）。"""
    period = str(period)
    out_dir = ROOT / "out" / period
    rows = state_store.list_history(db, period)
    hits = match_rows(rows, terms)

    print(f"\n=== {period} ===")
    print(f"  历史：{_counts(rows)}")
    print(f"  命中 {len(hits)} 条（词：{'、'.join(terms)}）")
    for h in hits:
        row = h["row"]
        print(f"    #{row['id']:>5} {row['ts']} {row['action']:6s} {row['actor']:6s}"
              f"  原批注：{h['note']!r} → 改后：（空串）")
    if not hits:
        print("  → 没有命中（这一期已经是干净的）")
        return 0
    print("  改法：整条批注清空；actor / ts / action / payload 其余键一字不动；行数不变")

    if not apply:
        print("  （dry-run：只打印，未落库、未写备份；加 --apply 才改）")
        return len(hits)

    backups_dir = pathlib.Path(db).resolve().parent / "backups"
    try:
        backup = backup_db(db, backups_dir)
    except (sqlite3.Error, OSError) as exc:
        raise ScrubError(f"备份失败（{exc}）——没有备份不许改审计流水，库未改动") from exc
    if backup["integrity"] != "ok":
        raise ScrubError(f"备份副本 integrity_check={backup['integrity']!r}，库未改动")
    print(f"  [备份] {backup['path']}")
    print(f"         size={backup['size']} sha256={backup['sha256']}"
          f" integrity_check={backup['integrity']}")

    before_path = write_before_json(
        ROOT / "tmp" / f"_cleanup_{period}_note" / "before.json", period, terms,
        [h["row"] for h in hits])
    print(f"  [留痕] {before_path}（原始 payload，含 ts / action / actor）")

    payloads = {}
    for h in hits:
        payload = dict(h["row"]["payload"])
        payload["note"] = ""
        payloads[h["row"]["id"]] = payload
    changed = state_store.set_history_payload(db, period, payloads)
    print(f"  已落库：改 {changed} 条（一个短事务，只写 payload 一列）")
    _rewrite_record(out_dir)

    after = state_store.list_history(db, period)
    print(f"  复查：历史 {_counts(after)}（行数 {'不变' if len(after) == len(rows) else '变了！'}）")
    for h in hits:
        now = next((r for r in after if r["id"] == h["row"]["id"]), None)
        if now is None:
            raise ScrubError(f"#{h['row']['id']} 改完不见了——审计流水少了一行")
        print(f"    #{now['id']:>5} 批注={_note(now)!r}")
    return changed


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # 旧用法（`--period 202607 --apply`）仍然算 e2e 子命令：习惯与外部脚本不用改。
    if not raw or raw[0] not in ("e2e", "scrub-note", "-h", "--help"):
        raw.insert(0, "e2e")

    ap = argparse.ArgumentParser(
        description="清理状态库里的审批流水（默认 dry-run；两个子命令见下）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e2e = sub.add_parser("e2e", help="按期次删掉 e2e / 探针攒下的审批流水（默认子命令）")
    e2e.add_argument("--period", nargs="+", required=True, help="期次（目录名，如 202607）")
    e2e.add_argument("--db", default=None, help="状态库路径（默认 out/_state/wenheng.sqlite）")
    e2e.add_argument("--apply", action="store_true", help="真删（默认只打印）")

    scrub = sub.add_parser("scrub-note", help="把批注里的指定词（真人姓名）整条清空")
    scrub.add_argument("--period", nargs="+", required=True, help="期次（目录名，如 202609）")
    scrub.add_argument("--term", action="append", default=[], required=True,
                       metavar="词", help="要清的词；可重复给，也可逗号分隔")
    scrub.add_argument("--db", default=None, help="状态库路径（默认 out/_state/wenheng.sqlite）")
    scrub.add_argument("--apply", action="store_true", help="真改（默认只打印）")

    args = ap.parse_args(raw)

    db = pathlib.Path(args.db) if args.db else state_store.db_path(out_root=ROOT)
    if not db.is_file():
        print(f"[跳过] 状态库不存在：{db}")
        return 0
    print(f"状态库：{db}")
    print(f"模式：{'APPLY（会落库）' if args.apply else 'dry-run（只打印）'}")

    if args.cmd == "e2e":
        total = 0
        for period in args.period:
            total += run_period(period, db, apply=args.apply)
        if args.apply:
            print(f"\n合计删除历史 {total} 条")
        return 0

    try:
        terms = parse_terms(args.term)
        total = 0
        for period in args.period:
            total += run_scrub(period, db, terms, apply=args.apply)
    except ScrubError as exc:
        print(f"\n[中止] {exc}")
        return 1
    print(f"\n合计改批注 {total} 条" + ("" if args.apply else "（dry-run，未落库）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
