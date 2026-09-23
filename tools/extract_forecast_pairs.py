# -*- coding: utf-8 -*-
"""自动维护台账《实际与预测差值》——方法 B（InCites + 历史差值校准）的校准语料。

口径（2026-09-23 用 35 个历史块逐格实测钉死）
------------------------------------------------
· 每期一块 3 行：A 列块标签 = 覆盖窗口 + （期次月），如 `2016.1.1-2026.6.30（2026.09）`；
  覆盖窗口算法与 `src/compute.py` 的 coverage_window 完全一致（期末 = 期次月 - 3，整十年 1.1 起）。
· 第 1 行 `incite` = InCites 快照值：论文数 | 被引频次 | 国际排名 | 国内排名（SNAP_MAP 当期快照）。
· 第 2 行 `esi`   = ESI 包值：论文数/被引 = 云大在学科榜那行；国际排名 = ESI「序号」；
  国内排名 = 中国大陆条目内序号。**未进榜学科写空**（历史块如此；绝不写 0——0 会被
  forecast 的历史差值均值当成真实值，污染下一期校准）。
· 第 3 行 `差值` = esi - incite（esi 空则清空）。
· 学科列固定 14 个（表头第 1 行每 4 列一组：中文名 → DISCIPLINES_CN 反查）。

写回纪律同其它清洗工具：zip 级 XML、写前自检、冲突拒写（esi 行的 0 视为占位可覆盖）、
--write 自动备份。语义上它补的正是「馆员原来要提供的 ESI 实际值」——现在两路数据都能自动出。

用法（wenheng/ 下，.venv 的 python）：
    python tools\\extract_forecast_pairs.py 202607                  # 预览 + 与台账逐格比对
    python tools\\extract_forecast_pairs.py 202607 --out tmp\\x.xlsx # 写副本
    python tools\\extract_forecast_pairs.py 202607 --write          # 写台账（自动备份）
"""
from __future__ import annotations

import argparse
import calendar
import pathlib
import sys

import openpyxl

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import extract_incites as T                                                    # noqa: E402
import parse_ledger as PL                                                      # noqa: E402
from extract_matrix import SNAP_MAP                                            # noqa: E402

SHEET = "实际与预测差值"
CN2EN = {v: k for k, v in PL.DISCIPLINES_CN.items()}


def en_of(name: str):
    """中文（含台账手写变体）→ 规范英文名。"""
    n = PL.norm_disc_cn(name)
    return CN2EN.get(n) or CN2EN.get(PL.ENTRY_CN_ALIAS.get(n))


def coverage_window(period: str) -> str:
    y, m = int(period[:4]), int(period[4:])
    end_y, end_m = (y, m - 3) if m > 3 else (y - 1, m + 9)
    return f"{end_y - 10}.1.1-{end_y}.{end_m}.{calendar.monthrange(end_y, end_m)[1]}"


def block_label(period: str) -> str:
    return f"{coverage_window(period)}（{period[:4]}.{period[4:]}）"


def read_gap(g, shared):
    """→ (块行 {incite/esi/差值: rn}, [(列首, 中文名, EN 名)])"""
    groups = []
    hdr = g.get(1, {})
    for cn, (a, i) in sorted(hdr.items(), key=lambda kv: T.col_index(kv[0])):
        if T.col_index(cn) % 4 == 3 and T.col_index(cn) >= 3:      # 1-based：学科组首列 3,7,11,…
            name = str(T.gtext(g, shared, 1, cn) or "").strip()
            if name:
                groups.append((cn, name, en_of(name)))
    blocks = {}
    cur = None
    for rn in sorted(g):
        lab = str(T.gtext(g, shared, rn, "A") or "").strip()
        src = str(T.gtext(g, shared, rn, "B") or "").strip()
        if lab:
            cur = lab
        if src in ("incite", "esi", "差值") and cur is not None:
            blocks.setdefault(cur, {})[src] = rn
    return blocks, groups


def collect(period: str, esi_dir: pathlib.Path, snap_dir: pathlib.Path):
    """→ ({EN: incite 4 元组或 None}, {EN: esi 4 元组或 None})"""
    snap = T.read_incites_snapshot(snap_dir)
    incite = {s: (v["papers"], v["cites"], v["rank"], v["cn_rank"]) for s, v in snap.items()}
    esi = {}
    for s in PL.DISCIPLINES_EN:
        p = T._resolve_file(esi_dir, s)
        if p is None:
            raise SystemExit(f"[缺件] ESI 包 {esi_dir.name} 里没有 {s}")
        r = T.read_esi_list(p)
        esi[s] = ((r["y_docs"], r["y_cites"], r["ypos"], r["cn_pos"])
                  if r["ypos"] and r["y_docs"] is not None else None)
    return incite, esi


