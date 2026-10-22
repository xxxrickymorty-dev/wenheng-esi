# -*- coding: utf-8 -*-
"""仓库内路径的两种写法：**给人看 / 落状态**用仓库相对，**读写**用真实路径。

为什么要有这一层（2026-10-22）：`out/_state` 的 `jobs.payload` 与
`out/_acquisition/<期次>.json` 都在部署包白名单里（`tools/make_deploy_pkg.py`）。
把 `C:/Users/<用户名>/...` 写进去等于把开发机路径打进外发件，换台机器后也不成立。

判据分三档：
  · 仓库之下 → `out/_jobs/<id>/progress.jsonl`（部署机从 `/opt/wenheng` 拼回同一位置）；
  · 仓库外的**兄弟目录** → `../数据与复现/云大…xlsx`（工作区是一起搬的，`..` 只爬一层，
    比绝对路径少一段用户名；`input/` 的母本来源 `../数据与复现/` 就是这一档）；
  · 再远（`/tmp` 里的临时目录、别的盘）→ 只能给绝对路径——`../../..` 这种链子换台机器
    就指到别处，写出来是编的。这类值本身不进外发件，真漏了由打包的泄漏扫描兜住
    （判据见打包脚本的 `_path_checks`）。

读回一律走 `from_repo_relative()`：相对写法（含 `../`）按**仓库根**拼回绝对路径；
绝对写法原样返回（历史记录里有旧工作区的绝对路径，重定位见 `server/jobs.py::_relocate`）。
只做字符串换算，不碰磁盘——不存在的路径也照样给出，缺件由上层判。
"""
from __future__ import annotations

import os
import pathlib

#: 仓库根（`wenheng/`）。两种写法共用它，避免各处再 `parent.parent` 一遍。
REPO = pathlib.Path(__file__).resolve().parent.parent


def to_repo_relative(p, root=None) -> str:
    """真实路径 → 仓库相对写法（posix 分隔符）；仓库外的兄弟目录给 `../<目录>/…`。

    只认「上一层」：`../数据与复现/x.xlsx` 是工作区里的兄弟目录（母本的来源），
    再往上爬的 `..` 链子换台机器就不成立，宁可给绝对路径让打包的扫描去管。
    `root` 只给测试/工具改锚点用；常态是 `REPO`。
    """
    base = pathlib.Path(root) if root is not None else REPO
    raw = pathlib.Path(p)
    try:
        return raw.resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        pass
    try:                                                   # 别的盘在 Windows 上会抛 ValueError
        rel = pathlib.PurePosixPath(
            os.path.relpath(raw.resolve(), base.resolve()).replace(os.sep, "/"))
    except (ValueError, OSError):
        return raw.as_posix()
    if rel.parts.count("..") == 1 and rel.parts[0] == "..":
        return rel.as_posix()
    return raw.as_posix()


def from_repo_relative(value, root=None) -> pathlib.Path:
    """仓库相对写法 → 真实路径（绝对）；本来就是绝对的（含 `C:/...` 旧记录）原样返回。

    `../数据与复现/x.xlsx` 这类兄弟目录写法按词法归一（`Path / '..'` 不会自己折回去，
    不归一的话 `==` 比较与 `.parent` 都会错位）。
    Windows 旧记录在 Linux 部署机上解不出真实位置——那是 `_relocate` 按同名文件
    兜的活，这里不假装能解析。
    """
    base = pathlib.Path(root) if root is not None else REPO
    raw = pathlib.Path(str(value))
    if is_absolute(value):
        return raw
    if ".." in raw.parts:
        return pathlib.Path(os.path.normpath(base / raw))
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
