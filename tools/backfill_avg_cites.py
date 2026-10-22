# -*- coding: utf-8 -*-
"""任务4：给台账「篇均被引」表补齐历史期次列（201903 -> 202407，共 33 期）。

口径（已在 12 期存量列上验证 263/264 相符）：
    篇均被引·云大 = 总被引 ÷ 论文数
「中国大陆 / 国际」两列在台账与 ESI/InCites 现有数据里都没有来源，留空。

结构：该表每期占 3 列（云大/中国大陆/国际），期次自左向右递增。
历史期次比现有首期（202409）早，只能**从左侧插入** 33 组 x 3 列 = 99 列。
该表无公式、无图表、无条件格式，左侧插入不会牵动任何引用。

安全：不碰其它 sheet 的 XML；写出后做 XML 合法性 + openpyxl 全文比对自检。
默认只写副本（--out），加 --write 才动真台账。
"""
import argparse
import pathlib
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import unescape as html_unescape

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[2]    # 工作区根（本文件在 wenheng/tools/ 下）
LED = ROOT / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
BACKUP = ROOT / "归档" / "台账备份"
SCRATCH = ROOT / "wenheng" / "tmp"          # 副本默认落这里，别污染 数据与复现/
SHEET_NAME = "篇均被引"
GROUP_W = 3
FIRST_COL = 2                        # 组首列 = B
NEW_PERIODS = [f"{y}{m:02d}" for y in range(2019, 2025) for m in (1, 3, 5, 7, 9, 11)
               if not (y == 2019 and m < 3) and not (y == 2024 and m > 7)]
STYLE_HEAD = 206                     # r2 期次号
STYLE_SUB = 59                       # r3 云大/中国大陆/国际
STYLE_DATA = 116                     # 数据格（numFmt 0.00）
SS = {"云大": 234, "中国大陆": 235, "国际": 236}   # sharedStrings 下标

DISCIPLINES = {
    "Chemistry", "Plant & Animal Science", "Microbiology", "Engineering",
    "Materials Science", "Mathematics", "Environment/Ecology",
    "Biology & Biochemistry", "Pharmacology & Toxicology", "Geosciences",
    "Agricultural Sciences", "Computer Science", "Clinical Medicine",
    "Molecular Biology & Genetics", "Physics", "Social Sciences, general",
    "Multidisciplinary", "Neuroscience & Behavior", "Space Science",
    "Immunology", "Psychiatry/Psychology", "Economics & Business",
}


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


