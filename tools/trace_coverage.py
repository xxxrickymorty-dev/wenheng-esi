# -*- coding: utf-8 -*-
"""逐格追溯率：red_slots.json 里每一条红件，能不能说出「这个数从哪来」。

**只读工具，不进流水线、不重出报告、不写 `out/`。**

为什么要有这个指标
────────────────────────────────────────────────────────────────
`红色件清单.md` 只回答「还剩多少手工槽」，不回答「自动填的那几百格里，有多少
真的指得回一份数据文件」。指不回去的格子照样会被签单通过 —— 这就是静默失效
的入口。本工具把 red_slots.json 的每一条 `source` 归到四类：

    数据文件   source 指向 .csv/.json/.parquet/.xlsx… 或数据目录（可逐格复核）
    期次参数   期次/封面这类非数据槽（本期第几期、年月）
    图表引用   `new` 以 `[图]` 开头，或 source 指向 charts/ 下的成品图
    其它       sentences.py / extract_province / report_forecast / 母版清理 …

**覆盖率 = 数据文件类条数 ÷ 总槽位数**，是可直接断言的指标：签单前跑一遍，
覆盖率 < 100% 就退出 2，让 CI 拦住「口头可追溯」。

用法：
    python tools/trace_coverage.py                 # 最新一期
    python tools/trace_coverage.py --period 202609
    python tools/trace_coverage.py --period 202605 --period 202609
    python tools/trace_coverage.py --all --json

退出码：0 = 覆盖率 100%；2 = 覆盖率 < 100%（报告照常打印）；3 = 产物/参数问题。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "out"

# ---------------------------------------------------------------- 分类规则
#: 四类（顺序即报告顺序）
KIND_DATA = "数据文件"
KIND_PERIOD = "期次参数"
KIND_CHART = "图表引用"
KIND_OTHER = "其它"
KINDS = (KIND_DATA, KIND_PERIOD, KIND_CHART, KIND_OTHER)

#: 认「这是数据文件」的后缀。刻意不含 .md/.docx/.pdf —— 那是报告，不是可回读的源。
DATA_EXTS = (".csv", ".tsv", ".json", ".parquet", ".xlsx", ".xls", ".xlsm")

#: 认「这是数据目录」的路径片段（源端包，文件常不带后缀，如「22 学科榜中出现 14/22 次」）
DATA_PATH_MARKERS = ("数据覆盖", "ESI数据/", "incites/", "input/", "wide/")

#: 期次参数的标记词
PERIOD_MARKERS = ("期次参数",)

#: 图表成品的路径前缀（`new` 没写 `[图]` 也算图表引用）
CHART_MARKERS = ("charts/",)

#: `new` 里图表槽的标记
CHART_TEXT_PREFIX = "[图]"

#: 按 location 归前缀时，`T01/r1c0` → `T01`
_LOC_PREFIX_SEP = "/"


def classify(slot: dict) -> str:
    """一条红件 → 四类之一。规则写在上面常量里，改口径只改常量。"""
    new = str(slot.get("new") or "").strip()
    source = str(slot.get("source") or "")
    if new.startswith(CHART_TEXT_PREFIX):
        return KIND_CHART
    if any(m in source for m in CHART_MARKERS):
        return KIND_CHART
    if any(m in source for m in PERIOD_MARKERS):
        return KIND_PERIOD
    low = source.lower()
    if any(low.endswith(ext) or ext + "#" in low or ext + "（" in low for ext in DATA_EXTS):
        return KIND_DATA
    if any(m in source for m in DATA_PATH_MARKERS):
        return KIND_DATA
    return KIND_OTHER


def loc_prefix(location: str) -> str:
    """`T01/r1c0` → `T01`；`正文/p1` → `正文`；无分隔符则原样。"""
    return str(location).split(_LOC_PREFIX_SEP, 1)[0] or "（空）"


def load_slots(path: pathlib.Path) -> list[dict]:
    """读 red_slots.json。容许 list 或 {"slots": [...]} 两种形态。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("slots") or []
    if not isinstance(raw, list):
        raise ValueError(f"{path} 不是槽位清单（顶层 {type(raw).__name__}）")
    return [x for x in raw if isinstance(x, dict)]


