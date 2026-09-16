# -*- coding: utf-8 -*-
"""1‰（千分之一）被引阈值口径：最容易漂、代价最大的一环。

口径（2026-09-15 反推确立）：
    ESI 学科机构榜只收录**全球前 1%** 机构，按 Cites 降序。
      1%  阈值 = 榜单**末位** Cites
      1‰  阈值 = 榜单第 **⌊(m+1)/10⌋** 位 Cites（榜单前 10% = 全局前 0.1%）
      m = 有效数据行数；`+1` 是因为馆员的百分比区间**含表头行**

这个 `+1` 曾让 Materials / Microbiology 两学科各偏 1 位，
改成 ⌊(m+1)/10⌋ 后才 23/23 全中。所以这里必须焊死。

数据来自 `../数据与复现/<期次>/`（仓库外，2026-09-16 起每期一个目录；
此前是 `../数据与复现/202601-03ESI数据/<期次>/`），缺失时整组自动 skip。
⚠ 路径常量过期时**不报错、只静默跳过**——整整一组守卫会无声消失，
所以 `test_数据根目录存在且含期次子目录` 专门盯着这件事。
"""
import pathlib

import pytest

import extract_1permille


@pytest.fixture(scope="session")
def esi_root():
    r = extract_1permille.DEFAULT_DATA_ROOT
    if not r.is_dir():
        pytest.skip(f"ESI 原始包不在：{r}")
    return r


@pytest.fixture(scope="session")
def esi_periods(esi_root):
    ps = sorted(p.name for p in esi_root.iterdir() if p.is_dir() and p.name.isdigit())
    if not ps:
        pytest.skip(f"{esi_root} 下无期次目录")
    return ps


@pytest.fixture(scope="session")
def ledger():
    for p in extract_1permille.DEFAULT_LEDGERS:
        if p.exists():
            return p
    pytest.skip("台账不在仓库内")


def test_数据根常量指向真正含期次的那一层():
    """**守卫静默失效**的元凶就是"常量指向了一层旧目录"——不报错，整组 skip。

    这里不猜目录名：先问工作区里哪一层直接含期次子目录，再要求常量指那一层。
    2026-09-16 实例：原始包由 `数据与复现/202601-03ESI数据/<期次>/` 改为
    `数据与复现/<期次>/`，常量没跟着改，本文件 4 例守卫无声消失。
    """
    ws = pathlib.Path(__file__).resolve().parents[2]
    period_dirs = [p for p in (ws / "数据与复现").rglob("[0-9]" * 6) if p.is_dir()]
    if not period_dirs:
        pytest.skip("工作区里没有 ESI 期次目录（原始包不入库，属正常）")
    layers = {p.parent for p in period_dirs}
    assert extract_1permille.DEFAULT_DATA_ROOT in layers, (
        f"期次目录所在层是 {sorted(str(p) for p in layers)}，"
        f"而 DEFAULT_DATA_ROOT = {extract_1permille.DEFAULT_DATA_ROOT} —— "
        f"过期常量会让整套 1‰ 取位守卫静默 skip")


class TestNum:
    """ESI 导出的单元格是**文本**（'111691' 而非 111691）——这是初版脚本
    「解析成功但一条都没抓到」的真正原因，必须能自行转数。"""

    def test_纯数字串(self):
        assert extract_1permille._num("111691") == 111691.0

    def test_带千分位逗号(self):
        assert extract_1permille._num("1,234,567") == 1234567.0

    def test_两侧空白(self):
        assert extract_1permille._num("  42  ") == 42.0

    def test_原生数值原样通过(self):
        assert extract_1permille._num(42) == 42.0
        assert extract_1permille._num(42.5) == 42.5

    def test_非数值一律None(self):
        for bad in (None, "", "n/a", "-", "合计"):
            assert extract_1permille._num(bad) is None


def test_每期抽取覆盖全部22学科(esi_root, esi_periods):
    for period in esi_periods:
        res = extract_1permille.extract_period(esi_root, period)
        errs = {d: i["error"] for d, i in res.items() if "error" in i}
        assert not errs, f"{period} 抽取有缺：{errs}"
        discs = [d for d in res if d != "__OVERALL__"]
        assert len(discs) == 22, f"{period} 学科数 {len(discs)} ≠ 22"
        assert "__OVERALL__" in res, f"{period} 缺全校整体（Institutions.xlsx）"


def test_千分位名次落在榜单内且阈值单调(esi_root, esi_periods):
    """榜单按 Cites 降序：位次越靠前、被引门槛越高。

      1% 阈值 = 末位（门槛最低）
      1‰ 阈值 = 第 ⌊(m+1)/10⌋ 位（更靠前 → 门槛更高）

    所以恒有 t1pct ≤ t1pm。方向写反是最容易犯的错，这里用不等式钉住。
    """
    for period in esi_periods:
        res = extract_1permille.extract_period(esi_root, period)
        for disc, info in res.items():
            if "error" in info:
                continue
            assert 1 <= info["rank_1pm"] <= info["m"], f"{period}/{disc}: rank 越界"
            assert 0 < info["t1pct"] <= info["t1pm"], \
                f"{period}/{disc}: 1%({info['t1pct']}) 应 ≤ 1‰({info['t1pm']})"


def test_抽取结果与台账已写入列逐格一致(esi_root, ledger, esi_periods):
    """台账《千分之一被引阈值》里 202601/202603/202605 三列由本脚本写入，
    重算一遍必须逐格吻合——这就是当初 23/23 命中的复现。"""
    periods, table = extract_1permille.read_sheet_table(ledger)
    checked, bad = 0, []
    for period in esi_periods:
        if period not in periods:
            continue
        res = extract_1permille.extract_period(esi_root, period)
        for disc, info in res.items():
            if disc == "__OVERALL__" or "error" in info:
                continue
            stored = table.get(disc, {}).get(period)
            if stored in (None, ""):
                continue
            checked += 1
            if int(extract_1permille._num(stored)) != info["t1pm"]:
                bad.append(f"{period}/{disc}: 台账 {stored} ≠ 重算 {info['t1pm']}")
    assert checked > 0, "台账里没有任何可核对的已写入列"
    assert not bad, "口径漂移：\n" + "\n".join(bad)


def test_1pct阈值与ThresholdESI交叉校验(esi_root, esi_periods):
    """1% 阈值应恒等于 ThresholdESI.xlsx 的 INSTITUTION 列。
    这是独立于 1‰ 的第二来源，用来证明榜单末位口径本身没错。"""
    for period in esi_periods:
        res = extract_1permille.extract_period(esi_root, period)
        xc = extract_1permille.crosscheck_t1pct(esi_root, period, res)
        if xc is None:
            continue                      # 该期没下 ThresholdESI.xlsx
        hit, miss, detail = xc
        assert hit > 0, f"{period} 交叉校验一个学科都没匹配上（学科名映射可能失效）"
        assert miss == 0, f"{period} 1% 阈值与 ThresholdESI 不符：{detail}"
