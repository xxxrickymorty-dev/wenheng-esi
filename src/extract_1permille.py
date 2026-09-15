# -*- coding: utf-8 -*-
"""从 ESI 原始下载包抽取「前 1% / 前 0.1%（千分之一）」被引阈值，并可写回台账。

背景与口径（2026-09-15 反推确立，用 202605 全 23 项验证 23/23 命中）
--------------------------------------------------------------------
ESI 每个学科的「机构榜」（文件如 `Chemistry.xlsx`）只收录**全球前 1%** 的机构，
按 Cites 降序排列。由此：

  · 1%  阈值 = 榜单**末位**机构的 Cites
                （恒等于 `ThresholdESI.xlsx` 的 INSTITUTION 列，可作交叉校验）
  · 1‰  阈值 = 榜单第 **floor((m+1)/10)** 位机构的 Cites
                榜单前 10% 即全局前 0.1% = 千分之一
                m = 榜单有效数据行数；+1 是因为馆员的百分比区间**含表头行**

榜单结构（三种期次导出一致）：
    行4 = 说明行、行5 = 表头、行6 起为数据
    列 A 序号 │ B Institutions │ C Countries/Regions │ D WoS Docs │ E Cites │ F Cites/Paper │ G Top Papers
注意：**这些导出文件的单元格是文本**（'111691' 而非 111691），必须自行转数。

用法
----
    # 只看（dry-run，默认）
    .venv\\Scripts\\python.exe src\\extract_1permille.py 202601

    # 写回台账（先自动备份，再只改目标 sheet 的 XML，其余 zip 成员字节不变）
    .venv\\Scripts\\python.exe src\\extract_1permille.py 202601 --write

    # 手工指定数据根目录 / 目标台账
    ... --data-root "..\\数据与复现\\202601-03ESI数据" --ledger "<台账.xlsx>" --ledger "<另一份.xlsx>"

写回是**按列追加、绝不覆盖历史**：新期次与现有期次合并后按时间序重排，已存在的值若与
新算值冲突会**拒绝写入**并报错（口径变化必须先人工确认）。
"""
import argparse
import html
import pathlib
import re
import shutil
import sys
import zipfile

import openpyxl

REPO = pathlib.Path(__file__).resolve().parent.parent          # wenheng/
SHEET = "千分之一被引阈值"

# 台账学科名（与 parse_ledger.DISCIPLINES_EN 对齐） → ESI 原始文件名
DISC_FILES = {
    "Agricultural Sciences": "Agricultural Sciences.xlsx",
    "Biology & Biochemistry": "Biology & Biochemistry.xlsx",
    "Chemistry": "Chemistry.xlsx",
    "Clinical Medicine": "Clinical Medicine.xlsx",
    "Computer Science": "Computer Science.xlsx",
    "Economics & Business": "Economics & Business.xlsx",
    "Engineering": "Engineering.xlsx",
    "Environment/Ecology": "Environment Ecology.xlsx",
    "Geosciences": "Geosciences.xlsx",
    "Immunology": "Immunology.xlsx",
    "Materials Science": "Materials Science.xlsx",
    "Mathematics": "Mathematics.xlsx",
    "Microbiology": "Microbiology.xlsx",
    "Molecular Biology & Genetics": "Molecular Biology & Genetics.xlsx",
    "Multidisciplinary": "Multidisciplinary.xlsx",
    "Neuroscience & Behavior": "Neuroscience & Behavior.xlsx",
    "Pharmacology & Toxicology": "Pharmacology & Toxicology.xlsx",
    "Physics": "Physics.xlsx",
    "Plant & Animal Science": "Plant & Animal Science.xlsx",
    "Psychiatry/Psychology": "Psychiatry Psychology.xlsx",
    "Social Sciences, general": "Social Sciences, General.xlsx",
    "Space Science": "Space Science.xlsx",
}
OVERALL_FILE = "Institutions.xlsx"          # 全校整体（台账不存，仅供信息）

DEFAULT_DATA_ROOT = REPO.parent / "数据与复现" / "202601-03ESI数据"
DEFAULT_LEDGERS = [
    REPO.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx",
    REPO / "input" / "202607" / "监测表.xlsx",
]
BACKUP_DIR = REPO.parent / "归档" / "台账备份"


def _num(v):
    """ESI 导出为文本，统一转 float。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def parse_ranking(path):
    """返回 (cites 列表 降序, m)。找不到机构榜时返回 (None, 0)。"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    best = None
    try:
        for sn in wb.sheetnames:
            rows = list(wb[sn].iter_rows(values_only=True))
            if len(rows) < 8:
                continue
            hdr = " ".join(str(c) for c in (rows[5] or []) if c)
            if "Institutions" not in hdr:
                continue
            cites = []
            for r in rows[6:]:
                if not r or len(r) < 5 or _num(r[0]) is None:
                    break                       # 末尾版权行/空行即终止
                cites.append(_num(r[4]))
            if best is None or len(cites) > len(best):
                best = cites
    finally:
        wb.close()
    if not best:
        return None, 0
    return best, len(best)


