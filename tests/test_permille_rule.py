# -*- coding: utf-8 -*-
"""1‰（千分之一）被引阈值口径：最容易漂、代价最大的一环。

口径（2026-09-15 反推确立）：
    ESI 学科机构榜只收录**全球前 1%** 机构，按 Cites 降序。
      1%  阈值 = 榜单**末位** Cites
      1‰  阈值 = 榜单第 **⌊(m+1)/10⌋** 位 Cites（榜单前 10% = 全局前 0.1%）
      m = 有效数据行数；`+1` 是因为馆员的百分比区间**含表头行**

这个 `+1` 曾让 Materials / Microbiology 两学科各偏 1 位，
改成 ⌊(m+1)/10⌋ 后才 23/23 全中。所以这里必须焊死。

数据来自 `../数据与复现/ESI数据/<期次>/`（仓库外，2026-09-18 去冗余 + 命名归一后
固定在这个位置；此前依次是 `../数据与复现/202601-03ESI数据/<期次>/`、
`../数据与复现/<期次>/`），缺失时整组自动 skip。
⚠ 路径常量过期时**不报错、只静默跳过**——整整一组守卫会无声消失，
所以 `test_数据根目录存在且含期次子目录` 专门盯着这件事。
"""
import pathlib

import pytest

import extract_1permille
from _guard_registry import skip_unless


@pytest.fixture(scope="session")
def esi_root():
    r = extract_1permille.DEFAULT_DATA_ROOT
    if not r.is_dir():
        skip_unless(f"ESI 原始包不在：{r}",
                    lambda: extract_1permille.DEFAULT_DATA_ROOT.is_dir())
    return r


@pytest.fixture(scope="session")
def esi_periods(esi_root):
    ps = sorted(p.name for p in esi_root.iterdir() if p.is_dir() and p.name.isdigit())
    if not ps:
        skip_unless(f"{esi_root} 下无期次目录",
                    lambda: any(p.is_dir() for p in esi_root.iterdir()))
    return ps


@pytest.fixture(scope="session")
def ledger():
    for p in extract_1permille.DEFAULT_LEDGERS:
        if p.exists():
            return p
    skip_unless("台账不在仓库内",
                lambda: any(p.exists() for p in extract_1permille.DEFAULT_LEDGERS))


@pytest.fixture(scope="session")
def extracted(esi_root, esi_periods):
    """{期次: extract_period 结果}——**只抽一次**，本文件 5 个用例共用。

    45 期 × 22 科 × 每科一个 Excel，抽一遍 ~50s；不缓存则 5 个用例各抽一遍
    （实测 3.5 min），纯属重复劳动。
    """
    return {p: extract_1permille.extract_period(esi_root, p) for p in esi_periods}


def test_数据根常量指向真正含期次的那一层():
    """**守卫静默失效**的元凶就是"常量指向了一层旧目录"——不报错，整组 skip。

    这里不猜目录名：先问工作区里哪一层直接含期次子目录，再要求常量指那一层。
    2026-09-16 实例：原始包由 `数据与复现/202601-03ESI数据/<期次>/` 改为
    `数据与复现/<期次>/`，常量没跟着改，本文件 4 例守卫无声消失。
    2026-09-18 实例：去冗余后再挪到 `数据与复现/ESI数据/<期次>/`，同一类风险第二次出现。
    """
    ws = pathlib.Path(__file__).resolve().parents[2]

    def _period_layers():
        return {p.parent for p in (ws / "数据与复现").rglob("[0-9]" * 6) if p.is_dir()}

    layers = _period_layers()
    if not layers:
        skip_unless("工作区里没有 ESI 期次目录（原始包不入库，属正常）",
                    lambda: bool(_period_layers()))
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


#: **2026-09-18 更新 —— 原来的白名单已过期，别再照旧写。**
#: 原先认为「2019 年那 4 期是老格式包、原理上算不出」。给 `resolve_file` 补上
#: 中文文件名别名表 + 递归索引（`201909/ESI/<学科>.xlsx` 这种嵌一层的）+ 前缀
#: 截断匹配之后，**201905 / 201907 / 201909 已能 22/22 全抽**（它们的机构榜叫
#: `全球机构-<中文>.xlsx` / `全球<学科>入选情况.xlsx` 这类）。
#: 只剩 **201903** 是**原始包本身残缺**：它只有 8 份「全球<学科>入选情况.xlsx」，
#: 且其中数学那份是**美国机构子集**（不是全球榜）→ 实得 7 科，其余 14 科该期
#: 根本没下文件。这是数据缺陷，不是解析缺陷。
OLD_FORMAT_PERIODS = set()            # 目前没有「一期都算不出」的包
PARTIAL_PERIODS = {"201903"}          # 原始包残缺：允许 <22，但不得再往下掉
PARTIAL_FLOOR = {"201903": 7}         # 该期可用学科下限（低于它=解析回归）

