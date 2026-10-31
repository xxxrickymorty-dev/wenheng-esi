# -*- coding: utf-8 -*-
"""监测版·多校对比报告：队列里选几所就比几所，不限数量、不限省份。

数据全部来自期次缓存（全局件一次读盘的产物）：总量表（每校一行）＋学科矩阵
（学科 × 校，格＝全球排名/榜内所数，1‰ 与 1% 分档着色）＋解读段（与单校同构：
确定性事实行 → `ai._writer.compose` 过盾 → 数字白名单 veto → 句骨架回落）。
省份不设限——这正是对比队列对「省内无对手」场景（如贵州）的意义。
"""
from __future__ import annotations

import hashlib
import html
import pathlib

from monitor import charts as mch
from monitor import insight as mi
from monitor import report as mr
from monitor import schools as sch

_e = html.escape
_cn = mi.cn_name
_fmt = lambda v: f"{v:,.0f}"          # noqa: E731


def compare_path(cns: list[str], period: str) -> pathlib.Path:
    """确定性文件名：校名**集合**相同即同一份文件（渲染按总被引排序，与队列顺序无关）。"""
    key = hashlib.md5(("|".join(sorted(set(cns))) + "|" + period).encode("utf-8")).hexdigest()[:12]
    return mr.MONITOR_ROOT / "_compare" / period / f"cmp_{key}.html"


def _school_row(cache: dict, cn: str) -> dict | None:
    s = sch.find(cn)
    if s is None:
        return None
    en = s["en"]
    total = next((r for r in cache["cn_inst"] if r[0] == en), None)
    rows = {stem: d["schools"].get(en) for stem, d in cache["fields"].items()}
    present = {stem: r for stem, r in rows.items() if r}
    norm = lambda x: " ".join(str(x).upper().replace("/", " ").split())  # noqa: E731
    entered = [stem for stem, r in present.items()
               if cache["thr1"].get(norm(stem)) and r[3] >= cache["thr1"][norm(stem)]]
    pm = [stem for stem, r in present.items() if r[0] <= cache["fields"][stem]["line"]]
    return {"cn": cn, "en": en, "tag": "985" if s["is985"] else "211",
            "total": total, "present": present, "n": len(present),
            "n_entered": len(entered), "n_pm": len(pm)}


def facts_of(cns: list[str], cache: dict) -> list[str]:
    """对比解读的事实行：总量序 + 分学科龙头（只取覆盖≥2 校的学科，免清单化）。"""
    rows = [r for r in (_school_row(cache, cn) for cn in cns) if r and r["total"]]
    if len(rows) < 2:
        return []
    out: list[str] = []
    ordered = sorted(rows, key=lambda r: r["total"][3])
    out.append(f"本次对比 {len(ordered)} 校，按总被引排序："
               + "、".join(f"{r['cn']}（第 {r['total'][1]} 名）" for r in ordered))
    lead, lag = ordered[0], ordered[-1]
    out.append(f"总被引最强是{lead['cn']}（{_fmt(lead['total'][3])}），最弱是{lag['cn']}（{_fmt(lag['total'][3])}）")
    tops = [(r["cn"], r["n"], r["n_entered"], r["n_pm"]) for r in ordered]
    out.append("；".join(f"{cn}上榜 {n}/22、前1% {ne}、前1‰ {np_}"
                        for cn, n, ne, np_ in tops))
    stems = set()
    for r in rows:
        stems |= set(r["present"])
    shared = []
    for stem in stems:
        in_rows = [(r["cn"], r["present"][stem]) for r in rows if stem in r["present"]]
        if len(in_rows) >= 2:
            best = min(in_rows, key=lambda kv: kv[1][0])
            shared.append((stem, best, len(in_rows)))
    shared.sort(key=lambda kv: kv[1][1][3] or 0, reverse=True)
    for stem, (wcn, r), k in shared[:5]:
        out.append(f"{_cn(stem)}有 {k} 校上榜，{wcn}位次最靠前（全球第 {r[0]}/{cache['fields'][stem]['m']}）")
    n_pm = sum(1 for r in rows if r["n_pm"])
    if n_pm:
        out.append(f"进入过全球前 1‰ 的有 {n_pm} 校"
                   + ("：" + "、".join(r["cn"] for r in rows if r["n_pm"]) if n_pm <= 6 else ""))
    return out


