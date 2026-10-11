# -*- coding: utf-8 -*-
"""书架（陈列馆）的数据组装。

完整指标只在服务端按请求从已部署的 ``out/<期次>`` 读取；这里刻意不读取
``web/public`` 或 ``web/dist``，避免构建产物成为数据副本。缺失或损坏的期次
会被跳过。

2026-10-11：角色改两级后两种角色（管理员/操作员）同拿全数据；
新增 ``report_text``——报告正文块（从报告初稿 docx 提取，给册页「报告正文」分页）。
"""
import json
import math
import re
from pathlib import Path

from starlette.responses import Response

from . import artifacts, config
from src import period as period_mod
from src.parse_ledger import DISCIPLINES_CN, norm_disc_cn


EN2CN_SAFE = {en: norm_disc_cn(cn) for en, cn in DISCIPLINES_CN.items()}
EMPTY_FORECAST = {"rows": [], "rows2": [], "impl": "", "window": ""}


def _number(value, cast=float):
    try:
        number = float((value or "").strip())
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return cast(number)


def _read_table(period_dir):
    """table2 的前端投影（读取唯一在 `artifacts.read_table2`）。"""
    rows = artifacts.read_table2(period_dir)
    required = {"discipline", "papers", "total_cites", "cnci", "top_papers", "thr_1pct",
                "thr_1pct_gap", "prox_change", "rank_cn_change"}
    if not rows or not all(required <= set(row) for row in rows):
        return None

    table = []
    for row in rows:
        english = (row.get("discipline") or "").strip()
        if not english:
            continue
        table.append({
            "en": english,
            "cn": EN2CN_SAFE.get(english, english),
            "papers": _number(row.get("papers"), int),
            "cites": _number(row.get("total_cites"), int),
            "cnci": _number(row.get("cnci")),
            "top": _number(row.get("top_papers"), int),
            "thr": _number(row.get("thr_1pct"), int),
            "gap": _number(row.get("thr_1pct_gap"), int),
            "prox": (row.get("prox_change") or "").strip(),
            "rank": (row.get("rank_cn_change") or "").strip(),
        })
    if not table:
        return None
    table.sort(key=lambda row: (row["top"] is None, -(row["top"] or 0)))
    return table


