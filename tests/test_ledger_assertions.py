# -*- coding: utf-8 -*-
"""台账解析断言闸：每期台账都必须全绿，否则不允许产出报告。

对应 README 里说的「机器断言」——`parse_ledger.run_assertions()`。
它挡的是最脏的一类错误：馆员贴表错位、期次串行、单位漏换算。
一旦这层破了，后面的计算再正确也是错的。
"""
import pytest

import parse_ledger


def test_所有台账断言全绿(all_ledgers):
    bad = []
    for led in all_ledgers:
        ledger = parse_ledger.load_ledger(led)
        ok, report = parse_ledger.run_assertions(ledger)
        if not ok:
            fails = [m for s, m in report if s == "FAIL"]
            bad.append(f"{led.parent.name}: {fails}")
    assert not bad, "断言未过：\n" + "\n".join(bad)


def test_当期与上期可定位且严格递增(all_ledgers):
    """第 N 期 = 2N−1 月，期次为 6 位年月，且当期必须晚于上期。"""
    for led in all_ledgers:
        ledger = parse_ledger.load_ledger(led)
        P, Q = parse_ledger._latest_periods(ledger)
        assert P.isdigit() and len(P) == 6, f"{led.parent.name}: 当期期次异常 {P!r}"
        assert Q.isdigit() and len(Q) == 6, f"{led.parent.name}: 上期期次异常 {Q!r}"
        assert P > Q, f"{led.parent.name}: 当期 {P} 不应早于上期 {Q}"
