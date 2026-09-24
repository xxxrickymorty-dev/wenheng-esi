# -*- coding: utf-8 -*-
"""护栏回归：读 ESI 原始包禁 `read_only=True`。

背景（2026-09-23 实测）：202609 起新导出的 ESI xlsx，`<dimension>` 被写成 `A1`，
openpyxl 在 `read_only=True` 下据此把 1 万行读成 **1×1 空表**（`reset_dimensions`
也救不回），而且**静默**——解析结果变空、不抛异常。

真实后果：`src/extract_matrix.py::_esi_top_schools` 漏改，202609 的 T20 矩阵
「已进前 1%」判据全空 → 本应是 `Y` 的 **49 格**被填成百分比，安静地进了报告。
（修后 55 个 Y，与 202607 的 54 个同量级；云大 Y=14 与 ESI 在榜 14 一致。）

守的是**静默失效**，所以护栏自身也必须自证有辨别力。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO / "src"), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import guard_no_readonly as g                                   # noqa: E402


def test_guard_selftest_passes():
    """护栏要有辨别力：正例判 FAIL、读 InCites/普通模式不误报。"""
    assert g.selftest() == 0


def test_no_readonly_on_esi_readers():
    """仓内不得存在「读 ESI 包却用 read_only=True」的调用点。"""
    fails = [
        (path, line, func)
        for path in g.iter_targets(REPO)
        for level, line, func in g.scan_file(path)
        if level == "FAIL"
    ]
    assert not fails, "读 ESI 包却用 read_only=True：" + "; ".join(
        f"{path.relative_to(REPO).as_posix()}:{line} {func}" for path, line, func in fails
    )
