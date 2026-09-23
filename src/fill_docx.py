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
from docx.oxml import parse_xml  # noqa: E402
from docx.oxml.ns import nsdecls, qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402
from docx.table import Table  # noqa: E402

import charts  # noqa: E402
import college_stats  # noqa: E402
import compute  # noqa: E402
import sentences  # noqa: E402
from parse_ledger import DISCIPLINES_CN, norm_disc_cn  # noqa: E402

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


#: 省域对比表 T19 的列（除首列机构名）→ 与 `extract_province.py` 的键一致
PROVINCE_COLS = ("国内排名", "国际排名", "ESI前1%学科数", "发文量", "被引频次",
                 "篇均被引频次", "顶尖论文", "高被引论文", "热点论文")


#: 学科×高校矩阵 T20 的 11 列（简称）→ 与 extract_matrix.py 的键一致
MATRIX_COLS = ("云大", "昆工", "昆医", "师大", "农大", "大理大学", "财大",
               "西林", "民大", "中医药大学", "曲靖师范")


def fill_matrix(doc, ledger_dir, slots):
    """填学科×高校矩阵 T20（23 行 × 12 列：表头 + 22 学科 × 11 校）。

    数据来自 `src/extract_matrix.py` 落的 `out/<期次>/matrix.json`：
    `接近度 = InCites(该期快照) 被引 ÷ 该学科当期 ESI 1% 阈值`，
    `Y` = 该机构在 ESI 该学科的 1% 榜内。**必须用当期对应的历史快照** ——
    最新一期快照的数据会覆盖旧值（rick 2026-09-20 指出）。

    ⚠ 母版里 T20 有表头（学科/高校 + 11 校简称）与首列学科名，只有数据格是空的 →
      按**首列学科名**对行、按**表头简称**对列，不要按序号盲填。
    """
    p = pathlib.Path(ledger_dir) / "matrix.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    mat = data.get("matrix") or {}
    t20 = None
    for cand in doc.tables:
        try:
            head = [c.text.strip() for c in cand.rows[0].cells]
        except (IndexError, AttributeError):
            continue
        if "云大" in head and "昆工" in head:      # 按表头认表，别按形状
            t20 = cand
            break
    if t20 is None:
        return 0
    col_of = {c.text.strip(): i for i, c in enumerate(t20.rows[0].cells)}
    n = 0
    for ri, row in enumerate(t20.rows[1:], start=1):
        # 🔴 行名必须先归一：母版与历期原件把「植物与动物学」写作「植物**学**与动物学」，
        #    而 matrix.json 的键是台账规范名。不归一 → mat.get 查不到 → **整行 11 格留白**，
        #    且不报错（2026-09-20 逐格核验才发现）。
        cn = norm_disc_cn(row.cells[0].text.strip())
        rec = mat.get(cn)
        if not rec:
            continue
        for short in MATRIX_COLS:
            ci = col_of.get(short)
            if ci is None:
                continue
            item = rec.get(short) or {}
            text = str(item.get("v") or "")
            if not text:
                continue
            old = row.cells[ci].text.strip()
            if old != text:
                set_cell(row.cells[ci], text)
                slots.append({"location": f"T20/r{ri}c{short}", "old": old,
                              "new": text, "source": item.get("src") or "InCites 历史快照"})
            n += 1
    return n


