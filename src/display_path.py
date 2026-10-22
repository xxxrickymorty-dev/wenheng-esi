# -*- coding: utf-8 -*-
"""仓库内路径的两种写法：**给人看 / 落状态**用仓库相对，**读写**用真实路径。

为什么要有这一层（2026-10-22）：`out/_state` 的 `jobs.payload` 与
`out/_acquisition/<期次>.json` 都在部署包白名单里（`tools/make_deploy_pkg.py`）。
把 `C:/Users/<用户名>/...` 写进去等于把开发机路径打进外发件，换台机器后也不成立。

判据是「路径在不在仓库之下」：
  · 在 → `out/_jobs/<id>/progress.jsonl`（部署机从 `/opt/wenheng` 拼回同一位置）；
  · 不在（`/tmp` 里的临时目录、别的盘）→ 只能给绝对路径——这类值本身不进外发件，
    真漏了由打包的泄漏扫描兜住（判据见打包脚本的 `_path_checks`）。

读回一律走 `from_repo_relative()`：相对写法按**仓库根**拼回绝对路径；绝对写法原样
返回（历史记录里有旧工作区的绝对路径，重定位见 `server/jobs.py::_relocate`）。
只做字符串换算，不碰磁盘——不存在的路径也照样给出，缺件由上层判。
"""
from __future__ import annotations

import pathlib

#: 仓库根（`wenheng/`）。两种写法共用它，避免各处再 `parent.parent` 一遍。
REPO = pathlib.Path(__file__).resolve().parent.parent


def to_repo_relative(p, root=None) -> str:
    """真实路径 → 仓库相对写法（posix 分隔符）；仓库外给绝对路径的 posix 写法。

    `root` 只给测试/工具改锚点用；常态是 `REPO`。
    """
    base = pathlib.Path(root) if root is not None else REPO
    raw = pathlib.Path(p)
    try:
        return raw.resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return raw.as_posix()


def from_repo_relative(value, root=None) -> pathlib.Path:
    """仓库相对写法 → 真实路径（绝对）；本来就是绝对的（含 `C:/...` 旧记录）原样返回。

    Windows 旧记录在 Linux 部署机上解不出真实位置——那是 `_relocate` 按同名文件
    兜的活，这里不假装能解析。
    """
    base = pathlib.Path(root) if root is not None else REPO
    raw = pathlib.Path(str(value))
    if is_absolute(value):
        return raw
    return base / raw


def is_absolute(value) -> bool:
    """是不是绝对写法（posix 的 `/x` 与 Windows 的 `C:\\x` 都算）。

    单靠 `PurePosixPath.is_absolute()` 认不出盘符，单靠 `PureWindowsPath.drive`
    在 posix 写法上又只认 `C:` 开头——两种都要过一遍。
    """
    text = str(value or "")
    if not text:
        return False
    return pathlib.PurePosixPath(text).is_absolute() or bool(pathlib.PureWindowsPath(text).drive)
