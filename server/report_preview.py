# -*- coding: utf-8 -*-
"""审核台 · 试排报告预览装配（只读）。

把 `out/<期次>/报告初稿_*.docx` 按文档顺序拆成前端可渲染的块：
段落（含字符级加粗/字号/对齐）、表格（含图与合并列）、插图；
并把正文里的 `【手工：…】` 空位标成可在线填的字段。

字段 id 与工作台（`server/workbench.py`）同一套规则 —— `位置::标记文字`：
- 标记文字在全产物里唯一时直接定 id（不依赖文本定位，最稳）；
- 同一标记出现多处时，用「段落正文 == 某槽位的完整新文本」消歧。

数据只来自 docx 本身与产物目录里的 `red_slots.json`（给空位找归属），
不重算、不改写、不落盘。图片按 rId 惰性交付（`image()`）。
"""
from __future__ import annotations

import pathlib
import re
import time

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from . import artifacts

_HAND = re.compile(r"【手工：([^】]*)】")
_ALIGN = {0: "left", 1: "center", 2: "right", 3: "justify", 4: "distribute"}

#: docx 一变（重出 / 手改），mtime 与体积必变 → 缓存自动失效
_MAX_CACHE = 6
_CACHE: dict[tuple, dict] = {}


def _find_docx(out_dir: pathlib.Path):
    cands = sorted(out_dir.glob("报告初稿_*.docx"))
    return cands[-1] if cands else None


def _red_slot_maps(out_dir: pathlib.Path):
    """red_slots.json → （完整正文 → 位置、标记文字 → [字段 id]）两张查找表。"""
    by_text: dict[str, str] = {}
    by_hint: dict[str, list[str]] = {}
    for r in artifacts.read_slots(out_dir):
        loc = str(r.get("location") or "")
        full = artifacts.slot_text(r, "new").strip()
        if not loc or not full:
            continue
        by_text.setdefault(full, loc)
        for m in _HAND.finditer(full):
            hint = (m.group(1) or "").strip()
            fid = f"{loc}::{hint}"
            ids = by_hint.setdefault(hint, [])
            if fid not in ids:
                ids.append(fid)
    return by_text, by_hint


def _field_id(hint, loc, by_hint):
    """一处空位的字段 id；定不了就返回 None（宁可不填，不瞎挂键）。"""
    ids = by_hint.get(hint) or []
    if len(ids) == 1:
        return ids[0]
    if len(ids) > 1:
        want = f"{loc}::{hint}" if loc else ""
        if want in ids:
            return want
        return ids[0]
    return None


def _para_runs(p: Paragraph):
    runs = []
    for r in p.runs:
        t = r.text
        if not t:
            continue
        size = r.font.size.pt if r.font.size is not None else None
        runs.append([t, bool(r.bold), size])
    return runs


def _push_text(segs, text, styles):
    if not text:
        return
    b, s = styles[0]
    if segs and "t" in segs[-1] and segs[-1].get("b") == b and segs[-1].get("size") == s:
        segs[-1]["t"] += text
    else:
        segs.append({"t": text, "b": b, "size": s})


def _segments(runs, loc, by_hint):
    """runs → 前端段序列；`【手工：…】` 合成单段（ph），不跨 run、不丢字。"""
    full = "".join(r[0] for r in runs)
    if not full:
        return [], 0
    styles = []
    for t, b, s in runs:
        styles += [(b, s)] * len(t)
    segs, n_ph, pos = [], 0, 0
    for m in _HAND.finditer(full):
        if m.start() > pos:
            _push_text(segs, full[pos:m.start()], styles[pos:m.start()])
        hint = (m.group(1) or "").strip()
        fid = _field_id(hint, loc, by_hint)
        if fid:
            b, s = styles[m.start()]
            segs.append({"ph": fid, "title": hint, "b": b, "size": s})
            n_ph += 1
        else:
            _push_text(segs, m.group(0), styles[m.start():m.end()])
        pos = m.end()
    if pos < len(full):
        _push_text(segs, full[pos:], styles[pos:])
    return segs, n_ph


