# -*- coding: utf-8 -*-
"""陈列馆游客预览：只从报告中摘取封面、目录和名词解释。"""
import json
import re
from pathlib import Path

from docx import Document

from . import artifacts, config

_ISSUE_LINE = re.compile(r"^(?P<year>\d{4})年第\d+期（总第(?P<no>\d+)期）$")
_MONTH_LINE = re.compile(r"(\d{4}年\d{1,2}月)\s*$")
_PAGE_NUMBER = re.compile(r"^[1-9]\d*$")
_TOC_TITLES = (
    "名词解释", "一 概述", "二 我校学科发展情况", "三 我校潜力学科趋势预测",
    "四 云南省主要高校学科发展基本情况", "五 我校顶尖论文清单",
)
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
        if (tuple(row["title"] for row in toc) != _TOC_TITLES or toc[0]["page"] != ""
                or any(not _PAGE_NUMBER.fullmatch(row["page"]) for row in toc[1:])):
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


#: 陈列馆首页事实条从该期产物里取的数：键＝overview_facts.json 里的字段，值＝给前端的字段名。
#: top_papers_now 的口径是「上榜论文」（热点∪高被引，与报告一致）。
_STATS_FROM_FACTS = (("n_disc_1pct", "topOnePercent"), ("top_papers_now", "highlyCited"))

#: 审计记录里「手工槽清点」条目的 id（audit.py 第 5 项）——待人工数从这条里取。
_MANUAL_SLOTS_ID = "manual_slots"


def _stats_from_period(period_dir: Path) -> dict:
    """首页事实条：最新一期产物里的数，哪项缺或形状不对就省哪项，绝不估数。"""
    stats = {}
    rows = artifacts.read_table2(period_dir)
    if rows:
        stats["monitored"] = len(rows)  # 对勘本一行一学科，行数就是在监测的学科数
    facts = artifacts.read_facts(period_dir)
    for key, name in _STATS_FROM_FACTS:
        value = facts.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            stats[name] = value
    # 出处槽数：red_slots.json 一槽一处出处（每条都带 source），条数就是「标了出处」的处数
    slots = artifacts.read_slots(period_dir)
    if slots:
        stats["docSlots"] = len(slots)
    # 机器自检数：meta.json 的断言清单——出稿前逐项过、全 PASS 才继续（口径与签单闸同源）
    counts = artifacts.assertion_counts(artifacts.read_meta(period_dir))
    if counts["total"]:
        stats["selfChecks"] = counts["total"]
    # 待人工数：审计记录「手工槽清点」条目的 n_pending；早期期次没有审计产物 → 省
    audit = artifacts.read_json(period_dir / "audit_record.json")
    items = audit.get("items") if isinstance(audit, dict) else None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id") == _MANUAL_SLOTS_ID:
                pending = item.get("n_pending")
                if isinstance(pending, int) and not isinstance(pending, bool):
                    stats["pendingManual"] = pending
                break
    return stats


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
        period_match = re.match(r"^(?P<year>\d{4})(?P<month>\d{2})", period)
        expected_month = (f"{period_match.group('year')}年{int(period_match.group('month'))}月"
                          if period_match else None)
        if (preview is not None and period_match and preview["label"] == expected_month
                and preview["cover"][2].strip().startswith(period_match.group("year"))):
            books.append({"period": period, **preview})
    books.sort(key=lambda book: book["period"])
    payload = {"preview": True, "books": books, "trend": {}}
    # 首页事实条跟着书架上最新一期走：数从该期产物里取，产物不齐就整个不给，
    # 前端按「没有事实条」处理（宁可缺，不可给没有出处的数）。
    if books:
        latest = books[-1]["period"]
        stats = _stats_from_period(Path(out_dir) / latest)
        if stats:
            stats["source"] = f"{latest} 期流水线产物（table2、overview_facts、red_slots、meta、audit_record）"
            payload["stats"] = stats
    return payload


def javascript_response(cards):
    """输出动态 data.js；绝不以完整静态数据作为故障回退。"""
    payload = build_preview(cards)
    body = "window.WH_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    from starlette.responses import Response  # 避免模块加载时扩大 Web 依赖
    return Response(body, media_type="application/javascript")