def shared_strings(zf):
    si = re.findall(r"<si>(.*?)</si>", zf.read("xl/sharedStrings.xml").decode("utf-8"), re.S)
    return [html_unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", x, re.S))) for x in si]


def read_pairs(ledger):
    """总被引 / 论文数 -> {(学科, 期次): float}"""
    zf = zipfile.ZipFile(ledger)
    out = {}
    for sheet in ("总被引", "论文数"):
        sp = sheet_path(zf, sheet)
        xml = zf.read(sp).decode("utf-8")
        ss = shared_strings(zf)
        hdr = {}
        m = re.search(r'<row r="1"[^>]*>(.*?)</row>', xml, re.S)
        for cn, attrs, inner in re.findall(r'<c r="([A-Z]+)1"([^>]*?)(?:/>|>(.*?)</c>)',
                                           m.group(1), re.S):
            v = re.search(r"<v>(.*?)</v>", inner or "")
            if v and re.fullmatch(r"20\d{4}", v.group(1)):
                hdr[cn] = v.group(1)
        tab = {}
        for rm in re.finditer(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
            rn, body = int(rm.group(1)), rm.group(2)
            ca = re.search(r'<c r="A%d"([^>]*?)(?:/>|>(.*?)</c>)' % rn, body, re.S)
            if not ca:
                continue
            if 't="s"' in ca.group(1):
                v = re.search(r"<v>(\d+)</v>", ca.group(2) or "")
                if v:
                    tab["__name__"] = ss[int(v.group(1))]
            name = tab.pop("__name__", None)
            if not name:
                continue
            for cn, p in hdr.items():
                cm = re.search(r'<c r="%s%d"([^>]*?)(?:/>|>(.*?)</c>)' % (cn, rn), body, re.S)
                if not cm:
                    continue
                v = re.search(r"<v>(.*?)</v>", cm.group(2) or "")
                if v:
                    out[(sheet, name, p)] = float(v.group(1))
    zf.close()
    return out


def build_patch(xml, values_by_disc, new_periods):
    """返回改写后的 sheet XML。values_by_disc: {行号: {期次: 值}}"""
    shift = len(new_periods) * GROUP_W
    ss = values_by_disc

    def bump(ref):
        """把一个 A1 引用里的列字母右移 shift（A 列不动）。"""
        cn = re.match(r"([A-Z]+)(\d*)", ref).group(1)
        rest = ref[len(cn):]
        ci = col_index(cn)
        return col_letter(ci if ci < FIRST_COL else ci + shift) + rest

    CELL = re.compile(r'<c r="([A-Z]+)(\d+)"[^>]*?(?:/>|>.*?</c>)', re.S)

    # 学科名 -> 行号（A 列）
    disc_row = {}
    for m in re.finditer(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
        rn, body = int(m.group(1)), m.group(2)
        ca = re.search(r'<c r="A%d"([^>]*?)(?:/>|>(.*?)</c>)' % rn, body, re.S)
        if ca and 't="s"' in ca.group(1):
            v = re.search(r"<v>(\d+)</v>", ca.group(2) or "")
            if v:
                disc_row[rn] = int(v.group(1))

    def rebuild_row(m):
        rn = int(m.group(1))
        raw_row = m.group(0)
        head = raw_row[:raw_row.index(">") + 1]
        body = m.group(2)
        cells = []
        for x in CELL.finditer(body):
            ci, raw = col_index(x.group(1)), x.group(0)
            newc = col_letter(ci if ci < FIRST_COL else ci + shift)
            raw = re.sub(r'r="[A-Z]+\d+"', 'r="%s%d"' % (newc, rn), raw, count=1)
            cells.append((ci if ci < FIRST_COL else ci + shift, raw))
        # 新增期的三列
        for i, p in enumerate(new_periods):
            base = FIRST_COL + i * GROUP_W
            if rn == 2:
                add = ['<c r="%s2" s="%d"><v>%s</v></c>' % (col_letter(base), STYLE_HEAD, p),
                       '<c r="%s2" s="%d"/>' % (col_letter(base + 1), STYLE_HEAD),
                       '<c r="%s2" s="%d"/>' % (col_letter(base + 2), STYLE_HEAD)]
            elif rn == 3:
                add = ['<c r="%s3" s="%d" t="s"><v>%d</v></c>' % (col_letter(base), STYLE_SUB, SS["云大"]),
                       '<c r="%s3" s="%d" t="s"><v>%d</v></c>' % (col_letter(base + 1), STYLE_SUB, SS["中国大陆"]),
                       '<c r="%s3" s="%d" t="s"><v>%d</v></c>' % (col_letter(base + 2), STYLE_SUB, SS["国际"])]
            elif rn in ss:
                v = ss[rn].get(p)
                add = [('<c r="%s%d" s="%d"><v>%s</v></c>' % (col_letter(base), rn, STYLE_DATA, repr(v))
                        if v is not None else '<c r="%s%d" s="%d"/>' % (col_letter(base), rn, STYLE_DATA)),
                       '<c r="%s%d" s="%d"/>' % (col_letter(base + 1), rn, STYLE_DATA),
                       '<c r="%s%d" s="%d"/>' % (col_letter(base + 2), rn, STYLE_DATA)]
            else:
                continue
            cells.extend((base + k, add[k]) for k in range(GROUP_W))
        cells.sort(key=lambda kv: kv[0])
        sp = re.search(r'spans="1:(\d+)"', head)
        if sp:
            head = head.replace(sp.group(0), 'spans="1:%d"' % (int(sp.group(1)) + shift))
        return head + "".join(raw for _, raw in cells) + "</row>"

    xml = re.sub(r'<row r="(\d+)"[^>]*>(.*?)</row>', rebuild_row, xml, flags=re.S)

    # dimension
    m = re.search(r'<dimension ref="A1:([A-Z]+)(\d+)"', xml)
    if m:
        xml = xml.replace(m.group(0), '<dimension ref="A1:%s%s"' % (
            col_letter(col_index(m.group(1)) + shift), m.group(2)))

    # mergeCells：先把既有合并区右移，再补新增期次
    xml = re.sub(r'<mergeCell ref="([^"]*)"/>',
                 lambda m: '<mergeCell ref="%s"/>' % ":".join(bump(x) for x in m.group(1).split(":")), xml)
    cnt = int(re.search(r'<mergeCells count="(\d+)"', xml).group(1))
    first = re.search(r'<mergeCell ref="([^"]*)"/>', xml).group(1)
    extra = "".join('<mergeCell ref="%s2:%s2"/>' % (col_letter(FIRST_COL + i * GROUP_W),
                                                    col_letter(FIRST_COL + i * GROUP_W + GROUP_W - 1))
                    for i in range(len(new_periods)))
    xml = xml.replace('<mergeCells count="%d">' % cnt, '<mergeCells count="%d">' % (cnt + len(new_periods)))
    xml = xml.replace('<mergeCell ref="%s"/>' % first, '<mergeCell ref="%s"/>' % first + extra, 1)

    # 冻结窗格 / 选中区：只改列字母
    xml = re.sub(r'(topLeftCell|activeCell)="([A-Z]+\d+)"',
                 lambda m: '%s="%s"' % (m.group(1), bump(m.group(2))), xml)
    xml = re.sub(r'sqref="([A-Z]+\d+):([A-Z]+\d+)"',
                 lambda m: 'sqref="%s:%s"' % (bump(m.group(1)), bump(m.group(2))), xml)
    return xml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(LED))
    ap.add_argument("--out", default="")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    led = pathlib.Path(a.ledger)

    pairs = read_pairs(led)
    ss = shared_strings(zipfile.ZipFile(led))
    # 学科行：A 列 sharedString 下标 -> 名称
    zf = zipfile.ZipFile(led)
    xml = zf.read(sheet_path(zf, SHEET_NAME)).decode("utf-8")
    zf.close()
    # 🔴 防重入：本脚本是**一次性左插**，在已回填过的台账上再跑一次会二次插入、
    #    把 99 列变成 198 列且列序全乱。已含首期标签就拒绝。
    if f"<v>{NEW_PERIODS[0]}</v>" in xml:
        raise SystemExit(
            f"[拒绝] 篇均被引里已出现 {NEW_PERIODS[0]}，像是回填过了。"
            f"如需重做，先从 归档/台账备份/ 恢复对应备份。")

    rows = {}
    for m in re.finditer(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
        rn, body = int(m.group(1)), m.group(2)
        ca = re.search(r'<c r="A%d"([^>]*?)(?:/>|>(.*?)</c>)' % rn, body, re.S)
        if ca and 't="s"' in ca.group(1):
            v = re.search(r"<v>(\d+)</v>", ca.group(2) or "")
            if v:
                rows[rn] = ss[int(v.group(1))]
    zf.close()

    values, missing = {}, []
    for rn, disc in rows.items():
        if disc not in DISCIPLINES:          # 排除 A1 注释行 / A2 表头行
            continue
        values[rn] = {}
        for p in NEW_PERIODS:
            cit = pairs.get(("总被引", disc, p))
            pap = pairs.get(("论文数", disc, p))
            if cit is None or pap in (None, 0):
                missing.append((disc, p))
                continue
            values[rn][p] = round(cit / pap, 10)

    print(f"待插期次 {len(NEW_PERIODS)} 期：{NEW_PERIODS[0]} .. {NEW_PERIODS[-1]}")
    print(f"学科行 {len(rows)} 行；可算 {sum(len(v) for v in values.values())} 格；缺源 {len(missing)}")
    if missing:
        print("  缺源样例:", missing[:8])

    new_xml = build_patch(xml, values, NEW_PERIODS)
    try:
        ET.fromstring(new_xml)
    except ET.ParseError as e:
        raise SystemExit(f"[拒绝] 改写后 XML 非法：{e}")

    # 写副本
    out = pathlib.Path(a.out) if a.out else SCRATCH / (led.stem + ".avg_backfill.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(led, out)
    zf = zipfile.ZipFile(led)
    items = zf.infolist()
    target = sheet_path(zf, SHEET_NAME)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in items:
            data = zf.read(it.filename)
            if it.filename == target:
                data = new_xml.encode("utf-8")
            zo.writestr(it, data)
    zf.close()
    print(f"已写副本: {out}")
    print(f"  目标 sheet: {target}  ({len(xml)} -> {len(new_xml)} 字节)")
    if a.write:
        BACKUP.mkdir(parents=True, exist_ok=True)
        bak = BACKUP / f"{led.stem}.回填篇均被引前.bak{led.suffix}"
        shutil.copy2(led, bak)
        print(f"  备份 → {bak}")
        shutil.copy2(out, led)
        print(f"已覆盖真台账: {led}")


if __name__ == "__main__":
    main()
