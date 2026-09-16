# -*- coding: utf-8 -*-
"""台账期次覆盖自检（只读，不 save）。

回答"这套流水线现在能用哪些期次的数据、还缺哪些期次"——每期取数前先跑一次。

用法（workdir=wenheng）：
    .venv\\Scripts\\python.exe tools\\ledger_coverage.py [台账路径]

默认台账 = ..\\数据与复现\\云大全学科排名、阈值动态检测表.xlsx（唯一事实源）。

输出四类信号：
    1. 各页有数据的期次区间与期数（只填表头没填数的"空列"单独标出）
    2. 期数 ≤ 12 的页给出逐期明细；每页再给**末 3 期行数**
       （行数为 1 的"末列"往往是批注/子表头残留，不是真数据）
    3. **期内空洞**：在整个双月期次网格内、该页连表头/首列都没有的期次。
       当前台账此信号为空（无真空洞）。注意别被「期次标签格式不统一」骗出假空洞：
       TOP论文有 3 列写成浮点 `2023.01`／`2023.3`／`2023.5`，其余是整数 `202307`；
       归一化不够宽就会误报成「缺 3 期列」（本工具第一版即如此误报过一次）。
    4. **水位线异常**：以各页最末有数据期次的众数为"水位线"，某页**抢跑**
       （比水位线多一期）或**落后**（比水位线少）都会标出。
       注意 CNCI 来自 InCites、比 ESI 提前一个月，天然会高于水位线，属正常。

期次标签识别：兼容 `202601` 与 `2025.01` 两种写法；表头**不必在第 1 行**
（在前 6 行里挑期次标签最多的那行，故 `篇均被引` 这类第 1 行是批注的表也能认）。
认不出期次但确实有内容的页，会打印行数/非空格数与首行样本，避免误判成"空表"。

⚠ 读输出时别把「末端空列」当缺口：台账习惯**提前建好下一期的表头列**，
   而下一期 ESI 数据集往往还没发布（当期 202609 即如此）。那是占位列，不是缺数。
   判断"缺"要看：**已发布期次内部**有没有空值 / 有没有整列空洞。
退出码：0=正常，2=台账读不到。仅只读，绝不写台账。
"""
import re
import sys
from collections import Counter
from datetime import date

import openpyxl

DEFAULT = r"..\数据与复现\云大全学科排名、阈值动态检测表.xlsx"
YM = re.compile(r"^20\d{4}$")
Y_M = re.compile(r"^(20\d{2})[.\-/](\d{1,2})$")
SHORT = 12  # 期数不超过此值时打印逐期明细
HEAD_SCAN = 6  # 在前几行里找期次表头行
PERIOD_MONTHS = (1, 3, 5, 7, 9, 11)  # 双月期次：第 N 期 = 2N−1 月


def norm_period(v):
    """把 202601 / 2025.01 / 2025-1 归一成 'YYYYMM'；否则 None。"""
    if v is None:
        return None
    s = str(v).strip()
    if YM.fullmatch(s):
        mm = int(s[4:])
        return s if 1 <= mm <= 12 else None
    m = Y_M.fullmatch(s)
    if m:
        mm = int(m.group(2))
        return f"{m.group(1)}{mm:02d}" if 1 <= mm <= 12 else None
    return None


def grid(start_year=2019, end=None):
    """项目双月期次全集，例：201903, 201905, ... 202609。"""
    end = end or date.today()
    return [f"{y}{m:02d}" for y in range(start_year, end.year + 1) for m in PERIOD_MONTHS
            if f"{y}{m:02d}" <= f"{end.year}{end.month:02d}"]


def _count_col(rows, header_i, col_i):
    return sum(1 for r in rows[header_i + 1:]
               if col_i < len(r) and r[col_i] is not None and str(r[col_i]).strip() != "")


