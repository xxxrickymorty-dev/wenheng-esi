# -*- coding: utf-8 -*-
"""灵活报告 → DOCX（2026-10-15，rick：下载报告给 docx，方便馆员修改）。

- 只支持本产线实际用到的 md 子集（与 `mdview` 同一口径）：标题 / 段落 / 引用 /
  表格 / 列表 / 图片+图注 / 水平线 / `**粗体**` / `` `行内码` `` / `==待审线==`（→ 下划线）；
- 声明口径与渲染层一致：报告内不再重复「内部参考·非报送」（页面导语承担），
  本件按 doc19 导出规格在**页脚位置标注一次**；
- 图片从报告目录就地嵌入（`base_dir`）；缺图静默跳过（宁可少图，不编）。
"""
from __future__ import annotations

import io
import pathlib
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import mdview

_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|==[^=\n]+==)")
_FOOTER = "内部参考 · 非报送件　｜　灵活报告（第二条产线）　｜　不带盖章位"
_SEP = re.compile(r"^\|[\s:|-]+\|$")
_IMG = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
_CAP = re.compile(r"^\*([^*].*)\*$")

_FONT = "SimSun"          # 正文中文：宋体（公文习惯，便于馆员直接改）


def _set_font(run, name=_FONT):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _add_runs(p, text: str) -> None:
    """行内标记 → docx run：**粗体** / `行内码` / ==待审线（下划线）。"""
    for tok in _INLINE.split(text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            r = p.add_run(tok[2:-2])
            r.bold = True
            _set_font(r)
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            r = p.add_run(tok[1:-1])
            _set_font(r, "Consolas")
        elif tok.startswith("==") and tok.endswith("==") and len(tok) > 4:
            r = p.add_run(tok[2:-2])
            r.underline = True
            _set_font(r)
        else:
            r = p.add_run(tok)
            _set_font(r)


def _add_quote(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.55)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    _add_runs(p, text)
    for r in p.runs:
        r.font.size = Pt(10.5)
        r.font.color.rgb = RGBColor(0x5A, 0x51, 0x48)


def build(md: str, *, base_dir=None) -> bytes:
    """报告 md → docx 字节流。`base_dir`＝报告目录（`charts/` 相对它解析）。"""
    md = mdview._strip_legacy_banner(md)
    md = re.sub(r"(?m)^\*内部参考[^\n]*\*[ \t]*\n?", "", md)   # md 里的页脚行：docx 有自己的
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = _FONT
    normal.font.size = Pt(12)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), _FONT)

    lines = md.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        s = raw.strip()

        # 表格（本行含 | 且下一行是分隔行）
        if s.startswith("|") and i + 1 < len(lines) and _SEP.match(lines[i + 1].strip()):
            head = [c.strip() for c in s.strip("|").split("|")]
            aligns = []
            for cell in lines[i + 1].strip().strip("|").split("|"):
                c = cell.strip()
                aligns.append("r" if c.startswith("-") and c.endswith(":") else
                              "c" if c.startswith(":") and c.endswith(":") else "l")
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            tbl = doc.add_table(rows=1 + len(rows), cols=len(head))
            tbl.style = "Table Grid"
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            for j, cell in enumerate(head):
                r = tbl.rows[0].cells[j].paragraphs[0].add_run(cell)
                r.bold = True
                _set_font(r)
            for ri, row in enumerate(rows, start=1):
                for j in range(len(head)):
                    para = tbl.rows[ri].cells[j].paragraphs[0]
                    if j < len(aligns) and aligns[j] == "r":
                        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    _add_runs(para, row[j] if j < len(row) else "")
            doc.add_paragraph()
            continue

        if not s:
            i += 1
            continue
        if s.startswith("---") and set(s) <= {"-"}:
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if m:
            doc.add_heading(m.group(2), level=min(len(m.group(1)) - 1, 4))  # h1→Title，h2→Heading 1
            i += 1
            continue
        if s.startswith(">"):
            _add_quote(doc, s.lstrip("> ").strip())
            i += 1
            continue
        mi = _IMG.match(s)
        if mi:
            _alt, src = mi.group(1), mi.group(2)
            cap = None
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                m2 = _CAP.match(lines[j].strip())
                if m2:
                    cap = m2.group(1)
                    i = j
            if base_dir is not None:
                pp = pathlib.Path(base_dir) / src
                if pp.is_file():
                    doc.add_picture(str(pp), width=Cm(14))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            if cap:
                cp = doc.add_paragraph()
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = cp.add_run(cap)
                r.italic = True
                r.font.size = Pt(10.5)
                r.font.color.rgb = RGBColor(0x8A, 0x7F, 0x72)
                _set_font(r)
            i += 1
            continue
        m = re.match(r"^[-*]\s+(.*)$", raw)
        if m:
            _add_runs(doc.add_paragraph(style="List Bullet"), m.group(1))
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)$", raw)
        if m:
            _add_runs(doc.add_paragraph(style="List Number"), m.group(1))
            i += 1
            continue
        _add_runs(doc.add_paragraph(), raw)
        i += 1

    # 页脚标注（doc19 导出规格：标注一次，不带盖章位）
    fp = doc.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run(_FOOTER)
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x8A, 0x7F, 0x72)
    _set_font(r)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
