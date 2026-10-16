# -*- coding: utf-8 -*-
"""结语句句骨架：模板 + 数字槽（只填台账可算数；台账外用手工槽标记）。

输出键 → 报告段落映射：
  p1 概述·数据来源段      p2 概述·前1%与前1‰段
  p3 概述·亮点与警示段    p4 概述·顶尖论文段
  trend 学校发展趋势段    situation 学科发展态势段（22 学科升降统计）
  cover_issue 封面期数     cover_month 封面年月
"""
import period as period_mod

from parse_ledger import DISCIPLINES_CN

MANUAL = "【手工：{}】"


def cn_name(en):
    return DISCIPLINES_CN.get(en, en)


def updown_phrase(delta, unit="位"):
    if delta > 0:
        return f"上升{delta}{unit}"
    if delta < 0:
        return f"下降{abs(delta)}{unit}"
    return f"位次不变"


def top3_text(groups):
    """[(count, [disc_en,...]), ...] → '化学44篇、材料科学36篇、工程学和植物与动物学同为29篇'"""
    parts = []
    for count, discs in groups:
        names = [cn_name(d) for d in discs]
        if len(names) == 1:
            parts.append(f"{names[0]}{count}篇")
        else:
            parts.append("和".join(names) + f"同为{count}篇")
    return "、".join(parts)


def _college_clauses(college):
    """学院统计（college_stats.json）→ 文句子句素材；缺数据时返回 None（沿用旧稿措辞）。"""
    if not college or not college.get("units"):
        return None
    units = college["units"]                      # 已按（发文量降序, 被引降序）
    by_cites = sorted(units, key=lambda u: (-u["cites"], u["unit"]))[:3]
    tot = college.get("n_cites") or sum(u["cites"] for u in units) or 1
    return {
        "n_subjects": college.get("n_subjects") or 0,
        "n_units": college.get("n_units") or len(units),
        "by_papers": units[:3],
        "by_cites": [(u["unit"], u["cites"] / tot * 100) for u in by_cites],
    }


def _fmt_period_cn(period):
    """202709 → '2027年9月'；None/空 → None。"""
    if not period:
        return None
    p = str(int(period))
    return f"{p[:4]}年{int(p[4:])}月"


def _forecast_index(forecast):
    """forecast_charts.json 的 charts 列表 → {(index, task): meta}（脏数据跳过）。"""
    out = {}
    for c in forecast or []:
        try:
            out[(int(c["index"]), str(c["task"]))] = c
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _cross_clauses(model1, model2, cross1, cross2):
    """模型说明子句（rick 2026-09-24 定稿样式）：
    两线同名模型 →「采用拟合度较好的X得到的预测显示，其…」；
    不同模型 →「采用拟合度较好的X与Y分别对被引频次、国内排名进行预测，…」。
    """
    if model1 and model1 == model2:
        head = f"采用拟合度较好的{model1}得到的预测显示，其"
    else:
        head = f"采用拟合度较好的{model1}与{model2}分别对被引频次、国内排名进行预测，"
    t1 = (f"被引频次预测曲线预计于{_fmt_period_cn(cross1)}前后越过ESI前1%阈值预测曲线"
          if cross1 else "被引频次预测曲线在预测区间内尚未越过ESI前1%阈值预测曲线")
    t2 = (f"国内排名预测曲线预计于{_fmt_period_cn(cross2)}前后与国内ESI前1%机构数预测曲线交叉"
          if cross2 else "国内排名预测曲线在预测区间内尚未与国内ESI前1%机构数预测曲线交叉")
    return f"{head}{t1}，{t2}"


def _prox_phrases(tail):
    """近一年接近度尾迹 → (趋势描述, 发展力度评价)；数据不足返回 (None, None)（保留手工槽）。"""
    vals = [float(v) for v in (tail or []) if v is not None and v == v]
    if len(vals) < 2:
        return None, None
    rising = all(b >= a for a, b in zip(vals, vals[1:]))
    net = vals[-1] - vals[0]
    if rising:
        return "一直呈稳步上升趋势", "持续增强"
    if net > 0:
        return "呈波动上升趋势", "持续增强"
    return "呈波动趋势", "需要继续加强"


