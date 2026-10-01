# -*- coding: utf-8 -*-
"""从台账计算第 P 期报告所需的全部数值（只读台账，不产新数据）。

Table2 十一列口径（已用第 4 期实物反推验证）：
  国内排名/变化 = new_cn.rank[P] + Δ(new_cn.rank[Q]->[P])  → "139/↓4"
  论文数/CNCI/总被引/1%阈值/1‰阈值/顶尖论文 = 宽表 [P]（顶尖论文空白=空）
  1%阈值差 = 总被引 - 1%阈值
  千分位 = new_intl.rank_pct[P] × 10（3 位小数）
  接近度较Q月 = (接近度[P] - 接近度[Q]) × 100 → "↑33.87%"
"""
import pathlib

import pandas as pd


def load_wide(out_dir="out/202607"):
    wide = {m: pd.read_parquet(f"{out_dir}/wide/{m}.parquet") for m in
            ["total_cites", "papers", "cnci", "proximity_1pct", "threshold_1pct", "top_papers"]}
    longdf = pd.read_parquet(f"{out_dir}/ledger_long.parquet")
    new_intl = longdf[(longdf.source == "new_intl")].pivot_table(
        index="discipline", columns=["metric", "period"], values="value")
    new_cn = longdf[(longdf.source == "new_cn")].pivot_table(
        index="discipline", columns=["metric", "period"], values="value")
    thr = pd.read_parquet(f"{out_dir}/wide/threshold_1permille.parquet")
    # 「某期是否已进入前 1%」的唯一权威来源。缺失必须报错，不能回退到接近度 ——
    # 未进入学科的接近度来自 InCites，用它反推会多算（第 1 期 202601：14 vs 原件 13）。
    ent = pathlib.Path(out_dir) / "wide" / "entered_1pct.parquet"
    if not ent.is_file():
        raise FileNotFoundError(
            f"{ent} 缺失。该表由台账「学科进入时间」事件表推导（见 parse_ledger."
            f"build_entered_1pct），是「是否已进前 1%」的唯一权威来源；"
            f"请对本目录重跑 parse_ledger 生成后再算报告。")
    wide["entered_1pct"] = pd.read_parquet(ent)
    return wide, new_intl, new_cn, thr


def detect_periods(wide):
    """当前期/上期。口径唯一在 `period.detect`（本函数保名兼容调用方）。"""
    import period                                              # noqa: PLC0415

    return period.detect(wide)


def fmt_rank_change(rank_now, rank_prev):
    d = rank_prev - rank_now  # 正值=上升
    if d == 0:
        return f"{int(rank_now)}/-"
    arrow = "↑" if d > 0 else "↓"
    return f"{int(rank_now)}/{arrow}{abs(int(d))}"


def fmt_pct_change(v):
    arrow = "↑" if v > 0 else ("↓" if v < 0 else "-")
    return f"{arrow}{abs(v):.2f}%"


def build_table2(wide, new_intl, new_cn, thr, period=None, prev=None):
    if period is None or prev is None:
        period, prev = detect_periods(wide)
    c = wide["total_cites"][period]
    p = wide["papers"][period]
    cnci = wide["cnci"][period]
    t1 = wide["threshold_1pct"][period]
    tp = thr[period]
    top = wide["top_papers"][period]
    pr = wide["proximity_1pct"]

    rows = []
    for d in c.index:
        rn = new_cn.loc[d, ("rank", period)]
        rq = new_cn.loc[d, ("rank", prev)]
        rp = new_intl.loc[d, ("rank_pct", period)]
        prox_chg = (pr.loc[d, period] - pr.loc[d, prev]) * 100
        topv = top.loc[d]
        rows.append({
            "discipline": d,
            "rank_cn_change": fmt_rank_change(rn, rq),
            "papers": int(p[d]),
            "cnci": cnci[d],
            "total_cites": int(c[d]),
            "thr_1pct": int(t1[d]),
            "thr_1pct_gap": int(c[d] - t1[d]),
            "thr_1permille": int(tp[d]),
            "permille_rank": round(rp * 10, 3),
            "top_papers": "" if topv != topv else int(topv),
            "prox_change": fmt_pct_change(prox_chg),
            "_prox_change": prox_chg,
        })
    df = pd.DataFrame(rows)
    df = df.sort_values("_prox_change", ascending=False).drop(columns="_prox_change")
    return df


