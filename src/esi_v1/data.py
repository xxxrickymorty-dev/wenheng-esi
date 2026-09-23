"""从文衡只读派生产物组装 V1 双路线输入。"""

from __future__ import annotations

import pathlib
import re

import pandas as pd

from parse_ledger import DISCIPLINES_CN


PERIOD_RE = re.compile(r"^\d{6}$")
DISPLAY_ALIASES = {
    "神经系统科学与行为学": "神经科学与行为科学",
}
ECONOMICS_202003_TOTAL_CITES = 31.0


def display_name(english_name: str) -> str:
    name = DISCIPLINES_CN.get(english_name, english_name)
    return DISPLAY_ALIASES.get(name, name)


def latest_ready_period(out_root: pathlib.Path) -> pathlib.Path:
    """返回最新且具备四条 V1 序列派生产物的期次目录。"""
    required = (
        "wide/total_cites.parquet",
        "wide/threshold_1pct.parquet",
        "wide/proximity_1pct.parquet",
        "ledger_long.parquet",
    )
    candidates = []
    if out_root.exists():
        for path in out_root.iterdir():
            if path.is_dir() and PERIOD_RE.fullmatch(path.name):
                if all((path / rel).is_file() for rel in required):
                    candidates.append(path)
    if not candidates:
        raise FileNotFoundError("暂无可用预测数据；请先运行一期完整流水线。")
    return sorted(candidates, key=lambda p: p.name, reverse=True)[0]


def _period_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(c) for c in frame.columns]
    return frame


def validate_known_v1_inputs(total: pd.DataFrame, subjects_en: list[str]) -> None:
    """拦住已确认的数据修正回退；只校验本次确实要预测的学科。"""
    discipline, period = "Economics & Business", "202003"
    if discipline not in subjects_en:
        return
    if discipline not in total.index or period not in total.columns:
        raise ValueError("V1输入缺少经济与商业 202003 总被引；请检查台账并重跑流水线。")
    actual = pd.to_numeric(total.at[discipline, period], errors="coerce")
    if pd.isna(actual) or abs(float(actual) - ECONOMICS_202003_TOTAL_CITES) > 1e-9:
        raise ValueError(
            f"V1输入校验失败：经济与商业 202003 总被引应为31，当前为{actual}；"
            "请修正台账并重跑流水线。预测模块没有改写数据。")


def load_standard_input(period_dir: pathlib.Path, validate: bool = True) -> tuple[pd.DataFrame, dict]:
    """生成 V1 标准长表；只保留四个指标同时齐备的公共期次。

    `validate=True`（默认）执行已确认输入修正闸门（经济与商业 2020-03）。
    历史期次快照可能早于该修正（如 out/202607 的旧值），出图/复现路径可在
    **目标学科不含该闸门学科**时显式关闭（调用方自行把关，见 report_forecast）。
    """
    wide = period_dir / "wide"
    total = _period_columns(pd.read_parquet(wide / "total_cites.parquet"))
    threshold = _period_columns(pd.read_parquet(wide / "threshold_1pct.parquet"))
    proximity = _period_columns(pd.read_parquet(wide / "proximity_1pct.parquet"))

    ledger = pd.read_parquet(period_dir / "ledger_long.parquet")
    rank_rows = ledger[ledger["source"] == "rank_cn"].copy()
    rank_rows["period"] = rank_rows["period"].astype(str)
    rank = rank_rows[rank_rows["metric"] == "rank"].pivot_table(
        index="discipline", columns="period", values="value")
    institutions = rank_rows[rank_rows["metric"] == "n_inst_1pct"].pivot_table(
        index="discipline", columns="period", values="value")
    rank, institutions = _period_columns(rank), _period_columns(institutions)

    periods = sorted(c for c in total.columns if PERIOD_RE.fullmatch(c))
    if not periods:
        raise ValueError("总被引派生表没有有效期次。")
    # 当期 = 最后一个**总被引非空且接近度表同期存在**的期次。
    # ⚠ 不能直接取 periods[-1]：派生宽表带完整期次骨架，老期次目录（如 out/202607）
    # 末尾会带一列全空的 `202609`，直接取末列会误判当期、并在接近度表上找不到该期。
    filled = [p for p in periods if p in proximity.columns and total[p].notna().any()]
    if not filled:
        raise ValueError("总被引派生表没有有效期次（或接近度表缺同期列）。")
    current = filled[-1]

    current_proximity = pd.to_numeric(proximity[current], errors="coerce")
    subjects_en = sorted(current_proximity[(current_proximity < 1) & current_proximity.notna()].index)
    if validate:
        validate_known_v1_inputs(total, subjects_en)
    frames = {
        "总被引": total,
        "ESI前1%被引阈值": threshold,
        "云大国内排名": rank,
        "国内ESI前1%机构数": institutions,
    }

    rows = []
    subject_keys = {}
    for english in subjects_en:
        chinese = display_name(english)
        subject_keys[chinese] = english
        all_periods = set()
        for frame in frames.values():
            if english in frame.index:
                all_periods.update(c for c in frame.columns if PERIOD_RE.fullmatch(c))
        for period in sorted(all_periods):
            row = {"学科": chinese, "期次": int(period)}
            for column, frame in frames.items():
                value = frame.at[english, period] if english in frame.index and period in frame.columns else None
                row[column] = pd.to_numeric(value, errors="coerce")
            # 正式 V1 输入由四列齐备的公共窗口组成。被引路线也必须沿用
            # 这组期次，才能复现 2026-07 基线的 MAPE 与推荐模型。
            if all(pd.notna(row[column]) for column in frames):
                rows.append(row)

    data = pd.DataFrame(rows)
    meta = {
        "period_dir": period_dir,
        "current_period": current,
        "subjects": sorted(subject_keys),
        "subject_keys": subject_keys,
    }
    return data, meta


def subject_task_data(data: pd.DataFrame, subject: str, task: str) -> tuple[list[int], dict]:
    if task == "citation":
        columns = ["总被引", "ESI前1%被引阈值"]
    elif task == "rank":
        columns = ["云大国内排名", "国内ESI前1%机构数"]
    else:
        raise ValueError("路线只能是 citation 或 rank。")
    found = data[data["学科"] == subject][["期次", *columns]].copy()
    for column in columns:
        found[column] = pd.to_numeric(found[column], errors="coerce")
    found = found.dropna(subset=columns).drop_duplicates("期次", keep="last").sort_values("期次")
    periods = found["期次"].astype(int).tolist()
    return periods, {column: found[column].to_numpy(dtype=float) for column in columns}
