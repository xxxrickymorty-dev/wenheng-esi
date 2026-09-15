# -*- coding: utf-8 -*-
"""pytest 公共夹具与路径解析。

测试分两层，互不干扰：

  · **纯函数测试** —— 只依赖 `src/` 里的代码，永远可跑（含 CI）。
  · **数据驱动测试** —— 依赖馆员台账（`input/`）或历史产物（`out/`）。
    这两类数据按 `.gitignore` 不入库，**新 clone 的仓库里不存在**，
    因此夹具在缺数据时直接 `skip`，而不是让测试失败——
    避免"没数据 = 代码坏了"这种误导性红灯。

跑法：
    uv run pytest                 # 全跑
    uv run pytest -m "not slow"   # 跳过端到端
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _ensure_path():
    """保证 `import compute / parse_ledger / verify_report_docx` 可用。

    pyproject 的 `[tool.pytest.ini_options] pythonpath` 已配好，
    这里再兜一层，让 `python tests/test_x.py` 直接跑也成立。
    """
    for sub in ("src", "tools"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()


def _ledgers():
    """仓库内所有台账，按期次升序。"""
    return sorted((REPO / "input").glob("*/监测表.xlsx"))


def _out_dirs():
    d = REPO / "out"
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("20*") if p.is_dir())


@pytest.fixture(scope="session")
def repo():
    return REPO


@pytest.fixture(scope="session")
def all_ledgers():
    """全部可用台账；一个都没有则 skip。"""
    leds = _ledgers()
    if not leds:
        pytest.skip("input/ 下无台账（馆员数据不入库，属正常）")
    return leds


@pytest.fixture(scope="session")
def latest_ledger(all_ledgers):
    return all_ledgers[-1]


@pytest.fixture(scope="session")
def out_dirs():
    dirs = _out_dirs()
    if not dirs:
        pytest.skip("out/ 下无历史产物")
    return dirs


@pytest.fixture(scope="session")
def reports(out_dirs):
    """历史产物中的报告初稿 docx。"""
    rs = [p for d in out_dirs for p in d.glob("报告初稿*.docx")]
    if not rs:
        pytest.skip("out/ 下无报告初稿 docx")
    return rs