def extract_period(data_root, period):
    """→ {学科: {'m','t1pct','t1pm','rank_1pm','inst_1pm'}} + '__OVERALL__'"""
    d = pathlib.Path(data_root) / str(period)
    if not d.is_dir():
        raise SystemExit(f"数据目录不存在：{d}")
    out = {}
    for disc, fn in DISC_FILES.items():
        p = d / fn
        if not p.exists():
            out[disc] = {"error": f"缺文件 {fn}"}
            continue
        cites, m = parse_ranking(p)
        if not cites:
            out[disc] = {"error": "未识别机构榜 sheet"}
            continue
        rank = (m + 1) // 10
        out[disc] = {"m": m, "t1pct": int(cites[-1]),
                     "t1pm": int(cites[rank - 1]), "rank_1pm": rank}
    p = d / OVERALL_FILE
    if p.exists():
        cites, m = parse_ranking(p)
        if cites:
            rank = (m + 1) // 10
            out["__OVERALL__"] = {"m": m, "t1pct": int(cites[-1]),
                                  "t1pm": int(cites[rank - 1]), "rank_1pm": rank}
    return out


def crosscheck_t1pct(data_root, period, res):
    """1% 阈值 与 ThresholdESI.xlsx 的 INSTITUTION 列比对，作口径体检。"""
    p = pathlib.Path(data_root) / str(period) / "ThresholdESI.xlsx"
    if not p.exists():
        return None
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        thr = {}
        for r in ws.iter_rows(values_only=True):
            if r[0] and _num(r[3]) is not None and str(r[0]).strip().isupper():
                thr[str(r[0]).strip()] = int(_num(r[3]))
    finally:
        wb.close()
    hit = miss = 0
    detail = []
    for disc, rec in res.items():
        if disc.startswith("__") or "error" in rec:
            continue
        key = [k for k in thr
               if k.replace(" ", "").upper() == disc.replace(" ", "").upper()
               or k.upper().startswith(disc.split("/")[0].upper()[:8])]
        if not key:
            continue
        if thr[key[0]] == rec["t1pct"]:
            hit += 1
        else:
            miss += 1
            detail.append((disc, rec["t1pct"], thr[key[0]]))
    return hit, miss, detail


# ---------------------------------------------------------------- 写回台账
def _sheet_member(zf, sheetname):
    wbxml = zf.read("xl/workbook.xml").decode("utf-8")
    pairs = dict(re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wbxml))
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rmap = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    t = rmap[pairs[sheetname]].lstrip("/")
    return t if t.startswith("xl/") else "xl/" + t


CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
ROW_RE = re.compile(r'<row r="(\d+)"([^>]*?)>(.*?)</row>', re.S)


def read_sheet_table(ledger, sheetname=SHEET):
    """→ (periods:list[str], {学科: {期次: 值}})"""
    zf = zipfile.ZipFile(ledger)
    try:
        shared = ["".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
                  for si in re.findall(r"<si>(.*?)</si>",
                                       zf.read("xl/sharedStrings.xml").decode("utf-8"), re.S)]
        member = _sheet_member(zf, sheetname)
        xml = zf.read(member).decode("utf-8")
    finally:
        zf.close()
    rows = {}
    for mrow in ROW_RE.finditer(xml):
        rn = int(mrow.group(1))
        cells = {}
        for col, _r, attrs, inner in CELL_RE.findall(mrow.group(3)):
            if 't="s"' in attrs and inner:
                cells[col] = html.unescape(shared[int(re.search(r"<v>(\d+)</v>", inner).group(1))])
            else:
                v = re.search(r"<v>([^<]*)</v>", inner) if inner else None
                cells[col] = v.group(1) if v else None
        rows[rn] = cells
    periods = [str(c) for c in [rows[1].get("B"), rows[1].get("C"), rows[1].get("D"),
                                rows[1].get("E"), rows[1].get("F")] if c]
    table = {}
    for rn in sorted(rows):
        if rn == 1:
            continue
        name = rows[rn].get("A")
        if not name:
            continue
        table[name] = {p: rows[rn].get(chr(ord("B") + i)) for i, p in enumerate(periods)}
    return periods, table


