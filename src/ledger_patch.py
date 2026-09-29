# -*- coding: utf-8 -*-
"""台账（唯一事实源）的 **zip 级**安全改写。

铁律
----
《云大全学科排名、阈值动态检测表.xlsx》**禁止用 openpyxl 存盘**——会把图表、条件格式、
打印设置、列宽全部丢掉。所有写入只重写**目标 sheet 的 XML**，其余 zip 成员逐字节原样复制。

用法
----
    from ledger_patch import backup, read_grid, locate, write_cells, diff_members

    bak = backup(LEDGER, "改P0-4前")
    grid, shared = read_grid(LEDGER, "总被引")
    r = locate(grid, shared, "A", "Economics & Business")   # 行号
    c = locate(grid, shared, 1, "202003", by="row")         # 列字母
    write_cells(LEDGER, "总被引", {(r, c): 31})
    diff_members(bak, LEDGER, "总被引")                     # 非目标成员必须 0 变化

口径
----
- 只支持**已有单元格改值**（<v> 替换）。加列/加行请用 `write_sheet_table` 或
  `extract_1permille.rewrite_sheet`。
- 目标单元格若含公式（<f>）直接拒绝：改值会让公式与缓存值不一致。
"""
import hashlib
import html
import pathlib
import re
import shutil
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
BACKUP_DIR = REPO.parent / "归档" / "台账备份"

CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
ROW_RE = re.compile(r'<row r="(\d+)"([^>]*?)>(.*?)</row>', re.S)


# ------------------------------------------------------------------ zip 基础
def sheet_member(zf, sheetname):
    """sheet 名 → zip 内成员路径（如 xl/worksheets/sheet8.xml）。"""
    wbxml = zf.read("xl/workbook.xml").decode("utf-8")
    pairs = dict(re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wbxml))
    if sheetname not in pairs:
        raise KeyError(f"台账里没有 sheet「{sheetname}」，现有：{list(pairs)}")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    # 属性顺序不设前提：真台账是 Id 在前，合成文件（openpyxl）是 Type/Target/Id——
    # 逐元素独立取属性，两种都认（2026-09-29：并入工具的自测文件踩过这个坑）。
    rmap = {}
    for rel in re.findall(r"<Relationship\b[^>]*/?>", rels):
        mid = re.search(r'Id="([^"]+)"', rel)
        mt = re.search(r'Target="([^"]+)"', rel)
        if mid and mt:
            rmap[mid.group(1)] = mt.group(1)
    t = rmap[pairs[sheetname]].lstrip("/")
    return t if t.startswith("xl/") else "xl/" + t


def sheet_names(ledger):
    with zipfile.ZipFile(ledger) as zf:
        wbxml = zf.read("xl/workbook.xml").decode("utf-8")
    return re.findall(r'<sheet[^>]*name="([^"]+)"', wbxml)


def member_hashes(ledger):
    out = {}
    with zipfile.ZipFile(ledger) as zf:
        for i in zf.infolist():
            out[i.filename] = hashlib.sha256(zf.read(i.filename)).hexdigest()
    return out


