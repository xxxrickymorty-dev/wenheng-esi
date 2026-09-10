# -*- coding: utf-8 -*-
"""母版原地替换：复制第 5 期骨架 → 填充数据与图表 → 产出报告初稿 + 红色件清单。

v0 范围（W2）：
  1. 大表 T01：22 学科 × 10 列数值填充（楷体 10pt，来源 table2.csv）
  2. 表头期次槽位："接近度较X月" 按上期月份更新
  3. 学科图表槽位：T03（化学）6 图插入演示（其余 15 学科同机制，待验收后批量）
  4. 红色件清单：red_slots.json（逐格审计）+ 红色件清单.md（给签单人的汇总）

原则：只动"红色件"；名词解释、版式、表头文字一律不碰。
"""
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pandas as pd  # noqa: E402
from docx import Document  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

import charts  # noqa: E402
import compute  # noqa: E402
from parse_ledger import DISCIPLINES_CN  # noqa: E402

CELL_FONT = "楷体"
CELL_SIZE = Pt(10)

# 大表列序 → table2 字段
TABLE2_COLS = ["discipline", "rank_cn_change", "papers", "cnci", "total_cites",
               "thr_1pct", "thr_1pct_gap", "thr_1permille", "permille_rank",
               "top_papers", "prox_change"]

# T03-T18 顺序 → 学科名（英文）
DETAIL_TABLES = charts.DETAIL_TABLES

# 学科图槽位：表内单元格位置 → 图文件名
CHART_SLOTS = {
    (0, 0): "rank_pct.png",
    (0, 1): "cnci.png",
    (1, 0): "papers_new.png",
    (1, 1): "cites_threshold.png",
    (2, 0): "top_papers.png",
    (2, 1): "q_dist.png",
}


def set_cell(cell, text):
    """清空单元格并写入（楷体 10pt）。"""
    for p in list(cell.paragraphs):
        p._element.getparent().remove(p._element)
    p = cell.add_paragraph()
    r = p.add_run(text)
    r.font.name = "Times New Roman"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), CELL_FONT)
    r.font.size = CELL_SIZE
    return p


def fmt_val(v):
    if v == "" or v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v) < 1000 else f"{v:.3f}"
    return str(v)


def fill_big_table(doc, t2, slots, prev_month):
    """填充 T01 大表（23×11：r0 表头，r1-r22 数据）。"""
    big = [t for t in doc.tables if len(t.columns) >= 11 and len(t.rows) == 23][0]
    header = [c.text.strip() for c in big.rows[0].cells]
    old = next((h for h in header if h.startswith("接近度较")), None)
    if old:
        new = f"接近度较{prev_month}月"
        if old != new:
            cell = big.rows[0].cells[10]
            runs = [r for p in cell.paragraphs for r in p.runs]
            if runs:
                runs[0].text = new
                for r in runs[1:]:
                    r._element.getparent().remove(r._element)
            else:
                set_cell(cell, new)
            slots.append({"location": "T01/表头", "old": old, "new": new,
                          "source": "期次参数（上期月份）"})
    for i, (_, row) in enumerate(t2.iterrows(), start=1):
        for j, col in enumerate(TABLE2_COLS):
            val = row[col]
            if col == "discipline":
                text = DISCIPLINES_CN[val]
            elif col == "cnci":
                text = f"{float(val):.2f}"
            elif col == "permille_rank":
                text = f"{float(val):.3f}"
            else:
                text = fmt_val(val)
            old = big.rows[i].cells[j].text.strip()
            if old != text:
                set_cell(big.rows[i].cells[j], text)
                slots.append({"location": f"T01/r{i}c{j}", "old": old, "new": text,
                              "source": "table2.csv"})
    return big


def insert_charts(doc, period_dir, discipline, table_idx, slots, chart_dir):
    """向指定槽位表插入 6 图（保持图题，图追加到单元格）。"""
    tbl = doc.tables[table_idx]
    slug = charts._slug(discipline)
    for (ri, ci), fname in CHART_SLOTS.items():
        png = pathlib.Path(chart_dir) / slug / fname
        if not png.exists():
            continue
        cell = tbl.rows[ri].cells[ci]
        p = cell.add_paragraph()
        p.add_run().add_picture(str(png), width=Cm(8.26))
        slots.append({"location": f"T{table_idx:02d}/r{ri}c{ci}",
                      "old": "（空槽位）", "new": f"[图] {slug}/{fname}",
                      "source": f"charts/{slug}/{fname}"})


def fill_header_month(doc, period_dir, slots):
    """大表表头已处理；此处预留给封面/目录期数槽位（W3）。"""
    return


def main(ledger_dir="out/202607", master=r"master\学科信息参考母版_2026第5期.docx",
         out_path=None, charts_only_demo=True):
    ledger_dir = pathlib.Path(ledger_dir)
    P = json.loads((ledger_dir / "meta.json").read_text(encoding="utf-8"))["period_current"]
    out_path = pathlib.Path(out_path or ledger_dir / f"报告初稿_{P}（试排）.docx")

    wide, ni, nc, thr = compute.load_wide(str(ledger_dir))
    period, prev = compute.detect_periods(wide)
    prev_month = str(int(prev[4:]))
    t2 = compute.build_table2(wide, ni, nc, thr, period, prev)

    shutil.copy(master, out_path)
    doc = Document(str(out_path))
    slots = []

    fill_big_table(doc, t2, slots, prev_month)
    charts_used = ["Chemistry"] if charts_only_demo else DETAIL_TABLES
    chart_dir = ledger_dir / "charts"
    for disc in charts_used:
        idx = 3 + DETAIL_TABLES.index(disc)
        insert_charts(doc, ledger_dir, disc, idx, slots, chart_dir)

    doc.save(out_path)

    (ledger_dir / "red_slots.json").write_text(
        json.dumps(slots, ensure_ascii=False, indent=1), encoding="utf-8")

    n_img = sum(1 for s in slots if s["new"].startswith("[图]"))
    md = [f"# 红色件清单 · {P} 期（试排）", "",
          f"- 报告初稿：`{out_path}`",
          f"- 大表数值格：{sum(1 for s in slots if s['location'].startswith('T01/r'))} 格（逐格见 red_slots.json）",
          f"- 表头期次槽位：{sum(1 for s in slots if s['location'] == 'T01/表头')} 处",
          f"- 图表槽位：{n_img} 张（本期先行 {len(charts_used)} 学科的 {len(CHART_SLOTS)} 图，其余学科同机制批量）", "",
          "## 待生成（下一批）",
          "- 概述与各段结语句（句骨架+数字槽，W3）",
          "- 封面/目录 期数、日期、页码（W3）",
          "- 其余 15 学科图表槽位批量替换（验收图表样式后）",
          "- 省表各校数据、顶尖论文清单（台账外，人工贴入）", "",
          "## 说明", "签单核对方法：打开报告初稿，对照 red_slots.json 逐条核对“改了啥、来自哪”。"]
    (ledger_dir / "红色件清单.md").write_text("\n".join(md), encoding="utf-8")
    print(f"报告初稿 → {out_path}")
    print(f"红色件：{len(slots)} 条（大表 {sum(1 for s in slots if s['location'].startswith('T01/r'))} 格 + 图 {n_img} 张）")
    return out_path


if __name__ == "__main__":
    main()
