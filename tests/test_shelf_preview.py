# -*- coding: utf-8 -*-
"""陈列馆游客数据只能来自报告的三段白名单。"""
import json

from docx import Document

from server import shelf_preview


def _report(path, *, valid=True, cover=True, delayed_body=False, issue="2026年第5期（总第39期）",
            month="2026年9月", toc_extra=None):
    document = Document()
    cover_lines = ("   ", "学科信息参考", issue, f"云南大学发展规划处  图书馆编      {month}")
    for line in (cover_lines if cover else cover_lines[1:]):
        document.add_paragraph(line)
    toc = list(zip(shelf_preview._TOC_TITLES, ("", "1", "2", "26", "28", "30")))
    if toc_extra:
        toc.append(toc_extra)
    table = document.add_table(rows=len(toc), cols=2)
    for index, (title, page) in enumerate(toc):
        table.cell(index, 0).text = title if valid else "正文数据"
        table.cell(index, 1).text = page
    document.add_paragraph("名词解释：")
    for term in shelf_preview._GLOSSARY_TERMS:
        document.add_paragraph(term)
        document.add_paragraph(f"{term}的说明。")
    if delayed_body:
        document.add_paragraph("正文秘密：291 篇及运行路径 C:/private/out")
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
    assert set(book) == {"period", "cover", "toc", "glossary", "label", "no"}
    assert book["cover"] == ["   ", "学科信息参考", "2026年第5期（总第39期）", "云南大学发展规划处  图书馆编      2026年9月"]
    assert book["toc"] == [
        {"title": title, "page": page}
        for title, page in zip(shelf_preview._TOC_TITLES, ("", "1", "2", "26", "28", "30"))
    ]
    assert book["label"] == "2026年9月" and book["no"] == 39
    assert "正文秘密" not in json.dumps(payload, ensure_ascii=False)
    assert "表二秘密" not in json.dumps(payload, ensure_ascii=False)


def test_缺文件或结构异常逐期关闭(tmp_path):
    malformed = tmp_path / "202607"
    malformed.mkdir()
    _report(malformed / "报告初稿_202607.docx", valid=False)

    payload = shelf_preview.build_preview(
        [{"period": "202609"}, {"period": "202607"}], out_dir=tmp_path)
    assert payload == {"preview": True, "books": [], "trend": {}}


def test_缺封面标志或延迟正文标题都关闭(tmp_path):
    missing_cover = tmp_path / "202601"
    delayed_heading = tmp_path / "202603"
    missing_cover.mkdir()
    delayed_heading.mkdir()
    _report(missing_cover / "报告初稿_202601.docx", cover=False)
    _report(delayed_heading / "报告初稿_202603.docx", delayed_body=True)

    payload = shelf_preview.build_preview(
        [{"period": "202601"}, {"period": "202603"}], out_dir=tmp_path)
    assert payload == {"preview": True, "books": [], "trend": {}}


def test_按期次升序并补齐书架封面字段(tmp_path):
    old = tmp_path / "202601"
    latest = tmp_path / "202609"
    old.mkdir()
    latest.mkdir()
    _report(old / "报告初稿_202601.docx", issue="2026年第1期（总第35期）", month="2026年1月")
    _report(latest / "报告初稿_202609.docx")

    payload = shelf_preview.build_preview(
        [{"period": "202609"}, {"period": "202601"}], out_dir=tmp_path)
    assert [(book["period"], book["label"], book["no"]) for book in payload["books"]] == [
        ("202601", "2026年1月", 35), ("202609", "2026年9月", 39),
    ]


def test_目录混入正文或封面期次错标都关闭(tmp_path):
    toc_leak = tmp_path / "202601"
    mismatched_cover = tmp_path / "202603"
    toc_leak.mkdir()
    mismatched_cover.mkdir()
    _report(toc_leak / "报告初稿_202601.docx", toc_extra=("正文秘密", "31"))
    _report(mismatched_cover / "报告初稿_202603.docx")

    payload = shelf_preview.build_preview(
        [{"period": "202601"}, {"period": "202603"}], out_dir=tmp_path)
    assert payload == {"preview": True, "books": [], "trend": {}}
