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
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pandas as pd  # noqa: E402
from docx import Document  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

import charts  # noqa: E402
import compute  # noqa: E402
import sentences  # noqa: E402
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


def _replace_para(p, new_text):
    """保留首 run 格式，替换整段文本（删除其余 run）。"""
    runs = p.runs
    if runs:
        runs[0].text = new_text
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
    else:
        p.add_run(new_text)


def fill_texts(doc, ledger_dir, slots, period, prev, facts):
    """概述 4 段 + 发展趋势段 + 态势段 + 封面期数（句骨架 + 数字槽）。"""
    texts = sentences.build(facts, period, prev)
    anchors = [
        ("p1", lambda t: "ESI最新数据显示" in t),
        ("p2", lambda t: "与ESI前1‰接近度较高" in t),
        ("p3", lambda t: "国内排名继续呈现较大降幅" in t),
        ("p4", lambda t: "篇顶尖论文" in t and "较上期总数增加" in t),
        ("trend", lambda t: t.startswith("与上期数据相比")),
        ("situation_head", lambda t: "前1%学科继续保持" in t),
        ("situation", lambda t: "从国内排名上看" in t),
        ("table2_title", lambda t: "主要参数情况" in t),
        ("top_section", lambda t: "篇顶尖论文" in t and "排名前3位的学院" in t),
        ("forecast_p1", lambda t: "接近度达到" in t),
        ("forecast_p2", lambda t: "从预测情况看" in t),
        ("province_p", lambda t: "云南高校ESI前1%学科总数" in t),
    ]
    for key, pred in anchors:
        hit = False
        for p in doc.paragraphs:
            t = p.text.strip()
            if pred(t):
                _replace_para(p, texts[key])
                slots.append({"location": f"正文/{key}", "old": t[:50],
                              "new": texts[key][:50], "source": "sentences.py（句骨架+数字槽）"})
                hit = True
                break
        if not hit:
            slots.append({"location": f"正文/{key}", "old": "（未找到锚点段落）",
                          "new": texts[key][:50], "source": "sentences.py"})

    # 封面：期数 + 年月
    pat_issue = re.compile(r"\d{4}年第\d+期（总第\d+期）")
    pat_date = re.compile(r"\d{4}年\d{1,2}月")
    for p in doc.paragraphs:
        t = p.text.strip()
        if pat_issue.fullmatch(t):
            _replace_para(p, texts["cover_issue"])
            slots.append({"location": "封面/期数", "old": t, "new": texts["cover_issue"],
                          "source": "期次参数"})
        elif "发展规划处" in t and pat_date.search(t):
            hits = [r for r in p.runs if pat_date.search(r.text)]
            old = t
            if hits:
                hits[-1].text = pat_date.sub(texts["cover_month"], hits[-1].text)
            else:
                _replace_para(p, pat_date.sub(texts["cover_month"], t))
            slots.append({"location": "封面/年月", "old": pat_date.search(old).group(),
                          "new": texts["cover_month"], "source": "期次参数"})


def fill_header_month(doc, period_dir, slots):
    """大表表头已处理；此处预留给目录页码（需 Word 分页，人工）。"""
    return


def main(ledger_dir="out/202607", master=r"master\学科信息参考母版_2026第5期.docx",
         out_path=None, charts_only_demo=False, period_override=None):
    ledger_dir = pathlib.Path(ledger_dir)
    P = json.loads((ledger_dir / "meta.json").read_text(encoding="utf-8"))["period_current"]
    out_path = pathlib.Path(out_path or ledger_dir / f"报告初稿_{P}（试排）.docx")

    wide, ni, nc, thr = compute.load_wide(str(ledger_dir))
    if period_override:
        filled = [c for c in wide["total_cites"].columns if wide["total_cites"][c].notna().any()]
        period = period_override
        prev = [c for c in filled if c < period][-1]
    else:
        period, prev = compute.detect_periods(wide)
    prev_month = str(int(prev[4:]))
    t2 = compute.build_table2(wide, ni, nc, thr, period, prev)
    ynd = pd.read_parquet(f"{ledger_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = pd.read_parquet(f"{ledger_dir}/wide/top_total.parquet").set_index("period")["total"].to_dict()
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, period, prev)

    shutil.copy(master, out_path)
    doc = Document(str(out_path))
    slots = []

    fill_big_table(doc, t2, slots, prev_month)
    fill_texts(doc, ledger_dir, slots, period, prev, facts)
    charts_used = ["Chemistry"] if charts_only_demo else DETAIL_TABLES
    chart_dir = ledger_dir / "charts"
    for disc in charts_used:
        idx = 3 + DETAIL_TABLES.index(disc)
        insert_charts(doc, ledger_dir, disc, idx, slots, chart_dir)

    doc.save(out_path)

    (ledger_dir / "red_slots.json").write_text(
        json.dumps(slots, ensure_ascii=False, indent=1), encoding="utf-8")

    n_img = sum(1 for s in slots if s["new"].startswith("[图]"))
    n_text = sum(1 for s in slots if not s["location"].startswith("T01/r") and not s["new"].startswith("[图]"))
    md = [f"# 红色件清单 · {period} 期", "",
          f"- 报告初稿：`{out_path}`",
          f"- 大表数值格：{sum(1 for s in slots if s['location'].startswith('T01/r'))} 格（逐格见 red_slots.json）",
          f"- 文字/期次槽位：{n_text} 处（概述 4 段、发展趋势、态势统计、封面期数年月、大表表头）",
          f"- 图表槽位：{n_img} 张（{len(charts_used)} 学科 × 6 图）", "",
          "## 仍为手工的槽位（红色件中的【手工：…】）",
          "- ESI 发布日期、当期全球机构总数（台账外，1 分钟可查）",
          "- 去年同期升幅%；预测章的趋势描述/预计时间/发展力度评价（编辑判断）",
          "- 学科数/学院数、学院贡献度前三、学院发文前三（顶尖论文清单口径）",
          "- 云南高校总数/增减/新晋学科（省级对比，台账外）",
          "- 目录页码（需 Word 分页后人工填）",
          "- 省表其余高校数据、顶尖论文清单 275 行（台账外，人工贴入）", "",
          "## 说明", "签单核对方法：打开报告初稿，对照 red_slots.json 逐条核对“改了啥、来自哪”。"]
    (ledger_dir / "红色件清单.md").write_text("\n".join(md), encoding="utf-8")
    print(f"报告初稿 → {out_path}")
    print(f"红色件：{len(slots)} 条（大表 {sum(1 for s in slots if s['location'].startswith('T01/r'))} 格 + 文字 {n_text} + 图 {n_img}）")
    return out_path


if __name__ == "__main__":
    main()
