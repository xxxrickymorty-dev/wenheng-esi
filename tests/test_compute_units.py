# -*- coding: utf-8 -*-
"""compute.py 的口径与格式化：纯函数测试，零外部依赖。

这些函数是所有报告数字的**最后一道出口**——大表里「139/↓4」「↑33.87%」
这类字符串就是它们拼出来的。口径一旦漂移，报告会静默出错，
所以这里把当前行为焊死。
"""
import pandas as pd
import pytest

import compute
import parse_ledger


class TestBuildEntered1pct:
    """事件表 → 0/1 矩阵的回放规则。

    「学科进入时间」是手填流水账，一个学科可以**多次进出**（微生物学进出 4 次、
    数学 202505 退出 / 202603 再进入）。回放规则错了不会报错，只会让某期多算或少算一个学科。
    """
    D = ["Chemistry", "Mathematics"]

    @staticmethod
    def _run(events, periods=("202501", "202503", "202505", "202507", "202509")):
        return parse_ledger.build_entered_1pct(events, list(periods), TestBuildEntered1pct.D)

    def test_退出后重新进入_必须被回放出来(self):
        """🔴 若实现成「先全部 in 再全部 out」，202507 之后的 Chemistry 会被 202505 的退出误删。"""
        df = self._run([("202501", "Chemistry", "in"),
                        ("202505", "Chemistry", "out"),
                        ("202507", "Chemistry", "in")])
        assert df.loc["Chemistry", "202503"] == 1.0   # 退出前
        assert df.loc["Chemistry", "202505"] == 0.0   # 已退出
        assert df.loc["Chemistry", "202507"] == 1.0   # 重新进入
        assert df.loc["Chemistry", "202509"] == 1.0   # 仍在

    def test_同一期次既有进又有出时_out_优先(self):
        df = self._run([("202505", "Chemistry", "in"),
                        ("202505", "Chemistry", "out")])
        assert df.loc["Chemistry", "202505"] == 0.0

    def test_早于首个期次的事件仍然生效(self):
        """台账最早一期是 201903，而化学 201211 就进入了 —— 不能因为不在列里就丢掉。"""
        df = self._run([("201211", "Chemistry", "in")])
        assert df.loc["Chemistry", "202501"] == 1.0

    def test_从没进入过的学科恒为零(self):
        df = self._run([("202501", "Chemistry", "in")])
        assert df.loc["Mathematics"].sum() == 0.0

    def test_认不出的学科名不进矩阵(self):
        """事件表里若出现拼错/变体名，宁可不进，也不能挂到别的学科上。"""
        df = self._run([("202501", "化 learned", "in")])
        assert df.sum().sum() == 0.0


class TestCn2En学科名归一:
    """中文学科名 → 规范英文名。

    🔴 这里是「生物与生物化学」被「化学」子串截胡的事故现场：
    台账规范名是「**生物学**与生物化学」，事件表手写少一个「学」，
    精确匹配落空后若按任意顺序做包含匹配，就会命中「化学」。
    """

    def test_规范名精确命中(self):
        assert parse_ledger._cn2en("化学") == "Chemistry"
        assert parse_ledger._cn2en("生物学与生物化学") == "Biology & Biochemistry"

    def test_手写变体不会被子串截胡(self):
        assert parse_ledger._cn2en("生物与生物化学") == "Biology & Biochemistry"
        assert parse_ledger._cn2en("微生物") == "Microbiology"

    def test_认不出时原样返回_不臆测(self):
        assert parse_ledger._cn2en("化") == "化"


