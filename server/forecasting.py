"""ESI双路线V1预测页面的数据编排与PNG图表。"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import pathlib
import re

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

from charts import STACK as CHART_FONT_STACK
from esi_v1.config_v1 import (BASELINE_RECOMMENDATIONS_202607, MODEL_NAMES,
                                MODEL_PACKAGE_VERSION)
from esi_v1.data import display_name, latest_ready_period, load_standard_input, subject_task_data
from esi_v1.service import run_prediction

from . import config


#: V1 基线推荐的冻结期次（与 BASELINE_RECOMMENDATIONS_202607 成对）。
#: 前端不写死基线表——写死会跟冻结口径漂移（契约 #16）。
RECOMMENDATION_BASELINE = "202607"

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


def _data_provenance(period_dir: pathlib.Path) -> dict:
    """只回报能从本机文件和完整运行记录核实的来源时间。"""
    workbook = (pathlib.Path(config.ROOT).parent / "数据与复现"
                / "云大全学科排名、阈值动态检测表.xlsx")
    run_log = period_dir / "run_log.json"

    def modified_at(path: pathlib.Path) -> tuple[float | None, str | None]:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return None, None
        value = dt.datetime.fromtimestamp(stamp, tz=dt.timezone.utc)
        return stamp, value.isoformat(timespec="seconds").replace("+00:00", "Z")

    workbook_mtime, workbook_at = modified_at(workbook)
    run_record_mtime = None
    run_record_at = None
    input_info = {"name": None, "last_modified_at": None}
    input_mtime = None
    try:
        record = json.loads(run_log.read_text(encoding="utf-8"))
        if (isinstance(record, dict)
                and record.get("period") == period_dir.name
                and record.get("assertions_ok") is True):
            run_record_mtime, run_record_at = modified_at(run_log)
            raw_input = record.get("input")
            if isinstance(raw_input, str) and raw_input.strip():
                rel = pathlib.PurePosixPath(raw_input.strip().replace("\\", "/"))
                if not rel.is_absolute() and ".." not in rel.parts:
                    input_file = pathlib.Path(config.ROOT).joinpath(*rel.parts)
                    input_mtime, input_at = modified_at(input_file)
                    input_info = {"name": rel.name, "last_modified_at": input_at}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass

    if run_record_mtime is None or workbook_mtime is None:
        freshness = "unverified"
    elif workbook_mtime > run_record_mtime or (
            input_mtime is not None and input_mtime > run_record_mtime):
        freshness = "needs_check"
    else:
        # 旧记录没有台账和输入文件的版本信息，仅凭时间不能确认当前文件已被处理。
        freshness = "unverified"

    return {
        "upstream_workbook": {
            "name": workbook.name,
            "last_modified_at": workbook_at,
        },
        "processed_input": input_info,
        "run_record_at": run_record_at,
        "data_freshness": freshness,
        # 运行记录单独列出处理所用文件，不能证明预测直接读取了工作区主台账。
        "master_workbook_consumption_verified": False,
    }


def page_context() -> dict:
    try:
        period_dir, _data, meta = _load()
        return {
            "available": True,
            "source_period": period_dir.name,
            **_data_provenance(period_dir),
            "subjects": meta["subjects"],
            "routes": ROUTES,
            "models": MODEL_OPTIONS,
            "model_version": MODEL_PACKAGE_VERSION,
            # V1 基线推荐（按路线分）：前端「V1 推荐」列直接读它
            "recommendations": BASELINE_RECOMMENDATIONS_202607,
            "recommendation_baseline": RECOMMENDATION_BASELINE,
            "load_error": "",
        }
    except Exception as exc:
        return {
            "available": False,
            "source_period": "",
            "upstream_workbook": {
                "name": "云大全学科排名、阈值动态检测表.xlsx",
                "last_modified_at": None,
            },
            "processed_input": {"name": None, "last_modified_at": None},
            "run_record_at": None,
            "data_freshness": "unverified",
            "master_workbook_consumption_verified": False,
            "subjects": [],
            "routes": ROUTES,
            "models": MODEL_OPTIONS,
            "model_version": MODEL_PACKAGE_VERSION,
            "recommendations": BASELINE_RECOMMENDATIONS_202607,
            "recommendation_baseline": RECOMMENDATION_BASELINE,
            "load_error": str(exc),
        }


# ---------------------------------------------------------------- 学科板（契约 #20）
_PERIOD_TITLE_RE = re.compile(r"[（(]基准期\s*(20\d{4})[）)]")
_WINDOW_RE = re.compile(r"(20\d{4})[～~—-](20\d{4})")
_EMPTY_CELLS = ("", "-", "--", "—", "–")


def _pct(s):
    """百分数单元格 -> float（"37.62%" -> 37.62）；空值 -> None。"""
    s = (s or "").strip()
    if s in _EMPTY_CELLS:
        return None
    try:
        return float(s.rstrip("%"))
    except ValueError:
        return None


def _cell_date(s):
    s = (s or "").strip()
    return "" if s in _EMPTY_CELLS else s


def _board_row(cells):
    """12 列表格行 -> 学科单条（两条路线共用，第 5/6 列含义随路线不同）。

    学科名出接口前换中文（契约 #22）——md 里是英文名，前端不再自己搭名字桥。
    """
    return {
        "subject": display_name(cells[0]),
        "model": cells[1],
        "fit_mape": _pct(cells[2]),
        "rolling_mape": _pct(cells[3]),
        "cur_value": _pct(cells[4]),
        "threshold": _pct(cells[5]),
        "gap": _pct(cells[6]),
        "both_under_5": cells[7].strip() == "是",
        "prox": _pct(cells[8]),
        "t1": _cell_date(cells[9]),
        "t2": _cell_date(cells[10]),
        "t3": _cell_date(cells[11]),
    }


def _split_md_tables(text):
    """把 markdown 里的连续 | 行切成若干张表（每张 = 行列表）。"""
    tables, cur = [], []
    for ln in text.splitlines():
        if ln.startswith("|"):
            cur.append(ln)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


def board_context(period=None):
    """预测台「学科板」（契约 #20）：解析 `out/<期次>/预测选模与过线.md` 的两张表。

    不重算任何东西——md 是预测阶段写定的；此处只把它序列化。
    缺文件（没跑过预测阶段）返回空板 + note，不 500。
    """
    out = pathlib.Path(config.OUT_DIR)
    if period:
        md = out / period / "预测选模与过线.md"
    else:
        cands = sorted(out.glob("*/预测选模与过线.md"))
        md = cands[-1] if cands else None
    empty = {"period": (period or ""), "window": "",
             "routes": {"citation": [], "rank": []},
             "note": "未找到 预测选模与过线.md（跑一次预测阶段后生成）"}
    if md is None or not md.exists():
        return empty

    text = md.read_text(encoding="utf-8")
    m_period = _PERIOD_TITLE_RE.search(text)
    m_window = _WINDOW_RE.search(text)
    routes = {"citation": [], "rank": []}
    for table in _split_md_tables(text):
        header = [c.strip() for c in table[0].strip("|").split("|")]
        kind = None
        if "总被引" in "".join(header):          # 被引维度：总被引 / 前1%阈值
            kind = "citation"
        elif "云大国内排名" in "".join(header):   # 排名维度
            kind = "rank"
        if kind is None:
            continue
        for ln in table[2:]:                         # table[1] 是 |---| 分隔行
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 12 and not all(set(c) <= {"-", ":"} for c in cells):
                routes[kind].append(_board_row(cells))

    return {
        "period": (m_period.group(1) if m_period else md.parent.name),
        "window": (f"{m_window.group(1)}-{m_window.group(2)}" if m_window else ""),
        "routes": routes,
        "note": ("源：预测选模与过线.md；"
                 "t1/t2/t3 空串＝该窗口内未过线；"
                 "数值为百分数点值（如 37.62 表示 37.62%）"),
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