def fill_province(doc, ledger_dir, slots):
    """填省域对比表 T19（13 行 × 10 列，**两级表头**：r0 大类 / r1 细分）。

    🔴 这份数据**不来自台账**：台账的《高校学科发展》是另一个口径，数值对不上
    （昆工发文量：机构总表 31045 / 台账 19259）。它来自 **ESI 原始包的机构总表**，
    由 `src/extract_province.py` 算好落在 `out/<期次>/province.json`（每格带 src，
    指回 ESI 文件名与行号）。实测 11 校 × 9 列 = 99/99 格与人工原件逐格一致。
    """
    p = pathlib.Path(ledger_dir) / "province.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    uni = data.get("universities") or {}
    t19 = next((t for t in doc.tables if (len(t.rows), len(t.columns)) == (13, 10)), None)
    if t19 is None:
        return 0
    n = 0
    # ⚠ 母版里 T19 **整表是空的**（连机构名都没有），所以不能按首列已有名字去查 ——
    #   按 province.json 的顺序逐行填，机构名一并写进去。
    for i, (cn, rec) in enumerate(uni.items(), start=2):
        if i >= len(t19.rows):
            break
        row = t19.rows[i]
        if not row.cells[0].text.strip():
            set_cell(row.cells[0], cn)
            slots.append({"location": f"T19/r{i}c0", "old": "", "new": cn,
                          "source": "extract_province（11 校名单来自人工原件）"})
        for j, col in enumerate(PROVINCE_COLS, start=1):
            item = rec.get(col) or {}
            v = item.get("v")
            if v is None:
                continue
            text = f"{v:.2f}" if col == "篇均被引频次" else str(v)
            old = row.cells[j].text.strip()
            if old != text:
                set_cell(row.cells[j], text)
                slots.append({"location": f"T19/r{i}c{j}", "old": old, "new": text,
                              "source": item.get("src") or "ESI 机构总表"})
            n += 1
    return n


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


def _apply_slot_geometry(tbl):
    """恢复第 4 期槽位表几何：列宽 8.64+8.64cm（图 8.26cm 恰好放得下）。"""
    grid = tbl._tbl.find(qn('w:tblGrid'))
    if grid is not None:
        for col in grid.findall(qn('w:gridCol'))[:2]:
            col.set(qn('w:w'), str(int(8.64 * 567)))
    for row in tbl.rows:
        for cell in row.cells[:2]:
            cell.width = Cm(8.64)


def insert_charts(doc, period_dir, discipline, table_idx, slots, chart_dir):
    """向指定槽位表插入 6 图：填入既有空段（保持 2 段结构，避免行高超限）。"""
    tbl = doc.tables[table_idx]
    _apply_slot_geometry(tbl)
    slug = charts._slug(discipline)
    for (ri, ci), fname in CHART_SLOTS.items():
        png = pathlib.Path(chart_dir) / slug / fname
        if not png.exists():
            continue
        cell = tbl.rows[ri].cells[ci]
        img_p = None
        for p in cell.paragraphs:  # 找最后一个空段（无文字无图）放图
            if not p.text.strip() and not p._element.findall('.//' + qn('w:drawing')):
                img_p = p
        if img_p is None:
            img_p = cell.add_paragraph()
        img_p.alignment = 1  # 居中
        img_p.add_run().add_picture(str(png), width=Cm(8.26))
        # 归一：只保留 图题（首个非空段）+ 本图段；清除骨架残留（空段/碎字），保 2 段结构防行高超限
        # 注意：cell.paragraphs 每次返回新包装对象，必须比较底层 XML 元素
        cap_el = next((p._element for p in cell.paragraphs if p.text.strip()), None)
        img_el = img_p._element
        for p in list(cell.paragraphs):
            el = p._element
            if el is img_el or el is cap_el:
                continue
            if p.text.strip():
                slots.append({"location": f"T{table_idx:02d}/r{ri}c{ci}",
                              "old": p.text.strip()[:24], "new": "（清除母版残留文本）",
                              "source": "母版清理"})
            el.getparent().remove(el)
        slots.append({"location": f"T{table_idx:02d}/r{ri}c{ci}",
                      "old": "（空槽位）", "new": f"[图] {slug}/{fname}",
                      "source": f"charts/{slug}/{fname}"})


def _text_slot(location, old, new, source):
    """正文槽位：old/new 存 50 字预览（红色件清单表用）；
    超长时另存 old_full/new_full，供演示站「对勘本」做完整正文对照。"""
    d = {"location": location, "old": old[:50], "new": new[:50], "source": source}
    if len(old) > 50:
        d["old_full"] = old
    if len(new) > 50:
        d["new_full"] = new
    return d


def _replace_para(p, new_text):
    """保留首 run 格式，替换整段文本（删除其余 run）。"""
    runs = p.runs
    if runs:
        runs[0].text = new_text
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
    else:
        p.add_run(new_text)


