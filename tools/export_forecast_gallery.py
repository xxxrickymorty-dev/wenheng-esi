# -*- coding: utf-8 -*-
"""批量导出「五模型预测图」画廊：8 个潜力学科 × 2 条路线 × 5 个候选模型。

口径 = 研究线 `src/forecast_select.py`（V1 实现，与报告实际口径对齐），
基准期默认 202607（与《双路线未来18期预估报告》《五模型比较与选模分析报告》
同一基准）。产物落在 `web/public/forecast/<期次>/`：80 张 PNG + index.json，
页面直接引用——零后端依赖、断网可用、同一数据重复运行结果一致。

用法（仓根、venv）：
    .venv\\Scripts\\python.exe tools\\export_forecast_gallery.py
    .venv\\Scripts\\python.exe tools\\export_forecast_gallery.py --period 202609
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import charts as chart_style  # noqa: E402  （导入即设置中文字体栈）
import forecast_select as fs  # noqa: E402
from esi_v1.data import display_name  # noqa: E402

MODEL_SLUG = {
    "Holt": "holt",
    "阻尼Holt": "damped_holt",
    "季节性ETS": "seasonal_ets",
    "SARIMA": "sarima",
    "经验贝叶斯状态空间": "bayesian_ss",
}

ROUTE_META = {
    "被引维度": {
        "key": "citation",
        "label": "路线 1 · 总被引 × ESI 前 1% 阈值",
        "metric_a": "总被引频次",
        "metric_b": "ESI 前 1% 被引阈值",
    },
    "排名维度": {
        "key": "rank",
        "label": "路线 2 · 国内排名 × 前 1% 机构数",
        "metric_a": "云大国内排名",
        "metric_b": "国内前 1% 机构数",
    },
}

#: 图例与线色（与站内试跑图一致：指标1 蓝、指标2 绿；实际实线 / 模型虚线）
C_A = "#4472C4"
C_B = "#70AD47"
C_DIVIDER = "#B23A2A"
INK = "#1F2937"
WARMUP = fs.MIN_TRAIN  # 拟合 MAPE 跳过冷启动前 6 期（V1 清单 fit_mape_start_index）


def subject_slug(en_name: str) -> str:
    return (en_name.lower().replace(" & ", "_and_").replace(" ", "_")
            .replace("/", "_"))


def fmt_period(p) -> str:
    p = str(p)
    return f"{p[:4]}-{p[4:]}"


def fit_and_metrics(series, name):
    """返回 (拟合值, 点预测(h=horizon 由外部截取), 回测相对误差)；无法拟合时 None。"""
    y = series.to_numpy(dtype=float)
    fc, fitted, ok = fs.fit_model(name, y, fs.IMPL)
    if not ok:
        return None
    errs = fs.expanding_backtest(y, name, impl=fs.IMPL)
    return {
        "fitted": np.asarray(fitted, dtype=float),
        "forecast": fc,
        "errs": errs,
    }


def band(point, errs, h):
    q = fs._err_quantiles(errs)
    if q is None:
        return point.copy(), point.copy()
    q10, q50, q90 = q
    scale = np.sqrt(np.arange(1, h + 1))
    lo = point * (1 + (q50 + (q10 - q50) * scale))
    hi = point * (1 + (q50 + (q90 - q50) * scale))
    return lo, hi


def first_cross(periods, ratio):
    for p, r in zip(periods, ratio):
        if np.isfinite(r) and r >= 1:
            return p
    return None


def draw_chart(subject_cn, model, route_key, hist_periods, actual_a, actual_b,
               model_a, model_b, fut_periods, fut_a, fut_b, crossing, out_png):
    ink = INK
    fig = Figure(figsize=(8.4, 3.7), dpi=96)
    ax = fig.subplots()
    n_h = len(hist_periods)
    xh = list(range(n_h))
    xf = list(range(n_h, n_h + len(fut_periods)))
    all_p = [fmt_period(p) for p in list(hist_periods) + list(fut_periods)]

    ax.plot(xh, actual_a, color=C_A, lw=1.8, label="总被引/排名·实际", zorder=3)
    ax.plot(xh, actual_b, color=C_B, lw=1.8, label="阈值/机构数·实际", zorder=3)

    for values, fut, color in ((model_a, fut_a, C_A), (model_b, fut_b, C_B)):
        xs, ys = [], []
        for x, v in zip(xh, values):
            if math.isfinite(float(v)):
                xs.append(x)
                ys.append(float(v))
        if xs:
            xs += xf
            ys += [float(v) for v in np.asarray(fut, dtype=float)]
            ax.plot(xs, ys, color=color, lw=1.5, ls="--", alpha=.9, zorder=2)

    ax.axvline(n_h - 0.5, color=C_DIVIDER, lw=1, alpha=.75, zorder=1)
    if crossing is not None and crossing in list(fut_periods):
        xi = n_h + list(fut_periods).index(crossing)
        ax.axvline(xi, color=C_DIVIDER, lw=1, ls=":", alpha=.7, zorder=1)
        va = float(np.asarray(fut_a, dtype=float)[xi - n_h])
        ax.scatter([xi], [va], s=46, facecolor="none", edgecolor=C_DIVIDER,
                   linewidth=1.6, zorder=5)
        ax.annotate(f"首次过线 {fmt_period(crossing)}", xy=(xi, va),
                    xytext=(6, 14), textcoords="offset points", fontsize=8.6,
                    color=C_DIVIDER)

    tick_idx = [i for i, p in enumerate(all_p) if p.endswith("-01")]
    if len(tick_idx) > 12:
        tick_idx = tick_idx[::2]
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([all_p[i] for i in tick_idx], fontsize=8)
    ax.set_xlim(-0.6, len(all_p) - 0.4)
    ax.grid(axis="y", color="#E8EAED", lw=.7)
    ax.spines[["top", "right"]].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#D1D5DB")
    ax.tick_params(labelsize=8.4, colors=ink)
    ax.set_title(f"{subject_cn} · {model}（{'路线1' if route_key == 'citation' else '路线2'}）",
                 fontsize=10.5, color=ink, pad=8)
    ax.legend(frameon=False, ncol=2, fontsize=8, loc="upper left",
              prop={"family": chart_style.STACK, "size": 8})
    fig.tight_layout(pad=0.6)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=96, facecolor="#FBFAF7", bbox_inches="tight")
    del fig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="202607")
    parser.add_argument("--horizon", type=int, default=18)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    period_dir = ROOT / "out" / args.period
    out_dir = pathlib.Path(args.out) if args.out else ROOT / "web" / "public" / "forecast" / args.period
    chart_dir = out_dir / "charts"

    matplotlib.rcParams["font.family"] = chart_style.STACK
    matplotlib.rcParams["axes.unicode_minus"] = False

    series = fs.load_series(period_dir, fs.WINDOW)
    ref = fs.current_period(series["Chemistry"], fs.DIMS["被引维度"])
    discs = fs.potential_disciplines(series, ref)
    print(f"基准期 {args.period}（当前期 {ref}），潜力学科 {len(discs)} 个，"
          f"外推 {args.horizon} 期 → {fs.next_periods(ref, args.horizon)[-1]}")

    subjects_payload = []
    for disc in discs:
        s = series[disc]
        cn = display_name(disc)
        routes = {}
        badge_signals = 0
        max_cur = 0.0
        for dim_name, dim in fs.DIMS.items():
            a, b = dim
            periods_ref = fs.current_period(s, dim)
            fut_periods = fs.next_periods(periods_ref, args.horizon)
            hist_a = s[a]
            hist_b = s[b]
            cur_ratio = float(hist_a[periods_ref]) / float(hist_b[periods_ref])
            rows = []
            for name in fs.MODELS:
                ma = fit_and_metrics(hist_a, name)
                mb = fit_and_metrics(hist_b, name)
                if ma is None or mb is None:
                    continue
                fut_a = np.asarray(ma["forecast"](args.horizon), dtype=float)
                fut_b = np.asarray(mb["forecast"](args.horizon), dtype=float)
                lo_a, hi_a = band(fut_a, ma["errs"], args.horizon)
                lo_b, hi_b = band(fut_b, mb["errs"], args.horizon)
                eps = 1e-9
                r_pt = fut_a / np.where(np.abs(fut_b) < eps, eps, fut_b)
                r_lo = lo_a / np.where(np.abs(hi_b) < eps, eps, hi_b)
                r_hi = hi_a / np.where(np.abs(lo_b) < eps, eps, lo_b)
                point_cross = first_cross(fut_periods, r_pt)
                earliest = first_cross(fut_periods, r_hi)
                latest = first_cross(fut_periods, r_lo)

                def mape(errs):
                    if len(errs) < 3:
                        return None
                    return float(np.mean(np.abs(errs)) * 100)

                def fit_mape(fitted, actual):
                    if fitted is None or len(fitted) != len(actual):
                        return None
                    y = actual.to_numpy(dtype=float)[WARMUP:]
                    part = np.asarray(fitted[WARMUP:], dtype=float)
                    if not len(part) or np.any(y == 0):
                        return None
                    return float(np.mean(np.abs(part / y - 1)) * 100)

                rolling_a = mape(ma["errs"])
                rolling_b = mape(mb["errs"])
                rolling = (None if rolling_a is None or rolling_b is None
                           else (rolling_a + rolling_b) / 2)
                fit_a = fit_mape(ma["fitted"], hist_a)
                fit_b = fit_mape(mb["fitted"], hist_b)
                fit = (None if fit_a is None or fit_b is None else (fit_a + fit_b) / 2)

                slug = f"{subject_slug(disc)}--{ROUTE_META[dim_name]['key']}--{MODEL_SLUG[name]}"
                png = chart_dir / f"{slug}.png"
                draw_chart(cn, name, ROUTE_META[dim_name]["key"], hist_a.index,
                           hist_a, hist_b, ma["fitted"], mb["fitted"],
                           fut_periods, fut_a, fut_b, point_cross, png)
                rows.append({
                    "name": name,
                    "slug": slug,
                    "png": f"charts/{slug}.png",
                    "rolling_mape": None if rolling is None else round(rolling, 2),
                    "rolling_a": None if rolling_a is None else round(rolling_a, 2),
                    "rolling_b": None if rolling_b is None else round(rolling_b, 2),
                    "fit_mape": None if fit is None else round(fit, 2),
                    "point_crossing": point_cross,
                    "earliest": earliest,
                    "latest": latest,
                    "cur_ratio": round(cur_ratio, 4),
                    "end_ratio": round(float(r_pt[-1]), 4),
                })

            usable = [r for r in rows if r["rolling_mape"] is not None]
            selected = min(usable, key=lambda r: r["rolling_mape"])["name"] if usable else None
            if selected:
                sel_row = next(r for r in rows if r["name"] == selected)
                if sel_row["point_crossing"] is not None:
                    badge_signals += 1
            max_cur = max(max_cur, cur_ratio)
            routes[ROUTE_META[dim_name]["key"]] = {
                "label": ROUTE_META[dim_name]["label"],
                "metric_a": ROUTE_META[dim_name]["metric_a"],
                "metric_b": ROUTE_META[dim_name]["metric_b"],
                "current_period": periods_ref,
                "cur_ratio": round(cur_ratio, 4),
                "horizon_end": fut_periods[-1],
                "selected": selected,
                "models": rows,
            }
            best = min((r for r in rows if r["rolling_mape"] is not None),
                       key=lambda r: r["rolling_mape"], default=None)
            print(f"  {cn:14s} {ROUTE_META[dim_name]['key']:8s} "
                  f"推荐={selected}  滚动MAPE={best['rolling_mape'] if best else '—'}  "
                  f"过线={best['point_crossing'] if best else '—'}")

        if badge_signals == 2:
            badge = "双线信号"
        elif badge_signals == 1:
            badge = "单线信号"
        elif max_cur >= 0.6:
            badge = "临近基线"
        else:
            badge = "持续观察"
        subjects_payload.append({
            "en": disc,
            "cn": cn,
            "badge": badge,
            "routes": routes,
        })

    payload = {
        "period": args.period,
        "horizon": args.horizon,
        "generated_from": "src/forecast_select.py（V1 研究线口径）",
        "note": ("图为确定性重算：五模型各自「历史拟合（虚线）+ 18 期点预测」，"
                 "红线为预测起点与首次过线；滚动 MAPE 为扩展窗口一步回测，"
                 "拟合 MAPE 跳过前 6 期冷启动。"),
        "subjects": subjects_payload,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    (out_dir / "index.json").write_text(body, encoding="utf-8")
    # 静态稿要能 file:// 双击打开：fetch 会被 CORS 拦，脚本挂载不受限。
    (out_dir / "index.js").write_text(
        "window.WH_FORECAST_GALLERY = " + body + ";\n", encoding="utf-8")
    n_png = len(list(chart_dir.glob("*.png")))
    print(f"完成：{n_png} 张图 + index.json → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
