# -*- coding: utf-8 -*-
"""文衡 Agent 层（P1，里程碑 M2）。

对外只暴露编排入口与状态机定义：

    from agent import flow, states
    result = flow.run("input/202609/监测表.xlsx")

本包把 `src/` 加入 sys.path，使编排器可以直接 import 引擎模块
（parse_ledger / compute / forecast / charts / fill_docx）。
"""
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from . import states  # noqa: E402,F401

__all__ = ["states", "flow", "tools", "trace"]
