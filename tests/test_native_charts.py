# -*- coding: utf-8 -*-
"""Word 原生图表（`src/native_charts.py` / `src/native_report_charts.py`）测试。

两条主线：

1. **schema 护栏**（纯静态，不需要数据）—— 2026-10-22 实测踩过三个坑，每个都让
   **Word 拒绝打开整份文档**（报「Word 在读取该文件时遇到错误」，不是"图表不显示"）：
     · 柱状图写 `c:dLblPos val="t"`（折线专属位）；
     · `c:gapWidth` 超过 500（matplotlib `width=0.16` 换算是 525）；
     · `formatCode="0.##"%"` 里的引号没转义，把 XML 属性截断。
   这三条现在由 `native_charts.validate_chart_xml` 在插入前拦住，本文件再钉一遍。

2. **口径一致**（数据驱动）—— 原生路径的纵轴刻度必须与 matplotlib 路径
   （`charts._auto_ylim`）逐学科一致，否则两条路径会画出不同的图。
"""
from __future__ import annotations

import pathlib
import re
import sys
import zipfile

import pytest

from _guard_registry import skip_unless

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import charts  # noqa: E402
import native_charts as nc  # noqa: E402
import native_report_charts as nrc  # noqa: E402

MASTER = ROOT / "master" / "学科信息参考母版_2026第5期.docx"
LEDGER = ROOT / "out" / "202607"          # 金标期次（演示站首屏依赖，长期在库）


def _ledger_available():
    return (LEDGER / "ledger_long.parquet").exists() and (LEDGER / "wide").exists()


def _bar(gap=525, overlap=-27):
    return nc.bar_chart_xml([{"name": "x", "values": [1.0, 2.0, 3.0], "color": "4472C4"}],
                            ["a", "b", "c"], gap_width=gap, overlap=overlap)


# ============================================================ ① schema 护栏
def test_柱状图不许用折线专属的数值标签位():
    """柱状/条形图只认 outEnd/inEnd/inBase/ctr/bestFit；写 t 会让 Word 打不开整份文档。"""
    xml = _bar()
    assert '<c:dLblPos val="outEnd"/>' in xml
    for bad in ('<c:dLblPos val="t"/>', '<c:dLblPos val="b"/>',
                '<c:dLblPos val="l"/>', '<c:dLblPos val="r"/>'):
        assert bad not in xml


def test_柱状图类目轴显式水平():
    """不写 `rot` 时 Word 会把六位期次自动斜排 45°（2026-10-23 实测），必须写 rot="0"。"""
    xml = _bar()
    cat = xml[xml.find("<c:catAx>"):xml.find("</c:catAx>")]
    assert '<a:bodyPr rot="0"/>' in cat
    # 折线图的类目轴保持不写 rot（没有斜排问题，别动）
    line = nc.line_chart_xml([{"name": "x", "values": [1.0, 2.0], "color": "4472C4"}], ["a", "b"])
    line_cat = line[line.find("<c:catAx>"):line.find("</c:catAx>")]
    assert 'rot="0"' not in line_cat


def test_柱状图拒绝_bestFit_标签位():
    """2026-10-23 实测：柱状图写 `dLblPos="bestFit"` 同样让 Word 拒开整份文档。"""
    xml = _bar().replace('<c:dLblPos val="outEnd"/>', '<c:dLblPos val="bestFit"/>')
    with pytest.raises(ValueError, match="bestFit"):
        nc.validate_chart_xml(xml)


def test_折线图数值标签用上方位():
    xml = nc.line_chart_xml([{"name": "x", "values": [1.0, 2.0], "color": "4472C4"}], ["a", "b"])
    assert '<c:dLblPos val="t"/>' in xml


def test_堆叠柱的标签位必须是_inBase():
    """堆叠/百分比堆叠柱只认 ctr/inBase/inEnd；写 outEnd 同样让 Word 打不开整份文档。"""
    groups = [{"kind": "bar", "cat_ax": "c1", "val_ax": "v1", "grouping": "stacked",
               "series": [{"name": "a", "values": [1.0, 2.0], "color": "4472C4",
                           "label_fmt": "0", "show_labels": True}]}]
    axes = [{"id": "c1", "kind": "cat", "cross": "v1"},
            {"id": "v1", "kind": "val", "cross": "c1"}]
    xml = nc.combo_chart_xml(groups, axes, ["a", "b"])
    assert '<c:dLblPos val="inBase"/>' in xml
    assert '<c:dLblPos val="outEnd"/>' not in xml


