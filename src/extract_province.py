# -*- coding: utf-8 -*-
"""从 ESI 原始包算「云南省高校学科对比表」（报告 T19）→ `out/<期次>/province.json`。

背景（2026-09-20）
------------------------------------------------------------------
T19 在历期都是**馆员手工填**的（母版里是空表）。查证后确认它的数据源就是
ESI 原始包里的**机构总表 `institutions.xlsx`**，而不是台账 —— 台账的
`高校学科发展` sheet（6 指标 × 9 校）是**另一个口径**，数值对不上
（昆工发文量：机构总表 31045 / 台账 19259），不能拿来填。

实测：本工具算出的 11 校 × 9 列 = **99/99 格与人工原件逐格一致**（202607 期）。

为什么不写回台账
------------------------------------------------------------------
台账是馆员维护的事实源，加 sheet 要走 zip 级 XML 替换（openpyxl 存盘会丢
图表/条件格式 —— 项目红线）。这里改成**居间产物**：算完落 `province.json`，
由 `fill_docx` 读它填 docx。每格都带 `src`（ESI 文件名 + 行号），
"可溯源"这条链照样闭合：报告数字 → province.json → ESI 原始包。

用法
------------------------------------------------------------------
    .venv\\Scripts\\python.exe src\\extract_province.py 202607            # dry-run，只打印
    .venv\\Scripts\\python.exe src\\extract_province.py 202607 --write    # 落 out/202607/province.json
    .venv\\Scripts\\python.exe src\\extract_province.py 202607 --check    # 与人工原件逐格比对
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import openpyxl                                                 # noqa: E402
import parse_ledger                                             # noqa: E402

#: 报告固定列这 11 所（业务口径，取自人工原件 T19 —— **不是**"云南省全部高校"）。
#: 英文名逐字取自 ESI 机构总表：别用模糊匹配，机构总表里还有中科院昆明植物所/
#: 动物所、云南省农科院这类**非高校**机构，名字里同样带 YUNNAN/KUNMING。
UNIVERSITIES = (
    ("云南大学", "YUNNAN UNIVERSITY"),
    ("昆明理工大学", "KUNMING UNIVERSITY OF SCIENCE & TECHNOLOGY"),
    ("昆明医科大学", "KUNMING MEDICAL UNIVERSITY"),
    ("西南林业大学", "SOUTHWEST FORESTRY UNIVERSITY - CHINA"),
    ("云南师范大学", "YUNNAN NORMAL UNIVERSITY"),
    ("云南农业大学", "YUNNAN AGRICULTURAL UNIVERSITY"),
    ("大理大学", "DALI UNIVERSITY"),
    ("云南中医药大学", "YUNNAN UNIVERSITY OF CHINESE MEDICINE"),
    ("云南民族大学", "YUNNAN MINZU UNIVERSITY"),
    ("云南财经大学", "YUNNAN UNIVERSITY OF FINANCE & ECONOMICS"),
    ("曲靖师范学院", "QUJING NORMAL UNIVERSITY"),
)

#: T19 的列（除"机构名称"）→ 机构总表的列名。表里直接有，不用算。
INST_COLS = {
    "国内排名": None,                    # 派生：在中国大陆机构里的序号
    "国际排名": "序号",
    "ESI前1%学科数": None,               # 派生：在几个学科榜里出现
    "发文量": "Web of Science Documents",
    "被引频次": "Cites",
    "篇均被引频次": "Cites/Paper",
    "顶尖论文": "Top Papers",
    "高被引论文": "Highly Cited Papers",
    "热点论文": "Hot Papers",
}
COLS = list(INST_COLS)

DEFAULT_ESI_ROOT = pathlib.Path("../数据与复现/ESI数据")

#: 22 个学科榜的**真实文件名**。别用 `parse_ledger.DISCIPLINES_EN` 去拼：
#: 实际文件里 `Environment/Ecology` 写作 `Environment Ecology`（斜杠变空格）、
#: `Psychiatry/Psychology` 写作 `Psychiatry Psychology`、
#: `Social Sciences, general` 是 `Social Sciences, General` ——
#: 按规范名拼只会命中 20 个，导致「ESI前1%学科数」**每校统一少 1**
#: （2026-09-20 实测：93/99，差的全是这一列）。
DISC_FILES = (
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
    "Computer Science", "Economics & Business", "Engineering", "Environment Ecology",
    "Geosciences", "Immunology", "Materials Science", "Mathematics", "Microbiology",
    "Molecular Biology & Genetics", "Multidisciplinary", "Neuroscience & Behavior",
    "Pharmacology & Toxicology", "Physics", "Plant & Animal Science",
    "Psychiatry Psychology", "Social Sciences, General", "Space Science",
)

#: ⚠ **机构总表的列序会变，必须按表头名找列**（不能按固定下标）：
#:   · 202601 / 202605 版 = 7 列：只有 `Top Papers`，**没有**高被引/热点两列
#:     → T19「高被引论文」「热点论文」× 11 校 = 22 格源端不存在，只能留空（非漏填）；
#:   · 202607 版 = 9 列：高被引第 8 列、热点第 9 列；
#:   · **202609 起（取数默认）= 15 列**：三组各带 `Cites to …` / `Cites/…` 两列，
#:     高被引挪到第 10 列、热点挪到第 13 列。
#: 🔴 2026-09-24 实测踩过：按下标读 15 列版 → 「高被引论文」被填成
#:   `Cites to Top Papers`（云大 41979，真值 290）、「热点论文」读成空
#:   （rick 问「最后一列热点论文为什么不填写」即此）。填表器与校验器共用同一读法，
#:   属于**自证式漏报** —— 换列序的期次必须按表头核一遍。
_INST_HEADERS = {
    "webofsciencedocuments": "Web of Science Documents",
    "cites": "Cites",
    "citespaper": "Cites/Paper",
    "toppapers": "Top Papers",
    "highlycitedpapers": "Highly Cited Papers",
    "hotpapers": "Hot Papers",
}


def _norm_header(v):
    """表头归一：小写 + 只留字母。`Cites/Top Paper`→`citestoppaper`，
    与 `Cites`→`cites`、`Highly Cited Papers`→`highlycitedpapers` 互不混淆。"""
    import re

    return re.sub(r"[^a-z]", "", str(v or "").lower())



def _disc_workbooks(d):
    """{学科名: 路径}。先精确匹配，再宽松（去掉非字母后比较）——
    早期包的学科榜文件名有残缺（如 `COMPUTER SCIENC.xlsx`），宽松匹配是兜底。"""
    import re
    files = {p.stem: p for p in pathlib.Path(d).glob("*.xlsx")}
    got = {}
    for want in DISC_FILES:
        p = files.get(want)
        if p is None:
            key = re.sub(r"[^a-z]", "", want.lower())
            p = next((q for stem, q in files.items()
                      if re.sub(r"[^a-z]", "", stem.lower()) == key), None)
        if p is not None:
            got[want] = p
    return got


def _num(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fnum(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def compute(esi_root, period):
    """返回 `{中文校名: {列: {"v": 值, "src": 溯源}}}`。"""
    d = pathlib.Path(esi_root) / str(period)
    inst_file = d / "institutions.xlsx"
    if not inst_file.exists():
        raise SystemExit(f"[拒绝] 找不到机构总表：{inst_file}")

    want = {en: cn for cn, en in UNIVERSITIES}
    rows, cn_rank = {}, {}
    cn_seen = 0
    # 表头在第 6 行（1-based；第 5 行是 "Indicators Results"），数据从第 7 行起。
    # 列**按表头名定位**（见 _INST_HEADERS 的上方注释：15 列版会把下标全打乱）。
    wb = openpyxl.load_workbook(inst_file, data_only=True)  # ESI 新导出 dimension 常坏，普通模式才读得全
    ws = wb[wb.sheetnames[0]]
    col_of, i_inst, i_country = {}, 1, 2
    for ridx, row in enumerate(ws.iter_rows(min_row=5, values_only=True), start=5):
        if not col_of:
            norm = [_norm_header(v) for v in row]
            if "institutions" in norm:
                col_of = {_INST_HEADERS[n]: i for i, n in enumerate(norm) if n in _INST_HEADERS}
                missing = [c for c in ("Web of Science Documents", "Cites", "Cites/Paper",
                                       "Top Papers") if c not in col_of]
                if missing:
                    raise SystemExit(f"[拒绝] 机构总表表头认不出这些列：{missing}"
                                     f"（表头={list(row)}）")
                i_inst = norm.index("institutions")
                i_country = norm.index("countriesregions") if "countriesregions" in norm else 2
            continue
        nm = str(row[i_inst] or "").strip()
        if not nm:
            continue
        if str(row[i_country] or "").strip().upper() == "CHINA MAINLAND":
            cn_seen += 1
            cn_rank[nm] = cn_seen
        if nm in want:
            rec = {
                "_row": ridx,
                "序号": _num(row[0]),
                "Web of Science Documents": _num(row[col_of["Web of Science Documents"]]),
                "Cites": _num(row[col_of["Cites"]]),
                "Cites/Paper": _fnum(row[col_of["Cites/Paper"]]),
                "Top Papers": _num(row[col_of["Top Papers"]]),
            }
            for key in ("Highly Cited Papers", "Hot Papers"):
                rec[key] = _num(row[col_of[key]]) if key in col_of else None
            rows[nm] = rec
    wb.close()

    # 学科榜：数每校在几个学科里出现 → ESI前1%学科数
    disc_hits = {en: [] for _, en in UNIVERSITIES}
    wbs = _disc_workbooks(d)
    n_disc = len(wbs)
    if n_disc < len(DISC_FILES):
        missing = [x for x in DISC_FILES if x not in wbs]
        print(f"  ⚠ 只找到 {n_disc}/{len(DISC_FILES)} 个学科榜，缺：{missing}", file=sys.stderr)
    for disc, f in wbs.items():
        try:
            wb = openpyxl.load_workbook(f, data_only=True)  # ESI 新导出 dimension 常坏，普通模式才读得全
            ws = wb[wb.sheetnames[0]]
            for row in ws.iter_rows(min_row=6, max_col=2, values_only=True):
                nm = str(row[1]).strip() if row[1] else ""
                if nm in disc_hits:
                    disc_hits[nm].append(disc)
            wb.close()
        except Exception as e:                                      # noqa: BLE001
            print(f"  ⚠ 学科榜读不了 {disc}：{type(e).__name__}", file=sys.stderr)

    out = {}
    for cn, en in UNIVERSITIES:
        r = rows.get(en)
        if not r:
            print(f"  ⚠ 机构总表里没有 {cn}（{en}）", file=sys.stderr)
            continue
        iref = f"ESI数据/{period}/institutions.xlsx#r{r['_row']}"
        rec = {}
        for col in COLS:
            if col == "国内排名":
                rec[col] = {"v": cn_rank.get(en), "src": f"{iref}（中国大陆机构第 N 位）"}
            elif col == "ESI前1%学科数":
                hits = disc_hits.get(en) or []
                show = "、".join(hits[:6]) + ("…" if len(hits) > 6 else "")
                rec[col] = {"v": len(hits),
                            "src": f"ESI数据/{period}/ 22 学科榜中出现 "
                                   f"{len(hits)}/{n_disc} 次（{show}）"}
            else:
                key = INST_COLS[col]
                v = r.get(key)
                if col == "篇均被引频次" and v is not None:
                    v = round(float(v), 2)
                rec[col] = {"v": v, "src": f"{iref}（{key} 列）"}
        out[cn] = rec
    return {"period": str(period), "n_universities": len(out),
            "n_disciplines": n_disc, "universities": out}


def write_json(period, out_dir, esi_root=None):
    """算好省域表并落 `out/<期次>/province.json`，返回数据 dict。

    `run_pipeline`（当期）与 `rerun_history`（历史期复现）**共用这一处** ——
    两处各写一份会让「复现稿」和「当期稿」的省域表来源悄悄分叉，
    而这类分叉不会报错，只会在两份报告里出现不同的数。
    """
    data = compute(esi_root if esi_root is not None else DEFAULT_ESI_ROOT, period)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "province.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def compare_with_original(data, orig_docx, period):
    """与人工原件 T19 逐格比对。返回 (一致格数, 总格数, 差异列表)。"""
    try:
        from docx import Document                               # noqa: PLC0415
    except ImportError:
        return 0, 0, [("（未安装 python-docx）", "", "")]
    d = Document(str(orig_docx))
    t19 = next((t for t in d.tables
                if (len(t.rows), len(t.columns)) == (13, 10)), None)
    if t19 is None:
        return 0, 0, [("（原件里找不到 13×10 的 T19）", "", "")]
    ok = bad = 0
    diffs = []
    for r in t19.rows[2:]:
        cn = r.cells[0].text.strip()
        if not cn or cn not in data["universities"]:
            continue
        mine = data["universities"][cn]
        for col, cell in zip(COLS, [c.text.strip() for c in r.cells[1:]]):
            v = mine.get(col, {}).get("v")
            s = "" if v is None else (f"{v:.2f}" if col == "篇均被引频次" else str(v))
            if s == cell:
                ok += 1
            else:
                bad += 1
                diffs.append((cn, col, f"算出 {s!r} ≠ 原件 {cell!r}"))
    return ok, ok + bad, diffs


def main():
    ap = argparse.ArgumentParser(description="从 ESI 原始包算省域对比表（T19）")
    ap.add_argument("period", nargs="?", default="202607")
    ap.add_argument("--esi-root", default=str(DEFAULT_ESI_ROOT))
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--write", action="store_true", help="落 out/<期次>/province.json")
    ap.add_argument("--check", action="store_true", help="与人工原件逐格比对")
    ap.add_argument("--orig", default="../云南大学原报告/云南大学学科信息参考2026年第4期.docx")
    a = ap.parse_args()

    data = compute(a.esi_root, a.period)
    print(f"算出 {data['n_universities']} 所高校 × {len(COLS)} 列"
          f"（学科榜 {data['n_disciplines']} 个）")
    for cn, rec in list(data["universities"].items())[:3]:
        print(f"  {cn}: " + " ".join(
            f"{c}={rec[c]['v']}" for c in ("国内排名", "国际排名", "ESI前1%学科数", "发文量")))
    print("  …")

    if a.check:
        ok, total, diffs = compare_with_original(data, pathlib.Path(a.orig), a.period)
        print(f"\n与人工原件逐格比对：一致 {ok}/{total}")
        for cn, col, msg in diffs[:20]:
            print(f"  ✗ {cn} {col}: {msg}")
        if total and ok == total:
            print("  ✓ 全对 —— 口径与原件完全一致")

    if a.write:
        out = pathlib.Path(a.out_root) / str(a.period)
        out.mkdir(parents=True, exist_ok=True)
        (out / "province.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {out / 'province.json'}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
