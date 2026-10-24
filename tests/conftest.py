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

跳过不是无声的
--------------------------------------------------------------------------------
本文件末尾的 `pytest_sessionfinish` 会把"跳过了几条、理由是否成立"复核一遍：
每次跳过都登记了复核探针（见 `_guard_registry.py`），**只要探针说那个资源还在，
会话就判失败**。防的是"路径写错 → 整组守卫静默 skip → pytest 全绿"。
"""
import os
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

_TESTS_DIR = str(pathlib.Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from _guard_registry import outstanding, skip_unless, stats   # noqa: E402


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
    """仓库里的动态监测表（母本；2026-10-13 起 input/ 只放它）——数据驱动用例的探针。"""
    p = REPO / "input" / "云大全学科排名、阈值动态检测表.xlsx"
    return [p] if p.is_file() else []


def is_demo_ledger(path=None):
    """台账是否为 `tools/make_demo_ledger.py` 生成的演示数据。

    以 `input/.demo_marker.json`（sidecar，含台账 sha256）为准：
    标记在且 sha256 与台账一致才算演示数据 —— 防止真台账与旧标记错配。
    演示数据在位时，钉真实指纹的数据测试应显式 skip（理由登记守卫体检）。
    """
    p = pathlib.Path(path) if path else (
        REPO / "input" / "云大全学科排名、阈值动态检测表.xlsx")
    if not p.is_file():
        return False
    marker = p.parent / ".demo_marker.json"
    if not marker.is_file():
        return False
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
        import hashlib
        return bool(info.get("demo")) and \
            info.get("sha256") == hashlib.sha256(p.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False


def _out_dirs():
    d = REPO / "out"
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("20*") if p.is_dir())


def _reports():
    return [p for d in _out_dirs() for p in d.glob("报告初稿*.docx")]


@pytest.fixture(scope="session")
def repo():
    return REPO


@pytest.fixture(scope="session", autouse=True)
def _isolate_ai_env_session():
    """会话级收口：收集期各测试模块 import 会把 `server/.env` 灌进 os.environ（setdefault）。

    ⚠ 但它挡不住「session 级夹具创建早于本夹具」的次序（2026-09-29 踩：flex_report_out
    带着真 key 出网，结果随网络成败漂移）——那种夹具自己显式注入 `RuleBrain`；
    函数级再有 `_isolate_ai_env` 逐测试兜底。
    """
    saved = {k: os.environ.pop(k) for k in [k for k in os.environ if k.startswith("WENHENG_AI_")]}
    yield
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _isolate_ai_env(monkeypatch):
    """AI 层云配置对每个测试隐身：本机 server/.env 配了 key 也不许测试走模型/出网。

    - 「默认 = 规则版」是金样对拍与 determinism 测试的前提；
    - 云适配器测试自己用 `monkeypatch.setenv` 显式开（tests/test_ai_openai.py）；
    - 灵活报告的两个开关（润色/写作位）同样收口：开发机开着也不许漏进测试。
    """
    for key in [k for k in os.environ
                if k.startswith("WENHENG_AI_")
                or k in ("WENHENG_FLEX_WRITE", "WENHENG_FLEX_POLISH")]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(scope="session")
def all_ledgers():
    """全部可用台账；一个都没有则 skip。"""
    leds = _ledgers()
    if not leds:
        skip_unless("input/ 下无台账（馆员数据不入库，属正常）",
                    lambda: bool(_ledgers()))
    return leds


@pytest.fixture(scope="session")
def real_ledger(all_ledgers):
    """真实（非演示）台账；当前在位的是演示台账则 skip。

    钉真实数据指纹的测试（金样 MAPE、期数、潜力集合等）用它：
    演示台账能过形状断言但数值是合成的，指纹必然失败——
    skip 理由登记进守卫体检，探针（is_demo_ledger）复核非静默降级。
    """
    if is_demo_ledger(all_ledgers[-1]):
        skip_unless("在位台账为演示数据（make_demo_ledger），"
                    "该用例钉的是真实台账指纹",
                    lambda: not is_demo_ledger())
    return all_ledgers[-1]


@pytest.fixture(scope="session")
def latest_ledger(all_ledgers):
    return all_ledgers[-1]


@pytest.fixture(scope="session")
def out_dirs():
    dirs = _out_dirs()
    if not dirs:
        skip_unless("out/ 下无历史产物", lambda: bool(_out_dirs()))
    return dirs


@pytest.fixture(scope="session")
def reports(out_dirs):
    """历史产物中的报告初稿 docx。"""
    rs = _reports()
    if not rs:
        skip_unless("out/ 下无报告初稿 docx", lambda: bool(_reports()))
    return rs


# ---------------------------------------------------------------- 会话收尾复核
def pytest_sessionfinish(session, exitstatus):
    """把"跳过"从静默降级变成可核验的缺席。

    只要有一条跳过站不住脚（探针说资源其实在），整个会话判失败 ——
    这类错的症状就是"测试全绿但少跑了几十条"，唯一能让它现形的时机是收尾。
    """
    n_skips, n_bad = stats()
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if not n_skips:
        return
    if n_bad:
        if tr:
            tr.write_sep("=", "守卫体检未过", red=True, bold=True)
            for reason in outstanding():
                tr.write_line(f"  · 跳过站不住脚：{reason}", red=True)
            tr.write_line("  这些用例跳过了，但它们依赖的资源其实在仓库里 ——"
                          " 多半是路径/常量写错了，不是数据缺失。", red=True)
        session.exitstatus = 1
        return
    if tr:
        tr.write_line(f"守卫体检：跳过 {n_skips} 条，均有可核验的缺席理由（探针已复核）")