def build_overview(wide, new_intl, new_cn, thr, ynd_rank, top_total, period=None, prev=None):
    """概述段与学校发展段的全部数字事实（供回测/填稿）。"""
    if period is None or prev is None:
        period, prev = detect_periods(wide)
    c = wide["total_cites"][period]
    pr = wide["proximity_1pct"]
    tp = thr[period]
    top = wide["top_papers"][period]
    # 「已进入前 1%」的唯一权威来源（parse_ledger.build_entered_1pct）。
    # 生产路径由 load_wide 保证存在（缺失即报错）；此处兜底只为兼容手工构造的测试 dict，
    # 且兜底与 charts.py 取的是同一个来源，不会出现「文字 13 个、图里 14 个」。
    ent = wide.get("entered_1pct")
    src = ent if (ent is not None and period in ent.columns) else pr

    facts = {
        "rank_intl_now": int(ynd_rank.loc[period, "rank_intl"]),
        "rank_intl_prev": int(ynd_rank.loc[prev, "rank_intl"]),
        "rank_intl_delta": int(ynd_rank.loc[prev, "rank_intl"] - ynd_rank.loc[period, "rank_intl"]),
        "rank_cn_inst_now": int(ynd_rank.loc[period, "rank_cn"]),
        "rank_cn_uni_now": int(ynd_rank.loc[period, "rank_cn_uni"]),
        "rank_cn_inst_delta": int(ynd_rank.loc[prev, "rank_cn"] - ynd_rank.loc[period, "rank_cn"]),
        "rank_cn_uni_delta": int(ynd_rank.loc[prev, "rank_cn_uni"] - ynd_rank.loc[period, "rank_cn_uni"]),
        "n_disc_1pct": int((src[period] >= 1).sum()),
        "top_papers_now": int(top_total.get(period)),
        "top_papers_prev": int(top_total.get(prev)),
        "top_papers_delta": int(top_total.get(period)) - int(top_total.get(prev)),
        "top3_by_top_papers": sorted([(d, int(top[d])) for d in top.index if top[d] == top[d]],
                                     key=lambda x: -x[1])[:3],
    }
    # 1‰ 接近度最高学科（未进入 1‰ 时即千分位阈值比最低者）
    r1p = (c / tp).dropna()
    best = r1p.idxmax()
    has_prev_tp = prev in thr.columns and pd.notna(thr[prev].get(best))
    facts["best_1permille"] = {
        "discipline": best,
        "prox_pct": round(c[best] / tp[best] * 100, 2),
        "prox_prev_pct": (round(wide["total_cites"][prev][best] / thr[prev][best] * 100, 2)
                          if has_prev_tp else None),
    }
    # 接近度变化最大两学科
    chg = ((pr[period] - pr[prev]) * 100).sort_values(ascending=False)
    facts["top2_prox_change"] = [(d, chg[d]) for d in chg.index[:2]]
    # 国内排名升降统计（new_cn 口径）与降幅最大
    rn_now = new_cn.loc[:, ("rank", period)]
    rn_prev = new_cn.loc[:, ("rank", prev)]
    d_rank = rn_prev - rn_now  # 正=上升
    facts["rank_up"] = int((d_rank > 0).sum())
    facts["rank_down"] = int((d_rank < 0).sum())
    facts["rank_flat"] = int((d_rank == 0).sum())
    worst = d_rank.idxmin()
    facts["worst_cn_rank"] = {
        "discipline": worst,
        "drop": int(-d_rank[worst]),
        "rank": int(rn_now[worst]),
    }
    # 顶尖论文前三档（含并列；并列内按接近度变化降序，与报告排序惯例一致）
    tops = [(d, int(top[d])) for d in top.index if top[d] == top[d]]
    order = {d: i for i, d in enumerate(chg.index)}
    tops.sort(key=lambda x: order.get(x[0], 9_999))
    gmap = {}
    for d, v in tops:
        gmap.setdefault(v, []).append(d)
    facts["top3_groups"] = [(c, gmap[c]) for c in sorted(gmap, reverse=True)[:3]]
    # 未进入 1% 学科中接近度前二（预测章目标学科）
    ne = pr[period][pr[period] < 1].sort_values(ascending=False)
    top2 = []
    for d in ne.index[:2]:
        # 近 7 期（含当期，≈1 年）接近度尾迹：预测章「趋势描述 / 发展力度评价」的措辞依据
        # （sentences._prox_phrases 按「是否连涨 + 净变化」分档，不给数字）。
        hist_cols = [c for c in pr.columns
                     if isinstance(c, str) and c.isdigit() and c <= str(period)
                     and pd.notna(pr.at[d, c])]
        top2.append({
            "discipline": d,
            "prox_pct": round(ne[d] * 100, 2),
            "chg": round((pr.loc[d, period] - pr.loc[d, prev]) * 100, 2),
            "prox_tail": [round(float(pr.at[d, c]), 4) for c in hist_cols[-7:]],
        })
    facts["top2_not_entered"] = top2
    # 1‰ 状态与年化进入时间估算（按上期增速外推；上期 1‰阈值缺失则不强算）
    ratio_1pm = (c / tp).dropna()
    facts["any_1permille"] = bool((ratio_1pm >= 1).any())
    best_info = facts["best_1permille"]
    if best_info["prox_prev_pct"] is not None:
        growth = (best_info["prox_pct"] - best_info["prox_prev_pct"]) * 6  # 百分点/年（双月×6）
        facts["permille_years_est"] = (-(-(100 - best_info["prox_pct"]) // growth)
                                       if growth > 0.1 else None)
    else:
        facts["permille_years_est"] = None
    # 覆盖窗口与上期中文标签
    import calendar
    y, m = int(period[:4]), int(period[4:])
    end_y, end_m = (y, m - 3) if m > 3 else (y - 1, m + 9)
    facts["coverage_window"] = f"{end_y - 10}.1.1-{end_y}.{end_m}.{calendar.monthrange(end_y, end_m)[1]}"
    facts["prev_label"] = f"{int(prev[:4])}年{int(prev[4:])}月"
    return facts


if __name__ == "__main__":
    import sys
    out_dir = sys.argv[1] if len(sys.argv) > 1 else None
    if out_dir is None:
        import pathlib
        outs = sorted(pathlib.Path("out").glob("20*/"), key=lambda p: p.name)
        out_dir = str(outs[-1]).replace("\\", "/")
    wide, ni, nc, thr = load_wide(out_dir)
    P, Q = detect_periods(wide)
    t2 = build_table2(wide, ni, nc, thr, P, Q)
    pd.set_option("display.width", 200)
    print(f"# 当期 {P} / 上期 {Q} (@{out_dir})")
    print(t2.to_string(index=False))
