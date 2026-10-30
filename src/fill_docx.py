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

import atomic_io  # noqa: E402
import charts  # noqa: E402
import college_stats  # noqa: E402
import compute  # noqa: E402
import native_charts  # noqa: E402
import period as period_mod  # noqa: E402
import sentences  # noqa: E402
from parse_ledger import DISCIPLINES_CN, norm_disc_cn  # noqa: E402

CELL_FONT = "楷体"
CELL_SIZE = Pt(10)

#: 原生图表开关（环境变量）。**默认关＝走 PNG**（rick 2026-10-26 裁决：
#: 原生图表画不出堆叠柱的段内数值标签、数据表宽度不可控、观感不如 matplotlib 版）。
#: 要开原生图表：`set WENHENG_NATIVE_CHARTS=1`（可右键「编辑数据」，代价是上面三条）。
#: `charts/**/*.png` 无论开关如何都照旧生成 —— 它是网站/前端的唯一图源。
NATIVE_CHARTS_ENV = "WENHENG_NATIVE_CHARTS"
_NATIVE_ON = ("1", "true", "yes", "on")


def native_charts_enabled(explicit=None):
    """是否走原生图表路径。`explicit` 给了就以它为准（命令行/API 优先于环境变量）。"""
    if explicit is not None:
        return bool(explicit)
    import os  # noqa: PLC0415
    raw = os.environ.get(NATIVE_CHARTS_ENV)
    if raw is None:
        return False                     # 2026-10-26 起默认 PNG，见上方注释
    return raw.strip().lower() in _NATIVE_ON

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


def _save_docx(doc, tmp_path, out_path):
    """docx 成品落盘：`doc.save` 写进同目录 tmp → `os.replace` 换成正式名。

    `doc.save` 是二进制、自己写盘，用不了 `write_text_atomic`；但重试口径仍走
    `atomic_io.replace`（Windows 上报告常被 Word 打开着，`os.replace` 会 WinError 5/32）。
    失败时清掉 tmp，`out_path` 保持上一次的完整产物。
    """
    tmp_path = pathlib.Path(tmp_path)
    try:
        doc.save(str(tmp_path))
        atomic_io.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _missing(slots, location, msg, source):
    """缺数据 / 缺表时的**哨兵红件**：宁可红件清单里多一条，也不许静默留白。

    R2-3（2026-10-28）：这三处原先直接 `return 0`，表格整片空白、红件清单也不记，
    状态照旧 `completed` —— 「缺一步」被读成「这一步本来就没内容」。
    """
    slots.append({"location": location, "old": "", "new": f"[缺] {msg}", "source": source})
    print(f"[warn] {location}：{msg}（{source}）→ 已记入红件清单")


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
        _missing(slots, "T20/整表", "矩阵表未生成（缺 matrix.json）", "fill_matrix")
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _missing(slots, "T20/整表", "矩阵表读不出（matrix.json 损坏）", "fill_matrix")
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
        _missing(slots, "T20/整表", "母版里找不到矩阵表（表头含 云大/昆工）", "fill_matrix")
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
        _missing(slots, "T19/整表", "省域表未生成（缺 province.json）", "fill_province")
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _missing(slots, "T19/整表", "省域表读不出（province.json 损坏）", "fill_province")
        return 0
    uni = data.get("universities") or {}
    t19 = next((t for t in doc.tables if (len(t.rows), len(t.columns)) == (13, 10)), None)
    if t19 is None:
        _missing(slots, "T19/整表", "母版里找不到 13×10 的省域表", "fill_province")
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
    """恢复槽位表几何，并固定布局，避免保存时按母版总宽重新分配列宽。"""
    slot_width = int(8.64 * 567)
    grid = tbl._tbl.find(qn('w:tblGrid'))
    if grid is not None:
        for col in grid.findall(qn('w:gridCol'))[:2]:
            col.set(qn('w:w'), str(slot_width))
    for row in tbl.rows:
        for cell in row.cells[:2]:
            cell.width = Cm(8.64)

    # 网格和单元格总宽为 9796 twips；母版中的 tblW 仍是各表原始宽度，
    # 继续使用旧总宽会让 Word/WPS 在自动布局时改写网格列宽。
    table_width = tbl._tbl.tblPr.find(qn('w:tblW'))
    if table_width is None:
        raise ValueError("槽位表缺少 w:tblW，无法固定列宽")
    table_width.set(qn('w:w'), str(slot_width * 2))
    table_width.set(qn('w:type'), 'dxa')
    tbl.autofit = False


def _next_docpr_id(doc):
    """文档里 `wp:docPr/@id` 的下一个可用号（原生图表图形框要唯一 id，否则 Word 报损坏）。"""
    ids = [int(v) for v in re.findall(r'<wp:docPr[^>]*\bid="(\d+)"', doc.element.xml)]
    return max(ids, default=0) + 1