def test_组合图的轴_id_必须是数字():
    """`c:axId/@val` 是 xsd:unsignedInt；写逻辑名 "c1" 会让 Word 打不开整份文档。"""
    groups = [{"kind": "bar", "cat_ax": "c1", "val_ax": "v1",
               "series": [{"name": "a", "values": [1.0, 2.0], "color": "4472C4"}]},
              {"kind": "line", "cat_ax": "c1", "val_ax": "v1",
               "series": [{"name": "b", "values": [2.0, 1.0], "color": "FF0000"}]}]
    axes = [{"id": "c1", "kind": "cat", "cross": "v1"},
            {"id": "v1", "kind": "val", "cross": "c1"}]
    xml = nc.combo_chart_xml(groups, axes, ["a", "b"])
    for v in re.findall(r'<c:axId val="([^"]*)"/>', xml):
        assert v.isdigit(), f"axId 不是数字：{v}"
    for v in re.findall(r'<c:crossAx val="([^"]*)"/>', xml):
        assert v.isdigit(), f"crossAx 不是数字：{v}"


def test_组合图的系列_idx_全局唯一():
    """两个 chart group 各自从 0 数 idx → 重复；Word 自己生成的组合图是 bar 0,1 + line 2。"""
    groups = [{"kind": "bar", "cat_ax": "c1", "val_ax": "v1",
               "series": [{"name": "a", "values": [1.0, 2.0], "color": "4472C4"},
                          {"name": "b", "values": [2.0, 1.0], "color": "70AD47"}]},
              {"kind": "line", "cat_ax": "c1", "val_ax": "v1",
               "series": [{"name": "c", "values": [3.0, 3.0], "color": "FF0000"}]}]
    axes = [{"id": "c1", "kind": "cat", "cross": "v1"},
            {"id": "v1", "kind": "val", "cross": "c1"}]
    xml = nc.combo_chart_xml(groups, axes, ["a", "b"])
    idx = re.findall(r'<c:ser><c:idx val="(\d+)"/>', xml)
    assert idx == ["0", "1", "2"], idx


def test_原生数据表放在_plotArea_里():
    """`c:dTable` 是 plotArea 的子元素；放错到 chartSpace 虽然 Word 容忍，但不合规。"""
    xml = nc.line_chart_xml([{"name": "x", "values": [1.0, 2.0], "color": "4472C4"}],
                            ["a", "b"], dtable=nc.data_table_xml())
    pa = xml[xml.find("<c:plotArea>"):xml.find("</c:plotArea>")]
    assert "<c:dTable>" in pa


def test_gapWidth_夹到_schema_上限_500():
    """matplotlib width=0.16 → gapWidth 525 > 500（ST_GapAmount 上限）→ Word 拒开。"""
    assert '<c:gapWidth val="500"/>' in _bar(gap=525)
    assert '<c:gapWidth val="25"/>' in _bar(gap=25)
    assert '<c:overlap val="-100"/>' in _bar(overlap=-500)


def test_柱状图默认间隙不越界():
    for gap in (150, 500, 525, 9999):
        m = re.search(r'<c:gapWidth val="(\d+)"/>', _bar(gap=gap))
        assert m and 0 <= int(m.group(1)) <= 500


def test_formatCode_里的引号被转义():
    """`0.##"%"` 直接插进 `formatCode="…"` 会把属性截断 —— 必须转成 &quot;。"""
    xml = nc.bar_chart_xml([{"name": "x", "values": [1.0, 2.0], "color": "4472C4"}],
                           ["a", "b"], label_fmt='0.##"%"')
    assert 'formatCode="0.##&quot;%&quot;"' in xml
    assert 'formatCode="0.##"%' not in xml


def test_数值缓存里没有_nan_inf_None():
    xml = nc.line_chart_xml(
        [{"name": "x", "values": [1.0, 2.0, 3.0], "color": "4472C4"}], ["a", "b", "c"])
    for pat in ("nan", "NaN", "inf", "None"):
        assert not re.search(r"<c:v>[^<]*" + pat + r"[^<]*</c:v>", xml)


