# -*- coding: utf-8 -*-
"""预测章配图：2 个潜力学科 × 2 图（被引频次/阈值、国内机构数/云大排名）。

- 数据：`out/<期次>/` 的只读派生产物（经 `esi_v1.data` 组装四列标准输入）
- 口径：V1 交接包调用副本 —— `model="recommended"`（202607 基线推荐模型），
  多期结果按 V1 的逐期递推外推 `HORIZON` 期（与网页预测工作台同一口径）
- 产物：`out/<期次>/charts/_overview/forecast_{1|2}_{cites|rank}.png`
  + `out/<期次>/forecast_charts.json`（学科/模型/过线期，红色件清单引用）

⚠ 图号（1/2）按「未进入 1% 学科中接近度前二」的顺序，与报告预测章 4 条图题的
出现顺序一一对应；报告侧 `fill_docx.fill_forecast_charts` 按位置对号入座
（母版图题里的学科名与台账名存在历史写法差异，不能按名字匹配）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import charts  # noqa: E402
from esi_v1.config_v1 import FIT_MAPE_START_INDEX  # noqa: E402
from esi_v1.data import display_name, load_standard_input, subject_task_data  # noqa: E402
from esi_v1.service import TASK_COLUMNS, fit_and_forecast, run_prediction  # noqa: E402

HORIZON = 18  # 3 年（双月 6 期/年；与网页预测工作台默认一致）

CITES_LABELS = ("被引频次", "被引频次预测值", "阈值", "阈值预测值")
CITES_COLORS = ("#00B050", "#92D050", "#4472C4", "#9DC3E6")
# 顺序必须与 esi_v1.service.TASK_COLUMNS["rank"] 一致：(云大国内排名, 国内ESI前1%机构数)；
# 配色沿用母版 chart4：云大排名=紫、国内机构数=红。
RANK_LABELS = ("云大排名", "云大排名预测值", "国内机构数", "国内机构预测值")
RANK_COLORS = ("#7030A0", "#B08BD0", "#FF0000", "#FF9E9E")


def pick_subjects(period_dir):
    """未进入 1%（接近度<1）的学科中接近度前二 —— 与概述 facts 同一规则。"""
    prox = pd.read_parquet(pathlib.Path(period_dir) / "wide" / "proximity_1pct.parquet")
    cols = [str(c) for c in prox.columns if re.fullmatch(r"\d{6}", str(c))]
    if not cols:
        raise ValueError("proximity_1pct 没有有效期次。")
    col = prox[cols[-1]].dropna()
    subjects = [display_name(en) for en in col[col < 1].sort_values(ascending=False).index]
    return subjects[:2], cols[-1]


def generate(period_dir) -> int:
    """渲染 4 张预测图；返回张数（异常向上抛，由调用方决定降级策略）。"""
    period_dir = pathlib.Path(period_dir)
    subjects_cn, period = pick_subjects(period_dir)
    if len(subjects_cn) < 2:
        raise ValueError("未进入 1% 的潜力学科不足 2 个，预测图无从生成。")

    try:
        data, _meta = load_standard_input(period_dir)
    except ValueError as exc:
        # 历史期次快照可能早于台账修正（如 经济与商业 202003：旧 364 → 现行 31）。
        # 报告只画当期潜力学科前二：只要这两个学科不含闸门学科，即放行出图；
        # 一旦命中，宁可不出图也不带病出图（重新抛出）。
        if "V1输入校验失败" not in str(exc):
            raise
        if "经济与商业" in subjects_cn:
            raise ValueError(f"本期目标学科命中 V1 数据修正闸门，禁止降级出图：{exc}") from exc
        data, _meta = load_standard_input(period_dir, validate=False)
    known = set(data["学科"])
    missing = [s for s in subjects_cn if s not in known]
    if missing:
        raise ValueError(f"潜力学科不在 V1 标准输入里：{'、'.join(missing)}")

    ov = period_dir / "charts" / "_overview"
    made, chart_meta = [], []
    for i, cn in enumerate(subjects_cn, 1):
        for task, kind, labels, colors in (
                ("citation", "cites", CITES_LABELS, CITES_COLORS),
                ("rank", "rank", RANK_LABELS, RANK_COLORS)):
            periods, series = subject_task_data(data, cn, task)
            res = run_prediction(cn, periods, series, task, "recommended", HORIZON)
            best = min(res["results"], key=lambda r: r["rolling_mape"])
            columns = TASK_COLUMNS[task]
            hist, model_hist, fut = [], [], []
            for column in columns:
                fitted, future, _params = fit_and_forecast(best["model"], series[column], HORIZON)
                y = np.asarray(series[column], dtype=float)
                fitted = np.asarray(fitted, dtype=float).copy()
                # V1 口径：拟合从第 7 期起；初始化毛刺可能再延续几期（UC 实测第 7 期
                # 还是 217 vs 实际 134），继续裁到模型落位（首个相对误差 ≤25% 的点）。
                fitted[:FIT_MAPE_START_INDEX] = np.nan
                k = FIT_MAPE_START_INDEX
                while 0 < k < len(fitted) and np.isfinite(fitted[k]) and y[k] \
                        and abs(fitted[k] - y[k]) / abs(y[k]) > 0.25:
                    fitted[k] = np.nan
                    k += 1
                hist.append(y)
                model_hist.append(fitted)
                fut.append(future)
            png = ov / f"forecast_{i}_{kind}.png"
            charts.chart_forecast(
                [str(p) for p in periods], tuple(hist), tuple(model_hist),
                [str(r["period"]) for r in best["forecast"]],
                tuple(fut), labels, colors, png, grid=(task == "citation"))
            made.append(png)
            chart_meta.append({
                "index": i, "subject": cn, "task": task, "kind": kind,
                "model": best["model"],
                "rolling_mape": round(float(best["rolling_mape"]), 2),
                "first_crossing": best["first_crossing"],
                "png": png.name,
            })

    meta = {"period": period, "horizon": HORIZON, "generated": len(made), "charts": chart_meta}
    (period_dir / "forecast_charts.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(made)


def main(period_dir=None):
    sys.stdout.reconfigure(encoding="utf-8")
    if period_dir is None:
        outs = sorted(pathlib.Path("out").glob("20*/"), key=lambda p: p.name)
        period_dir = outs[-1]
    n = generate(period_dir)
    print(f"预测图 {n} 张 → {pathlib.Path(period_dir) / 'charts' / '_overview'}")
    meta = json.loads((pathlib.Path(period_dir) / "forecast_charts.json").read_text(encoding="utf-8"))
    for c in meta["charts"]:
        cross = f"，预计过线 {c['first_crossing']}" if c["first_crossing"] else "（预测区间内未过线）"
        print(f"  [{c['index']}] {c['subject']} · {c['task']}: {c['model']}"
              f"（滚动 MAPE {c['rolling_mape']}%{cross}）")
    return n


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