def diff_members(before, after, target_sheet=None):
    """→ {'changed': [...], 'added': [...], 'removed': [...]}；非目标成员必须为空。"""
    a, b = member_hashes(before), member_hashes(after)
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    res = {"changed": changed, "added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b))}
    if target_sheet:
        with zipfile.ZipFile(after) as zf:
            tgt = sheet_member(zf, target_sheet)
        extra = [k for k in res["changed"] if k != tgt]
        res["unexpected_changed"] = extra
    return res


# ------------------------------------------------------------------ 读
def read_grid(ledger, sheetname):
    """→ ({行号: {列字母: (attrs, inner)}}, shared_strings)"""
    with zipfile.ZipFile(ledger) as zf:
        try:
            shared = ["".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
                      for si in re.findall(r"<si>(.*?)</si>",
                                           zf.read("xl/sharedStrings.xml").decode("utf-8"), re.S)]
        except KeyError:                       # 合成/简化 xlsx 可能没有共享串表（真台账必有）
            shared = []
        xml = zf.read(sheet_member(zf, sheetname)).decode("utf-8")
    grid = {}
    for mrow in ROW_RE.finditer(xml):
        rn = int(mrow.group(1))
        grid[rn] = {c: (a, i) for c, _r, a, i in CELL_RE.findall(mrow.group(3))}
    return grid, shared


def cell_text(attrs, inner, shared):
    """把 (attrs, inner) 还原成用户看到的文本/数字字符串。

    支持三类：共享字符串（t="s"）、**行内字符串**（t="inlineStr"，工具新写的期次标签用这种）、
    其余数字/普通文本。
    """
    if inner is None:
        return None
    if "<is>" in inner:                                   # 行内字符串（可含多段 <t>）
        parts = re.findall(r"<t[^>]*>(.*?)</t>", inner, re.S)
        if parts:
            return html.unescape("".join(parts))
    if 't="s"' in attrs:
        m = re.search(r"<v>(\d+)</v>", inner)
        return html.unescape(shared[int(m.group(1))]) if m else None
    m = re.search(r"<v>([^<]*)</v>", inner)
    return html.unescape(m.group(1)) if m else None


def locate(grid, shared, row_or_col, label, by="col", sheet_header_row=1):
    """定位标签所在的**行号**（by="col"：在 A 列找）或**列字母**（by="row"：在表头行找）。

    宽松比较：去空格、大小写无关、全角百分号归一。
    """
    def norm(s):
        return re.sub(r"[\s　]+", "", str(s or "")).replace("％", "%").lower()

    want = norm(label)
    if by == "col":
        for rn in sorted(grid):
            t = cell_text(*grid[rn].get(row_or_col, ("", None)), shared)
            if norm(t) == want:
                return rn
        raise KeyError(f"A 列找不到「{label}」")
    for cn, (a, i) in sorted(grid.get(sheet_header_row, {}).items(),
                             key=lambda kv: (len(kv[0]), kv[0])):
        if norm(cell_text(a, i, shared)) == want:
            return cn
    raise KeyError(f"表头行找不到「{label}」")


# ------------------------------------------------------------------ 写
def write_cells(ledger, sheetname, updates, dry=False):
    """把 {(行号, 列字母): 新值} 写进目标 sheet 的 XML。其余成员原样复制。

    → 实际改动的单元格列表 [((行,列), 旧文本, 新文本)]；无变化返回 []。
    """
    ledger = pathlib.Path(ledger)
    with zipfile.ZipFile(ledger) as zf:
        member = sheet_member(zf, sheetname)
        xml = zf.read(member).decode("utf-8")
        members = {i.filename: zf.read(i.filename) for i in zf.infolist()}
        infos = zf.infolist()
    shared = ["".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
              for si in re.findall(r"<si>(.*?)</si>",
                                   members["xl/sharedStrings.xml"].decode("utf-8"), re.S)]

    applied = []

    def fix(mrow):
        rn = int(mrow.group(1))
        cells = {c: (a, i) for c, _r, a, i in CELL_RE.findall(mrow.group(3))}
        touched = False
        out = []
        for cn, (a, i) in cells.items():
            key = (rn, cn)
            if key in updates:
                new = updates[key]
                if "<f>" in (i or "") or "<f " in (a or ""):
                    raise SystemExit(f"[拒绝] {sheetname}!{cn}{rn} 含公式，改值会让缓存值失配")
                old = cell_text(a, i, shared)
                if str(old) != str(new):
                    if not isinstance(new, (int, float)) or isinstance(new, bool):
                        raise SystemExit(
                            f"[拒绝] {sheetname}!{cn}{rn}：write_cells 只写数字，"
                            f"收到 {type(new).__name__}（文本请用 write_sheet_table）")
                    applied.append((key, old, new))
                    # 复用原始 attrs（a 自带前导空格），只摘掉 t="…"——
                    # 新内容是 <v>数字</v>，保留 t="s" 会被 Excel 当成共享字符串下标。
                    # 🔴 曾在此处用 re.search 抠 s="…" 再拼回，丢了前导空格 →
                    #    产出 `<c r="H23"s="53">`，整个 sheet XML 非法。
                    attrs = re.sub(r'\s+t="[^"]*"', "", a or "")
                    out.append(f'<c r="{cn}{rn}"{attrs}><v>{new}</v></c>')
                    touched = True
                    continue
            out.append(f'<c r="{cn}{rn}"{a}>{i}</c>' if i is not None
                       else f'<c r="{cn}{rn}"{a}/>')
        if not touched:
            return mrow.group(0)
        return f'<row r="{rn}"{mrow.group(2)}>' + "".join(out) + "</row>"

    new_xml = ROW_RE.sub(fix, xml)
    if not applied:
        return []
    # 🔴 自检闸门：改写后的 XML 必须合法，否则拒绝落盘。
    #    2026-09-18 的教训——正则拼串少个空格，整份台账变砖（唯一事实源）。
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(new_xml)
    except ET.ParseError as e:
        raise SystemExit(f"[拒绝] {sheetname} 改写后 XML 非法（{e}），未写盘。")
    if dry:
        return applied
    tmp = ledger.with_suffix(".patching.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in infos:
            data = new_xml.encode("utf-8") if info.filename == member else members[info.filename]
            zo.writestr(info, data)
    shutil.move(str(tmp), str(ledger))
    return applied


def backup(ledger, tag="bak"):
    """→ 备份路径。永不覆盖：同名自动加序号。"""
    ledger = pathlib.Path(ledger)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    base = BACKUP_DIR / f"{ledger.stem}.{tag}.bak.xlsx"
    n = 0
    while base.exists():
        n += 1
        base = BACKUP_DIR / f"{ledger.stem}.{tag}.{n}.bak.xlsx"
    shutil.copy2(ledger, base)
    return base


def audit(ledger_before, ledger_after, target_sheet, cells):
    """写入后的四件事一起查：非目标成员不变 / 目标成员 XML 良构 / 单元格新值已生效 / sheet 数不变。"""
    import openpyxl
    d = diff_members(ledger_before, ledger_after, target_sheet)
    # 🔴 2026-09-18 加：目标成员必须 XML 良构（那次事故就是写坏 XML 却没拦住）
    import xml.etree.ElementTree as ET
    bad_xml = []
    with zipfile.ZipFile(ledger_after) as zf:
        for n in zf.namelist():
            if n.endswith((".xml", ".rels")):
                try:
                    ET.fromstring(zf.read(n))
                except ET.ParseError as e:
                    bad_xml.append((n, str(e)))
    wb = openpyxl.load_workbook(ledger_after, read_only=True, data_only=True)
    got = {}
    for (rn, cn), new in cells.items():
        got[(rn, cn)] = wb[target_sheet].cell(row=rn, column=openpyxl.utils.column_index_from_string(cn)).value
    sheets = wb.sheetnames
    wb.close()
    res = {"diff": d, "readback": got, "sheets": len(sheets), "bad_xml": bad_xml}
    res["ok"] = (not bad_xml and not d.get("unexpected_changed") and not d["added"] and not d["removed"])
    return res