def _strip_images(p):
    """删除段落中的图片/图表 run（用于替换母版残留旧图）。"""
    n = 0
    for r in list(p.runs):
        el = r._element
        if el.findall('.//' + qn('w:drawing')) or el.findall('.//' + qn('w:pict')):
            el.getparent().remove(el)
            n += 1
    return n


def _strip_native_chart_runs(doc, title_keyword):
    """删掉内嵌原生图表 run（按 chart 部件标题匹配，如「我校主要学科近期发展趋势」）。"""
    import re as _re

    hits = 0
    for p in doc.paragraphs:
        for r in list(p.runs):
            for ch in r._element.findall('.//' + qn('c:chart')):
                rid = ch.get(qn('r:id'))
                if not rid or rid not in doc.part.rels:
                    continue
                part = doc.part.rels[rid].target_part
                try:
                    xml = part.blob.decode("utf-8", "ignore")
                except Exception:                               # noqa: BLE001
                    continue
                if title_keyword in "".join(_re.findall(r"<a:t>(.*?)</a:t>", xml)):
                    r._element.getparent().remove(r._element)
                    hits += 1
                    break
    return hits


def _insert_picture_after(doc, anchor_para, png, width_cm=13.9):
    """在锚点段后插入居中的图片段。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    new_p = doc.add_paragraph()
    anchor_para._p.addnext(new_p._p)
    new_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    new_p.add_run().add_picture(str(png), width=Cm(width_cm))
    return new_p


def fill_body_charts(doc, ledger_dir, slots):
    """正文概览图三张：我校排名（插入）、1%接近度（插入）、1‰潜力（替换旧图）。"""
    ov = pathlib.Path(ledger_dir) / "charts" / "_overview"
    plan = [
        ("前1%学科继续保持", ov / "1pct.png", "正文/1%接近度图（新）", 14.3),
    ]
    for anchor, png, label, w in plan:
        if not png.exists():
            slots.append({"location": label, "old": "（缺图）", "new": str(png), "source": "charts/_overview"})
            continue
        hit = None
        for p in doc.paragraphs:
            if p.text.strip().startswith(anchor) or anchor in p.text:
                hit = p
                break
        if hit is None:
            slots.append({"location": label, "old": "（未找到锚点段落）", "new": str(png), "source": "charts/_overview"})
            continue
        _insert_picture_after(doc, hit, png, w)
        slots.append({"location": label, "old": "（无图）", "new": f"[图] {png.name}",
                      "source": f"charts/_overview/{png.name}"})

    # 1‰ 潜力图：替换"我校ESI学科1‰潜力值："段的旧图
    for p in doc.paragraphs:
        if "我校ESI学科1‰潜力值" in p.text:
            stripped = _strip_images(p)
            png = ov / "1permille.png"
            if png.exists():
                p.add_run().add_picture(str(png), width=Cm(14.5))
                slots.append({"location": "正文/1‰潜力图", "old": f"（母版旧图 ×{stripped}）",
                              "new": f"[图] {png.name}", "source": f"charts/_overview/1permille.png"})
            break

    # —— 对标第4期 fmt（带数据表 / 顶尖论文分布）：新增/替换 ——
    plan2 = [
        ("我校ESI排名情况", ov / "rank_table.png", "正文/排名情况图（第4期格式·带数据表）", 13.9),
        ("下图显示的是近期我校主要学科", ov / "trend_table.png", "正文/发展趋势图（第4期格式·带数据表）", 14.5),
        ("顶尖论文学科分布（篇）", ov / "top_by_subject.png", "正文/顶尖论文·学科分布", 13.5),
        ("顶尖论文年代分布（篇）", ov / "top_by_year.png", "正文/顶尖论文·年代分布", 13.5),
    ]
    for anchor, png, label, w in plan2:
        if not png.exists():
            slots.append({"location": label, "old": "（缺图）", "new": str(png), "source": "charts/_overview"})
            continue
        hit = next((p for p in doc.paragraphs if anchor in p.text), None)
        if hit is None:
            slots.append({"location": label, "old": "（未找到锚点段落）", "new": str(png), "source": "charts/_overview"})
            continue
        stripped = _strip_images(hit)
        if png.name == "rank_table.png":
            # 图内已带「我校ESI排名情况」标题 → 清掉母版占位图题「（图）」，避免页面上出现两次；
            # 同时删掉「与上期数据相比」段尾部遗留的旧版排名图（ynd_rank.png 已停用）
            for r in list(hit.runs):
                r._element.getparent().remove(r._element)
        _insert_picture_after(doc, hit, png, w)
        slots.append({"location": label, "old": f"（替换旧图 ×{stripped}）", "new": f"[图] {png.name}",
                      "source": f"charts/_overview/{png.name}"})

    # —— 学院件（数据源＝馆员《<期次>论文清单》）：两张饼图 + 统计表 + 附录清单表 ——
    warn = []
    fill_college(doc, ledger_dir, slots, warn)
    # —— 预测章 4 张模型预测图：替换母版原生图表 ——
    fill_forecast_charts(doc, ledger_dir, slots, warn)

    # 母版残留：趋势图（旧数据原生图表）删掉，改由生成图替代；其余原生图表预警
    n_stale = _strip_native_chart_runs(doc, "我校主要学科近期发展趋势")
    if n_stale:
        slots.append({"location": "正文/趋势图（母版旧原生图表）", "old": f"×{n_stale}",
                      "new": "已删除，改用 trend_table.png", "source": "fill_docx._strip_native"})
    n_charts = 0
    for p in doc.paragraphs:
        n_charts += len(p._element.findall('.//' + qn('c:chart')))
    if n_charts:
        warn.append(f"母版残留原生图表 {n_charts} 张（预测章 4 张等），本期需人工替换/确认（映射清单见红色件清单）")
    return warn


def _cell_set_keepfont(cell, text):
    """写单元格但**保留原格式**（只动第一个 run 的文字；统计表/附录清单表用）。"""
    ps = cell.paragraphs
    p = ps[0]
    if p.runs:
        p.runs[0].text = text
        for r in p.runs[1:]:
            r._element.getparent().remove(r._element)
    else:
        p.add_run(text)
    for q in ps[1:]:
        q._element.getparent().remove(q._element)


def _find_top_list_table(doc):
    """定位附录《我校顶尖论文清单》表（7 列、第 2 列表头含 WOS）。"""
    for t in doc.tables:
        if len(t.columns) == 7 and "WOS" in t.rows[0].cells[1].text:
            return t
    return None


def _clone_stat_table3(doc, widths=(4676, 2809, 2809)):
    """从附录清单表克隆出 3 列统计表骨架（表头行 + 1 行数据模板），列宽单位 twips。"""
    import copy

    src = _find_top_list_table(doc)
    if src is None:
        return None
    tbl = copy.deepcopy(src._tbl)
    trs = tbl.findall(qn("w:tr"))
    for tr in trs[2:]:
        tbl.remove(tr)
    grid = tbl.find(qn("w:tblGrid"))
    for gc in grid.findall(qn("w:gridCol"))[3:]:
        grid.remove(gc)
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(w))
    tbl_pr = tbl.find(qn("w:tblPr"))
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = parse_xml(f'<w:tblW {nsdecls("w")}/>')
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), "5000")
    tbl_w.set(qn("w:type"), "pct")
    for tr in tbl.findall(qn("w:tr")):
        tcs = tr.findall(qn("w:tc"))
        for tc in tcs[3:]:
            tr.remove(tc)
        for tc, w in zip(tcs[:3], widths):
            tc_pr = tc.find(qn("w:tcPr"))
            if tc_pr is None:
                tc_pr = parse_xml(f'<w:tcPr {nsdecls("w")}/>')
                tc.insert(0, tc_pr)
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = parse_xml(f'<w:tcW {nsdecls("w")}/>')
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(w))
            tc_w.set(qn("w:type"), "dxa")
    return tbl


def fill_college(doc, ledger_dir, slots, warns):
    """学院件：两张贡献度饼图（替换母版旧图）+ 学院统计表（替换空占位）+ 附录清单表。"""
    ledger_dir = pathlib.Path(ledger_dir)
    m = re.search(r"(\d{6})", ledger_dir.name)
    period = m.group(1) if m else ""
    cs = college_stats.load(ledger_dir, period, save=True)
    if cs is None:
        warns.append("学院件：未找到《<期次>论文清单.xlsx》→ 两张饼图/统计表/附录清单表未填")
        return

    ov = ledger_dir / "charts" / "_overview"
    for cap_kw, png, label in (
            ("顶尖论文被引频次学院贡献度", ov / "college_cites.png", "正文/学院贡献度饼图（被引频次）"),
            ("顶尖论文发文量学院贡献度", ov / "college_papers.png", "正文/学院贡献度饼图（发文量）")):
        if not png.exists():
            slots.append({"location": label, "old": "（缺图）", "new": str(png),
                          "source": "charts/_overview"})
            continue
        tgt = None
        paras = doc.paragraphs
        for i, p in enumerate(paras):
            t = p.text.strip()
            # 必须整段就是标题：正文句里含「…被引频次学院贡献度…」会被误命中（p36 教训）
            if t == cap_kw or (t.startswith(cap_kw) and len(t) < 40):
                for q in paras[i + 1:i + 4]:
                    if q._element.findall(".//" + qn("a:blip")):
                        tgt = q
                        break
                break
        if tgt is None:
            slots.append({"location": label, "old": "（未找到母版旧图）", "new": str(png),
                          "source": "charts/_overview"})
            continue
        n = _strip_images(tgt)
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
        tgt.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tgt.add_run().add_picture(str(png), width=Cm(13.6))
        slots.append({"location": label, "old": f"（母版旧图 ×{n}）", "new": f"[图] {png.name}",
                      "source": f"charts/_overview/{png.name}"})

    # —— 学院统计表：替换「学院顶尖论文发文量与被引频次统计表」后方的空占位表 ——
    units = cs["units"]
    tbl = _clone_stat_table3(doc)
    if tbl is None:
        warns.append("学院统计表：母版缺 7 列附录清单表模板，无法克隆 3 列表")
    else:
        import copy

        tpl_tr = copy.deepcopy(tbl.findall(qn("w:tr"))[1])
        for _ in range(len(units)):              # 现成 1 行当首个学院行；合计行随之
            tbl.append(copy.deepcopy(tpl_tr))
        nt = Table(tbl, doc._body)
        _cell_set_keepfont(nt.cell(0, 0), "学院名称")
        _cell_set_keepfont(nt.cell(0, 1), "顶尖论文发文量（篇）")
        _cell_set_keepfont(nt.cell(0, 2), "被引频次")
        for i, u in enumerate(units, start=1):
            _cell_set_keepfont(nt.cell(i, 0), u["unit"])
            _cell_set_keepfont(nt.cell(i, 1), str(u["papers"]))
            _cell_set_keepfont(nt.cell(i, 2), str(u["cites"]))
        _cell_set_keepfont(nt.cell(len(units) + 1, 0), "合计")
        _cell_set_keepfont(nt.cell(len(units) + 1, 1), str(cs["n_papers"]))
        _cell_set_keepfont(nt.cell(len(units) + 1, 2), str(cs["n_cites"]))
        cap = next((p for p in doc.paragraphs
                    if "学院顶尖论文发文量与被引频次统计表" in p.text), None)
        old_desc = "（未找到标题段，未插入）"
        placed = False
        if cap is not None:
            sib = cap._element.getnext()
            for _ in range(4):
                if sib is None or sib.tag == qn("w:tbl"):
                    break
                sib = sib.getnext()
            if sib is not None and sib.tag == qn("w:tbl"):
                old_desc = "空占位表（1×2）"
                sib.addprevious(tbl)
                sib.getparent().remove(sib)
            else:
                old_desc = "（无占位表，插在标题后）"
                cap._element.addnext(tbl)
            placed = True
        slots.append({"location": "正文/学院顶尖论文发文量与被引频次统计表", "old": old_desc,
                      "new": f"{len(units)} 行学院 + 合计（{cs['n_papers']} 篇 / {cs['n_cites']} 次）",
                      "source": "college_stats.json（馆员论文清单）"})
        if not placed:
            warns.append("学院统计表：未找到标题段，表已构好但未插入")

    fill_top_list(doc, cs, slots, warns)


def _strip_chart_runs(p):
    """删掉段落里内嵌的原生图表 run（返回删掉的 run 数）。"""
    n = 0
    for r in list(p.runs):
        if r._element.findall(".//" + qn("c:chart")):
            r._element.getparent().remove(r._element)
            n += 1
    return n


def fill_forecast_charts(doc, ledger_dir, slots, warns):
    """预测章 4 张「模型预测图」：按位置把母版原生图表换成生成图。

    对位规则：母版图题按「学科1 被引频次 → 学科1 国内排名 → 学科2 被引 → 学科2 排名」
    出现；生成图 `forecast_{1|2}_{cites|rank}.png` 同序（见 report_forecast——
    母版图题里的学科写法与台账名有历史差异，**不能按名字匹配**）。
    """
    ledger_dir = pathlib.Path(ledger_dir)
    ov = ledger_dir / "charts" / "_overview"
    caps = [i for i, p in enumerate(doc.paragraphs)
            if p.text.strip().endswith("的模型预测图")]
    if len(caps) != 4:
        warns.append(f"预测图：母版里应有 4 条「…的模型预测图」图题，实际找到 {len(caps)} 条")
        return
    meta = {}
    mp = ledger_dir / "forecast_charts.json"
    if mp.exists():
        try:
            meta = {c["png"]: c for c in json.loads(mp.read_text(encoding="utf-8"))["charts"]}
        except Exception:                                      # noqa: BLE001
            meta = {}
    plan = [(1, "cites"), (1, "rank"), (2, "cites"), (2, "rank")]
    for cap_idx, (subj_i, kind) in zip(caps, plan):
        png = ov / f"forecast_{subj_i}_{kind}.png"
        label = ("预测章/预测图（学科%d·%s）"
                 % (subj_i, "被引频次与阈值" if kind == "cites" else "国内排名与机构数"))
        if not png.exists():
            slots.append({"location": label, "old": "（缺生成图）", "new": str(png),
                          "source": "report_forecast"})
            continue
        paras = doc.paragraphs
        tgt = paras[cap_idx]
        for q in paras[cap_idx + 1:cap_idx + 3]:
            if q._element.findall(".//" + qn("c:chart")):
                tgt = q
                break
        n = _strip_chart_runs(tgt)
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
        tgt.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tgt.add_run().add_picture(str(png), width=Cm(14.0))
        info = meta.get(png.name, {})
        new_desc = f"[图] {png.name}"
        if info.get("model"):
            new_desc += (f"（{info.get('subject', '')}·{info['model']}，"
                         f"预计过线 {info.get('first_crossing') or '区间内未过线'}）")
        slots.append({"location": label, "old": f"母版原生图表 ×{n}",
                      "new": new_desc, "source": "report_forecast（V1 推荐模型）"})


def fill_top_list(doc, college, slots, warns):
    """附录《我校顶尖论文清单》：按馆员清单逐行填入（行数随清单增减）。"""
    rows = (college or {}).get("rows") or []
    if not rows:
        warns.append("附录顶尖论文清单：无清单数据，未填（母版仍是上一期行）")
        return
    import copy

    t = _find_top_list_table(doc)
    if t is None:
        warns.append("附录顶尖论文清单：未找到 7 列清单表")
        return
    trs = t._tbl.findall(qn("w:tr"))
    n_data = len(trs) - 1
    if len(rows) > n_data:
        tpl = copy.deepcopy(trs[-1])
        for _ in range(len(rows) - n_data):
            t._tbl.append(copy.deepcopy(tpl))
    elif len(rows) < n_data:
        for tr in trs[1 + len(rows):]:
            t._tbl.remove(tr)
    for i, vals in enumerate(rows, start=1):
        for c, v in enumerate(vals):
            _cell_set_keepfont(t.rows[i].cells[c], v)
    slots.append({"location": "附录/我校顶尖论文清单", "old": f"{n_data} 行（母版遗留）",
                  "new": f"{len(rows)} 行（馆员清单逐行）",
                  "source": "college_stats.json rows"})


def apply_manual_inputs(texts, fills, key_prefix="正文/"):
    """把句骨架里的 `【手工：xxx】` 换成馆员在线填的值（2026-09-19 工作台闭环）。

    三个边界，改这里前先读：
    1. **只替换填过的**。没填的保留原样的 `【手工：…】` —— 报告上留着未完成的
       标记，比悄悄抹平成空白要好（人工一眼能看到还剩几处）。
    2. **键是 `位置::标记文字`**（如 `正文/p2::去年同期升幅%`），与工作台
       `workbench._todo_from_slot` 生成的 id 同一套。**不能用序号**：重跑流水线
       后 red_slots 行序会变，序号会错位到别的格子。
    3. **只改报告文本，不碰台账、不改数字**。填进来的值原样落进 docx，
       仍然过不了机器断言 —— 人工输入的可信度由「谁填的 + 什么时候填的」
       （manual_inputs.json 有留痕）承担，而不是由系统假装校验过。

    返回 `(新 texts, 用了 N 处)`。
    """
    if not fills:
        return texts, 0
    used = 0

    def repl(key):
        def f(m):
            nonlocal used
            v = fills.get(f"{key_prefix}{key}::{m.group(1).strip()}")
            if v is None or not str(v.get("value") or "").strip():
                return m.group(0)                   # 没填 → 原样保留标记
            used += 1
            return str(v["value"])
        return f

    out = {}
    for k, t in texts.items():
        out[k] = _HAND_RE.sub(repl(k), t) if isinstance(t, str) else t
    return out, used


_HAND_RE = re.compile(r"【手工：([^】]*)】")


def fill_texts(doc, ledger_dir, slots, period, prev, facts, fills=None):
    """概述 4 段 + 发展趋势段 + 态势段 + 封面期数（句骨架 + 数字槽）。"""
    college = college_stats.load(pathlib.Path(ledger_dir), period, save=True)
    texts = sentences.build(facts, period, prev, college=college)
    texts, n_filled = apply_manual_inputs(texts, fills)
    anchors = [
        ("p1", lambda t: "ESI最新数据显示" in t),
        ("p2", lambda t: "与ESI前1‰接近度较高" in t),
        ("p3", lambda t: "国内排名继续呈现较大降幅" in t),
        ("p4", lambda t: "篇顶尖论文" in t and "较上期总数增加" in t),
        ("trend", lambda t: t.startswith("与上期数据相比")),
        ("situation_head", lambda t: "前1%学科继续保持" in t),
        ("situation", lambda t: "从国内排名上看" in t),
        ("table2_title", lambda t: "主要参数情况" in t),
        ("top_section", lambda t: "篇顶尖论文" in t and "学科分别" in t),
        ("forecast_p1", lambda t: "接近度达到" in t),
        ("forecast_p2", lambda t: "从预测情况看" in t),
        ("province_p", lambda t: "云南高校ESI前1%学科总数" in t),
    ]
    used = set()
    for key, pred in anchors:
        hit = False
        for p in doc.paragraphs:
            if p._element in used:               # 防同一段被两个锚点先后命中
                continue
            t = p.text.strip()
            if pred(t):
                _replace_para(p, texts[key])
                used.add(p._element)
                slots.append(_text_slot(f"正文/{key}", t, texts[key],
                                        "sentences.py（句骨架+数字槽）"))
                hit = True
                break
        if not hit:
            slots.append(_text_slot(f"正文/{key}", "（未找到锚点段落）", texts[key], "sentences.py"))

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


def main(ledger_dir="out/202607", master="master/学科信息参考母版_2026第5期.docx",
         out_path=None, charts_only_demo=False, period_override=None,
         manual_inputs=None):
    """`manual_inputs` 为 None 时**不应用**任何人工填值（机器稿保持纯机器产出）。

    ⚠ 这条默认值是刻意的：`run_pipeline` / `agent/tools.run_docx` 都不传它，
    所以流水线产出的永远是带 `【手工：…】` 占位的机器稿，可复现、可断言。
    只有演示站的「重出报告」显式传入 `manual_inputs.json` —— 那份产物是
    「叠加了人工输入、待签发」的稿子，两者不能混为一谈。
    """
    ledger_dir = pathlib.Path(ledger_dir)

    wide, ni, nc, thr = compute.load_wide(str(ledger_dir))
    filled = [c for c in wide["total_cites"].columns if wide["total_cites"][c].notna().any()]

    # 期次三级优先：显式 override > **目录名**（out/202605_复现 → 202605）> 台账最新有效期的自动推断。
    # 目录名这一级不可省：复现历史期次时若不认目录名，大表/概述会被填成**台账当期**数据，
    # 产出「文件名是第 3 期、内容是第 4 期」的错稿（2026-09-18 回测发现）。
    # `period_override` 只在 rerun_history 传；`run_pipeline` / `agent/tools.run_docx` 都不传，
    # 那两处以前对复现目录会静默产错稿。charts._infer_end_period 早就有这级兜底，此处对齐。
    m = re.search(r"(\d{6})", ledger_dir.name)
    dir_period = m.group(1) if m else None
    if period_override:
        period = period_override
    elif dir_period and dir_period in filled:
        period = dir_period
    else:
        period, _ = compute.detect_periods(wide)
    prev = [c for c in filled if c < period][-1]

    out_path = pathlib.Path(out_path or ledger_dir / f"报告初稿_{period}（试排）.docx")
    prev_month = str(int(prev[4:]))
    t2 = compute.build_table2(wide, ni, nc, thr, period, prev)
    ynd = pd.read_parquet(f"{ledger_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = pd.read_parquet(f"{ledger_dir}/wide/top_total.parquet").set_index("period")["total"].to_dict()
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, period, prev)

    shutil.copy(master, out_path)
    doc = Document(str(out_path))
    slots = []

    fill_big_table(doc, t2, slots, prev_month)
    n_prov = fill_province(doc, ledger_dir, slots)
    if n_prov:
        print(f"      省域表 T19：填入 {n_prov} 格（数据源＝ESI 机构总表，见 province.json）")
    n_mat = fill_matrix(doc, ledger_dir, slots)
    if n_mat:
        print(f"      矩阵表 T20：填入 {n_mat} 格（数据源＝InCites 历史快照，见 matrix.json）")
    fill_texts(doc, ledger_dir, slots, period, prev, facts, fills=manual_inputs)
    warns = fill_body_charts(doc, ledger_dir, slots)
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
          f"- 图表槽位：{n_img} 张（{len(charts_used)} 学科 × 6 图 + 概览/学院/预测图）", "",
          "## 仍为手工的槽位（红色件中的【手工：…】）",
          "- ESI 发布日期、当期全球机构总数（台账外，1 分钟可查）",
          "- 去年同期升幅%；预测章的趋势描述/预计时间/发展力度评价（编辑判断）",
          "- 云南高校总数/增减/新晋学科（省级对比，台账外）",
          "- 目录页码（需 Word 分页后人工填）",
          "- 省表其余高校数据（台账外，人工贴入）", "",
          "## 预警（母版残留）"]
    if warns:
        md += [f"- {w}" for w in warns]
    else:
        md += ["- 无"]
    md += [
        "- 1‰接近度趋势图（「从国内排名上看」段原图）：需历史 1‰ 阈值列，台账现只存最近两期，暂无法重建；",
        "  建议《千分之一被引阈值》表按列追存历史后由流水线自动生成。", "",
        "## 说明", "签单核对方法：打开报告初稿，对照 red_slots.json 逐条核对“改了啥、来自哪”。"]
    (ledger_dir / "红色件清单.md").write_text("\n".join(md), encoding="utf-8")
    print(f"报告初稿 → {out_path}")
    print(f"红色件：{len(slots)} 条（大表 {sum(1 for s in slots if s['location'].startswith('T01/r'))} 格 + 文字 {n_text} + 图 {n_img}）")
    return out_path


if __name__ == "__main__":
    main()
