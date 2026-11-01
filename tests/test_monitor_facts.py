# -*- coding: utf-8 -*-
"""校次事实层（20261101 C6）一致性测试：facts 唯一派生，三处消费逐项相等。

钉死「同一校同期」下：facts 层输出 ↔ report.report_data 渲染列、compare._school_row
对比列、insight.facts_of 事实行逐项相等；进位事件在 report 时间轴文字清单与
insight 事实行之间同源（原来靠人工一致的两份判定，现在同一份 facts.entry_events）。
数据依赖与登记簿规则同 test_monitor_report.py。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from _guard_registry import skip_unless            # noqa: E402
from monitor import compare as mcmp                # noqa: E402
from monitor import facts as mfacts                # noqa: E402
from monitor import insight as mi                  # noqa: E402
from monitor import report as mr                   # noqa: E402
from monitor import schools as sch                 # noqa: E402

_PERIOD = mr.latest_period()
_cache_probe = lambda: bool(_PERIOD) and mr.cache_path(_PERIOD).exists()   # noqa: E731
_trend_probe = lambda: (mr.MONITOR_ROOT / "_trend" / "_index.json").exists()   # noqa: E731

_CN = "海南大学"


def _fmt(v) -> str:
    return f"{v:,.0f}"


def _expected_row_cells(cache: dict, sf: dict, stem: str) -> list[str]:
    """站位表 11 列的期望值：数字取自 facts（present 行/mine_sum），格式＝装配层契约。"""
    r = sf["present"][stem]
    m = cache["fields"][stem]["m"]
    gp = cache.get("global_papers") or {}
    g_sum, mine_sum = sum(gp.values()), sf["mine_sum"]
    gf = gp.get(mr.norm(stem))
    rca = (f"×{(r[2] / mine_sum) / (gf / g_sum):.2f}"
           if g_sum and mine_sum and gf and r[2] is not None else "—")
    pct = f"前 {r[0] / m * 100:.1f}%" if m else "—"
    return [mr.CN[stem], f"{r[0]} / {m}", pct, str(r[1]), _fmt(r[2]), _fmt(r[3]),
            f"{r[4]:.2f}", f"{r[5]:.0f}", f"{r[6]:.0f}", rca,
            "前 1‰" if r[0] <= cache["fields"][stem]["line"] else "前 1%"]


def test_facts_chemistry_and_agri_match_report_columns():
    """海大 202609：facts 的化学/农业科学行值与缓存原始行一致，report_data 渲染列逐格相等。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    en = sch.find(_CN)["en"]
    sf = mfacts.school_facts(cache, en)
    # facts ↔ 缓存原始行（含 cn_rank 宽口径 123）与接近度原始量
    chem = cache["fields"]["Chemistry"]["schools"][en]
    assert sf["present"]["Chemistry"] == chem
    assert sf["prox"]["Chemistry"] == chem[3] / cache["thr1"]["CHEMISTRY"]
    assert sf["miss"] == [s for s in mr.STEMS if s not in sf["present"]], "miss 必须 STEMS 序"
    # report_data 渲染列逐格相等（化学＝前 1% 档；农业科学＝非化学学科且前 1‰ 档）
    d = mr.report_data(_CN, _PERIOD, cache)
    t1 = d["sections"][0]["table"]
    for stem in ("Chemistry", "Agricultural Sciences"):
        assert stem in t1["subs"], f"{stem} 应在海大在榜学科里"
        row = t1["rows"][t1["subs"].index(stem)]
        assert row == _expected_row_cells(cache, sf, stem), f"{stem} 渲染列与 facts 不等"
    assert t1["rows"][t1["subs"].index("Chemistry")][10] == "前 1%"
    assert t1["rows"][t1["subs"].index("Agricultural Sciences")][10] == "前 1‰"
    # nums 的前 1‰ 计数与名单也必须出自 facts（note 按被引降序 pairs）
    assert d["nums"][3]["value"] == str(len(sf["pm"]))
    assert d["nums"][3]["note"] == "、".join(mr.CN[st] for st, _r in sf["pairs"]
                                             if st in set(sf["pm"]))


