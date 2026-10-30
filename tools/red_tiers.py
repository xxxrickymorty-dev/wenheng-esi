# -*- coding: utf-8 -*-
"""红件分级：几百条红件不该平铺给人核，按「错一格的代价」分三级。

**只读工具，不进流水线、不重出报告、不写 `out/`。**

判据（全部是显式规则，改口径只改下面这些常量）
────────────────────────────────────────────────────────────────
核心   错一格就错数：T01 大表 / T19 省域表 / T20 矩阵表的数值格（不含图）
支持   错一处要返工但不改结论：正文段落、各表表头、非图的其它 T 表
次要   错一处只是观感：图表槽（`[图]`）、清除母版残留、母版/行距等格式类

分级只看 `location` / `new` 两个字段，不猜内容语义 —— 这样规则可复核、可争论，
但不会因为文案措辞变化而漂移。

用法：
    python tools/red_tiers.py                       # 最新一期，打到 stdout
    python tools/red_tiers.py --period 202609
    python tools/red_tiers.py --period 202609 --out tmp/红件分级_202609.md

退出码：0 正常；3 产物缺失 / 试图写进 out/。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "out"

# ---------------------------------------------------------------- 分级规则
TIER_CORE = "核心"
TIER_SUPPORT = "支持"
TIER_MINOR = "次要"
TIERS = (TIER_CORE, TIER_SUPPORT, TIER_MINOR)

#: 核心：大表 / 省域表 / 矩阵表 —— 这三张表上的数字会被读者直接引用
CORE_PREFIXES = ("T01", "T19", "T20")

#: 图表槽标记（`new` 以此开头）
CHART_MARKER = "[图]"

#: 母版清理留下的动作槽（不是数，是「把这行删掉」）
CLEAR_MARKERS = ("（清除母版残留",)

#: 格式类 location 关键字：图片行距、母版红字、字体行距…
FORMAT_MARKERS = ("母版", "图片行距", "行距", "字体", "格式")

#: 支持：正文段落前缀 + 表头 suffix
SUPPORT_PREFIXES = ("正文",)
HEADER_SUFFIX = "/表头"

#: 之外命中的 T 表（T03…T18、T17 图表行、预测章、封面、附录）默认算支持
_T_PREFIX = "T"

#: 各级建议核验比例（判据见报告正文；表头例外，永远全查）
SAMPLE_RATIO = {TIER_CORE: 1.0, TIER_SUPPORT: 0.3, TIER_MINOR: 0.1}
#: 表头一律全查：表头错了，整列的数就都在错的地方
HEADER_ALWAYS_FULL = True


def loc_prefix(location: str) -> str:
    return str(location).split("/", 1)[0] or "（空）"


def _is_format(location: str) -> bool:
    return any(m in location for m in FORMAT_MARKERS)


def _is_other_table(location: str) -> bool:
    p = loc_prefix(location)
    return p.startswith(_T_PREFIX) and p[1:].isdigit()


def tier_of(slot: dict) -> str:
    """一条红件 → 三级之一。**判据顺序有意义**：先排除「不是数」的，再判核心。"""
    new = str(slot.get("new") or "").strip()
    location = str(slot.get("location") or "")
    if new.startswith(CHART_MARKER):
        return TIER_MINOR
    if any(m in new for m in CLEAR_MARKERS):
        return TIER_MINOR
    if _is_format(location):
        return TIER_MINOR
    # 表头先于「核心」判：`T01/表头` 虽然挂在 T01 下，但它是列名不是数
    if location.endswith(HEADER_SUFFIX):
        return TIER_SUPPORT
    if loc_prefix(location) in CORE_PREFIXES:
        return TIER_CORE
    if loc_prefix(location) in SUPPORT_PREFIXES:
        return TIER_SUPPORT
    if _is_other_table(location):
        return TIER_SUPPORT
    return TIER_SUPPORT                      # 封面 / 预测章 / 附录 兜底


def load_slots(path: pathlib.Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("slots") or []
    if not isinstance(raw, list):
        raise ValueError(f"{path} 不是槽位清单（顶层 {type(raw).__name__}）")
    return [x for x in raw if isinstance(x, dict)]


def analyse(slots: list[dict]) -> dict:
    total = len(slots)
    buckets = {t: [] for t in TIERS}
    for s in slots:
        buckets[tier_of(s)].append(s)

    tiers = []
    for t in TIERS:
        items = buckets[t]
        prefixes = Counter(loc_prefix(x.get("location") or "") for x in items)
        ratio = SAMPLE_RATIO[t]
        # 支持级里的表头不受抽样比例约束：表头全查
        headers = sum(1 for x in items
                      if str(x.get("location") or "").endswith(HEADER_SUFFIX))
        plan = math.ceil(len(items) * ratio)
        if t == TIER_SUPPORT and HEADER_ALWAYS_FULL:
            plan = max(plan, headers)
        tiers.append({
            "tier": t,
            "count": len(items),
            "share": (len(items) / total) if total else 0.0,
            "sample_ratio": ratio,
            "plan_count": plan,
            "headers": headers,
            "prefixes": [{"prefix": p, "count": n}
                         for p, n in sorted(prefixes.items(), key=lambda kv: (-kv[1], kv[0]))],
        })
    return {
        "total": total,
        "tiers": tiers,
        "by_prefix": [{"prefix": p, "count": n} for p, n in sorted(
            Counter(loc_prefix(x.get("location") or "") for x in slots).items(),
            key=lambda kv: (-kv[1], kv[0]))],
    }


# ---------------------------------------------------------------- 输出
TIER_RULE_TEXT = {
    TIER_CORE: "T01/T19/T20 的数值格（`new` 不以 `[图]` 开头）——错一格就错数",
    TIER_SUPPORT: "正文段落、各表表头、非图的其它 T 表——错一处要返工但不改结论",
    TIER_MINOR: "图表槽（`[图]`）、清除母版残留、母版/行距等格式类——错一处只是观感",
}


def render(period: str, rep: dict) -> str:
    total = rep["total"]
    by = {t["tier"]: t for t in rep["tiers"]}
    lines = [f"# 红件分级 · {period} 期", "",
             f"总槽位 {total} 条（源：`out/{period}/red_slots.json`）", "",
             "| 级别 | 条数 | 占比 | 建议核验条数 |", "|---|---|---|---|"]
    for t in TIERS:
        b = by[t]
        lines.append(f"| {t} | {b['count']} | {b['share'] * 100:.1f}% | {b['plan_count']} |")
    lines += ["", "## 判据", ""]
    for t in TIERS:
        lines.append(f"- **{t}**：{TIER_RULE_TEXT[t]}")
    lines += ["", "## 各级构成", ""]
    for t in TIERS:
        b = by[t]
        if not b["count"]:
            lines.append(f"- **{t}**：0 条")
            continue
        top = "、".join(f"{p['prefix']}({p['count']})" for p in b["prefixes"][:8])
        extra = "" if len(b["prefixes"]) <= 8 else f" 等 {len(b['prefixes'])} 个前缀"
        lines.append(f"- **{t}**：{top}{extra}")

    lines += ["", "## 建议核验顺序", "",
              "1. **核心逐格** —— 先核 T01/T19/T20 的数值格，一格一格对台账。"
              f"本期待核 {by[TIER_CORE]['count']} 格，**全查（100%）**，不抽样；"
              "发现一格错，同列其余格必须连坐重查。"]
    sup = by[TIER_SUPPORT]
    hdr = f"其中表头 {sup['headers']} 条一律全查，" if sup["headers"] else ""
    lines.append(f"2. **支持抽段** —— 正文段落与其它表。{hdr}"
                 f"其余按 {int(SAMPLE_RATIO[TIER_SUPPORT] * 100)}% 抽，"
                 f"约 {sup['plan_count']} 条；抽到的段落要连读上下句，看数字与主语是否错位。")
    lines.append(f"3. **次要抽样** —— 图表槽与格式类。按 "
                 f"{int(SAMPLE_RATIO[TIER_MINOR] * 100)}% 抽，"
                 f"约 {by[TIER_MINOR]['plan_count']} 条；重点看图题学科名是否与图内数据同科，"
                 "格式类只看最终 PDF 是否有肉眼可见残迹。")
    lines += ["", f"合计建议核验 {sum(by[t]['plan_count'] for t in TIERS)} 条"
                  f"（占全部 {total} 条的 "
                  f"{(sum(by[t]['plan_count'] for t in TIERS) / total * 100) if total else 0:.0f}%）。"]
    return "\n".join(lines)


def _in_out_dir(path: pathlib.Path) -> bool:
    """硬约束：out/ 只读。显式 --out 也不许指进去。"""
    try:
        path.resolve().relative_to(OUT_ROOT.resolve())
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="红件分级（只读）")
    ap.add_argument("--period", action="append", default=[], help="期次，默认最新一期")
    ap.add_argument("--out", default=None, help="落盘路径（默认 stdout；禁止写 out/）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是 markdown")
    args = ap.parse_args(argv)

    periods = args.period or sorted(p.parent.name for p in OUT_ROOT.glob("*/red_slots.json"))[-1:]
    if not periods:
        print(f"out/ 下没有任何 */red_slots.json：{OUT_ROOT}", file=sys.stderr)
        return 3

    chunks, failed = [], False
    for period in periods:
        path = OUT_ROOT / period / "red_slots.json"
        if not path.is_file():
            print(f"缺少 {path}", file=sys.stderr)
            failed = True
            continue
        try:
            rep = analyse(load_slots(path))
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"{path} 解析失败：{exc}", file=sys.stderr)
            failed = True
            continue
        if args.json:
            chunks.append(json.dumps({period: rep}, ensure_ascii=False, indent=1))
        else:
            chunks.append(render(period, rep))

    text = "\n\n".join(chunks)
    if args.out:
        out = pathlib.Path(args.out)
        if _in_out_dir(out):
            print(f"--out 不许写进 out/（只读区）：{out}；请用 tmp/ 下的路径", file=sys.stderr)
            return 3
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {out}")
    else:
        print(text)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
