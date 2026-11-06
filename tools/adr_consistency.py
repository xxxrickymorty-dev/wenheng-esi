#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ADR 一致性检查（只读，零新增依赖）。

用途：把 ADR 之间的软约束变成可机检的验收项，接进 AGENTS.md 验收清单。
用法：uv run python tools/adr_consistency.py
退出码：0 = 无 FAIL；1 = 存在 FAIL（WARNING 不计入退出码）。

检查项：
  1. ADR 之间 `docs/adr/xxxx-*.md` 引用路径存在性；
  2. 状态字段是否属于 5 值枚举；被取代件不得被别处标为「现行」/「继承来源」；
  3. 数字口径单源（ESI 期数 / InCites 快照数 / 槽位数 / 用例数）：命中已知多口径组
     或检出多值冲突报 WARNING，未登记的新冲突报 FAIL；扫描含 CONTEXT 与根仓 MEMORY（存在才读）；
  4. GLOSSARY `_Avoid_` 禁用词扫描（提示级 WARNING，需人工判读）；
  5. 每份 ADR 头部三字段（Supersedes / Amends / Superseded-by）完整性。

不读台账、不写任何文件、不依赖第三方包。
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"
GLOSSARY = REPO / "GLOSSARY.md"
CONTEXT = REPO / "CONTEXT.md"
MEMORY = REPO.parent / ".workbuddy" / "memory" / "MEMORY.md"

STATUS_ENUM = ["已接受", "提案", "待确认", "已取代", "已修订"]
THREE_FIELDS = ["Supersedes", "Amends", "Superseded-by"]

# 已知数字口径冲突（统计时点不同），命中报 WARNING，不计入 EXIT 1。
# 数值取自现状（0015 / CONTEXT / 复刻线口径）；ADR 不得手抄，应以 tools/doc_counts.py 为准。
KNOWN_NUMBER_CONFLICTS = [
    ("ESI 期数", {45, 46},
     "统计时点不同：0015 为档案库覆盖范围（201903–202609），CONTEXT 为解析根常量范围"
     "（201903→202607），引用须注明日期"),
    ("InCites 快照数", {43, 45}, "统计时点不同：引用须注明日期"),
    ("槽位数", {704, 721},
     "统计时点不同：704 为复刻线口径，721 为 red_slots.json 坐标数，引用须注明日期"),
    ("用例数", {1527, 2365},
     "CONTEXT 两处计数口径不一致，应以 tools/doc_counts.py 实测为准"),
]


def _adr_files():
    return sorted(p for p in ADR_DIR.glob("*.md") if re.match(r"\d{4}-", p.name))


