# -*- coding: utf-8 -*-
"""监测版 Word 导出：消费 report._report_data() 的同一份数据装配，出简洁公文版式。

数字与 HTML 同源（共用 _report_data，无第二套换算）；导出不调模型（路由侧
insight=None，缺省即无解读段）。v1 取舍：图表（svg）不放 docx，趋势章保留章首注
与进位时间线文字。落盘 monitor_data/<校名>/<期次>.docx，已存在直接返回（幂等）。
"""
from __future__ import annotations

import pathlib

import docx
from docx.shared import Pt

from monitor import report as mr
from monitor import schools as sch


def _small(doc, text: str) -> None:
    """注脚式小字段落（meta／note／页脚）。"""
    p = doc.add_paragraph(text)
    for r in p.runs:
        r.font.size = Pt(9.5)


def _table(doc, t: dict) -> None:
    """table 规格 → Table Grid 表（表头行加粗；空表落 placeholder 合并行）。"""
    tab = doc.add_table(rows=1, cols=len(t["head"]))
    tab.style = "Table Grid"
    for i, head in enumerate(t["head"]):
        tab.rows[0].cells[i].paragraphs[0].add_run(head).bold = True
    if not t["rows"] and t.get("placeholder"):
        row = tab.add_row()
        merged = row.cells[0].merge(row.cells[-1])
        merged.paragraphs[0].add_run(t["placeholder"])
        return
    for vals in t["rows"]:
        cells = tab.add_row().cells
        for i, v in enumerate(vals):
            cells[i].text = str(v)


def export(cn: str, period: str, cache: dict, insight: dict | None = None) -> pathlib.Path:
    """导出一所学校的 Word 版监测报告，返回文件路径（已存在直接返回，幂等）。

    存在性检查在装配（含 trend.combine 全库扫描）之前——缓存命中不付全额（20261101 C7）。"""
    out = mr.MONITOR_ROOT / cn / f"{period}.docx"
    if out.exists():
        return out
    d = mr._report_data(cn, period, cache, insight)
    doc = docx.Document()
    doc.add_heading(f'{d["cn"]} · 学科监测报告 · {d["period"]}', level=0)
    _small(doc, d["meta"])
    for n in d["nums"]:
        p = doc.add_paragraph()
        p.add_run(f'{n["label"]}：').bold = True
        p.add_run(n["value"] + (n.get("suffix") or ""))
        if n.get("note"):
            p.add_run(f'（{n["note"]}）')
    if d.get("absent_note"):
        _small(doc, d["absent_note"])
    for sec in d["sections"]:
        doc.add_heading(f'{sec["num"]}、{sec["title"]}', level=1)
        if sec.get("table"):
            _table(doc, sec["table"])
        for note in sec.get("notes", []):
            _small(doc, note)
        # 图表（svg）v1 不放 docx：趋势章的章首注随 notes、进位时间线随 timeline 保留
        tl = sec.get("timeline")
        if tl:
            p = doc.add_paragraph()
            p.add_run(tl["cap"]).bold = True
            for item in tl["items"]:
                doc.add_paragraph(item)
    ins = d.get("insight")
    if ins and (ins.get("text") or "").strip():
        doc.add_heading("六、解读", level=1)
        for pp in [x for x in ins["text"].split("\n\n") if x.strip()]:
            doc.add_paragraph(pp)
        _small(doc, mr.insight_how(ins.get("mode")) + "。")
    _small(doc, "派生算法：" + " · ".join(d["algorithms"]) + "。")
    _small(doc, d["footer"]["source"])
    _small(doc, d["footer"]["engine"])
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def ensure(cn: str, period: str) -> pathlib.Path | None:
    """缺件兜底（20261101 C7，供服务端 docx 触发段接线）：当期 docx 缺失 → 现算导出
    （不调模型，insight=None）；已存在 → 直接返回该路径。

    老期次缺失 → 不补（返回 None）——docx 只随当期生成，老期次连 html 都不随档；
    名单外校 / 无可用期次 → None。期次目录存在但包坏 → build_cache 的异常照抛
    （调用方按 404/500 处理），与 server 内联段语义一致。"""
    if sch.find(cn) is None:
        return None
    if period != (mr.latest_period() or ""):
        return None
    out = mr.MONITOR_ROOT / cn / f"{period}.docx"
    if out.exists():
        return out
    cache = mr.load_cache(period) or mr.build_cache(period)
    return export(cn, period, cache)