def render(cns: list[str], period: str, cache: dict, insight: dict | None = None) -> str:
    cols = [r for r in (_school_row(cache, cn) for cn in cns) if r is not None]
    unknown = [cn for cn in cns if sch.find(cn) is None]
    cols.sort(key=lambda r: -(r["total"][3] if r["total"] else 0))
    col_names = [r["cn"] for r in cols]

    # ---- 总量表（每校一行）----
    total_rows = "".join(
        f'<tr><td><b>{_e(r["cn"])}</b><span class="en">{_e(r["tag"])}</span></td>'
        + (f'<td class="n">{r["total"][1]:,}</td><td class="n">{_fmt(r["total"][2])}</td>'
           f'<td class="n">{_fmt(r["total"][3])}</td><td class="n">{r["total"][4]:.2f}</td>'
           if r["total"] else '<td class="n" colspan="4">未入册</td>')
        + f'<td class="n">{r["n"]} / 22</td><td class="n">{r["n_entered"]}</td>'
          f'<td class="n">{r["n_pm"]}</td></tr>'
        for r in cols)

    # ---- 学科矩阵（union 学科 × 校；格＝全球排名/榜内所数，分档着色）----
    stems = sorted({stem for r in cols for stem in r["present"]},
                   key=lambda st: (
                       -sum(1 for r in cols if st in r["present"]),
                       min((r["present"][st][0] for r in cols if st in r["present"]), default=0)))
    matrix_rows = []
    for stem in stems:
        cells = []
        for r in cols:
            hit = r["present"].get(stem)
            if not hit:
                cells.append('<td class="n dim">—</td>')
                continue
            d = cache["fields"][stem]
            cls = "pm" if hit[0] <= d["line"] else "ok"
            cells.append(f'<td class="n {cls}">{hit[0]}<i>/{d["m"]}</i></td>')
        matrix_rows.append(
            f'<tr><td><b>{_e(_cn(stem))}</b><span class="en">{_e(stem)}</span></td>'
            + "".join(cells) + "</tr>")
    matrix_head = "".join(f'<th class="n">{_e(n)}</th>' for n in col_names)

    # ---- 恰好 2 校：逐学科位次哑铃（都上榜学科按位次差降序取前 8）；>2 校矩阵已足够 ----
    dumbbell_html, num_matrix = "", "二"
    if len(cols) == 2:
        a, b = cols
        shared = sorted((st for st in stems if st in a["present"] and st in b["present"]),
                        key=lambda st: -abs(a["present"][st][0] - b["present"][st][0]))[:8]
        if shared:
            rows_dl = [(_cn(st), a["present"][st][0], b["present"][st][0]) for st in shared]
            dumbbell_html = (
                '<section>\n<h2><span class="num">二</span>逐学科位次哑铃</h2>\n'
                + mch.dumbbell(rows_dl, name_a=a["cn"], name_b=b["cn"])
                + '\n<p class="note">排名越小越好；只取两校都上榜学科中位次差最大的前 8 个。</p>\n</section>')
            num_matrix = "三"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{len(cols)} 校对比 · {period}</title>
