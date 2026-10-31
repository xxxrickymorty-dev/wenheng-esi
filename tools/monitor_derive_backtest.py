# -*- coding: utf-8 -*-
"""监测版 D4 对拍：45 期「云大学科」推导件 vs 手工下载件逐格对拍。

推导逻辑（契约 §2.3）：`云大学科.xlsx` 冗余——把 22 张分学科全球榜按 `YUNNAN UNIVERSITY`
捞行即可拼出。本工具逐期执行该推导，与馆员当年手工下载的同名文件逐格比对，
验证「推导＝手工」。只读，不写任何数据源；结果落 `monitor_data/derive_backtest.json`。

列按表头名匹配（容忍历史版式漂移：9 列/15 列、列序变化都不致误报）；
数值判定容差：计数列 0.5、比值列（Cites/…）0.051。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import openpyxl

WENHENG = pathlib.Path(__file__).resolve().parents[1]
ESI_ROOT = WENHENG.parent / "数据与复现" / "ESI数据"
OUT = WENHENG / "monitor_data" / "derive_backtest.json"
SCHOOL = "YUNNAN UNIVERSITY"
SCHOOL_CN = "云大学科"

_norm = lambda s: " ".join(str(s).upper().replace("/", " ").split())


def _grid(path: pathlib.Path) -> tuple[list[str], list[list]]:
    """→ (表头名列表, 数据行)；自动跳过标题区、剔除页脚两行。"""
    wb = openpyxl.load_workbook(path)
    rows = [r for r in wb.active.iter_rows(values_only=True)
            if any(c is not None and str(c).strip() for c in r)]
    wb.close()
    hdr_i = next((i for i, r in enumerate(rows)
                  if any(str(c).strip() in ("Institutions", "Research Fields") for c in r if c)), None)
    if hdr_i is None:
        raise ValueError(f"表头找不到：{path.name}")
    hdr = [str(c).strip() if c is not None else "" for c in rows[hdr_i]]
    data = []
    for r in rows[hdr_i + 1:]:
        c0 = str(r[1]).strip() if r and r[1] is not None else ""
        if c0.upper().startswith(("COPYRIGHT", "EXPORT DATE")):
            break
        if not c0:
            continue
        data.append([c if c is not None else "" for c in r])
    return hdr, data


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def derive_one(base: pathlib.Path, stems: list[str]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """从 22 榜捞本校行 → {规范学科名: {列名: 值}}；返回 (行, 版式备注)。"""
    notes: list[str] = []
    out: dict[str, dict[str, float]] = {}
    for stem in stems:
        f = base / f"{stem}.xlsx"
        if not f.exists():
            notes.append(f"缺 {stem}.xlsx")
            continue
        hdr, data = _grid(f)
        cols = {h: i for i, h in enumerate(hdr) if h}
        row = next((r for r in data if str(r[cols["Institutions"]]).strip() == SCHOOL), None)
        if row is None:
            continue
        key = _norm(stem)
        rec: dict[str, float] = {}
        for h, i in cols.items():
            if h in ("Institutions", "Countries/Regions", ""):
                continue
            v = _num(row[i])
            if v is not None:
                rec[h] = v
        out[key] = rec
    return out, notes


def hand_one(base: pathlib.Path) -> tuple[dict[str, dict[str, float]], int]:
    """读手工下载的 云大学科.xlsx → {规范学科名: {列名: 值}}；返回 (行, 数据行数)。"""
    hdr, data = _grid(base / f"{SCHOOL_CN}.xlsx")
    cols = {h: i for i, h in enumerate(hdr) if h}
    out: dict[str, dict[str, float]] = {}
    for r in data:
        field = _norm(str(r[cols["Research Fields"]]))
        if not field or field == "ALL FIELDS":
            continue
        rec: dict[str, float] = {}
        for h, i in cols.items():
            if h in ("Research Fields", "") or re.match(r"^\d", h):
                continue
            v = _num(r[i])
            if v is not None:
                rec[h] = v
        out[field] = rec
    return out, len(data)


def _tol(col: str) -> float:
    return 0.051 if ("Cites/" in col or "/Paper" in col or col.startswith("Cites to")) else 0.5


def main() -> int:
    periods = sorted(d.name for d in ESI_ROOT.iterdir()
                     if re.fullmatch(r"20\d{4}", d.name)
                     and (d / "Institutions.xlsx").exists()
                     and (d / f"{SCHOOL_CN}.xlsx").exists())
    print(f"对拍期次：{len(periods)} 期（{periods[0]}–{periods[-1]}）")
    stems = ["Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
             "Computer Science", "Economics & Business", "Engineering", "Environment Ecology",
             "Geosciences", "Immunology", "Materials Science", "Mathematics", "Microbiology",
             "Molecular Biology & Genetics", "Multidisciplinary", "Neuroscience & Behavior",
             "Pharmacology & Toxicology", "Physics", "Plant & Animal Science",
             "Psychiatry Psychology", "Social Sciences, General", "Space Science"]
    tot_cells = tot_eq = tot_diff = 0
    per_period: list[dict] = []
    diff_samples: list[dict] = []
    for period in periods:
        base = ESI_ROOT / period
        try:
            derived, notes = derive_one(base, stems)
            hand, n_hand_rows = hand_one(base)
        except ValueError as exc:
            per_period.append({"period": period, "error": str(exc)})
            print(f"  [跳过] {period}: {exc}")
            continue
        cells = eq = diff = 0
        diffs: list[str] = []
        for field, hrec in hand.items():
            drec = derived.get(field)
            if drec is None:
                diffs.append(f"{field}:推导缺行")
                diff += len(hrec)
                continue
            for col, hv in hrec.items():
                dv = drec.get(col)
                if dv is None:
                    continue            # 该期版式缺列，不算格差
                cells += 1
                if abs(hv - dv) <= _tol(col):
                    eq += 1
                else:
                    diff += 1
                    if len(diff_samples) < 12:
                        diffs.append(f"{field}.{col}: 手工{hv} vs 推导{dv}")
        # 反向：推导有而手工没有的学科行（手工版只含已入围）——数量记录，不算格差
        extra = sorted(set(derived) - set(hand))
        tot_cells += cells
        tot_eq += eq
        tot_diff += diff
        state = ("equal" if diff == 0 and cells > 0 else
                 "不可比(手工件版式异常)" if cells == 0 and eq == 0 else "diff")
        mark = {"equal": "✓", "diff": "✗"}.get(state, "△")
        per_period.append({"period": period, "state": state, "cells": cells, "equal": eq,
                           "diff": diff, "fields_hand": len(hand),
                           "fields_derived": len(derived), "fields_extra": len(extra),
                           "notes": notes})
        print(f"  [{period}] {mark} {state} · 格 {cells} · 差 {diff}"
              + (f" · 例: {diffs[:2]}" if diffs else ""))
    rep = {"generated": str(__import__("datetime").date.today()),
           "periods": len(periods), "cells": tot_cells, "equal": tot_eq, "diff": tot_diff,
           "tolerance": {"计数列": 0.5, "比值列": 0.051},
           "per_period": per_period, "diff_samples": diff_samples}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[对拍] {tot_cells} 格 · 相等 {tot_eq} · 差 {tot_diff} → {OUT.name}")
    return 0 if tot_diff == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