def test_生成的_XML_可解析且标签成对():
    for xml in (nc.line_chart_xml([{"name": "x", "values": [1.0], "color": "4472C4"}], ["a"]),
                _bar(), nc.pie_chart_xml([{"name": "p", "values": [1.0, 2.0]}], ["a", "b"])):
        from lxml import etree  # noqa: PLC0415
        etree.fromstring(xml.encode("utf-8"))
        for tag in ("c:chartSpace", "c:chart", "c:plotArea", "c:ser"):
            assert len(re.findall("<" + tag + r"[ >]", xml)) == xml.count("</" + tag + ">")


def test_validate_chart_xml_拦住越界与折线标签位():
    nc.validate_chart_xml(_bar())                     # 合法：不抛
    with pytest.raises(ValueError):
        nc.validate_chart_xml(_bar().replace('<c:gapWidth val="500"/>',
                                             '<c:gapWidth val="525"/>'))
    with pytest.raises(ValueError):
        nc.validate_chart_xml(_bar().replace('<c:dLblPos val="outEnd"/>',
                                             '<c:dLblPos val="t"/>'))
    with pytest.raises(ValueError):
        nc.validate_chart_xml("<c:chartSpace>未闭合")


# ============================================================ ② 口径一致
def test_开关默认开_可用环境变量回落到_PNG(monkeypatch):
    """默认走原生图表（rick 2026-10-23 定）；`WENHENG_NATIVE_CHARTS=0` 回 PNG。"""
    import fill_docx  # noqa: PLC0415
    monkeypatch.delenv(fill_docx.NATIVE_CHARTS_ENV, raising=False)
    assert fill_docx.native_charts_enabled() is True
    assert fill_docx.native_charts_enabled(False) is False
    assert fill_docx.native_charts_enabled(True) is True
    for v in ("0", "false", "no", "off", "OFF"):
        monkeypatch.setenv(fill_docx.NATIVE_CHARTS_ENV, v)
        assert fill_docx.native_charts_enabled() is False, v
    monkeypatch.setenv(fill_docx.NATIVE_CHARTS_ENV, "1")
    assert fill_docx.native_charts_enabled() is True


def test_原生轴刻度与_matplotlib_路径逐学科一致():
    """16 学科 × 6 图：`native_charts.auto_axis` 的刻度必须等于 `charts._auto_ylim`。"""
    if not _ledger_available():
        skip_unless("缺 out/202607 宽表（原生图表轴口径比对需要真实台账产物）",
                    _ledger_available)
    w = nrc.load_wide(LEDGER)
    periods, delta_periods, P = nrc.window(LEDGER)
    cases = []
    ri_all = w["_long"].pipe(lambda d: d[(d.source == "rank_intl") & (d.metric == "rank_pct")]) \
        .pivot(index="discipline", columns="period", values="value")
    rc_all = w["_long"].pipe(lambda d: d[(d.source == "rank_cn") & (d.metric == "rank_pct")]) \
        .pivot(index="discipline", columns="period", values="value")
    for disc in charts.DETAIL_TABLES:
        ri = ri_all.loc[disc, periods].astype(float).tolist()
        rc = rc_all.loc[disc, periods].astype(float).tolist()
        v = w["cnci"].loc[disc, periods].astype(float).tolist()
        dd = w["papers"].loc[disc, delta_periods].astype(float).diff().iloc[1:].tolist()
        c = w["total_cites"].loc[disc, periods].astype(float).tolist()
        t = w["threshold_1pct"].loc[disc, periods].astype(float).tolist()
        tp = w["top_papers"].loc[disc, periods].fillna(0).astype(float).tolist()
        qkey = f"{P[:4]}.{P[4:]}"
        flat = []
        for ent, _lab, _col in charts.Q_ENTITIES:
            s = w["q1q4"][(w["q1q4"].discipline == disc) & (w["q1q4"].entity == ent)
                          & (w["q1q4"].quarter == qkey)]
            if len(s):
                flat.extend(float(s[k].iloc[0]) for k in ("q1", "q2", "q3", "q4")
                            if s[k].iloc[0] == s[k].iloc[0])
        cases += [
            (disc, "rank_pct", [ri, rc], dict(intervals=4, pad=0.06, invert=True)),
            (disc, "cnci", [v], dict(include=[1.0], intervals=5, pad=0.05, lo_pad=0.12)),
            (disc, "papers_new", [dd], dict(zero_base=True, intervals=6, pad=0.08, integer=True)),
            (disc, "cites_threshold", [c, t], dict(intervals=5, pad=0.06, zero_base=False)),
            (disc, "top_papers", [tp], dict(intervals=7, pad=0.06, integer=True, floor_zero=False)),
            (disc, "q_dist", [flat], dict(floor_zero=True, intervals=6, pad=0.05, integer=True)),
        ]
    bad = []
    for disc, name, series, kw in cases:
        fig, ax = charts._fig()
        mpl = charts._auto_ylim(ax, series, **kw)
        charts.plt.close(fig)
        got = nc.auto_axis(series, **kw)
        mine = None if got is None else got[3]
        if mpl != mine:
            bad.append((disc, name, mpl, mine))
    assert bad == [], f"原生轴与 matplotlib 口径不一致：{bad[:3]}"


