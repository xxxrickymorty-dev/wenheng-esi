# -*- coding: utf-8 -*-
"""并入：主台账受控写入的**守卫与写后核对**（ADR-0004）。

写机制
------
落笔走清洗链自己的 `clean_ledger.py <期次> --write`（每个工具自带冲突拒写 + 备份 + zip 级
XML 自检）——而不是把副本字节搬进母版。原因：探针（2026-09-29）显示副本与母版之间还夹着
合法的结构性变化（styles / sharedStrings / calcChain / charts / 新 sheet…），逐字节白名单
既挡不住、也证不了「只动当期列」。于是把 ADR 的「审的＝写的」从**机制**改成**可验证属性**：
副本是先导出的审阅物与前导值；写后用副本对母版**逐格核对**。

五道查（`write_after_checks`，任一硬查不过 → 不宣告成功）：
  a. 没删：母版原有的 sheet 与格都在（副本/写后不得少格）
  b. 旧格不动：母版里**非当期**的格值写后必须一字不变
  c. 新增/改动格都归当期：落在「列头/行首含期次号（含其后 ≤2 列的成组延续）」的列/行上
  d. 审写同值：副本里当期标签下的格，写后母版逐格一致
  e. 写后档 XML 良构（由 ledger_patch.audit 承担，本模块只查格层面）
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import ledger_patch as LP                                            # noqa: E402

#: 清洗链会写的 sheet（外框白名单：写后「非这些 sheet 的成员变没变」由调用方报告；格层面五查兜底）
SHEET_SOURCE = {
    "云大ESI排名": "ESI", "总被引": "ESI", "论文数": "ESI", "ESI被引阈值": "ESI",
    "千分之一被引阈值": "ESI", "接近度": "本地派生", "新国际排名": "InCites",
    "新国内排名": "InCites", "国际排名": "InCites", "国内排名": "InCites",
    "TOP论文": "ESI", "篇均被引": "ESI＋InCites", "Q1-Q4": "InCites", "CNCI": "InCites",
    "实际与预测差值": "ESI＋InCites", "InCites快照": "InCites", "学科进入时间": "ESI",
}
CHAIN_SHEETS = tuple(SHEET_SOURCE)

_PERIOD_TXT = re.compile(r"20\d{4}")
#: 期次标签在台账里不止一种写法：多数表写 `202609`，Q1-Q4 / 实际与预测差值写 `2026.09`
#  （写入方 extract_incites.plan_q1q4 / extract_forecast_pairs.block_label）。
#  归因前先把 . - / 去掉再找期次号，两种格式都认；找不到原文期的检查照旧。
_SEP_RE = re.compile(r"[.\-/]")


def _norm(txt) -> str:
    return _SEP_RE.sub("", str(txt))


def sha256_file(p: pathlib.Path) -> str:
    """文件指纹（实现唯一在 `xlsx_io.sha256_file`；缺文件抛）。"""
    import xlsx_io                                               # noqa: PLC0415

    return xlsx_io.sha256_file(p)


# ------------------------------------------------------------------ 格快照
def sheet_cells(workbook: pathlib.Path, sheet: str) -> dict:
    """→ {(行, 列字母): 文本}；空 upper-left 占位（无值）不收录。"""
    grid, shared = LP.read_grid(workbook, sheet)
    out = {}
    for rn, row in grid.items():
        for cn, (attrs, inner) in row.items():
            txt = LP.cell_text(attrs, inner, shared)
            if txt is not None and str(txt).strip() != "":
                out[(rn, cn)] = str(txt)
    return out


def snapshot(workbook: pathlib.Path, sheets: tuple = CHAIN_SHEETS) -> dict:
    """逐 sheet 的格值快照（只拍清洗链会写的那些表）。"""
    have = set(LP.sheet_names(workbook))
    return {s: sheet_cells(workbook, s) for s in sheets if s in have}


def _col_index(cn: str) -> int:
    n = 0
    for ch in cn:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ------------------------------------------------------------------ 期次归因
def period_marks(cells: dict, period: str, *, label_cols: int = 3,
                 header_rows: int = 8, group_width: int = 2) -> tuple[set, set]:
    """→ (当期列集合, 当期行集合)。

    - 列：表头前 `header_rows` 行里出现期次号的列，及其右侧至多 `group_width` 列「无其它期次号的
      成组延续列」（新国际排名 = 每期 3 列一组，只有首列带期次号）。
    - 行：前 `label_cols` 列里出现期次号的行，及其下方至多 `group_width` 行延续（表尾成块追加）。
    """
    cols: set = set()
    rows: set = set()
    col_has_period: dict = {}
    row_has_period: dict = {}
    for (rn, cn), txt in cells.items():
        if period in _norm(txt):
            if rn <= header_rows:
                col_has_period[cn] = True
            if _col_index(cn) <= label_cols:
                row_has_period[rn] = True
    labelled_cols = sorted(col_has_period, key=_col_index)
    for cn in labelled_cols:
        base = _col_index(cn)
        cols.add(_col_letter(base))
        for step in range(1, group_width + 1):
            nxt = _col_letter(base + step)
            if nxt in col_has_period:
                break
            header_vals = [str(v).strip() for (rn, c), v in cells.items()
                           if c == nxt and rn <= header_rows]
            if any(header_vals):
                break                          # 右邻列表头有字（如「备注」）→ 不是成组延续
            cols.add(nxt)
    for rn in sorted(row_has_period):
        rows.add(rn)
        for step in range(1, group_width + 1):
            rows.add(rn + step)                # 行块（表尾追加）向下延续
    return cols, rows


def attribute(cells: dict, period: str, **kw) -> tuple[set, set]:
    """把 cells 里的格分成 (归当期, 不归当期)。"""
    cols, rows = period_marks(cells, period, **kw)
    ok, bad = set(), set()
    for key in cells:
        rn, cn = key
        (ok if (cn in cols or rn in rows) else bad).add(key)
    return ok, bad


# ------------------------------------------------------------------ 写后五查
def write_after_checks(master_before: pathlib.Path, master_after: pathlib.Path,
                       copy: pathlib.Path, period: str) -> dict:
    """见模块文档串的五道查。→ {ok, reasons, ...明细}；reasons 非空即不宣告成功。"""
    reasons: list[str] = []
    details: dict = {}
    sheets_before = set(LP.sheet_names(master_before))
    sheets_after = set(LP.sheet_names(master_after))
    missing_sheets = sorted(sheets_before - sheets_after)
    if missing_sheets:
        reasons.append(f"写后丢了 sheet：{missing_sheets}")
    old_modified, unattributed, mismatched = {}, {}, {}
    total_added = 0
    for sheet in (s for s in CHAIN_SHEETS if s in sheets_after and s in sheets_before):
        before = sheet_cells(master_before, sheet)
        after = sheet_cells(master_after, sheet)
        removed = [k for k in before if k not in after]
        if removed:
            reasons.append(f"《{sheet}》写后少了 {len(removed)} 个格（如 {removed[:3]}）")
        changed = {k: (before[k], after[k]) for k in before if k in after and before[k] != after[k]}
        added = {k: after[k] for k in after if k not in before}
        total_added += len(added)
        # b：非当期旧格一字不动（用写前快照定「当期列/行」）
        cols, rows = period_marks(before, period)
        bad_old = {k: v for k, v in changed.items() if not (k[1] in cols or k[0] in rows)}
        if bad_old:
            old_modified[sheet] = {f"{c}{r}": f"{a}→{b}" for (r, c), (a, b) in list(bad_old.items())[:8]}
            reasons.append(f"《{sheet}》有 {len(bad_old)} 个非当期旧格被改（如 "
                           f"{list(bad_old)[:3]}）")
        # c：新增/改动格归当期（用写后快照的标签归因）
        cols2, rows2 = period_marks(after, period)
        leftover = [k for k in list(added) + list(changed)
                    if not (k[1] in cols2 or k[0] in rows2)]
        if leftover:
            unattributed[sheet] = [f"{c}{r}" for r, c in leftover[:8]]
            reasons.append(f"《{sheet}》有 {len(leftover)} 个新增/改动格不在当期列/行上"
                           f"（如 {unattributed[sheet][:3]}）")
        # d：审写同值（副本里当期标签下的格，写后母版要一致）
        if copy.exists():
            copy_cells = sheet_cells(copy, sheet)
            ccols, crows = period_marks(copy_cells, period)
            diff = {k: (v, after.get(k)) for k, v in copy_cells.items()
                    if (k[1] in ccols or k[0] in crows) and after.get(k) != v}
            if diff:
                mismatched[sheet] = {f"{c}{r}": f"副本 {a!r} ≠ 母版 {b!r}"
                                     for (r, c), (a, b) in list(diff.items())[:8]}
                reasons.append(f"《{sheet}》审写不一致 {len(diff)} 格（如 {list(diff)[:3]}）")
    details.update({"sheets": {"before": len(sheets_before), "after": len(sheets_after)},
                    "added_cells": total_added, "old_modified": old_modified,
                    "unattributed": unattributed, "mismatched": mismatched})
    return {"ok": not reasons, "reasons": reasons, **details}


def review_summary(master: pathlib.Path, copy: pathlib.Path, period: str) -> list[dict]:
    """核对表：母版 → 副本，每张被写的表一行（给取数台「本期新增列核对表」）。"""
    rows = []
    have = set(LP.sheet_names(copy))
    for sheet in (s for s in CHAIN_SHEETS if s in have):
        try:
            before = sheet_cells(master, sheet) if sheet in set(LP.sheet_names(master)) else {}
            after = sheet_cells(copy, sheet)
        except KeyError:
            continue
        added = [k for k in after if k not in before or before[k] != after[k]]
        if not added:
            continue
        cols, _rows = period_marks(after, period)
        n_cols = len({c for _r, c in added if c in cols})
        note = f"{len(added)} 格" + (f" · {n_cols} 列" if n_cols else "")
        rows.append({"name": sheet, "added": f"{period} 列/组" if n_cols else "—",
                     "content": note, "source": SHEET_SOURCE.get(sheet, "—")})
    return rows
