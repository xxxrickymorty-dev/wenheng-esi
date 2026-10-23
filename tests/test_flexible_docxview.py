# -*- coding: utf-8 -*-
"""flexible.docxview（灵活报告 → docx 导出）回归：md 子集 → docx 结构。

rick 2026-10-15 的需求：下载报告给 docx 方便馆员改。口径：
- 只支持本产线实际用到的 md 子集（标题/段落/引用/表格/列表/图片+图注/水平线/行内标记）；
- 页脚在 docx 里**只标一次**（md 里的旧页脚行要去掉）；
- 缺图静默跳过（宁可少图，不编）。
"""
import base64
import io
import pathlib
import sys

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from flexible import docxview  # noqa: E402

# 1×1 PNG（最小合法图，够 add_picture 识别尺寸）
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMI"
    "QAAAABJRU5ErkJggg==")

_MD = """# 工程学单学科分析

**加粗** 与 `行内码` 与 ==待审句== 同段。

> 引用：本摘要为规划依据。

| 学科 | 论文数 | CNCI |
| --- | --: | :--: |
| 工程学 | 123 | 1.05 |

- 列表项甲
1. 编号项一

![趋势图](charts/trend.png)
*图 1　工程学论文数趋势*

---

*内部参考 · md 里的旧页脚应被去掉*
"""


@pytest.fixture()
def base_dir(tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "trend.png").write_bytes(_PNG)
    return tmp_path


def _doc(b: bytes) -> Document:
    return Document(io.BytesIO(b))


def test_标题段落与行内标记(base_dir):
    doc = _doc(docxview.build(_MD, base_dir=base_dir))
    texts = [p.text for p in doc.paragraphs]
    assert "工程学单学科分析" in texts                       # h1 → 标题
    para = next(p for p in doc.paragraphs if "加粗" in p.text)
    runs = {r.text: r for r in para.runs}
    assert runs["加粗"].bold is True
    assert runs["行内码"].font.name == "Consolas"
    assert runs["待审句"].underline is True                 # ==待审线== → 下划线
    assert "引用：本摘要为规划依据。" in texts


def test_表格_表头加粗与列对齐(base_dir):
    doc = _doc(docxview.build(_MD, base_dir=base_dir))
    assert len(doc.tables) == 1
    tbl = doc.tables[0]
    assert [c.text for c in tbl.rows[0].cells] == ["学科", "论文数", "CNCI"]
    assert tbl.rows[0].cells[0].paragraphs[0].runs[0].bold is True
    assert [c.text for c in tbl.rows[1].cells] == ["工程学", "123", "1.05"]
    assert tbl.rows[1].cells[1].paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
    # 可疑点（按现状记录，未改 src）：`:--:` 解析出 "c" 但 build 只应用右对齐，
    # 居中列从不设置 alignment（None）——居中表头在 docx 里实际左对齐。
    assert tbl.rows[1].cells[2].paragraphs[0].alignment is None
    assert tbl.rows[1].cells[0].paragraphs[0].alignment is None


def test_图片就地嵌入_带图注(base_dir):
    doc = _doc(docxview.build(_MD, base_dir=base_dir))
    assert len(doc.inline_shapes) == 1
    assert any("图 1　工程学论文数趋势" == p.text for p in doc.paragraphs)


def test_缺图静默跳过_图注仍在(tmp_path):
    doc = _doc(docxview.build(_MD, base_dir=tmp_path))      # charts/trend.png 不存在
    assert len(doc.inline_shapes) == 0
    assert any("图 1　工程学论文数趋势" == p.text for p in doc.paragraphs)
    doc2 = _doc(docxview.build(_MD, base_dir=None))         # 不给 base_dir 同样不炸
    assert len(doc2.inline_shapes) == 0


def test_页脚只标一次_md旧页脚被去掉(base_dir):
    doc = _doc(docxview.build(_MD, base_dir=base_dir))
    texts = [p.text for p in doc.paragraphs]
    assert not any("旧页脚" in t for t in texts)             # md 里的页脚行不重复出现
    footers = [t for t in texts if "内部参考 · 非报送件" in t]
    assert len(footers) == 1                                 # docx 自己的页脚标注一次
    assert texts[-1] == footers[0]


def test_水平线不产生段落(base_dir):
    doc = _doc(docxview.build(_MD, base_dir=base_dir))
    assert not any(p.text.strip() == "---" for p in doc.paragraphs)


def test_列表样式(base_dir):
    doc = _doc(docxview.build(_MD, base_dir=base_dir))
    styles = [p.style.name for p in doc.paragraphs if p.text in ("列表项甲", "编号项一")]
    assert "List Bullet" in styles and "List Number" in styles