def _eta_goal(cross1, cross2):
    """第一学科口径：取两线较晚的交叉点 →「可能将在2027年前后实现」；无交叉点保留手工槽。"""
    pts = [int(c) for c in (cross1, cross2) if c]
    if not pts:
        return MANUAL.format("预计时间（两线交叉点）")
    return f"可能将在{max(pts) // 100}年前后实现"


def _eta_expect(cross1, cross2):
    """第二学科口径：两线跨年（11 月/次年 1 月型）→「有望在2027年底至2028年初进入ESI前1%」；
    否则以较晚交叉点 →「有望在YYYY年前后进入ESI前1%」；无交叉点保留手工槽。"""
    pts = sorted(int(c) for c in (cross1, cross2) if c)
    if not pts:
        return MANUAL.format("预计时间（两线交叉点）")
    first, last = pts[0], pts[-1]
    if last // 100 - first // 100 == 1 and first % 100 >= 10 and last % 100 <= 3:
        return f"有望在{first // 100}年底至{last // 100}年初进入ESI前1%"
    return f"有望在{last // 100}年前后进入ESI前1%"


def build(facts, period, prev, college=None, forecast=None, targets=None):
    """句骨架 → 各段落文本。

    `targets`（2026-10-16，可选）：报告预测章的目标学科（**中文名**，顺序即 1/2 号位）——
    来自 `forecast_charts.json` 的 `report_subjects`（改选学科优先的产物）。
    文字段与预测图必须同一套学科；不传＝按接近度前二（老行为）。
    明细取自 `facts["not_entered"]`（全量）；缺该键的老 facts 回落 `top2_not_entered`。
    """
    y, m = period[:4], str(int(period[4:]))
    prev_m = str(int(prev[4:]))
    p1 = facts
    best = p1["best_1permille"]
    col = _college_clauses(college)
    d1, c1 = p1["top2_prox_change"][0]
    d2, c2 = p1["top2_prox_change"][1]
    d3 = p1["worst_cn_rank"]

    qianfen = ("，其中已有学科进入前1‰" if p1["any_1permille"]
               else "，但暂时还没有前1‰的学科")
    years = p1.get("permille_years_est")
    if years:
        years_text = f"按此增长率，{cn_name(best['discipline'])}进入ESI前1‰的时间预计还需要{years}年左右。"
    else:
        years_text = f"按当前增速尚难估算{cn_name(best['discipline'])}进入ESI前1‰的时间。"

    if best["prox_prev_pct"] is not None:
        prev_clause = f"此数值较{prev_m}月上升{best['prox_pct'] - best['prox_prev_pct']:.2f}%，"
    else:
        prev_clause = f"此数值较{prev_m}月{MANUAL.format('升幅%（台账缺上期1‰阈值）')}，"
    p2 = (f"本期我校仍保持有ESI前1%学科{p1['n_disc_1pct']}个，位列云南省高校首位"
          f"{qianfen}。我校目前与ESI前1‰接近度较高的学科为{cn_name(best['discipline'])}，"
          f"接近度为{best['prox_pct']:.2f}%，{prev_clause}较一年前上升"
          f"{MANUAL.format('去年同期升幅%')}，{years_text}")

    p3 = (f"本期我校{cn_name(d1)}和{cn_name(d2)}在ESI前1%接近度方面较{prev_m}月表现较好，"
          f"分别上升{c1:.2f}%和{c2:.2f}%；值得关注的是{cn_name(d3['discipline'])}国内排名"
          f"继续呈现较大降幅，该学科本期较{prev_m}月下降了{d3['drop']}位，国内排名为{d3['rank']}。")

    if col:
        p4 = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加{p1['top_papers_delta']}篇，"
              f"分别有{col['n_subjects']}个学科来自{col['n_units']}个学院。"
              f"论文量排名前三位的学科分别是{top3_text(p1['top3_groups'])}。"
              f"本期顶尖论文量及其被引频次学院贡献度排名前三位的是："
              f"{'、'.join(u for u, _p in col['by_cites'])}。")
    else:
        p4 = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加{p1['top_papers_delta']}篇，"
              f"覆盖{MANUAL.format('学科数')}个学科。"
              f"论文量排名前三位的学科分别是{top3_text(p1['top3_groups'])}。")

    # ⚠️ 国内机构 / 国内高校是**两个独立 delta**，不能合并成一个值。
    # 2026-09-18 逐格回测发现：旧版写成「…排名较X月均{...inst_delta}…」，
    # 但原件第 2/3 期两者并不相等（202603: +2/+1、202605: +3/+2；台账实测一致），
    # 于是机器稿在 3 期里有 3 期把高校升降说错。现值各说各的。
    trend = (f"与上期数据相比，我校国内机构排名较{p1['prev_label']}"
             f"{updown_phrase(p1['rank_cn_inst_delta'])}，排在{p1['rank_cn_inst_now']}名；"
             f"国内高校排名较{p1['prev_label']}{updown_phrase(p1['rank_cn_uni_delta'])}，"
             f"排在{p1['rank_cn_uni_now']}名；本期云南大学国际排名{p1['rank_intl_now']}位，"
             f"较上期{updown_phrase(p1['rank_intl_delta'])}。")

    situation = (f"本期云南大学22个ESI学科从国内排名上看，有{p1['rank_up']}个学科排名上升，"
                 f"有{p1['rank_down']}个学科排名下降，{p1['rank_flat']}个学科排名与{prev_m}月持平；"
                 f"本期我校{cn_name(d1)}和{cn_name(d2)}在接近度方面较{prev_m}月表现较好，"
                 f"分别上升{c1:.2f}%和{c2:.2f}%；{cn_name(d3['discipline'])}继续呈现排名下降现象，"
                 f"本期较{prev_m}月下降了{d3['drop']}位，国内排名为{d3['rank']}。")

    # 期号口径唯一在 `period.issue_of`：早于锚点直接报错，不给封面算假期号。
    idx, total = period_mod.issue_of(period)

    # 预测章两个目标学科：targets（report_subjects）优先，缺位按接近度补齐；
    # 不传 targets ＝ entries 前二（与老行为一致）。明细来自全量 not_entered。
    entries = p1.get("not_entered") or p1["top2_not_entered"]
    picked = []
    if targets:
        by_cn = {cn_name(e["discipline"]): e for e in entries}
        picked = [by_cn[t] for t in targets if t in by_cn and by_cn[t] not in picked]
    for e in entries:
        if len(picked) >= 2:
            break
        if e not in picked:
            picked.append(e)
    ne1, ne2 = picked[0], picked[1]
    top3_paren = "、".join(f"{cn_name(d)}（{c}篇）"
                          for c, discs in p1["top3_groups"] for d in discs)
    sit_head = (f"本期云南大学ESI前1%学科继续保持{p1['n_disc_1pct']}个。下图红线为ESI前1%基线。"
                f"各数值为论文被引频次与该学科进入ESI阈值的比值百分数，通过该图展示出我校各学科"
                f"与ESI全球前1%学科的接近度，数值大于100%则为ESI前1%学科。")
    if col:
        by_p = "、".join(f"{u['unit']}（{u['papers']}篇）" for u in col["by_papers"])
        by_c = "、".join(f"{u}（{p:.2f}%）" for u, p in col["by_cites"])
        top_section = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加"
                       f"{p1['top_papers_delta']}篇，分别有{col['n_subjects']}个学科来自"
                       f"{col['n_units']}个学院。论文量排名前三位的学科分别是{top3_paren}。"
                       f"本期顶尖论文量排名前3位的学院分别是{by_p}；"
                       f"顶尖论文被引频次学院贡献度排名前三位的是：{by_c}。")
    else:
        top_section = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加"
                       f"{p1['top_papers_delta']}篇，覆盖{MANUAL.format('学科数')}个学科。"
                       f"论文量排名前三位的学科分别是{top3_paren}。")

    def _dir_chg(v):
        return ("上升" if v >= 0 else "下降") + f"{abs(v):.2f}%"

    fc1 = (f"我校{cn_name(ne1['discipline'])}学科的发展{MANUAL.format('趋势描述')}，"
           f"本期该学科的ESI前1%接近度达到{ne1['prox_pct']:.2f}%，较上期{_dir_chg(ne1['chg'])}；"
           f"学科如按目前的态势发展，进入ESI前1%的目标{MANUAL.format('预计时间（两线交叉点）')}。")
    fc2 = (f"我校{cn_name(ne2['discipline'])}学科本期ESI前1%接近度为{ne2['prox_pct']:.2f}%，"
           f"较上期{_dir_chg(ne2['chg'])}。从预测情况看，{MANUAL.format('发展力度评价')}。")

    # 有预测图元数据（forecast_charts.json）时把上面的手工槽换成模型说明：
    # 数字/日期只来自 report_forecast 的 V1 推荐模型结果，措辞分档是确定的（见 _prox_phrases）。
    fm = _forecast_index(forecast)
    f1c, f1r = fm.get((1, "citation")), fm.get((1, "rank"))
    f2c, f2r = fm.get((2, "citation")), fm.get((2, "rank"))
    trend1, _strength1 = _prox_phrases(ne1.get("prox_tail"))
    _trend2, strength2 = _prox_phrases(ne2.get("prox_tail"))
    if f1c and f1r and f2c and f2r and trend1 and strength2:
        fc1 = (f"我校{cn_name(ne1['discipline'])}学科的发展{trend1}，本期该学科的ESI前1%接近度达到"
               f"{ne1['prox_pct']:.2f}%，较上期{_dir_chg(ne1['chg'])}；从预测情况看，"
               f"{_cross_clauses(f1c['model'], f1r['model'], f1c.get('first_crossing'), f1r.get('first_crossing'))}，"
               f"学科如按目前的态势发展，进入ESI前1%的目标"
               f"{_eta_goal(f1c.get('first_crossing'), f1r.get('first_crossing'))}。（两线交叉点）")
        fc2 = (f"我校{cn_name(ne2['discipline'])}学科本期ESI前1%接近度为{ne2['prox_pct']:.2f}%，"
               f"较上期{_dir_chg(ne2['chg'])}。从预测情况看，我校{cn_name(ne2['discipline'])}进入ESI前1%的"
               f"发展力度{strength2}，"
               f"{_cross_clauses(f2c['model'], f2r['model'], f2c.get('first_crossing'), f2r.get('first_crossing'))}，"
               f"{_eta_expect(f2c.get('first_crossing'), f2r.get('first_crossing'))}。")

    return {
        "p1": (f"据{MANUAL.format('ESI发布日期')}ESI最新数据显示（ESI数据覆盖时间范围为"
               f"{p1['coverage_window']}），本期全球共有{MANUAL.format('当期机构总数')}个机构登上"
               f"ESI前1%榜单，我校位于第{p1['rank_intl_now']}位，较上期"
               f"{updown_phrase(p1['rank_intl_delta'])}。"),
        "p2": p2, "p3": p3, "p4": p4, "trend": trend, "situation": situation,
        "situation_head": sit_head,
        "table2_title": f"云南大学ESI学科发展主要参数情况（{y}年{int(m)}月）",
        "top_section": top_section,
        "forecast_p1": fc1, "forecast_p2": fc2,
        "province_p": (f"本期云南高校ESI前1%学科总数为{MANUAL.format('总数')}个，"
                       f"与上期相比增加{MANUAL.format('增减')}个，{MANUAL.format('新晋学科描述')}。"),
        "cover_issue": f"{y}年第{idx}期（总第{total}期）",
        "cover_month": f"{y}年{int(m)}月",
    }


if __name__ == "__main__":
    import json
    import pathlib
    import sys
    ld = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/202607")
    facts = json.loads((ld / "overview_facts.json").read_text(encoding="utf-8"))
    texts = build(facts, "202607", "202605")
    for k, v in texts.items():
        print(f"--- {k} ---")
        print(v)
