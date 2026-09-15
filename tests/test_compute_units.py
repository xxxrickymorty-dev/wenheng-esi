# -*- coding: utf-8 -*-
"""compute.py 的口径与格式化：纯函数测试，零外部依赖。

这些函数是所有报告数字的**最后一道出口**——大表里「139/↓4」「↑33.87%」
这类字符串就是它们拼出来的。口径一旦漂移，报告会静默出错，
所以这里把当前行为焊死。
"""
import pandas as pd
import pytest

import compute


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