def test_96_个槽位图规格齐且都能过_schema_护栏():
    if not _ledger_available():
        skip_unless("缺 out/202607 宽表（96 槽位图规格需要真实台账产物）", _ledger_available)
    specs = nrc.slot_charts(LEDGER, end_period="202607")
    assert len(specs) == 96
    assert {f for _s, f in specs} == set(nrc.SLOT_FILES)
    for (slug, fname), spec in specs.items():
        nc.validate_chart_xml(spec["xml"])            # 不合法会抛
        assert spec["xlsx"][:2] == b"PK", f"{slug}/{fname} 的内嵌工作簿不是 xlsx"
        assert len(spec["xlsx"]) > 2000


def test_柱状图槽位的期次标签水平_分区占比用整数标签():
    """2026-10-23 视觉验收：C3/C5 期次不得斜排；C6 12 个标签在 8.26cm 内只能标整数百分比。"""
    if not _ledger_available():
        skip_unless("缺 out/202607 宽表（槽位图规格需要真实台账产物）", _ledger_available)
    specs = nrc.slot_charts(LEDGER, end_period="202607", disciplines=["Chemistry"])
    for fname in ("papers_new.png", "top_papers.png", "q_dist.png"):
        xml = specs[("Chemistry", fname)]["xml"]
        cat = xml[xml.find("<c:catAx>"):xml.find("</c:catAx>")]
        assert '<a:bodyPr rot="0"/>' in cat, fname
    q = specs[("Chemistry", "q_dist.png")]["xml"]
    assert q.count('formatCode="0&quot;%&quot;"') == 3      # 3 个系列的数值标签
    assert '<c:legendPos val="t"/>' in q
    assert '<c:numFmt formatCode="0.##&quot;%&quot;"' not in q


# ============================================================ ③ 插进母版
def test_插入原生图表后包结构正确(tmp_path):
    if not MASTER.exists():
        skip_unless("缺 master/ 母版（原生图表插入需要结构金母版）", MASTER.exists)
    if not _ledger_available():
        skip_unless("缺 out/202607 宽表（原生图表插入需要真实台账产物）", _ledger_available)
    from docx import Document  # noqa: PLC0415
    from docx.oxml.ns import qn  # noqa: PLC0415

    spec = nrc.slot_charts(LEDGER, end_period="202607", disciplines=["Chemistry"])[
        ("Chemistry", "rank_pct.png")]
    doc = Document(str(MASTER))
    tbl = next(t for t in doc.tables if t.rows and t.rows[0].cells
               and t.rows[0].cells[0].text.strip().startswith("国内外排名百分位趋势"))
    cell = tbl.rows[0].cells[0]
    p = next((q for q in cell.paragraphs
              if not q.text.strip() and not q._element.findall(".//" + qn("w:drawing"))), None)
    p = p or cell.add_paragraph()
    rId, partname = nc.insert_chart_in_paragraph(p, spec["xml"], doc, doc_pr_id=9001,
                                                name="测试", xlsx_blob=spec["xlsx"])
    out = tmp_path / "t.docx"
    doc.save(str(out))

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert str(partname).lstrip("/") in names
        rels = z.read(f"word/charts/_rels/{pathlib.PurePosixPath(str(partname)).name}.rels").decode()
        assert "/package" in rels                       # 内嵌工作簿的关系在
        emb = [n for n in names if n.startswith("word/embeddings/")]
        assert len(emb) == 1
        ct = z.read("[Content_Types].xml").decode()
        assert 'Extension="xlsx"' in ct
        assert "drawingml.chart+xml" in ct
        # 段落里确实是一个 chart 图形框，不是图片
        assert "<c:chart " in z.read("word/document.xml").decode()
