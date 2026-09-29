# -*- coding: utf-8 -*-
"""自动取数台（X2/X3）：取数状态的读取门面 + 写动作要用的路径常量。

状态文件 `out/_acquisition/<期次>.json` 的生成、写入与形状定义都在 `src/acquisition_state.py`
（取数流程 `tools/acquire.py` 与工作区写动作共用同一份实现）；本模块只做转出，
不另起一套口径。形状见那份文档串（与前端 `AcquisitionState` 对齐，字段只增不改）。

文件缺失或损坏一律返回 None——界面显示「还没开始」，不编数据。
"""
from __future__ import annotations

from src import acquisition_state as _state

STATE_DIR = _state.STATE_DIR
state_path = _state.state_path
write_state = _state.write_state
load = _state.load_state
periods = _state.periods