class TestNDisc1pct取事件表而非接近度:
    """`n_disc_1pct` 必须取 `entered_1pct`，不是 `proximity_1pct`。

    两者在阈值附近会打架（第 1 期 202601：事件表 13、接近度 14，原件是 13）。
    这里故意造一个冲突的最小数据集，把取值来源焊死。
    """

    IDX = ["Chemistry", "Mathematics"]

    @staticmethod
    def _wide(entered_now, periods=("202511", "202601")):
        """造一个 `entered_1pct` 与 `proximity_1pct` 互相冲突的最小 wide。"""
        prev, period = periods
        z = lambda v: pd.DataFrame(v, index=TestNDisc1pct取事件表而非接近度.IDX, columns=list(periods))
        return {
            "total_cites": z(100.0),
            "papers": z(10.0),
            "cnci": z(1.0),
            "top_papers": z(1.0),
            "threshold_1pct": z(90.0),
            # 事件表口径：只有 entered_now 指定的那些算「已进入」
            "entered_1pct": pd.DataFrame({prev: [1.0, 0.0], period: entered_now},
                                        index=TestNDisc1pct取事件表而非接近度.IDX),
            # 接近度口径：两科都 >= 1（故意与事件表冲突）
            "proximity_1pct": z(1.5),
        }

    @classmethod
    def _facts(cls, entered_now, periods=("202511", "202601"), drop_entered=False):
        prev, period = periods
        wide = cls._wide(entered_now, periods)
        if drop_entered:
            del wide["entered_1pct"]
        # new_intl / new_cn 是 (metric, period) 双层列，build_overview 要用 ("rank", period/prev)
        mcols = pd.MultiIndex.from_product([["n_inst_1pct", "rank", "rank_pct"], list(periods)])
        nc = pd.DataFrame(1.0, index=cls.IDX, columns=mcols)
        thr = pd.DataFrame(50.0, index=cls.IDX, columns=list(periods))
        ynd = pd.DataFrame({"rank_intl": [100, 100], "rank_cn": [10, 10], "rank_cn_uni": [9, 9]},
                           index=list(periods))
        return compute.build_overview(wide, nc.copy(), nc, thr, ynd,
                                      {period: 10.0, prev: 8.0}, period, prev)

    def test_取事件表口径_忽略接近度(self):
        """事件表说只有 Chemistry 进了（1 个），接近度口径会给出 2 个。"""
        assert self._facts([1.0, 0.0])["n_disc_1pct"] == 1

    def test_两学科都进入则为2(self):
        assert self._facts([1.0, 1.0], periods=("202601", "202603"))["n_disc_1pct"] == 2

    def test_缺表时兜底接近度_不炸(self):
        """手工构造的测试 dict 可能不带这张表；生产路径由 load_wide 保证存在（缺失即报错）。"""
        assert self._facts([1.0, 0.0], drop_entered=True)["n_disc_1pct"] == 2  # 退回接近度口径


class TestFmtRankChange:
    """国内排名变化：<排名>/<上下箭头><幅度>。"""

    def test_排名上升(self):
        assert compute.fmt_rank_change(135, 139) == "135/↑4"

    def test_排名下降(self):
        assert compute.fmt_rank_change(139, 135) == "139/↓4"

    def test_排名持平用减号(self):
        assert compute.fmt_rank_change(139, 139) == "139/-"

    def test_接受浮点排名(self):
        assert compute.fmt_rank_change(135.0, 139.0) == "135/↑4"


class TestFmtPctChange:
    """接近度变化：箭头 + 两位小数百分比。"""

    def test_正值(self):
        assert compute.fmt_pct_change(33.87) == "↑33.87%"

    def test_负值取绝对值(self):
        assert compute.fmt_pct_change(-1.2) == "↓1.20%"

    def test_零值(self):
        # 注意：零值与 Down 分支共用「-」前缀，得到 "-0.00%"。
        # 实际数据里接近度变化恰为 0 极罕见，故先锁定现状；
        # 若日后要改成 "0.00%"，改这里即可，避免口径无声漂移。
        assert compute.fmt_pct_change(0) == "-0.00%"


class TestDetectPeriods:
    """当期/上期自动检测：以总被引表最后一个有数据的期次为准。"""

    @staticmethod
    def _wide(cols):
        # 只造 total_cites 一列有意义，其余 load_wide 的键用同形空表补齐
        tc = pd.DataFrame({c: [1.0, 2.0] for c in cols}, index=["a", "b"])
        return {"total_cites": tc}

    def test_取最后两个有数据期次(self):
        wide = self._wide(["202601", "202603", "202605"])
        assert compute.detect_periods(wide) == ("202605", "202603")

    def test_忽略全空列(self):
        """尾部整列空白（馆员先插了表头还没贴数）不应被当成当期。"""
        wide = self._wide(["202601", "202603"])
        wide["total_cites"]["202605"] = [None, None]
        assert compute.detect_periods(wide) == ("202603", "202601")

    def test_有效期次不足两期时报错(self):
        wide = self._wide(["202601"])
        with pytest.raises(ValueError, match="不足 2 期"):
            compute.detect_periods(wide)
