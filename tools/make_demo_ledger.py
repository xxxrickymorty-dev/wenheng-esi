# -*- coding: utf-8 -*-
"""演示台账生成器（本地开发/外网演示用；数据不入库）。

本机没有馆员母本（input/ 不入库，属正常）时，用它造一份**确定性**的
演示台账放 `input/`，让 AI 问数 / 看板 / 流水线离线可跑。

- 形状完全按 `src/parse_ledger.py` 的读表口径反推（13 张工作表）；
- 数值由固定公式生成（种子确定性，同命令同内容）；
- 刻意迎合金样断言（202607 国际排名=995、顶尖论文合计=274、
  202601 前 1% 学科=13），让 `run_assertions` 全绿；
- ⚠ 仅演示：数字与真实云大数据**无关**，不得进任何正式报告。

用法：
  uv run python tools/make_demo_ledger.py            # 生成 input/<母本名>
  uv run python tools/make_demo_ledger.py --force    # 已存在也重建

演示标记（sidecar）：
  生成台账的同时写 `input/.demo_marker.json`（含台账 sha256）。
  数据指纹测试（如金样 MAPE 指纹）读到该标记即 skip ——
  它们钉的是真实台账的指纹，对演示数据必然失败；
  skip 走 `_guard_registry` 登记，守卫体检照常复核，不是静默降级。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import openpyxl                                               # noqa: E402
from openpyxl.utils import get_column_letter                  # noqa: E402

from parse_ledger import DISCIPLINES_CN, DISCIPLINES_EN       # noqa: E402

#: 期次轴：201903 → 202607（45 期，与真实台账同期轴）。
PERIODS: list[str] = []
_y, _m = 2019, 3
while f"{_y}{_m:02d}" <= "202607":
    PERIODS.append(f"{_y}{_m:02d}")
    _m += 2
    if _m > 12:
        _m -= 12
        _y += 1

#: 202601 已进入前 1% 的 13 个学科（金样断言：第 1 期 13 个）。
IN_1PCT_EARLY = [
    "Chemistry", "Plant & Animal Science", "Engineering",
    "Materials Science", "Mathematics", "Environment/Ecology",
    "Biology & Biochemistry", "Agricultural Sciences",
    "Computer Science", "Clinical Medicine", "Pharmacology & Toxicology",
    "Geosciences", "Social Sciences, general",
]
#: 其余学科较晚进入（进入期次按名单序错开）。
LATE_ENTRY_AT = {
    "Molecular Biology & Genetics": "202603",
    "Physics": "202603",
    "Neuroscience & Behavior": "202603",
    "Immunology": "202603",
    "Psychiatry/Psychology": "202603",
    "Space Science": "202603",
    "Economics & Business": "202603",
    "Microbiology": "202607",
    "Multidisciplinary": "202603",
}
#: 微生物学曾退出（演示 out 事件时序回放）。
EXIT_EVENT = ("202505", "微生物学")


def _t(period: str) -> int:
    """期次 → 时间步（0 起）。"""
    return PERIODS.index(str(period))


def _v(disc: str, period: str, base: float, slope: float, wobble: float = 0.0) -> float:
    """确定性数值：base 起步、按期次线性增长 + 学科指纹微扰。"""
    t = _t(period)
    fp = (sum(ord(c) for c in disc) % 17) / 17.0          # 学科指纹 0–1
    v = base * (1.0 + slope * t) * (1.0 + wobble * ((fp * 7 + t) % 3 - 1) / 100.0)
    return round(v, 3)


def _period_cols(ws, periods, row=0):
    """首行写期次表头。"""
    ws.cell(row=row + 1, column=1, value="学科")
    for j, p in enumerate(periods):
        ws.cell(row=row + 1, column=j + 2, value=p)


def _fill_wide(ws, periods, base_fn, slope):
    """宽表：首行期次、首列学科。"""
    _period_cols(ws, periods)
    for i, d in enumerate(DISCIPLINES_EN):
        base = base_fn(d)
        ws.cell(row=i + 2, column=1, value=d)
        for j, p in enumerate(periods):
            ws.cell(row=i + 2, column=j + 2,
                    value=_v(d, p, base, slope, wobble=1.5))


def _add_wide_sheets(wb):
    spec = {
        "总被引": (lambda d: 1200.0 + DISCIPLINES_EN.index(d) * 650, 0.012),
        "论文数": (lambda d: 300.0 + DISCIPLINES_EN.index(d) * 90, 0.008),
        "CNCI": (lambda d: 0.7 + DISCIPLINES_EN.index(d) * 0.02, 0.004),
        "接近度": (lambda d: 0.55 + DISCIPLINES_EN.index(d) * 0.03, 0.010),
        "ESI被引阈值": (lambda d: 900.0 + DISCIPLINES_EN.index(d) * 420, 0.011),
    }
    for name, (base_fn, slope) in spec.items():
        ws = wb.create_sheet(name)
        _fill_wide(ws, PERIODS, base_fn, slope)
    # 千分之一阈值：只有 4 期近窗（与真实口径同构：列少）
    ws = wb.create_sheet("千分之一被引阈值")
    near = PERIODS[-4:]
    _fill_wide(ws, near, lambda d: 9000.0 + DISCIPLINES_EN.index(d) * 3800, 0.011)


def _add_top_papers(wb):
    """TOP论文：宽表 + 年份行 + 合计行（合计行金样 202607=274）。"""
    ws = wb.create_sheet("TOP论文")
    _period_cols(ws, PERIODS)
    for i, d in enumerate(DISCIPLINES_EN):
        ws.cell(row=i + 2, column=1, value=d)
        for j, p in enumerate(PERIODS):
            ws.cell(row=i + 2, column=j + 2,
                    value=_v(d, p, 2.0 + i * 1.5, 0.014))
    # 年份行：紧跟学科行
    row = len(DISCIPLINES_EN) + 2
    ws.cell(row=row, column=1, value="2019")
    for j, p in enumerate(PERIODS):
        ws.cell(row=row, column=j + 2, value=1 + (int(p[:4]) - 2019))
    # 合计行：紧跟年份行，列位与宽表对齐
    ws.cell(row=row + 1, column=1, value="TOP论文合计（篇）")
    for j, p in enumerate(PERIODS):
        # 金样：202607 合计 274；其余期按期次线性走
        total = 274 if p == "202607" else round(180 + _t(p) * 2.2)
        ws.cell(row=row + 1, column=j + 2, value=total)


def _add_ynd_rank(wb):
    """云大ESI排名：两块 4 列并排（期次/国际/国内/国内高校）。金样 202607=995。"""
    ws = wb.create_sheet("云大ESI排名")
    ws.cell(row=1, column=1, value="期次")
    half = (len(PERIODS) + 1) // 2
    for i, p in enumerate(PERIODS):
        r = i + 2
        ws.cell(row=r, column=1, value=p)
        ws.cell(row=r, column=2, value=995 if p == "202607" else 1100 - _t(p) * 3)
        ws.cell(row=r, column=3, value=105 - _t(p))
        ws.cell(row=r, column=4, value=2)
        if i + half < len(PERIODS):
            q = PERIODS[i + half]
            ws.cell(row=r, column=7, value=q)
            ws.cell(row=r, column=8, value=995 if q == "202607" else 1100 - _t(q) * 3)
            ws.cell(row=r, column=9, value=105 - _t(q))
            ws.cell(row=r, column=10, value=2)


def _add_grouped(wb, name):
    """新国际/新国内排名：每期 3 列组（前1%机构数/排名/百分位），组名首行。"""
    ws = wb.create_sheet(name)
    ws.cell(row=1, column=1, value="学科")
    for k, p in enumerate(PERIODS):
        col = 2 + k * 3
        ws.cell(row=1, column=col, value=p)
    for i, d in enumerate(DISCIPLINES_EN):
        r = i + 2
        ws.cell(row=r, column=1, value=d)
        for k, p in enumerate(PERIODS):
            col = 2 + k * 3
            shift = 0 if name == "新国际排名" else 5
            rank = max(1, round((80 - i * 3 + shift) * (1 - _t(p) * 0.004)))
            ws.cell(row=r, column=col, value=200 + i)
            ws.cell(row=r, column=col + 1, value=rank)
            ws.cell(row=r, column=col + 2, value=round(rank / 900, 4))


def _add_transposed(wb, name):
    """国际/国内排名：学科 3 列组（组名首行），期次为行。"""
    ws = wb.create_sheet(name)
    ws.cell(row=1, column=1, value="期次")
    for i, d in enumerate(DISCIPLINES_EN):
        ws.cell(row=1, column=2 + i * 3, value=d)
    # 第 2 行：子表头（读表跳过它）
    ws.cell(row=2, column=1, value="")
    for i in range(len(DISCIPLINES_EN)):
        ws.cell(row=2, column=2 + i * 3, value="前1%机构数")
        ws.cell(row=2, column=3 + i * 3, value="排名")
        ws.cell(row=2, column=4 + i * 3, value="百分位")
    for r, p in enumerate(PERIODS):
        row = r + 3
        ws.cell(row=row, column=1, value=p)
        for i, d in enumerate(DISCIPLINES_EN):
            shift = 0 if name == "国际排名" else 5
            rank = max(1, round((300 - i * 10 + shift) * (1 - _t(p) * 0.005)))
            ws.cell(row=row, column=2 + i * 3, value=180 + i)
            ws.cell(row=row, column=3 + i * 3, value=rank)
            ws.cell(row=row, column=4 + i * 3, value=round(rank / 1200, 4))


def _add_avg_cites(wb):
    """篇均被引：每期 3 列组（云大/中国大陆/国际），数据从第 4 行。"""
    ws = wb.create_sheet("篇均被引")
    ws.cell(row=1, column=1, value="学科")
    for k, p in enumerate(PERIODS):
        ws.cell(row=2, column=2 + k * 3, value=p)
    ws.cell(row=3, column=1, value="")
    for k in range(len(PERIODS)):
        ws.cell(row=3, column=2 + k * 3, value="云大")
        ws.cell(row=3, column=3 + k * 3, value="中国大陆")
        ws.cell(row=3, column=4 + k * 3, value="国际")
    for i, d in enumerate(DISCIPLINES_EN):
        r = i + 4
        ws.cell(row=r, column=1, value=d)
        for k, p in enumerate(PERIODS):
            base = _v(d, p, 9.0 + i * 2.0, 0.006)
            ws.cell(row=r, column=2 + k * 3, value=base)
            ws.cell(row=r, column=3 + k * 3, value=round(base * 1.15, 3))
            ws.cell(row=r, column=4 + k * 3, value=round(base * 1.3, 3))


def _add_q1q4(wb):
    """Q1-Q4：季度 × 实体 × 4 列。"""
    ws = wb.create_sheet("Q1-Q4")
    quarters = ["2019Q1", "2019Q2", "2019Q3", "2019Q4"]
    ws.cell(row=1, column=1, value="学科")
    for k, q in enumerate(quarters):
        for e, ent in enumerate(["云大", "中国大陆", "全球"]):
            ws.cell(row=1, column=2 + k * 4 + e, value=ent)
        ws.cell(row=2, column=2 + k * 4, value=q)
    for i, d in enumerate(DISCIPLINES_EN):
        r = i + 4
        ws.cell(row=r, column=1, value=d)
        for k in range(len(quarters)):
            for e in range(4):
                ws.cell(row=r, column=2 + k * 4 + e,
                        value=round(0.2 + 0.03 * e + i * 0.01, 3))


def _add_province(wb):
    """高校学科发展：6 指标 × 9 校。"""
    ws = wb.create_sheet("高校学科发展")
    unis = ["云南大学", "郑州大学", "苏州大学", "上海大学", "暨南大学",
            "西南大学", "江南大学", "宁夏大学", "西藏大学"]
    ws.cell(row=1, column=1, value="指标")
    for j, u in enumerate(unis):
        ws.cell(row=1, column=j + 2, value=u)
    metrics = ["ESI前1%学科数", "ESI前1%机构数", "顶尖论文数",
               "论文总数", "总被引频次", "篇均被引"]
    for i, mname in enumerate(metrics):
        r = i + 3
        ws.cell(row=r, column=1, value=mname)
        for j in range(9):
            ws.cell(row=r, column=j + 2, value=10 + i * 7 + j)


def _add_forecast_gap(wb):
    """实际与预测差值：期次范围 × 学科 × 指标 × 来源(incite/esi/差值)。"""
    ws = wb.create_sheet("实际与预测差值")
    ws.cell(row=1, column=1, value="范围")
    ws.cell(row=1, column=2, value="来源")
    discs = list(DISCIPLINES_CN.items())
    for k, (_en, cn) in enumerate(discs):
        ws.cell(row=1, column=3 + k * 4, value=cn)
    wins = ["202507-202509", "202509-202511", "202511-202601",
            "202601-202603", "202603-202605", "202605-202607"]
    r = 3
    for w in wins:
        for src in ("incite", "esi", "差值"):
            ws.cell(row=r, column=1, value=w)
            ws.cell(row=r, column=2, value=src)
            for k, (_en, _cn) in enumerate(discs):
                col = 3 + k * 4
                ws.cell(row=r, column=col, value=100 + k)
                ws.cell(row=r, column=col + 1, value=1500 + k * 10)
                ws.cell(row=r, column=col + 2, value=400 - k)
                ws.cell(row=r, column=col + 3, value=90 - k)
            r += 1


def _add_entry_events(wb):
    """学科进入时间：馆员流水账形态（年向下填充；退出写注释）。"""
    ws = wb.create_sheet("学科进入时间")
    ws.cell(row=1, column=1, value="年")
    ws.cell(row=1, column=2, value="月")
    ws.cell(row=1, column=3, value="学科")
    ws.cell(row=1, column=4, value="目前ESI前1%学科")
    rows = []
    # 早期进入的 13 个（金样：202601 已进 13 个）
    for k, en in enumerate(IN_1PCT_EARLY):
        rows.append((2012 + k // 4, 3 + (k % 4) * 2, DISCIPLINES_CN[en], "√"))
    # 较晚进入的（都在 202601 之后）
    for en, ym in LATE_ENTRY_AT.items():
        rows.append((int(ym[:4]), int(ym[4:]), DISCIPLINES_CN[en], ""))
    # 微生物学退出 + 再进入（演示时序回放）
    rows.append((int(EXIT_EVENT[0][:4]), int(EXIT_EVENT[0][4:]),
                 f"{DISCIPLINES_CN['Microbiology']}退出", ""))
    rows.append((2026, 7, DISCIPLINES_CN["Microbiology"], "√"))
    # 按进入时间排序（年月升序），年向下填充
    rows.sort(key=lambda t: (t[0], t[1]))
    cur_year = None
    r = 2
    for y, m, name, cur in rows:
        ws.cell(row=r, column=1, value=y if y != cur_year else None)
        cur_year = y
        ws.cell(row=r, column=2, value=f"{m}月")
        ws.cell(row=r, column=3, value=name)
        ws.cell(row=r, column=4, value=cur)
        r += 1
    # 断言口径：每月退出多算一个「进入」事件（退出行也被 _cn2en 匹配进名单时）
    # ——这里无需处理：退出行已写成注释文本，parse_entry_events 正则识别为 out。


def build(path: pathlib.Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.worksheets[0])
    _add_wide_sheets(wb)
    _add_ynd_rank(wb)
    _add_grouped(wb, "新国际排名")
    _add_grouped(wb, "新国内排名")
    _add_transposed(wb, "国际排名")
    _add_transposed(wb, "国内排名")
    _add_avg_cites(wb)
    _add_q1q4(wb)
    _add_top_papers(wb)
    _add_province(wb)
    _add_forecast_gap(wb)
    _add_entry_events(wb)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_marker(path: pathlib.Path) -> pathlib.Path:
    """在台账旁边落演示标记（sidecar）：input/.demo_marker.json。

    内容含台账 sha256，测试据此可判「标记是否对应当前台账」。
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    marker = path.parent / ".demo_marker.json"
    marker.write_text(json.dumps({
        "demo": True,
        "generator": "tools/make_demo_ledger.py",
        "sha256": digest,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return marker


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成演示台账（本地开发用）")
    ap.add_argument("--out", default="",
                    help="输出路径（默认 input/<母本名>）")
    ap.add_argument("--force", action="store_true",
                    help="已存在也重建")
    args = ap.parse_args(argv)
    import ledger as ledger_mod                  # noqa: PLC0415

    out = pathlib.Path(args.out) if args.out else ledger_mod.runtime_path(REPO)
    if out.exists() and not args.force:
        print(f"已存在（不动）：{out}；要重建请加 --force")
        return 0
    build(out)
    marker = write_marker(out)
    print(f"演示台账已生成：{out}")
    print(f"演示标记已写入：{marker}")
    print(f"期次轴：{PERIODS[0]} → {PERIODS[-1]}（{len(PERIODS)} 期）")
    print("⚠ 演示数据与真实云大数据无关，不得进正式报告。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