def main() -> int:
    ap = argparse.ArgumentParser(description="《实际与预测差值》三行自动维护（校准语料）")
    ap.add_argument("period")
    ap.add_argument("--snapshot", default=None, help="InCites 快照目录名（默认走 SNAP_MAP）")
    ap.add_argument("--esi-root", default=str(T.ESI_ROOT))
    ap.add_argument("--ledger", default=str(T.LEDGER))
    ap.add_argument("--out", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    period = args.period
    ledger = pathlib.Path(args.ledger)
    snap_name = SNAP_MAP.get(period) or args.snapshot
    if not snap_name:
        raise SystemExit(f"[拒绝] {period} 未登记 InCites 快照（SNAP_MAP：{sorted(SNAP_MAP)}）")
    snap_dir = T.INCITES_ROOT / snap_name
    esi_dir = pathlib.Path(args.esi_root) / period
    if not (snap_dir.is_dir() and esi_dir.is_dir()):
        raise SystemExit(f"[拒绝] 缺数据：{snap_dir} / {esi_dir}")

    label = block_label(period)
    g, shared = T.read_grid(ledger, SHEET)
    blocks, groups = read_gap(g, shared)
    rows = blocks.get(label)
    append_block = False
    if rows is None:
        near = [k for k in blocks if k.startswith(coverage_window(period))]
        if near:
            rows, label = blocks[near[0]], near[0]
        else:
            append_block = True
            print(f"[i] 表里没有 {label} 的块 → 将在表尾新建 3 行（incite/esi/差值）")
    incite, esi = collect(period, esi_dir, snap_dir)
    block = rows or {}
    kinds = ("incite", "esi", "差值")

    # 期望值 + 冲突（已有块逐格比对；新块先记账号后补行号）
    expect_fixed: dict = {}
    expect_new: dict = {}
    conflicts = []
    for cn, cn_name, en in groups:
        if en is None:
            continue
        col0 = T.col_index(cn)
        iv = incite.get(en)
        ev = esi.get(en)
        dv = tuple(i - e for i, e in zip(iv, ev)) if (ev and iv) else None   # 台账口径：差值 = incite − esi
        for k, kind in enumerate(kinds):
            v = (iv, ev, dv)[k]
            rn = block.get(kind)
            for t in range(4):
                new = v[t] if v is not None else None
                c = T.col_letter(col0 + t)
                if rn is None:
                    expect_new[(k, col0, t)] = new
                    continue
                cell = T.gtext(g, shared, rn, c)
                if k == 0 and cell not in (None, "") and not T._eq(cell, new):
                    conflicts.append((f"incite·{cn_name}·{t}", cell, new))
                    continue
                if (k == 1 and cell not in (None, "") and T._num(cell) not in (0.0,)
                        and not T._eq(cell, new)):
                    conflicts.append((f"esi·{cn_name}·{t}", cell, new))
                    continue
                expect_fixed[(rn, c)] = new

    if not conflicts and not append_block:
        print(f"== [✓] 与台账现有值逐格一致（{len(groups)} 学科 × 4 指标 × 3 行）")
    if conflicts:
        print(f"[!] 与台账现有值冲突 {len(conflicts)} 处：")
        for loc, old, new in conflicts[:15]:
            print(f"    {loc}: 台账 {old} ≠ 新算 {new}")
        if not args.force:
            print("    → 拒绝写入；确认后 --force")
            return 1
    print(f"== {period} 块「{label}」：学科组 {len(groups)}，"
          f"incite {sum(1 for v in incite.values() if v)} 科，esi 在榜 {sum(1 for v in esi.values() if v)} 科")
    for cn, cn_name, en in groups:
        if en is None:
            continue
        if esi.get(en):
            print(f"    {cn_name}: incite={incite.get(en)} → esi={esi[en]}")
        else:
            print(f"    {cn_name}: incite={incite.get(en)} → esi=（未进榜，写空）")
    if not (args.write or args.out):
        print("\n（预览模式。--out 写副本 / --write 写台账）")
        return 0

    tx = T.LedgerTx(ledger)
    xml = tx.sheet_xml(SHEET)
    max_col = max(T.col_index(c) for c in g.get(1, {"BF": None})) if g.get(1) else 58
    if append_block:                                       # 建块：3 行（样式借最后一个同名块）
        last = max(blocks.values(), key=lambda d: d["incite"])
        base = T.max_row_xml(xml) + 1
        rows = {}
        block = rows
        for k, kind in enumerate(kinds):
            rn = base + k
            rows[kind] = rn
            row_ops = {}
            if k == 0:
                t_attr, inner = T.text_op(shared, label)
                st = g.get(last["incite"], {}).get("A", ("", None))[0]
                row_ops[(rn, "A")] = ("new", st, t_attr, inner)
            t_attr, inner = T.text_op(shared, kind)
            st = g.get(last[kind], {}).get("B", ("", None))[0]
            row_ops[(rn, "B")] = ("new", st, t_attr, inner)
            xml = T.append_row(xml, rn, row_ops, max_col, shared)
    expect = dict(expect_fixed)
    for (k, col0, t), v in expect_new.items():
        expect[(block[kinds[k]], T.col_letter(col0 + t))] = v
    ops = {(rn, c): ("set", v) for (rn, c), v in expect.items()}
    xml, n = T.edit_cells(xml, ops)
    xml = T.fix_dimension(xml, max_col, T.max_row_xml(xml))
    tx.put_sheet(SHEET, xml)
    T._do_write(tx, ledger, args, tag=f"回填{period}差值前", preview_log={SHEET: {"cells": n}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
