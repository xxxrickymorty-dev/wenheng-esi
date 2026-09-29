# -*- coding: utf-8 -*-
"""生成《仍需馆员提供的数据清单》docx（发卜彤）· v2。

v2 修订（2026-09-23，按 rick 意见）：
  · 删除「ESI 发布日期」项——取数即发布，日期由我们下载时自动记录（_下载信息.json）；
  · 学院映射改为「已用《新学院英文对照（含成果平台）.xlsx》自动匹配 137/150」，
    只把 13 个未命中片段 + 非学院平台单元口径 + 274/275 差异留给馆员；
  · 「22 学院名单」不再需要圈改（以对照表“教学科研机构”39 个单元为准）。

用法（wenheng/ 下，.venv 的 python）：
    .venv\\Scripts\\python.exe tools\\make_librarian_ask_docx.py
输出：..\\评审文档\\27-仍需馆员提供的数据清单（送卜彤·2026-09-23）.docx
"""
from __future__ import annotations

import pathlib
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO.parent / "评审文档" / "27-仍需馆员提供的数据清单（送卜彤·2026-09-23）.docx"

TODAY = "2026-09-23"

# 自动匹配结果（2026-09-23 用《新学院英文对照（含成果平台）.xlsx》跑出）
MATCHED, TOTAL = 137, 150
UNMATCHED = [
    ("SCH MAT SCI & ENGN", 6),
    ("(无系所信息)", 3),
    ("YUNNAN PROV KEY LAB MICRONANO MAT & TECHNOL", 1),
    ("SCH PHYS SCI & TECHNOL", 1),
    ("INT JOINT RES CTR SUSTAINABLE UTILIZATIONOF CORDYC", 1),
    ("KEY LAB QUANTUM INFORMAT YUNNAN PROV", 1),
    ("COLL BASIC MED", 1),
    ("INST INT RIVERS & ECOL SECUR", 1),
    ("INST ECOL RES & POLLUT CONTROL PLATEAU LAKES SCH E", 1),
    ("DEPT EDUC | KEY LAB DIGITAL HUMAN TECHNOL R&D APPLICAT APPLICA", 1),
    ("INT JOINT RES CTR OPTOELECT & ENGN RES | LAKESIDE AR VR LAB", 1),
    ("YUNNAN KEY LAB SERV COMP", 1),
    ("SCH STAT & MATH", 1),
]
PLATFORMS = [
    ("云南生物资源国家重点实验室", 12),
    ("云南马来亚学院（现代工学院）", 9),
    ("中国（西南）天文研究所", 6),
    ("云南大学附属医院（云南省第二人民医院、云南省眼科医院）", 5),
    ("西南联合研究生院综合事务部", 4),
    ("药学院（教育部自然资源药物化学重点实验室）", 2),
    ("古生物研究院", 2),
    ("植被结构功能与建造全国重点实验室", 1),
]
EN_ONLY = ["Int Joint Res Ctr Sustainable Utilizat Cordyceps", "Minist Educ",
           "Biocontrol Engn Res Ctr Crop Dis & Pest", "Yunnan Key Lab Plant Reprod Adaptat & Evolutionar",
           "State Key Lab Conservat & Utilizat Bio resources", "Inst Int Rivers & Eco Secur"]