def rewrite_sheet(ledger, periods, order, table, sheetname=SHEET):
    """按 periods 顺序重写该 sheet。

    只改目标 sheet 的 XML，其余 zip 成员原样复制（保住图表/条件格式/打印设置）。
    order = [学科名...]（保持原行序）；table = {学科: {期次: 值}}
    值单元格沿用该行原 B 列样式，斑马纹与边框不变。
    """
    zf = zipfile.ZipFile(ledger)
    try:
        member = _sheet_member(zf, sheetname)
        xml = zf.read(member).decode("utf-8")
        members = {i.filename: zf.read(i.filename) for i in zf.infolist()}
        infos = zf.infolist()
    finally:
        zf.close()

    cols = [chr(ord("B") + i) for i in range(len(periods))]

    def fix(mrow):
        rn = int(mrow.group(1))
        attrs_row = mrow.group(2)
        cells = {c: (a, i) for c, _r, a, i in CELL_RE.findall(mrow.group(3))}
        a_attr, a_inner = cells["A"]
        b_attr = cells["B"][0]                       # 该行值列样式（斑马纹）
        if a_inner is not None:
            head = f'<c r="A{rn}"{a_attr}>{a_inner}</c>'
        else:
            head = f'<c r="A{rn}"{a_attr}/>'
        if rn == 1:                                  # 表头行 → 期次号
            vals = list(periods)
        elif rn - 2 < len(order):                    # 数据行 → 按学科取值
            vals = [table[order[rn - 2]].get(p, "") for p in periods]
        else:
            return mrow.group(0)                     # 结构外的行，原样保留
        body = "".join(f'<c r="{c}{rn}"{b_attr}><v>{v}</v></c>' for c, v in zip(cols, vals))
        spans = re.sub(r'spans="1:\d+"', f'spans="1:{len(periods) + 1}"', attrs_row)
        return f'<row r="{rn}"{spans}>{head}{body}</row>'

    new_xml = ROW_RE.sub(fix, xml)
    last_col = chr(ord("A") + len(periods))
    last_row = len(order) + 1
    new_xml = re.sub(r'<dimension ref="A1:[A-Z]+\d+"/>',
                     f'<dimension ref="A1:{last_col}{last_row}"/>', new_xml)
    if new_xml == xml:
        return False
    tmp = ledger.with_suffix(".patching.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in infos:
            data = new_xml.encode("utf-8") if info.filename == member else members[info.filename]
            zo.writestr(info, data)
    shutil.move(str(tmp), str(ledger))
    return True


def update_ledger(ledger, period, values):
    """把某期次的 22 学科 1‰ 值按时间序写回台账。→ (periods, is_new)"""
    periods, table = read_sheet_table(ledger)
    order = list(table.keys())
    for disc, v in values.items():                   # 冲突即拒绝，绝不悄悄覆盖
        old = table.get(disc, {}).get(str(period))
        if old not in (None, "") and _num(old) is not None and int(_num(old)) != int(v):
            raise SystemExit(f"[拒绝写入] {ledger.name} 中 {disc} @{period} 已有 {old}，"
                             f"与新算 {v} 不符；口径变化需人工确认后再改。")
    is_new = str(period) not in periods
    if is_new:
        periods = sorted(set(periods) | {str(period)})
    for disc, v in values.items():
        if disc in table:
            table[disc][str(period)] = int(v)
    rewrite_sheet(ledger, periods, order, table)
    return periods, is_new


def main():
    ap = argparse.ArgumentParser(description="抽取 ESI 1‰/1% 被引阈值（可写回台账）")
    ap.add_argument("period", help="期次，如 202601")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    ap.add_argument("--ledger", action="append", default=None,
                    help="要写回的台账（可多次）；默认两份已知台账")
    ap.add_argument("--write", action="store_true", help="写回台账（默认只打印）")
    args = ap.parse_args()

    res = extract_period(args.data_root, args.period)
    print(f"### {args.period} 1‰ / 1% 阈值（数据根：{pathlib.Path(args.data_root).name}）")
    print(f"{'学科':30s} {'m':>7s} {'rank':>6s} {'1‰阈值':>10s} {'1%阈值':>9s}")
    values = {}
    for disc, rec in res.items():
        if disc.startswith("__"):
            continue
        if "error" in rec:
            print(f"{disc:30s}  !! {rec['error']}")
            continue
        values[disc] = rec["t1pm"]
        print(f"{disc:30s} {rec['m']:>7d} {rec['rank_1pm']:>6d} {rec['t1pm']:>10,d} {rec['t1pct']:>9,d}")
    ov = res.get("__OVERALL__")
    if ov:
        print(f"{'[整体 Institutions]':30s} {ov['m']:>7d} {ov['rank_1pm']:>6d} "
              f"{ov['t1pm']:>10,d} {ov['t1pct']:>9,d}   ← 台账不存，仅参考")

    cc = crosscheck_t1pct(args.data_root, args.period, res)
    if cc:
        hit, miss, detail = cc
        print(f"\n口径体检：1% 阈值 vs ThresholdESI.INSTITUTION → 相符 {hit} / 不符 {miss}")
        for d in detail:
            print(f"   ✗ {d[0]}: 末位 {d[1]} vs {d[2]}")

    if not args.write:
        print("\n（dry-run。加 --write 写回台账）")
        return

    ledgers = [pathlib.Path(x) for x in (args.ledger or DEFAULT_LEDGERS)]
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for lg in ledgers:
        if not lg.exists():
            print(f"[跳过] 不存在：{lg}")
            continue
        bak = BACKUP_DIR / f"{lg.stem}.{args.period}.bak.xlsx"
        shutil.copy2(lg, bak)
        periods, n_new = update_ledger(lg, args.period, values)
        print(f"\n已写回 {lg}\n  备份 → {bak}\n  期次列现为 {periods}")
    print("完成。请重新运行 rerun_history.py 复现目标期次。")


if __name__ == "__main__":
    sys.exit(main())
