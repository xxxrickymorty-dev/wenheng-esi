# -*- coding: utf-8 -*-
"""ESI 侧「待工具化」列 → 台账：云大ESI排名（三序列）/ 总被引·论文数·TOP论文（在榜学科）
/ 篇均被引（云大·中国大陆·国际）/ ESI被引阈值。

口径（2026-09-23 用 202607、202605 两期回放钉死）
--------------------------------------------------
· 云大ESI排名（左右两块：A-D 与 G-J）
    国际排名  = 云大在 `institutions.xlsx` 总榜里的「序号」
    国内排名  = 中国大陆条目中 ≤ 云大序号 的条数（含云大）
    国内高校排名 = 其中「机构类型 = Academic」的条数（含云大；类型查 `中国机构属性.xlsx`，
               该文件只有 202607 有 → 缺失时自动回退到最近一期并提醒）
· 总被引 / 论文数 / TOP论文 / 篇均被引（云大列）← `云大学科.xlsx`（14/6 列版都行，按表头名取）
   （后备：机构档案 `YUNNAN UNIVERSITY*.xlsx`，202607 就是这种）
· 篇均被引（中国大陆 / 国际）← `中国学科.xlsx` / `全球学科.xlsx` 的 Cites/Paper
   （全球后备：`BaselineCitationRates.xlsx` 的 ALL YEARS 列——202605 实测两者相等）
· ESI被引阈值 ← `ThresholdESI.xlsx` Sheet1（RESEARCH FIELDS / INSTITUTION 两列，全 22 学科）

只写「非 ESI 在榜学科」之外的列；未进榜学科的 总被引/论文数/篇均（云大列）由 `extract_incites.py` 从
InCites 写。写回纪律与 extract_incites 完全一致（zip 级 XML、写前自检、冲突拒写、--write 前备份）。

用法（wenheng/ 下，.venv 的 python）：
    python tools\\extract_esi.py 202607                    # 预览 + 与台账逐格比对（只读）
    python tools\\extract_esi.py 202607 --out tmp\\x.xlsx   # 写副本
    python tools\\extract_esi.py 202607 --write            # 写台账（自动备份）
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import openpyxl

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import extract_incites as T                                                    # noqa: E402
import ledger_patch as LP                                                      # noqa: E402
import parse_ledger as PL                                                      # noqa: E402

SUBJECTS = list(PL.DISCIPLINES_EN)
UP2EN = {s.upper(): s for s in SUBJECTS}


# ------------------------------------------------------------------ 源文件小工具
def _rows(p: pathlib.Path):
    wb = openpyxl.load_workbook(p, data_only=True)  # ESI 新导出 dimension 常坏，普通模式才读得全
    try:
        rows = [list(r) for r in wb[wb.sheetnames[0]].iter_rows(values_only=True)]
    finally:
        wb.close()
    return rows


def _header(rows):
    for i, r in enumerate(rows[:12]):
        h = [str(c).strip() if c is not None else "" for c in r]
        if "Research Fields" in h or "RESEARCH FIELDS" in [x.upper() for x in h]:
            return i, h
    return 0, [str(c).strip() if c is not None else "" for c in rows[0]]


def _col(h, *keys):
    for i, x in enumerate(h):
        xu = x.upper()
        if all(k.upper() in xu for k in keys):
            return i
    raise ValueError(f"表头缺列 {keys}: {h}")


def _norm(v):
    return 0.0 if v is None or str(v).strip() == "" else float(v)


# ------------------------------------------------------------------ 读源
def read_institutions(esi_dir: pathlib.Path) -> dict:
    rows = _rows(esi_dir / "institutions.xlsx")
    hi = next(i for i, r in enumerate(rows[:12])
              if r and any(str(c).strip() == "Institutions" for c in r if c is not None))
    h = [str(c).strip() if c is not None else "" for c in rows[hi]]
    ni = h.index("Institutions")
    gi = next((j for j, x in enumerate(h) if "Countries" in x), None)
    data = []
    seq = 0
    for r in rows[hi + 1:]:
        if not r or any(c and "copyright" in str(c).lower() for c in r[:3]):
            break
        name = str(r[ni]).strip() if ni < len(r) and r[ni] is not None else ""
        if not name:
            continue
        s = T._num(r[0]) if len(r) else None
        seq = int(s) if s and s > 0 else seq + 1
        ctry = str(r[gi]).strip().upper() if gi is not None and gi < len(r) and r[gi] else ""
        data.append((seq, name.upper(), ctry))
    ypos = next((s for s, n, _c in data if "YUNNAN UNIVERSITY" in n), None)
    if ypos is None:
        raise SystemExit(f"[缺行] {esi_dir.name}/institutions.xlsx 里没有 YUNNAN UNIVERSITY")
    cn = sum(1 for s, _n, c in data if s <= ypos and "CHINA" in c)
    # 高校数：查机构类型（中国机构属性.xlsx，只有 202607 有 → 回退最近一期）
    types = {}
    src = None
    for d in [esi_dir] + sorted((p for p in esi_dir.parent.glob("*") if p.is_dir()
                                 and not p.name.startswith("_")), reverse=True):
        p = d / "中国机构属性.xlsx"
        if p.exists():
            rows2 = _rows(p)
            h2 = [str(c).strip() if c is not None else "" for c in rows2[0]]
            ti, ni2 = h2.index("Organization Type"), h2.index("Name")
            types = {str(r[ni2]).strip().upper(): str(r[ti]).strip()
                     for r in rows2[1:] if r and r[ni2]}
            src = d.name
            break
    if not types:
        raise SystemExit("[缺件] 找不到 中国机构属性.xlsx（国内高校排名算不了）")
    acad_before = sum(1 for s, n, c in data if s < ypos and "CHINA" in c and types.get(n) == "Academic")
    acad = acad_before + (1 if types.get("YUNNAN UNIVERSITY") == "Academic" else 0)
    if src != esi_dir.name:
        print(f"[i] 机构类型取自 {src}（当期目录没有 中国机构属性.xlsx）")
    return {"国际排名": int(ypos), "国内排名": cn, "国内高校排名": acad}


def read_ynu_fields(esi_dir: pathlib.Path) -> dict:
    """云大学科.xlsx（优先）或机构档案 YUNNAN UNIVERSITY*.xlsx → {学科EN: (docs, cites, cpp, top)}"""
    p = esi_dir / "云大学科.xlsx"
    rows = None
    if p.exists():
        rows = _rows(p)
        hi, h = _header(rows)
        fi = _col(h, "Research Fields") or 1
        di, ci, qi, ti = _col(h, "Web of Science"), _col(h, "Cites"), _col(h, "Cites/Paper"), _col(h, "Top Papers")
        recs = {}
        for r in rows[hi + 1:]:
            nm = str(r[fi]).strip().upper() if fi < len(r) and r[fi] else ""
            if nm in UP2EN:
                recs[UP2EN[nm]] = (int(_norm(r[di])), int(_norm(r[ci])), _norm(r[qi]), int(_norm(r[ti])))
        return recs
    cands = sorted(esi_dir.glob("YUNNAN UNIVERSITY*.xlsx"))
    if not cands:
        raise SystemExit(f"[缺件] {esi_dir.name} 里既没有 云大学科.xlsx 也没有机构档案 YUNNAN UNIVERSITY*.xlsx")
    rows = _rows(cands[0])
    hi = next(i for i, r in enumerate(rows[:14])
              if r and any(str(c).strip() == "Research Fields" for c in r if c is not None))
    h = [str(c).strip() if c is not None else "" for c in rows[hi]]
    fi = h.index("Research Fields")
    di, ci, qi, ti = (_col(h, "Web of Science"), _col(h, "Cites"),
                      _col(h, "Cites/Paper"), _col(h, "Top Papers"))
    recs = {}
    for r in rows[hi + 1:]:
        nm = str(r[fi]).strip().upper() if fi < len(r) and r[fi] else ""
        if nm in UP2EN:
            recs[UP2EN[nm]] = (int(_norm(r[di])), int(_norm(r[ci])), _norm(r[qi]), int(_norm(r[ti])))
    return recs


def _cpp_file(esi_dir: pathlib.Path, names: tuple) -> dict | None:
    for n in names:
        p = esi_dir / n
        if not p.exists():
            continue
        rows = _rows(p)
        hi, h = _header(rows)
        fi = _col(h, "Research Fields") or 1
        qi = _col(h, "Cites/Paper")
        out = {}
        for r in rows[hi + 1:]:
            nm = str(r[fi]).strip().upper() if fi < len(r) and r[fi] else ""
            if nm in UP2EN:
                out[UP2EN[nm]] = _norm(r[qi])
        return out
    return None


def read_cn_global(esi_dir: pathlib.Path) -> tuple[dict, dict, list]:
    notes = []
    cn = _cpp_file(esi_dir, ("中国学科.xlsx", "中国大陆学科.xlsx", "大陆22学科.xlsx"))
    if cn is None:
        notes.append("缺 中国学科.xlsx（中国大陆列跳过）")
        cn = {}
    gl = _cpp_file(esi_dir, ("全球学科.xlsx", "国际学科.xlsx", "国际22学科.xlsx"))
    if gl is None:
        # 后备：BaselineCitationRates 的 ALL YEARS 列
        for nm in ("BaselineCitationRates.xlsx",):
            p = esi_dir / nm
            if not p.exists():
                continue
            rows = _rows(p)
            hi = next((i for i, r in enumerate(rows[:6])
                       if r and str(r[0]).strip().upper() == "RESEARCH FIELDS"), 2)
            h = [str(c).strip() if c is not None else "" for c in rows[hi]]
            ai = _col(h, "ALL YEARS")
            gl = {}
            for r in rows[hi + 1:]:
                nm2 = str(r[0]).strip().upper() if r and r[0] else ""
                if nm2 in UP2EN and ai is not None and r[ai] is not None:
                    gl[UP2EN[nm2]] = _norm(r[ai])
            notes.append(f"全球篇均取自 BaselineCitationRates ALL YEARS（缺 全球学科.xlsx）")
            break
    if not gl:
        notes.append("缺 全球学科.xlsx 且无基线后备（国际列跳过）")
        gl = {}
    return cn, gl, notes


def read_in_list(esi_dir: pathlib.Path) -> tuple[set, list, list]:
    """本期各学科 ESI 榜里有没有云大 → (在榜集合, 缺件, 解析异常)。"""
    hit, miss, bad = set(), [], []
    for s in SUBJECTS:
        p = T._resolve_file(esi_dir, s)
        if p is None:
            miss.append(s)
            continue
        try:
            if T.read_esi_list(p)["ypos"]:
                hit.add(s)
        except Exception as e:                                     # noqa: BLE001
            bad.append((s, str(e)))
    return hit, miss, bad


def read_entry_state(led: pathlib.Path, period: str) -> set:
    """《学科进入时间》事件推到 period 为止的在榜集合。"""
    wb = openpyxl.load_workbook(str(led), data_only=True)
    try:
        events, _ = PL.parse_entry_events(wb["学科进入时间"], [])
    finally:
        wb.close()
    cur = set()
    for ym, d, typ in sorted(events, key=lambda x: (x[0], 0 if x[2] == "in" else 1)):
        if ym <= period:
            cur.add(d) if typ == "in" else cur.discard(d)
    return cur


def plan_events(tx: T.LedgerTx, adds: list) -> tuple[str, dict]:
    """往《学科进入时间》表尾追加事件行；adds: [(期次, 学科EN, "in"|"out")]。"""
    sheet = "学科进入时间"
    xml = tx.sheet_xml(sheet)
    g, shared = T.read_grid(tx.path, sheet)
    last = T.max_row_xml(xml)
    styles = {cn: (g.get(last, {}).get(cn, ("", None))[0] or "") for cn in ("A", "B", "C", "D")}
    rn = last
    n = 0
    for ym, en, typ in adds:
        rn += 1
        cn_name = PL.DISCIPLINES_CN.get(en) or en
        ops = {}
        if typ == "in":
            ops[(rn, "A")] = ("new", styles["A"], "", f"<v>{ym[:4]}</v>")
            t_attr, inner = T.text_op(shared, f"{int(ym[4:])}月")
            ops[(rn, "B")] = ("new", styles["B"], t_attr, inner)
            t_attr, inner = T.text_op(shared, cn_name)
            ops[(rn, "C")] = ("new", styles["C"], t_attr, inner)
            t_attr, inner = T.text_op(shared, "是")
            ops[(rn, "D")] = ("new", styles["D"], t_attr, inner)
        else:
            t_attr, inner = T.text_op(shared, f"{ym[:4]}年{int(ym[4:])}月{cn_name}退出")
            ops[(rn, "C")] = ("new", styles["C"], t_attr, inner)
        xml = T.append_row(xml, rn, ops, 4, shared)
        n += len(ops)
    xml = T.fix_dimension(xml, 4, rn)
    return xml, {"cells": n}


def read_top_counts(esi_dir: pathlib.Path) -> tuple[dict, dict, int]:
    """Top 论文清单（`291top.xlsx` / `top274.xlsx`）→（学科计数, 年度计数, 合计）。

    口径（2026-09-23 与台账逐格对上）：逐科计数 = 该学科 Top 论文篇数（含未进 ESI 榜的学科）；
    合计 = 清单总篇数（202607=274、202609=291）；年度行 = 按 Publication Date 年份计数。
    """
    cands = sorted(p for p in esi_dir.glob("*top*.xlsx")
                   if "highly" not in p.name.lower() and "hot" not in p.name.lower())
    if not cands:
        raise SystemExit(f"[缺件] {esi_dir.name} 里没有 Top 论文清单（形如 291top.xlsx）")
    rows = _rows(cands[0])
    hi = next((i for i, r in enumerate(rows[:14])
               if r and any(str(c).strip() in ("Research Field", "Research Fields")
                            for c in r if c is not None)), None)
    if hi is None:
        raise SystemExit(f"[缺表头] {cands[0].name} 里找不到 Research Field 表头")
    h = [str(c).strip() if c is not None else "" for c in rows[hi]]
    fi = _col(h, "Research Field")
    yi = _col(h, "Publication Date")
    subj, years, total = {}, {}, 0
    for r in rows[hi + 1:]:
        if not r or fi >= len(r) or r[fi] is None:
            continue
        nm = str(r[fi]).strip().upper()
        if nm not in UP2EN:
            continue
        total += 1
        subj[UP2EN[nm]] = subj.get(UP2EN[nm], 0) + 1
        y = str(r[yi]).strip()[:4] if yi is not None and yi < len(r) and r[yi] is not None else ""
        if y.isdigit():
            years[y] = years.get(y, 0) + 1
    return subj, years, total


def plan_top_extra(xml: str, ledger: pathlib.Path, period: str, years: dict,
                   total: int) -> tuple[str, dict]:
    """在（已追加期次列的）TOP论文 XML 上补：「高被引论文合计（篇）」两行 + 年度行。"""
    g, shared = T.read_grid(ledger, "TOP论文")
    hdr = {cn: str(T.gtext(g, shared, 1, cn) or "").strip() for cn in g.get(1, {})}
    period_cols = [(T.col_index(cn), cn) for cn, v in hdr.items() if re.fullmatch(r"20\d{4}", v)]
    last_i, _last_cn = max(period_cols)
    period_col = next((cn for _i, cn in period_cols if hdr[cn] == period), None) or T.col_letter(last_i + 1)
    prev_col = T.col_letter(T.col_index(period_col) - 1)
    ops = {}
    for rn in sorted(g):
        nm = str(T.gtext(g, shared, rn, "A") or "").strip()
        if nm.startswith("高被引论文合计"):
            v = total
        elif re.fullmatch(r"20\d\d", nm):
            v = years.get(nm)
        else:
            continue
        if period_col in g.get(rn, {}):
            ops[(rn, period_col)] = ("set", v)
        else:
            style = g.get(rn, {}).get(prev_col, ("", None))[0]
            inner = f"<v>{T._fmt(v)}</v>" if v is not None else None
            ops[(rn, period_col)] = ("new", style, "", inner)
    xml, n = T.edit_cells(xml, ops)
    xml = T.fix_dimension(xml, T.col_index(period_col), T.max_row_xml(xml))
    return xml, {"cells": n}


def read_thresholds(esi_dir: pathlib.Path) -> dict:
    p = esi_dir / "ThresholdESI.xlsx"
    if not p.exists():
        raise SystemExit(f"[缺件] {esi_dir.name}/ThresholdESI.xlsx")
    rows = _rows(p)
    # Sheet1：RESEARCH FIELDS / INSTITUTION
    for i, r in enumerate(rows[:8]):
        h = [str(c).strip().upper() if c is not None else "" for c in r]
        if "RESEARCH FIELDS" in h and any(x == "INSTITUTION" for x in h):
            fi, ii = h.index("RESEARCH FIELDS"), h.index("INSTITUTION")
            out = {}
            for r2 in rows[i + 1:]:
                nm = str(r2[fi]).strip().upper() if r2 and fi < len(r2) and r2[fi] else ""
                if nm in UP2EN:
                    out[UP2EN[nm]] = int(_norm(r2[ii]))
            if out:
                return out
    raise SystemExit(f"[缺表] {p.name} 里没找到 RESEARCH FIELDS/INSTITUTION 块")


# ------------------------------------------------------------------ 写计划
def plan_esi_rank(tx: T.LedgerTx, period: str, v: dict) -> tuple[str, dict]:
    """云大ESI排名：左右两块（A-D 与 G-J）同时写当期行。"""
    sheet = "云大ESI排名"
    xml = tx.sheet_xml(sheet)
    g, shared = T.read_grid(tx.path, sheet)
    cur_max = T.max_row_xml(xml)
    ops, inserts = {}, {}
    vals = (v["国际排名"], v["国内排名"], v["国内高校排名"])
    for base_cn, cols in (("A", ("B", "C", "D")), ("G", ("H", "I", "J"))):
        found = next((rn for rn in sorted(g)
                      if str(T.gtext(g, shared, rn, base_cn) or "").strip() == period), None)
        if found is not None:
            prow, bucket = found, ops
        else:                                              # 追加：行号超出现有行 → 插入新行
            last = max((rn for rn in g if str(T.gtext(g, shared, rn, base_cn) or "").strip()),
                       default=1)
            prow = last + 1
            bucket = ops if prow <= cur_max else inserts
            style = g.get(last, {}).get(base_cn, ("", None))[0]
            t_attr, inner = T.text_op(shared, period)
            bucket[(prow, base_cn)] = ("new", style, t_attr, inner)
        for k, cn in enumerate(cols):
            if cn in g.get(prow, {}):
                ops[(prow, cn)] = ("set", vals[k])
            else:
                style = g.get(prow - 1, {}).get(cn, ("", None))[0]
                bucket[(prow, cn)] = ("new", style, "", f"<v>{vals[k]}</v>")
    xml, n = T.edit_cells(xml, ops)
    for prow in sorted({rn for rn, _c in inserts}, reverse=True):
        sub = {(rn, cn): op for (rn, cn), op in inserts.items() if rn == prow}
        xml = T.insert_row(xml, prow, sub, 10)
        n += len(sub)
    xml = T.fix_dimension(xml, 10, T.max_row_xml(xml))
    return xml, {"cells": n}


def existing_extra(led: pathlib.Path, period: str) -> dict:
    """既有值（云大ESI排名 / TOP论文 / ESI被引阈值 / Q1-Q4）→ {(sheet, 学科, 字段): 值}"""
    out = {}
    g, shared = T.read_grid(led, "云大ESI排名")
    for base_cn, cols in (("A", ("B", "C", "D")), ("G", ("H", "I", "J"))):
        prow = next((rn for rn in sorted(g)
                     if str(T.gtext(g, shared, rn, base_cn) or "").strip() == period), None)
        if prow is None:
            continue
        for k, cn in enumerate(cols):
            val = T.gtext(g, shared, prow, cn)
            if val not in (None, ""):
                out[("云大ESI排名", cn, str(k))] = val
    for sheet in ("TOP论文", "ESI被引阈值"):
        g, shared = T.read_grid(led, sheet)
        col = next((cn for cn, (a, i) in g[1].items()
                    if str(LP.cell_text(a, i, shared) or "").strip() == period), None)
        if col is None:
            continue
        for s, rn in T.subject_rows(g, shared, set(SUBJECTS)).items():
            val = T.gtext(g, shared, rn, col)
            if val not in (None, ""):
                out[(sheet, s, "v")] = val
    return out


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="ESI 侧待工具化列 → 台账（预览/写回）")
    ap.add_argument("period")
    ap.add_argument("--esi-root", default=str(T.ESI_ROOT))
    ap.add_argument("--ledger", default=str(T.LEDGER))
    ap.add_argument("--out", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--append-events", action="store_true",
                    help="把「在榜核对」查出的新进/退出事件追加到《学科进入时间》表尾")
    args = ap.parse_args()
    period = args.period
    esi_dir = pathlib.Path(args.esi_root) / period
    if not esi_dir.is_dir():
        raise SystemExit(f"[拒绝] ESI 包不存在：{esi_dir}")
    ledger = pathlib.Path(args.ledger)

    rank = read_institutions(esi_dir)
    ynu = read_ynu_fields(esi_dir)
    cn_cpp, gl_cpp, notes = read_cn_global(esi_dir)
    thr = read_thresholds(esi_dir)
    in_list, miss, bad = read_in_list(esi_dir)
    state = read_entry_state(ledger, period)
    for n in notes:
        print(f"[!] {n}")

    print(f"== 云大ESI排名 {period}: 国际={rank['国际排名']} 国内={rank['国内排名']} 高校={rank['国内高校排名']}")
    print(f"== 在榜学科 {len(ynu)} 个（总被引/论文数/TOP论文）+ 篇均：云大 {len(ynu)} / 中国 {len(cn_cpp)} / 国际 {len(gl_cpp)}")
    print(f"== ESI被引阈值 {len(thr)} 学科（示例 Chemistry={thr.get('Chemistry')}）")
    adds = []
    if miss or bad:
        print(f"== 在榜核对：缺件 {len(miss)} / 解析异常 {len(bad)} → 跳过事件推断（不瞎报）")
    else:
        need_in = [s for s in SUBJECTS if s in in_list - state]
        need_out = [s for s in SUBJECTS if s in state - in_list]
        if need_in or need_out:
            print(f"== 在榜核对：ESI 包 {len(in_list)} 个 vs 台账事件状态 {len(state)} 个 → 有差异")
            for s in need_in:
                print(f"    [建议·进入] {period[:4]}年{int(period[4:])}月 {PL.DISCIPLINES_CN.get(s) or s}")
                adds.append((period, s, "in"))
            for s in need_out:
                print(f"    [建议·退出] {period[:4]}年{int(period[4:])}月 {PL.DISCIPLINES_CN.get(s) or s}退出")
                adds.append((period, s, "out"))
            print("    （《学科进入时间》缺以上事件；--append-events 可自动追加）")
        else:
            print(f"== 在榜核对：ESI 包 {len(in_list)} 个 == 台账事件状态 {len(state)} 个 ✓")

    ex = existing_extra(ledger, period)
    bad = []
    checks = []
    for cn, k in (("B", "0"), ("C", "1"), ("D", "2")):
        checks.append(("云大ESI排名", cn, k, [rank["国际排名"], rank["国内排名"], rank["国内高校排名"]][int(k)]))
    for s, (docs, cites, cpp, top) in ynu.items():
        checks += [("总被引", s, "v", cites), ("论文数", s, "v", docs), ("TOP论文", s, "v", top)]
    for s, v in thr.items():
        checks.append(("ESI被引阈值", s, "v", v))
    for sheet, s, field, new in checks:
        old = ex.get((sheet, s, field))
        if old is not None and not T._eq(old, new):
            bad.append((sheet, s, field, old, new))
    if bad:
        print(f"\n[!] 与台账现有值冲突 {len(bad)} 处：")
        for row in bad[:12]:
            print("    ", row)
        if not args.force:
            print("    → 拒绝写入；确认后 --force")
            return 1
    elif ex:
        print(f"\n[✓] 与台账现有值逐格一致（抽查 {len(ex)} 个存量格）")
    if not (args.write or args.out):
        print("\n（预览模式。--out 写副本 / --write 写台账）")
        return 0

    tx = T.LedgerTx(ledger)
    log = {}

    def apply(sheet, result):
        xml, lg = result
        tx.put_sheet(sheet, xml)
        log[sheet] = lg

    apply("云大ESI排名", plan_esi_rank(tx, period, rank))
    apply("总被引", T.plan_wide(tx, "总被引", period, {s: v[1] for s, v in ynu.items()}))
    apply("论文数", T.plan_wide(tx, "论文数", period, {s: v[0] for s, v in ynu.items()}))
    # TOP论文：逐科计数改用**Top 论文清单**（覆盖含未进 ESI 榜的 5 科），再补合计行与年度行
    top_subj, top_years, top_total = read_top_counts(esi_dir)
    xml_top, log_top = T.plan_wide(tx, "TOP论文", period, {s: top_subj.get(s) for s in SUBJECTS})
    xml_top, log_top2 = plan_top_extra(xml_top, tx.path, period, top_years, top_total)
    tx.put_sheet("TOP论文", xml_top)
    log["TOP论文"] = {"cells": log_top["cells"] + log_top2["cells"]}
    print(f"    TOP论文：学科 {len(top_subj)} 科 + 年度 {len(top_years)} 行 + 合计 {top_total}")
    apply("ESI被引阈值", T.plan_wide(tx, "ESI被引阈值", period, thr))
    # 篇均被引：3 列（云大 / 中国大陆 / 国际）——云大只写在榜学科；中国/国际写能取到的学科
    avg_vals = {}
    for s in SUBJECTS:
        a = ynu[s][2] if s in ynu else None
        b = cn_cpp.get(s)
        c = gl_cpp.get(s)
        if a is not None or b is not None or c is not None:
            avg_vals[s] = (a, b, c)
    apply("篇均被引", plan_avg3(tx, "篇均被引", period, avg_vals))
    if args.append_events and adds:
        apply("学科进入时间", plan_events(tx, adds))
    T._do_write(tx, ledger, args, tag=f"回填{period}ESI侧前", preview_log=log)
    return 0


def plan_avg3(tx: T.LedgerTx, sheet: str, period: str, vals: dict) -> tuple[str, dict]:
    """篇均被引：每期 3 列（云大|中国大陆|国际）；逐个非空格写。"""
    xml = tx.sheet_xml(sheet)
    g, shared = T.read_grid(tx.path, sheet)
    starts = []
    for cn, (a, i) in g[2].items():
        txt = str(LP.cell_text(a, i, shared) or "").strip()
        if re.fullmatch(r"20\d{2}\.\d{2}", txt) or re.fullmatch(r"20\d{4}", txt):
            starts.append((T.col_index(cn), cn, txt))
    starts.sort()
    label = f"{period[:4]}.{period[4:]}" if starts and "." in starts[-1][2] else period
    period_col = next((cn for _i, cn, t in starts if t == label), None)
    row_of = T.subject_rows(g, shared, set(SUBJECTS))
    ops = {}
    if period_col is None:
        base, prev_base = starts[-1][0] + 3, starts[-1][0]
        t_attr, inner = T.text_op(shared, label)
        ops[(2, T.col_letter(base))] = ("new", g[2][T.col_letter(prev_base)][0], t_attr, inner)
        for k, lab in enumerate(("云大", "中国大陆", "国际")):
            t_attr, inner = T.text_op(shared, lab)
            style = g[3][T.col_letter(prev_base + k)][0] if 3 in g and T.col_letter(prev_base + k) in g[3] else ""
            ops[(3, T.col_letter(base + k))] = ("new", style, t_attr, inner)
        if "<mergeCells" in xml:
            xml = T.add_merge(xml, f"{T.col_letter(base)}2:{T.col_letter(base + 2)}2")
        vcols = {k: T.col_letter(base + k) for k in range(3)}
        prev_cols = {k: T.col_letter(prev_base + k) for k in range(3)}
    else:
        vcols = {k: T.col_letter(T.col_index(period_col) + k) for k in range(3)}
        prev_cols = {k: T.col_letter(T.col_index(period_col) + k - 3) for k in range(3)}
    for s, tup in vals.items():
        rn = row_of.get(s)
        if rn is None:
            continue
        for k, v in enumerate(tup):
            if v is None:
                continue
            cn = vcols[k]
            if cn in g.get(rn, {}):
                ops[(rn, cn)] = ("set", v)
            else:
                style = g.get(rn, {}).get(prev_cols[k], ("", None))[0]
                ops[(rn, cn)] = ("new", style, "", f"<v>{T._fmt(v)}</v>")
    xml, n = T.edit_cells(xml, ops)
    xml = T.fix_dimension(xml, max(T.col_index(c) for c in vcols.values()), T.max_row_xml(xml))
    return xml, {"cells": n}


if __name__ == "__main__":
    sys.exit(main())