#: **有「整体机构榜」且该文件确为榜单结构**的期次（2026-09-18 全量清点得出）。
#: 其余期次分两类，都不能要求 `__OVERALL__`：
#:   · 该期根本没下这份文件 —— 201903/201905/201907/201909/201911/202003/202005/
#:     202007/202009/202011/202101/202105/202107/202109/202111/202203/202211/
#:     202301/202305/202307/202311/202401/202507（共 23 期）
#:   · 下了但**不是榜单**（汇总表，`parse_ranking` 读到 0 行）——
#:     202103 `global institute.xlsx`、202309 `institute.xlsx`
#: `__OVERALL__` 台账不存、不进报告，**仅供人工参考**，所以这里只做「曾经能定位、
#: 现在丢了就是回归」的正向守卫，不把它当成每期必备的契约。
OVERALL_PERIODS = {
    "202001", "202201", "202205", "202207", "202209", "202303", "202403",
    "202405", "202407", "202409", "202411", "202501", "202503", "202505",
    "202509", "202511", "202601", "202603", "202605", "202607",
}


def test_每期抽取覆盖全部22学科(extracted):
    """除 2019 残缺包外，**每一期都必须 22/22 齐且无解析错误**。

    历史上文件名不干净（大写 `CHEMISTRY.xlsx`、截断 `COMPUTER SCIENC.xlsx`、
    拼错 `PSYCHIATRY SYCHOLOGY.xlsx`、首行缺序号），都由 `resolve_file` /
    `parse_ranking` 兜住了；兜不住时这个用例必须红，不要靠放宽断言蒙过去。
    """
    bad, surprises = [], []
    for period, res in extracted.items():
        errs = {d: i["error"] for d, i in res.items() if "error" in i}
        # 注意：解析失败时学科名**仍会作为键存在**（值为 {'error': …}），
        # 所以「算出来了几个」必须排除带 error 的键，不能只数 len(res)。
        ok_discs = [d for d, i in res.items() if d != "__OVERALL__" and "error" not in i]
        if period in OLD_FORMAT_PERIODS:
            if ok_discs or "__OVERALL__" in res:
                surprises.append(f"{period} 已能算出 {len(ok_discs)} 科 —— "
                                 f"请把它从 OLD_FORMAT_PERIODS 里移出")
            continue
        if period in PARTIAL_PERIODS:
            floor = PARTIAL_FLOOR[period]
            if len(ok_discs) < floor:
                bad.append(f"{period}（残缺包）只算出 {len(ok_discs)} 科 < 下限 {floor}"
                           f"；错误 {sorted(errs)} —— 疑似解析回归")
            continue
        if errs or len(ok_discs) != 22:
            bad.append(f"{period}: {len(ok_discs)} 科；缺 {sorted(errs)}")
    assert not surprises, "老格式包白名单过期：\n" + "\n".join(surprises)
    assert not bad, "抽取有缺口：\n" + "\n".join(bad)


def test_整体机构榜曾能定位的期次不许丢(extracted):
    """`resolve_overall` 接住了 8 种文件写法；这里钉住它别退化。

    见 `OVERALL_PERIODS` 上方的清点说明——23 期没下这份文件、2 期下的是汇总表，
    都属数据侧正常，不算失败。
    """
    lost = sorted(p for p in OVERALL_PERIODS if "__OVERALL__" not in extracted[p])
    assert not lost, f"这些期的整体榜曾能定位、现在丢了（解析/定位回归）：{lost}"


def test_千分位名次落在榜单内且阈值单调(extracted):
    """榜单按 Cites 降序：位次越靠前、被引门槛越高。

      1% 阈值 = 末位（门槛最低）
      1‰ 阈值 = 第 ⌊(m+1)/10⌋ 位（更靠前 → 门槛更高）

    所以恒有 t1pct ≤ t1pm。方向写反是最容易犯的错，这里用不等式钉住。
    """
    for period, res in extracted.items():
        for disc, info in res.items():
            if "error" in info:
                continue
            assert 1 <= info["rank_1pm"] <= info["m"], f"{period}/{disc}: rank 越界"
            assert 0 < info["t1pct"] <= info["t1pm"], \
                f"{period}/{disc}: 1%({info['t1pct']}) 应 ≤ 1‰({info['t1pm']})"


def test_抽取结果与台账已写入列逐格一致(ledger, esi_periods, extracted):
    """台账《千分之一被引阈值》里**已有值的期次**（2026-09-18 前是馆员成品
    202601/202603/202605/202607 四列；回填后扩到 41 列）由本脚本写入，
    重算一遍必须逐格吻合——这就是当初 23/23 命中的复现。"""
    periods, table = extract_1permille.read_sheet_table(ledger)
    checked, bad = 0, []
    for period in esi_periods:
        if period not in periods:
            continue
        res = extracted[period]
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


def test_1pct阈值与ThresholdESI交叉校验(esi_root, esi_periods, extracted):
    """1% 阈值应恒等于 ThresholdESI.xlsx 的 INSTITUTION 列。
    这是独立于 1‰ 的第二来源，用来证明榜单末位口径本身没错。"""
    for period in esi_periods:
        xc = extract_1permille.crosscheck_t1pct(esi_root, period, extracted[period])
        if xc is None:
            continue                      # 该期没下 ThresholdESI.xlsx
        hit, miss, detail = xc
        assert hit > 0, f"{period} 交叉校验一个学科都没匹配上（学科名映射可能失效）"
        assert miss == 0, f"{period} 1% 阈值与 ThresholdESI 不符：{detail}"
