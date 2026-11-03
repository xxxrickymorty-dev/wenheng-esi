# -*- coding: utf-8 -*-
"""陈列馆「阅览桌」静态稿装配器（2026-11-03）。

输入：`wenheng/tmp/book-202609.json`（shelf_data + shelf_preview 导出的真数据）
      `reader.template.html`（版式与交互）
输出：`wenheng/web/mockups/陈列馆-阅览桌（静态稿 20261103）.html`（单文件、双击即开）

只做装配：插图从报告 docx 现取（rId → 媒体），压成 webp 内联；翻页声取 public/audio。
不造数、不改文案——正文一字不动。
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[5]          # 工作区根
WEB = pathlib.Path(__file__).resolve().parents[3]           # wenheng/web
OUT = WEB / "mockups" / "陈列馆-阅览桌（静态稿 20261103）.html"
DATA = ROOT / "wenheng" / "tmp" / "book-202609.json"
TPL = pathlib.Path(__file__).resolve().parent / "reader.template.html"
PERIOD = "202609"


def b64(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def webp(raw: bytes, max_w: int, quality: int = 84) -> bytes:
    from PIL import Image
    image = Image.open(io.BytesIO(raw))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    if image.width > max_w:
        h = round(image.height * max_w / image.width)
        image = image.resize((max_w, h), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def docx_images(period: str) -> dict[str, bytes]:
    """rId → 原始图片字节（与 `/api/periods/{期次}/report-image/{rid}` 同源）。"""
    from docx import Document
    docxs = sorted((ROOT / "wenheng" / "out" / period).glob("报告初稿_*.docx"))
    if not docxs:
        return {}
    doc = Document(str(docxs[-1]))
    out: dict[str, bytes] = {}
    for rid, rel in doc.part.rels.items():
        if rel.is_external or "image" not in rel.reltype:
            continue
        try:
            out[rid] = rel.target_part.blob
        except (KeyError, AttributeError):
            continue
    return out


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    book, preview = payload["book"], payload["preview"]["books"][0]
    images = docx_images(PERIOD)
    cache: dict[str, str] = {}

    def src(rid: str) -> str:
        if rid not in cache:
            raw = images.get(rid)
            if raw is None:
                raise SystemExit(f"缺插图 {rid}")
            cache[rid] = b64(webp(raw, 1080), "image/webp")
        return cache[rid]

    blocks = []
    for block in book["report_text"]:
        if block["t"] == "img":
            h_cm, w_cm = block.get("h_cm") or 8, block.get("w_cm") or 14
            blocks.append({"t": "img", "src": src(block["rid"]), "ratio": round(w_cm / h_cm, 4)})
        elif block["t"] == "tbl":
            rows = []
            for row in block["rows"]:
                rows.append([{
                    "text": cell.get("text", ""),
                    "span": cell.get("span") or 1,
                    "imgs": [src(r) for r in (cell.get("imgs") or [])],
                } for cell in row])
            blocks.append({"t": "tbl", "rows": rows})
        else:
            blocks.append({"t": block["t"], "text": block["text"]})

    cover_raw = (WEB / "mockups" / "assets" / "wenheng-covers" / "huizeyuan.webp").read_bytes()
    sounds = [(WEB / "public" / "audio" / f"page-{n}.mp3").read_bytes() for n in (1, 2, 3, 4)]

    issue = preview["cover"][2]
    m = re.match(r"(\d{4})年第(\d+)期（总第(\d+)期）", issue)
    month = re.search(r"(\d{4})年(\d{1,2})月", preview["cover"][3])

    data = {
        "period": PERIOD,
        "issue": f"{m.group(1)} 年第 {int(m.group(2))} 期" if m else issue,
        "total": int(m.group(3)) if m else None,
        "month": f"{month.group(1)} 年 {int(month.group(2))} 月" if month else "",
        "design": "会泽院",
        "org": "云南大学发展规划处 · 图书馆",
        "cover": b64(webp(cover_raw, 900, 88), "image/webp"),
        "toc": preview["toc"],
        "glossary": preview["glossary"],
        "blocks": blocks,
        "kpi": {
            "rankIntl": book.get("rank_intl_now"),
            "rankIntlDelta": book.get("rank_intl_delta"),
            "rankCn": book.get("rank_cn_uni_now"),
            "nDisc": book.get("n_disc_1pct"),
            "topPapers": book.get("top_papers_now"),
            "topPapersDelta": book.get("top_papers_delta"),
            "pass": book.get("n_assert_pass"),
            "total": book.get("n_assert_total"),
            "coverage": book.get("coverage") or "",
            "prev": book.get("prev_label") or "",
        },
        "table": book.get("table") or [],
        "top": {
            "top3": book.get("top3") or [],
            "best": book.get("best_permille") or None,
            "near": book.get("not_entered") or [],
        },
        "sounds": [b64(s, "audio/mpeg") for s in sounds],
    }

    script = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = TPL.read_text(encoding="utf-8").replace("/*__PAYLOAD__*/null", script)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  {OUT.stat().st_size/1024:.0f} KB  blocks={len(blocks)} pages_img={len(cache)}")


if __name__ == "__main__":
    main()
