"""V1模型的网站调用层：冻结结构、滚动回测与多期递推预测。"""

from __future__ import annotations

from typing import Any

import numpy as np

from .config_v1 import (
    BASELINE_RECOMMENDATIONS_202607,
    INITIAL_TRAIN_SIZE,
    MODEL_NAMES,
    MODEL_PACKAGE_VERSION,
)
from .model_core_v1 import (
    calibrate_state_space_params,
    historical_fit_mape,
    rolling_backtest,
    select_sarima_structure,
    fit_model,
)


TASK_COLUMNS = {
    "citation": ("总被引", "ESI前1%被引阈值"),
    "rank": ("云大国内排名", "国内ESI前1%机构数"),
}
SUBJECT_ALIASES = {
    "神经系统科学与行为学": "神经科学与行为科学",
}


def next_periods(period: int | str, count: int) -> list[int]:
    text = str(int(period))
    year, month = int(text[:4]), int(text[4:])
    result = []
    for _ in range(count):
        month += 2
        if month > 12:
            year += 1
            month -= 12
        result.append(int(f"{year:04d}{month:02d}"))
    return result


def _frozen_inputs(model_name: str, values: np.ndarray):
    initial = np.asarray(values[:INITIAL_TRAIN_SIZE], dtype=float)
    sarima = None
    state_params = None
    meta: dict[str, Any] = {}
    if model_name == "SARIMA模型":
        order, seasonal_order, aic = select_sarima_structure(initial)
        sarima = (order, seasonal_order)
        meta = {"order": list(order), "seasonal_order": list(seasonal_order), "initial_30_aic": aic}
    elif model_name == "经验贝叶斯状态空间模型":
        state = calibrate_state_space_params(initial)
        state_params = state["params"]
        meta = {"frozen_variances": state["param_map"]}
    return sarima, state_params, meta


def _iterative_forecast(model_name: str, values: np.ndarray, horizon: int,
                        sarima_structure, state_space_params) -> list[float]:
    """逐期追加预测值并重拟合；SARIMA阶数和状态空间方差始终使用初始窗冻结值。"""
    work = np.asarray(values, dtype=float).copy()
    forecasts = []
    for _ in range(horizon):
        result = fit_model(model_name, work, sarima_structure, state_space_params)
        value = float(result.next_forecast)
        if not np.isfinite(value):
            raise ValueError(f"{model_name}产生非有限预测值。")
        forecasts.append(value)
        work = np.append(work, value)
    return forecasts


def _one_model(periods: list[int], series: dict[str, np.ndarray], task: str,
               model_name: str, horizon: int) -> dict:
    columns = TASK_COLUMNS[task]
    if len(periods) < INITIAL_TRAIN_SIZE + 1:
        raise ValueError(f"有效期数仅{len(periods)}，至少需要{INITIAL_TRAIN_SIZE + 1}期。")

    fit_mapes, rolling_mapes, forecasts, params = {}, {}, {}, {}
    failures = 0
    for column in columns:
        values = np.asarray(series[column], dtype=float)
        sarima, state_params, meta = _frozen_inputs(model_name, values)
        fit_mape, _ = historical_fit_mape(model_name, values, sarima, state_params)
        rolling_mape, _detail, failed = rolling_backtest(
            model_name, values, periods, sarima, state_params)
        fit_mapes[column] = fit_mape
        rolling_mapes[column] = rolling_mape
        if not np.isfinite(fit_mape) or not np.isfinite(rolling_mape):
            raise ValueError(f"{model_name}在{column}上未得到有限MAPE。")
        forecasts[column] = _iterative_forecast(
            model_name, values, horizon, sarima, state_params)
        params[column] = meta
        failures += failed

    future_periods = next_periods(periods[-1], horizon)
    a, b = forecasts[columns[0]], forecasts[columns[1]]
    if task == "citation":
        ratios = [x / y * 100 if y else float("nan") for x, y in zip(a, b)]
        crossed = [x >= y for x, y in zip(a, b)]
    else:
        ratios = [y / x * 100 if x else float("nan") for x, y in zip(a, b)]
        crossed = [x <= y for x, y in zip(a, b)]
    first_crossing = next((p for p, hit in zip(future_periods, crossed) if hit), None)

    rows = []
    for idx, period in enumerate(future_periods):
        rows.append({
            "period": period,
            "metric1": float(a[idx]),
            "metric2": float(b[idx]),
            "proximity": float(ratios[idx]),
            "crossed": bool(crossed[idx]),
        })

    fit_combined = float(np.nanmean(list(fit_mapes.values())))
    rolling_combined = float(np.nanmean(list(rolling_mapes.values())))
    both_under = all(np.isfinite(x) and x < 5 for x in rolling_mapes.values())
    return {
        "model": model_name,
        "fit_mape": fit_combined,
        "rolling_mape": rolling_combined,
        "gap": rolling_combined - fit_combined,
        "metric_mapes": {
            column: {"fit": float(fit_mapes[column]), "rolling": float(rolling_mapes[column])}
            for column in columns
        },
        "failures": failures,
        "both_under_5": both_under,
        "status": "PASS" if failures == 0 and both_under else "REVIEW",
        "first_crossing": first_crossing,
        "parameters": params,
        "forecast": rows,
    }


def run_prediction(subject: str, periods: list[int], series: dict[str, np.ndarray],
                   task: str, model: str, horizon: int) -> dict:
    if task not in TASK_COLUMNS:
        raise ValueError("未知预测路线。")
    if not 1 <= horizon <= 24:
        raise ValueError("预测期数必须在1至24期之间。")

    baseline_key = SUBJECT_ALIASES.get(subject, subject)
    recommended = BASELINE_RECOMMENDATIONS_202607.get(task, {}).get(baseline_key, "")
    if model == "recommended":
        if not recommended:
            raise ValueError("该学科没有V1基线推荐模型。")
        selected = [recommended]
    elif model == "all":
        selected = list(MODEL_NAMES)
    elif model in MODEL_NAMES:
        selected = [model]
    else:
        raise ValueError("未知模型。")

    results, errors = [], []
    for model_name in selected:
        try:
            results.append(_one_model(periods, series, task, model_name, horizon))
        except Exception as exc:  # 单个模型失败不抹掉其余模型结果
            errors.append({"model": model_name, "error": str(exc)})
    if not results:
        raise ValueError("所选模型均运行失败。" + (f" {errors[0]['error']}" if errors else ""))

    best = min(results, key=lambda item: item["rolling_mape"])
    columns = TASK_COLUMNS[task]
    history_start = max(0, len(periods) - 18)
    history = [
        {"period": int(periods[i]), "metric1": float(series[columns[0]][i]),
         "metric2": float(series[columns[1]][i])}
        for i in range(history_start, len(periods))
    ]
    return {
        "model_version": MODEL_PACKAGE_VERSION,
        "subject": subject,
        "task": task,
        "metric_names": list(columns),
        "data_start": periods[0],
        "data_end": periods[-1],
        "history_periods": len(periods),
        "horizon": horizon,
        "recommended_model": recommended,
        "compared_all": model == "all",
        "comparison_best_model": best["model"],
        "history": history,
        "results": results,
        "errors": errors,
        "notice": (
            "V1正式验证范围为一步预测；多期结果采用逐期追加预测值的递推外推。"
            "过线仅表示模型曲线达到条件，不等同于科睿唯安正式入榜时间。"
        ),
    }
