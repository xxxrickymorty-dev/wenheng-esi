# -*- coding: utf-8 -*-
"""陈列馆游客预览：只从报告中摘取封面、目录和名词解释。"""
import json
import re
from pathlib import Path

from docx import Document

from . import config

_ISSUE_LINE = re.compile(r"^\d{4}年第\d+期（总第(?P<no>\d+)期）$")
_MONTH_LINE = re.compile(r"(\d{4}年\d{1,2}月)\s*$")
_GLOSSARY_TERMS = (
    "高被引论文（Highly Cited Paper）", "热点论文（Hot Paper）", "顶尖论文（Top paper）", "阈值",
    "潜力学科", "学科规范化引文影响力（CNCI）", "排名百分位", "引文影响力",
)


def _preview_from_docx(docx_path: Path):
    """按固定报告结构提取白名单字段；结构不符时不输出任何内容。"""
    try:
        doc = Document(str(docx_path))
        cover = [paragraph.text for paragraph in doc.paragraphs[:4]]
        issue = _ISSUE_LINE.fullmatch(cover[2].strip()) if len(cover) == 4 else None
        month = _MONTH_LINE.search(cover[3].strip()) if len(cover) == 4 else None
        if (not issue or cover[0].strip() or cover[1].strip() != "学科信息参考"
                or "云南大学" not in cover[3] or "图书馆编" not in cover[3] or not month):
            return None

        table = doc.tables[0]
        toc = []
        for row in table.rows:
            if len(row.cells) != 2:
                return None
            title, page = (cell.text.strip() for cell in row.cells)
            if not title:
                return None
            toc.append({"title": title, "page": page})
        if (len(toc) < 2 or toc[0] != {"title": "名词解释", "page": ""}
                or toc[1]["title"] != "一 概述" or not toc[1]["page"].isdigit()):
            return None

        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs]
        start = paragraphs.index("名词解释：") + 1
        end = paragraphs.index("一 概述", start)
        glossary_lines = [line for line in paragraphs[start:end] if line]
        if (len(glossary_lines) != len(_GLOSSARY_TERMS) * 2
                or tuple(glossary_lines[::2]) != _GLOSSARY_TERMS):
            return None
        glossary = [
            {"term": glossary_lines[index], "definition": glossary_lines[index + 1]}
            for index in range(0, len(glossary_lines), 2)
        ]
    except Exception:  # 损坏 DOCX 或不符合固定版式时一律不出现在游客数据中。
        return None
    return {"cover": cover, "toc": toc, "glossary": glossary,
            "label": month.group(1), "no": int(issue.group("no"))}


def build_preview(cards, *, out_dir=config.OUT_DIR):
    """按 period_cards 的期次构建安全投影，缺件或坏件逐期关闭。"""
    books = []
    for card in cards:
        period = card.get("period") if isinstance(card, dict) else None
        if not isinstance(period, str):
            continue
        period_dir = Path(out_dir) / period
        docx_files = list(period_dir.glob("报告初稿_*.docx")) if period_dir.is_dir() else []
        if len(docx_files) != 1:
            continue
        preview = _preview_from_docx(docx_files[0])
        if preview is not None:
            books.append({"period": period, **preview})
    books.sort(key=lambda book: book["period"])
    return {"preview": True, "books": books, "trend": {}}


def javascript_response(cards):
    """输出动态 data.js；绝不以完整静态数据作为故障回退。"""
    payload = build_preview(cards)
    body = "window.WH_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    from starlette.responses import Response  # 避免模块加载时扩大 Web 依赖
    return Response(body, media_type="application/javascript")
