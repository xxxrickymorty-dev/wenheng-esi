# -*- coding: utf-8 -*-
"""数据集更新日 → 期次归位 + 取数前「数据期」判定（票 04）。

判据：要求期次 vs 网站当前数据集更新日（按双月节拍归位）。
读不到更新日要放行（ok=None），不能因网络/登录抖动把人锁死。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

import acquire as acq  # noqa: E402
import period  # noqa: E402


def test_更新日归位到双月期次():
    assert period.release_of("2026-09-02") == "202609"
    assert period.release_of("2026.11.03") == "202611"
    assert period.release_of("2026年07月31日") == "202607"
    # 偶月归到前一个双月：宁可保守，不把数据算成还没到的那一期
    assert period.release_of("2026-10-05") == "202609"
    assert period.release_of("2026-12-01") == "202611"


def test_认不出来的更新日返回空():
    assert period.release_of("") == ""
    assert period.release_of("今天") == ""
    assert period.release_of("2026-13-01") == ""


def test_数据期判定三分支():
    # 一致 → 放行
    assert acq._data_gate("202609", "2026-09-02")["ok"] is True
    # 网站还没更新到这一期 → 拦，并说清当前是哪一期
    blocked = acq._data_gate("202611", "2026-09-02")
    assert blocked["ok"] is False
    assert "还没更新" in blocked["note"] and "202609" in blocked["note"]
    # 读不到更新日 → 放行（提示去连浏览器），不硬拦
    unknown = acq._data_gate("202611", "")
    assert unknown["ok"] is None
    assert "没读到" in unknown["note"]
