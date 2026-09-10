# -*- coding: utf-8 -*-
"""从台账计算第 P 期报告所需的全部数值（只读台账，不产新数据）。

Table2 十一列口径（已用第 4 期实物反推验证）：
  国内排名/变化 = new_cn.rank[P] + Δ(new_cn.rank[Q]->[P])  → "139/↓4"
  论文数/CNCI/总被引/1%阈值/1‰阈值/顶尖论文 = 宽表 [P]（顶尖论文空白=空）
  1%阈值差 = 总被引 - 1%阈值
  千分位 = new_intl.rank_pct[P] × 10（3 位小数）
  接近度较Q月 = (接近度[P] - 接近度[Q]) × 100 → "↑33.87%"
"""
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
    return wide, new_intl, new_cn, thr


def detect_periods(wide):
    """当前期 = 总被引表最后一个有数据的期次；上期 = 其前一个（自动跟随台账更新）。"""
    tc = wide["total_cites"]
    filled = [c for c in tc.columns if tc[c].notna().any()]
    if len(filled) < 2:
        raise ValueError("台账被引表有效期次不足 2 期，无法定位当期")
    return filled[-1], filled[-2]


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

    facts = {
        "rank_intl_now": int(ynd_rank.loc[period, "rank_intl"]),
        "rank_intl_prev": int(ynd_rank.loc[prev, "rank_intl"]),
        "rank_intl_delta": int(ynd_rank.loc[prev, "rank_intl"] - ynd_rank.loc[period, "rank_intl"]),
        "rank_cn_inst_now": int(ynd_rank.loc[period, "rank_cn"]),
        "rank_cn_uni_now": int(ynd_rank.loc[period, "rank_cn_uni"]),
        "n_disc_1pct": int((pr[period] >= 1).sum()),
        "top_papers_now": int(top_total.get(period)),
        "top_papers_prev": int(top_total.get(prev)),
        "top_papers_delta": int(top_total.get(period)) - int(top_total.get(prev)),
        "top3_by_top_papers": sorted([(d, int(top[d])) for d in top.index if top[d] == top[d]],
                                     key=lambda x: -x[1])[:3],
    }
    # 1‰ 接近度最高学科（未进入 1‰ 时即千分位阈值比最低者）
    r1p = (c / tp).dropna()
    best = r1p.idxmax()
    facts["best_1permille"] = {
        "discipline": best,
        "prox_pct": round(c[best] / tp[best] * 100, 2),
        "prox_prev_pct": round(wide["total_cites"][prev][best] / thr[prev][best] * 100, 2),
    }
    # 接近度变化最大两学科
    chg = ((pr[period] - pr[prev]) * 100).sort_values(ascending=False)
    facts["top2_prox_change"] = [(d, chg[d]) for d in chg.index[:2]]
    # 国内排名降幅最大
    rn_now = new_cn.loc[:, ("rank", period)]
    rn_prev = new_cn.loc[:, ("rank", prev)]
    delta = rn_now - rn_prev
    worst = delta.idxmax()
    facts["worst_cn_rank"] = {
        "discipline": worst,
        "drop": int(delta[worst]),
        "rank": int(rn_now[worst]),
    }
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