<style>{mr._CSS}
.mwrap{{overflow-x:auto;margin-top:16px}}
.mtable{{min-width:{520 + 110 * max(len(cols), 1)}px}}
.mtable td.n,.mtable th.n{{text-align:right}}
td.pm{{background:var(--warn-bg)}}td.ok{{background:var(--ok-bg)}}
td.dim{{color:var(--muted)}}td.n i{{font-style:normal;font-size:11px;color:var(--muted)}}
</style>
</head>
<body>
<header class="top wrap"><span>监测版 · 对比件</span><span>生成 {_e(cache["built"])}</span></header>
<div class="wrap">
<h1>{len(cols)} 校 · 学科对比</h1>
<p class="lead">队列自由选校，不限省份、不限数量。数据面＝<b>{_e(period)} 期 ESI 全局件</b>，数字可回溯到包内原始行。</p>
<p class="meta">对比顺序（按总被引降序）：{'、'.join(_e(n) for n in col_names)}
{('；名单外未识别：' + _e('、'.join(unknown))) if unknown else ''}</p>

<section>
<h2><span class="num">一</span>总量对比</h2>
<table>
<thead><tr><th>学校</th><th class="n">全球总排名</th><th class="n">论文</th><th class="n">总被引</th><th class="n">篇均</th><th class="n">上榜</th><th class="n">前 1%</th><th class="n">前 1‰</th></tr></thead>
<tbody>{total_rows}</tbody>
</table>
<p class="note">上榜＝22 学科全球榜内搜到该校；前 1%＝被引 ≥ 该学科机构阈值；前 1‰＝排名压过 1‰ 线（第 ⌊(m+1)/10⌋ 位）。</p>
</section>

{dumbbell_html}
<section>
<h2><span class="num">{num_matrix}</span>学科矩阵（全球排名 / 榜内所数）</h2>
<div class="mwrap"><table class="mtable">
<thead><tr><th>学科</th>{matrix_head}</tr></thead>
<tbody>{''.join(matrix_rows)}</tbody>
</table></div>
<p class="note">着色＝档位：<span class="pill pm">前 1‰</span> <span class="pill ok">前 1%</span>；「—」＝该校该学科未上榜（无被引数据，不外推）。未入册校不进矩阵。</p>
</section>

{mr._insight_section(insight, num="四" if dumbbell_html else "三")}

<footer>
数据来源：Clarivate ESI（Essential Science Indicators）{_e(period)} 期全局件（{_e(cache.get("download") or "—")} 下载）；
对比件按队列生成，学校与学科覆盖以当期包为准。派生算法同单校报告页脚。
生成：文衡监测版引擎 <code>src/monitor/compare.py</code>（{_e(cache["built"])}）。
</footer>
</div>
</body>
</html>
"""


def generate(cns: list[str], period: str | None = None) -> pathlib.Path:
    """生成（或复用）一份多校对比报告。名单内有未知校 → KeyError（编程错误面）。"""
    period = period or mr.latest_period()
    if not period:
        raise FileNotFoundError("数据与复现/ESI数据/ 下没有可用的 ESI 期次目录")
    for cn in cns:
        if sch.find(cn) is None:
            raise KeyError(cn)
    # 去重保序
    seen: list[str] = []
    for cn in cns:
        if cn not in seen:
            seen.append(cn)
    cache = mr.load_cache(period) or mr.build_cache(period)
    ins: dict | None = None
    try:
        facts = facts_of(seen, cache)
        if facts:
            safe = "；".join(facts) + "。各表数字即原始值，未做换算。"
            topic = (f"为 {len(seen)} 所高校的 {period} 期 ESI 学科对比报告写一段总体解读："
                     "150 字以内、不分点、不写建议，只概括校间格局与分学科强弱；"
                     "数字只准用事实摘要里出现过的。")
            from ai import _writer                                          # noqa: PLC0415
            st: dict = {}
            text = _writer.compose(topic, facts=facts, safe=safe, period="",
                                   label="monitor/insight_compare",
                                   veto=lambda t: mi.number_guard(t, [topic, *facts]),
                                   status=st)
            ins = {"text": text, "mode": "model" if st.get("mode") == "model" else "rule"}
    except Exception:                                                   # noqa: BLE001
        ins = None
    out = compare_path(seen, period)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(seen, period, cache, insight=ins), encoding="utf-8")
    return out