def insert_charts(doc, period_dir, discipline, slots, chart_dir, native=None):
    """向指定槽位表插入 6 图：填入既有空段（保持 2 段结构，避免行高超限）。

    🔴 **不能用 `doc.tables[idx]` 盲取**：学院统计表改成两张后，其后的表序号整体后移
    （2026-09-24 实测：6 张学科图被塞进「被引频次学院统计表」里）。改为按内容找——
    第 k 个「表头以『国内外排名百分位趋势』开头」的表 = `charts.DETAIL_TABLES[k]`；
    槽位标签用**实测序号**（对勘本/在线填按 T<序号> 回查 docx，必须与真实位置一致）。

    `native` 非空时走**原生图表**路径：`{(slug, fname): {"xml":…, "xlsx":…}}` 由
    `native_report_charts.slot_charts()` 一次算好传入（96 张图共用一份宽表，别逐张读盘）。
    """
    cands = [t for t in doc.tables if t.rows and t.rows[0].cells
             and t.rows[0].cells[0].text.strip().startswith("国内外排名百分位趋势")]
    k = charts.DETAIL_TABLES.index(discipline)
    if k >= len(cands):
        slots.append({"location": f"T?/{discipline}", "old": "（找不到槽位表）", "new": "跳过",
                      "source": "fill_docx.insert_charts"})
        return
    tbl = cands[k]
    # ⚠ `doc.tables` 每次返回新的包装对象 → 必须比较底层 XML 元素（不是 `in`/`.index`）
    table_idx = next(i for i, t in enumerate(doc.tables) if t._tbl is tbl._tbl)
    _apply_slot_geometry(tbl)
    slug = charts._slug(discipline)
    docpr = _next_docpr_id(doc) if native else 0
    for (ri, ci), fname in CHART_SLOTS.items():
        spec = (native or {}).get((slug, fname))
        png = pathlib.Path(chart_dir) / slug / fname
        if spec is None and not png.exists():
            continue
        cell = tbl.rows[ri].cells[ci]
        img_p = None
        for p in cell.paragraphs:  # 找最后一个空段（无文字无图）放图
            if not p.text.strip() and not p._element.findall('.//' + qn('w:drawing')):
                img_p = p
        if img_p is None:
            img_p = cell.add_paragraph()
        img_p.alignment = 1  # 居中
        if spec is not None:
            native_charts.insert_chart_in_paragraph(
                img_p, spec["xml"], doc, w_cm=8.26, h_cm=5.50, doc_pr_id=docpr,
                name=f"原生图表-{slug}-{fname}", xlsx_blob=spec.get("xlsx"))
            docpr += 1
        else:
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
                      "old": "（空槽位）",
                      "new": f"[图] {slug}/{fname}" + ("（原生图表）" if spec is not None else ""),
                      # 🔴 source 必须保持 `charts/...`：`agent/audit.manual_slot_checklist`
                      #    靠这个前缀把图槽排除在「待人工清点」之外（换前缀会让待清点虚高到 115）；
                      #    `test_chart_preview` 也靠它把槽位反查成可预览的 PNG。
                      #    原生图表模式下 PNG 照旧生成（网站的唯一图源），所以这个指针仍然有效。
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