def analyse(slots: list[dict]) -> dict:
    """→ 一份可直接 json.dumps 的报告体。"""
    kinds = Counter()
    by_source = Counter()
    per_prefix: dict[str, dict[str, int]] = {}
    for s in slots:
        kind = classify(s)
        kinds[kind] += 1
        by_source[str(s.get("source") or "")] += 1
        p = loc_prefix(s.get("location") or "")
        bucket = per_prefix.setdefault(p, {"total": 0, KIND_DATA: 0})
        bucket["total"] += 1
        if kind == KIND_DATA:
            bucket[KIND_DATA] += 1

    total = len(slots)
    data = kinds.get(KIND_DATA, 0)
    prefixes = []
    for p, b in per_prefix.items():
        prefixes.append({
            "prefix": p,
            "total": b["total"],
            "traceable": b[KIND_DATA],
            "ratio": (b[KIND_DATA] / b["total"]) if b["total"] else 0.0,
        })
    prefixes.sort(key=lambda x: (-x["total"], x["prefix"]))
    return {
        "total": total,
        "traceable": data,
        "coverage": (data / total) if total else 0.0,
        "kinds": {k: kinds.get(k, 0) for k in KINDS},
        "by_source": [
            {"source": src, "count": n}
            for src, n in sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_prefix": prefixes,
    }


# ---------------------------------------------------------------- 输出
def render(period: str, rep: dict) -> str:
    lines = [f"== 期次 {period} · 逐格追溯率 ==", ""]
    lines.append(f"{'总槽位':<12}{rep['total']:>6}")
    lines.append(f"{'可追溯至数据文件':<10}{rep['traceable']:>6}")
    lines.append(f"{'覆盖率':<12}{rep['coverage'] * 100:>6.1f}%")
    lines.append("")
    lines.append("-- 按类别 " + "-" * 46)
    for k in KINDS:
        n = rep["kinds"][k]
        share = (n / rep["total"] * 100) if rep["total"] else 0.0
        lines.append(f"  {k:<8}{n:>5}  {share:>5.1f}%")
    lines.append("")
    lines.append(f"-- 按 source（共 {len(rep['by_source'])} 种，取前 20）" + "-" * 20)
    for row in rep["by_source"][:20]:
        src = row["source"] if len(row["source"]) <= 78 else row["source"][:75] + "…"
        lines.append(f"  {row['count']:>5}  {src or '（空 source）'}")
    lines.append("")
    lines.append(f"-- 按 location 前缀（{len(rep['by_prefix'])} 个）" + "-" * 26)
    lines.append(f"  {'前缀':<10}{'槽位':>6}{'可追溯':>8}{'覆盖率':>9}")
    for row in rep["by_prefix"]:
        lines.append(
            f"  {row['prefix']:<10}{row['total']:>6}{row['traceable']:>8}"
            f"{row['ratio'] * 100:>8.1f}%")
    lines.append("")
    if rep["coverage"] >= 1.0:
        lines.append("结论：覆盖率 100%，每一格都能指回一份数据文件。")
    else:
        lost = rep["total"] - rep["traceable"]
        lines.append(f"结论：覆盖率 {rep['coverage'] * 100:.1f}%，{lost} 格无法指回数据文件"
                     "（见「其它」类的 source）。")
    return "\n".join(lines)


def periods_of(args) -> list[str]:
    if args.all:
        found = sorted(p.parent.name for p in OUT_ROOT.glob("*/red_slots.json"))
        if not found:
            raise SystemExit(f"out/ 下没有任何 */red_slots.json：{OUT_ROOT}")
        return found
    if args.period:
        return list(args.period)
    latest = sorted(p.parent.name for p in OUT_ROOT.glob("*/red_slots.json"))
    if not latest:
        raise SystemExit(f"out/ 下没有任何 */red_slots.json：{OUT_ROOT}")
    return [latest[-1]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="逐格追溯率（只读）")
    ap.add_argument("--period", action="append", default=[],
                    help="期次，可重复（如 --period 202609）")
    ap.add_argument("--all", action="store_true", help="扫 out/*/red_slots.json")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    reports, missing, worst = {}, [], 1.0
    for period in periods_of(args):
        path = OUT_ROOT / period / "red_slots.json"
        if not path.is_file():
            missing.append(period)
            reports[period] = {"error": f"缺少 {path}"}
            continue
        try:
            rep = analyse(load_slots(path))
        except (json.JSONDecodeError, ValueError) as exc:
            missing.append(period)
            reports[period] = {"error": f"{path} 解析失败：{exc}"}
            continue
        reports[period] = rep
        worst = min(worst, rep["coverage"])

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=1))
    else:
        blocks = []
        for period, rep in reports.items():
            if "error" in rep:
                blocks.append(f"== 期次 {period} · 逐格追溯率 ==\n\n{rep['error']}")
            else:
                blocks.append(render(period, rep))
        print("\n\n".join(blocks))

    if missing:
        print(f"\n缺产物或解析失败：{', '.join(missing)}", file=sys.stderr)
        return 3
    return 0 if worst >= 1.0 else 2


if __name__ == "__main__":
    sys.exit(main())