def test_facts_matches_school_row_columns():
    """compare._school_row 对比列与 facts 逐项相等（海大全量；政法＝未入围零值）。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    sf = mfacts.school_facts(cache, sch.find(_CN)["en"])
    row = mcmp._school_row(cache, _CN)
    assert row["total"] == sf["total"] and row["present"] == sf["present"]
    assert row["n"] == len(sf["present"])
    assert row["n_entered"] == len(sf["entered"])
    assert row["n_pm"] == len(sf["pm"])
    assert row["n_pm"] == 2, "海大 202609 应 2 学科进前 1‰（农业科学、植物与动物学）"
    # 未入围校：_school_row 与 facts 同为零值/None
    row2 = mcmp._school_row(cache, "中国政法大学")
    sf2 = mfacts.school_facts(cache, sch.find("中国政法大学")["en"])
    assert sf2["total"] is None and sf2["present"] == {} and len(sf2["miss"]) == 22
    assert row2["total"] is None and row2["n"] == 0
    assert row2["n_entered"] == 0 and row2["n_pm"] == 0


def test_facts_matches_insight_lines():
    """insight.facts_of 事实行与 facts 逐项相等（海大；未入围校整表相等）。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    sf = mfacts.school_facts(cache, sch.find(_CN)["en"])
    rows = sf["present"]
    n = len(rows)
    facts = mi.facts_of(_CN, cache)
    # 逐条钉「映射自 facts 字段」的事实行（条件结构与 insight 渲染契约一致）
    assert f"{_CN}（211 工程）本期上榜 {n}/22 学科" in facts
    assert f"全部 {n} 个上榜学科已进入 ESI 前 1%" in facts, "海大 entered 应等于在榜数"
    pm = sf["pm"]
    best = min(pm, key=lambda st: rows[st][0])
    assert (f"{len(pm)} 个学科进入全球前 1‰："
            f"{'、'.join(mi.cn_name(x) for x in sorted(pm, key=lambda x: rows[x][0]))}"
            f"；其中{mi.cn_name(best)}位次最靠前（全球第 {rows[best][0]}/{cache['fields'][best]['m']}）") in facts
    top_cites = max(rows.items(), key=lambda kv: kv[1][3])
    assert (f"被引最强学科是{mi.cn_name(top_cites[0])}"
            f"（被引 {top_cites[1][3]:,.0f}，篇均 {top_cites[1][4]:.2f}）") in facts
    assert f"全球机构总排名 {sf['total'][1]}/{cache['n_inst']}（按总被引）" in facts
    assert f"未上榜 {22 - n} 学科（低于收录线或未入册）无被引数据，报告不外推" in facts
    # 未入围校：insight 整表＝未进入单行（facts present 空的早退语义）
    facts2 = mi.facts_of("中国政法大学", cache)
    assert facts2 == ["中国政法大学（211 工程）本期未进入 22 学科全球机构榜"
                      "（低于收录线或未入册），报告如实呈现，不外推"]


def test_facts_unregistered_school_matches_report():
    """未入围校（政法）：facts 零值 ↔ report_data 的 absent/placeholder/空 nums 呈现。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    sf = mfacts.school_facts(cache, sch.find("中国政法大学")["en"])
    d = mr.report_data("中国政法大学", _PERIOD, cache)
    assert sf["total"] is None and sf["present"] == {} and sf["pm"] == []
    assert d["nums"] == [] and d["absent_note"], "未入册 → absent_note 承载，无 nums"
    assert d["sections"][0]["table"]["placeholder"], "站位表落 placeholder 合并行"
    assert d["sections"][1]["notes"][0] == "本期无学科进入前 1‰。"


def test_entry_events_timeline_and_insight_same_source():
    """进位事件同源：report 时间轴文字清单与 insight 事实行都逐字出自 facts.entry_events。"""
    if not _cache_probe():
        skip_unless("监测版期次缓存未建", _cache_probe)
    if not _trend_probe():
        skip_unless("趋势库未建（monitor_data/_trend/_index.json 缺）", _trend_probe)
    import monitor.trend as mtrend
    cache = mr.load_cache(_PERIOD)
    sf = mfacts.school_facts(cache, sch.find(_CN)["en"])
    tr = mtrend.combine(sch.find(_CN)["en"])
    evf = mfacts.entry_events(tr, sf["present"])
    assert evf, "海大在趋势窗内应有可判定的进位事件（真实趋势库）"
    # report 时间轴 items ↔ facts 事件逐字同源
    d = mr.report_data(_CN, _PERIOD, cache)
    items = (d["sections"][2].get("timeline") or {}).get("items") or []
    expected = []
    for stem in mr.STEMS:
        ef = evf.get(stem)
        if not ef:
            continue
        if ef["first1"]:
            expected.append(f"{mr.CN[stem]}：{ef['first1']} 起进入前 1%（{ef['n_seq']} 期在榜）")
        if ef["firstpm"]:
            expected.append(f"{mr.CN[stem]}：{ef['firstpm']} 起进入前 1‰（{ef['n_seq']} 期在榜）")
    assert expected, "海大应有进位事件行"
    assert items == expected, "时间轴文字清单必须与 facts 事件逐字同源"
    # insight 事实行同源：解读只点名「最早/最近/前 1‰ 计数」——逐一由 facts 事件
    # 按解读的行文契约（tl 排序取首尾）推导并整句比对
    tl = sorted((p, f"{mr.CN[stem]} {p} 起进入前 1{kind}")
                for stem, ef in evf.items()
                for p, kind in ((ef["first1"], "%"), (ef["firstpm"], "‰")) if p)
    joined = "；".join(mi.facts_of(_CN, cache, tr))
    assert tl
    assert "进位时间线上最早的是" + tl[0][1] in joined, "解读「最早」必须＝facts 事件最小期次"
    assert "最近的一次是" + tl[-1][1] in joined, "解读「最近」必须＝facts 事件最大期次"
    pm_events = [x for _, x in tl if "1‰" in x]
    if len(pm_events) >= 2:
        assert (f"前 1‰ 事件共 {len(pm_events)} 次，"
                f"近一次为{pm_events[-1].split(' ', 1)[-1]}") in joined
