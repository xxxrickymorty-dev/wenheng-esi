# -*- coding: utf-8 -*-
"""从 InCites 历史快照算「学科 × 高校矩阵」（报告 T20）→ `out/<期次>/matrix.json`。

口径（2026-09-20 由人工原件逐格反推 + 验证，四期各 11/11 吻合）
------------------------------------------------------------------
    接近度 = InCites(该期快照) 该机构该学科被引 ÷ 该学科**当期** ESI 1% 阈值
    ≥ 1 → 报告显示 `Y`（已进全球前 1%）；< 1 → 显示百分比（两位小数）

🔴 **被引必须取「当期对应的那一期快照」，不能用最新的**（rick 2026-09-20 指出）：
   那份「阈值计算方法」表里的被引数据每期覆盖更新（现已更新到 2026.06.30），
   拿最新值去算历史期次必然不对 —— 要回到历史快照重新匹配。

期次 → 快照映射（**已验证**，别用"最近快照"去猜）
| ESI 期次 | InCites 快照 | 与原件一致 |
|---|---|---|
| 202601 | 2025.11.25 | 11/11 |
| 202603 | 2025.12.31 | 11/11 |
| 202605 | 2026.02.28 | 11/11 |
| 202607 | 2026.04.30 | 11/11 |
| 202609 | 2026.06.30 | 待验证（下一期要用的） |

⚠ 未知期次**不猜**：查不到映射就报错退出 —— 猜错一期，整张矩阵都错。

用法
------------------------------------------------------------------
    .venv\\Scripts\\python.exe src\\extract_matrix.py 202607            # 打印
    .venv\\Scripts\\python.exe src\\extract_matrix.py 202607 --write    # 落 matrix.json
    .venv\\Scripts\\python.exe src\\extract_matrix.py 202607 --check    # 与人工原件逐格比对
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import openpyxl                                                 # noqa: E402
import parse_ledger                                             # noqa: E402

#: ESI 期次 → InCites 快照目录名（**逐期验证过，别改也别外推**）
SNAP_MAP = {
    "202601": "数据覆盖2015-2025.11.25",
    "202603": "数据覆盖2015-2025.12.31",
    "202605": "数据覆盖2016-2026.02.28",
    "202607": "数据覆盖2016-2026.04.30",
    "202609": "数据覆盖2016-2026.06.30",
}

#: 矩阵的 11 列 → InCites 里的机构名关键词（前缀匹配，不区分大小写）
UNIVERSITIES = (
    ("云大", "yunnan university"),
    ("昆工", "kunming university of science"),
    ("昆医", "kunming medical"),
    ("师大", "yunnan normal"),
    ("农大", "yunnan agricultural"),
    ("大理大学", "dali university"),
    ("财大", "yunnan university of finance"),
    ("西林", "southwest forestry"),
    ("民大", "yunnan minzu"),
    ("中医药大学", "yunnan university of chinese"),
    ("曲靖师范", "qujing normal"),
)

DEFAULT_INCITES = pathlib.Path("../数据与复现/incites")
DEFAULT_LEDGER = pathlib.Path("../数据与复现/云大全学科排名、阈值动态检测表.xlsx")
DEFAULT_ESI_ROOT = "../数据与复现/ESI数据"      # Y 的判据要读 ESI 1% 机构榜


def _col_index(ws, *keys, max_scan=40):
    """按**表头语义**定位列 —— 早期快照表头有乱码，写死索引必然错列。"""
    for r in ws.iter_rows(min_row=1, max_row=max_scan, max_col=14, values_only=True):
        cells = [str(c) if c is not None else "" for c in r]
        name_i = cite_i = None
        for i, c in enumerate(cells):
            if name_i is None and c in ("名称", "Name"):
                name_i = i
            if cite_i is None and ("被引频次" in c or c == "Cites"):
                cite_i = i
        if name_i is not None and cite_i is not None:
            return name_i, cite_i
    return None, None


def _norm(s):
    """归一化：只留字母数字并小写。用于跨「脏写法」比较文件名与机构名。"""
    import re
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _same_school(n, k):
    """两个**已归一化**的机构名是否指同一家。

    🔴 `yunnan university` 不能当前缀乱匹：「云南财经大学」（…offinance…）与
       「云南中医药大学」（…ofchinese…）都以它开头，串了就把云大的值取成别人的。
       ⚠ 判据用 `rest.startswith("of")`；写成 `rest[:3] != "of"` 会永远为真（切片是 `off`）。
    """
    if n == k:
        return True
    return n.startswith(k) and not n[len(k):].startswith("of")


def _disc_file(snap_dir, disc):
    """在快照里找某学科的表。

    ⚠ **不能按规范名拼路径**：InCites 导出的文件名有脏写法 ——
    `Agricultural Sciencesxlsx.xlsx`（尾巴粘了 xlsx）、
    `Social Sciences, general.xlsx`（小写 g）、`Environment Ecology.xlsx`（斜杠变空格）。
    先归一化精确比对，再退到 startswith（治尾巴粘连）。
    """
    snap_dir = pathlib.Path(snap_dir)
    want = _norm(disc)
    cands = []
    for p in snap_dir.glob("*.xlsx"):
        key = _norm(p.stem)
        if len(key) < 6:                      # `云大 研究领域.xlsx` 归一化后过短，别误配
            continue
        if key == want:
            return p
        if key.startswith(want) or want.startswith(key):
            cands.append((len(key), p))
    return min(cands)[1] if cands else None


def _read_school_cites(snap, disc):
    """一次读出 11 校在该学科的被引频次 → {简称: 值}。"""
    f = _disc_file(snap, disc)
    if f is None:
        return {}
    try:
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        name_i, cite_i = _col_index(ws)
        if name_i is None:
            wb.close()
            return {}
        out = {}
        for r in ws.iter_rows(min_row=5, max_col=max(name_i, cite_i) + 1, values_only=True):
            nm = str(r[name_i] or "").strip()
            if not nm:
                continue
            # 🔴 **必须归一化精确比对**：`yunnan university` 当前缀会同时匹上
            #    「云南财经大学」和「云南中医药大学」—— 云大的值就取成别人的了。
            n = _norm(nm)
            for short, key in UNIVERSITIES:
                if short in out:
                    continue
                if _same_school(n, _norm(key)):
                    try:
                        out[short] = float(str(r[cite_i]).replace(",", ""))
                    except (TypeError, ValueError):
                        pass
        wb.close()
        return out
    except Exception:                                           # noqa: BLE001
        return {}


def _esi_top_schools(esi_root, period, disc):
    """该学科**当期 ESI 1% 机构榜**里的机构名（归一化）。

    🔴 这是 `Y` 的判据 —— **不是**"接近度 ≥ 1"：原件里有 `102.41%` 这种
    >100% 却仍显示百分比的格子（云南财经大学·社会科学），因为该校根本
    不在 ESI 那份榜里。反过来说，在榜 = 真的进了全球前 1%。
    """
    f = pathlib.Path(esi_root) / str(period) / f"{disc}.xlsx"
    if not f.exists():
        return None
    try:
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        names = set()
        for r in ws.iter_rows(min_row=6, max_col=2, values_only=True):
            nm = str(r[1] or "").strip()
            if nm and nm.lower() != "institutions":
                names.add(_norm(nm))
        wb.close()
        return names
    except Exception:                                           # noqa: BLE001
        return None


def compute(incites_root, ledger_path, period, esi_root=None):
    """返回 `{学科中文名: {简称: {"v": "Y"|"xx.xx%", "src": ...}}}`。"""
    period = str(period)
    snap_name = SNAP_MAP.get(period)
    if not snap_name:
        raise SystemExit(
            f"[拒绝] {period} 期没有登记 InCites 快照映射。\n"
            f"       已登记：{sorted(SNAP_MAP)}\n"
            f"       新增期次请先**用人工原件反推验证**（tmp/_snap_map.py），别猜 —— "
            f"猜错一期整张矩阵都错。")
    snap = pathlib.Path(incites_root) / snap_name
    if not snap.is_dir():
        raise SystemExit(f"[拒绝] 快照目录不存在：{snap}")

    led = parse_ledger.load_ledger(pathlib.Path(ledger_path))
    thr = led["wide"]["threshold_1pct"]

    out = {}
    for en in parse_ledger.DISCIPLINES_EN:
        cn = parse_ledger.DISCIPLINES_CN.get(en)
        if not cn:
            continue
        try:
            t = float(thr.loc[en, period])
        except (KeyError, TypeError, ValueError):
            continue
        cites = _read_school_cites(snap, en)
        top = _esi_top_schools(esi_root, period, en) if esi_root else None
        rec = {}
        for short, en_key in UNIVERSITIES:
            c = cites.get(short)
            if c is None:
                rec[short] = {"v": "", "src": f"{snap.name}/{en}.xlsx（该期无此校数据）"}
                continue
            close = c / t
            if top is not None and any(_same_school(x, _norm(en_key)) for x in top):
                v = "Y"
            elif close >= 1 and top is None:
                v = "Y"                      # 没有 ESI 榜可比对时退到接近度判据
            else:
                v = f"{close*100:.2f}%"
            rec[short] = {
                "v": v,
                "src": f"{snap.name}/{en}.xlsx（被引 {c:.0f} ÷ {period} 期 1% 阈值 {t:.0f}"
                       f"{'，且在 ESI 前1%榜内' if v == 'Y' else ''}）"}
        out[cn] = rec
    return {"period": period, "snapshot": snap_name, "matrix": out,
            # 已知分歧（202607 实测 230/231，只剩这一格）。2026-09-20 追查到底：
            #   原件 T20「社会科学 × 财大」= 102.41%
            #   它 = 2169 ÷ 2118，而 2169 就在馆员那份《云南高校阈值计算方法》表的
            #   「社会科学」sheet（云南财经大学行 · 被引频次列）。
            #   但 **2169 不等于任何一期 InCites 快照**：43 个快照全扫过，
            #   2026.04.30=1901、2026.06.30=2010、2025.12.31=2203（最接近）。
            #   → 那张表的被引另有来源（疑似我们没有的中间月份快照，或「研究领域」
            #     口径的导出）。同一张表里化学能与 InCites 学科表对上、社科对不上，
            #     说明各页的更新时间/来源可能不同。
            #   **要问卜彤**：那张表的被引是从来哪导的、什么时间窗口。
            "known_diffs": [{"disc": "社会科学", "school": "财大",
                             "ours": "89.75%", "original": "102.41%",
                             "original_source": "2169（馆员表）÷ 2118（社科1%阈值）",
                             "ours_source": "1901（InCites 2026.04.30）÷ 2118",
                             "note": "2169 不在任何一期 InCites 快照里；其余 230 格用当期快照全对"}]}


def compare_with_original(data, orig_docx):
    """与人工原件 T20 逐格比对。返回 (一致, 总数, 差异)。

    ⚠ 按**表头里有「云大」「昆工」**认表 —— 早期原件的章节结构与第 4 期不同，
       用「23×12」形状识别会撞上别的表。
    """
    try:
        from docx import Document                               # noqa: PLC0415
    except ImportError:
        return 0, 0, [("（未安装 python-docx）", "", "")]
    d = Document(str(orig_docx))
    t = None
    for cand in d.tables:
        try:
            head = [c.text.strip() for c in cand.rows[0].cells]
        except (IndexError, AttributeError):
            continue
        if "云大" in head and "昆工" in head:
            t = cand
            break
    if t is None:
        return 0, 0, [("（原件里找不到 T20 矩阵表）", "", "")]
    shorts = [c.text.strip() for c in t.rows[0].cells[1:]]
    ok = bad = 0
    diffs = []
    for r in t.rows[1:]:
        cn = r.cells[0].text.strip()
        rec = data["matrix"].get(cn)
        if not rec:
            continue
        for short, cell in zip(shorts, [c.text.strip() for c in r.cells[1:]]):
            mine = (rec.get(short) or {}).get("v")
            if mine is None:
                continue
            if mine == cell:
                ok += 1
            else:
                bad += 1
                diffs.append((cn, short, f"算出 {mine!r} ≠ 原件 {cell!r}"))
    return ok, ok + bad, diffs


def main():
    ap = argparse.ArgumentParser(description="从 InCites 历史快照算 T20 矩阵")
    ap.add_argument("period", nargs="?", default="202607")
    ap.add_argument("--incites-root", default=str(DEFAULT_INCITES))
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--esi-root", default=DEFAULT_ESI_ROOT)
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--orig", default="../云南大学原报告/云南大学学科信息参考2026年第4期.docx")
    a = ap.parse_args()

    data = compute(a.incites_root, a.ledger, a.period, esi_root=a.esi_root)
    n_disc = len(data["matrix"])
    n_y = sum(1 for r in data["matrix"].values() for x in r.values() if x["v"] == "Y")
    n_pct = sum(1 for r in data["matrix"].values() for x in r.values()
                if x["v"] and x["v"] != "Y")
    print(f"{a.period} 期 · 快照 {data['snapshot']}")
    print(f"  {n_disc} 学科 × 11 校：Y（已进前1%）{n_y} 格，百分比 {n_pct} 格")

    if a.check:
        ok, total, diffs = compare_with_original(data, pathlib.Path(a.orig))
        print(f"\n与人工原件逐格比对：一致 {ok}/{total}")
        for cn, short, msg in diffs[:15]:
            print(f"  ✗ {cn} {short}: {msg}")
        if total and ok == total:
            print("  ✓ 全对 —— 口径与原件完全一致")

    if a.write:
        out = pathlib.Path(a.out_root) / a.period
        out.mkdir(parents=True, exist_ok=True)
        (out / "matrix.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {out / 'matrix.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
