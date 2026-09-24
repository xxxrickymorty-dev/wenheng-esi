# -*- coding: utf-8 -*-
"""顶尖论文「学院统计」：读馆员的《<期次>论文清单.xlsx》→ 每学院发文量/被引频次。

清单由来（馆员每期提供）：列 = 序号 | WOS收录号 | 被引频次 | ESI学科 | 出版年 | 云大作者 |
热点论文/研究前沿；「云大作者」形如 `Zhu, Lei//生命科学学院` 或 `Chen, Wen/通讯作者/地球科学学院`
（单双斜杠混用）→ 取最后一段为学院/机构。

产物：`out/<期次>/college_stats.json`（charts 与 fill_docx 共用）。
"""
from __future__ import annotations

import json
import pathlib
import re
from collections import Counter

import openpyxl

CAND_DIRS = ("input/{period}", "../数据与复现", "out/{period}", "{ledger_dir}")

#: 学院/机构名归一（同一机构的清单写法可能不同）。
#: 2026-09 实测：清单里 `天文研究所`（5 篇/617 引）与 `中国（西南）天文研究所`（1 篇/8 引）
#: 各占一行 → 报告出现两行；**出版件第 7 页是合并成一行 6 篇/625 引**（对照模板发现）。
UNIT_ALIAS = {
    "天文研究所": "中国（西南）天文研究所",
}

#: 解析器版本：改动 `parse()` 的口径（别名表、取段规则…）就 +1 ——
#: 缓存 `college_stats.json` 版本不匹配会**重新解析**，避免"改了规则但旧缓存照用"
#: （2026-09-24 实测踩过：加了别名，报告里天文所仍是两行）。
_PARSER_VERSION = 2


def find_list(ledger_dir: pathlib.Path, period: str) -> pathlib.Path | None:
    """按优先级找清单：input/<期次>/ → ../数据与复现/ → out/<期次>/。"""
    for d in (pathlib.Path("input") / period, pathlib.Path("..") / "数据与复现",
              pathlib.Path(ledger_dir), pathlib.Path(ledger_dir).parent / period):
        if not d.is_dir():
            continue
        hits = sorted(q for q in d.glob("*论文清单*.xlsx") if not q.name.startswith("~$"))
        if hits:
            return hits[0]
    return None


def parse(path: pathlib.Path) -> dict:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr = [str(c).strip() if c is not None else "" for c in rows[0]]
    ia = next(i for i, h in enumerate(hdr) if "作者" in h)
    ic = next(i for i, h in enumerate(hdr) if "被引频次" in h)
    ie = next((i for i, h in enumerate(hdr) if "学科" in h), None)
    papers, cites = Counter(), Counter()
    no_unit = []
    for r in rows[1:]:
        if r is None or all(c is None for c in r):
            continue
        s = re.sub(r"\s+", "", str(r[ia] or ""))
        parts = [x for x in re.split(r"/+", s) if x]
        unit = parts[-1] if parts else ""
        unit = UNIT_ALIAS.get(unit, unit)
        if not unit:
            no_unit.append(str(r[ia])[:40])
        papers[unit] += 1
        try:
            cites[unit] += int(float(r[ic]))
        except (TypeError, ValueError):
            pass
    units = sorted(
        ({"unit": u, "papers": papers[u], "cites": cites[u]} for u in papers if u),
        key=lambda x: (-x["papers"], -x["cites"]))
    rows_out = [[("" if c is None else str(c)) for c in r[:7]]
                for r in rows[1:] if r and any(c is not None for c in r)]
    n_subjects = 0
    if ie is not None:
        n_subjects = len({re.sub(r"\s+", "", str(r[ie]))
                          for r in rows[1:] if r and r[ie] not in (None, "")})
    return {"parser": _PARSER_VERSION, "source": str(path), "units": units,
            "rows": rows_out, "header": hdr[:7],
            "n_papers": sum(papers.values()), "n_cites": sum(cites.values()),
            "n_units": len(units), "n_subjects": n_subjects, "no_unit": no_unit[:10]}


def load(ledger_dir: pathlib.Path, period: str, *, save: bool = False) -> dict | None:
    j = pathlib.Path(ledger_dir) / "college_stats.json"
    if j.exists():
        try:
            st = json.loads(j.read_text(encoding="utf-8"))
            if st.get("parser") == _PARSER_VERSION:
                return st
        except Exception:                                          # noqa: BLE001
            pass
    p = find_list(pathlib.Path(ledger_dir), period)
    if p is None:
        return None
    st = parse(p)
    if save:
        j.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    ld = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/202609")
    per = re.search(r"(\d{6})", ld.name)
    st = load(ld, per.group(1) if per else "", save=True)
    if st is None:
        raise SystemExit("没找到论文清单")
    print(f"清单 {st['source']}: {st['n_papers']} 篇 / {st['n_subjects']} 学科 / "
          f"{st['n_units']} 个学院机构 / 被引 {st['n_cites']}")
    for u in st["units"][:8]:
        print(f"   {u['unit']:24s} {u['papers']:>3} 篇  {u['cites']:>6} 次")
