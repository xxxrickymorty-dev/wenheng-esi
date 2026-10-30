# -*- coding: utf-8 -*-
"""他校简报：把 `panel()` 的结果落成一份能读、能核的 markdown 稿。

为什么要有这一层
----------------
`panel.py` 只算数据（谁在哪一期上榜了几个学科、交集是谁、哪几处值得标）。算完
没有出口，就只是一段能力而不是一条产线——对话层没东西可回，渲染层没东西可画。
本模块补的就是这个出口：**一条命令，一份稿**。

与旧线的分工（别混）
--------------------
旧线 `report.py` 是「单学科 + 云大锚点」，按**节**组织；本模块是「多校 × 多学科」，
按**格**组织。两者共用数据底座（`peers` / `discipline_list` / `period`），但**不共用
编排**——那 2289 行写死的假设改一处就是全员回归，所以旁边新开。

三条硬约束
----------
1. **零模型**：全文由 `panel()` 的数字 + 固定句式拼出来，没有任何 LLM 参与。
   这也是「运行期 LLM 不进数据路径」在简报场景的落地形态。
2. **数字只从 `panel()` 拿**：本模块不做任何算术（除了「末期 − 首期」这种一眼可核的
   差值），不读表、不碰 parquet。
3. **确定性**：同一输入除 `generated_at` 外逐字节一致（`tests/test_flexible_brief.py` 锁）。

产物（沿用旧线约定，`list_reports` 能直接列出）
----------------------------------------------
    out/<期次>/flexible/multi_school/report.md       人读
    out/<期次>/flexible/multi_school/brief.json      机读（panel 全量，含 grid）
    out/<期次>/flexible/multi_school/flex_meta.json  元信息 + 自检
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sys

try:                                     # 仓库惯例：pytest 的 pythonpath 已含 src
    from discipline_list import cn_of
    from period import label as period_label
except ImportError:                      # 作为包被导入或独立跑脚本时兜底
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from discipline_list import cn_of
    from period import label as period_label

from .panel import panel

#: 产物目录名。ASCII 与旧线的 `single_trend` / `cross_compare` 保持一致。
INTENT = "multi_school"

#: 给人看的名字（`planner.INTENTS` 只登记旧线的意图，这里不改它——改了会让
#: `report.generate` 认下一个它渲染不了的意图）。
TITLE = "他校简报（多校多学科）"

#: 事件类别 → 中文小标题。顺序即正文里的分节顺序。
_KIND_CN = {
    "enter": "新进学科",
    "exit": "退出学科",
    "overtake": "名次交叉",
    "flat": "持平",
    "inflect": "转向",
}


def _short_period(period: str) -> str:
    """`202511` → `2025-11`（表头用，比「2025年11月」省地方）。"""
    p = str(period)
    return f"{p[:4]}-{p[4:6]}"


def _delta(counts: list) -> str:
    """末期 − 首期。任一格为 `None`（该期无数据）就不给差值，不拿缺数据凑结论。"""
    if not counts or any(v is None for v in counts):
        return "—"
    d = counts[-1] - counts[0]
    return "持平" if d == 0 else f"{d:+d}"


def _counts_table(p: dict) -> list[str]:
    """六期上榜学科数：行＝学校，列＝期次，末列给首末差值。"""
    head = "| 学校 | " + " | ".join(_short_period(x) for x in p["periods"]) + " | 首末变化 |"
    sep = "|---" * (len(p["periods"]) + 2) + "|"
    lines = [head, sep]
    for s in p["schools"]:
        cells = ["—" if v is None else str(v) for v in (s["counts"] or [])]
        lines.append(f"| {s['cn']} | " + " | ".join(cells) + f" | {_delta(s['counts'])} |")
    return lines


def _only_table(p: dict) -> list[str]:
    """「本校另有」——相对共同交集，不是「全校独有」。"""
    if not p["only"]:
        return []
    lines = ["| 学校 | 共同之外另有 |", "|---|---|"]
    for cn, stems in p["only"].items():
        got = "、".join(cn_of(s) for s in stems) if stems else "—"
        lines.append(f"| {cn} | {got} |")
    return lines


def _event_text(e: dict) -> str:
    """事件 → 一行话。

    `overtake` 要单独拼：它的 `school` 是**被追上的那方**（图上该标的那条线），
    直接套 `text` 会读成「昆明理工大学 6 期追平昆明理工」——主语和宾语同一校。
    """
    if e["kind"] == "overtake":
        m = e.get("meta") or {}
        verb = "追平" if m.get("gap") == 0 else "反超"
        return f"被{m.get('with', '对手')}{verb}"
    return e["text"]


def _event_lines(p: dict) -> list[str]:
    """事件按类别分组列出来；每行都带学校与期次，读者能自己回原始表核对。"""
    if not p["events"]:
        return ["本期窗口内没有值得标注的变化。"]
    grouped: dict[str, list] = {}
    for e in p["events"]:
        grouped.setdefault(e["kind"], []).append(e)
    lines: list[str] = []
    for kind in _KIND_CN:
        items = grouped.get(kind)
        if not items:
            continue
        lines.append(f"**{_KIND_CN[kind]}**")
        lines.append("")
        for e in items:
            lines.append(f"- {e['school']} · {_short_period(e['period'])}：{_event_text(e)}")
        lines.append("")
    return lines


def _note_lines(p: dict) -> list[str]:
    """没能正常纳入的学校 / 缺数据的期次——照实写，不静默。"""
    lines: list[str] = []
    bad = [s for s in p["schools"] if s["status"] != "ok"]
    if bad:
        lines.append("### 未能纳入的学校")
        lines.append("")
        for s in bad:
            label = "整校未在 ESI 中出现" if s["status"] == "absent" else "校名对不上"
            lines.append(f"- **{s['query']}**（{label}）：{s['note']}")
        lines.append("")
    if p["missing"]:
        lines.append("### 缺数据的期次")
        lines.append("")
        lines.append("下列期次在 ESI 数据里读不到学科表，表内对应格记「—」，未用其他期次顶替：")
        lines.append("")
        lines.append("- " + "、".join(_short_period(x) for x in p["missing"]))
        lines.append("")
    return lines


def render(p: dict, generated_at: str | None = None) -> str:
    """panel 结果 → markdown 全文（纯函数，不碰磁盘）。

    `generated_at` 显式传入而不是在内部取当前时间——否则这个函数不再可复现，
    「同一输入逐字节一致」这条就没法测。`None` 时才取当前时间。
    """
    schools = [s["cn"] for s in p["schools"]]
    n_periods = p.get("n_periods") or len(p["periods"])
    generated_at = generated_at or _dt.datetime.now().isoformat(timespec="seconds")
    span = f"{period_label(p['periods'][0])}–{period_label(p['periods'][-1])}"
    out: list[str] = [
        f"# 他校简报：{' · '.join(schools)}（{period_label(p['period_end'])}）",
        "",
        "> 本件由灵活产线「他校简报」生成，**运行期无模型参与**：数字全部来自 ESI 学科表，",
        "> 正文由固定句式按数拼装。**非报送件**——不带盖章位，正式对外件请走复刻报告产线。",
        ">",
        f"> 期次：**{period_label(p['period_end'])}**（{n_periods} 期窗口 {span}）"
        f"　｜　学科口径：{len(p['disciplines'])} 个 ESI 学科",
        "",
        "---",
        "",
        "## 一、各期上榜学科数",
        "",
        "上榜＝该校出现在该学科的 ESI 机构表中。",
        "",
        *_counts_table(p),
        "",
        "## 二、共同与差异",
        "",
    ]
    if p["common"]:
        out += [
            f"{period_label(p['period_end'])}，各校**共同上榜 {len(p['common'])} 个学科**：",
            "",
            "、".join(cn_of(s) for s in p["common"]) + "。",
            "",
        ]
        out += _only_table(p)
    else:
        out.append("末期没有可比的共同学科（可能各校都没有数据）。")
    out += ["", "## 三、值得标注的变化", ""]
    out += _event_lines(p)
    out += ["## 四、口径与来源", ""]
    out += [
        f"- 数据源：`{p['source']['dataset']}`（{len(p['disciplines'])} 个学科表，只读）",
        f"- 期次：{p['period_end']}；窗口回溯用台账有效期次链，不做日历减法",
        "- 上榜判据：机构英文名归一（`&`→`AND`、去 `- CHINA` 后缀、去标点）后，出现在该学科机构表中",
        "- 「共同之外另有」＝本校末期满血学科 − 共同交集，**不是「全校独有」**",
        "- 「—」表示该期无数据，与「0（本期未上榜）」是两件事",
        f"- 生成时间：{generated_at}",
        "",
    ]
    out += _note_lines(p)
    return "\n".join(out).rstrip() + "\n"


def _check(p: dict) -> dict:
    """自检：几条能一眼核的结构不变量。判据是「数字对」，不是「断言全过」。"""
    bad: list[str] = []
    n = len(p["periods"])
    for s in p["schools"]:
        if len(s["counts"] or []) != n:
            bad.append(f"{s['cn']} 的计数有 {len(s['counts'] or [])} 期，窗口有 {n} 期")
    for s in p["schools"]:
        if s["status"] != "ok":
            continue
        last = p["grid"]["sets"].get(s["cn"], {}).get(p["periods"][-1], [])
        if s["counts"] and s["counts"][-1] is not None and len(last) != s["counts"][-1]:
            bad.append(f"{s['cn']} 末期计数 {s['counts'][-1]} 与学科集合 {len(last)} 不符")
        if any(c not in last for c in p["common"]):
            bad.append(f"{s['cn']} 的末期满血学科里缺共同学科")
    return {"pass": not bad, "problems": bad,
            "n_schools": len(p["schools"]), "n_periods": n,
            "n_events": len(p["events"])}


def generate(out_dir, schools, disciplines=None, n: int = 6) -> dict:
    """产出他校简报。`out_dir` 是**期次目录**（`out/202609`）。

    返回 `{report, json, meta, panel, check}`；`out_dir` 下只新建
    `flexible/multi_school/`，不碰该期次的复刻报告产物。
    """
    out_dir = pathlib.Path(out_dir)
    period_end = out_dir.name
    if not (len(period_end) == 6 and period_end.isdigit()):
        raise ValueError(f"out_dir 应该是期次目录（如 out/202609），收到 {str(out_dir)!r}")

    p = panel(schools, disciplines=disciplines, period_end=period_end, n=n)
    p["n_periods"] = len(p["periods"])
    text = render(p)
    check = _check(p)

    dest = out_dir / "flexible" / INTENT
    dest.mkdir(parents=True, exist_ok=True)
    md = dest / "report.md"
    md.write_text(text, encoding="utf-8")
    (dest / "brief.json").write_text(
        json.dumps(p, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    meta = {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "intent": INTENT,
        "title": TITLE,
        "backend": "rule",                  # 零模型：这里永远是 rule
        "period": p["period_end"],
        "periods": p["periods"],
        "schools": [{"cn": s["cn"], "status": s["status"], "match": s["match"],
                     "counts": s["counts"]} for s in p["schools"]],
        "common": p["common"],
        "n_charts": 0,                      # 图在阶段 3（ECharts）接，本稿只有表与句
        "check": check,
    }
    (dest / "flex_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return {"report": str(md), "json": str(dest / "brief.json"),
            "meta": str(dest / "flex_meta.json"), "panel": p, "check": check}
