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
  5. 预测区间随步长单调变宽；
  6. 实现口径默认钉在 **V1**（Holt 族走 `tsa.holtwinters` / SARIMA 在初始窗按 AIC 选阶 /
     状态空间超参冻结），旧 statespace 口径仍可调用，仅作对照；
  7. 「冻结」的含义可被验证：砍掉序列尾部不改变 SARIMA 阶与状态空间超参；
  8. 序列窗口默认取四列齐备的公共窗口，其长度**恒等于「云大国内排名」列的长度**；
  9. 口径指纹：物理学·被引维度·经验贝叶斯滚动 MAPE = **3.326%**（WH-DOC-12 记的 V1 实测值）；
 10. V1 口径对报告首选命中 **15/16**，且不命中的正是「多学科·被引维度」那一格。

6–10 是 2026-09-16 按 WH-DOC-12 §六 #3 补齐的；第 6 条里"旧口径仍可调用"是刻意的——
口径换过一次，旧结论要能复核回去。
"""
import importlib
import sys

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
    # 演示台账跑出的产物：金样指纹（MAPE 3.263 / 46 期 / 潜力 8 学科）
    # 只对真实台账成立，对演示数据必然失败 —— 显式 skip，理由登记守卫体检。
    from conftest import is_demo_ledger
    if is_demo_ledger():
        skip_unless("out/202607 由演示台账产出（make_demo_ledger），"
                    "指纹断言只对真实台账适用",
                    lambda: not is_demo_ledger())
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
    # 2026-10-13 重定基线后 out/202607 带全母本视野（序列止于 202609）；潜力集合在
    # 202607 与 202609 两个参考期下都稳定为 EXPECTED_8。
    assert ref == "202609"
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


# ------------------------------------------------------------ 实现口径（WH-DOC-12 §四.B.4）
#
# 背景：报告用的是「tsa.holtwinters + 初始窗 AIC 选阶 + 状态空间超参冻结」口径。
# 本模块原先是 statespace 版且每期重估，对报告首选只命中 7/16；改成 V1 口径后 15/16。
# 下面把「默认口径 = V1」和「V1 到底冻了什么」钉住，防止日后回退。

def _synthetic():
    """合成序列：够长、带趋势与季节，且不依赖仓库数据 —— 让口径测试永远可跑。"""
    rng = np.random.default_rng(20260916)
    n = 40
    y = 100 + np.arange(n) * 1.5 + 3 * np.sin(np.arange(n) * np.pi / 3) + rng.normal(0, 1, n)
    return np.abs(y)


def test_默认口径钉在V1():
    assert F.IMPL == "V1", "报告实际口径是 V1，默认必须对齐它"
    assert "statespace" in F.IMPL_CHOICES, "对照口径必须仍可调用，否则旧结论无法复核"


def test_V1口径与对照口径造出不同的模型类():
    """Holt 一族：V1 走 tsa.holtwinters，对照走 statespace —— 结果类名即可区分。"""
    y = _synthetic()
    for name in ("Holt", "阻尼Holt", "季节性ETS"):
        assert type(F._fit_v1(name, y)).__name__ == "HoltWintersResultsWrapper", name
        assert type(F._fit_statespace(name, y)).__name__ == "ExponentialSmoothingResultsWrapper", name


def test_冻结输入只取初始窗_尾部变化不影响():
    """V1 的「冻结」= SARIMA 阶与状态空间超参只由前 MIN_TRAIN 期决定，之后不再动。"""
    y = _synthetic()
    for name in ("SARIMA", "经验贝叶斯状态空间"):
        a_sar, a_ssp = F.frozen_inputs(y, name, "V1")
        b_sar, b_ssp = F.frozen_inputs(y[:-5], name, "V1")   # 砍掉尾巴，不该有任何影响
        if name == "SARIMA":
            assert a_sar is not None and a_sar == b_sar
        else:
            assert a_ssp is not None and np.allclose(a_ssp, b_ssp, rtol=1e-12)
    # Holt 族本就没有可冻结的东西
    assert F.frozen_inputs(y, "Holt", "V1") == (None, None)


def test_对照口径不做任何冻结():
    """对照口径每期重估，因此拿不到可复用的冻结输入。"""
    y = _synthetic()
    for name in ("SARIMA", "经验贝叶斯状态空间", "Holt"):
        assert F.frozen_inputs(y, name, "statespace") == (None, None)


def test_SARIMA候选池是3乘4的12组():
    assert len(F.SARIMA_ORDERS) == 3 and len(F.SARIMA_SEASONAL_ORDERS) == 4
    assert all(s[3] == F.SEASONAL_PERIODS for s in F.SARIMA_SEASONAL_ORDERS)


def test_未知口径要判失败而不是静默换口径():
    """防「传错口径名 → 悄悄用别的口径跑出一堆数」这种静默失效。"""
    _, _, ok = F.fit_model("Holt", _synthetic(), impl="不存在的口径")
    assert ok is False


def test_默认序列窗口是V1的公共窗口():
    assert F.WINDOW == "V1"
    assert "full" in F.WINDOW_CHOICES


def test_V1窗口下同一学科四列期次完全一致(out_dir):
    """公共窗口的定义：同一学科四条序列的期次集合必须相同（对齐 V1 装载口径）。"""
    common = F.load_series(out_dir, "V1")
    d = "Molecular Biology & Genetics"
    lens = {k: len(v) for k, v in common[d].items()}
    assert len(set(lens.values())) == 1, f"公共窗口下四列应等长，实际 {lens}"
    assert lens["total_cites"] == 43


def test_公共窗口长度恒等于排名序列长度(out_dir):
    """把「代价」钉住：公共窗口 = 四列期次的交集，而**卡住它的是「云大国内排名」**。

    实测 22 个学科一致（2026-10-13 重定基线后、202609 视野）：总被引/前1%阈值恒 46 期，
    前1%机构数 45 或 46 期，排名 43 或 46 期 —— 公共窗口长度**恒等于排名那一列的长度**。
    所以公共窗口把被引 46→43、机构数 45→43 都压短了（Physics 等 7 科 46 期、不被压）；排名不动。
    """
    common = F.load_series(out_dir, "V1")
    full = F.load_series(out_dir, "full")
    compressed = 0
    for d in EXPECTED_8:
        assert len(full[d]["total_cites"]) == 46, d
        assert len(full[d]["threshold_1pct"]) == 46, d
        assert len(full[d]["rank"]) in (43, 46), d
        assert len(common[d]["total_cites"]) == len(full[d]["rank"]), \
            f"{d}：公共窗口应等于排名列长度"
        assert len(common[d]["rank"]) == len(full[d]["rank"]), f"{d}：排名列不该被压"
        assert len(common[d]["n_inst_1pct"]) <= len(full[d]["n_inst_1pct"])
        if len(common[d]["total_cites"]) < len(full[d]["total_cites"]):
            compressed += 1
    assert compressed >= 6, f"应有多数学科的被引被压短，实际只 {compressed} 个"


def test_物理学被引维度_V1口径指纹(out_dir):
    """V1 实测指纹：物理学被引维度·经验贝叶斯滚动 MAPE = 3.263%。

    （2026-10-13 重定基线：out/202607 序列视野延至 202609、多一个回测点，
    WH-DOC-12 记录的 202607 视野值 3.326% 随之更新；「口径真对齐 V1」的硬证据
    仍是 test_与交接包在同一输入上逐模型一致——那条与视野无关。）
    """
    series = F.load_series(out_dir)
    ev = F.evaluate_discipline(series["Physics"], "Physics", "被引维度",
                               F.DIMS["被引维度"], "V1")
    got = float(ev.set_index("model").loc["经验贝叶斯状态空间", "rolling_mape"])
    assert abs(got - 3.263) < 0.01, f"V1 口径指纹漂了：{got:.3f}（应为 3.263）"


@pytest.mark.slow
def test_V1口径选模对报告命中15格(out_dir):
    """验收判据（WH-DOC-12 §六 #3）：V1 口径对报告首选 15/16；旧 statespace 口径只有 7/16。

    16 格 = 8 潜力学科 × 2 维度。**不只要命中数对，还要命中的是同 15 格** ——
    所以额外钉住「唯一不命中的是 多学科/被引维度」：那是 V1 自己也判 REVIEW 的漂移格。
    若这条挂了，先怀疑输入窗口/口径开关被改动，而不是"报告变了"。
    """
    series = F.load_series(out_dir)
    # 对样口径是 202607 报告：序列切片到该期为止——2026-10-13 重定基线后 out/202607
    # 带全母本视野（止于 202609），不切窗就变成「拿 09 的实测评 07 的选模」。
    series = {d: {k: v.loc[v.index <= "202607"] for k, v in s.items()}
              for d, s in series.items()}
    ref = "202607"
    discs = F.potential_disciplines(series, ref)
    rows = [F.evaluate_discipline(series[d], d, dim_name, dim, "V1")
            for d in discs for dim_name, dim in F.DIMS.items()]
    cmp_df = F.compare_with_report(pd.concat(rows, ignore_index=True))
    hit = int(cmp_df["首选一致"].sum())
    assert hit >= 15, f"V1 口径对报告首选仅命中 {hit}/{len(cmp_df)}，应为 15+"
    missed = {(r.discipline, r.dim) for _, r in cmp_df.iterrows() if not r["首选一致"]}
    assert missed == {("Multidisciplinary", "被引维度")}, \
        f"不命中的格子变了：{missed}（应为 {{('Multidisciplinary','被引维度')}}）"


@pytest.mark.slow
def test_与交接包在同一输入上逐模型一致(repo, out_dir):
    """对勘：同一 y 上，本仓 V1 口径与交接包 `model_core_v1` 的滚动 MAPE 必须逐位相同。

    这是「口径已对齐」唯一结实的证据 —— 比对照代码长相可靠得多。
    交接包在**文档仓库根目录**（`../ESI_Workflow_Model_V1_Handoff/`），不随代码仓库分发；
    拿不到就 skip（新 clone 的代码仓库里本来就没有它）。
    """
    handoff = repo.parent / "ESI_Workflow_Model_V1_Handoff"
    if not (handoff / "model_core_v1.py").exists():
        skip_unless("V1 交接包不在工作区（在文档仓库根目录，不随代码仓库分发）",
                    lambda: (handoff / "model_core_v1.py").exists())

    for p in (str(handoff), str(repo / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    V1 = importlib.import_module("model_core_v1")

    NAME_TO_V1 = {
        "Holt": "Holt趋势模型",
        "阻尼Holt": "阻尼Holt模型",
        "季节性ETS": "季节性ETS模型",
        "SARIMA": "SARIMA模型",
        "经验贝叶斯状态空间": "经验贝叶斯状态空间模型",
    }
    series = F.load_series(out_dir)
    dim = F.DIMS["被引维度"]
    bad, frozen_bad, n = [], [], 0
    for d in ("Physics", "Molecular Biology & Genetics"):
        for key in dim:
            y = series[d][key].to_numpy(dtype=float)
            periods = [int(p) for p in series[d][key].index]
            sar = V1.select_sarima_structure(y[:V1.INITIAL_TRAIN_SIZE])[:2]
            ssp = V1.calibrate_state_space_params(y[:V1.INITIAL_TRAIN_SIZE])["params"]
            for name, v1name in NAME_TO_V1.items():
                mine = F.expanding_backtest(y, name, impl="V1")
                mine_mape = float(np.mean(np.abs(mine)) * 100)
                ref_mape, _, _ = V1.rolling_backtest(
                    v1name, y, periods,
                    sar if name == "SARIMA" else None,
                    ssp if name == "经验贝叶斯状态空间" else None)
                n += 1
                if abs(mine_mape - ref_mape) > 1e-6:
                    bad.append((d, key, name, mine_mape, ref_mape))
                my_sar, my_ssp = F.frozen_inputs(y, name, "V1")
                if name == "SARIMA" and my_sar != sar:
                    frozen_bad.append((d, key, "SARIMA阶", my_sar, sar))
                if name == "经验贝叶斯状态空间" and not np.allclose(my_ssp, ssp, rtol=1e-10):
                    frozen_bad.append((d, key, "状态空间超参", None, None))

    assert not frozen_bad, f"冻结输入与交接包不一致（冻结口径没对齐）：{frozen_bad}"
    assert not bad, f"同一输入下滚动 MAPE 有差（口径未对齐）：{bad[:4]}（共 {len(bad)}/{n} 组）"

