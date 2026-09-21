# -*- coding: utf-8 -*-
"""网站预测模块的 V1 口径与接口守卫。"""

import hashlib
import pathlib

import numpy as np
import pandas as pd
import pytest

from esi_v1 import config_v1
from esi_v1.data import load_standard_input, subject_task_data, validate_known_v1_inputs
from esi_v1.service import next_periods, run_prediction
from server import forecasting


pytestmark = [
    pytest.mark.filterwarnings("ignore:Glyph .* missing from font"),
    pytest.mark.filterwarnings("ignore:Maximum Likelihood optimization failed"),
]


def _periods(start_year=2019, start_month=1, count=36):
    result = []
    year, month = start_year, start_month
    for _ in range(count):
        result.append(int(f"{year:04d}{month:02d}"))
        month += 2
        if month > 12:
            year += 1
            month -= 12
    return result


def _write_period(period_dir, count=34, missing_rank=2):
    periods = _periods(count=count)
    columns = [str(period) for period in periods]
    wide = period_dir / "wide"
    wide.mkdir(parents=True)
    index = pd.Index(["Physics"], name="discipline")
    pd.DataFrame([np.arange(100, 100 + count)], index=index, columns=columns).to_parquet(
        wide / "total_cites.parquet")
    pd.DataFrame([np.arange(150, 150 + count)], index=index, columns=columns).to_parquet(
        wide / "threshold_1pct.parquet")
    pd.DataFrame([[.8] * count], index=index, columns=columns).to_parquet(
        wide / "proximity_1pct.parquet")
    ledger_rows = []
    for idx, period in enumerate(periods):
        ledger_rows.extend([
            {"source": "rank_cn", "metric": "rank", "discipline": "Physics",
             "period": period, "value": np.nan if idx < missing_rank else 60 - idx},
            {"source": "rank_cn", "metric": "n_inst_1pct", "discipline": "Physics",
             "period": period, "value": np.nan if idx < missing_rank else 30 + idx},
        ])
    pd.DataFrame(ledger_rows).to_parquet(period_dir / "ledger_long.parquet")
    return periods


def test_v1固定参数与五模型名单():
    assert config_v1.MODEL_PACKAGE_VERSION == "V1.0"
    assert config_v1.SEASONAL_PERIODS == 6
    assert config_v1.INITIAL_TRAIN_SIZE == 30
    assert config_v1.FIT_MAPE_START_INDEX == 6
    assert len(config_v1.MODEL_NAMES) == 5
    assert len(config_v1.SARIMA_ORDERS) * len(config_v1.SARIMA_SEASONAL_ORDERS) == 12


def test_v1核心与已验收交接包校验和一致():
    """校验和按 **LF 字节** 计算。

    🔴 Windows 检出（core.autocrlf=true）会把文件变成 CRLF，直接哈希必然与期望值
    不符 —— 2026-09-22 本地实测（CI/Ubuntu 检出是 LF，反而是对的）。所以先归一到 LF。
    """
    def _lf(b: bytes) -> bytes:
        return b.replace(b"\r\n", b"\n")

    root = pathlib.Path(config_v1.__file__).resolve().parent
    config_bytes = _lf((root / "config_v1.py").read_bytes())
    core_bytes = _lf((root / "model_core_v1.py").read_bytes()).replace(
        b"from .config_v1 import", b"from config_v1 import")
    assert hashlib.sha256(config_bytes).hexdigest() == (
        "229750169cd45f471c20b15c2e11b008e846263ac96e5fe934bed28850360e96")
    assert hashlib.sha256(core_bytes).hexdigest() == (
        "a23e282928712c7b54ed7901852a526e097f8f1954db6053580ed1533564da55")


def test_v1输入窗口必须四列同期齐备(tmp_path):
    periods = _write_period(tmp_path)

    common, _meta = load_standard_input(tmp_path)
    cite_periods, _ = subject_task_data(common, "物理学", "citation")
    rank_periods, _ = subject_task_data(common, "物理学", "rank")
    assert cite_periods == rank_periods == periods[2:]


def test经济与商业已确认修正不能静默回退():
    total = pd.DataFrame({"202003": [31.0]}, index=["Economics & Business"])
    validate_known_v1_inputs(total, ["Economics & Business"])
    total.at["Economics & Business", "202003"] = 310.0
    with pytest.raises(ValueError, match="应为31"):
        validate_known_v1_inputs(total, ["Economics & Business"])


def test网站编排能从最新派生产物返回图表(tmp_path, monkeypatch):
    period_dir = tmp_path / "202607"
    _write_period(period_dir, count=33, missing_rank=2)
    monkeypatch.setattr(forecasting.config, "OUT_DIR", tmp_path)
    meta = forecasting.page_context()
    assert meta["available"] is True
    assert meta["subjects"] == ["物理学"]
    result = forecasting.run({
        "subject": "物理学", "task": "citation",
        "model": "Holt趋势模型", "horizon": 2,
    })
    assert result["source_period"] == "202607"
    assert result["results"][0]["chart"].startswith("data:image/png;base64,")


def test_holt网页预测产出有限值且跨年期次正确():
    periods = _periods(count=36)
    t = np.arange(36, dtype=float)
    result = run_prediction(
        "物理学",
        periods,
        {
            "总被引": 100 + 2.1 * t + 2 * np.sin(t * np.pi / 3),
            "ESI前1%被引阈值": 150 + 1.3 * t + np.sin(t * np.pi / 3),
        },
        "citation",
        "Holt趋势模型",
        4,
    )
    item = result["results"][0]
    assert result["model_version"] == "V1.0"
    assert len(item["forecast"]) == 4
    assert np.isfinite([row["metric1"] for row in item["forecast"]]).all()
    assert np.isfinite(item["rolling_mape"])
    assert next_periods(202611, 3) == [202701, 202703, 202705]


def test排名路线按机构数除以排名计算接近度():
    periods = _periods(count=31)
    t = np.arange(31, dtype=float)
    result = run_prediction(
        "物理学",
        periods,
        {
            "云大国内排名": 70 - .8 * t,
            "国内ESI前1%机构数": 25 + .7 * t,
        },
        "rank",
        "Holt趋势模型",
        2,
    )
    for row in result["results"][0]["forecast"]:
        assert np.isclose(row["proximity"], row["metric2"] / row["metric1"] * 100)
        assert row["crossed"] is (row["metric1"] <= row["metric2"])


def test推荐模型固定而全模型比较不改写推荐():
    periods = _periods(count=31)
    t = np.arange(31, dtype=float)
    result = run_prediction(
        "多学科",
        periods,
        {
            "总被引": 100 + 2 * t,
            "ESI前1%被引阈值": 180 + t,
        },
        "citation",
        "recommended",
        1,
    )
    assert result["recommended_model"] == "Holt趋势模型"
    assert result["compared_all"] is False
    assert [item["model"] for item in result["results"]] == ["Holt趋势模型"]


def test五模型入口全部可运行():
    periods = _periods(count=31)
    t = np.arange(31, dtype=float)
    result = run_prediction(
        "物理学",
        periods,
        {
            "总被引": 100 + 2.1 * t + 2 * np.sin(t * np.pi / 3),
            "ESI前1%被引阈值": 155 + 1.2 * t + np.sin(t * np.pi / 3),
        },
        "citation",
        "all",
        1,
    )
    assert result["compared_all"] is True
    assert result["errors"] == []
    assert [item["model"] for item in result["results"]] == config_v1.MODEL_NAMES
    assert all(np.isfinite(item["rolling_mape"]) for item in result["results"])
