# -*- coding: utf-8 -*-
"""造一份「脏台账」样本：只把某个学科名改成一个认不出的名字。

用途：演示 / 验收「断言未过 → 带病出稿 → 附《诊断报告》」这条链路。
复赛那 10 分钟里，"上传一份脏台账，系统自己说出哪里脏、怎么核对"
是最能说明「受控自主」的一幕，需要一份**可控且可复现**的脏样本。

🔴 为什么不用 openpyxl 存盘（本项目红线）
------------------------------------------------------------------
openpyxl 存盘会**丢条件格式与图表扩展**（实测报 `Unknown extension is not
supported and will be removed`），产出的副本是被**写坏**的 —— 后面 compute 崩在
`KeyError ('rank_pct','202607')` 其实跟脏数据无关，是副本损坏。拿它判断
"脏数据会不会让流水线崩"会得出错误结论。
所以这里走 **zip 级 XML 替换**：只改目标 sheet 的一个 `<c>`，其余 zip 成员
字节照抄，格式/图表/条件格式全部保留。

用法（workdir=wenheng）：
    .venv\\Scripts\\python.exe tools\\make_dirty_ledger.py
    .venv\\Scripts\\python.exe tools\\make_dirty_ledger.py tmp\\脏台账.xlsx --name 某某新学科
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys
import zipfile

DEFAULT_SRC = pathlib.Path("out/_acquisition/202607/监测表.xlsx")   # 202607 当期核对副本
DEFAULT_DST = pathlib.Path("tmp/脏台账_演示.xlsx")
DEFAULT_SHEET = "总被引"
DEFAULT_CELL = "A2"          # 202607 台账里这里原本是 Chemistry
DEFAULT_NAME = "某某新学科"

CELL_RE = re.compile(r'<c r="{cell}"[^>]*?/>|<c r="{cell}"[^>]*?>.*?</c>')


def _sheet_member(zf, sheet_name):
    """工作表名 → `xl/worksheets/sheetN.xml`。找不到抛 SystemExit（别猜）。"""
    wb = zf.read("xl/workbook.xml").decode("utf-8")
    rid = None
    for m in re.finditer(r'<sheet[^>]*?name="([^"]+)"[^>]*?r:id="(rId\d+)"', wb):
        if m.group(1) == sheet_name:
            rid = m.group(2)
            break
    if not rid:
        raise SystemExit(f"[拒绝] 台账里没有工作表「{sheet_name}」")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    tgt = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels)).get(rid)
    if not tgt:
        raise SystemExit(f"[拒绝] {rid} 在 rels 里没有 Target")
    return "xl/" + tgt.lstrip("/").replace("xl/", "", 1) if tgt.startswith(
        "/") else "xl/" + tgt.lstrip("/")


def make_dirty(src, dst, sheet=DEFAULT_SHEET, cell=DEFAULT_CELL, name=DEFAULT_NAME):
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    if not src.exists():
        raise SystemExit(f"[拒绝] 源台账不存在：{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)

    with zipfile.ZipFile(dst) as zf:
        member = _sheet_member(zf, sheet)
        xml = zf.read(member).decode("utf-8")
        blobs = {i.filename: zf.read(i.filename) for i in zf.infolist()}

    pat = re.compile(CELL_RE.pattern.format(cell=re.escape(cell)))
    m = pat.search(xml)
    if not m:
        raise SystemExit(f"[拒绝] {sheet}!{cell} 在 XML 里找不到（换个单元格？）")
    old = m.group(0)
    # 保留原格的样式 `s="…"`，内容改成 inlineStr —— 不动 sharedStrings，最省最安全
    style = re.search(r's="(\d+)"', old)
    new = (f'<c r="{cell}"' + (f' s="{style.group(1)}"' if style else '')
           + f' t="inlineStr"><is><t>{name}</t></is></c>')
    new_xml = xml.replace(old, new, 1)

    import xml.etree.ElementTree as ET
    try:                                    # 写盘前良构自检（2026-09-18 事故后加的规矩）
        ET.fromstring(new_xml)
    except ET.ParseError as e:
        raise SystemExit(f"[拒绝] 改写后 XML 非法（{e}），未写盘。")

    tmp = dst.with_suffix(".patching.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zipfile.ZipFile(dst).infolist():
            data = new_xml.encode("utf-8") if info.filename == member else blobs[info.filename]
            zo.writestr(info, data)
    shutil.move(str(tmp), dst)
    return dst, old


def main():
    ap = argparse.ArgumentParser(description="造一份脏台账样本（zip 级改一个学科名）")
    ap.add_argument("dst", nargs="?", default=str(DEFAULT_DST))
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--sheet", default=DEFAULT_SHEET)
    ap.add_argument("--cell", default=DEFAULT_CELL)
    ap.add_argument("--name", default=DEFAULT_NAME)
    a = ap.parse_args()
    dst, old = make_dirty(a.src, a.dst, a.sheet, a.cell, a.name)
    print(f"✓ 脏台账：{dst}")
    print(f"  {a.sheet}!{a.cell}：{old}  →  {a.name}")
    print("  其余 zip 成员字节照抄，条件格式/图表未受影响。")
    print("  跑它：.venv\\Scripts\\python.exe -c "
          f"\"import run_pipeline,sys;sys.exit(run_pipeline.main(r'{dst}',out_root='tmp/_dirty_out'))\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
