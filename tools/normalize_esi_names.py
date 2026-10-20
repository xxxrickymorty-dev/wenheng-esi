# -*- coding: utf-8 -*-
"""把往期 ESI 原始包统一成 202609 的命名（2026-10-20 rick 要求）。

背景：202609 起取数脚本按固定文件名落盘，核验（`src/acquisition_state.py::scan_groups`）
也按这些名字逐件对。202601–202607 是馆员**手工下载**的，名字各期不同（`202605ESI总表.xlsx`、
`top paper252.xlsx`、`ResearchFields.xlsx`…），于是核验把明明在的文件报成缺件。

本工具做三件事（**按内容认人，不按名字瞎改**）：

1. **改名**——只认内容，认准了才改成标准名：
   - 学科汇总：`ResearchFields.xlsx` → `全球学科.xlsx`；`CHINA MAINLAND*.xlsx` → `中国学科.xlsx`；
     `YUNNAN UNIVERSITY*.xlsx` → `云大学科.xlsx`（内容须是「Research Fields + Web of Science Documents」表）
   - 论文清单：`top paper252.xlsx` → `252top.xlsx`、`highly cited paper251.xlsx` → `251highly cited.xlsx`
     （篇数取**文件自身行数 − 8**；与 202609 三个文件反推一致：299−8=291、298−8=290、21−8=13）
2. **归档**——不属于标准 64 件、也不是抽取支撑件的（`20260xESI总表模板.xlsx`、`千分之一阈值.xlsx`、
   `进入1%…统计表.xlsx`、`top…按发文量排序.xlsx` 等），移到 `<ESI 根>/_归档统一命名/<期次>/`。
3. **留痕**——`--write` 时写 `_改名记录.json`（旧名/新名/大小/sha256/动作），可原路撤回。

支撑件（保留、不动）：`_下载信息.json`、`中国机构属性.xlsx`（202607 的国内排名要用）、
各学科表 / 阈值 / 基线 / 20xxESI总表模板 之外的正文文件。

默认 **dry-run**（只打印计划）；`--write` 才动盘。Windows 上重名/占用会直接报错，不静默覆盖。

用法（在 wenheng/ 下）：
    uv run python tools/normalize_esi_names.py                     # 预览
    uv run python tools/normalize_esi_names.py --write            # 执行（写记录）
    uv run python tools/normalize_esi_names.py --periods 202605   # 只处理某几期
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import pathlib
import re
import sys

import openpyxl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from acquisition_state import (INCITES_ROOT_DEFAULT, SUBJECTS, ESI_ROOT_DEFAULT,  # noqa: E402
                              resolve_snapshot)

ARCHIVE_DIRNAME = "_归档统一命名"
#: 论文清单三类（与 scan_groups 的 glob 后缀一致）
PAPER_SUFFIXES = (("top", ("top",)), ("highly cited", ("highly cited", "highlycited")),
                  ("hot papers", ("hot papers", "hotpaper")))
#: 抽取支撑件：不属于 64 件，但别归档（202607 的国内排名靠它）
KEEP_EXTRA = {"中国机构属性.xlsx", "_下载信息.json"}


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rows(path: pathlib.Path) -> int:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    try:
        return wb.worksheets[0].max_row
    finally:
        wb.close()


def _first_cells(path: pathlib.Path, rows: int = 4, cols: int = 8) -> list[str]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    try:
        out: list[str] = []
        for r in wb.worksheets[0].iter_rows(min_row=1, max_row=40, max_col=cols, values_only=True):
            vals = [str(v).strip() for v in r if v is not None and str(v).strip()]
            if vals:
                out.append(" | ".join(vals[:6]))
            if len(out) >= rows:
                break
        return out
    finally:
        wb.close()


def is_fields_table(p: pathlib.Path) -> bool:
    """学科汇总表：首屏有 Research Fields + Web of Science Documents，20–40 行。"""
    try:
        if not 15 <= _rows(p) <= 45:
            return False
        head = " ".join(_first_cells(p, rows=2)).lower()
        return "research fields" in head and "web of science documents" in head
    except Exception:  # noqa: BLE001
        return False


def is_papers(p: pathlib.Path) -> bool:
    """论文清单：Accession Number / Documents Result List，>= 10 行。"""
    try:
        if _rows(p) < 10:
            return False
        head = " ".join(_first_cells(p, rows=2)).lower()
        return "accession number" in head and "documents result list" in head
    except Exception:  # noqa: BLE001
        return False


def papers_count(p: pathlib.Path) -> int:
    """篇数 = 行数 − 8（202609 三份反推：299→291 / 298→290 / 21→13）。"""
    return max(0, _rows(p) - 8)


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", " ", name).strip().lower()


def expected_keep() -> set[str]:
    """标准 64 件里 **ESI 一侧** 的固定名（论文清单按后缀单独认）。

    学科文件名与 `scan_groups` 同口径：学科名里的 `/` 换成空格（`Environment/Ecology`
    → `Environment Ecology.xlsx`）——漏了这一步会把 22 个学科表误判成「多余」。
    """
    keep = {f"{s.replace('/', ' ')}.xlsx" for s in SUBJECTS}
    keep |= {"Institutions.xlsx", "全球学科.xlsx", "中国学科.xlsx", "云大学科.xlsx",
             "ThresholdESI.xlsx", "ThresholdHighlyCited.xlsx", "ThresholdHot.xlsx",
             "BaselineCitationRates.xlsx", "BaselinePercentiles.xlsx", "BaselineFieldRankings.xlsx"}
    keep |= KEEP_EXTRA
    return keep


def _plausible_fields_source(name: str, which: str) -> bool:
    n = _norm(name)
    if which == "全球学科":
        return n in ("researchfields.xlsx", "研究领域.xlsx", "research fields.xlsx")
    if which == "中国学科":
        return n.startswith("china mainland") or n == "中国研究领域.xlsx"
    if which == "云大学科":
        return n.startswith("yunnan university")
    return False


def plan_period(period: str, esi_root: pathlib.Path) -> dict:
    """→ {"rename": [(src, dst, why)], "archive": [(src, why)], "skip": [...]}"""
    d = esi_root / period
    files = [p for p in d.iterdir() if p.is_file()] if d.is_dir() else []
    plan: dict = {"period": period, "rename": [], "archive": [], "warn": []}
    if not files:
        plan["warn"].append("目录不存在或为空")
        return plan

    keep = {_norm(x) for x in expected_keep()}
    taken = {_norm(p.name) for p in files}
    consumed: set[str] = set()

    # ---- 1) 学科汇总三件：按内容认，且目标名没被占 ----
    for target, which in (("全球学科.xlsx", "全球学科"), ("中国学科.xlsx", "中国学科"),
                          ("云大学科.xlsx", "云大学科")):
        if _norm(target) in taken:
            continue
        cands = [p for p in files if _norm(p.name) not in consumed
                 and _plausible_fields_source(p.name, which) and is_fields_table(p)]
        if len(cands) == 1:
            plan["rename"].append((cands[0], target, f"学科汇总 → {target}（内容核过）"))
            consumed.add(_norm(cands[0].name))
            taken.add(_norm(target))
        elif len(cands) > 1:
            plan["warn"].append(f"{target} 有多个候选：{[p.name for p in cands]}，未动")

    # ---- 2) 论文清单三件：目标名 = <篇数><后缀>.xlsx ----
    for suffix, keys in PAPER_SUFFIXES:
        have = [p for p in files if re.fullmatch(rf"\d+{re.escape(suffix)}\.xlsx", p.name, re.I)]
        if have:
            continue
        cands = []
        for p in files:
            n = _norm(p.name)
            if _norm(p.name) in consumed or not n.endswith(".xlsx"):
                continue
            if not any(k in n for k in keys):
                continue
            if "排序" in p.name or "按" in p.name:      # 派生视图（按发文量排序）不是原件
                continue
            if is_papers(p):
                cands.append(p)
        if len(cands) == 1:
            dst = f"{papers_count(cands[0])}{suffix}.xlsx"
            if _norm(dst) in taken:
                plan["archive"].append((cands[0], f"{dst} 已存在（重复件）"))
            else:
                plan["rename"].append((cands[0], dst, f"论文清单 → {dst}（行数−8=篇数）"))
                taken.add(_norm(dst))
            consumed.add(_norm(cands[0].name))
        elif len(cands) > 1:
            plan["warn"].append(f"{suffix} 有多个候选：{[p.name for p in cands]}，未动")

    # ---- 3) 其余：标准件 / 支撑件留下，别的进归档 ----
    std_papers = re.compile(r"\d+(top|highly cited|hot papers)\.xlsx$", re.I)
    for p in files:
        if _norm(p.name) in consumed:
            continue
        if _norm(p.name) in keep or std_papers.match(p.name):
            continue
        plan["archive"].append((p, "不属于标准件，也不是抽取支撑件"))
    return plan


def apply_plan(plan: dict, esi_root: pathlib.Path, write: bool) -> dict:
    d = esi_root / plan["period"]
    arch = esi_root / ARCHIVE_DIRNAME / plan["period"]
    rec = {"period": plan["period"], "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "renamed": [], "archived": []}
    if not write:
        return rec
    for src, dst, _why in plan["rename"]:
        target = d / dst
        if target.exists():
            raise SystemExit(f"[拒绝] 目标已存在，不动：{target}")
        meta = {"from": src.name, "to": dst, "size": src.stat().st_size, "sha256": _sha(src)}
        src.rename(target)
        rec["renamed"].append(meta)
    for src, _why in plan["archive"]:
        arch.mkdir(parents=True, exist_ok=True)
        target = arch / src.name
        if target.exists():
            raise SystemExit(f"[拒绝] 归档目标已存在，不动：{target}")
        meta = {"from": src.name, "size": src.stat().st_size, "sha256": _sha(src)}
        src.rename(target)
        rec["archived"].append(meta)
    (arch / "_改名记录.json").parent.mkdir(parents=True, exist_ok=True)
    (arch / "_改名记录.json").write_text(
        __import__("json").dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def _is_incites_fields(p: pathlib.Path) -> bool:
    """InCites 研究领域汇总：名称/Name + Web of Science 论文数(Documents)，15–45 行。"""
    try:
        if not 15 <= _rows(p) <= 45:
            return False
        head = " ".join(_first_cells(p, rows=2)).lower()
        has_docs = "web of science 论文数" in head or "web of science documents" in head
        return has_docs and ("名称" in head or "name" in head)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ InCites 快照（同族命名坑）
def plan_incites(snapshot_dir: pathlib.Path) -> dict:
    """InCites 快照里的命名坑（**只改名、不归档**——额外的切法有用）：

    · `Agricultural Sciencesxlsx.xlsx`（多打了一个 xlsx）→ `Agricultural Sciences.xlsx`
    · `作者所在地中国 研究领域.xlsx`（中国领域当年的叫法）→ `中国研究领域.xlsx`
    · `云大学科.xlsx`（其实是 InCites 的云南大学研究领域表）→ `云南大学研究领域.xlsx`
    """
    plan = {"dir": snapshot_dir, "rename": [], "warn": []}
    if not snapshot_dir.is_dir():
        return plan
    files = {p.name for p in snapshot_dir.iterdir() if p.is_file()}
    for p in sorted(snapshot_dir.iterdir()):
        if not p.is_file():
            continue
        m = re.fullmatch(r"(.+?)xlsx\.xlsx", p.name, re.I)
        if m:
            target = f"{m.group(1)}.xlsx"
            if target in files:
                plan["warn"].append(f"{p.name} 应改成 {target}，但目标已存在（未动）")
            else:
                plan["rename"].append((p, target, "双扩展名 → 单扩展名"))
                files.add(target)
    alias = "作者所在地中国 研究领域.xlsx"
    if alias in files and "中国研究领域.xlsx" not in files:
        plan["rename"].append((snapshot_dir / alias, "中国研究领域.xlsx",
                               "「作者所在地中国」＝中国领域表（基线量级与全球/中国一致）"))
        files.add("中国研究领域.xlsx")
    ynu = "云大学科.xlsx"
    if ynu in files and "云南大学研究领域.xlsx" not in files \
            and _is_incites_fields(snapshot_dir / ynu):
        plan["rename"].append((snapshot_dir / ynu, "云南大学研究领域.xlsx",
                               "名字叫「云大学科」，内容是本快照的云南大学研究领域表（23 行）"))
    return plan


def apply_incites(plan: dict, write: bool) -> dict:
    rec = {"dir": str(plan["dir"]), "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "renamed": []}
    if not write:
        return rec
    for src, dst, _why in plan["rename"]:
        target = plan["dir"] / dst
        if target.exists():
            raise SystemExit(f"[拒绝] 目标已存在，不动：{target}")
        rec["renamed"].append({"from": src.name, "to": dst, "size": src.stat().st_size,
                               "sha256": _sha(src)})
        src.rename(target)
    (plan["dir"] / "_改名记录.json").write_text(
        __import__("json").dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="往期 ESI 包统一命名（默认只预览）")
    ap.add_argument("--periods", nargs="*", default=["202601", "202603", "202605", "202607"])
    ap.add_argument("--esi-root", default=str(ESI_ROOT_DEFAULT))
    ap.add_argument("--write", action="store_true", help="真正动盘（改名 + 归档 + 写记录）")
    ap.add_argument("--incites", action="store_true",
                    help="顺带核 InCites 快照的命名坑（双扩展名 / 作者所在地中国）")
    args = ap.parse_args()
    root = pathlib.Path(args.esi_root)

    if args.incites:
        for period in args.periods:
            snap = resolve_snapshot(period, INCITES_ROOT_DEFAULT)
            if not snap:
                print(f"{period}：未登记 InCites 快照，跳过")
                continue
            plan = plan_incites(INCITES_ROOT_DEFAULT / snap)
            print("=" * 78)
            print(f"{period} · InCites {snap}：改名 {len(plan['rename'])} 个")
            for src, dst, why in plan["rename"]:
                print(f"  改名  {src.name}  →  {dst}   （{why}）")
            for w in plan["warn"]:
                print(f"  ⚠ {w}")
            if args.write:
                rec = apply_incites(plan, write=True)
                print(f"  已执行：改名 {len(rec['renamed'])}")

    for period in args.periods:
        plan = plan_period(period, root)
        print("=" * 78)
        print(f"{period}：改名 {len(plan['rename'])} 个 · 归档 {len(plan['archive'])} 个")
        for src, dst, why in plan["rename"]:
            print(f"  改名  {src.name}  →  {dst}   （{why}）")
        for src, why in plan["archive"]:
            print(f"  归档  {src.name}   （{why}）")
        for w in plan["warn"]:
            print(f"  ⚠ {w}")
        if args.write:
            rec = apply_plan(plan, root, write=True)
            print(f"  已执行：改名 {len(rec['renamed'])} · 归档 {len(rec['archived'])} → "
                  f"{root / ARCHIVE_DIRNAME / period}")
    if not args.write:
        print("\n（本次是预览；确认无误加 --write 执行）")
    else:
        print("\n下一步：重扫这四期的核验状态 —— "
              r"uv run python tools\acquire.py scan <期次>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
