# -*- coding: utf-8 -*-
"""状态文件的原子写（ADR-0012 决定 1）：同目录 tmp → fsync → `os.replace`。

仓里原本有两份写法，本模块是合并后的唯一实现：

- `src/ai/_record.py::atomic_write_text`：唯一 tmp 名（pid + token）✓、失败清理 tmp ✓，
  但**不 fsync、不重试**。
- `src/acquisition_state.py::write_state`：`PermissionError` 重试 ✓（Windows 上 `os.replace`
  撞并发读句柄会 WinError 5/32，取数台 4 秒轮询就是常态读方），但 tmp 名固定、并发会互撞。

🔴 **字节不变是本模块的硬要求**：`newline` 默认 `None`，与 `Path.write_text` 一致
（平台换行翻译：Windows 上 `\n` → `\r\n`）。仓里既有状态文件都是这样写出来的，改成强制
`"\n"` 会让「同一个 dict 重新序列化」产生不同字节——审批指纹与归档比对都建在字节上。
唯一用 `"\n"` 的是 `_record.atomic_write_text` 那一路（`out/_ai/settings.json` 历来是 LF），
由它自己显式传参，**别改这里的默认值**。
"""
from __future__ import annotations

import os
import pathlib
import secrets
import time

try:                                        # 仓内常态：仓库根在 sys.path 上（server / tests）
    from src import acquisition_state as _acq
except ImportError:                         # 只有 src/ 在 sys.path 上（src 内脚本、tools）
    import acquisition_state as _acq


def tmp_path(path) -> pathlib.Path:
    """同目录唯一临时名（pid + token：并发的两次写不会撞同一个 tmp）。"""
    path = pathlib.Path(path)
    return path.with_name(f"{path.name}.tmp-{os.getpid()}-{secrets.token_hex(3)}")


def write_text_atomic(path, text: str, *, encoding: str = "utf-8", newline=None) -> None:
    """把 `text` 原子写到 `path`；中途失败时目标文件保持旧内容、tmp 被清理。

    - 父目录不存在则建（沿用原 `_record.atomic_write_text` 的口径）；
    - `flush` + `os.fsync` 之后才替换：进程被杀/断电不会留下半截文件；
    - `os.replace` 撞 Windows 并发读句柄时，按 `acquisition_state` 那套退避重试
      （`WRITE_RETRIES` × `WRITE_RETRY_SLEEP`），仍失败才抛 —— 参数只在那边定义一份。
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path(path)
    try:
        with open(tmp, "w", encoding=encoding, newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(_acq.WRITE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _acq.WRITE_RETRIES - 1:
                    raise
                time.sleep(_acq.WRITE_RETRY_SLEEP)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
