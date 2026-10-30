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
    out/<期次>/flexible/multi_school/charts/*.png    图（markdown 里按 `charts/xxx.png` 相对引用）
    out/<期次>/flexible/multi_school/brief.json      机读（panel 全量，含 grid）
    out/<期次>/flexible/multi_school/flex_meta.json  元信息 + 自检

七节结构（数字全部落在表里，图和画像只是换个读法）
--------------------------------------------------
一 各期上榜学科数（表）／二 各期趋势（图）／三 学科覆盖矩阵（22 学科 × 各校）／
四 逐校画像／五 共同与差异／六 值得标注的变化／七 口径与来源。

`render` 仍然是**纯函数**：图不由它画，图名由 `charts=` 参数传进来。这样「同一输入
逐字节一致」在纯函数层可测，出图（唯一碰磁盘的那步）留在 `generate`。
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


def _flat_run(counts: list, periods: list) -> tuple[int, str | None]:
    """最长的一段「计数不变」连续期数 → `(期数, 起点期次)`。

    只数相邻相等，不做任何拟合；缺数据的期次把序列切断（`None` 不等于 `None`——
    「两期都没数」不是「两期都是同一个数」）。并列最长时取**靠后**那段（更贴当期）。
    """
    best, best_at = 0, None
    cur, cur_at = 0, None
    for i, v in enumerate(counts):
        if v is None:
            cur, cur_at = 0, None
            continue
        if cur and counts[i - 1] == v:
            cur += 1
        else:
            cur, cur_at = 1, i
        if cur >= best:
            best, best_at = cur, cur_at
    return best, (periods[best_at] if best_at is not None and best_at < len(periods) else None)


def _disc_list(items: list, limit: int = 4) -> str:
    """`[{period, cn}]` → 「微生物学（2026-01）、地球科学（2026-03）」。空给「无」。"""
    if not items:
        return "无"
    shown = [f"{x['cn']}（{_short_period(x['period'])}）" for x in items[:limit]]
    tail = f" 等 {len(items)} 个" if len(items) > limit else ""
    return "、".join(shown) + tail


def _trend_lines(p: dict, charts: list | None) -> list[str]:
    """趋势图一节。图名由调用方传（`render` 不碰磁盘），没有图就照实说。"""
    lines = ["## 二、各期趋势", ""]
    if not charts:
        return lines + ["本期未出图（`render` 是纯函数，出图在 `generate` 里做）。", ""]
    for c in charts:
        lines += [f"![{c['title']}](charts/{c['file']})", ""]
    lines += ["实心圆＝各校各期上榜学科数，缺数据的期次断开不连线；空心标记＝事件点，"
              "形状对应「值得标注的变化」一节；同一坐标只画一个点。", ""]
    return lines


def _matrix_lines(p: dict) -> list[str]:
    """22 学科 × 各校的覆盖矩阵（末期）。✓ / — 直接读 `grid.sets`，本模块不重算。

    排序＝共同 → 某校独有 → 末期均未上榜：读者从上往下看，差异自然分层。
    """
    last = p["periods"][-1]
    schools = p["schools"]
    sets = {s["cn"]: set(p["grid"]["sets"].get(s["cn"], {}).get(last) or []) for s in schools}
    ok = {s["cn"]: s["status"] == "ok" for s in schools}
    common = set(p["common"])
    idx = {s["cn"]: i for i, s in enumerate(schools)}

    rows = []
    for stem in p["disciplines"]:
        have = [stem in sets[s["cn"]] for s in schools]
        if stem in common:
            key = (0, 0, cn_of(stem))
        elif any(have):
            owner = min(idx[s["cn"]] for s, h in zip(schools, have) if h)
            key = (1, owner, cn_of(stem))
        else:
            key = (2, 0, cn_of(stem))
        rows.append((key, stem, have))
    rows.sort(key=lambda r: r[0])

    head = "| 学科 | " + " | ".join(s["cn"] for s in schools) + " | 分布 |"
    lines = ["## 三、学科覆盖矩阵", "",
             f"末期（{period_label(last)}）各校上榜学科；✓＝上榜，—＝未上榜。"
             "按「共同 → 某校独有 → 末期均未上榜」排序。", "",
             head, "|---" * (len(schools) + 2) + "|"]
    for _, stem, have in rows:
        cells = [("✓" if h else "—") if ok[s["cn"]] else "·"
                 for s, h in zip(schools, have)]
        owners = [s["cn"] for s, h in zip(schools, have) if h]
        if stem in common:
            dist = "共同"
        elif not owners:
            dist = "末期均未上榜"
        elif len(owners) == 1:
            dist = f"仅{owners[0]}"
        else:
            dist = f"{len(owners)} 校"
        lines.append(f"| {cn_of(stem)} | " + " | ".join(cells) + f" | {dist} |")
    lines.append("")
    if not all(ok.values()):
        lines += ["·＝该校未纳入 ESI，不是「未上榜」（见文末「未能纳入的学校」）。", ""]
    return lines


def _profile_lines(p: dict) -> list[str]:
    """逐校一小段：覆盖广度 / 首末变化 / 新进退出 / 最长持平。四个数全来自 `panel()`。"""
    lines = ["## 四、逐校画像", ""]
    periods = p["periods"]
    for s in p["schools"]:
        lines += [f"### {s['cn']}", ""]
        if s["status"] != "ok":
            lines += [f"未纳入：{s['note']}", ""]
            continue
        counts = s["counts"] or []
        last = counts[-1] if counts else None
        broad = (f"末期上榜 **{last}** 个学科（口径 {len(p['disciplines'])} 个）"
                 if last is not None else "末期缺数据，覆盖广度不可比")
        lines.append(f"- 覆盖广度：{broad}")
        if counts and None not in counts:
            lines.append(f"- 首末变化：{counts[0]} → {counts[-1]}（{_delta(counts)}）")
        else:
            lines.append(f"- 首末变化：{_delta(counts)}（窗口内有期次缺数据）")
        for label, got in (("新进", s["entered"]), ("退出", s["exited"])):
            head = f"{label} {len(got)} 个：" if got else f"{label}："
            lines.append(f"- {head}{_disc_list(got)}")
        run, start = _flat_run(counts, periods)
        if not run:
            lines.append("- 最长持平：—（窗口内没有可比的期次）")
        else:
            tail = f"（{_short_period(start)} 起）" if run > 1 and start else ""
            lines.append(f"- 最长持平：{run} 期{tail}")
        lines.append("")
    return lines


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


def render(p: dict, generated_at: str | None = None, charts: list | None = None) -> str:
    """panel 结果 → markdown 全文（纯函数，不碰磁盘）。

    `generated_at` 显式传入而不是在内部取当前时间——否则这个函数不再可复现，
    「同一输入逐字节一致」这条就没法测。`None` 时才取当前时间。

    `charts`：`[{file, title}]`，即已经落盘的图（文件名 + 图题）。**本函数不画图**
    ——出图是 `generate` 的事。不传就照实写「本期未出图」，不编一个指向空文件的链接。
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
        *_trend_lines(p, charts),
        *_matrix_lines(p),
        *_profile_lines(p),
        "## 五、共同与差异",
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
    out += ["", "## 六、值得标注的变化", ""]
    out += _event_lines(p)
    out += ["## 七、口径与来源", ""]
    out += [
        f"- 数据源：`{p['source']['dataset']}`（{len(p['disciplines'])} 个学科表，只读）",
        f"- 期次：{p['period_end']}；窗口回溯用台账有效期次链，不做日历减法",
        "- 上榜判据：机构英文名归一（`&`→`AND`、去 `- CHINA` 后缀、去标点）后，出现在该学科机构表中",
        "- 「共同之外另有」＝本校末期满血学科 − 共同交集，**不是「全校独有」**",
        "- 覆盖矩阵的 ✓ 取自末期学科集合，与「共同/另有」同一份数；逐校画像的四个数同源",
        "- 趋势图纵轴范围由数据决定（`charts._auto_ylim`），本稿不指定任何轴界",
        "- 「—」表示该期无数据，与「0（本期未上榜）」是两件事",
        f"- 生成时间：{generated_at}",
        "",
    ]
    out += _note_lines(p)
    return "\n".join(out).rstrip() + "\n"


def _check(p: dict, charts: list | None = None, chart_dir=None) -> dict:
    """自检：几条能一眼核的结构不变量。判据是「数字对」，不是「断言全过」。

    `charts` / `chart_dir` 给了就一并核「图真的落盘且非空」——链接指向不存在的文件，
    比没有图更糟（读者只会以为图挂了）。
    """
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
    for c in (charts or []):
        f = pathlib.Path(chart_dir) / c["file"] if chart_dir else None
        if f is None or not f.is_file() or f.stat().st_size == 0:
            bad.append(f"图 {c['file']} 没有落盘（正文会指向空链接）")
    return {"pass": not bad, "problems": bad,
            "n_schools": len(p["schools"]), "n_periods": n,
            "n_events": len(p["events"]), "n_charts": len(charts or [])}


def _write_charts(p: dict, chart_dir) -> list[dict]:
    """趋势图落盘 → `[{file, title}]`（给 `render` 拼 markdown 用）。

    只有 `status == "ok"` 的学校进图：缺席校的 counts 全是 `None`，画出来是一条
    看不见的线，图例里却占一个词条。
    """
    series = {s["cn"]: list(s["counts"] or []) for s in p["schools"] if s["status"] == "ok"}
    if not series or not p["periods"]:
        return []
    import charts                                    # 延迟导入：`render` 不该被 matplotlib 拖慢

    chart_dir = pathlib.Path(chart_dir)
    name = "trend.png"
    charts.chart_multi_line(
        series, chart_dir / name, p["periods"],
        events=[{"school": e["school"], "index": e["index"], "value": e["value"],
                 "kind": e["kind"]} for e in p["events"]],
        kind_labels=_KIND_CN,
    )
    span = f"{_short_period(p['periods'][0])}–{_short_period(p['periods'][-1])}"
    return [{"file": name, "title": f"各校各期上榜学科数（{span}）"}]


def generate(out_dir, schools, disciplines=None, n: int = 6, generated_at=None) -> dict:
    """产出他校简报。`out_dir` 是**期次目录**（`out/202609`）。

    返回 `{report, json, meta, panel, check, charts}`；`out_dir` 下只新建
    `flexible/multi_school/`，不碰该期次的复刻报告产物。

    `generated_at` 只是为「除时间外逐字节一致」留的口子（测试用），正常调用不传。
    """
    out_dir = pathlib.Path(out_dir)
    period_end = out_dir.name
    if not (len(period_end) == 6 and period_end.isdigit()):
        raise ValueError(f"out_dir 应该是期次目录（如 out/202609），收到 {str(out_dir)!r}")

    stamp = generated_at or _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    p = panel(schools, disciplines=disciplines, period_end=period_end, n=n)
    p["n_periods"] = len(p["periods"])

    dest = out_dir / "flexible" / INTENT
    dest.mkdir(parents=True, exist_ok=True)
    made = _write_charts(p, dest / "charts")
    text = render(p, generated_at=stamp, charts=made)
    check = _check(p, made, dest / "charts")

    md = dest / "report.md"
    md.write_text(text, encoding="utf-8")
    (dest / "brief.json").write_text(
        json.dumps(p, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    meta = {
        "generated_at": stamp,
        "intent": INTENT,
        "title": TITLE,
        "backend": "rule",                  # 零模型：这里永远是 rule
        "period": p["period_end"],
        "periods": p["periods"],
        "schools": [{"cn": s["cn"], "status": s["status"], "match": s["match"],
                     "counts": s["counts"]} for s in p["schools"]],
        "common": p["common"],
        "n_charts": len(made),              # 图由 charts.chart_multi_line 自绘（零模型、零新依赖）
        "charts": [c["file"] for c in made],
        "check": check,
    }
    (dest / "flex_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return {"report": str(md), "json": str(dest / "brief.json"),
            "meta": str(dest / "flex_meta.json"), "panel": p, "check": check,
            "charts": [str(dest / "charts" / c["file"]) for c in made]}
