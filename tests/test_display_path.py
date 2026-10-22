# -*- coding: utf-8 -*-
"""`src/display_path.py`：仓库相对 ↔ 真实路径的换算（2026-10-22）。

口径只有一条：**在仓库之下就给仓库相对，否则给绝对**。这条口径同时被
`out/_acquisition/<期次>.json`（上一票）与 `jobs.payload`（本票）使用——
所以换算本体只写一遍，这里把它钉住，别让两处各写一套再漂。
"""
import pathlib

from src import display_path


def test_仓库内路径给仓库相对(tmp_path):
    root = tmp_path / "wenheng"
    p = root / "out" / "_jobs" / "j1" / "progress.jsonl"
    assert display_path.to_repo_relative(p, root) == "out/_jobs/j1/progress.jsonl"


def test_仓库外路径给绝对(tmp_path):
    root = tmp_path / "wenheng"
    outside = tmp_path / "别处" / "x.xlsx"
    value = display_path.to_repo_relative(outside, root)
    assert display_path.is_absolute(value)
    assert value.endswith("别处/x.xlsx")                      # 换算只改写法，不改路径内容


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
