# -*- coding: utf-8 -*-
"""生成《仍需馆员提供的数据清单》docx（发卜彤）。

背景：2026-09-23 起 ESI 8 项 + InCites 6 项取数已全部脚本化并自动贴入台账
（含顶尖论文清单 = ESI Top Papers 明细自动导出、在榜学科进/退事件自动核对），
馆员侧只剩少数「下载数据里没有的东西」。

用法（wenheng/ 下，.venv 的 python）：
    .venv\\Scripts\\python.exe tools\\make_librarian_ask_docx.py
输出：..\\评审文档\\27-仍需馆员提供的数据清单（送卜彤·2026-09-23）.docx
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO.parent / "评审文档" / "27-仍需馆员提供的数据清单（送卜彤·2026-09-23）.docx"

TODAY = "2026-09-23"


def set_cn_font(doc):
    st = doc.styles["Normal"]
    st.font.name = "等线"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "等线")
    for s in ("Title", "Heading 1", "Heading 2"):
        try:
            st2 = doc.styles[s]
            st2.font.name = "等线"
            st2.element.rPr.rFonts.set(qn("w:eastAsia"), "等线")
        except KeyError:
            pass


def h(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x3B, 0x63)
    return p


def para(doc, text, bold=False, indent=0.0, size=None):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.left_indent = Pt(indent)
    r = p.add_run(text)
    r.bold = bold
    if size:
        r.font.size = Pt(size)
    return p


def table(doc, header, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, v in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(v)
        r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Pt(w)
    return t


def main():
    doc = Document()
    set_cn_font(doc)
    t = doc.add_heading("仍需馆员提供的数据清单", 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"（《云南大学学科信息参考》取数自动化上线后 · {TODAY}）").italic = True

    table(doc, ["项目", "内容"], [
        ["编制", "文衡项目组"],
        ["送交", "卜彤老师（请核对/提供）"],
        ["目的", "说明：自 2026-09-23 起，原《每期取数工作清单》里的 ESI 8 项、InCites 6 项、"
                 "顶尖论文清单已全部由程序自动下载并自动贴入监测表；本清单只列**程序无论如何拿不到、"
                 "必须由馆内提供**的少数几项，并逐项说明原因。"],
    ], widths=[60, 380])
    doc.add_paragraph()

    h(doc, "一、每期需提供（2 项）", 1)
    table(doc, ["项目", "用途", "为什么无法从下载数据 / 台账中提取", "请提供的形态"], [
        ["《实际与预测差值》里的\n“预测值”记录（SPSS）",
         "监测表《实际与预测差值》表；报告预测章与历史回测基准。",
         "这套预测值是馆内 SPSS 模型跑出来的结果，不在 ESI / InCites / WoS 任何导出文件里；"
         "台账里能自动算出的只有“实际值”（由两路数据推导），没有“预测值”的外部来源。",
         "按现有表格格式提供每期预测值（贴回监测表或单独发一张表/截图均可）。"],
        ["当期 ESI 发布日期\n（报告数据说明用）",
         "报告“数据来源/说明”中需要写明 ESI 数据为哪一天发布。",
         "ESI 导出文件里只有内容（机构、学科、阈值等），**没有发布日期字段**；"
         "InCites 的 “dataset updated” 是 InCites 自己的更新日，不等于 ESI 官方发布日。",
         "一句话即可（官网/邮件通知上的发布日）。"],
    ], widths=[100, 110, 230, 130])
    para(doc, "※ 同属“报告里要写的信息”：若报告口径还需要“当期全球机构总数”，我们可以直接从 ESI 机构总表"
              "数出来（202607 期为 10428 家），请确认是否就用这个数；如另有官方口径，请给出数字。", indent=12)

    h(doc, "二、一次性确认（2 项）", 1)
    para(doc, "1. 学院归属映射（《学院映射草表（待卜彤确认）》）：24 组建议归属 + 4 个重点判断", bold=True)
    para(doc, "为什么无法自动：WoS/ESI 导出的地址字段只有英文片段（如 SCH MAT & ENERGY、"
              "INST ECOL RES & POLLUT CONTROL PLATEAU LAKES），**没有到学院的对应关系**；"
              "全台账搜索也没有“学院级映射”（0 处）。学院统计表要用它把论文归到学院，只能由熟悉"
              "校内机构的老师确认。", indent=12)
    para(doc, "请做什么：在草表里每行三选一圈改——☐同意 ｜ ☐修改（写正确学院）｜ ☐合并到上一条；"
              "重点回答四件事：① 22 个学院名单是否照草案；② 国重室/研究院是否单列或挂靠；"
              "③ 附属医院是否单列；④ “SCH ENGN”（9 篇）对应哪个学院。"
              "（另：本次导出 274 条与馆内“275 行”差 1，也请一并说明。）", indent=12)
    doc.add_paragraph()
    para(doc, "2. 省级对比口径（报告第四章省表）", bold=True)
    para(doc, "为什么无法自动：“云南省高校总数”来自教育主管部门名单，不在 ESI/InCites 任何表里；"
              "各校的 ESI 学科在榜/进退我们可以从学科榜自动推，但“全省新晋学科”若按官方通报口径，"
              "需馆内确认。", indent=12)
    para(doc, "请做什么：给出“云南高校总数/增减/新晋学科”的现行口径与数字；如希望由我们推各校进退，"
              "请确认参与对比的学校范围。", indent=12)

    h(doc, "三、可选补录（低优先，做历史图时才需要）", 1)
    table(doc, ["项目", "为什么无法自动", "说明"], [
        ["Q1–Q4 表 2021.09 之前的期次；《篇均被引》表“中国大陆/国际”两列 2024.11 之前的期次",
         "更早期 InCites 快照本身没导过这些列（快照导出文件里就没有），不是台账缺格。",
         "若报告要做更长的历史曲线再补导，可分批。"],
        ["早期 InCites 快照 219 个“字节级损坏”文件重导",
         "当年导出/另存时编码损坏且字节已丢失（不可逆），本地无法修复。",
         "对应 201911–202011 的台账列，**不在现阶段报告窗口**，需要时再重导。"],
        ["历史人工原件（2026 年第 1–4 期已齐）",
         "人工原件是馆内 Word/纸质存档，不存在于任何数据源；回测要用它做“机器稿 vs 人工稿”逐格比对。",
         "如馆内还有更早期（2019–2025）各期报告，请一并提供。"]
    ], widths=[150, 190, 130])

    h(doc, "四、已自动化，请不必再手工下载/粘贴", 1)
    para(doc, "以下内容现在由程序自动完成（每期一条命令：下载两路数据 → 自动清洗进监测表）：", indent=12)
    for line in (
        "① ESI 侧 8 项：云大排名三序列、22 学科总被引/论文数/CNCI/TOP论文、ESI 前 1% 阈值、"
        "前 0.1% 阈值、已进入学科清单与**进/退事件**（自动核对，不再需要人工报）；",
        "② InCites 侧 6 项：22 学科国际/国内排名与百分位、未进入学科论文数/被引、篇均被引、Q1–Q4、"
        "云南省高校对比底料；",
        "③ WoS 侧 1 项：**顶尖论文清单**——已由 ESI “机构=云南大学 + Top Papers”明细自动导出，"
        "列与馆员导出完全同构（含 Authors / Addresses / Institutions），无需再手工导出；",
        "④ 台账《InCites快照》登记表、接近度等派生列也自动维护。",
    ):
        para(doc, line, indent=24)

    h(doc, "五、交付方式与时间", 1)
    for line in (
        "· 每期在出稿前 1–2 天提供即可；文本类信息（发布日期等）直接微信/邮件一句话即可。",
        "· 表格类（预测值、学院映射圈改）可发回电子版，或贴回监测表对应工作表。",
        "· 历史原件请放/发到项目目录（或扫描件）。",
        "· 收到后我们会跑一致性检查（含在榜学科自动核对）再出稿；有冲突会逐条回报。",
    ):
        para(doc, line, indent=12)
    doc.add_paragraph()
    para(doc, f"编制日期：{TODAY}　·　本清单随自动化进度更新，如有与本清单不一致的历史习惯，以卜老师意见为准并回改。", size=9)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"[OK] {OUT}")


if __name__ == "__main__":
    sys.exit(main())
