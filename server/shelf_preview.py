# -*- coding: utf-8 -*-
"""陈列馆游客预览：只从报告中摘取封面、目录和名词解释。"""
import json
from pathlib import Path

from docx import Document

from . import config


def _preview_from_docx(docx_path: Path):
    """按固定报告结构提取白名单字段；结构不符时不输出任何内容。"""
    try:
        doc = Document(str(docx_path))
        cover = [paragraph.text for paragraph in doc.paragraphs[:4]]
        if len(cover) != 4:
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
        if not toc or toc[0]["title"] != "名词解释":
            return None

        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs]
        start = paragraphs.index("名词解释：") + 1
        end = paragraphs.index("一 概述", start)
        glossary_lines = [line for line in paragraphs[start:end] if line]
        if not glossary_lines or len(glossary_lines) % 2:
            return None
        glossary = [
            {"term": glossary_lines[index], "definition": glossary_lines[index + 1]}
            for index in range(0, len(glossary_lines), 2)
        ]
    except Exception:  # 损坏 DOCX 或不符合固定版式时一律不出现在游客数据中。
        return None
    return {"cover": cover, "toc": toc, "glossary": glossary}


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
    return {"preview": True, "books": books, "trend": {}}


def javascript_response(cards):
    """输出动态 data.js；绝不以完整静态数据作为故障回退。"""
    payload = build_preview(cards)
    body = "window.WH_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    from starlette.responses import Response  # 避免模块加载时扩大 Web 依赖
    return Response(body, media_type="application/javascript")
