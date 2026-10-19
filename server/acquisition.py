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
#: 当期核对副本（`out/_acquisition/<期次>/监测表.xlsx`；ADR-0004 载体，2026-10-13 起不进 input/）
COPY_NAME = _state.COPY_NAME
copy_path = _state.copy_path
#: 「下载数据专用浏览器」（独立 profile + CDP 9222）的认主口径，唯一实现在 src/acquisition_state.py
CDP_PORT = _state.CDP_PORT
CDP_PROFILE_DIR = _state.CDP_PROFILE_DIR
cdp_listener_cmdline = _state.cdp_listener_cmdline
cdp_browser_ours = _state.cdp_browser_ours
#: 取数任务活性（ADR-0010）：判活＝进程在不在；时间兜底只留给无 pid 的旧状态
pid_alive = _state.pid_alive
OP_STALE_SECONDS = _state.OP_STALE_SECONDS

#: 两路原始数据的根目录与「期次→InCites 快照」解析（打包下载等处要用；唯一实现在 src）
ESI_ROOT_DEFAULT = _state.ESI_ROOT_DEFAULT
INCITES_ROOT_DEFAULT = _state.INCITES_ROOT_DEFAULT
resolve_snapshot = _state.resolve_snapshot