def _load(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _check_cross_refs(files, problems):
    pat = re.compile(r"docs/adr/(\d{4}-[^\s)`]+\.md)")
    for f in files:
        for m in pat.finditer(_load(f)):
            ref = m.group(1)
            if not (ADR_DIR / ref).exists():
                problems.append(f"{f.name}: 引用 ADR 路径不存在 → docs/adr/{ref}")


def _check_status_enum(files, problems):
    for f in files:
        m = re.search(r"状态\**\s*[：:]\s*\**\s*([^\n（(]*)", _load(f))
        if not m:
            problems.append(f"{f.name}: 未找到状态行")
            continue
        val = m.group(1).strip().strip("*").strip()
        if not any(s in val for s in STATUS_ENUM):
            problems.append(f"{f.name}: 状态「{val}」不在 5 值枚举 {STATUS_ENUM}")


def _check_superseded_misuse(files, problems):
    superseded = {}
    for f in files:
        if re.search(r"状态[：:]\s*\**\s*已取代", _load(f)):
            num = re.match(r"(\d{4})", f.name)
            if num:
                superseded[num.group(1)] = f.name
    if not superseded:
        return
    pats = [
        r"{n}\S{{0,30}}(现行有效|现行生效|当前生效)",
        r"{name}\S{{0,20}}(现行有效|现行生效|当前生效|继承来源)",
    ]
    for num, name in superseded.items():
        for f in files:
            if f.name == name:
                continue
            text = _load(f)
            for p in pats:
                if re.search(p.format(n=num, name=name), text):
                    problems.append(
                        f"{f.name}: 已取代件 {num} 被标为现行/继承来源，违反唯一性作用域表")
                    break


def _check_three_fields(files, problems):
    for f in files:
        text = _load(f)
        for field in THREE_FIELDS:
            if field not in text:
                problems.append(f"{f.name}: 缺头部字段 {field}")


def _check_numbers(files, problems, warns):
    scan = files + [p for p in (CONTEXT, MEMORY) if p.exists()]
    metrics = {
        "ESI 期数": re.compile(r"ESI[^\d]{0,6}?(\d+)\s*期"),
        "InCites 快照数": re.compile(r"InCites[^\d]{0,6}?(\d+)\s*(?:个)?快照"),
        "槽位数": re.compile(r"(\d+)\s*槽位"),
        "用例数": re.compile(r"全量\s*(\d+)\s*例"),
    }
    for metric, pat in metrics.items():
        found: dict[int, list[str]] = {}
        for f in scan:
            for m in pat.finditer(_load(f)):
                found.setdefault(int(m.group(1)), []).append(f.name)
        vals = set(found)
        known_group = next((k for k in KNOWN_NUMBER_CONFLICTS if k[0] == metric), None)
        # 只检出一个值、且该值属于已登记的多口径组时也要出声——否则
        # KNOWN_NUMBER_CONFLICTS 会变成永不触发的死配置，检查成了摆设。
        if len(vals) == 1 and known_group:
            v = next(iter(vals))
            if v in known_group[1]:
                warns.append(
                    f"[数字口径][WARNING] {metric} 仅检出 {v}"
                    f"（{', '.join(sorted(set(found[v])))}），属已知多口径组"
                    f" {sorted(known_group[1])} —— {known_group[2]}")
                continue
        if len(vals) <= 1:
            continue
        known = next((k for k in KNOWN_NUMBER_CONFLICTS if k[0] == metric and vals <= k[1]), None)
        detail = "; ".join(f"{v}（{', '.join(sorted(set(found[v])))})" for v in sorted(vals))
        if known:
            warns.append(f"[数字口径][WARNING] {metric} 多值 {detail} —— {known[2]}")
        else:
            problems.append(f"[数字口径][FAIL] {metric} 未注明时点的冲突 {detail}")
    # ADR 不应手抄用例数
    for f in files:
        if re.search(r"\d+\s*例（默认|\d+\s*个用例|\d+\s*个测试", _load(f)):
            warns.append(f"[数字口径][WARNING] {f.name}: 疑似手抄用例数，应以 tools/doc_counts.py 为准")


def _check_glossary_avoid(files, warns):
    if not GLOSSARY.exists():
        return
    banned: set[str] = set()
    # 通用/基础设施词，在内部设计 ADR 中作为正确用法出现，不单独标红（如「唯一事实源」「红线」「报告」）。
    stop = {
        "唯一", "报告", "红线", "口径", "审核", "断言", "AI", "入库", "放行", "审批",
        "回写", "数据库", "红件", "红件清单", "P2", "只有", "三个", "就是",
    }
    for m in re.finditer(r"_Avoid_[:：]\s*(.+)", _load(GLOSSARY)):
        seg = m.group(1)
        # 1) 粗体显式术语：**「x」** 或 **x**
        for bm in re.finditer(r"\*\*(?:「([^」]+)」|([^*]+))\*\*", seg):
            tok = (bm.group(1) or bm.group(2)).strip()
            if 2 <= len(tok) <= 12 and tok not in stop:
                banned.add(tok)
        # 2) （/；/： 之前、以 、 分隔的术语清单（避免把解释性长句当术语）
        head = re.split(r"[（(；:：]", seg)[0]
        for tok in re.split(r"[、/,\s]+", head):
            tok = tok.strip(" *「」\"'")
            if 2 <= len(tok) <= 12 and tok not in stop:
                banned.add(tok)
    if not banned:
        return
    for f in files:
        hits = sorted({b for b in banned if b and b in _load(f)})
        if hits:
            warns.append(
                f"[禁用词][WARNING] {f.name}: 命中 GLOSSARY 禁用词 {hits}"
                f"（提示级，界面禁用词，内部设计 ADR 可含，需人工判读，不计入 EXIT 1）")


def main() -> int:
    files = _adr_files()
    problems: list[str] = []
    warns: list[str] = []

    _check_cross_refs(files, problems)
    _check_status_enum(files, problems)
    _check_superseded_misuse(files, problems)
    _check_three_fields(files, problems)
    _check_numbers(files, problems, warns)
    _check_glossary_avoid(files, warns)

    print(f"ADR 一致性检查：扫描 {len(files)} 份 ADR")
    if warns:
        print("\n--- WARNING（不计入 EXIT 1）---")
        for w in warns:
            print(f"  {w}")
    if problems:
        print("\n--- FAIL（EXIT 1）---")
        for p in problems:
            print(f"  [FAIL] {p}")
        print(f"\n结果：{len(problems)} 项失败，{len(warns)} 项警告 → EXIT 1")
        return 1
    print("\n结果：全部通过（0 失败）" + (f"；含 {len(warns)} 项提示级警告" if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
