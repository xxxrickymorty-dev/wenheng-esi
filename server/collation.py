# -*- coding: utf-8 -*-
"""对勘本数据装配。

把 `out/<期次>/red_slots.json`（逐格审计）+ `meta.json`（期次与断言）
归纳成「槽位分组 → 槽位」结构，交给 `templates/collation.html` 渲染。

与 `redslots.html` 的区别：
- 红色件清单是**全量可搜索表**（354 行，给签单人逐条核）；
- 对勘本是**正文级阅读视图**（改了什么、改在句子的哪个位置，朱笔点校）。

两者读同一份 red_slots.json，不新增数据源。

一处增益：大表（T01）在母版里是**空表**，所以 red_slots.json 里 239 个格子的
old 全是空串，对勘视图会退化成「只列本期值」。这里按学科名对齐上期
`out/<上期*>/table2.csv`，把**上期的同一个格子**补进来当参照——这才是阅签人
真正想看的「哪个学科指标变了」。所以每个槽位自带 `oldLabel`：
正文槽位是「母版原文」，大表格子是「上期 202605」，不混为一谈。
"""
import pathlib
import re

from . import artifacts

# 「正文/p1」这类槽位在 red_slots.json 里 old/new 被截断到 50 字（清单表用）。
# 若 fill_docx 写入了 old_full/new_full，则优先使用全文。
CELL_RE = re.compile(r"^T\d{2}/r\d+c\d+$")
CELL_T01 = re.compile(r"^T01/r(\d+)c(\d+)$")
DCHART_RE = re.compile(r"^T(?:0[2-9]|[1-9]\d)/")
MANUAL_RE = re.compile(r"【手工：[^】]*】")   # 完整占位符，用于计数
MANUAL_HINT = re.compile(r"【手工：")        # 仅探测前缀——50 字预览会截断右括号，仍要能命中

# 大表列序（与 src/fill_docx.py 的 TABLE2_COLS 一致）
TABLE2_COLS = ["discipline", "rank_cn_change", "papers", "cnci", "total_cites",
               "thr_1pct", "thr_1pct_gap", "thr_1permille", "permille_rank",
               "top_papers", "prox_change"]

# 分组顺序即页面左栏顺序；谓词按序消费，先匹配先得（"其他"必须垫底）
SECTIONS = [
    ("cover", "封面", "期数 · 年月", lambda l: l.startswith("封面/")),
    ("overview", "概述正文", "第一章四段", lambda l: l in {"正文/p1", "正文/p2", "正文/p3", "正文/p4"}),
    ("trend", "发展趋势", "排名走势段", lambda l: l == "正文/trend"),
    ("situation", "学科态势", "22 学科排名升降统计", lambda l: l.startswith("正文/situation")),
    ("bigtable", "大表与表题", "T01 逐格 · 对照上期", lambda l: l == "正文/table2_title" or l.startswith("T01/")),
    ("dcharts", "学科图表槽位", "16 学科 × 6 图", lambda l: bool(DCHART_RE.match(l))),
    ("top", "顶尖论文", "学科数 · 学院数", lambda l: l == "正文/top_section"),
    ("forecast", "预测回测", "趋势判断与进入区间", lambda l: l.startswith("正文/forecast")),
    ("province", "云南省对比", "9 校横向表", lambda l: l == "正文/province_p"),
    ("charts", "概览图槽位", "插入 / 替换母版图", lambda l: l.startswith("正文/") and "图" in l),
    ("other", "其他槽位", "未归类", lambda l: True),
]

OLD_LABEL = {"text": "母版原文", "cell": "母版此格", "chart": "母版原状"}


def _kind(loc, new):
    """槽位类型：chart（图）/ cell（表格格）/ text（文字）。"""
    if str(new).startswith("[图]") or (loc.startswith("正文/") and "图" in loc):
        return "chart"
    if loc.startswith("T") and "/" in loc:
        return "cell"
    return "text"


def _fmt_cell(col, v):
    """按 src/fill_docx.py 写进 docx 的同一套规则回放上期值，保证 old/new 同格式可比。

    fill_docx 的规则是「只有 float 才格式化，整数 / 字符串原样输出」；CSV 里读出来
    全是字符串，所以用「字面量是否带小数点」还原原始类型——否则 papers 会变成
    1814.000，和本期的 1852 并排像两个量纲。
    """
    if v is None or v == "":
        return ""
    s = str(v)
    if "." not in s:
        return s                      # 整数、"153/↑1"、"（空）" 等原样
    try:
        f = float(s)
    except ValueError:
        return s                      # "↑33.28%" 这类带百分号的
    if col == "cnci":
        return f"{f:.2f}"
    if col == "permille_rank":
        return f"{f:.3f}"
    return f"{f:.2f}" if abs(f) < 1000 else f"{f:.3f}"


