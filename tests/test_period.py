# -*- coding: utf-8 -*-
"""期次口径的唯一事实源：`src/period.py`。

这组用例存在的理由：期次判定原先有 4 套算法、15 个落点，改错了**不抛异常** ——
只会静默把报告填成别的期次（2026-09-18 已发生过一次）。所以每条口径都要钉住，
尤其是「脏列名算不算一期」这种只有脏台账才暴露的分歧。
"""
import pathlib
import subprocess
import sys

import pandas as pd
import pytest

import period

REPO = pathlib.Path(__file__).resolve().parent.parent


def _wide(cols, filled_cols=None):
    """构造 compute.load_wide 形状的最小宽表字典。"""
    filled_cols = list(cols) if filled_cols is None else filled_cols
    data = {c: ([1.0] * 3 if c in filled_cols else [None] * 3) for c in cols}
    return {"total_cites": pd.DataFrame(data, index=["Chemistry"] * 3)}


class TestValid:
    def test_规范期次是六位数字(self):
        assert period.valid("202607") and period.valid("201903")

    @pytest.mark.parametrize("bad", ["2026.5", "202605_复现", "20260", "2026070",
                                     "2026年7月", "", None, "20260a"])
    def test_别的形态都不算规范期次(self, bad):
        assert not period.valid(bad)


class TestParse:
    @pytest.mark.parametrize("raw,want", [
        ("202605", "202605"),
        ("2026.5", "202605"),
        ("2023-03", "202303"),
        ("2023年7月", "202307"),
        ("2023年11月", "202311"),
        ("2023/3", "202303"),
        ("20233", "202303"),
        ("2026年第3期", "202603"),
        ("  202605  ", "202605"),
        # 尾部的说明性后缀同样被吃掉（正则尾段是 `\D*$`）。这一条不是"顺手"：
        # 它意味着 `parse` **不能**用来判断"这是不是一个干净的列名"——
        # 目录名要抽取请走 `from_dir`（前缀锚定），要校验请走 `valid`。
        ("202605_复现", "202605"),
    ])
    def test_脏期次归一到YYYYMM(self, raw, want):
        assert period.parse(raw) == want

    @pytest.mark.parametrize("raw", ["20231231", "2023.03.15", "2023年", "抽查", "第二期"])
    def test_认不出来的原样返回(self, raw):
        assert period.parse(raw) == raw

    def test_空值返回空串(self):
        assert period.parse(None) == "" and period.parse("") == ""


class TestFromDir:
    @pytest.mark.parametrize("name,want", [
        ("202607", "202607"),
        ("202605_复现", "202605"),
        ("202607_备份", "202607"),
    ])
    def test_期次目录取出期次(self, name, want):
        assert period.from_dir(f"out/{name}") == want

    @pytest.mark.parametrize("name", ["_jobs", "_pending", "_archive", "对样包_202607",
                                      "20260", "twothousand"])
    def test_非期次目录返回None(self, name):
        assert period.from_dir(f"out/{name}") is None

    def test_认完整路径也认纯目录名(self):
        p = REPO / "out" / "202605_复现"
        assert period.from_dir(p) == "202605" and period.from_dir("202605_复现") == "202605"


class TestFilled:
    def test_只算有数据的列(self):
        w = _wide(["202601", "202603", "202605"], filled_cols=["202601", "202603"])
        assert period.filled(w) == ["202601", "202603"]

    def test_脏列名不算一期(self):
        """2023.3 这种脏表头即使有数据也不成为一期 —— 否则 out/2023.3/ 会建出来。"""
        w = _wide(["2023.3", "202603", "202605"])
        assert period.filled(w) == ["202603", "202605"]

    def test_保持台账列序(self):
        w = _wide(["202605", "202601", "202603"])
        assert period.filled(w) == ["202605", "202601", "202603"]


class TestDetect:
    def test_取最后两个有效期次(self):
        w = _wide(["202601", "202603", "202605"])
        assert period.detect(w) == ("202605", "202603")

    def test_忽略尾部全空列(self):
        w = _wide(["202601", "202603", "202605"], filled_cols=["202601", "202603"])
        assert period.detect(w) == ("202603", "202601")

    def test_不足两期报错(self):
        with pytest.raises(period.PeriodUndetectable, match="不足 2 期"):
            period.detect(_wide(["202605"]))

    def test_报错可按ValueError捕获(self):
        """旧调用方（含既有测试）按 ValueError 捕获，不能被这次搬家破坏。"""
        assert issubclass(period.PeriodUndetectable, ValueError)


class TestPrevBefore:
    def test_取严格早于的最近一期(self):
        ps = ["202601", "202603", "202605", "202607"]
        assert period.prev_before(ps, "202607") == "202605"
        assert period.prev_before(ps, "202605") == "202603"

    def test_跨缺口也取最近的上一期(self):
        assert period.prev_before(["202601", "202507"], "202601") == "202507"

    def test_没有更早的期次就报错(self):
        with pytest.raises(period.PeriodUndetectable, match="没有早于"):
            period.prev_before(["202601"], "202601")

    def test_当期的上期等于序列倒数第二个(self):
        ps = ["202601", "202603", "202605"]
        assert period.prev_before(ps, ps[-1]) == ps[-2]


class TestLabelAndMonth:
    @pytest.mark.parametrize("p,m", [("202607", 7), ("202611", 11), ("202601", 1)])
    def test_月份数(self, p, m):
        assert period.month(p) == m

    def test_中文年月(self):
        assert period.label("202607") == "2026年7月"
        assert period.label("202611") == "2026年11月"


class TestIssueOf:
    @pytest.mark.parametrize("p,want", [
        ("202601", (1, 35)),
        ("202603", (2, 36)),
        ("202605", (3, 37)),
        ("202607", (4, 38)),
        ("202609", (5, 39)),
        ("202611", (6, 40)),
        ("202701", (7, 41)),
    ])
    def test_年内序号与总期号(self, p, want):
        assert period.issue_of(p) == want

    def test_早于锚点报错而不是算负号(self):
        with pytest.raises(period.PeriodBeforeAnchor):
            period.issue_of("201903")

    def test_非规范期次报错(self):
        with pytest.raises(period.PeriodUndetectable):
            period.issue_of("202605_复现")


class TestServerFacing:
    def test_目录正则只认前缀不认后缀(self):
        """server/jobs.py re-export 这两个常量，语义必须是它原来那两条。"""
        assert period.PERIOD_RE.match("202607") and not period.PERIOD_RE.match("202605_复现")
        assert period.PERIOD_DIR_RE.match("202605_复现")

    def test_模块不依赖pandas(self):
        """server/ 全目录零 pandas；period 被 server import 时不能把 pandas 拖进启动路径。"""
        code = ("import sys; sys.path.insert(0, r'%s'); import period; "
                "print('pandas' in sys.modules)" % (REPO / "src"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, check=True).stdout.strip()
        assert out == "False", "import period 顺手把 pandas 也拉进来了"
