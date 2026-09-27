# -*- coding: utf-8 -*-
"""预测章配图：2 个潜力学科 × 2 图（被引频次/阈值、国内机构数/云大排名）。

- 数据：`out/<期次>/` 的只读派生产物（经 `esi_v1.data` 组装四列标准输入）
- 口径：V1 交接包调用副本 —— 模型默认 `"recommended"`（202607 基线推荐模型）；
  选模记录（契约 #17 嵌套形状）的读写统一走 `forecast_choice`：运行时 applied 快照
  优先，否则按 primary（`out/_forecast_choices/<期次>.json`）→ legacy
  （`out/<期次>/forecast_choice.json`）读回；记录里列出的 (路线, 学科) 按所选模型出图，
  未列出＝推荐；所选模型失败降级推荐并在 `warnings` 留痕（`run_pipeline` 收进 run_log）。
  多期结果按 V1 的逐期递推外推 `HORIZON` 期（与网页预测工作台同一口径）
- 产物：`out/<期次>/charts/_overview/forecast_{1|2}_{cites|rank}.png`
  + `out/<期次>/forecast_charts.json`（学科/模型/过线期/选模警告，红色件清单与 run_log 引用）

⚠ 图号（1/2）按「未进入 1% 学科中接近度前二」的顺序，与报告预测章 4 条图题的
出现顺序一一对应；报告侧 `fill_docx.fill_forecast_charts` 按位置对号入座
（母版图题里的学科名与台账名存在历史写法差异，不能按名字匹配）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import charts  # noqa: E402
import forecast_choice  # noqa: E402
from esi_v1.config_v1 import FIT_MAPE_START_INDEX  # noqa: E402
from esi_v1.data import display_name, load_standard_input, subject_task_data  # noqa: E402
from esi_v1.service import TASK_COLUMNS, fit_and_forecast, run_prediction  # noqa: E402

HORIZON = 18  # 3 年（双月 6 期/年；与网页预测工作台默认一致）

CHOICE_FILE = forecast_choice.CHOICE_FILE   # 预测台落盘的模型选择（契约 #17 嵌套形状）
ROUTES = forecast_choice.ROUTES             # 选模语义（读序/形状/常量）唯一实现在 forecast_choice
VALID_MODELS = forecast_choice.VALID_MODELS

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


def load_choice(period_dir, choice_path=None):
    """读预测台落盘的模型选择 → `{(路线, 学科): 模型名}`，附警告清单。

    实现统一在 `forecast_choice.load`（primary → legacy 读序与服务端 GET 一致）：
    只认契约 #17 的新嵌套形状 `{choice: {"citation": {学科: 模型}, "rank": {...}}}`；
    中文学科键、只存改过的学科。旧扁平形状（英文键）**整份忽略**——硬接会把选择
    错配到别的学科（前端提醒 #9 已确认口径）。形状/模型不合法都只记警告、不拦停：
    未列出的学科保持 `"recommended"`。
    """
    return forecast_choice.load(period_dir, choice_path)


def load_warnings(period_dir) -> list[str]:
    """读回 `forecast_charts.json` 里的选模警告（run_pipeline 收进 run_log）。"""
    p = pathlib.Path(period_dir) / "forecast_charts.json"
    try:
        warnings = json.loads(p.read_text(encoding="utf-8")).get("warnings", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    return [str(w) for w in warnings] if isinstance(warnings, list) else []


def quarantine_forecast_artifacts(period_dir) -> list[str]:
    """把旧预测元数据和图移出活动路径，避免失败运行复用上一版。"""
    period_dir = pathlib.Path(period_dir)
    overview = period_dir / "charts" / "_overview"
    stale = [period_dir / "forecast_charts.json"]
    if overview.is_dir():
        stale.extend(overview.glob("forecast_*.png"))
    stale = sorted({p for p in stale if p.is_file()})
    if not stale:
        return []

    stamp = time.strftime("%Y%m%dT%H%M%S") + f"-{time.time_ns()}"
    archive = period_dir / "_superseded" / "forecast" / stamp
    moved = []
    for path in stale:
        target = archive / path.relative_to(period_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        moved.append(path.relative_to(period_dir).as_posix())
    return moved


def _choice_provenance(period_dir, data_period, choice_path=None):
    """返回可随 forecast_charts.json 审计的配置来源字段（见 forecast_choice.provenance）。"""
    return forecast_choice.provenance(period_dir, data_period, choice_path)


def _run_with_choice(subject, periods, series, task, model, warnings):
    """按预测台选择跑模型；所选模型失败 → 降级 V1 推荐并记警告（不拦停出图）。"""
    try:
        return run_prediction(subject, periods, series, task, model, HORIZON)
    except Exception as exc:                                     # noqa: BLE001
        if model == "recommended":
            raise
        warnings.append(f"预测选模：{task}/{subject} 所选模型「{model}」运行失败，"
                        f"已降级 V1 推荐（{exc}）")
        return run_prediction(subject, periods, series, task, "recommended", HORIZON)


def generate(period_dir, choice_path=None) -> int:
    """先隔离旧产物；若本次生成中途失败，也隔离本次的不完整图。"""
    period_dir = pathlib.Path(period_dir)
    quarantine_forecast_artifacts(period_dir)
    try:
        return _generate(period_dir, choice_path)
    except Exception:
        quarantine_forecast_artifacts(period_dir)
        raise


def _generate(period_dir, choice_path=None) -> int:
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
    choices, warnings = load_choice(period_dir, choice_path)
    made, chart_meta = [], []
    for i, cn in enumerate(subjects_cn, 1):
        for task, kind, labels, colors in (
                ("citation", "cites", CITES_LABELS, CITES_COLORS),
                ("rank", "rank", RANK_LABELS, RANK_COLORS)):
            periods, series = subject_task_data(data, cn, task)
            model = choices.get((task, cn), "recommended")
            res = _run_with_choice(cn, periods, series, task, model, warnings)
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
                "requested": model,
                "rolling_mape": round(float(best["rolling_mape"]), 2),
                "first_crossing": best["first_crossing"],
                "png": png.name,
            })

    meta = {"period": period, **_choice_provenance(period_dir, period, choice_path),
            "horizon": HORIZON, "generated": len(made),
            "warnings": warnings, "charts": chart_meta}
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
    for w in meta.get("warnings", []):
        print(f"  ⚠ {w}")
    return n


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
