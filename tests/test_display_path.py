# -*- coding: utf-8 -*-
"""`src/display_path.py`：仓库相对 ↔ 真实路径的换算（2026-10-22）。

口径分三档：**仓库之下给仓库相对**；**工作区里的兄弟目录给 `../<目录>/…`（只爬一层）**；
再远（别处、别的盘）给绝对——`../../..` 链子换台机器就指到别处，写出来是编的。
这条口径同时被 `out/_acquisition/<期次>.json`（上一票）与 `jobs.payload`（本票）使用——
所以换算本体只写一遍，这里把它钉住，别让两处各写一套再漂。
"""
import os
import pathlib

import pytest

from src import display_path


def test_仓库内路径给仓库相对(tmp_path):
    root = tmp_path / "wenheng"
    p = root / "out" / "_jobs" / "j1" / "progress.jsonl"
    assert display_path.to_repo_relative(p, root) == "out/_jobs/j1/progress.jsonl"


def test_仓库外路径看远近(tmp_path):
    """兄弟目录给 `../`，再远给绝对——判据是「换台机器还指得到吗」。"""
    root = tmp_path / "wenheng"
    sibling = tmp_path / "数据与复现" / "x.xlsx"
    assert display_path.to_repo_relative(sibling, root) == "../数据与复现/x.xlsx"
    assert display_path.from_repo_relative("../数据与复现/x.xlsx", root) == sibling

    far = tmp_path.parent.parent / "别的盘" / "x.xlsx"          # 要爬好几层
    value = display_path.to_repo_relative(far, root)
    assert display_path.is_absolute(value), f"太远的路径不该编成 ../ 链子：{value}"
    assert not value.startswith(".."), f"两层以上只许退回绝对，不许编 ../../：{value}"
    assert value.endswith("x.xlsx")                            # 换算只改写法，不改路径内容


def test_兄弟目录写法折回后_parent_是对的(tmp_path):
    """`Path / '..'` 不会自己折回去：不归一的话 `.parent` 会留下 `..`，上层判目录就错。"""
    root = tmp_path / "wenheng"
    back = display_path.from_repo_relative("../数据与复现/云大…xlsx", root)
    assert back.is_absolute()
    assert ".." not in back.parts, f"折回后还留着 ..：{back}"
    assert back == tmp_path / "数据与复现" / "云大…xlsx"
    assert back.parent == tmp_path / "数据与复现"

    nested = display_path.from_repo_relative("../数据与复现/ESI数据/202607/x.zip", root)
    assert nested.parent.name == "202607", f"深一层也要对：{nested}"
    assert ".." not in nested.parts


@pytest.mark.skipif(os.name != "nt", reason="跨盘 relpath 抛 ValueError 只发生在 Windows")
def test_别的盘不炸(tmp_path):
    """Windows 上 `os.path.relpath` 跨盘抛 ValueError；换算必须退回绝对而不是炸。"""
    root = tmp_path / "wenheng"
    value = display_path.to_repo_relative(pathlib.Path("D:/别处/x.xlsx"), root)
    assert display_path.is_absolute(value), f"跨盘给不出相对，就该给绝对：{value}"
    assert value.endswith("x.xlsx")


def test_绝对判据没变(tmp_path):
    """`../x` 是相对（要拼回仓库根），`C:\\x` 与 `/x` 仍是绝对。"""
    assert display_path.is_absolute("C:\\x")
    assert display_path.is_absolute("/x")
    assert display_path.is_absolute("../x") is False
    assert display_path.is_absolute("out/_jobs/j1/progress.jsonl") is False
    assert display_path.from_repo_relative("../x", tmp_path) == tmp_path.parent / "x"


def test_仓库相对能拼回原位置(tmp_path):
    root = tmp_path / "wenheng"
    p = root / "out" / "202607" / "report.docx"
    assert display_path.from_repo_relative(
        display_path.to_repo_relative(p, root), root) == p


def test_绝对写法原样返回(tmp_path):
    """历史记录里的 `C:/…`（另一台机器 / 旧工作区）不许被"猜"成相对。"""
    value = "C:/Users/someone/Desktop/wenheng/out/_jobs/j1/progress.jsonl"
    assert display_path.from_repo_relative(value, tmp_path) == pathlib.Path(value)
    assert display_path.is_absolute(value)


def test_posix绝对也算绝对(tmp_path):
    """部署机是 Linux：`/opt/wenheng/...` 不能被当成仓库相对再拼一遍。"""
    assert display_path.from_repo_relative("/opt/wenheng/out/x.json", tmp_path) \
        == pathlib.Path("/opt/wenheng/out/x.json")
    assert display_path.is_absolute("/opt/wenheng/out/x.json")


def test_空串不算绝对():
    assert display_path.is_absolute("") is False
