# -*- coding: utf-8 -*-
"""xlsx 的 zip 级读写原语：台账唯一事实源的机械保证都建在这上面。

- `member_of(zf, sheetname)`：sheet 名 → zip 成员路径。**属性顺序不设前提**——
  真台账 `Id` 在前，openpyxl 合成文件是 `Type/Target/Id`，旧正则踩过这个坑；
- `read_shared_strings(zf)`：共享串表；没有该成员返回 `[]`（前面还有它挂掉的写手）；
- `rewrite(src, replacements)`：成员级替换——良构闸先过、其余成员**逐字节原样**、
  写 `.patching.xlsx` 再 move；`dry=True` 只跑良构闸不落盘；
- `sha256_file(path)`：1 MiB 分块文件指纹（台账只读护栏共用）。

策略（公式拒改、数字白名单、列白名单、备份、冲突拒写）留在各写手/并入工具里；
这里只回答「怎么动 zip、其余字节一个不动」。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile

RELS = "xl/_rels/workbook.xml.rels"


def member_of(zf, sheetname):
    """sheet 名 → zip 内成员路径（如 `xl/worksheets/sheet8.xml`）。"""
    wbxml = zf.read("xl/workbook.xml").decode("utf-8")
    pairs = {}
    for el in re.findall(r"<sheet\b[^>]*/?>", wbxml):
        mn = re.search(r'name="([^"]+)"', el)
        mi = re.search(r'r:id="([^"]+)"', el)
        if mn and mi:
            pairs[mn.group(1)] = mi.group(1)
    if sheetname not in pairs:
        raise KeyError(f"台账里没有 sheet「{sheetname}」，现有：{list(pairs)}")
    rels = zf.read(RELS).decode("utf-8")
    rmap = {}
    for rel in re.findall(r"<Relationship\b[^>]*/?>", rels):
        mid = re.search(r'Id="([^"]+)"', rel)
        mt = re.search(r'Target="([^"]+)"', rel)
        if mid and mt:
            rmap[mid.group(1)] = mt.group(1)
    t = rmap[pairs[sheetname]].lstrip("/")
    return t if t.startswith("xl/") else "xl/" + t


def read_shared_strings(zf) -> list:
    """`xl/sharedStrings.xml` → 串列表；没有该成员返回 []。"""
    try:
        xml = zf.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        return []
    return ["".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def rewrite(src, replacements: dict, *, dry: bool = False) -> None:
    """成员级替换：良构闸 → 其余成员逐字节复制 → 临时文件 → move。

    `replacements`：`{zip 成员名: str|bytes}`（只该动目标 sheet 的 XML）。
    良构不过抛 `SystemExit`（连 dry 也跑闸）——唯一事实源宁可不落盘。
    """
    src = pathlib.Path(src)
    payload = {name: (data.encode("utf-8") if isinstance(data, str) else bytes(data))
               for name, data in replacements.items()}
    for name, data in payload.items():
        try:
            ET.fromstring(data)
        except ET.ParseError as e:
            raise SystemExit(f"[拒绝] {name} 改写后 XML 非法（{e}），未写盘。")
    if dry:
        return
    with zipfile.ZipFile(src) as zf:
        infos = zf.infolist()
        members = {i.filename: zf.read(i.filename) for i in infos}
    for name in payload:
        if name not in members:
            raise KeyError(f"目标成员不存在：{name}")
    tmp = src.with_suffix(".patching.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in infos:
            zo.writestr(info, payload.get(info.filename, members[info.filename]))
    shutil.move(str(tmp), str(src))


def sha256_file(path) -> str:
    """文件指纹（1 MiB 分块）。缺文件抛；要 None 语义由调用方薄壳处理。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()