def set_cn_font(doc):
    st = doc.styles["Normal"]
    st.font.name = "等线"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "等线")
    for s in ("Title", "Heading 1"):
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
    p.add_run(f"（《云南大学学科信息参考》取数自动化上线后 · {TODAY} · v4）").italic = True

    table(doc, ["项目", "内容"], [
        ["编制", "文衡项目组"],
        ["送交", "卜彤老师（请核对/提供）"],
        ["目的", "原《每期取数工作清单》里的 ESI 8 项、InCites 6 项、顶尖论文清单均已由程序自动下载、"
                 "逐份核验；**核对通过后并入监测表**（下载完成 ≠ 台账已更新）。本清单只列"
                 "**程序拿不到、必须由馆内提供/确认**的少数几项，并逐项说明原因。"],
        ["修订记录", "v2（同日）：删「ESI 发布日期」（取数即发布，程序记录下载日）；学院映射改为按"
                    "《新学院英文对照（含成果平台）.xlsx》自动匹配 137/150，只留 3 个小问题。"
                    "v3（同日）：删「SPSS 预测值」——预测由我方模型（方法 B）出，其校准语料"
                    "《实际与预测差值》三行（incite/esi/差值）已由两路数据自动生成。"
                    "v4（同日）：流程改为「下载→逐份核验→您核对→并入台账」（写前自动备份、写后逐格核对）；"
                    "按覆盖审计校准两处口径：《顶尖论文》表计数、进/退事件追加（见第四节的 ⚠ 说明）。"],
    ], widths=[60, 380])
    doc.add_paragraph()

    h(doc, "一、每期需提供：无需再向馆内要数据", 1)
    para(doc, "说明（v4）：原先《每期取数工作清单》里要贴进监测表的每一列，现在都能从两路下载数据自动生成、"
              "并在您核对后自动并入台账，包括：", indent=12)
    for line in (
        "· 预测：报告第三章用我方预测模型（方法 B＝InCites 当期值 ＋ 历史差值校准；回测 MAPE 1.92%，"
        "验收线 <5%），模型与方法已写进《预测模型双维度选模报告》，不依赖馆内 SPSS；",
        "· 预测所需的校准语料＝《实际与预测差值》表里的 incite / esi / 差值 三行——InCites 值、ESI 值"
        "两边都已自动抽取，每期自动追加并重算差值；",
        "· ESI 发布日期＝下载日（发布即下载），程序在取数时自动记入 `_下载信息.json`；",
        "· 当期全球机构总数由程序从 ESI 机构总表直接计数（202607 期为 10428 家）。",
    ):
        para(doc, line, indent=24)
    para(doc, "因此每期**不需要**馆内提供数据；如您在核对中发现任何数字与馆内口径不符，请直接指出，"
              "我们逐条回报并回改。", indent=12)

    h(doc, "二、一次性确认（2 项）", 1)
    para(doc, f"1. 学院归属映射：已自动完成 {MATCHED}/{TOTAL}，剩 3 个小问题", bold=True)
    para(doc, "怎么做的：把《学院映射草表》的 150 个地址片段（344 篇论文）与"
              "《新学院英文对照（含成果平台）.xlsx》逐条比对，137 个片段直接命中对照表；"
              "其中 69 处我们初稿的建议与对照表不一致，一律**以对照表为准**（如 SCH ENGN → "
              "云南马来亚学院（现代工学院）、DEPT ATMOSPHER SCI → 地球科学学院、"
              "SCH SOFTWARE → 软件学院（人工智能学院）等）。", indent=12)
    para(doc, "为什么还要问：（对照表里没有的东西，程序无法猜）", indent=12)
    para(doc, "① 以下 13 个片段在对照表里查不到，请给中文单元名（括号内为涉及论文数）：", indent=24)
    for frag, n in UNMATCHED:
        para(doc, f"· {frag}（{n} 篇）", indent=36)
    para(doc, "② 以下“非学院平台”在报告学院统计表里是**单列**还是**并入挂靠学院**？"
              "若并入请给对应关系（括号内为涉及论文数）：", indent=24)
    for u, n in PLATFORMS:
        para(doc, f"· {u}（{n} 篇）", indent=36)
    para(doc, "③ 另 6 个片段在对照表里只对应到英文单元名，也需要中文名：", indent=24)
    para(doc, "、".join(EN_ONLY) + "。", indent=36)
    para(doc, "④ 顺带说明：本期 Top Papers 明细导出 274 条，馆内口径为“275 行”，差 1 条请指认（清单已发）。",
         indent=24)
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
    para(doc, "以下内容现在由程序自动完成（每期三步：取数台下载 + 逐份核验 → 您核对 → 并入台账）：", indent=12)
    for line in (
        "① ESI 侧 8 项：云大排名三序列、22 学科总被引/论文数/TOP论文、ESI 前 1% 阈值、"
        "前 0.1% 阈值、已进入学科清单与进/退事件的**自动核对**；",
        "② InCites 侧 6 项：22 学科国际/国内排名与百分位、未进入学科论文数/被引、篇均被引、Q1–Q4、"
        "CNCI、云南省高校对比底料；",
        "③ WoS 侧 1 项：**顶尖论文清单明细**——已由 ESI “机构=云南大学 + Top Papers”明细自动导出"
        "（列与馆员导出完全同构）；",
        "④ 报告里「ESI 发布日期」取**下载日**（发布即下载，程序自动记入 `_下载信息.json`）；"
        "「当期全球机构总数」由程序从 ESI 机构总表直接计数（202607 期为 10428 家）；",
        "⑤ 台账《实际与预测差值》的 incite/esi/差值 三行（预测校准语料）随每期自动生成；"
        "《InCites快照》登记表、接近度等派生列也自动维护。",
    ):
        para(doc, line, indent=24)
    para(doc, "⚠ 两处说明（v4 覆盖审计后校准，避免口径落差）：", indent=12)
    para(doc, "· 台账《顶尖论文》表的当期计数暂仍需人工——清单明细已自动化（上条③），但"
              "由清单换算成表内计数这一步还没接线；如您愿意，我们下一步把它也做成自动的。", indent=24)
    para(doc, "· 进/退事件：程序每期自动**核对**在榜学科与事件；若确有新增/退出，事件行追加"
              "目前需人工或由我们以专用参数补（默认流程不自动写）。", indent=24)

    h(doc, "五、交付方式与时间", 1)
    for line in (
        "· 每期在出稿前 1–2 天提供即可；文本类信息直接微信/邮件一句话即可。",
        "· 表格类（预测值、学院映射 13 条/平台口径）可发回电子版，或贴回监测表对应工作表。",
        "· 历史原件请放/发到项目目录（或扫描件）。",
        "· 收到后我们会跑一致性检查（含在榜学科自动核对）再出稿；有冲突会逐条回报。",
    ):
        para(doc, line, indent=12)
    doc.add_paragraph()
    para(doc, f"编制日期：{TODAY}　·　本清单随自动化进度更新；如有与本清单不一致的历史习惯，"
              f"以卜老师意见为准并回改。", size=9)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"[OK] {OUT}")


if __name__ == "__main__":
    sys.exit(main())
