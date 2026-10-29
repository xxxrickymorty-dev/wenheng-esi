# -*- coding: utf-8 -*-
"""「方法与边界说明」生成器：把产物里**已有的事实**拼成一段可放进报告的说明。

**只读工具，不进流水线、不重出报告、不写 `out/`。零 LLM、零新数字。**

三条硬规矩
────────────────────────────────────────────────────────────────
1. **固定骨架**：章节顺序写死在 `SECTIONS` 里，不随数据变化增删章节 ——
   否则「这期缺了一段」会被读成「这期没这个问题」。
2. **数字只从产物读**：`overview_facts.json` / `run_log.json` / `meta.json` /
   `forecast_*` / `red_slots.json` / `table2.csv` / `province.json` / `matrix.json`。
   文案里没有任何字面量数字（连「三个」都不写，写「T01/T19/T20」）。
3. **缺字段就写「（本期无该字段）」**，绝不猜一个填上。

列的性质（原值 / 派生值 / 预测值）不靠注释宣称，靠读产物判定：
    · T01 的列名来自 `table2.csv` 表头，按 `COLUMN_KIND` 分原值/派生
    · T19 的字段来自 `province.json`，每格自带 `src`（可回链到 ESI 机构总表）
    · T20 的格子来自 `matrix.json`，值形如「被引 ÷ 阈值 = 百分比」，是派生比值
    · 预测来自 `forecast_charts.json` + `forecast_backtest_summary.csv`，附回测 MAPE

用法：
    python tools/method_boundary.py                # 最新一期，打到 stdout
    python tools/method_boundary.py --period 202609
    python tools/method_boundary.py --period 202609 --out tmp/方法与边界_202609.md

退出码：0 正常；3 产物缺失 / 试图写进 out/。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "out"

#: 缺字段时的统一占位（**不许**换成编造值）
MISSING = "（本期无该字段）"

#: 章节骨架：顺序固定，标题固定
SECTIONS = ("数据来源与期次口径", "原始值 / 派生值 / 预测值", "未覆盖与源端缺失", "声明")

#: T01 列的三种性质。列名来自 table2.csv 表头；表里没有登记的列会单列「未登记列」，
#: 以便下次口径变化时立刻发现，而不是被静默算进原值。
COLUMN_KIND = {
    "discipline": "维度",
    "papers": "原值",
    "cnci": "原值",
    "total_cites": "原值",
    "thr_1pct": "原值",
    "thr_1permille": "原值",
    "top_papers": "原值",
    "rank_cn_change": "派生",
    "thr_1pct_gap": "派生",
    "permille_rank": "派生",
    "prox_change": "派生",
}

#: 判「这条红件其实是人工填的」的关键字（出现在 source 里）
MANUAL_MARKERS = ("人工", "手工")

#: 红色件清单.md 里手工槽小节的标题前缀
MANUAL_SECTION = "## 仍为手工的槽位"


# ---------------------------------------------------------------- 读产物
def _json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _csv_header(path: pathlib.Path) -> list[str]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return next(csv.reader(fh), [])
    except OSError:
        return []


def _csv_rows(path: pathlib.Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _manual_items(path: pathlib.Path) -> list[str]:
    """`红色件清单.md` 的「仍为手工的槽位」小节 → 条目列表。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    items, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line.startswith(MANUAL_SECTION)
            continue
        if inside and line.strip().startswith("- "):
            items.append(line.strip()[2:].strip())
    return items


def collect(period_dir: pathlib.Path) -> dict:
    """把一期能拿到的产物一次性读成 facts；缺的键就是 None / 空列表。"""
    meta = _json(period_dir / "meta.json") or {}
    slots = _json(period_dir / "red_slots.json") or []
    if isinstance(slots, dict):
        slots = slots.get("slots") or []
    slots = [x for x in slots if isinstance(x, dict)]

    province = _json(period_dir / "province.json") or {}
    universities = province.get("universities") if isinstance(province, dict) else None
    t19_fields = []
    if isinstance(universities, dict) and universities:
        first = next(iter(universities.values()))
        if isinstance(first, dict):
            t19_fields = [k for k in first if isinstance(first.get(k), dict)]

    matrix = _json(period_dir / "matrix.json") or {}
    matrix_rows = matrix.get("matrix") if isinstance(matrix, dict) else None

    return {
        "meta": meta,
        "run_log": _json(period_dir / "run_log.json") or {},
        "overview": _json(period_dir / "overview_facts.json") or {},
        "forecast_charts": _json(period_dir / "forecast_charts.json") or {},
        "backtest": _csv_rows(period_dir / "forecast_backtest_summary.csv"),
        "table2_cols": _csv_header(period_dir / "table2.csv"),
        "t19_fields": t19_fields,
        "t20_rows": len(matrix_rows) if isinstance(matrix_rows, dict) else None,
        "slots": slots,
        "manual": _manual_items(period_dir / "红色件清单.md"),
    }


