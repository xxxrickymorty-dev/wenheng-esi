# -*- coding: utf-8 -*-
"""逐格核验：报告 docx 里的每个数 ↔ 台账 / ESI 原始包 / InCites 快照。

**核验原则：不拿流水线自己的中间产物当依据。**
报告里的每一个数，都要能在原始源里指到一个具体单元格；指不到、或指过去对
不上，就报出来。这是发现「静默失效」（不抛异常、只把错的数安静地写进报告）
的唯一可靠手段 —— 2026-09-20 的 T20「植物学与动物学」整行留白就是这么发现的。

用法：
    python tools/verify_report_cells.py 202607
    python tools/verify_report_cells.py 202607 --docx out/202607/报告初稿_202607（试排）.docx
    python tools/verify_report_cells.py 202605 --docx out/202605_复现/报告初稿_202605（试排）.docx

覆盖：
    T01 大表    逐格回读台账（3 个派生列现场重算）
    T19 省域表  逐格回读 province.json（其源是 ESI 机构总表）
    T20 矩阵表  逐格回读 matrix.json，并检查行名归一后 22 学科是否全部命中
    表22 清单   序号连续 / 被引不增 / 与台账 TOP论文 合计一致 / 分学科计数 = 大表该列

退出码 0 = 全对；1 = 有差异（差异逐条打印）。
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import openpyxl                                             # noqa: E402
from openpyxl.utils import get_column_letter                # noqa: E402
import parse_ledger as PL                                   # noqa: E402

LEDGER = REPO.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
DOCX_RE = "报告初稿_{period}（*）.docx"

WIDE_SHEET = {"total_cites": "总被引", "papers": "论文数", "cnci": "CNCI",
              "proximity_1pct": "接近度", "threshold_1pct": "ESI被引阈值",
              "top_papers": "TOP论文"}
PROV_COLS = ["国内排名", "国际排名", "ESI前1%学科数", "发文量", "被引频次",
             "篇均被引频次", "顶尖论文", "高被引论文", "热点论文"]


# ---------------------------------------------------------------- docx 读取
def read_docx(path):
    """→ (tables, paragraphs)。tables[i] 是 list[list[str]]（按 body 顺序）。"""
    import zipfile
    from xml.etree import ElementTree as ET

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    q = lambda t: "{%s}%s" % (W, t)                          # noqa: E731

    def ptext(p):
        return "".join(t.text or "" for t in p.iter(q("t")))

    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml").decode("utf-8"))
    tbls, paras = [], []
    for el in root.find(q("body")):
        tag = el.tag.split("}")[1]
        if tag == "p":
            s = ptext(el).strip()
            if s:
                paras.append(s)
        elif tag == "tbl":
            tbls.append([[" ".join(ptext(p) for p in tc.findall(q("p"))).strip()
                          for tc in tr.findall(q("tc"))] for tr in el.findall(q("tr"))])
    return tbls, paras


# ---------------------------------------------------------------- 台账定位
class Book:
    def __init__(self, path):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        self.sheets = {n: list(wb[n].iter_rows(values_only=True)) for n in wb.sheetnames}
        wb.close()

    def row_of(self, sheet, name, start=1):
        rows = self.sheets[sheet]
        for i in range(start, len(rows)):
            if rows[i] and str(rows[i][0] or "").strip() == name:
                return i
        return None

    def col_of(self, sheet, period, header_row=0, norm=None):
        hdr = self.sheets[sheet][header_row]
        for j in range(1, len(hdr)):
            h = hdr[j]
            if h is None:
                continue
            s = str(h).strip()
            if norm is not None:
                s = norm(s)
            if s == period:
                return j
        return None

    def group_col(self, sheet, period, idx, header_row=0):
        """「新国内排名 / 新国际排名」每期占 3 列（n_inst_1pct, rank, rank_pct）。

        🔴 取组内第 `idx` 列时**必须**从该期首列偏移，不能直接用 `col_of` ——
           `col_of` 返回的是期次表头所在的那一格，也就是组内第 1 列（榜内机构数）。
           报告要的是 rank（idx=1）和 rank_pct（idx=2）；用错会拿到机构数，
           于是「报告 200 ≠ 源 598」这种假差异会一次冒出几十条
           （2026-09-20 本工具第一版就是这么错的）。
        """
        j = self.col_of(sheet, period, header_row)
        return None if j is None else j + idx

    def at_group(self, sheet, en, period, idx, start=1):
        r = self.row_of(sheet, en, start)
        c = self.group_col(sheet, period, idx)
        v, loc = self.at(sheet, r, c)
        return v, loc

    def at(self, sheet, r, c):
        rows = self.sheets[sheet]
        v = rows[r][c] if (r is not None and c is not None and c < len(rows[r])) else None
        return PL._num(v), (f"{sheet}!{get_column_letter(c + 1)}{r + 1}"
                            if r is not None and c is not None else f"{sheet}!（未定位）")


def top_norm(h):
    """《TOP论文》表头期次有脏值（2023.3），与 parse_top_summary 同一套归一。"""
    return re.sub(r"\.(\d)$", r".0\1", str(h)).replace(".", "")


# ---------------------------------------------------------------- 各项核验
def verify_big_table(book, tbl, period, prev):
    """T01 大表：22 行 × 11 列（首列学科名 + 10 个数值列）。"""
    bad, n = [], 0
    for i in range(1, len(tbl)):
        cn = (tbl[i][0] or "").strip()
        en = PL.CN2EN.get(cn) or PL.CN2EN.get(PL.norm_disc_cn(cn))
        if not en:
            bad.append(("T01", cn, "行首学科名认不出", ""))
            continue
        checks = []

        def wide(metric, sheet=None, norm=None):
            sh = sheet or WIDE_SHEET[metric]
            return book.at(sh, book.row_of(sh, en), book.col_of(sh, period, norm=norm))

        # 国内排名/变化 —— 「新国内排名」每期 3 列，rank 是组内第 2 列（idx=1）
        r_now, loc_n = book.at_group("新国内排名", en, period, 1)
        r_prev, loc_p = book.at_group("新国内排名", en, prev, 1)
        if r_now is not None and r_prev is not None:
            d = r_prev - r_now
            checks.append(("国内排名/变化", tbl[i][1],
                           f"{int(r_now)}/-" if d == 0 else
                           f"{int(r_now)}/{'↑' if d > 0 else '↓'}{abs(int(d))}",
                           f"{loc_n} 与 {loc_p}"))
        # 直接取数的列
        for col_j, metric in ((2, "papers"), (3, "cnci"), (4, "total_cites"),
                              (5, "threshold_1pct")):
            v, loc = wide(metric)
            fmt = (None if v is None else
                   (int(v) if metric != "cnci" else f"{v:.2f}"))
            checks.append((metric, tbl[i][col_j],
                           "" if fmt is None else str(fmt), loc))
        cites, loc_c = wide("total_cites")
        t1, loc_t = wide("threshold_1pct")
        checks.append(("1%阈值差", tbl[i][6],
                       "" if cites is None or t1 is None else str(int(cites - t1)),
                       f"派生：{loc_c} − {loc_t}"))
        v, loc = book.at("千分之一被引阈值", book.row_of("千分之一被引阈值", en),
                         book.col_of("千分之一被引阈值", period))
        checks.append(("1‰阈值", tbl[i][7], "" if v is None else str(int(v)), loc))
        # 千分位 = 「新国际排名」的 rank_pct（组内第 3 列，idx=2）× 10
        rp, loc_r = book.at_group("新国际排名", en, period, 2)
        if rp is not None:
            checks.append(("千分位", tbl[i][8], f"{round(rp * 10, 3):.3f}",
                           f"派生：{loc_r} × 10"))
        tpv, loc_tp = wide("top_papers", norm=top_norm)
        checks.append(("顶尖论文", tbl[i][9],
                       "" if tpv is None else str(int(tpv)), loc_tp))
        p_now, loc_pn = wide("proximity_1pct")
        p_prev, loc_pp = book.at("接近度", book.row_of("接近度", en),
                                 book.col_of("接近度", prev))
        if p_now is not None and p_prev is not None:
            chg = (p_now - p_prev) * 100
            checks.append(("接近度较上月", tbl[i][10],
                           f"{'↑' if chg > 0 else ('↓' if chg < 0 else '-')}{abs(chg):.2f}%",
                           f"派生：({loc_pn} − {loc_pp}) × 100"))
        for name, got, want, loc in checks:
            n += 1
            if got.strip() != want.strip():
                bad.append(("T01", f"{cn}·{name}", f"报告 {got!r} ≠ 源 {want!r}", loc))
    return n, bad


def verify_province(tbl, prov):
    """T19：逐格比对 province.json，并如实**报出源端缺的格**。

    ⚠ 「核验 99 格、不符 0」不等于「99 格都有数」：源端为 None 的格（ESI 机构总表
      没有那一列）报告里也是空的，两边都空会被判"一致"。所以要单独把 None 的格
      数出来当提示 —— 否则会以为省域表是全的。
      实测（2026-09-20）：`202601` / `202605` 的 ESI 机构总表只有 6 列，
      **没有 `Highly Cited Papers` / `Hot Papers`**（这两列是 202603 起才有的），
      所以那两期各有 11 校 × 2 列 = 22 格在源端就不存在，无法自动填。
    """
    bad, notes, n = [], [], 0
    if not prov:
        return 0, [("T19", "—", "缺 province.json（该期未生成省域表）", "")], []
    empty = []
    for r in tbl[2:]:
        cn = (r[0] or "").strip()
        mine = (prov.get("universities") or {}).get(cn) or {}
        for col, cell in zip(PROV_COLS, r[1:11]):
            it = mine.get(col) or {}
            v = it.get("v")
            want = "" if v is None else (f"{v:.2f}" if col == "篇均被引频次" else str(v))
            n += 1
            if cell.strip() != want:
                bad.append(("T19", f"{cn}·{col}", f"报告 {cell!r} ≠ 源 {want!r}",
                            it.get("src", "（无）")))
            elif v is None:
                empty.append(f"{cn}·{col}")
    if empty:
        cols = sorted({e.split("·")[1] for e in empty})
        notes.append(("T19", f"{len(empty)} 格源端无数据（{len(empty) // max(len(cols), 1)} 校 × {len(cols)} 列）",
                      f"ESI 机构总表缺这些列：{'、'.join(cols)} —— 该期导出格式所限，非漏填",
                      "（202603 起 ESI 才提供 Highly Cited / Hot Papers 两列）"))
    return n, bad, notes


def verify_matrix(tbl, mat):
    """T20：逐格比对 + **行名归一后必须 22 学科全命中**（守整行静默留空）。"""
    bad, notes, n = [], [], 0
    if not mat:
        return 0, [("T20", "—", "缺 matrix.json（该期未生成矩阵表）", "")], []
    shorts = [c.strip() for c in tbl[0][1:12]]
    empty = []
    for r in tbl[1:]:
        raw = (r[0] or "").strip()
        cn = PL.norm_disc_cn(raw)
        rec = (mat.get("matrix") or {}).get(cn)
        if rec is None:
            bad.append(("T20", raw, "行名归一后仍查不到矩阵数据（整行会被静默留空）",
                        f"归一为 {cn!r}"))
            n += len(shorts)
            continue
        for short, cell in zip(shorts, r[1:12]):
            it = rec.get(short) or {}
            want = it.get("v") or ""
            n += 1
            if cell.strip() != want:
                bad.append(("T20", f"{cn}·{short}", f"报告 {cell!r} ≠ 源 {want!r}",
                            it.get("src", "（无）")))
            elif not want:
                empty.append(f"{cn}·{short}")
    if empty:
        notes.append(("T20", f"{len(empty)} 格空",
                      "该期 InCites 快照里查不到这些校/学科的组合（源端无数据，非漏填）。"
                      "另一种口径是按 0.00% 显示，写哪种要馆员定",
                      "；".join(empty[:6]) + ("…" if len(empty) > 6 else "")))
    return n, bad, notes


def verify_top_papers(tbl, book, period, big_tbl):
    """表22：序号连续 / 被引不增 / 与台账合计一致 / 分学科计数 = 大表该列。

    返回 `(行数, 错误, 提示)`。

    🔴 与台账对账这一档**要看清单是不是本期的**：顶尖论文清单历来是台账外人工贴入，
       复现历史期次时沿用母版清单（不随期重出）→ 与当期台账合计本就不同。
       判据用「行数是否等于台账合计」：相等＝清单就是本期的，强校验（报错）；
       不等＝清单不是本期的，降级为提示，别让人把「没重出」当成「数据错」。
    """
    errs, notes = [], []
    rows = tbl[1:]
    seq, prev_c = [], 10 ** 9
    for k, r in enumerate(rows, start=1):
        no = (r[0] or "").strip()
        if not re.fullmatch(r"\d+", no):
            errs.append(("表22", f"第{k}行", f"序号非数字 {no!r}", ""))
            continue
        seq.append(int(no))
        try:
            ci = int((r[2] or "").strip())
            if ci > prev_c:
                errs.append(("表22", f"序号 {no}", f"被引 {ci} > 上一行 {prev_c}（应降序）", ""))
            prev_c = ci
        except ValueError:
            errs.append(("表22", f"序号 {no}", f"被引非数字 {(r[2] or '')!r}", ""))
    if seq and seq != list(range(1, len(seq) + 1)):
        errs.append(("表22", "序号列", f"不连续：{seq[0]}..{seq[-1]} 共 {len(seq)} 行", ""))
    # 台账合计
    sh = "TOP论文"
    r_tot = next((i for i, r in enumerate(book.sheets[sh])
                  if r and str(r[0] or "").strip().startswith(
                      ("TOP论文合计", "高被引论文合计"))), None)
    c = book.col_of(sh, period, norm=top_norm)
    tot, loc = book.at(sh, r_tot, c)
    is_current = tot is not None and int(tot) == len(rows)
    if tot is not None and not is_current:
        notes.append(("表22", f"{len(rows)} 行 vs 台账 {period} 合计 {int(tot)}",
                      "清单非本期（台账外人工贴入，复现稿沿用母版清单，不随期重出）", loc))
    # 分学科计数 = 大表「顶尖论文」列（仅当清单是本期的才有意义）
    up2cn = {k.upper(): v for k, v in PL.DISCIPLINES_CN.items()}
    cnt = {}
    for r in rows:
        d = (r[3] or "").strip().upper()
        cnt[d] = cnt.get(d, 0) + 1
    ledger_top = {}
    for r in big_tbl[1:]:
        v = (r[9] or "").strip()
        ledger_top[(r[0] or "").strip()] = int(v) if v else 0
    bucket = errs if is_current else notes
    dissent = [(up2cn.get(d, d), k, ledger_top.get(up2cn.get(d), 0))
               for d, k in cnt.items() if up2cn.get(d) and k != ledger_top.get(up2cn.get(d), 0)]
    if is_current:
        for cn, k, led in dissent:
            bucket.append(("表22", f"分学科计数·{cn}", f"清单 {k} ≠ 大表 {led}", ""))
    elif dissent:
        # 非本期清单的差异**合并成一条**：同一个原因刷十几条会把真正的错误淹掉。
        worst = sorted(dissent, key=lambda x: -abs(x[1] - x[2]))[:3]
        bucket.append(("表22", f"分学科计数有 {len(dissent)} 个学科不符",
                       "同上：清单非本期，与本期大表本就不同（非数据错）",
                       "；".join(f"{c} 清单{k}/大表{led}" for c, k, led in worst) + "…"))
    return len(rows), errs, notes


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description="报告逐格核验（回读原始源）")
    ap.add_argument("period")
    ap.add_argument("--docx", default=None)
    ap.add_argument("--ledger", default=str(LEDGER))
    a = ap.parse_args()

    period = a.period
    docx = pathlib.Path(a.docx) if a.docx else None
    if docx is None:
        cands = (sorted(glob.glob(str(REPO / "out" / period / DOCX_RE.format(period=period))))
                 or sorted(glob.glob(str(REPO / "out" / f"{period}_复现" /
                                       DOCX_RE.format(period=period)))))
        if not cands:
            raise SystemExit(f"[拒绝] 找不到 {period} 的报告初稿，请用 --docx 指定")
        docx = pathlib.Path(cands[0])

    print(f"报告：{docx.relative_to(REPO)}")
    print(f"台账：{a.ledger}")
    tbls, _ = read_docx(docx)
    book = Book(a.ledger)

    # 上期 = 台账里比当期小的最后一个有效期次
    tc = book.sheets["总被引"]
    filled = [str(h).strip() for h in tc[0][1:] if h is not None and str(h).strip()]
    prev = [p for p in filled if p < period][-1]

    def load(p):
        f = REPO / "out" / period / p
        if not f.is_file():
            f = REPO / "out" / f"{period}_复现" / p
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None

    results, all_bad, all_notes = [], [], []
    for label, fn in [("T01 大表", lambda: (*verify_big_table(book, tbls[1], period, prev), [])),
                      ("T19 省域表", lambda: verify_province(tbls[19], load("province.json"))),
                      ("T20 矩阵表", lambda: verify_matrix(tbls[20], load("matrix.json"))),
                      ("表22 清单", lambda: verify_top_papers(tbls[21], book, period, tbls[1]))]:
        cnt, bad, notes = fn()
        results.append((label, cnt, bad))
        all_bad += bad
        all_notes += notes

    print()
    unit = {"T01 大表": "格", "T19 省域表": "格", "T20 矩阵表": "格", "表22 清单": "行"}
    for label, cnt, bad in results:
        flag = "✓" if not bad else "★"
        print(f"  {flag} {label:12s} 核验 {cnt:>4} {unit[label]}  不符 {len(bad)}")
    if all_bad:
        print(f"\n=== 差异明细（{len(all_bad)} 条）===")
        for area, who, msg, loc in all_bad:
            print(f"  [{area}] {who}: {msg}\n        源：{loc}")
    if all_notes:
        print(f"\n=== 提示（{len(all_notes)} 条，非缺陷）===")
        for area, who, msg, loc in all_notes:
            print(f"  [{area}] {who}: {msg}\n        {loc}")
    if not all_bad:
        print("\n全部逐格回读一致。")
    return 1 if all_bad else 0


if __name__ == "__main__":
    sys.exit(main())
