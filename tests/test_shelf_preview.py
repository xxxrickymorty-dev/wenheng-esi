# -*- coding: utf-8 -*-
"""陈列馆游客数据只能来自报告的三段白名单。"""
import json

from docx import Document

from server import shelf_preview


def _report(path, *, valid=True):
    document = Document()
    for line in ("封面留白", "学科信息参考", "2026年第5期", "云南大学图书馆"):
        document.add_paragraph(line)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "名词解释" if valid else "正文数据"
    table.cell(0, 1).text = ""
    table.cell(1, 0).text = "一 概述"
    table.cell(1, 1).text = "1"
    document.add_paragraph("名词解释：")
    document.add_paragraph("高被引论文")
    document.add_paragraph("用于说明术语。")
    document.add_paragraph("一 概述")
    document.add_paragraph("正文秘密：291 篇及运行路径 C:/private/out")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "表二秘密"
    document.save(path)


def test_只提取封面目录和名词解释_正文哨兵不泄漏(tmp_path):
    period = tmp_path / "202609"
    period.mkdir()
    _report(period / "报告初稿_202609.docx")

    payload = shelf_preview.build_preview([{"period": "202609"}], out_dir=tmp_path)
    book = payload["books"][0]
    assert payload["preview"] is True and payload["trend"] == {}
    assert set(book) == {"period", "cover", "toc", "glossary"}
    assert book["cover"] == ["封面留白", "学科信息参考", "2026年第5期", "云南大学图书馆"]
    assert book["toc"] == [{"title": "名词解释", "page": ""}, {"title": "一 概述", "page": "1"}]
    assert book["glossary"] == [{"term": "高被引论文", "definition": "用于说明术语。"}]
    assert "正文秘密" not in json.dumps(payload, ensure_ascii=False)
    assert "表二秘密" not in json.dumps(payload, ensure_ascii=False)


def test_缺文件或结构异常逐期关闭(tmp_path):
    malformed = tmp_path / "202607"
    malformed.mkdir()
    _report(malformed / "报告初稿_202607.docx", valid=False)

    payload = shelf_preview.build_preview(
        [{"period": "202609"}, {"period": "202607"}], out_dir=tmp_path)
    assert payload == {"preview": True, "books": [], "trend": {}}
