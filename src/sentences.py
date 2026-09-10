# -*- coding: utf-8 -*-
"""结语句句骨架：模板 + 数字槽（只填台账可算数；台账外用手工槽标记）。

输出键 → 报告段落映射：
  p1 概述·数据来源段      p2 概述·前1%与前1‰段
  p3 概述·亮点与警示段    p4 概述·顶尖论文段
  trend 学校发展趋势段    situation 学科发展态势段（22 学科升降统计）
  cover_issue 封面期数     cover_month 封面年月
"""
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


def build(facts, period, prev):
    y, m = period[:4], str(int(period[4:]))
    prev_m = str(int(prev[4:]))
    p1 = facts
    best = p1["best_1permille"]
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

    p4 = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加{p1['top_papers_delta']}篇，"
          f"分别有{MANUAL.format('学科数')}个学科来自{MANUAL.format('学院数')}个学院。"
          f"论文量排名前三位的学科分别是{top3_text(p1['top3_groups'])}。"
          f"本期顶尖论文量及其被引频次学院贡献度排名前三位的是：{MANUAL.format('学院贡献度前三')}。")

    trend = (f"与上期数据相比，我校在国内机构及高校的排名较{p1['prev_label']}均"
             f"{updown_phrase(p1['rank_cn_inst_delta'])}，国内机构排名{p1['rank_cn_inst_now']}，"
             f"国内高校排名{p1['rank_cn_uni_now']}；本期云南大学国际排名{p1['rank_intl_now']}位，"
             f"较上期{updown_phrase(p1['rank_intl_delta'])}。")

    situation = (f"本期云南大学22个ESI学科从国内排名上看，有{p1['rank_up']}个学科排名上升，"
                 f"有{p1['rank_down']}个学科排名下降，{p1['rank_flat']}个学科排名与{prev_m}月持平；"
                 f"本期我校{cn_name(d1)}和{cn_name(d2)}在接近度方面较{prev_m}月表现较好，"
                 f"分别上升{c1:.2f}%和{c2:.2f}%；{cn_name(d3['discipline'])}继续呈现排名下降现象，"
                 f"本期较{prev_m}月下降了{d3['drop']}位，国内排名为{d3['rank']}。")

    idx = (int(period[:4]) - 2026) * 6 + (int(period[4:]) + 1) // 2
    total = 38 + idx - 4

    ne1, ne2 = p1["top2_not_entered"][0], p1["top2_not_entered"][1]
    top3_paren = "、".join(f"{cn_name(d)}（{c}篇）"
                          for c, discs in p1["top3_groups"] for d in discs)
    sit_head = (f"本期云南大学ESI前1%学科继续保持{p1['n_disc_1pct']}个。下图红线为ESI前1%基线。"
                f"各数值为论文被引频次与该学科进入ESI阈值的比值百分数，通过该图展示出我校各学科"
                f"与ESI全球前1%学科的接近度，数值大于100%则为ESI前1%学科。")
    top_section = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加"
                   f"{p1['top_papers_delta']}篇，分别有{MANUAL.format('学科数')}个学科来自"
                   f"{MANUAL.format('学院数')}个学院。论文量排名前三位的学科分别是{top3_paren}。"
                   f"本期顶尖论文量排名前3位的学院分别是{MANUAL.format('学院前三（篇数）')}；"
                   f"顶尖论文被引频次学院贡献度排名前三位的是：{MANUAL.format('学院贡献度（%）')}。")

    def _dir_chg(v):
        return ("上升" if v >= 0 else "下降") + f"{abs(v):.2f}%"

    fc1 = (f"我校{cn_name(ne1['discipline'])}学科的发展{MANUAL.format('趋势描述')}，"
           f"本期该学科的ESI前1%接近度达到{ne1['prox_pct']:.2f}%，较上期{_dir_chg(ne1['chg'])}；"
           f"学科如按目前的态势发展，进入ESI前1%的目标{MANUAL.format('预计时间（两线交叉点）')}。")
    fc2 = (f"我校{cn_name(ne2['discipline'])}学科本期ESI前1%接近度为{ne2['prox_pct']:.2f}%，"
           f"较上期{_dir_chg(ne2['chg'])}。从预测情况看，{MANUAL.format('发展力度评价')}。")

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
