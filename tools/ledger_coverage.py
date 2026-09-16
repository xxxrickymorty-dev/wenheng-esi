# -*- coding: utf-8 -*-
"""台账期次覆盖自检（只读，不 save）。

回答"这套流水线现在能用哪些期次的数据、还缺哪些期次"——每期取数前先跑一次。

用法（workdir=wenheng）：
    .venv\\Scripts\\python.exe tools\\ledger_coverage.py [台账路径]

默认台账 = ..\\数据与复现\\云大全学科排名、阈值动态检测表.xlsx（唯一事实源）。

输出三类信号：
    1. 各页有数据的期次区间与期数（只填表头没填数的"空列"单独标出）
    2. 期数 ≤ 12 的页给出逐期明细（看 1‰ 阈值这类短序列）
    3. **期内空洞**：在整个双月期次网格内、该页连表头/首列都没有的期次
       （例：TOP论文缺 2023 上半年整 3 期——不是空值，是整列不存在）
退出码：0=正常，2=台账读不到。仅只读，绝不写台账。
"""
import re
import sys
from datetime import date

import openpyxl

DEFAULT = r"..\数据与复现\云大全学科排名、阈值动态检测表.xlsx"
PAT = re.compile(r"20\d{4}")
SHORT = 12  # 期数不超过此值时打印逐期明细
PERIOD_MONTHS = (1, 3, 5, 7, 9, 11)  # 双月期次：第 N 期 = 2N−1 月


def grid(start_year=2019, end=None):
    """项目双月期次全集，例：201903, 201905, ... 202609。"""
    end = end or date.today()
    return [f"{y}{m:02d}" for y in range(start_year, end.year + 1) for m in PERIOD_MONTHS
            if f"{y}{m:02d}" <= f"{end.year}{end.month:02d}"]


def find_periods(rows):
    """返回 {期次: 非空数据格数}。表头首行与首列都扫（期次可能是文本或数字）。"""
    hit = {}
    if not rows:
        return hit

    def label(v):
        if v is None:
            return None
        s = str(v).strip()
        return s if PAT.fullmatch(s) else None

    for i, h in enumerate(rows[0]):
        p = label(h)
        if not p:
            continue
        cnt = sum(1 for r in rows[1:]
                  if i < len(r) and r[i] is not None and str(r[i]).strip() != "")
        hit[p] = max(hit.get(p, 0), cnt)

    for r in rows[1:]:
        if not r:
            continue
        p = label(r[0])
        if not p:
            continue
        cnt = sum(1 for c in r[1:] if c is not None and str(c).strip() != "")
        hit[p] = max(hit.get(p, 0), cnt)
    return hit


def main(path=DEFAULT):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    allp = grid()
    print(f"台账：{path}")
    print(f"期次网格：{allp[0]} → {allp[-1]}（双月，共 {len(allp)} 期）")
    print()
    print(f"{'页名':<20}{'期数':>4}  {'区间':<19}说明")
    print("-" * 92)
    for name in wb.sheetnames:
        try:
            rows = list(wb[name].iter_rows(values_only=True))
        except Exception as e:  # noqa: BLE001
            print(f"{name:<20}{'--':>4}  读取失败：{e}")
            continue
        hit = find_periods(rows)
        if not hit:
            print(f"{name:<20}{0:>4}  {'—':<19}(非按期间组织)")
            continue
        filled = sorted(p for p, c in hit.items() if c > 0)
        empty = sorted(p for p, c in hit.items() if c == 0)
        if not filled:
            print(f"{name:<20}{0:>4}  {'—':<19}⚠ 有期次标签但全空")
            continue
        span = f"{filled[0]} → {filled[-1]}"
        print(f"{name:<20}{len(filled):>4}  {span:<19}")
        if len(filled) <= SHORT:
            print(f"{'':<20}     明细：" + " ".join(f"{p}({hit[p]})" for p in filled))
        if empty:
            print(f"{'':<20}     ⚠ 有表头但空列：" + " ".join(empty))
        holes = [p for p in allp if filled[0] <= p <= filled[-1] and p not in filled and p not in empty]
        if holes:
            print(f"{'':<20}     ⚠ 期内空洞（连列都没有）：" + " ".join(holes))
    wb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