# ---------------------------------------------------------------- 拼骨架
def _fmt(value, suffix: str = "") -> str:
    return f"{value}{suffix}" if value is not None and value != "" else MISSING


def _section_scope(period: str, f: dict) -> str:
    run_log, overview, meta = f["run_log"], f["overview"], f["meta"]
    prev = run_log.get("prev") or meta.get("period_prev")
    prev_label = overview.get("prev_label")
    window = overview.get("coverage_window")
    ledger = run_log.get("input") or meta.get("input")
    sha = str(run_log.get("ledger_sha256") or "")
    mutated = run_log.get("ledger_mutated")

    head = (f"本期期次码 {period}，上一期 {_fmt(prev)}"
            + (f"（产物记为「{prev_label}」）" if prev_label else "")
            + f"；ESI 数据覆盖区间 {_fmt(window)}。")
    ledger_line = f"台账：`{ledger}`" if ledger else f"台账路径{MISSING}"
    if sha:
        ledger_line += f"（sha256 前缀 `{sha[:12]}…`"
        ledger_line += "，本期未回写台账）" if mutated is False else "）"
    asserts = run_log.get("assertions_fail")
    checks = run_log.get("assertions_ok")
    if asserts is not None:
        ledger_line += f"；出稿时断言失败 {asserts} 条"
        ledger_line += "，全部通过。" if asserts == 0 else "。"
    elif checks is None:
        ledger_line += f"；出稿断言结果{MISSING}，无法据此判断是否全部通过。"
    return head + "\n\n" + ledger_line


def _section_values(f: dict) -> str:
    cols = f["table2_cols"]
    if not cols:
        t01 = f"T01 大表列名{MISSING}（缺 `table2.csv`）。"
    else:
        groups: dict[str, list[str]] = {}
        unregistered = []
        for c in cols:
            kind = COLUMN_KIND.get(c)
            if kind is None:
                unregistered.append(c)
                continue
            groups.setdefault(kind, []).append(c)
        parts = [f"T01 大表（`table2.csv` 表头，共 {len(cols)} 列，{len(groups.get('原值', []))} "
                 f"列为台账原值、{len(groups.get('派生', []))} 列为派生）："]
        for kind in ("原值", "派生", "维度"):
            if groups.get(kind):
                parts.append(f"  · {kind}：{'、'.join(groups[kind])}")
        if unregistered:
            parts.append(f"  · 未登记性质（需补 `COLUMN_KIND`）：{'、'.join(unregistered)}")
        t01 = "\n".join(parts)

    if f["t19_fields"]:
        t19 = (f"T19 省域表（`province.json`，{len(f['t19_fields'])} 个字段，每格自带 `src`，"
               f"逐格可回链到 ESI 机构总表）：{'、'.join(f['t19_fields'])}")
    else:
        t19 = f"T19 省域表字段{MISSING}（缺 `province.json`）。"

    if f["t20_rows"]:
        t20 = (f"T20 矩阵表（`matrix.json`，{f['t20_rows']} 行）：格子是"
               "「本校被引 ÷ 本期 1% 阈值」算出的比值，属**派生值**，不是台账原值；"
               "`Y` 表示该值已在 ESI 前 1% 榜内。")
    else:
        t20 = f"T20 矩阵表{MISSING}（缺 `matrix.json`）。"

    fc, bt = f["forecast_charts"], f["backtest"]
    charts = fc.get("charts") if isinstance(fc, dict) else None
    mapes = [c.get("rolling_mape") for c in (charts or [])
             if isinstance(c, dict) and isinstance(c.get("rolling_mape"), (int, float))]
    overall = f["run_log"].get("predict_mape_overall")
    fc_lines = []
    if isinstance(charts, list) and charts:
        horizon = fc.get("horizon")
        subjects = fc.get("report_subjects") or []
        subject_text = "、".join(subjects) if subjects else MISSING
        fc_lines.append(
            f"预测值（`forecast_charts.json`）：{len(charts)} 张预测图，外推 "
            f"{_fmt(horizon, ' 期')}，目标学科 {subject_text}。")
        if mapes:
            fc_lines.append(
                f"  · 逐图滚动 MAPE {min(mapes):.2f}% ~ {max(mapes):.2f}%"
                f"（中位 {sorted(mapes)[len(mapes) // 2]:.2f}%）。")
    else:
        fc_lines.append(f"预测值：{MISSING}（缺 `forecast_charts.json` 或无图）。")
    if overall is not None:
        fc_lines.append(f"  · 整体回测 MAPE {overall:g}%（`run_log.predict_mape_overall`）。")
    if bt:
        metrics = sorted({r.get("metric", "") for r in bt if r.get("metric")})
        summary = []
        for m in metrics:
            vals = [float(r["mean"]) for r in bt
                    if r.get("metric") == m and r.get("mean") not in (None, "")]
            if vals:
                summary.append(f"{m} {sum(vals) / len(vals):.2f}%")
        if summary:
            fc_lines.append(f"  · 分指标回测均值（`forecast_backtest_summary.csv`）："
                            f"{'、'.join(summary)}。")
    else:
        fc_lines.append(f"  · 分指标回测{MISSING}（缺 `forecast_backtest_summary.csv`）。")
    return "\n".join([t01, "", t19, "", t20, "", *fc_lines])