def find_periods(rows):
    """返回 {期次: 非空数据格数}。先找期次表头行（前 6 行里标签最多的），再补扫首列。"""
    hit = {}
    if not rows:
        return hit
    # 1) 选期次表头行
    best_i, best_labels = None, {}
    for i, r in enumerate(rows[:HEAD_SCAN]):
        labels = {}
        for j, c in enumerate(r):
            p = norm_period(c)
            if p:
                labels.setdefault(p, j)
        if len(labels) > len(best_labels):
            best_i, best_labels = i, labels
    if best_i is not None and len(best_labels) >= 2:
        for p, j in best_labels.items():
            hit[p] = max(hit.get(p, 0), _count_col(rows, best_i, j))
    # 2) 首列期次（云大ESI排名这类按期竖排的表）
    for r in rows:
        if not r:
            continue
        p = norm_period(r[0])
        if not p:
            continue
        cnt = sum(1 for c in r[1:] if c is not None and str(c).strip() != "")
        hit[p] = max(hit.get(p, 0), cnt)
    return hit


def _brief(ws):
    """认不出期次时的兜底摘要：行数 / 非空格 / 首行样本。"""
    rows = list(ws.iter_rows(values_only=True))
    ne = sum(1 for r in rows for c in r if c is not None and str(c).strip() != "")
    sample = ""
    for r in rows[:3]:
        cells = [str(c) for c in r if c is not None and str(c).strip() != ""]
        if cells:
            sample = "｜".join(cells)[:70]
            break
    return len(rows), ne, sample


def main(path=DEFAULT):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    # 先收一遍：算"水位线"——各页最末「有数据」期次的众数
    info = []
    for name in wb.sheetnames:
        ws = wb[name]
        try:
            hit = find_periods(list(ws.iter_rows(values_only=True)))
        except Exception as e:  # noqa: BLE001
            info.append((name, None, None, str(e)))
            continue
        if hit and any(c > 0 for c in hit.values()):
            info.append((name, hit, None, None))
        else:
            try:
                info.append((name, None, _brief(ws), None))
            except Exception as e:  # noqa: BLE001
                info.append((name, None, None, str(e)))
    wb.close()

    allp = grid()
    lasts = [max(p for p, c in h.items() if c > 0) for _, h, _, _ in info if h]
    level = Counter(lasts).most_common(1)[0][0] if lasts else None

    print(f"台账：{path}")
    print(f"期次网格：{allp[0]} → {allp[-1]}（双月，共 {len(allp)} 期）")
    if level:
        print(f"水位线（各页最末有数据期次的众数）：{level}")
    print()
    print(f"{'页名':<20}{'期数':>4}  {'区间':<19}说明")
    print("-" * 92)
    for name, hit, brief, err in info:
        if err:
            print(f"{name:<20}{'--':>4}  读取失败：{err}")
            continue
        if not hit:
            rows_ct, ne, sample = brief
            print(f"{name:<20}{'-':>4}  未识别期次（行={rows_ct} 非空格={ne}）")
            if sample:
                print(f"{'':<20}     首行样本：{sample}")
            continue
        filled = sorted(p for p, c in hit.items() if c > 0)
        empty = sorted(p for p, c in hit.items() if c == 0)
        if not filled:
            print(f"{name:<20}{0:>4}  ⚠ 有期次标签但全空")
            continue
        print(f"{name:<20}{len(filled):>4}  {filled[0]} → {filled[-1]}")
        if len(filled) <= SHORT:
            print(f"{'':<20}     明细：" + " ".join(f"{p}({hit[p]})" for p in filled))
        print(f"{'':<20}     末 3 期行数：" + " ".join(f"{p}({hit[p]})" for p in filled[-3:]))
        if empty:
            print(f"{'':<20}     ⚠ 有表头但空列：" + " ".join(empty))
        holes = [p for p in allp if filled[0] <= p <= filled[-1] and p not in filled and p not in empty]
        if holes:
            print(f"{'':<20}     ⚠ 期内空洞（连列都没有）：" + " ".join(holes))
        if level and filled[-1] > level:
            print(f"{'':<20}     ⚠ 高于水位线 {level}：InCites 口径页（如 CNCI，提前一月）属正常；"
                  f"其他页须核实来源")
        elif level and filled[-1] < level:
            print(f"{'':<20}     ⚠ 落后水位线 {level}：只到 {filled[-1]} —— 是否漏录？")
    print()
    print("注：末端「有表头但空列」通常是**下一期尚未发布**（台账提前建列），不是缺数；")
    print("    判定缺数请看已发布期次内的空值 / 整列空洞。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
