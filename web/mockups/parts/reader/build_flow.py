# -*- coding: utf-8 -*-
"""陈列馆「入馆—取书—归架」动线静态稿装配器（2026-11-03 第二版）。

输入：`wenheng/tmp/shelf-all.json`（五期预览 + 全内容，真数据）
      `flow.template.html`（空间、动线与阅读器）
      `C:/Users/damn/Desktop/yunnan-library-360/assets/`（全景与内景）
输出：`wenheng/web/mockups/陈列馆-动线（静态稿 20261103）.html`
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[5]
WEB = pathlib.Path(__file__).resolve().parents[3]
OUT = WEB / "mockups" / "陈列馆-动线（静态稿 20261103）.html"
DATA = ROOT / "wenheng" / "tmp" / "shelf-all.json"
ASSETS = pathlib.Path("C:/Users/damn/Desktop/yunnan-library-360/assets")
TPL = pathlib.Path(__file__).resolve().parent / "flow.template.html"
DESIGN = {  # 装帧名 → 封面图（与 LibraryHome 的 DESIGN_MAP 同源）
    "202609": ("会泽院", "huizeyuan.webp"),
    "202607": ("至公堂", "zhigongtang.webp"),
    "202605": ("银杏", "yinxing.webp"),
    "202603": ("阅览室", "yuelanshi.webp"),
    "202601": ("校门", "xiaomen.webp"),
}


def b64(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def to_webp(raw: bytes, max_w: int, quality: int) -> bytes:
    from PIL import Image
    image = Image.open(io.BytesIO(raw))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    if image.width > max_w:
        image = image.resize((max_w, round(image.height * max_w / image.width)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def docx_images(period: str) -> dict[str, bytes]:
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
    preview = {b["period"]: b for b in payload["preview"]["books"]}
    full = {b["period"]: b for b in payload["full"]["books"]}

    books: dict[str, dict] = {}
    for period in sorted(full, reverse=True):
        book = full[period]
        prev = preview[period]
        design, cover_file = DESIGN[period]
        cache: dict[str, str] = {}
        images = docx_images(period)

        def src(rid: str) -> str:
            if rid not in cache:
                raw = images.get(rid)
                if raw is None:
                    raise SystemExit(f"缺插图 {period}/{rid}")
                cache[rid] = b64(to_webp(raw, 820, 78), "image/webp")
            return cache[rid]

        blocks = []
        for block in book.get("report_text") or []:
            if block["t"] == "img":
                h_cm, w_cm = block.get("h_cm") or 8, block.get("w_cm") or 14
                blocks.append({"t": "img", "src": src(block["rid"]), "ratio": round(w_cm / h_cm, 4)})
            elif block["t"] == "tbl":
                blocks.append({"t": "tbl", "rows": [[{
                    "text": c.get("text", ""), "span": c.get("span") or 1,
                    "imgs": [src(r) for r in (c.get("imgs") or [])],
                } for c in row] for row in block["rows"]]})
            else:
                blocks.append({"t": block["t"], "text": block["text"]})

        issue = prev["cover"][2]
        m = re.match(r"(\d{4})年第(\d+)期（总第(\d+)期）", issue)
        month = re.search(r"(\d{4})年(\d{1,2})月", prev["cover"][3])
        cover_raw = (WEB / "mockups" / "assets" / "wenheng-covers" / cover_file).read_bytes()

        books[period] = {
            "period": period,
            "issue": f"{m.group(1)} 年第 {int(m.group(2))} 期" if m else issue,
            "total": int(m.group(3)) if m else None,
            "month": f"{month.group(1)} 年 {int(month.group(2))} 月" if month else "",
            "design": design,
            "org": "云南大学发展规划处 · 图书馆",
            "cover": b64(to_webp(cover_raw, 900, 88), "image/webp"),
            "toc": prev["toc"],
            "glossary": prev["glossary"],
            "blocks": blocks,
            "kpi": {
                "rankIntl": book.get("rank_intl_now"), "rankIntlDelta": book.get("rank_intl_delta"),
                "rankCn": book.get("rank_cn_uni_now"), "nDisc": book.get("n_disc_1pct"),
                "topPapers": book.get("top_papers_now"), "topPapersDelta": book.get("top_papers_delta"),
                "pass": book.get("n_assert_pass"), "total": book.get("n_assert_total"),
                "coverage": book.get("coverage") or "", "prev": book.get("prev_label") or "",
            },
            "table": book.get("table") or [],
            "top": {"top3": book.get("top3") or [], "best": book.get("best_permille") or None,
                    "near": book.get("not_entered") or []},
        }

    data = {
        "books": books,
        "sounds": [b64((WEB / "public" / "audio" / f"page-{n}.mp3").read_bytes(), "audio/mpeg")
                   for n in (1, 2, 3, 4)],
        "plateExterior": b64(to_webp((ASSETS / "library-exterior.png").read_bytes(), 1000, 84), "image/webp"),
        "plateInterior": b64(to_webp((ASSETS / "library-interior.png").read_bytes(), 900, 84), "image/webp"),
        "plateDome": b64(to_webp((ASSETS / "top.png").read_bytes(), 700, 84), "image/webp"),
    }

    script = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = TPL.read_text(encoding="utf-8").replace("/*__PAYLOAD__*/null", script)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  {OUT.stat().st_size/1024/1024:.2f} MB  books={len(books)} "
          f"figs={sum(1 for b in books.values() for x in b['blocks'] if x['t']=='img')}")


if __name__ == "__main__":
    main()