def _drawings(el):
    """元素内所有插图：[(rId, cx, cy)]（EMU；cx/cy 可能为 None）。"""
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


def _para_blocks(p: Paragraph, by_text, by_hint):
    """一段 → （块列表, 空位数）。纯图段给图块；有文本段给段落块（图另附）。"""
    el = p._element
    drawings = _drawings(el)
    text = p.text.strip()
    blocks: list[dict] = []
    n_ph = 0
    if text:
        loc = by_text.get(text) or None
        segs, n_ph = _segments(_para_runs(p), loc, by_hint)
        if segs:
            align = _ALIGN.get(int(p.alignment)) if p.alignment is not None else None
            blocks.append({"t": "p", "align": align, "runs": segs})
    for rid, cx, cy in drawings:
        blocks.append(_img_block(rid, cx, cy))
    return blocks, n_ph


def _table_block(tbl_el):
    rows = []
    for tr in tbl_el.findall(qn('w:tr')):
        row = []
        for tc in tr.findall(qn('w:tc')):
            texts = []
            for p in tc.findall(qn('w:p')):
                texts.append("".join(n.text or "" for n in p.findall('.//' + qn('w:t'))))
            cell: dict = {"text": "\n".join(texts).strip()}
            imgs = [rid for rid, _cx, _cy in _drawings(tc)]
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


def _parse(out_dir: pathlib.Path, docx: pathlib.Path):
    by_text, by_hint = _red_slot_maps(out_dir)
    doc = Document(str(docx))
    blocks: list[dict] = []
    n_ph = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:p'):
            part, n = _para_blocks(Paragraph(child, doc), by_text, by_hint)
            blocks.extend(part)
            n_ph += n
        elif child.tag == qn('w:tbl'):
            blocks.append(_table_block(child))

    fields: dict[str, dict] = {}
    rids: list[str] = []
    for b in blocks:
        if b.get("t") == "p":
            for seg in b.get("runs", []):
                fid = seg.get("ph")
                if fid:
                    fields.setdefault(fid, {"where": fid.split("::", 1)[0],
                                            "title": seg.get("title") or ""})
        elif b.get("t") == "img":
            rids.append(b["rid"])
        elif b.get("t") == "tbl":
            for cells in b["rows"]:
                for cell in cells:
                    rids.extend(cell.get("imgs") or [])

    images: dict[str, tuple] = {}
    for rid in dict.fromkeys(rids):
        part = doc.part.related_parts.get(rid)
        if part is not None and hasattr(part, "blob"):
            images[rid] = (part.blob, getattr(part, "content_type", "application/octet-stream"))

    st = docx.stat()
    return {
        "period": out_dir.name,
        "docx": docx.name,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        "blocks": blocks,
        "fields": fields,
        "n_manual_ph": n_ph,
        "images": images,
    }


def load(out_dir):
    """解析（或命中缓存）并返回含图片二进制的大 dict；没出稿返回 None。"""
    out_dir = pathlib.Path(out_dir)
    docx = _find_docx(out_dir)
    if docx is None:
        return None
    st = docx.stat()
    key = (str(docx), st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    data = _parse(out_dir, docx)
    _CACHE[key] = data
    while len(_CACHE) > _MAX_CACHE:
        _CACHE.pop(next(iter(_CACHE)))
    return data


def build(out_dir):
    """前端用：不含图片二进制（图片走 image() 单独取）。"""
    data = load(out_dir)
    if data is None:
        return {"period": pathlib.Path(out_dir).name, "docx": None,
                "updated_at": "", "blocks": [], "fields": {}, "n_manual_ph": 0}
    return {k: v for k, v in data.items() if k != "images"}


def image(out_dir, rid):
    """按 rId 取图（bytes, content_type）；没有返回 None。"""
    if not re.fullmatch(r"rId\d+", rid or ""):
        return None
    data = load(out_dir)
    if data is None:
        return None
    return data["images"].get(rid)