def _blacken_red_runs(doc):
    """把正文/表格里的**纯红** #FF0000 文字改黑，返回改动的 run 数。

    母版用纯红标记「每期都要改数」的段落与图题（原件正文全黑）；`_replace_para` 只
    能覆盖走文字槽位的那部分，图题段、引导语段不在槽位里，必须整篇扫一遍
    （2026-10-26 rick 反馈「正文全是红字」）。只认纯红，其他颜色原样保留。
    """
    n = 0
    paras = list(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                paras.extend(cell.paragraphs)
    for p in paras:
        for r in p.runs:
            col = r.font.color
            if col is not None and col.rgb is not None and str(col.rgb).upper() == "FF0000":
                r.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
                n += 1
    return n


def _replace_para(p, new_text):
    """保留首 run 格式，替换整段文本（删除其余 run）。

    ⚠️ 母版有的段落首 run 是空跑/无字号，真格式在后面的 run 上（实测「本期云南大学
    22个ESI学科…」段：首 run 无字号、其后 run 均 15pt）——直接沿用首 run 会把整段
    掉到 Normal 10.5pt（rick 截图：这段字特别小）。首 run 无显式字号时，借同段
    首个带字号 run 的 rPr。
    """
    import copy

    runs = p.runs
    if runs:
        first = runs[0]
        if first.font.size is None:
            donor = next((r for r in runs[1:] if r.font.size is not None), None)
            donor_rpr = donor._element.find(qn("w:rPr")) if donor is not None else None
            if donor_rpr is not None:
                old = first._element.find(qn("w:rPr"))
                if old is not None:
                    first._element.remove(old)
                first._element.insert(0, copy.deepcopy(donor_rpr))
        first.text = new_text
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
        # 母版用纯红 #FF0000 标记「每期都要改数」的段落；填完值仍留红，整篇会像批注稿
        # （2026-10-26 rick 反馈「正文全是红字」）。只把**纯红**改黑，其他颜色原样保留。
        try:
            col = first.font.color
            if col is not None and col.rgb is not None and str(col.rgb).upper() == "FF0000":
                first.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
        except (AttributeError, ValueError):
            pass
    else:
        p.add_run(new_text)


#: 母版里的「图题占位」字样（图插进去后必须删，否则页面上会多一行「（图）」）
_PLACEHOLDER_CAPS = ("（图）", "(图)", "（更新图）", "(更新图)", "（缺图）", "(缺图)")


def _drop_placeholder_after(para, limit=3):
    """删掉紧跟在 `para` 之后的占位图题段落，返回被删掉的文字列表。

    母版在每个图槽位后面留了一段「（图）」/「（更新图）」当占位；图替换进去后这段
    就成了页面上孤零零的一行（2026-10-26 实测 p5「（图）」、p6「（更新图）」）。
    只往前扫 `limit` 段、只认 `_PLACEHOLDER_CAPS` 里的整段文字，避免误删正文。
    """
    from docx.text.paragraph import Paragraph                   # noqa: PLC0415

    dropped, blanks = [], 0
    nxt = para._element.getnext()
    while nxt is not None and nxt.tag == qn("w:p") and len(dropped) < limit and blanks <= 3:
        p = Paragraph(nxt, para._parent)
        txt = p.text.strip()
        if txt in _PLACEHOLDER_CAPS:
            dropped.append(txt)
            following = nxt.getnext()
            p._element.getparent().remove(p._element)
            nxt = following
            continue
        if not txt:                      # 空段：可能是刚被 strip 掉旧图的那一段，跨过去继续找
            blanks += 1
            nxt = nxt.getnext()
            continue
        break
    return dropped


def _strip_images(p):
    """删除段落中的图片/图表 run（用于替换母版残留旧图）。"""
    n = 0
    for r in list(p.runs):
        el = r._element
        if el.findall('.//' + qn('w:drawing')) or el.findall('.//' + qn('w:pict')):
            el.getparent().remove(el)
            n += 1
    return n


def _inline_to_anchor(inline, relative_height):
    """`wp:inline` → `wp:anchor`（上下型环绕、水平居中、垂直锚在本段）。

    **备选方案**：能解「图被遮挡」，但实测浮动图不随文字流走——页底放不下时图会被
    顶到下一页、在原页留下半页空白（预测章实测：每张图一页）。因此当前改用
    `relax_image_line_spacing`（内嵌图 + 放宽固定行距）。此函数留作 rick 若坚持
    上下型环绕时的现成实现；子元素必须按 CT_Anchor 的 schema 顺序搬：
    extent → effectExtent → wrap → docPr → cNvGraphicFramePr → graphic（错了 Word 报文档损坏）。
    """
    xmlns = nsdecls("wp", "a")
    anchor = parse_xml(
        f'<wp:anchor {xmlns} distT="0" distB="0" distL="114300" distR="114300" simplePos="0"'
        f' relativeHeight="{relative_height}" behindDoc="0" locked="0" layoutInCell="1"'
        ' allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="column"><wp:align>center</wp:align></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>299720</wp:posOffset></wp:positionV>'
        "</wp:anchor>")
    for tag in ("wp:extent", "wp:effectExtent"):
        el = inline.find(qn(tag))
        if el is not None:
            anchor.append(el)
    anchor.append(parse_xml(f'<wp:wrapTopAndBottom {xmlns}/>'))
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        el = inline.find(qn(tag))
        if el is not None:
            anchor.append(el)
    inline.getparent().replace(inline, anchor)


def _relax_exact_spacing(p):
    """把「固定行距」（lineRule=exact/atLeast）改成单倍行距——返回是否改动。"""
    pPr = p.find(qn("w:pPr"))
    if pPr is None:
        return False
    sp = pPr.find(qn("w:spacing"))
    if sp is None:
        return False
    if sp.get(qn("w:lineRule")) in ("exact", "atLeast"):
        sp.set(qn("w:lineRule"), "auto")
        sp.set(qn("w:line"), "240")
        return True
    return False


def relax_image_line_spacing(doc):
    """正文（不含表格/页眉页脚）里带图的段落：放宽「固定行距」，让图不再被遮挡。

    🔴 根因（rick 2026-09-23「你插入的图片有时候被遮挡」）：母版有图段行距是
    `w:lineRule="exact"`（预测章 20pt）——内嵌图不参与行高，图会压住上下文字。
    两种修法实测对比（Word 导出 PDF 逐页核对）：
      · 上下型环绕浮动图 → 图不参与文字流，页底放不下就被顶到下一页，
        原页留半页空白（预测章一度变成 4 页、每页一张图）；
      · 放宽为单倍行距（本实现）→ 图仍随文流走，行高按图撑开，不压字也不丢页。
    返回改动的段落数。
    ⚠ 表格槽位里的 96 张学科图**不动**：单元格行高本来靠内嵌图撑开。
    """
    n = 0
    for p in doc.paragraphs:
        if p._p.findall(".//" + qn("wp:inline")) and _relax_exact_spacing(p._p):
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


def _tie_title_to_figure(para, max_len=40):
    """短标题段加 `keepNext`，避免「标题在页底、图翻到下一页」。

    只对短段生效（≤40 字）：plan2 的四个锚点里「下图显示的是近期我校主要学科…」
    是一整句引导语，给它绑图会把整段推到下页，所以按长度筛。
    """
    try:
        if len(para.text.strip()) <= max_len:
            para.paragraph_format.keep_with_next = True
    except (AttributeError, ValueError):
        pass


def _insert_picture_after(doc, anchor_para, png, width_cm=13.9):
    """在锚点段后插入居中的图片段（顺带清掉紧随其后的母版占位图题）。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    _drop_placeholder_after(anchor_para)
    _tie_title_to_figure(anchor_para)
    new_p = doc.add_paragraph()
    anchor_para._p.addnext(new_p._p)
    new_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    new_p.add_run().add_picture(str(png), width=Cm(width_cm))
    return new_p


def _insert_chart_after(doc, anchor_para, spec, docpr, name):
    """在锚点段后插入居中的**原生图表**段（`spec` 来自 `native_report_charts.body_charts`）。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    _drop_placeholder_after(anchor_para)
    _tie_title_to_figure(anchor_para)
    new_p = doc.add_paragraph()
    anchor_para._p.addnext(new_p._p)
    new_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    native_charts.insert_chart_in_paragraph(
        new_p, spec["xml"], doc, w_cm=spec["w_cm"], h_cm=spec["h_cm"],
        doc_pr_id=_next_docpr_id(doc), name=name, xlsx_blob=spec.get("xlsx"))
    return new_p


def fill_body_charts(doc, ledger_dir, slots, native=None):
    """正文概览图三张：我校排名（插入）、1%接近度（插入）、1‰潜力（替换旧图）。

    `native` 非空时优先用**原生图表**（`native_report_charts.body_charts` 的规格），
    该键缺失就回落 PNG —— 单张失败不会让整份报告缺图。
    """
    native = native or {}
    ov = pathlib.Path(ledger_dir) / "charts" / "_overview"
    plan = [
        ("前1%学科继续保持", ov / "1pct.png", "正文/1%接近度图（新）", 14.3, "1pct"),
    ]
    for anchor, png, label, w, key in plan:
        spec = native.get(key)
        if spec is None and not png.exists():
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
        if spec is not None:
            _insert_chart_after(doc, hit, spec, 0, f"原生图表-{key}")
            slots.append({"location": label, "old": "（无图）", "new": f"[图] {png.name}（原生图表）",
                          "source": f"charts/_overview/{png.name}"})
            continue
        _insert_picture_after(doc, hit, png, w)
        slots.append({"location": label, "old": "（无图）", "new": f"[图] {png.name}",
                      "source": f"charts/_overview/{png.name}"})

    # 1‰ 潜力图：清掉"我校ESI学科1‰潜力值："段的旧图/旧原生图表，**另起一段**插新图
    # （图挤在文字段里，Word 里会和相邻内容叠成一片——rick 截图的「两个表格重叠」）
    for p in doc.paragraphs:
        if "我校ESI学科1‰潜力值" in p.text:
            stripped = _strip_images(p) + _strip_chart_runs(p)
            png = ov / "1permille.png"
            spec = native.get("1permille")
            if spec is not None:
                _insert_chart_after(doc, p, spec, 0, "原生图表-1permille")
                slots.append({"location": "正文/1‰潜力图", "old": f"（母版旧图 ×{stripped}）",
                              "new": "[图] 1permille.png（原生图表）",
                              "source": "charts/_overview/1permille.png"})
            elif png.exists():
                _insert_picture_after(doc, p, png, 14.5)
                slots.append({"location": "正文/1‰潜力图", "old": f"（母版旧图 ×{stripped}）",
                              "new": f"[图] {png.name}", "source": f"charts/_overview/1permille.png"})
            break

    # —— 对标第4期 fmt（带数据表 / 顶尖论文分布）：新增/替换 ——
    plan2 = [
        ("我校ESI排名情况", ov / "rank_table.png", "正文/排名情况图（第4期格式·带数据表）", 13.9, "rank_table"),
        ("下图显示的是近期我校主要学科", ov / "trend_table.png", "正文/发展趋势图（第4期格式·带数据表）", 14.5, "trend_table"),
        ("顶尖论文学科分布（篇）", ov / "top_by_subject.png", "正文/顶尖论文·学科分布", 13.5, "top_by_subject"),
        ("顶尖论文年代分布（篇）", ov / "top_by_year.png", "正文/顶尖论文·年代分布", 13.5, "top_by_year"),
    ]
    for anchor, png, label, w, key in plan2:
        spec = native.get(key)
        if spec is None and not png.exists():
            slots.append({"location": label, "old": "（缺图）", "new": str(png), "source": "charts/_overview"})
            continue
        hit = next((p for p in doc.paragraphs if anchor in p.text), None)
        if hit is None:
            slots.append({"location": label, "old": "（未找到锚点段落）", "new": str(png), "source": "charts/_overview"})
            continue
        stripped = _strip_images(hit)
        dropped = _drop_placeholder_after(hit)
        if dropped:
            slots.append({"location": label + "/占位图题", "old": "、".join(dropped),
                          "new": "已删除（母版占位字）",
                          "source": "fill_docx._drop_placeholder_after"})
        if png.name == "rank_table.png":
            # 图内已带「我校ESI排名情况」标题 → 清掉母版占位图题「（图）」，避免页面上出现两次；
            # 同时删掉「与上期数据相比」段尾部遗留的旧版排名图（ynd_rank.png 已停用）
            for r in list(hit.runs):
                r._element.getparent().remove(r._element)
        if spec is not None:
            _insert_chart_after(doc, hit, spec, 0, f"原生图表-{key}")
            slots.append({"location": label, "old": f"（替换旧图 ×{stripped}）",
                          "new": f"[图] {png.name}（原生图表）",
                          "source": f"charts/_overview/{png.name}"})
            continue
        _insert_picture_after(doc, hit, png, w)
        slots.append({"location": label, "old": f"（替换旧图 ×{stripped}）", "new": f"[图] {png.name}",
                      "source": f"charts/_overview/{png.name}"})

    # —— 学院件（数据源＝馆员《<期次>论文清单》）：两张饼图 + 统计表 + 附录清单表 ——
    warn = []
    fill_college(doc, ledger_dir, slots, warn, native=native)
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


def _tbl_pr_set(tbl, el, *succ):
    """在 `w:tblPr` 里按 OOXML 的 schema 顺序放入/替换一个子元素（顺序错 Word 报文档损坏）。"""
    tbl_pr = tbl.find(qn("w:tblPr"))
    for old in tbl_pr.findall(el.tag):
        tbl_pr.remove(old)
    tbl_pr.insert_element_before(el, *succ)


#: 学院统计表（左右并排两个子表）：列宽 twips ≈ 名称 5.0cm + 值 2.0cm，中间 0.6cm 空列当间隔；
#: 行高 0.40cm；微软雅黑 9pt
_COLLEGE_W = (2835, 1134)
_COLLEGE_GAP = 340
_COLLEGE_FONT = "微软雅黑"
_COLLEGE_HEAD_FILL = "F3F4F6"
_COLLEGE_TOTAL_FILL = "F9FAFB"
_COLLEGE_RULE = "E5E7EB"


def _college_cell(cell, text, *, align="left", size=9, bold=False, fill=None, color="1F2937"):
    """一格：微软雅黑（中西文都设）+ 对齐 + 可选底纹 + 垂直居中。"""
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    p = cell.paragraphs[0]
    for r in list(p.runs):
        r._element.getparent().remove(r._element)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if align == "right" else WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(10)      # 固定行高：两张表（各 25 行）才排得进一页
    run = p.add_run(str(text))
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    rpr.insert(0, parse_xml(
        f'<w:rFonts {nsdecls("w")} w:ascii="{_COLLEGE_FONT}" w:hAnsi="{_COLLEGE_FONT}"'
        f' w:eastAsia="{_COLLEGE_FONT}"/>'))
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if fill:
        cell._tc.get_or_add_tcPr().append(
            parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{fill}"/>'))
    return cell


def _college_block(doc, head1, rows1, head2, rows2):
    """学院统计表：**左右两个子表并排**（论文量降序 / 被引频次降序，rick 2026-09-25 定）。

    🔴 为什么不是两个 `w:tbl`：加一张表会让其后所有表的序号整体后移——
    `insert_charts`（学科 96 张图）、`verify_report_docx`（tables[3..18]）、
    T19/T20 的位置码（工作台翻译、逐格回验）全靠序号，实测踩过：6 张学科图被塞进
    「被引频次学院统计表」。Word 里两张独立表也没法并排（只能上下），所以用**一个表、
    五列**：名称 | 值 | 空列（当间隔） | 名称 | 值 —— 视觉上就是左右两张表，序号一个不动。
    美化：只留横向细线（无竖线/外框）；表头浅底纹 + 深一档下边线；总计行浅底纹加粗。
    """
    if len(rows1) != len(rows2):
        raise ValueError("左右两半行数必须一致（都是 学院数 + 总计）")
    n_rows = 1 + len(rows1)
    nt = doc.add_table(rows=n_rows, cols=5)
    tbl = nt._tbl
    widths = (_COLLEGE_W[0], _COLLEGE_W[1], _COLLEGE_GAP, _COLLEGE_W[0], _COLLEGE_W[1])
    _tbl_pr_set(tbl, parse_xml(
        f'<w:tblW {nsdecls("w")} w:w="{sum(widths)}" w:type="dxa"/>'),
        "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
        "w:tblCellMar", "w:tblLook")
    _tbl_pr_set(tbl, parse_xml(f'<w:jc {nsdecls("w")} w:val="center"/>'),
                "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
                "w:tblCellMar", "w:tblLook")
    _tbl_pr_set(tbl, parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{_COLLEGE_RULE}"/>'
        f'<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{_COLLEGE_RULE}"/>'
        f'<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f"</w:tblBorders>"), "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook")
    # 🔴 固定列宽（tblLayout=fixed）：不加的话 Word 自动适配会压缩名称列，
    # 「云南生物资源国家重点实验室」这类长名会折成两行（实测）。
    _tbl_pr_set(tbl, parse_xml(f'<w:tblLayout {nsdecls("w")} w:type="fixed"/>'),
                "w:tblCellMar", "w:tblLook")
    _tbl_pr_set(tbl, parse_xml(
        f'<w:tblCellMar {nsdecls("w")}>'
        f'<w:top w:w="10" w:type="dxa"/><w:left w:w="72" w:type="dxa"/>'
        f'<w:bottom w:w="10" w:type="dxa"/><w:right w:w="72" w:type="dxa"/>'
        f"</w:tblCellMar>"), "w:tblLook")
    grid = tbl.find(qn("w:tblGrid"))
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(w))
    for tr in tbl.findall(qn("w:tr")):
        for tc, w in zip(tr.findall(qn("w:tc")), widths):
            tc_pr = tc.find(qn("w:tcPr"))
            if tc_pr is None:
                tc_pr = parse_xml(f'<w:tcPr {nsdecls("w")}/>')
                tc.insert(0, tc_pr)
            old = tc_pr.find(qn("w:tcW"))
            if old is not None:
                tc_pr.remove(old)
            tc_pr.append(parse_xml(
                f'<w:tcW {nsdecls("w")} w:w="{w}" w:type="dxa"/>'))
        tr.get_or_add_trPr().append(parse_xml(
            f'<w:trHeight {nsdecls("w")} w:val="200" w:hRule="atLeast"/>'))
    # 表头：左右各一组（名称 | 值），中间空列
    _college_cell(nt.cell(0, 0), "学院名称", fill=_COLLEGE_HEAD_FILL, color="374151")
    _college_cell(nt.cell(0, 1), head1, align="right", fill=_COLLEGE_HEAD_FILL,
                  color="374151")
    _college_cell(nt.cell(0, 3), "学院名称", fill=_COLLEGE_HEAD_FILL, color="374151")
    _college_cell(nt.cell(0, 4), head2, align="right", fill=_COLLEGE_HEAD_FILL,
                  color="374151")
    for ci in (0, 1, 3, 4):
        _college_rule(nt.cell(0, ci), "D1D5DB")
    # 数据行：左半第 i 行 + 右半第 i 行
    for i, ((n1, v1, t1), (n2, v2, t2)) in enumerate(zip(rows1, rows2), start=1):
        f1 = _COLLEGE_TOTAL_FILL if t1 else None
        f2 = _COLLEGE_TOTAL_FILL if t2 else None
        _college_cell(nt.cell(i, 0), n1, fill=f1, bold=t1)
        _college_cell(nt.cell(i, 1), v1, align="right", fill=f1, bold=t1)
        _college_cell(nt.cell(i, 3), n2, fill=f2, bold=t2)
        _college_cell(nt.cell(i, 4), v2, align="right", fill=f2, bold=t2)
    return tbl


def _college_rule(cell, color):
    """给一格加/去下边线（color=None → 四边全无，用于子表之间的间隔行）。"""
    tc_pr = cell._tc.get_or_add_tcPr()
    if color is None:
        tc_pr.append(parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            f'<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            f"</w:tcBorders>"))
    else:
        tc_pr.append(parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="{color}"/>'
            f"</w:tcBorders>"))


def fill_college(doc, ledger_dir, slots, warns, native=None):
    """学院件：两张贡献度饼图（替换母版旧图）+ 学院统计表（替换空占位）+ 附录清单表。

    `native` 里有 `college_cites` / `college_papers` 规格时用**原生饼图/环形图**。
    """
    ledger_dir = pathlib.Path(ledger_dir)
    m = re.search(r"(\d{6})", ledger_dir.name)
    period = m.group(1) if m else ""
    cs = college_stats.load(ledger_dir, period, save=True)
    if cs is None:
        warns.append("学院件：未找到《<期次>论文清单.xlsx》→ 两张饼图/统计表/附录清单表未填")
        return

    ov = ledger_dir / "charts" / "_overview"
    native = native or {}
    for cap_kw, png, label, key in (
            ("顶尖论文被引频次学院贡献度", ov / "college_cites.png", "正文/学院贡献度饼图（被引频次）",
             "college_cites"),
            ("顶尖论文发文量学院贡献度", ov / "college_papers.png", "正文/学院贡献度饼图（发文量）",
             "college_papers")):
        spec = native.get(key)
        if spec is None and not png.exists():
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
                    if q._element.findall(".//" + qn("a:blip")) \
                            or q._element.findall(".//" + qn("c:chart")):
                        tgt = q
                        break
                break
        if tgt is None:
            slots.append({"location": label, "old": "（未找到母版旧图）", "new": str(png),
                          "source": "charts/_overview"})
            continue
        n = _strip_images(tgt) + _strip_chart_runs(tgt)
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
        tgt.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if spec is not None:
            native_charts.insert_chart_in_paragraph(
                tgt, spec["xml"], doc, w_cm=spec["w_cm"], h_cm=spec["h_cm"],
                doc_pr_id=_next_docpr_id(doc), name=f"原生图表-{key}",
                xlsx_blob=spec.get("xlsx"))
            slots.append({"location": label, "old": f"（母版旧图 ×{n}）",
                          "new": f"[图] {png.name}（原生图表）",
                          "source": f"charts/_overview/{png.name}"})
        else:
            tgt.add_run().add_picture(str(png), width=Cm(13.6))
            slots.append({"location": label, "old": f"（母版旧图 ×{n}）", "new": f"[图] {png.name}",
                          "source": f"charts/_overview/{png.name}"})

    # —— 学院统计表：**两张**（论文量降序 / 被引频次降序，对照出版件第 7 页），
    #    替换「学院顶尖论文发文量与被引频次统计表」后方的空占位表 ——
    units = cs["units"]
    rows_p = [(u["unit"], str(u["papers"]), False) for u in units]
    rows_p.sort(key=lambda x: (-int(x[1]), x[0]))
    rows_p.append(("总计", str(cs["n_papers"]), True))
    rows_c = sorted(((u["unit"], str(u["cites"]), False) for u in units),
                    key=lambda x: (-int(x[1]), x[0]))
    rows_c.append(("总计", str(cs["n_cites"]), True))
    tbl_p = _college_block(doc, "论文量（篇）", rows_p, "被引频次", rows_c)
    cap = next((p for p in doc.paragraphs
                if "学院顶尖论文发文量与被引频次统计表" in p.text), None)
    old_desc = "（未找到标题段，未插入）"
    placed = False
    if cap is not None:
        from docx.text.paragraph import Paragraph                  # noqa: PLC0415
        sib = cap._element.getnext()
        skipped = []
        for _ in range(4):
            if sib is None or sib.tag == qn("w:tbl"):
                break
            skipped.append(sib)
            sib = sib.getnext()
        if sib is not None and sib.tag == qn("w:tbl"):
            old_desc = "空占位表（1×2）+ 旧 1 张 3 列表"
            sib.addprevious(tbl_p)              # 换掉占位表（表数不变 → 后续序号不漂）
            sib.getparent().remove(sib)
            for sp in skipped:                  # 顺手清掉标题与表之间的空段（两张子表才排得进一页）
                if not Paragraph(sp, doc._body).text.strip():
                    sp.getparent().remove(sp)
        else:
            old_desc = "（无占位表，插在标题后）"
            cap._element.addnext(tbl_p)
        placed = True
    slots.append({"location": "正文/学院顶尖论文发文量与被引频次统计表", "old": old_desc,
                  "new": f"两个子表（论文量降序 / 被引频次降序，各 {len(units)} 行学院 + 总计；"
                         f"{cs['n_papers']} 篇 / {cs['n_cites']} 次）",
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
    # 图题学科名随**实际出图学科**改写（2026-10-16，改选学科优先后母版旧名不再可靠）：
    by_index = {}
    for info in meta.values():
        idx, subject = info.get("index"), info.get("subject")
        if isinstance(idx, int) and isinstance(subject, str) and idx not in by_index:
            by_index[idx] = subject
    # 章首导语的学科名（母版静态句）：随报告目标学科改写（2026-10-16，改选学科优先后）。
    # 原文：本期针对我校的{学科1}和{学科2}2个学科，我们利用指数平滑模型，…
    subs = [by_index.get(1), by_index.get(2)]
    if all(isinstance(s, str) and s for s in subs):
        lead_new = (f"本期针对我校的{subs[0]}和{subs[1]}2个学科，我们利用指数平滑模型，"
                    "从被引频次和国内排名两个指标对其进行预测分析，提供以下参考信息：")
        for p in doc.paragraphs:
            t = p.text.strip()
            if "本期针对我校的" in t and "2个学科" in t:
                if t != lead_new:
                    _replace_para(p, lead_new)
                    slots.append(_text_slot(
                        "预测章/导语（目标学科）", t, lead_new,
                        "report_forecast（改选学科优先，导语随实际学科）"))
                break
    plan = [(1, "cites"), (1, "rank"), (2, "cites"), (2, "rank")]
    for cap_idx, (subj_i, kind) in zip(caps, plan):
        png = ov / f"forecast_{subj_i}_{kind}.png"
        label = ("预测章/预测图（学科%d·%s）"
                 % (subj_i, "被引频次与阈值" if kind == "cites" else "国内排名与机构数"))
        if not png.exists():
            slots.append({"location": label, "old": "（缺生成图）", "new": str(png),
                          "source": "report_forecast"})
            continue
        subject = by_index.get(subj_i)
        if subject:
            new_cap = (f"{subject}学科被引频次与ESI阈值的模型预测图" if kind == "cites"
                       else f"{subject}学科国内排名与学科国内ESI前1%机构数的模型预测图")
            cap_p = doc.paragraphs[cap_idx]
            old_cap = cap_p.text.strip()
            if old_cap != new_cap:
                _replace_para(cap_p, new_cap)
                slots.append(_text_slot(
                    label + "题", old_cap, new_cap,
                    "report_forecast（改选学科优先，图题随实际学科）"))
        paras = doc.paragraphs
        tgt = paras[cap_idx]
        for q in paras[cap_idx + 1:cap_idx + 3]:
            if q._element.findall(".//" + qn("c:chart")):
                tgt = q
                break
        n = _strip_chart_runs(tgt)
        # 🔴 母版在「学科1·国内排名」图段里埋了一个**硬分页符**（第4期原件同款）：
        #    不删就会把第 2 张图顶到下一页、页底留大片空白（rick 打开的是待排版稿，
        #    出版件里这个分页符也是没有的）。删掉后「段落 + 两图」一页放得下。
        n_br = 0
        for br in list(tgt._p.findall(".//" + qn("w:br"))):
            if br.get(qn("w:type")) == "page":
                br.getparent().remove(br)
                n_br += 1
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
        tgt.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tgt.add_run().add_picture(str(png), width=Cm(14.0))
        info = meta.get(png.name, {})
        new_desc = f"[图] {png.name}"
        if info.get("model"):
            new_desc += (f"（{info.get('subject', '')}·{info['model']}，"
                         f"预计过线 {info.get('first_crossing') or '区间内未过线'}）")
        slots.append({"location": label,
                      "old": f"母版原生图表 ×{n}" + (f" + 硬分页符 ×{n_br}" if n_br else ""),
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


def _forecast_meta(ledger_dir):
    """预测元数据（`report_forecast` 落的 forecast_charts.json）→ 预测章模型说明句 + 目标学科。

    返回**整份 meta**（`charts` 列表 + `report_subjects` 名单）；缺文件/坏了都返回 None：
    段落退回 `【手工：…】` 槽、目标学科退回接近度前二（可复现性优先，不让填稿挂掉）。
    """
    p = pathlib.Path(ledger_dir) / "forecast_charts.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def fill_texts(doc, ledger_dir, slots, period, prev, facts, fills=None):
    """概述 4 段 + 发展趋势段 + 态势段 + 封面期数（句骨架 + 数字槽）。"""
    college = college_stats.load(pathlib.Path(ledger_dir), period, save=True)
    fm = _forecast_meta(ledger_dir) or {}
    texts = sentences.build(facts, period, prev, college=college,
                            forecast=fm.get("charts"),
                            targets=fm.get("report_subjects"))
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
         manual_inputs=None, native_charts=None):
    """`manual_inputs` 为 None 时**不应用**任何人工填值（机器稿保持纯机器产出）。

    ⚠ 这条默认值是刻意的：`run_pipeline` / `agent/tools.run_docx` 都不传它，
    所以流水线产出的永远是带 `【手工：…】` 占位的机器稿，可复现、可断言。
    只有演示站的「重出报告」显式传入 `manual_inputs.json` —— 那份产物是
    「叠加了人工输入、待签发」的稿子，两者不能混为一谈。

    `native_charts`：None＝看环境变量 `WENHENG_NATIVE_CHARTS`
    （**默认关＝走 PNG**；设 `1/true/yes/on` 开原生图表）。
    **整段兜底**：原生规格构建抛异常时整体回落 PNG，绝不产出缺图的报告。
    """
    ledger_dir = pathlib.Path(ledger_dir)

    wide, ni, nc, thr = compute.load_wide(str(ledger_dir))

    # 期次三级优先（override > 目录名[须是有效期次] > 台账最新）与上期口径都在
    # `period.resolve` 一处。目录名这一级不可省：复现历史期次时若不认目录名，
    # 大表/概述会被填成**台账当期**数据，产出「文件名是第 3 期、内容是第 4 期」的
    # 错稿（2026-09-18 回测发现）——修好后别再各写一套。
    issue = period_mod.resolve(wide, out_dir=ledger_dir, period_override=period_override)
    period, prev = issue.period, issue.prev

    out_path = pathlib.Path(out_path or ledger_dir / f"报告初稿_{period}（试排）.docx")
    prev_month = str(int(prev[4:]))
    # 🔴 成品走原子写（R2-5，2026-10-28）：母版先复制到**同目录 tmp**，全程在 tmp 上
    #    编辑，最后一步 `os.replace` 才让它变成 `out_path` —— 中途崩掉/被 Word 占住时，
    #    目录里不会出现「半截报告」或「没填数的母版副本」。
    tmp_doc = atomic_io.tmp_path(out_path)
    shutil.copy(master, tmp_doc)
    doc = Document(str(tmp_doc))
    t2 = compute.build_table2(wide, ni, nc, thr, period, prev)
    ynd = pd.read_parquet(f"{ledger_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = pd.read_parquet(f"{ledger_dir}/wide/top_total.parquet").set_index("period")["total"].to_dict()
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, period, prev)

    slots = []

    fill_big_table(doc, t2, slots, prev_month)
    n_prov = fill_province(doc, ledger_dir, slots)
    if n_prov:
        print(f"      省域表 T19：填入 {n_prov} 格（数据源＝ESI 机构总表，见 province.json）")
    n_mat = fill_matrix(doc, ledger_dir, slots)
    if n_mat:
        print(f"      矩阵表 T20：填入 {n_mat} 格（数据源＝InCites 历史快照，见 matrix.json）")
    fill_texts(doc, ledger_dir, slots, period, prev, facts, fills=manual_inputs)
    native_specs = None
    native_body = None
    if native_charts_enabled(native_charts):
        import native_report_charts  # noqa: PLC0415
        try:
            native_specs = native_report_charts.slot_charts(ledger_dir, end_period=period)
            if charts_only_demo:
                native_specs = {k: v for k, v in native_specs.items()
                                if k[0] == charts._slug("Chemistry")}
            try:
                _cs = college_stats.load(ledger_dir, period, save=False)
            except Exception:                                      # noqa: BLE001
                _cs = None
            native_body = native_report_charts.body_charts(ledger_dir, end_period=period,
                                                          college=_cs)
        except Exception as e:                                     # noqa: BLE001
            # 🔴 兜底：原生路径整段失败就**整套回落到 PNG**（PNG 照旧是网站图源，
            #    一定在）。绝不因为"新渲染器出问题"而产出一份缺图的报告。
            native_specs, native_body = None, None
            slots.append({"location": "正文/图表渲染路径", "old": "Word 原生图表",
                          "new": f"构建失败，已整体回落 PNG：{type(e).__name__}: {e}",
                          "source": f"{NATIVE_CHARTS_ENV}"})
        if native_specs is not None:
            slots.append({"location": "正文/图表渲染路径", "old": "matplotlib PNG",
                          "new": f"Word 原生图表（{len(native_specs)} 张槽位图 + "
                                 f"{len(native_body or {})} 张正文图，可右键「编辑数据」）",
                          "source": f"{NATIVE_CHARTS_ENV}=1"})
    warns = fill_body_charts(doc, ledger_dir, slots, native=native_body)
    charts_used = ["Chemistry"] if charts_only_demo else DETAIL_TABLES
    chart_dir = ledger_dir / "charts"
    for disc in charts_used:
        insert_charts(doc, ledger_dir, disc, slots, chart_dir, native=native_specs)

    # 带图段落统一「放宽固定行距」（rick 反馈：exact 行距段里内嵌图会压字）；表格槽位图不动。
    n_relax = relax_image_line_spacing(doc)
    if n_relax:
        slots.append({"location": "正文/图片行距", "old": f"{n_relax} 个图段固定行距",
                      "new": f"{n_relax} 个图段改为单倍行距（图不再压字、仍随文流走）",
                      "source": "rick 2026-09-23（防 exact 行距压图）"})

    n_red = _blacken_red_runs(doc)
    if n_red:
        slots.append({"location": "正文/母版红字", "old": f"{n_red} 个纯红 run（#FF0000）",
                      "new": "已还原为黑色（原件正文全黑）",
                      "source": "fill_docx._blacken_red_runs"})

    # 写回 tmp 再 `os.replace`：`doc.save` 自己写盘（二进制），用不了 write_text_atomic，
    # 但重试口径仍是 `atomic_io.replace` 那一份（Windows 上 docx 常被 Word 占着）。
    _save_docx(doc, tmp_doc, out_path)

    atomic_io.write_text_atomic(
        ledger_dir / "red_slots.json",
        json.dumps(slots, ensure_ascii=False, indent=1))

    n_img = sum(1 for s in slots if s["new"].startswith("[图]"))
    n_text = sum(1 for s in slots if not s["location"].startswith("T01/r") and not s["new"].startswith("[图]"))
    md = [f"# 红色件清单 · {period} 期", "",
          f"- 报告初稿：`{out_path}`",
          f"- 大表数值格：{sum(1 for s in slots if s['location'].startswith('T01/r'))} 格（逐格见 red_slots.json）",
          f"- 文字/期次槽位：{n_text} 处（概述 4 段、发展趋势、态势统计、封面期数年月、大表表头）",
          f"- 图表槽位：{n_img} 张（{len(charts_used)} 学科 × 6 图 + 概览/学院/预测图）", "",
          "## 仍为手工的槽位（红色件中的【手工：…】）",
          "- ESI 发布日期、当期全球机构总数（台账外，1 分钟可查）",
          "- 去年同期升幅%（台账外）",
          "- 云南高校总数/增减/新晋学科（省级对比，台账外）",
          "- 目录页码（需 Word 分页后人工填）",
          "- 省表其余高校数据（台账外，人工贴入）", "",
          "## 由流水线自动生成（不再留手工槽）",
          "- 预测章模型说明（趋势/发展力度/模型名/两线交叉期）：来自 `report_forecast` 的 V1 推荐模型结果；"
          "只有缺 `forecast_charts.json`（预测图跳过）时才退回【手工：…】", "",
          "## 预警（母版残留）"]
    if warns:
        md += [f"- {w}" for w in warns]
    else:
        md += ["- 无"]
    md += [
        "- 1‰接近度趋势图（「从国内排名上看」段原图）：需历史 1‰ 阈值列，台账现只存最近两期，暂无法重建；",
        "  建议《千分之一被引阈值》表按列追存历史后由流水线自动生成。", "",
        "## 说明", "签单核对方法：打开报告初稿，对照 red_slots.json 逐条核对“改了啥、来自哪”。"]
    atomic_io.write_text_atomic(ledger_dir / "红色件清单.md", "\n".join(md))
    print(f"报告初稿 → {out_path}")
    print(f"红色件：{len(slots)} 条（大表 {sum(1 for s in slots if s['location'].startswith('T01/r'))} 格 + 文字 {n_text} + 图 {n_img}）")
    return out_path


if __name__ == "__main__":
    main()
