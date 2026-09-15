# -*- coding: utf-8 -*-
"""验证报告 docx 结构（文衡流水线产出）。

检查项：
  1. 16 张学科槽位表（tables[3..18]）× 6 格 = 96 格：
     每格恰好 [图题 + 图] 两段、含 1 张图、图 8.26×5.50cm（±0.05）
  2. 槽位表列宽 8.64+8.64cm（±0.02）
  3. 正文图表统计（原生图表=需人工确认；图片段=已插入的概览图等）
  4. 大表（首个 ≥11 列的 23 行表）数据行非空计数

用法：
  .venv\\Scripts\\python.exe verify_report_docx.py "out\\202607\\报告初稿_202607（试排）.docx"
返回码：0=全绿；1=有异常（列出）
"""
import sys

from docx import Document
from docx.oxml.ns import qn


def main(path):
    d = Document(path)
    fails, warns = [], []

    n_ok = 0
    for ti in range(3, 19):
        t = d.tables[ti]
        grid = t._tbl.find(qn("w:tblGrid"))
        cols = [int(g.get(qn("w:w"))) / 567 for g in grid.findall(qn("w:gridCol"))]
        if abs(cols[0] - 8.64) > 0.02:
            fails.append(f"T{ti:02d} 列宽异常: {[round(c, 2) for c in cols]}")
        for ri in range(3):
            for ci in range(2):
                c = t.rows[ri].cells[ci]
                paras = c.paragraphs
                imgs = c._element.findall(".//" + qn("w:drawing"))
                exts = c._element.findall(".//" + qn("wp:extent"))
                size_ok = False
                if exts:
                    cx = int(exts[0].get("cx")) / 360000
                    cy = int(exts[0].get("cy")) / 360000
                    size_ok = abs(cx - 8.26) < 0.05 and abs(cy - 5.50) < 0.05
                if len(paras) == 2 and len(imgs) == 1 and size_ok:
                    n_ok += 1
                else:
                    fails.append(
                        f"T{ti:02d} r{ri}c{ci}: 段={len(paras)} 图={len(imgs)} 尺寸合规={size_ok}")

    big_tables = [t for t in d.tables if len(t.columns) >= 11 and len(t.rows) == 23]
    big_filled = None
    if big_tables:
        big = big_tables[0]
        big_filled = sum(1 for r in big.rows[1:] if any(c.text.strip() for c in r.cells[1:]))
    else:
        warns.append("未找到 23×11 大表")

    body_charts = sum(1 for p in d.paragraphs if p._element.findall(".//" + qn("c:chart")))
    body_imgs = sum(1 for p in d.paragraphs if p._element.findall(".//" + qn("w:drawing")))

    print(f"槽位格通过: {n_ok}/96")
    print(f"大表数据行: {big_filled}/22")
    print(f"正文: 原生图表(需人工确认)={body_charts} 图片段={body_imgs}")
    for w in warns:
        print("警告:", w)
    if fails:
        print(f"异常 {len(fails)} 处：")
        for f in fails:
            print("  -", f)
        return 1
    if big_filled is not None and big_filled < 22:
        print("异常：大表未填满 22 行")
        return 1
    print("结构验证全绿")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
