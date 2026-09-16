# -*- coding: utf-8 -*-
"""台账期次覆盖自检（只读，不 save）。

回答"这套流水线现在能用哪些期次的数据、还缺哪些期次"——每期取数前先跑一次。

用法（workdir=wenheng）：
    .venv\\Scripts\\python.exe tools\\ledger_coverage.py [台账路径]

默认台账 = ..\\数据与复现\\云大全学科排名、阈值动态检测表.xlsx（唯一事实源）。

输出：
    - 各页有数据的期次区间与期数；只填了表头没填数的"空列"单独标出
    - 期数 ≤ 12 的页给出逐期明细（便于看 1‰ 阈值这类短序列）
退出码：0=正常。仅只读，绝不写台账。
"""
import re
import sys

import openpyxl

DEFAULT = r"..\数据与复现\云大全学科排名、阈值动态检测表.xlsx"
PAT = re.compile(r"20\d{4}")
SHORT = 12  # 期数不超过此值时打印逐期明细


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
    print(f"台账：{path}")
    print()
    print(f"{'页名':<22}{'期数':>4}  {'区间':<20}说明")
    print("-" * 88)
    for name in wb.sheetnames:
        try:
            rows = list(wb[name].iter_rows(values_only=True))
        except Exception as e:  # noqa: BLE001
            print(f"{name:<22}{'--':>4}  读取失败：{e}")
            continue
        hit = find_periods(rows)
        if not hit:
            print(f"{name:<22}{0:>4}  {'—':<20}(非按期间组织)")
            continue
        filled = sorted(p for p, c in hit.items() if c > 0)
        empty = sorted(p for p, c in hit.items() if c == 0)
        span = f"{filled[0]} → {filled[-1]}" if filled else "全部为空"
        print(f"{name:<22}{len(filled):>4}  {span:<20}")
        if len(filled) <= SHORT and filled:
            print(f"{'':<22}     明细：" + " ".join(f"{p}({hit[p]})" for p in filled))
        if empty:
            print(f"{'':<22}     ⚠ 有表头但空列：" + " ".join(empty))
    wb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
