"""ESI双路线V1预测页面的数据编排与PNG图表。"""

from __future__ import annotations

import base64
import io
import math

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

from charts import STACK as CHART_FONT_STACK
from esi_v1.config_v1 import MODEL_NAMES, MODEL_PACKAGE_VERSION
from esi_v1.data import latest_ready_period, load_standard_input, subject_task_data
from esi_v1.service import run_prediction

from . import config


ROUTES = [
    {"value": "citation", "label": "路线1 · 总被引 / ESI前1%被引阈值"},
    {"value": "rank", "label": "路线2 · 国内排名 / 国内前1%机构数"},
]
MODEL_OPTIONS = [
    {"value": "recommended", "label": "V1基线推荐模型"},
    {"value": "all", "label": "五模型全部运行比较"},
    *({"value": name, "label": name} for name in MODEL_NAMES),
]


def _load():
    period_dir = latest_ready_period(config.OUT_DIR)
    data, meta = load_standard_input(period_dir)
    return period_dir, data, meta


def page_context() -> dict:
    try:
        period_dir, _data, meta = _load()
        return {
            "available": True,
            "source_period": period_dir.name,
            "subjects": meta["subjects"],
            "routes": ROUTES,
            "models": MODEL_OPTIONS,
            "model_version": MODEL_PACKAGE_VERSION,
            "load_error": "",
        }
    except Exception as exc:
        return {
            "available": False,
            "source_period": "",
            "subjects": [],
            "routes": ROUTES,
            "models": MODEL_OPTIONS,
            "model_version": MODEL_PACKAGE_VERSION,
            "load_error": str(exc),
        }


def _chart(result: dict, item: dict) -> str:
    names = result["metric_names"]
    history = result["history"]
    forecast = item["forecast"]
    hp = [str(x["period"]) for x in history]
    fp = [str(x["period"]) for x in forecast]
    xh = list(range(len(hp)))
    xf = list(range(len(hp), len(hp) + len(fp)))

    # 用独立 Figure，避免线程池里多个预测请求共享 pyplot 的当前图状态。
    fig = Figure(figsize=(8.2, 3.6), dpi=130)
    ax = fig.subplots()
    colors = ("#4472C4", "#70AD47")
    for idx, (key, name, color) in enumerate(zip(("metric1", "metric2"), names, colors)):
        hv = [row[key] for row in history]
        fv = [row[key] for row in forecast]
        ax.plot(xh, hv, color=color, linewidth=1.8, label=f"{name}·历史")
        if hv:
            ax.plot([xh[-1], *xf], [hv[-1], *fv], color=color, linewidth=1.8,
                    linestyle="--", label=f"{name}·预测")
    ax.axvline(len(hp) - 0.5, color="#B23A2A", linewidth=1, alpha=.8)
    ticks = xh + xf
    labels = hp + fp
    step = max(1, len(ticks) // 10)
    shown = ticks[::step]
    if ticks and ticks[-1] not in shown:
        shown.append(ticks[-1])
    ax.set_xticks(shown, [labels[i] for i in shown], rotation=35, ha="right", fontsize=7)
    ax.grid(axis="y", color="#D8D5CC", linewidth=.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(f"{result['subject']} · {item['model']}", fontsize=11,
                 fontfamily=CHART_FONT_STACK)
    ax.legend(frameon=False, ncol=2, fontsize=8, loc="upper left",
              prop={"family": CHART_FONT_STACK, "size": 8})
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="#FBFAF7")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _json_safe(value):
    """Starlette拒绝NaN/Infinity；接口在边界层统一转换为JSON的null。"""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("预测请求必须是JSON对象。")
    period_dir, data, meta = _load()
    subject = str(payload.get("subject") or "").strip()
    task = str(payload.get("task") or "").strip()
    model = str(payload.get("model") or "recommended").strip()
    try:
        horizon = int(payload.get("horizon", 18))
    except (TypeError, ValueError):
        raise ValueError("预测期数必须是整数。")
    if subject not in meta["subjects"]:
        raise ValueError("所选学科不在当前潜力学科数据中。")
    periods, series = subject_task_data(data, subject, task)
    result = run_prediction(subject, periods, series, task, model, horizon)
    result["source_period"] = period_dir.name
    for item in result["results"]:
        item["chart"] = _chart(result, item)
    return _json_safe(result)
