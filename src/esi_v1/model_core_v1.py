# -*- coding: utf-8 -*-
"""ESI 五模型核心引擎（冻结 V1）。"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import warnings
import numpy as np

from statsmodels.tsa.holtwinters import Holt, ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.statespace.structural import UnobservedComponents
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from .config_v1 import (
    MODEL_NAMES,
    SEASONAL_PERIODS,
    INITIAL_TRAIN_SIZE,
    FIT_MAPE_START_INDEX,
    SARIMA_ORDERS,
    SARIMA_SEASONAL_ORDERS,
)

warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)


@dataclass
class ModelResult:
    fitted_values: np.ndarray
    next_forecast: float
    aic: float = float("nan")
    bic: float = float("nan")


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not np.any(mask):
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _safe_float(x) -> float:
    try:
        return float(np.asarray(x).reshape(-1)[0])
    except Exception:
        return float("nan")


def select_sarima_structure(y_initial: np.ndarray):
    y_initial = np.asarray(y_initial, dtype=float)
    best = None
    best_aic = float("inf")

    for order in SARIMA_ORDERS:
        for seasonal_order in SARIMA_SEASONAL_ORDERS:
            try:
                fit = SARIMAX(
                    y_initial,
                    order=order,
                    seasonal_order=seasonal_order,
                    trend=None,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                ).fit(disp=False, maxiter=80)
                aic = float(fit.aic)
                if np.isfinite(aic) and aic < best_aic:
                    best_aic = aic
                    best = (order, seasonal_order)
            except Exception:
                continue

    if best is None:
        best = ((0, 1, 1), (0, 0, 0, SEASONAL_PERIODS))
        best_aic = float("nan")
    return best[0], best[1], best_aic


def calibrate_state_space_params(y_initial: np.ndarray) -> Dict[str, Any]:
    model = UnobservedComponents(
        np.asarray(y_initial, dtype=float),
        level="local linear trend",
        seasonal=SEASONAL_PERIODS,
    )
    fit = model.fit(disp=False, maxiter=100)
    params = np.asarray(fit.params, dtype=float)
    names = list(model.param_names)
    return {
        "params": params,
        "param_names": names,
        "param_map": {name: float(value) for name, value in zip(names, params)},
    }


def fit_model(
    model_name: str,
    y: np.ndarray,
    sarima_structure=None,
    state_space_params: Optional[np.ndarray] = None,
) -> ModelResult:
    y = np.asarray(y, dtype=float)

    if model_name == "Holt趋势模型":
        fit = Holt(y, damped_trend=False, initialization_method="estimated").fit(optimized=True)
        return ModelResult(
            np.asarray(fit.fittedvalues, dtype=float),
            _safe_float(fit.forecast(1)),
            _safe_float(getattr(fit, "aic", float("nan"))),
            _safe_float(getattr(fit, "bic", float("nan"))),
        )

    if model_name == "阻尼Holt模型":
        fit = Holt(y, damped_trend=True, initialization_method="estimated").fit(optimized=True)
        return ModelResult(
            np.asarray(fit.fittedvalues, dtype=float),
            _safe_float(fit.forecast(1)),
            _safe_float(getattr(fit, "aic", float("nan"))),
            _safe_float(getattr(fit, "bic", float("nan"))),
        )

    if model_name == "季节性ETS模型":
        fit = ExponentialSmoothing(
            y,
            trend="add",
            damped_trend=False,
            seasonal="add",
            seasonal_periods=SEASONAL_PERIODS,
            initialization_method="estimated",
        ).fit(optimized=True, use_brute=False)
        return ModelResult(
            np.asarray(fit.fittedvalues, dtype=float),
            _safe_float(fit.forecast(1)),
            _safe_float(getattr(fit, "aic", float("nan"))),
            _safe_float(getattr(fit, "bic", float("nan"))),
        )

    if model_name == "SARIMA模型":
        if sarima_structure is None:
            order, seasonal_order, _ = select_sarima_structure(y[:INITIAL_TRAIN_SIZE])
        else:
            order, seasonal_order = sarima_structure
        fit = SARIMAX(
            y,
            order=order,
            seasonal_order=seasonal_order,
            trend=None,
            enforce_stationarity=False,
            enforce_invertibility=False,
        ).fit(disp=False, maxiter=100)
        return ModelResult(
            np.asarray(fit.fittedvalues, dtype=float),
            _safe_float(fit.forecast(1)),
            _safe_float(fit.aic),
            _safe_float(fit.bic),
        )

    if model_name == "经验贝叶斯状态空间模型":
        model = UnobservedComponents(
            y,
            level="local linear trend",
            seasonal=SEASONAL_PERIODS,
        )
        if state_space_params is None:
            fit = model.fit(disp=False, maxiter=100)
        else:
            fit = model.smooth(np.asarray(state_space_params, dtype=float))
        return ModelResult(
            np.asarray(fit.fittedvalues, dtype=float),
            _safe_float(fit.forecast(1)),
            _safe_float(getattr(fit, "aic", float("nan"))),
            _safe_float(getattr(fit, "bic", float("nan"))),
        )

    raise ValueError(f"未知模型：{model_name}")


def historical_fit_mape(model_name, y, sarima_structure=None, state_space_params=None):
    result = fit_model(model_name, y, sarima_structure, state_space_params)
    start = FIT_MAPE_START_INDEX
    return mape(y[start:], result.fitted_values[start:]), result


def rolling_backtest(model_name, y, periods: List[int], sarima_structure=None, state_space_params=None):
    y = np.asarray(y, dtype=float)
    actuals, forecasts, detail = [], [], []
    failures = 0

    for test_idx in range(INITIAL_TRAIN_SIZE, len(y)):
        train = y[:test_idx]
        actual = float(y[test_idx])
        try:
            result = fit_model(model_name, train, sarima_structure, state_space_params)
            forecast = float(result.next_forecast)
            if not np.isfinite(forecast):
                raise ValueError("预测值不是有限数")
            error_message = ""
        except Exception as exc:
            failures += 1
            forecast = float("nan")
            error_message = str(exc)

        ape = abs((actual - forecast) / actual) * 100 if actual > 0 and np.isfinite(forecast) else float("nan")
        actuals.append(actual)
        forecasts.append(forecast)
        detail.append({
            "测试期次": int(periods[test_idx]),
            "真实值": actual,
            "预测值": forecast,
            "绝对百分比误差": ape,
            "错误信息": error_message,
        })

    return mape(np.asarray(actuals), np.asarray(forecasts)), detail, failures


def evaluate_two_series(subject: str, periods: List[int], series: Dict[str, np.ndarray], reference_mape: float = 5.0):
    if len(periods) < INITIAL_TRAIN_SIZE + 1:
        raise ValueError(f"{subject} 有效期数={len(periods)}，至少需要 {INITIAL_TRAIN_SIZE + 1} 期。")

    sarima_meta = {}
    for series_name, y in series.items():
        order, seasonal_order, init_aic = select_sarima_structure(np.asarray(y[:INITIAL_TRAIN_SIZE], dtype=float))
        sarima_meta[series_name] = {
            "order": order,
            "seasonal_order": seasonal_order,
            "initial_aic": init_aic,
        }

    state_meta = {}
    for series_name, y in series.items():
        state_meta[series_name] = calibrate_state_space_params(np.asarray(y[:INITIAL_TRAIN_SIZE], dtype=float))

    comparison, rolling_detail = [], []
    series_names = list(series.keys())
    if len(series_names) != 2:
        raise ValueError("V1 工作流要求每个任务恰好两条序列。")

    for model_name in MODEL_NAMES:
        row = {"学科": subject, "模型": model_name}
        total_failures = 0

        for series_name, y in series.items():
            sarima_structure = None
            state_params = None
            if model_name == "SARIMA模型":
                meta = sarima_meta[series_name]
                sarima_structure = (meta["order"], meta["seasonal_order"])
            if model_name == "经验贝叶斯状态空间模型":
                state_params = state_meta[series_name]["params"]

            fit_mape, fit_result = historical_fit_mape(model_name, y, sarima_structure, state_params)
            roll_mape, detail, failures = rolling_backtest(model_name, y, periods, sarima_structure, state_params)
            total_failures += failures

            row[f"{series_name}_历史拟合MAPE"] = fit_mape
            row[f"{series_name}_滚动样本外MAPE"] = roll_mape
            row[f"{series_name}_AIC"] = fit_result.aic
            row[f"{series_name}_BIC"] = fit_result.bic

            for item in detail:
                rolling_detail.append({
                    "学科": subject,
                    "序列": series_name,
                    "模型": model_name,
                    **item,
                })

        fit_values = [row[f"{s}_历史拟合MAPE"] for s in series_names]
        roll_values = [row[f"{s}_滚动样本外MAPE"] for s in series_names]
        row["历史拟合MAPE_综合"] = float(np.nanmean(fit_values))
        row["滚动样本外MAPE_综合"] = float(np.nanmean(roll_values))
        row["拟合预测差距Gap"] = row["滚动样本外MAPE_综合"] - row["历史拟合MAPE_综合"]
        row["滚动回测失败次数"] = total_failures
        row["双序列滚动MAPE均小于参考线"] = "是" if all(np.isfinite(v) and v < reference_mape for v in roll_values) else "否"
        comparison.append(row)

    comparison.sort(key=lambda r: (
        float("inf") if not np.isfinite(r["滚动样本外MAPE_综合"]) else r["滚动样本外MAPE_综合"],
        float("inf") if not np.isfinite(r["历史拟合MAPE_综合"]) else r["历史拟合MAPE_综合"],
    ))
    for rank, row in enumerate(comparison, start=1):
        row["学科内排名"] = rank
        row["是否最优模型"] = "是" if rank == 1 else "否"

    best = comparison[0]
    next_forecasts = {}
    best_name = best["模型"]
    for series_name, y in series.items():
        sarima_structure = None
        state_params = None
        if best_name == "SARIMA模型":
            meta = sarima_meta[series_name]
            sarima_structure = (meta["order"], meta["seasonal_order"])
        if best_name == "经验贝叶斯状态空间模型":
            state_params = state_meta[series_name]["params"]
        result = fit_model(best_name, np.asarray(y, dtype=float), sarima_structure, state_params)
        next_forecasts[series_name] = float(result.next_forecast)

    return {
        "comparison": comparison,
        "rolling_detail": rolling_detail,
        "best": best,
        "sarima_meta": sarima_meta,
        "state_space_meta": state_meta,
        "next_forecasts": next_forecasts,
    }
