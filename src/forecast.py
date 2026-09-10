# -*- coding: utf-8 -*-
"""预测模块：复刻馆内方法 ——「InCites 当月值 + 历史差值均值校准」。

实测（回测 13 潜力学科 240+ 点）：
  方法 A（Holt 纯外推）        整体 MAPE = 15.53%  ✗
  方法 B（InCites + 差值校准）  整体 MAPE =  1.92%  ✓（验收线 <5%，决策 C3）

方法 B 即《学科信息参考》第三章的口径：InCites 月更快于 ESI 双月，
用其当期值作为下期 ESI 发布值的基础预测，再以历史 (ESI-InCites)
差值的滚动均值做系统偏差校准。国内排名同理（rank 差值校准）。
"""
import sys
import pathlib

import numpy as np
import pandas as pd

METRICS = ["cites", "papers", "rank_intl", "rank_cn"]


def win_to_period(win: str) -> str:
    m = __import__("re").search(r"（(\d{4}\.\d{2})）?$", win)
    return m.group(1).replace(".", "") if m else None


def backtest_gap_calibration(gap, min_len=3):
    """游走前推回测：pred_i = incite_i + mean(esi-incite)_{<i}，比 esi_i。"""
    rows = []
    per_point = []
    for d, grp in gap.groupby("discipline"):
        for metric in METRICS:
            w = grp.pivot(index="win", columns="source", values=metric)
            if "incite" not in w or "esi" not in w:
                continue
            w = w.dropna(subset=["incite", "esi"])
            for k in range(min_len, len(w)):
                hist_gap = (w["esi"].iloc[:k] - w["incite"].iloc[:k]).dropna()
                if hist_gap.empty:
                    continue
                pred = w["incite"].iloc[k] + hist_gap.mean()
                act = w["esi"].iloc[k]
                if metric == "rank_cn" and act <= 0:
                    continue
                if act == 0:
                    continue
                ape = abs((act - pred) / act) * 100
                per_point.append(ape)
                rows.append({"discipline": d, "metric": metric, "ape": ape,
                             "win": w.index[k], "pred": pred, "actual": act})
    return pd.DataFrame(rows), pd.Series(per_point)


def main(ledger_dir="out/202607", out_dir="out/202607"):
    gap = pd.read_parquet(f"{ledger_dir}/wide/forecast_gap.parquet")
    df, per_point = backtest_gap_calibration(gap)

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "forecast_backtest_points.parquet", index=False)

    summ = df.groupby(["discipline", "metric"])["ape"].agg(["mean", "count"])
    summ.to_parquet(out / "forecast_backtest_summary.parquet")
    summ.reset_index().to_csv(out / "forecast_backtest_summary.csv", index=False, encoding="utf-8-sig")

    overall = per_point.mean()
    lines = ["# 预测模块回测报告（方法 B：InCites + 历史差值校准）", ""]
    lines.append(f"整体 MAPE = {overall:.2f}%（验收线 <5%，决策 C3）  ·  样本点数 {len(per_point)}")
    lines.append("")
    lines.append("## 分学科（被引频次口径，核心指标）")
    for d, g in df[df.metric == "cites"].groupby("discipline"):
        m = g.ape.mean()
        flag = " ⚠️ 超验收线" if m > 5 else ""
        lines.append(f"- {d}: MAPE={m:.2f}%（n={len(g)}）{flag}")
    lines.append("")
    lines.append("## 分指标（全部 13 学科合并）")
    for metric, g in df.groupby("metric"):
        lines.append(f"- {metric}: MAPE={g.ape.mean():.2f}%（n={len(g)}）")
    txt = "\n".join(lines)
    (out / "预测回测报告.md").write_text(txt, encoding="utf-8")
    print(txt)
    return overall


if __name__ == "__main__":
    main()