def _section_gaps(f: dict) -> str:
    run_log, meta = f["run_log"], f["meta"]
    miss_meta = meta.get("missing")
    miss_log = run_log.get("missing")
    lines = []
    if miss_meta is None and miss_log is None:
        lines.append(f"- 台账缺失项：{MISSING}（`meta.missing` / `run_log.missing` 均不存在）")
    else:
        items = list(miss_log or []) + [x for x in (miss_meta or []) if x not in (miss_log or [])]
        if items:
            lines.append(f"- 台账缺失项（{len(items)} 项）：" + "；".join(str(x) for x in items))
        else:
            lines.append("- 台账缺失项：无（`missing` 为空，源端未报缺列）。")

    slots = f["slots"]
    if not slots:
        lines.append(f"- 红件槽位：{MISSING}（缺 `red_slots.json`）。")
    else:
        empty = [s for s in slots if not str(s.get("new") or "").strip()]
        if empty:
            where = "、".join(str(s.get("location") or "（空）") for s in empty[:10])
            more = "" if len(empty) <= 10 else f" 等 {len(empty)} 处"
            lines.append(f"- 红件中落空的槽位（`new` 为空，源端无值）：{where}{more}")
        else:
            lines.append(f"- 红件中落空的槽位：{len(slots)} 条槽位全部有值"
                         "（`new` 无空串），本期无「源端无数据」格。")
        manual = [s for s in slots
                  if any(m in str(s.get("source") or "") for m in MANUAL_MARKERS)]
        if manual:
            lines.append(f"- 来源写明人工的槽位：{len(manual)} 条")

    if f["manual"]:
        lines.append(f"- 仍为手工填写的项（`红色件清单.md`，{len(f['manual'])} 项）：")
        lines.extend(f"    · {x}" for x in f["manual"])
    else:
        lines.append(f"- 手工填写项：{MISSING}（`红色件清单.md` 无「仍为手工的槽位」小节）")
    return "\n".join(lines)


def _section_statement(f: dict) -> str:
    n = len(f["slots"])
    scope = f"（本期 `red_slots.json` 共 {n} 条槽位，逐条带 `source`）" if n else ""
    return ("本文所有数值均可回链至台账或 ESI/InCites 原始包"
            f"{scope}，不由模型生成；"
            "预测值单独标注模型与回测误差，不并入台账数值。")


def build(period: str, facts: dict) -> str:
    bodies = {
        SECTIONS[0]: _section_scope(period, facts),
        SECTIONS[1]: _section_values(facts),
        SECTIONS[2]: _section_gaps(facts),
        SECTIONS[3]: _section_statement(facts),
    }
    parts = [f"# 方法与边界说明 · {period} 期", ""]
    for i, name in enumerate(SECTIONS, 1):
        parts += [f"## {'一二三四'[i - 1]}、{name}", "", bodies[name], ""]
    return "\n".join(parts).rstrip() + "\n"


def _in_out_dir(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(OUT_ROOT.resolve())
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="方法与边界说明生成器（只读）")
    ap.add_argument("--period", action="append", default=[], help="期次，默认最新一期")
    ap.add_argument("--out", default=None, help="落盘路径（默认 stdout；禁止写 out/）")
    args = ap.parse_args(argv)

    periods = args.period or sorted(p.parent.name for p in OUT_ROOT.glob("*/overview_facts.json"))[-1:]
    if not periods:
        print(f"out/ 下没有任何期次目录：{OUT_ROOT}", file=sys.stderr)
        return 3

    chunks, failed = [], False
    for period in periods:
        d = OUT_ROOT / period
        if not d.is_dir():
            print(f"缺少 {d}", file=sys.stderr)
            failed = True
            continue
        chunks.append(build(period, collect(d)))
    text = "\n".join(chunks)

    if args.out:
        out = pathlib.Path(args.out)
        if _in_out_dir(out):
            print(f"--out 不许写进 out/（只读区）：{out}；请用 tmp/ 下的路径", file=sys.stderr)
            return 3
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"已写入 {out}")
    else:
        print(text)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
