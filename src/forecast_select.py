# -*- coding: utf-8 -*-
"""研究线：五模型按学科选模 + 预测区间 + 预计过线时间。

对应 WH-DOC-10 §7.3：把《五模型比较与选模分析报告》的静态结论做成可重跑的流水线模块，
并补上两份报告都缺失的「预计过线时间」（报告原表该列 8×2 全为"待验证"）。

数据来源（只读台账派生数据，不写回台账）
  被引维度：wide/total_cites 与 wide/threshold_1pct，比值即 wide/proximity_1pct
  排名维度：ledger_long 中 source='rank_cn' 的 n_inst_1pct 与 rank

过线定义（两维度同构，均为「比值 ≥ 1」）
  被引维度：总被引 ≥ ESI前1%被引阈值
  排名维度：国内进入前1%机构数 ≥ 云大国内排名
  注：排名维度是序数序列，其 MAPE 只可在同维度内比较，不可与被引维度横比（WH-DOC-10 §P1-1）。

潜力学科：当前期被引接近度 < 1 的学科（即尚未进入 ESI 前1%），共 8 个。

模型与实现口径（报告未披露，此处显式写出以便复核 —— 对应 WH-DOC-10 §P1-7）
  默认口径 = **V1**（`IMPL = "V1"`），逐条对齐 `ESI_Workflow_Model_V1_Handoff/model_core_v1.py`：
    Holt              tsa.holtwinters.Holt(damped_trend=False), initialization_method="estimated"
    阻尼Holt          tsa.holtwinters.Holt(damped_trend=True),  同上
    季节性ETS         tsa.holtwinters.ExponentialSmoothing(trend="add", seasonal="add",
                                                          seasonal_periods=6)
    SARIMA            **初始窗内按 AIC 从 3×4=12 组候选选阶**，之后固定阶数重估系数
    经验贝叶斯状态空间  UnobservedComponents(level="local linear trend", seasonal=6)
                      **超参冻结**：初始窗 MLE 估出方差后固定，后续只滤隐状态（model.smooth(params)）
  对照口径（`IMPL = "statespace"`，保留以便复核旧结论）：
    五模型一律走 statespace 版，**参数每期在扩展窗口内重新估计**（不冻结超参、SARIMA 固定 (1,1,1)(1,0,1,6)）。
  为什么以 V1 为默认（WH-DOC-12 §四.B.4 实测）：报告用的是「冻结超参 + 初始窗 AIC 选阶」口径。
  以 V1 口径重算，选模对报告首选 **15/16 命中**；旧 statespace 口径只有 7/16 ——
  那 7/16 里混进了实现差异，不能全算成选模噪声。

序列窗口（第三个口径开关，同样默认 V1）
  默认只取**四列齐备的公共窗口**（201909～202607，42 期）。这是 V1 交接包的装载口径，
  也是复现已发布报告的那一套。实测 22 学科一致：**公共窗口长度恒等于「云大国内排名」列的长度**
  （多数 42 期，Chemistry/Physics 等 8 科 45 期），卡住窗口的是排名列（201903/05/07 无值）。
  代价必须写明：被引维度本有 45 期（201903 起）、前1%机构数本有 44 期（201905 起），
  都被一并压到 42 期 —— **丢掉真实数据**，换成「四列同期可比」。
  实测影响（分子生物学与遗传学·被引维度，V1 实现口径下）：
    42 期 → 季节性ETS **1.909%**（= 报告首选；且与 WH-DOC-12 记的 V1 实测 1.909% 同数）
    45 期 → 经验贝叶斯 1.987%（前二名只差 0.019pp，属噪声内翻面）
  即：这一开关会改变部分学科的选模结果，且只在「前二名差 ~0.02pp」的贴身项上显现。
  换 `window="full"` 可用满各列长度，信息更满，但与报告口径不一致，数字不可与报告对照。

回测规则（与报告一致）：前 MIN_TRAIN 期训练 → 预测下一期 → 逐期扩展训练窗口，取一步外推。
选模规则（与报告一致）：两条序列的滚动样本外 MAPE 等权平均，最低者胜出。

口径与局限（务必与结论一起引用）
  1. 预测区间不是模型自带区间，而是由回测期「一步相对误差」的经验分位数外推得到；
     多步按 sqrt(h) 放大离散度、保留中位偏差。区间宽度只反映该模型在回测窗内的表现，
     不覆盖结构性突变（如多学科的 2024 年水平切换、经济与商业 2020-03 跳点）。
  2. 回测窗仅 12–15 期，「程序排名」第 1/2 名之差通常不具统计可区分性，只应作同量级参考。
  3. 本模块是研究线工具，不替代生产线方法 B（wenheng/src/forecast.py）。
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing as HWES
from statsmodels.tsa.holtwinters import Holt
from statsmodels.tsa.statespace.exponential_smoothing import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.statespace.structural import UnobservedComponents
from statsmodels.tools.sm_exceptions import ConvergenceWarning

# V1 交接包口径，不掩盖收敛告警（V1 也是这么做的）
warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

MODELS = ["Holt", "阻尼Holt", "季节性ETS", "SARIMA", "经验贝叶斯状态空间"]
SEASONAL_PERIODS = 6      # ESI 双月更新 → 一年 6 期
MIN_TRAIN = 30            # 报告口径：前 30 期训练
Q_LO, Q_HI = 0.10, 0.90   # 80% 预测区间
DEFAULT_HORIZON = 24      # 最多外推 24 期（4 年）

# ---------------------------------------------------------------- 口径开关
# "V1"         = 对齐 ESI_Workflow_Model_V1_Handoff（报告实际口径）—— 默认
# "statespace" = 旧口径，statespace 版每期重估，仅作对照，勿用于结论
IMPL = "V1"
IMPL_CHOICES = ("V1", "statespace")

# 序列装载窗口：
# "V1"   = 四列齐备的公共窗口（V1 交接包的装载口径，也是复现报告的那一套）—— 默认
# "full" = 各列取各自有效期次（信息更满，但与报告口径不一致）
WINDOW = "V1"
WINDOW_CHOICES = ("V1", "full")

# V1 的 SARIMA 候选池：3 组非季节阶 × 4 组季节阶 = 12 组，初始窗内按 AIC 选一
SARIMA_ORDERS = [(0, 1, 1), (1, 1, 0), (1, 1, 1)]
SARIMA_SEASONAL_ORDERS = [
    (0, 0, 0, SEASONAL_PERIODS),
    (1, 0, 0, SEASONAL_PERIODS),
    (0, 0, 1, SEASONAL_PERIODS),
    (1, 0, 1, SEASONAL_PERIODS),
]
SARIMA_FALLBACK = ((0, 1, 1), (0, 0, 0, SEASONAL_PERIODS))


# ---------------------------------------------------------------- 数据装载

def load_series(out_dir, window=WINDOW):
    """返回 {discipline: {series_name: pd.Series}}，索引为 6 位期次字符串。

    series_name: total_cites / threshold_1pct / n_inst_1pct / rank

    `window="V1"`（默认）：只取**四列齐备的公共窗口**——对齐 V1 交接包的装载口径，
    也是复现已发布报告的那一套。实测 22 个学科一致：公共窗口长度**恒等于「云大国内排名」列的长度**
    （多数 42 期，Chemistry/Physics 等 8 科 45 期），因此被引恒 45→42、前1%机构数 44→42 都被压短。
    代价与取舍见模块 docstring 末段。
    `window="full"`：各列取各自有效期次（被引 45 期、机构数 44 期、排名 42 期），信息用得更满，
    但与报告口径不一致，**不能用于复现报告**，只作对照。
    """
    out_dir = Path(out_dir)
    tc = pd.read_parquet(out_dir / "wide" / "total_cites.parquet")
    th = pd.read_parquet(out_dir / "wide" / "threshold_1pct.parquet")
    long = pd.read_parquet(out_dir / "ledger_long.parquet")
    rk = long[long.source == "rank_cn"].pivot_table(
        index="period", columns=["metric", "discipline"], values="value")

    out = {}
    for d in tc.index:
        s = {}
        for name, frame in (("total_cites", tc), ("threshold_1pct", th)):
            if d in frame.index:
                v = frame.loc[d].dropna()
                s[name] = v[[c for c in v.index if str(c).isdigit()]].astype(float)
        for name in ("n_inst_1pct", "rank"):
            if (name, d) in rk.columns:
                v = rk[(name, d)].dropna()
                s[name] = v[[c for c in v.index if str(c).isdigit()]].astype(float)
        if len(s) == 4:
            if window == "V1":
                common = set.intersection(*(set(v.index) for v in s.values()))
                s = {k: v.loc[[p for p in v.index if p in common]] for k, v in s.items()}
            out[d] = s
    return out


def current_period(series, dim):
    """当前期 = 该维度两条序列共同的最后一个有效期次。"""
    a, b = dim
    common = [p for p in series[a].index if p in series[b].index]
    return max(common)


DIMS = {
    "被引维度": ("total_cites", "threshold_1pct"),
    "排名维度": ("n_inst_1pct", "rank"),
}


def potential_disciplines(series, period):
    """尚未进入 ESI 前1% 的学科：当前期 总被引 / 前1%阈值 < 1。"""
    return sorted(
        d for d, s in series.items()
        if period in s["total_cites"].index and period in s["threshold_1pct"].index
        and s["threshold_1pct"][period] > 0
        and s["total_cites"][period] / s["threshold_1pct"][period] < 1.0
    )


def next_periods(start, n):
    """双月期次序列：202607 → 202609, 202611, 202701 …"""
    y, m = int(start[:4]), int(start[4:])
    out = []
    for _ in range(n):
        m += 2
        if m > 12:
            m -= 12
            y += 1
        out.append(f"{y}{m:02d}")
    return out


# ---------------------------------------------------------------- 五模型

def _new_model(name, y):
    """**对照口径**（`IMPL="statespace"`）的模型构造：statespace 版，参数每期重估。

    statsmodels 0.15 的接口口径：statespace 版 ExponentialSmoothing 的 trend 是布尔量、
    seasonal 直接传季节期数（不是 seasonal_periods）；SARIMAX 无 initialization_method 参数。
    """
    y = np.asarray(y, dtype=float)
    if name == "Holt":
        return ExponentialSmoothing(y, trend=True, damped_trend=False,
                                    initialization_method="estimated")
    if name == "阻尼Holt":
        return ExponentialSmoothing(y, trend=True, damped_trend=True,
                                    initialization_method="estimated")
    if name == "季节性ETS":
        return ExponentialSmoothing(y, trend=True, seasonal=SEASONAL_PERIODS,
                                    initialization_method="estimated")
    if name == "SARIMA":
        return SARIMAX(y, order=(1, 1, 1), seasonal_order=(1, 0, 1, SEASONAL_PERIODS),
                       enforce_stationarity=False, enforce_invertibility=False)
    if name == "经验贝叶斯状态空间":
        return UnobservedComponents(y, level="local linear trend",
                                    seasonal=SEASONAL_PERIODS, stochastic_seasonal=True)
    raise ValueError(name)


def select_sarima_structure(y_initial):
    """V1 口径：初始窗内按 AIC 从 3×4=12 组候选里选阶。

    对应 `model_core_v1.select_sarima_structure`。12 组全失败时回落到
    `(0,1,1)(0,0,0,6)`（V1 同款兜底），而不是抛错——否则该学科整条链断掉。
    """
    y_initial = np.asarray(y_initial, dtype=float)
    best, best_aic = None, float("inf")
    for order in SARIMA_ORDERS:
        for seasonal_order in SARIMA_SEASONAL_ORDERS:
            try:
                aic = float(SARIMAX(
                    y_initial, order=order, seasonal_order=seasonal_order, trend=None,
                    enforce_stationarity=False, enforce_invertibility=False,
                ).fit(disp=False, maxiter=80).aic)
            except Exception:
                continue
            if np.isfinite(aic) and aic < best_aic:
                best, best_aic = (order, seasonal_order), aic
    return best if best is not None else SARIMA_FALLBACK


def calibrate_state_space_params(y_initial):
    """V1 口径：初始窗内 MLE 估出方差超参并返回，供后续各期**冻结复用**。"""
    model = UnobservedComponents(np.asarray(y_initial, dtype=float),
                                 level="local linear trend", seasonal=SEASONAL_PERIODS)
    return np.asarray(model.fit(disp=False, maxiter=100).params, dtype=float)


def _fit_v1(name, y, sarima_structure=None, state_space_params=None):
    """V1 口径拟合（对齐 `ESI_Workflow_Model_V1_Handoff/model_core_v1.py::fit_model`）。

    「冻结」体现在两个入参：`sarima_structure` 与 `state_space_params` 都应由**初始窗**
    （前 MIN_TRAIN 期）算一次后逐期复用。缺省时本函数按当前 y 现算一次，
    因此单次调用（如 `forecast_band`）也是自洽的。
    """
    y = np.asarray(y, dtype=float)
    if name == "Holt":
        return Holt(y, damped_trend=False, initialization_method="estimated").fit(optimized=True)
    if name == "阻尼Holt":
        return Holt(y, damped_trend=True, initialization_method="estimated").fit(optimized=True)
    if name == "季节性ETS":
        return HWES(y, trend="add", damped_trend=False, seasonal="add",
                    seasonal_periods=SEASONAL_PERIODS,
                    initialization_method="estimated").fit(optimized=True, use_brute=False)
    if name == "SARIMA":
        order, seasonal_order = sarima_structure or select_sarima_structure(y[:MIN_TRAIN])
        return SARIMAX(y, order=order, seasonal_order=seasonal_order, trend=None,
                       enforce_stationarity=False,
                       enforce_invertibility=False).fit(disp=False, maxiter=100)
    if name == "经验贝叶斯状态空间":
        model = UnobservedComponents(y, level="local linear trend", seasonal=SEASONAL_PERIODS)
        if state_space_params is None:
            return model.fit(disp=False, maxiter=100)
        # 冻结超参，只按新数据滤隐状态
        return model.smooth(np.asarray(state_space_params, dtype=float))
    raise ValueError(name)


def _fit_statespace(name, y):
    """对照口径拟合：statespace 版 + 扩展窗口内每期重估。"""
    return _new_model(name, y).fit(disp=False, maxiter=200)


def fit_model(name, y, impl=IMPL, sarima_structure=None, state_space_params=None):
    """返回 (forecast_fn, fitted_values, ok)。forecast_fn(h) -> np.ndarray(h)。

    `impl` 见模块 docstring。`sarima_structure` / `state_space_params` 只在 impl="V1"
    时生效；不传则由 `_fit_v1` 按当前 y 的初始窗现算一次。
    """
    y = np.asarray(y, dtype=float)
    try:
        if impl == "V1":
            res = _fit_v1(name, y, sarima_structure, state_space_params)
        elif impl in IMPL_CHOICES:
            res = _fit_statespace(name, y)
        else:
            raise ValueError(f"未知口径：{impl}（可选 {IMPL_CHOICES}）")
        one = float(np.asarray(res.forecast(1), dtype=float).reshape(-1)[0])
    except Exception:
        return None, None, False
    if not np.isfinite(one):
        return None, None, False

    def fc(h):
        return np.asarray(res.forecast(h), dtype=float)

    fitted = np.asarray(getattr(res, "fittedvalues", []), dtype=float)
    return fc, fitted, True


def frozen_inputs(y, name, impl=IMPL, min_train=MIN_TRAIN):
    """按口径给出「初始窗算一次、全程复用」的冻结输入 (sarima_structure, state_space_params)。

    V1 口径下 SARIMA 的阶与经验贝叶斯的方差超参都只在初始窗内定一次；
    对照口径（每期重估）两者同为 None，由 `_fit_statespace` 每期自己算。
    """
    if impl != "V1":
        return None, None
    yi = np.asarray(y, dtype=float)[:min_train]
    sar = select_sarima_structure(yi) if name == "SARIMA" else None
    ssp = calibrate_state_space_params(yi) if name == "经验贝叶斯状态空间" else None
    return sar, ssp


def expanding_backtest(y, name, min_train=MIN_TRAIN, impl=IMPL):
    """游走前推一步回测：fit(y[:k]) → pred(k)，返回相对误差数组 pred/act-1。"""
    y = np.asarray(y, dtype=float)
    sar, ssp = frozen_inputs(y, name, impl, min_train)
    errs = []
    for k in range(min_train, len(y)):
        fc, _, ok = fit_model(name, y[:k], impl, sar, ssp)
        if not ok:
            continue
        p = float(fc(1)[0])
        act = y[k]
        if act == 0 or not np.isfinite(p):
            continue
        errs.append(p / act - 1.0)
    return np.asarray(errs)


# ---------------------------------------------------------------- 选模

def evaluate_discipline(s, discipline, dim_name, dim, impl=IMPL):
    """对某学科某维度跑五模型回测，返回逐模型指标 DataFrame。s 为该学科的序列字典。"""
    a, b = dim
    recs = []
    for name in MODELS:
        row = {"discipline": discipline, "dim": dim_name, "model": name}
        ok_all = True
        for tag, key in (("A", a), ("B", b)):
            y = s[key]
            errs = expanding_backtest(y, name, impl=impl)
            if len(errs) < 3:
                ok_all = False
                row[f"rolling_{tag}"] = np.nan
                row[f"fit_{tag}"] = np.nan
                continue
            row[f"rolling_{tag}"] = float(np.mean(np.abs(errs)) * 100)
            fc, fitted, ok = fit_model(name, y, impl)
            if ok and len(fitted) == len(y):
                row[f"fit_{tag}"] = float(np.mean(np.abs(fitted / y - 1)) * 100)
            else:
                row[f"fit_{tag}"] = np.nan
        row["usable"] = ok_all
        row["rolling_mape"] = np.nanmean([row["rolling_A"], row["rolling_B"]])
        row["fit_mape"] = np.nanmean([row["fit_A"], row["fit_B"]])
        row["both_under5"] = bool(row["rolling_A"] < 5 and row["rolling_B"] < 5)
        recs.append(row)
    df = pd.DataFrame(recs)
    df["rank"] = df["rolling_mape"].rank(method="min")
    return df


# ---------------------------------------------------------------- 预测区间 + 过线

def _err_quantiles(errs):
    """一步相对误差的 (q10, q50, q90)。"""
    if len(errs) < 3:
        return None
    return tuple(float(np.quantile(errs, q)) for q in (Q_LO, 0.5, Q_HI))


def forecast_band(series, name, h, impl=IMPL):
    """点预测 + 80% 区间。返回 (point[h], lo[h], hi[h])。

    区间口径：回测期一步相对误差的经验分位数；第 h 步按 sqrt(h) 放大离散度、保留中位偏差。
    """
    y = series.to_numpy(dtype=float)
    fc, _, ok = fit_model(name, y, impl)
    if not ok:
        return None
    point = np.asarray(fc(h), dtype=float)
    q = _err_quantiles(expanding_backtest(y, name, impl=impl))
    if q is None:
        return point, point.copy(), point.copy()
    q10, q50, q90 = q
    scale = np.sqrt(np.arange(1, h + 1))
    # 第 h 步相对误差 = q50 + (q_p − q50) × sqrt(h)
    lo = point * (1 + (q50 + (q10 - q50) * scale))
    hi = point * (1 + (q50 + (q90 - q50) * scale))
    return point, lo, hi


def crossing_time(s, dim, model, horizon=DEFAULT_HORIZON, impl=IMPL):
    """给出「最早 / 最可能 / 最晚」过线期次（比值 ≥ 1）。s 为该学科的序列字典。

    比值 = A / B。区间传播取保守组合：比值下界 = A_lo/B_hi，上界 = A_hi/B_lo。
    """
    a, b = dim
    periods = next_periods(current_period(s, dim), horizon)
    empty = {"cur_ratio": np.nan, "earliest": None, "likely": None, "latest": None,
             "ratio_end": np.nan, "horizon_end": periods[-1]}
    fa = forecast_band(s[a], model, horizon, impl)
    fb = forecast_band(s[b], model, horizon, impl)
    if fa is None or fb is None:
        return empty
    pa, la, ha = fa
    pb, lb, hb = fb
    eps = 1e-9
    r_pt = pa / np.where(np.abs(pb) < eps, eps, pb)
    r_hi = ha / np.where(np.abs(lb) < eps, eps, lb)
    r_lo = la / np.where(np.abs(hb) < eps, eps, hb)

    def first(arr):
        idx = np.where(arr >= 1)[0]
        return periods[idx[0]] if len(idx) else None

    cp = current_period(s, dim)
    return {
        "cur_ratio": float(s[a][cp] / s[b][cp]),
        "earliest": first(r_hi),
        "likely": first(r_pt),
        "latest": first(r_lo),
        "ratio_end": float(r_pt[-1]),
        "horizon_end": periods[-1],
    }


# ---------------------------------------------------------------- 主流程

def run(out_dir="out/202607", horizon=DEFAULT_HORIZON, impl=IMPL, window=WINDOW):
    series = load_series(out_dir, window)
    ref = current_period(series["Chemistry"], DIMS["被引维度"])
    discs = potential_disciplines(series, ref)

    metrics, crossing = [], []
    for d in discs:
        for dim_name, dim in DIMS.items():
            ev = evaluate_discipline(series[d], d, dim_name, dim, impl)
            metrics.append(ev)
            usable = ev[ev.usable & ev.rolling_mape.notna()].sort_values("rolling_mape")
            if usable.empty:
                continue
            best = usable.iloc[0]
            runner = usable.iloc[1] if len(usable) > 1 else None
            ct = crossing_time(series[d], dim, best["model"], horizon, impl)
            crossing.append({
                "discipline": d, "dim": dim_name, "model": best["model"],
                "fit_mape": round(best["fit_mape"], 2), "rolling_mape": round(best["rolling_mape"], 2),
                "rolling_A": round(best["rolling_A"], 2), "rolling_B": round(best["rolling_B"], 2),
                "gap": round(best["rolling_mape"] - best["fit_mape"], 2),
                "both_under5": bool(best["both_under5"]),
                "runner_up": runner["model"] if runner is not None else None,
                "runner_up_mape": round(runner["rolling_mape"], 2) if runner is not None else None,
                **ct,
            })

    m = pd.concat(metrics, ignore_index=True)
    m["impl"] = impl
    c = pd.DataFrame(crossing)
    for col in ("earliest", "likely", "latest"):          # 写成 2027-01，避免被当数字
        if col in c.columns:
            c[col] = c[col].map(lambda p: f"{p[:4]}-{p[4:]}" if isinstance(p, str) else None)
    cmp_df = compare_with_report(m)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m.to_csv(out / "forecast_select_models.csv", index=False, encoding="utf-8-sig")
    c.to_csv(out / "forecast_select_crossing.csv", index=False, encoding="utf-8-sig")
    cmp_df.to_csv(out / "forecast_select_vs_report.csv", index=False, encoding="utf-8-sig")
    (out / "预测选模与过线.md").write_text(render_md(ref, discs, m, c, cmp_df), encoding="utf-8")
    return m, c


DIM_ALIAS = {
    "被引维度": ("总被引", "前1%阈值"),
    "排名维度": ("云大国内排名", "前1%机构数"),
}

# 两份报告公开发表的「综合滚动 MAPE」（合成自报告正文的表2–表9），用于复现性对照。
# 报告② 的"Holt趋势"在报告① 里写"Holt"，此处统一映射到本模块的 "Holt"。
REPORT_REF = {
    "被引维度": {
        "Molecular Biology & Genetics": {"季节性ETS": 1.96, "经验贝叶斯状态空间": 1.99, "SARIMA": 2.10, "Holt": 3.61, "阻尼Holt": 3.63},
        "Physics": {"经验贝叶斯状态空间": 3.33, "阻尼Holt": 4.06, "Holt": 4.18, "SARIMA": 4.26, "季节性ETS": 4.41},
        "Economics & Business": {"SARIMA": 1.72, "阻尼Holt": 4.39, "经验贝叶斯状态空间": 4.67, "Holt": 4.68, "季节性ETS": 5.71},
        "Immunology": {"季节性ETS": 2.99, "SARIMA": 3.14, "阻尼Holt": 3.28, "Holt": 3.41, "经验贝叶斯状态空间": 3.57},
        "Neuroscience & Behavior": {"季节性ETS": 2.27, "SARIMA": 2.53, "经验贝叶斯状态空间": 2.84, "阻尼Holt": 3.57, "Holt": 3.59},
        "Psychiatry/Psychology": {"经验贝叶斯状态空间": 1.62, "阻尼Holt": 1.92, "SARIMA": 1.93, "Holt": 2.08, "季节性ETS": 2.24},
        "Space Science": {"SARIMA": 1.61, "季节性ETS": 1.89, "Holt": 2.30, "阻尼Holt": 2.72, "经验贝叶斯状态空间": 2.78},
        "Multidisciplinary": {"Holt": 7.78, "阻尼Holt": 7.88, "SARIMA": 8.30, "季节性ETS": 8.43, "经验贝叶斯状态空间": 9.74},
    },
    "排名维度": {
        "Molecular Biology & Genetics": {"阻尼Holt": 1.70, "SARIMA": 1.79, "Holt": 1.87, "季节性ETS": 1.88, "经验贝叶斯状态空间": 1.88},
        "Physics": {"经验贝叶斯状态空间": 2.32, "阻尼Holt": 2.51, "SARIMA": 2.55, "Holt": 2.60, "季节性ETS": 2.69},
        "Economics & Business": {"阻尼Holt": 1.15, "SARIMA": 1.27, "经验贝叶斯状态空间": 1.38, "季节性ETS": 1.42, "Holt": 1.48},
        "Immunology": {"阻尼Holt": 2.19, "Holt": 2.51, "SARIMA": 2.53, "经验贝叶斯状态空间": 2.63, "季节性ETS": 2.93},
        "Neuroscience & Behavior": {"SARIMA": 1.67, "Holt": 1.74, "经验贝叶斯状态空间": 2.04, "季节性ETS": 2.08, "阻尼Holt": 2.09},
        "Psychiatry/Psychology": {"SARIMA": 1.45, "阻尼Holt": 1.69, "Holt": 1.75, "经验贝叶斯状态空间": 2.14, "季节性ETS": 2.17},
        "Space Science": {"SARIMA": 2.25, "经验贝叶斯状态空间": 2.57, "阻尼Holt": 2.61, "季节性ETS": 2.61, "Holt": 2.83},
        "Multidisciplinary": {"阻尼Holt": 8.62, "Holt": 8.67, "季节性ETS": 8.81, "经验贝叶斯状态空间": 8.84, "SARIMA": 9.46},
    },
}


def compare_with_report(m):
    """逐学科对照报告发表值：第 1 名是否一致 + 五模型名次 Spearman 秩相关。"""
    rows = []
    for (dim, d), g in m.groupby(["dim", "discipline"]):
        ref = REPORT_REF.get(dim, {}).get(d)
        if not ref:
            continue
        mine = g.set_index("model")["rolling_mape"]
        common = [k for k in ref if k in mine.index]
        if len(common) < 3:
            continue
        a = pd.Series({k: ref[k] for k in common})
        b = mine[common]
        rows.append({
            "discipline": d, "dim": dim,
            "报告首选": a.idxmin(), "本文首选": b.idxmin(),
            "首选一致": a.idxmin() == b.idxmin(),
            "秩相关": round(a.rank().corr(b.rank(), method="pearson"), 2),
            "中位偏差pp": round(float((b - a).abs().median()), 2),
        })
    return pd.DataFrame(rows)


def render_md(ref, discs, m, c, cmp_df=None, impl=IMPL, window=WINDOW):
    L = [f"# 预测选模与预计过线时间（基准期 {ref}）", ""]
    L.append(f"潜力学科 {len(discs)} 个（当前期被引接近度 < 1）：{'、'.join(discs)}")
    L.append("")
    L.append("口径：五模型扩展窗口一步回测（前 30 期训练）；选模取两序列滚动 MAPE 等权平均最低；"
             "区间为回测相对误差经验分位数的 sqrt(h) 外推。详见 `src/forecast_select.py` docstring。")
    L.append("")
    impl_note = {
        "V1": "**实现口径 = V1**（`ESI_Workflow_Model_V1_Handoff`，即报告实际口径）："
              "Holt/季节性ETS 走 `tsa.holtwinters`；SARIMA 在初始 30 期内按 AIC 从 12 组候选选阶后固定；"
              "经验贝叶斯的方差超参在初始窗估出后**冻结**（只滤隐状态）。对报告首选 15/16 命中。",
        "statespace": "**实现口径 = statespace（对照）**：五模型一律走 statespace 版且每期重估超参。"
                      "此口径对报告首选仅 7/16 命中，其中混入实现差异，**不应用于结论**，仅供复核旧结论。",
    }.get(impl, f"实现口径 = {impl}（未知）")
    L.append(impl_note)
    L.append("")
    win_note = {
        "V1": "**序列窗口 = 四列齐备的公共窗口**（V1 装载口径，复现报告的那一套）："
              "201909～202607 共 42 期。卡住窗口的是「云大国内排名」列（201903/05/07 无值）——"
              "实测 22 学科一致，公共窗口长度恒等于排名列长度。代价：被引 45→42、"
              "前1%机构数 44→42，均被压短。",
        "full": "**序列窗口 = 各列各自长度（对照）**：被引 45 期、前1%机构数 44 期、排名 42 期，"
                "信息更满，但与报告口径不一致，数字不可与报告对照。",
    }.get(window, f"序列窗口 = {window}（未知）")
    L.append(win_note)
    L.append("")
    if c.empty:
        L.append("（无可选模型，未产出过线时间）")
        return "\n".join(L)
    for dim_name, (a_tag, b_tag) in DIM_ALIAS.items():
        sub = c[c.dim == dim_name]
        if sub.empty:
            continue
        L.append(f"## {dim_name}（{a_tag} / {b_tag}）")
        L.append("")
        L.append(f"| 学科 | 推荐模型 | 拟合MAPE | 滚动MAPE | {a_tag} | {b_tag} | Gap | 双序列<5% | "
                 f"当前接近度 | 最早过线 | 最可能过线 | 最晚过线 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for _, r in sub.iterrows():
            fmt = lambda v: "—" if v is None or (isinstance(v, float) and np.isnan(v)) else v
            L.append(f"| {r.discipline} | {r.model} | {r.fit_mape}% | {r.rolling_mape}% | "
                     f"{r.rolling_A}% | {r.rolling_B}% | {r.gap}% | {'是' if r.both_under5 else '否'} | "
                     f"{r.cur_ratio*100:.2f}% | {fmt(r.earliest)} | {fmt(r.likely)} | {fmt(r.latest)} |")
        L.append("")
        L.append(f"（外推上限 {sub.horizon_end.iloc[0][:4]}-{sub.horizon_end.iloc[0][4:]}；"
                 f"空值表示该窗口内未过线）")
        L.append("")
    if cmp_df is not None and not cmp_df.empty:
        L.append("## 与两份报告发表值的对照（复现性证据）")
        L.append("")
        L.append("报告未披露实现超参，故用本模块口径重算后逐学科对照：`秩相关` 为五模型名次的"
                 "Spearman 秩相关，`中位偏差pp` 为我方与报告滚动 MAPE 之差的中位数。")
        L.append("")
        L.append("| 学科 | 维度 | 报告首选 | 本文首选 | 首选一致 | 秩相关 | 中位偏差pp |")
        L.append("|---|---|---|---|---|---|---|")
        for _, r in cmp_df.iterrows():
            L.append(f"| {r.discipline} | {r.dim} | {r['报告首选']} | {r['本文首选']} | "
                     f"{'✓' if r['首选一致'] else '✗'} | {r['秩相关']} | {r['中位偏差pp']} |")
        L.append("")
        L.append(f"首选一致 {int(cmp_df['首选一致'].sum())}/{len(cmp_df)}；"
                 f"秩相关中位数 {cmp_df['秩相关'].median():.2f}；"
                 f"滚动 MAPE 中位偏差 {cmp_df['中位偏差pp'].median():.2f}pp。")
        L.append("")
    L.append("## 需要注意")
    L.append("")
    L.append("- 「最可能」用点预测，「最早/最晚」用 80% 区间边界；三者跨度大说明该学科过线时点不确定性高。")
    L.append("- 回测窗仅 12–15 期，前二名 MAPE 之差通常不具统计可区分性，选模只区分量级。")
    L.append("- 排名维度为序数序列，其 MAPE 不可与被引维度横比。")
    L.append("- 本模块是研究线工具，不替代生产线方法 B（`src/forecast.py`）。")
    return "\n".join(L)


def main(out_dir="out/202607", horizon=DEFAULT_HORIZON, impl=IMPL, window=WINDOW):
    series = load_series(out_dir, window)
    ref = current_period(series["Chemistry"], DIMS["被引维度"])
    discs = potential_disciplines(series, ref)
    m, c = run(out_dir, horizon, impl, window)
    txt = render_md(ref, discs, m, c, compare_with_report(m), impl, window)
    print(txt)
    return m, c


def _cli():
    args = sys.argv[1:]
    opts = {"--impl": IMPL, "--window": WINDOW}
    for flag in opts:
        if flag in args:                       # 对照口径 / 对照窗口，复核旧结论用
            i = args.index(flag)
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    main(args[0] if args else "out/202607", DEFAULT_HORIZON, opts["--impl"], opts["--window"])


if __name__ == "__main__":
    _cli()