def _find_prev_dir(out_dir, prev_period):
    """上期目录：可能是 `202605`，也可能是 `202605_复现`（复现跑的）。"""
    if not prev_period:
        return None
    parent = out_dir.parent
    if not parent.exists():
        return None
    cands = [d for d in parent.iterdir()
             if d.is_dir() and d.name.startswith(str(prev_period)) and (d / "table2.csv").exists()]
    if not cands:
        return None
    cands.sort(key=lambda d: (d.name != str(prev_period), d.name))
    return cands[0]


def _enrich_bigtable(prepared, out_dir, prev_period):
    """把上期 table2.csv 的同一个格子补进大表槽位的 old。

    返回 (补了几个格, 上期目录名 or None)。
    """
    if not prev_period:
        return 0, None
    prev_dir = _find_prev_dir(out_dir, prev_period)
    if prev_dir is None:
        return 0, None
    cur_rows = artifacts.read_table2(out_dir)
    prev_map = {r.get("discipline", ""): r for r in artifacts.read_table2(prev_dir)}
    if not cur_rows or not prev_map:
        return 0, None

    n = 0
    for it in prepared:
        m = CELL_T01.match(it["loc"])
        if not m:
            continue
        i, j = int(m.group(1)), int(m.group(2))
        if j == 0 or i < 1 or i > len(cur_rows):
            continue          # c0 是学科名，母版空 → 保持「母版此格为空」更如实
        pr = prev_map.get(cur_rows[i - 1].get("discipline", ""))
        if not pr:
            continue
        ov = _fmt_cell(TABLE2_COLS[j], pr.get(TABLE2_COLS[j]))
        if ov == "":
            continue
        it["old"] = ov
        it["oldPreview"] = ov
        it["oldLabel"] = f"上期 {prev_period}"
        it["source"] = f"{it['source']} · 上期 {prev_period} 期对勘"
        n += 1
    return n, prev_dir.name


def build(path):
    """path → out/<期次> 目录。返回可直接 tojson 的 dict。"""
    out_dir = pathlib.Path(path)
    slots = artifacts.read_slots(out_dir)          # 读取/守卫唯一在 artifacts
    meta = artifacts.read_meta(out_dir)

    prepared = []
    for s in slots:
        loc = str(s.get("location", ""))
        old_p = artifacts.slot_text(s, "old", full=False)
        new_p = artifacts.slot_text(s, "new", full=False)
        old_f = artifacts.slot_text(s, "old")
        new_f = artifacts.slot_text(s, "new")
        kind = artifacts.slot_kind(s)
        prepared.append({
            "loc": loc,
            "old": old_f,
            "new": new_f,
            "oldPreview": old_p,
            "newPreview": new_p,
            "source": str(s.get("source", "")),
            "kind": kind,
            "oldLabel": "母版表头" if loc == "T01/表头" else OLD_LABEL.get(kind, "原值"),
            # 在全文上判定，避免被 50 字预览截断漏判
            "manual": bool(MANUAL_HINT.search(new_f)),
        })

    prev_period = str(meta.get("period_prev") or "")
    n_enriched, prev_dir_name = _enrich_bigtable(prepared, out_dir, prev_period)

    taken = [False] * len(prepared)
    sections = []
    for sid, name, note, pred in SECTIONS:
        items = []
        for i, it in enumerate(prepared):
            if not taken[i] and pred(it["loc"]):
                taken[i] = True
                items.append(it)
        if items:
            c = {"text": 0, "cell": 0, "chart": 0}
            m = 0
            for it in items:
                c[it["kind"]] += 1
                if it["manual"]:
                    m += 1
            sections.append({"id": sid, "name": name, "note": note,
                             "count": len(items), "text": c["text"],
                             "cell": c["cell"], "chart": c["chart"],
                             "manual": m, "slots": items})

    counts = {"total": len(prepared), "text": 0, "cell": 0, "chart": 0, "manual": 0}
    for it in prepared:
        counts[it["kind"]] += 1
        if it["manual"]:
            counts["manual"] += 1

    return {
        "period": str(meta.get("period_current") or out_dir.name),
        "periodPrev": prev_period,
        "outDir": out_dir.name,
        "assertions": artifacts.assertion_counts(meta),
        # totals 供题首大数使用；线上与 counts 恒等，静态快照可只内联抽样槽位
        "counts": dict(counts),
        "totals": dict(counts),
        # 大表跨期对勘的可见性：补了多少格、上期取自哪个目录
        "bigtable": {"enriched": n_enriched, "prevDir": prev_dir_name, "prevPeriod": prev_period},
        "sections": sections,
    }
