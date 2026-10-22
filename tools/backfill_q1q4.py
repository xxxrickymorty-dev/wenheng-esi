# -*- coding: utf-8 -*-
"""任务5：给台账「Q1-Q4」表补齐历史期次列（2019.03 -> 2024.11，共 35 期）。

数据来源：`数据与复现/incites/数据覆盖<年>-<覆盖月>/` 里的「<实体>研究领域」类文件。
口径（已用台账已有 9 个可映射期次做逐格回放：784/784 全中）：
    台账期次 = InCites 快照**覆盖月 + 3**（进到奇数月）
    Q1..Q4 = 表头 `Qn 期刊中论文的百分比` 那四列
    🔴 老快照的表头是乱码（GBK/UTF-8 混淆，`Q1鏈熷垔涓…`），所以**不能按表头名精确匹配**；
       判据改成「表头以 Q1..Q4 开头」+「该列数值像百分比（中位数∈[0,100]、最大值≤100.5）」，
       同一 Qn 有两列（篇数 / 百分比）时取百分比那列。这与 extract_1permille.pick_cites_col
       是同一个教训：**列位置随版式漂，只能按语义挑**。

结构：该表每期占 12 列 = 3 实体（云南大学/中国大陆/全球）× 4 分位（Q1/Q2/Q3/Q4）。
历史期次比现有首期（2025.01）早，只能**从左侧插入** 35 组 × 12 列 = 420 列。
该表无公式、无图表、无条件格式（只有合并区 + 冻结窗格 + 打印设置），左侧插入不牵动引用。

⚠ 数据现实（2026-09-18 全量清点）：35 期里
    云南大学 只有 13 期有源、中国大陆 1 期、全球 0 期；
    其余要么该覆盖月无快照（2019.03/05/07/09、2022.05），要么老导出根本没有四分位列。
    → 本期只回填能拿到的部分，空列留白（占位），缺口需馆员补 InCites 导出。

默认只写副本（--out），加 --write 才动真台账。
"""
import argparse
import csv
import pathlib
import re
import shutil
import statistics
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[2]    # 工作区根（本文件在 wenheng/tools/ 下）
LED = ROOT / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
INC = ROOT / "数据与复现" / "incites"
BACKUP = ROOT / "归档" / "台账备份"
SCRATCH = ROOT / "wenheng" / "tmp"          # 副本默认落这里，别污染 数据与复现/
SHEET_NAME = "Q1-Q4"
GROUP_W = 12                     # 3 实体 × 4 分位
FIRST_COL = 2                    # 组首列 = B
N_ENTITY = 3
N_Q = 4

NEW_PERIODS = [f"{y}{m:02d}" for y in range(2019, 2025) for m in (1, 3, 5, 7, 9, 11)
               if not (y == 2019 and m < 3) and not (y == 2024 and m > 11)]
def LD(p):                       # 台账期次标签：浮点写法（202501 -> 2025.01）
    return f"{p[:4]}.{p[4:]}"

STYLE_PERIOD = 198               # r1 期次号（沿用首期样式）
STYLE_ENTITY = 198               # r2 实体名
STYLE_Q = 158                    # r3 分位标签
STYLE_DATA = 157                 # 数据格（InCites 源浅色底）
SS_ENTITY = {"云南大学": 255, "中国大陆": 250, "全球": 256}
SS_Q = {0: 251, 1: 252, 2: 253, 3: 254}          # Q1 % / Q2% / Q3 % / Q4 %

DISCIPLINES = {
    "Chemistry", "Plant & Animal Science", "Microbiology", "Engineering",
    "Materials Science", "Mathematics", "Environment/Ecology",
    "Biology & Biochemistry", "Pharmacology & Toxicology", "Geosciences",
    "Agricultural Sciences", "Computer Science", "Clinical Medicine",
    "Molecular Biology & Genetics", "Physics", "Social Sciences, general",
    "Multidisciplinary", "Neuroscience & Behavior", "Space Science",
    "Immunology", "Psychiatry/Psychology", "Economics & Business",
}
_DISC_N = {re.sub(r"\s+", "", d).lower() for d in DISCIPLINES}

ENT_ALIAS = {
    "云南大学": ["云大", "云南大学", "YUNNAN"],
    "中国大陆": ["中国", "大陆", "国内", "CHINAMAINLAND", "作者所在地"],
    "全球": ["全球", "国际", "世界"],
}
_BAN = ["趋势", "合作论文", "组织机构", "统计", "人员", "WOS", "SCI",
        "发文", "指标", "总体", "22学科", "22个学科", "全学科", "少", "论文数"]