def _forecast_rows(markdown, marker):
    """从「预测选模与过线.md」的一个维度段落抽表（被引 / 排名共用）。"""
    section = markdown.split(marker, 1)[1].split("## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or len(cells) < 12:
            continue
        if cells[0] == "学科" or set(cells[0]) <= set("-: "):
            continue
        rows.append({"en": cells[0], "model": cells[1], "mape": cells[3],
                     "prox": cells[8], "t1": cells[9], "t2": cells[10], "t3": cells[11]})
    return rows


def _read_forecast(period_dir):
    """读取可选预测摘要；没有这项产物不阻止该期书架展示。

    `rows` = 被引维度（路线 1），`rows2` = 排名维度（路线 2，辅助）；
    两者同源同一份 md，展示层据此外出「双路线预测」页。
    """
    try:
        markdown = (period_dir / "预测选模与过线.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return dict(EMPTY_FORECAST)
    if "## 被引维度" not in markdown or "## 排名维度" not in markdown:
        return dict(EMPTY_FORECAST)
    rows = _forecast_rows(markdown, "## 被引维度")
    rows2 = _forecast_rows(markdown, "## 排名维度")

    def grab(prefix):
        for line in markdown.splitlines():
            if line.strip().startswith(prefix):
                text = line.replace("**", "").strip()
                return text.split("：", 1)[-1].strip() if "：" in text else text
        return ""

    return {"rows": rows, "rows2": rows2, "impl": "；".join(grab("**实现口径").split("；")[:2]),
            "window": grab("**序列窗口").split("。", 1)[0]}


#: 报告正文提取（陈列馆册页「报告正文」）：章标题 / 子标题 / 段落 / 插图 / 表格。
_REPORT_CHAPTER = re.compile(r"^[一二三四五六七八九十]+\s")
_REPORT_SUBHEAD = re.compile(r"^\d+[.、]")
_REPORT_TEXT_CACHE: dict = {}
_REPORT_TEXT_CACHE_MAX = 8


def _blip_rids(el):
    """元素内的插图 `[(rid, cx, cy)]`（EMU；cx/cy 可空）——与 report_preview 同口径。"""
    from docx.oxml.ns import qn                                # noqa: PLC0415
    out = []
    for blip in el.findall('.//' + qn('a:blip')):
        rid = blip.get(qn('r:embed'))
        if not rid:
            continue
        cx = cy = None
        parent = blip.getparent()
        while parent is not None and parent.tag != qn('w:p'):
            if parent.tag in (qn('wp:inline'), qn('wp:anchor')):
                ext = parent.find(qn('wp:extent'))
                if ext is not None:
                    cx, cy = int(ext.get('cx') or 0), int(ext.get('cy') or 0)
                break
            parent = parent.getparent()
        out.append((rid, cx, cy))
    return out


def _img_block(rid, cx, cy):
    block: dict = {"t": "img", "rid": rid}
    if cx:
        block["w_cm"] = round(cx / 360000, 2)
    if cy:
        block["h_cm"] = round(cy / 360000, 2)
    return block


def _table_block(tbl_el):
    """表格 → `{"t": "tbl", "rows": [[{text, imgs?, span?}]]}`（图与合并列都保留）。"""
    from docx.oxml.ns import qn                                # noqa: PLC0415
    rows = []
    for tr in tbl_el.findall(qn('w:tr')):
        row = []
        for tc in tr.findall(qn('w:tc')):
            texts = []
            for p in tc.findall(qn('w:p')):
                texts.append("".join(n.text or "" for n in p.findall('.//' + qn('w:t'))))
            cell: dict = {"text": "\n".join(texts).strip()}
            imgs = [rid for rid, _cx, _cy in _blip_rids(tc)]
            if imgs:
                cell["imgs"] = imgs
            span = 1
            tc_pr = tc.find(qn('w:tcPr'))
            if tc_pr is not None:
                gs = tc_pr.find(qn('w:gridSpan'))
                if gs is not None:
                    try:
                        span = int(gs.get(qn('w:val')) or 1)
                    except ValueError:
                        span = 1
            if span > 1:
                cell["span"] = span
            row.append(cell)
        rows.append(row)
    return {"t": "tbl", "rows": rows}


def _keep_table(rows, last_text):
    """适当删减（rick 2026-10-11 定）：顶尖论文清单/目录/大表不进正文；指标变化模块只留化学。"""
    n_rows = len(rows)
    n_img = sum(len(c.get("imgs") or []) for r in rows for c in r)
    if n_rows > 60:                       # 顶尖论文清单（292 行）——rick：不需要
        return False
    if n_rows <= 4 and n_img >= 4:        # 「近期XX发展参考指标变化情况」16 模块：只留化学
        return "近期化学发展" in (last_text or "")
    first = (rows[0][0].get("text") or "") if rows and rows[0] else ""
    if "名词解释" in first:               # 目录表（已有专页）
        return False
    if first.startswith("ESI学科"):       # 大表（册页已有「学科大表」专页，避免重复）
        return False
    return True


def report_text(period_dir):
    """报告初稿 docx → 正文块序列（陈列馆册页「报告正文」用）。

    块类型：`h1` 章标题（`^[一二三四五六七八九十]+\\s`）／`h2` 子标题（`List Paragraph`
    或 `^\\d+.`）／`p` 段落／`img` 插图（`rid` 供 `/api/periods/{期次}/report-image/{rid}`）／
    `tbl` 表格（含单元格图）。起点＝第一个章标题（「一 概述」类）——封面与名词解释不重复。

    删减口径见 `_keep_table`（2026-10-11 rick 定）。缺 docx / 坏 docx → `[]`。
    带 (路径, mtime, 体积) 缓存：docx 一改自动失效。
    """
    period_dir = Path(period_dir)
    docxs = sorted(period_dir.glob("报告初稿_*.docx"))
    if not docxs:
        return []
    docx = docxs[-1]
    try:
        st = docx.stat()
    except OSError:
        return []
    key = (str(docx), st.st_mtime_ns, st.st_size)
    hit = _REPORT_TEXT_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from docx import Document                              # noqa: PLC0415
        from docx.oxml.ns import qn                            # noqa: PLC0415
        from docx.text.paragraph import Paragraph              # noqa: PLC0415
        doc = Document(str(docx))
    except Exception:                                          # noqa: BLE001
        return []
    blocks: list[dict] = []
    started = False
    last_text = ""
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:p'):
            p = Paragraph(child, doc)
            text = p.text.strip()
            rids = _blip_rids(child)
            if text:
                if not started:
                    if _REPORT_CHAPTER.match(text) and text.startswith("一"):
                        started = True
                    else:
                        continue
                if _REPORT_CHAPTER.match(text):
                    blocks.append({"t": "h1", "text": text})
                elif ((p.style is not None and p.style.name == "List Paragraph")
                        or _REPORT_SUBHEAD.match(text)):
                    blocks.append({"t": "h2", "text": text})
                else:
                    blocks.append({"t": "p", "text": text})
                last_text = text
            if started:
                for rid, cx, cy in rids:
                    blocks.append(_img_block(rid, cx, cy))
        elif child.tag == qn('w:tbl'):
            if not started:
                continue
            block = _table_block(child)
            if not _keep_table(block["rows"], last_text):
                # 连图题一起去掉（表没了，题不悬着）——指标变化模块的题以「——」开头。
                if blocks and blocks[-1].get("t") == "p" \
                        and str(blocks[-1].get("text", "")).startswith("——"):
                    blocks.pop()
                continue
            blocks.append(block)
    _REPORT_TEXT_CACHE[key] = blocks
    while len(_REPORT_TEXT_CACHE) > _REPORT_TEXT_CACHE_MAX:
        _REPORT_TEXT_CACHE.pop(next(iter(_REPORT_TEXT_CACHE)))
    return blocks


def _book(card, out_dir):
    period_dir = Path(out_dir) / str(card.get("period", ""))
    facts = artifacts.read_facts(period_dir)
    meta = artifacts.read_meta(period_dir)
    table = _read_table(period_dir)
    if not facts or not meta or table is None:
        return None
    period = period_mod.from_dir(period_dir.name)
    if not period:
        return None
    try:
        _, issue = period_mod.issue_of(period)
    except ValueError:
        return None
    counts = artifacts.assertion_counts(meta)          # 严格口径唯一在 artifacts
    passed, total = counts["total"] - counts["fail"], counts["total"]
    return {
        "period": period, "no": issue, "label": period_mod.label(period),
        "coverage": facts.get("coverage_window", ""), "prev_label": facts.get("prev_label", ""),
        "rank_intl_now": facts.get("rank_intl_now"), "rank_intl_delta": facts.get("rank_intl_delta"),
        "rank_cn_uni_now": facts.get("rank_cn_uni_now"),
        "top_papers_now": facts.get("top_papers_now"), "top_papers_delta": facts.get("top_papers_delta"),
        "top3": facts.get("top3_by_top_papers", []), "best_permille": facts.get("best_1permille", []),
        "not_entered": facts.get("top2_not_entered", []), "n_disc_1pct": facts.get("n_disc_1pct"),
        "n_assert_pass": passed, "n_assert_total": total, "table": table,
        "forecast": _read_forecast(period_dir),
        "report_text": report_text(period_dir),
        "_trend": meta.get("trend", meta.get("top_total_by_period", {})),
    }


def build_data(cards, out_dir=None):
    """根据 ``period_cards`` 的部署清单同步组装；不缓存，下一请求即可反映文件变化。"""
    out_dir = config.OUT_DIR if out_dir is None else out_dir
    books = []
    for card in cards:
        try:
            book = _book(card, out_dir)
        except (OSError, TypeError, ValueError):
            book = None
        if book:
            try:
                json.dumps(book, allow_nan=False)
            except (TypeError, ValueError):
                book = None
        if book:
            books.append(book)
    books.sort(key=lambda book: book["period"])
    trend = books[-1].pop("_trend", {}) if books else {}
    for book in books:
        book.pop("_trend", None)
    trend = trend if isinstance(trend, (dict, list)) else {}
    try:
        json.dumps(trend, allow_nan=False)
    except (TypeError, ValueError):
        trend = {}
    return {"books": books, "trend": trend}


def javascript_response(cards):
    """即使所有期次损坏也回传可执行的空数据，绝不回退到静态完整数据。"""
    try:
        payload = build_data(cards)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        encoded = '{"books":[],"trend":{}}'
    return Response(f"window.WH_DATA = {encoded};\n", media_type="application/javascript")
