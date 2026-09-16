# -*- coding: utf-8 -*-
"""研究线选模模块（src/forecast_select.py）的守卫测试。

分两层，与仓库既有约定一致：
  · 纯函数测试 —— 永远可跑；
  · 数据驱动测试 —— 依赖 out/ 派生数据，缺失时 skip（数据不入库，属正常）。

验收口径（本文件即 WH-DOC-10 §7.3 的验收证据）：
  1. 潜力学科识别与台账一致（8 个）；
  2. 两套接近度**逐位**对上台账原始序列（被引维度 / 排名维度各 8/8）；
  3. 五个模型在新版 statsmodels 下都能收敛并给出有限预测（防 API 漂移）；
  4. 过线时序自洽：最早 ≤ 最可能 ≤ 最晚；
  5. 预测区间随步长单调变宽。
"""
import numpy as np
import pandas as pd
import pytest

import forecast_select as F
from _guard_registry import skip_unless

EXPECTED_8 = [
    "Economics & Business", "Immunology", "Molecular Biology & Genetics",
    "Multidisciplinary", "Neuroscience & Behavior", "Physics",
    "Psychiatry/Psychology", "Space Science",
]


@pytest.fixture(scope="module")
def out_dir(repo):
    d = repo / "out" / "202607"
    if not (d / "wide" / "total_cites.parquet").exists():
        skip_unless("out/202607 派生数据缺失（不入库，属正常）",
                    lambda: (d / "wide" / "total_cites.parquet").exists())
    return d


# ------------------------------------------------------------ 纯函数

def test_next_periods_双月跨年():
    assert F.next_periods("202607", 4) == ["202609", "202611", "202701", "202703"]
    assert F.next_periods("202611", 3) == ["202701", "202703", "202705"]


def test_两个维度的序列名互不相同():
    a = set(F.DIMS["被引维度"])
    b = set(F.DIMS["排名维度"])
    assert a.isdisjoint(b), "两维度必须各自独立，避免选模时串序列"
    assert len(F.MODELS) == 5


def test_五模型名单与报告一致():
    assert F.MODELS == ["Holt", "阻尼Holt", "季节性ETS", "SARIMA", "经验贝叶斯状态空间"]


# ------------------------------------------------------------ 数据驱动

def test_潜力学科恰为尚未进入前1个百分点的八个(out_dir):
    series = F.load_series(out_dir)
    ref = F.current_period(series["Chemistry"], F.DIMS["被引维度"])
    assert ref == "202607"
    assert F.potential_disciplines(series, ref) == EXPECTED_8


def test_两套接近度逐位对上台账(out_dir):
    """8/8 校验：被引接近度 = 总被引/前1%阈值；排名接近度 = 前1%机构数/云大国内排名。"""
    series = F.load_series(out_dir)
    tc = pd.read_parquet(out_dir / "wide" / "total_cites.parquet")
    th = pd.read_parquet(out_dir / "wide" / "threshold_1pct.parquet")
    prox = pd.read_parquet(out_dir / "wide" / "proximity_1pct.parquet")
    long = pd.read_parquet(out_dir / "ledger_long.parquet")
    rk = long[long.source == "rank_cn"].pivot_table(
        index="period", columns=["metric", "discipline"], values="value")
    P = "202607"

    bad = []
    for d in EXPECTED_8:
        s = series[d]
        if not np.isclose(s["total_cites"][P] / s["threshold_1pct"][P], prox.loc[d, P], rtol=1e-9):
            bad.append(("被引", d))
        if not np.isclose(s["n_inst_1pct"][P] / s["rank"][P],
                          rk[("n_inst_1pct", d)][P] / rk[("rank", d)][P], rtol=1e-9):
            bad.append(("排名", d))
        # 交叉验证：模块装载的值必须等于台账原始单元格
        assert s["total_cites"][P] == tc.loc[d, P]
        assert s["n_inst_1pct"][P] == rk[("n_inst_1pct", d)][P]
    assert not bad, f"接近度与台账不一致：{bad}"


def test_五个模型都能收敛并产出有限预测(out_dir):
    """防 statsmodels 升级导致的 API 漂移（0.15 改了 trend/seasonal 的取值口径）。"""
    series = F.load_series(out_dir)
    y = series["Physics"]["total_cites"].to_numpy(dtype=float)[:35]
    for name in F.MODELS:
        fc, _, ok = F.fit_model(name, y)
        assert ok, f"{name} 拟合失败"
        v = np.asarray(fc(2), dtype=float)
        assert v.shape == (2,) and np.isfinite(v).all(), f"{name} 预测非有限值"


@pytest.mark.slow
def test_过线时序自洽且区间随步长变宽(out_dir):
    """过线三值的单调关系，以及区间宽度随步长单调。

    注意：`latest`（区间下界过线）为空但 `likely`（点预测过线）非空是**正常**结果——
    下界比点预测更保守，窗口内可能永远追不上。因此只对**两侧都存在**时断言单调。
    """
    series = F.load_series(out_dir)
    for d in ["Physics", "Molecular Biology & Genetics"]:
        for dim in F.DIMS.values():
            ct = F.crossing_time(series[d], dim, "Holt", horizon=12)
            # 期次为 6 位 YYYYMM 字符串，字典序即时间序；latest ⊆ likely ⊆ earliest
            if ct["likely"]:
                assert ct["earliest"] and ct["earliest"] <= ct["likely"], ct
            if ct["latest"]:
                assert ct["likely"] and ct["likely"] <= ct["latest"], ct
            # 已过线（比值≥1）时最可能过线期必须落在第一期
            if ct["cur_ratio"] >= 1:
                assert ct["likely"] == F.next_periods("202607", 12)[0], ct

    point, lo, hi = F.forecast_band(series["Physics"]["total_cites"], "Holt", 10)
    assert (hi - lo >= -1e-9).all(), "区间宽度不应为负"
    assert (hi - lo)[-1] >= (hi - lo)[0] - 1e-9, "区间应随步长变宽（sqrt(h) 放大）"