def col_letter(i):
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(s):
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def sheet_path(zf, name):
    wb = zf.read("xl/workbook.xml").decode("utf-8")
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]*)"',
                           zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")))
    for nm, rid in re.findall(r'<sheet[^>]*name="([^"]*)"[^>]*r:id="(rId\d+)"', wb):
        if nm == name:
            return "xl/" + rels[rid].lstrip("/")
    raise SystemExit(f"找不到 sheet: {name}")


# ---------------------------------------------------------------- 源数据抽取
def _load_rows(p):
    if p.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "gbk"):
            try:
                return list(csv.reader(open(p, encoding=enc, errors="strict")))
            except Exception:
                continue
        return list(csv.reader(open(p, encoding="utf-8", errors="replace")))
    wb = __import__("openpyxl").load_workbook(p, read_only=True, data_only=True)
    r = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
    wb.close()
    return r


def _tf(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def q_cols(rows):
    """→ {Q1:列号, Q2:…, Q3:…, Q4:…}，编码无关（见模块 docstring）。"""
    if not rows:
        return None
    H = [str(c) if c is not None else "" for c in rows[0]]
    cd = {}
    for r in rows[1:]:
        if not r:
            continue
        k = re.sub(r"\s+", "", str(r[0] or "")).lower()
        if k in _DISC_N:
            cd[k] = r
    if len(cd) < 8:
        return None
    out = {}
    for q in "1234":
        cands = [j for j, h in enumerate(H) if re.match(rf"^Q{q}\b", h.strip(), re.I)]
        best = None
        for j in cands:
            vals = [_tf(r[j]) for r in cd.values() if len(r) > j]
            vals = [v for v in vals if v is not None]
            if len(vals) < 8:
                continue
            med = statistics.median(vals)
            sc = 2 if (0 <= med <= 100 and max(vals) <= 100.5) else (1 if 0 <= med <= 100 else 0)
            if best is None or sc > best[0]:
                best = (sc, j)
        if best and best[0] >= 1:
            out[f"Q{q}"] = best[1]
    return out if len(out) == 4 else None


def minus3(p):
    y, m = int(p[:4]), int(p[4:])
    m -= 3
    while m < 1:
        m += 12
        y -= 1
    return f"{y}{m:02d}"


def snapshots():
    out = {}
    for d in sorted(INC.iterdir()):
        if d.is_dir() and d.name.startswith("数据覆盖"):
            mm = re.search(r"(\d{4})\.(\d{2})", d.name)
            out[f"{mm.group(1)}{mm.group(2)}"] = d
    return out


def entity_data(sd, aliases):
    """在某快照里找该实体的「研究领域」表 → ({学科: (q1,q2,q3,q4)}, 文件名)"""
    cands = []
    for q in sd.rglob("*"):
        if not q.is_file() or q.suffix.lower() not in (".csv", ".xlsx"):
            continue
        n = re.sub(r"\s+", "", q.name)
        if any(b in n for b in _BAN):
            continue
        if any(k in n for k in aliases):
            cands.append(q)
    best = None
    for q in sorted(cands, key=lambda z: (len(z.relative_to(sd).parts), len(z.name))):
        try:
            rows = _load_rows(q)
        except Exception:
            continue
        c = q_cols(rows)
        if not c:
            continue
        got = {}
        for r in rows[1:]:
            if not r:
                continue
            k = re.sub(r"\s+", "", str(r[0] or "")).lower()
            for D in DISCIPLINES:
                if re.sub(r"\s+", "", D).lower() == k:
                    got[D] = tuple(_tf(r[c[f"Q{q}"]]) if len(r) > c[f"Q{q}"] else None
                                   for q in "1234")
        if best is None or len(got) > len(best[0]):
            best = (got, q.name)
    return best


def collect():
    """→ {(期次, 实体, 学科): (q1,q2,q3,q4)}；以及覆盖率统计"""
    snaps = snapshots()
    vals, cov = {}, {}
    for p in NEW_PERIODS:
        s = minus3(p)
        d = snaps.get(s)
        if not d:
            cov[p] = {e: None for e in ENT_ALIAS}
            continue
        cov[p] = {}
        for e, al in ENT_ALIAS.items():
            b = entity_data(d, al)
            cov[p][e] = (b[1], len(b[0])) if b else None
            if b:
                for D, t in b[0].items():
                    if all(v is not None for v in t):
                        vals[(p, e, D)] = t
    return vals, cov


# ---------------------------------------------------------------- 构建补丁
def build_patch(xml, vals, rows_by_rn):
    """xml → 改写后的 xml。vals: {(期次, 实体, 学科): (q1,q2,q3,q4)}"""
    shift = len(NEW_PERIODS) * GROUP_W
    # 🔴 必须带 `[^>]*?` 吃掉 ` s="198"` 这类属性——
    #    漏掉它只会匹配「无样式」的格（`<c r="F4">`），带样式的格（`<c r="B1" s="198">`）
    #    全部落空 → 旧内容连 A 列学科名一起被整列丢弃（2026-09-18 实测踩到）。
    CELL = re.compile(r'<c r="([A-Z]+)(\d+)"[^>]*?(?:/>|>.*?</c>)', re.S)

    def rebuild_row(m):
        rn = int(m.group(1))
        raw = m.group(0)
        head = raw[:raw.index(">") + 1]
        body = m.group(2)
        cells = []
        for x in CELL.finditer(body):
            ci, ctext = col_index(x.group(1)), x.group(0)
            newci = ci if ci < FIRST_COL else ci + shift
            ctext = re.sub(r'r="[A-Z]+\d+"', 'r="%s%d"' % (col_letter(newci), rn), ctext, count=1)
            cells.append((newci, ctext))
        for i, p in enumerate(NEW_PERIODS):
            base = FIRST_COL + i * GROUP_W
            if rn == 1:                                   # 期次号（首格带值，其余同格式空）
                add = [f'<c r="{col_letter(base)}1" s="{STYLE_PERIOD}"><v>{LD(p)}</v></c>'] + \
                      [f'<c r="{col_letter(base+k)}1" s="{STYLE_PERIOD}"/>' for k in range(1, GROUP_W)]
            elif rn == 2:                                 # 3 个实体名
                add = []
                for ei, e in enumerate(("云南大学", "中国大陆", "全球")):
                    b = base + ei * N_Q
                    add.append(f'<c r="{col_letter(b)}2" s="{STYLE_ENTITY}" t="s"><v>{SS_ENTITY[e]}</v></c>')
                    add += [f'<c r="{col_letter(b+k)}2" s="{STYLE_ENTITY}"/>' for k in range(1, N_Q)]
            elif rn == 3:                                 # Q1%/Q2%/Q3%/Q4% × 3
                add = [f'<c r="{col_letter(base+k)}3" s="{STYLE_Q}" t="s"><v>{SS_Q[k % 4]}</v></c>'
                       for k in range(GROUP_W)]
            elif 4 <= rn <= 25:                           # 数据行：按 (期次, 实体, 学科) 取值
                disc = rows_by_rn.get(rn)
                add = []
                for ei, e in enumerate(("云南大学", "中国大陆", "全球")):
                    tv = vals.get((p, e, disc))
                    for qi in range(4):
                        c = base + ei * N_Q + qi
                        if tv and tv[qi] is not None:
                            add.append(f'<c r="{col_letter(c)}{rn}" s="{STYLE_DATA}"><v>{tv[qi]}</v></c>')
                        else:
                            add.append(f'<c r="{col_letter(c)}{rn}" s="{STYLE_DATA}"/>')
            else:
                continue
            cells.extend((base + k, add[k]) for k in range(GROUP_W))
        cells.sort(key=lambda kv: kv[0])
        sp = re.search(r'spans="1:(\d+)"', head)
        if sp:
            head = head.replace(sp.group(0), 'spans="1:%d"' % (int(sp.group(1)) + shift))
        return head + "".join(t for _, t in cells) + "</row>"

    return shift, re.sub(r'<row r="(\d+)"[^>]*>(.*?)</row>', rebuild_row, xml, flags=re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(LED))
    ap.add_argument("--out", default="")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    led = pathlib.Path(a.ledger)

    zf = zipfile.ZipFile(led)
    ssxml = zf.read("xl/sharedStrings.xml").decode("utf-8")
    ss = [__import__("html").unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", x, re.S)))
          for x in re.findall(r"<si>(.*?)</si>", ssxml, re.S)]
    target = sheet_path(zf, SHEET_NAME)
    xml = zf.read(target).decode("utf-8")
    # 🔴 防重入：一次性左插 420 列；在已回填过的台账上再跑会二次插入、列序全乱。
    if f"<v>{LD(NEW_PERIODS[0])}</v>" in xml:
        raise SystemExit(
            f"[拒绝] Q1-Q4 里已出现 {LD(NEW_PERIODS[0])}，像是回填过了。"
            f"如需重做，先从 归档/台账备份/ 恢复对应备份。")
    members = {i.filename: zf.read(i.filename) for i in zf.infolist()}
    infos = zf.infolist()
    zf.close()

    # 行号 → 学科名（A 列 sharedString）
    rows_by_rn = {}
    for m in re.finditer(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
        rn = int(m.group(1))
        ca = re.search(r'<c r="A%d"([^>]*?)(?:/>|>(.*?)</c>)' % rn, m.group(2), re.S)
        if ca and 't="s"' in ca.group(1):
            v = re.search(r"<v>(\d+)</v>", ca.group(2) or "")
            if v:
                rows_by_rn[rn] = ss[int(v.group(1))]

    vals, cov = collect()
    n_cells = len(vals) * 4
    print(f"待插期次 {len(NEW_PERIODS)} 期：{NEW_PERIODS[0]} .. {NEW_PERIODS[-1]}")
    print(f"抽到可填格 {n_cells} 个（{len(vals)} 组 期×实体×学科）")
    print("\n覆盖率（源文件命中学科数 / 22）：")
    for p in NEW_PERIODS:
        c = cov[p]
        cells = " | ".join(f"{e[:4]}={'—' if c[e] is None else c[e][1]}" for e in ENT_ALIAS)
        print(f"  {p}  {cells}")

    shift, new_xml = build_patch(xml, vals, rows_by_rn)

    # dimension
    m = re.search(r'<dimension ref="A1:([A-Z]+)(\d+)"', new_xml)
    if m:
        new_xml = new_xml.replace(m.group(0), '<dimension ref="A1:%s%s"' % (
            col_letter(col_index(m.group(1)) + shift), m.group(2)))

    # mergeCells：既有右移 + 新增期 4 个/期
    new_xml = re.sub(r'<mergeCell ref="([^"]*)"/>',
                     lambda mm: '<mergeCell ref="%s"/>' % ":".join(
                         bump_ref(x, shift) for x in mm.group(1).split(":")), new_xml)
    cnt = int(re.search(r'<mergeCells count="(\d+)"', new_xml).group(1))
    first = re.search(r'<mergeCell ref="([^"]*)"/>', new_xml).group(1)
    extra = []
    for i in range(len(NEW_PERIODS)):
        base = FIRST_COL + i * GROUP_W
        extra.append('<mergeCell ref="%s1:%s1"/>' % (col_letter(base), col_letter(base + GROUP_W - 1)))
        for e in range(N_ENTITY):
            b = base + e * N_Q
            extra.append('<mergeCell ref="%s2:%s2"/>' % (col_letter(b), col_letter(b + N_Q - 1)))
    new_xml = new_xml.replace('<mergeCells count="%d">' % cnt,
                              '<mergeCells count="%d">' % (cnt + len(extra)))
    new_xml = new_xml.replace('<mergeCell ref="%s"/>' % first,
                              '<mergeCell ref="%s"/>' % first + "".join(extra), 1)

    # 冻结窗格 topLeftCell
    new_xml = re.sub(r'(topLeftCell)="([A-Z]+\d+)"',
                     lambda mm: 'topLeftCell="%s"' % bump_ref(mm.group(2), shift), new_xml)

    try:
        ET.fromstring(new_xml)
    except ET.ParseError as e:
        raise SystemExit(f"[拒绝] 改写后 XML 非法：{e}")

    out = pathlib.Path(a.out) if a.out else SCRATCH / (led.stem + ".q1q4_backfill.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in infos:
            data = new_xml.encode("utf-8") if it.filename == target else members[it.filename]
            zo.writestr(it, data)
    print(f"\n已写副本: {out}")
    print(f"  目标 sheet {target} ({len(xml)} -> {len(new_xml)} 字节)；列位移 {shift}")
    if a.write:
        BACKUP.mkdir(parents=True, exist_ok=True)
        bak = BACKUP / f"{led.stem}.回填Q1Q4前.bak{led.suffix}"
        shutil.copy2(led, bak)
        print(f"  备份 → {bak}")
        shutil.copy2(out, led)
        print(f"已覆盖真台账: {led}")


def bump_ref(ref, shift):
    cn = re.match(r"([A-Z]+)(\d*)", ref).group(1)
    rest = ref[len(cn):]
    ci = col_index(cn)
    return col_letter(ci if ci < FIRST_COL else ci + shift) + rest


if __name__ == "__main__":
    main()
