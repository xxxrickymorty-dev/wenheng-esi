# -*- coding: utf-8 -*-
"""取数开始前检查的两个坑（2026-10-17 事故复盘）：

- 探针/取数解释器必须**真装了 playwright**：`shutil.which("python")` 在 `uv run` 的 PATH 里
  先命中 `.venv` 的 python（没 playwright），探针一 import 就炸 → preflight 永远 browser:"bad"。
- 9222 认主：**任意占端口的进程不算**「下载数据专用浏览器」——被无头 Edge 之类骗过就永远不开登录窗口。

2026-10-19（ADR-0010）补：op 记 pid、判活（`_acq_op_running`）、顶层崩溃兜底（`_guarded`）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src"), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import acquire as acq                                                    # noqa: E402
import acquisition_state as st                                           # noqa: E402
from server import app as app_module                                     # noqa: E402


# ------------------------------------------------------------------ fetch_python 挑解释器
def test_挑解释器_显式环境变量优先(tmp_path, monkeypatch, capsys):
    want = str(tmp_path / "x" / "python.exe")
    monkeypatch.setenv("WENHENG_FETCH_PYTHON", want)
    monkeypatch.setattr(acq, "_has_playwright", lambda exe: False)
    assert acq._pick_fetch_python() == want
    assert "WENHENG_FETCH_PYTHON" in capsys.readouterr().err, "没 playwright 该提示"


def test_挑解释器_跳过没playwright的取第一个有的(tmp_path, monkeypatch):
    monkeypatch.delenv("WENHENG_FETCH_PYTHON", raising=False)
    bad = str(tmp_path / "bad" / "python.exe")
    good = str(tmp_path / "good" / "python.exe")
    monkeypatch.setattr(acq.shutil, "which", lambda name: bad)
    monkeypatch.setattr(acq.sys, "executable", good)
    monkeypatch.setattr(acq, "_has_playwright", lambda exe: exe == good)
    assert acq._pick_fetch_python() == good


def test_挑解释器_一个都没有_回落并警告(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WENHENG_FETCH_PYTHON", raising=False)
    fallback = str(tmp_path / "fallback" / "python.exe")
    monkeypatch.setattr(acq.shutil, "which", lambda name: fallback)
    monkeypatch.setattr(acq.sys, "executable", fallback)
    monkeypatch.setattr(acq, "_has_playwright", lambda exe: False)
    assert acq._pick_fetch_python() == fallback
    assert "没找到装 playwright" in capsys.readouterr().err


def test_fetch_python_只挑一次并记住(monkeypatch):
    calls = []
    monkeypatch.setattr(acq, "_pick_fetch_python", lambda: calls.append(1) or "C:\\p\\python.exe")
    monkeypatch.setattr(acq, "_FETCH_PY", None)
    assert acq.fetch_python() == "C:\\p\\python.exe"
    assert acq.fetch_python() == "C:\\p\\python.exe"
    assert len(calls) == 1


def test_跳过Windows商店占位stub(tmp_path, monkeypatch):
    monkeypatch.delenv("WENHENG_FETCH_PYTHON", raising=False)
    stub = str(tmp_path / "WindowsApps" / "python.exe")
    monkeypatch.setattr(acq.shutil, "which", lambda name: stub)
    monkeypatch.setattr(acq.sys, "executable", stub)
    monkeypatch.setattr(acq, "_has_playwright", lambda exe: True)   # stub 也装了也不许用
    assert acq._pick_fetch_python() != stub


# ------------------------------------------------------------------ 9222 认主
def test_认主_占用者带专用profile才算(monkeypatch):
    monkeypatch.setattr(st, "cdp_listener_cmdline",
                        lambda port=st.CDP_PORT:
                        f"chrome.exe --remote-debugging-port=9222 --user-data-dir={st.CDP_PROFILE_DIR}")
    assert st.cdp_browser_ours() is True


def test_认主_大小写不同也算_别的profile不算(monkeypatch):
    monkeypatch.setattr(st, "cdp_listener_cmdline",
                        lambda port=st.CDP_PORT: f"--user-data-dir={str(st.CDP_PROFILE_DIR).upper()}")
    assert st.cdp_browser_ours() is True
    monkeypatch.setattr(st, "cdp_listener_cmdline",
                        lambda port=st.CDP_PORT: "msedge.exe --user-data-dir=C:\\tmp\\opencode\\edge-dbg")
    assert st.cdp_browser_ours() is False
    monkeypatch.setattr(st, "cdp_listener_cmdline", lambda port=st.CDP_PORT: "")
    assert st.cdp_browser_ours() is False


def test_专用浏览器在跑_得应答CDP且认主(monkeypatch):
    monkeypatch.setattr(app_module, "_acq_cdp_responds", lambda: True)
    monkeypatch.setattr(app_module.acquisition, "cdp_browser_ours", lambda: False)
    assert app_module._acq_cdp_alive() is False, "别人占 9222 不能算在跑"
    monkeypatch.setattr(app_module.acquisition, "cdp_browser_ours", lambda: True)
    assert app_module._acq_cdp_alive() is True
    monkeypatch.setattr(app_module, "_acq_cdp_responds", lambda: False)
    assert app_module._acq_cdp_alive() is False


# ------------------------------------------------------------------ preflight 探针后认主降级
class _FakeRun:
    def __init__(self, stdout: str):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def _probe_stdout(browser: str) -> str:
    return json.dumps({"browser": browser, "esi": "waiting", "incites": "waiting"})


def _run_preflight(tmp_path, monkeypatch, browser: str, ours: bool) -> dict:
    monkeypatch.setattr(acq.A, "STATE_DIR", tmp_path / "_acquisition")
    monkeypatch.setattr(acq, "fetch_python", lambda: "C:\\fake\\python.exe")
    monkeypatch.setattr(acq.subprocess, "run", lambda *a, **kw: _FakeRun(_probe_stdout(browser)))
    monkeypatch.setattr(acq.A, "cdp_browser_ours", lambda: ours)
    rc = acq.cmd_preflight(argparse.Namespace(period="202611"))
    assert rc == 0
    saved = json.loads((tmp_path / "_acquisition" / "202611.json").read_text(encoding="utf-8"))
    return saved["preflight"]


def test_preflight_别的浏览器占着9222_照报未连接(tmp_path, monkeypatch):
    pf = _run_preflight(tmp_path, monkeypatch, browser="ok", ours=False)
    assert pf["browser"] == "bad", "无头 Edge 之类占 9222，探针不许报已连接"


def test_preflight_自家浏览器_已连接照报(tmp_path, monkeypatch):
    pf = _run_preflight(tmp_path, monkeypatch, browser="ok", ours=True)
    assert pf["browser"] == "ok"


def test_preflight_本来就没连上_不认主也不改(tmp_path, monkeypatch):
    pf = _run_preflight(tmp_path, monkeypatch, browser="bad", ours=False)
    assert pf["browser"] == "bad"


# ------------------------------------------------------------------ op 活性与崩溃兜底（ADR-0010）
def test_set_op_带pid(tmp_path, monkeypatch):
    """`op` 记写方进程号——服务端据此判活（原来是「1 小时没动静」的时间口径）。"""
    monkeypatch.setattr(acq.A, "STATE_DIR", tmp_path / "_acquisition")
    acq._set_op("202611", "fetch", "running", "正在下载")
    saved = json.loads((tmp_path / "_acquisition" / "202611.json").read_text(encoding="utf-8"))
    assert saved["op"]["pid"] == os.getpid()


def test_取数流程崩溃_顶层兜底落failed(tmp_path, monkeypatch):
    """2026-10-17 暴死留下的 op=running 僵尸：现在进程自己落 failed（带一行原因）。"""
    monkeypatch.setattr(acq.A, "STATE_DIR", tmp_path / "_acquisition")

    def boom(_args):
        raise RuntimeError("模拟暴死")

    rc = acq._guarded(argparse.Namespace(cmd="fetch", period="202611", fn=boom))
    assert rc == 1
    saved = json.loads((tmp_path / "_acquisition" / "202611.json").read_text(encoding="utf-8"))
    assert saved["op"]["state"] == "failed"
    assert "RuntimeError" in saved["op"]["note"] and "模拟暴死" in saved["op"]["note"]
    assert saved["op"]["pid"] == os.getpid()


def _op_state(**op) -> dict:
    return {"op": {"kind": "fetch", "state": "running", "at": "2026-10-17 13:02:40", **op}}


def test_op判活_进程已死_自动落failed并放行(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.acquisition, "load", lambda _p: _op_state(pid=424242))
    monkeypatch.setattr(app_module.acquisition, "pid_alive", lambda _pid: False)
    saved: dict = {}
    monkeypatch.setattr(app_module.acquisition, "write_state",
                        lambda p, s: saved.update(period=p, state=s))
    monkeypatch.setattr(app_module.acquisition, "state_path", lambda _p: tmp_path / "x.json")
    assert app_module._acq_op_running("202609") is None, "进程死了要放行新任务"
    assert saved["state"]["op"]["state"] == "failed"
    assert saved["state"]["op"]["note"].startswith("上次运行中断")


def test_op判活_进程活着_仍然拦(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.acquisition, "load", lambda _p: _op_state(pid=os.getpid()))
    monkeypatch.setattr(app_module.acquisition, "pid_alive", lambda _pid: True)
    assert app_module._acq_op_running("202609") is not None


def test_op无pid旧状态_15分钟兜底(tmp_path, monkeypatch):
    """没有 pid 的历史状态回退时间口径：阈值 15 分钟（原 1 小时）。

    超时视为中断 → 在写动作路径如实结清（落 failed）；不再干等 1 小时。
    """
    state_file = tmp_path / "202609.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_module.acquisition, "load", lambda _p: _op_state())
    monkeypatch.setattr(app_module.acquisition, "state_path", lambda _p: state_file)
    saved: dict = {}
    monkeypatch.setattr(app_module.acquisition, "write_state",
                        lambda p, s: saved.update(period=p, state=s))
    assert app_module._acq_op_running("202609") is not None, "刚写过 → 还在跑"
    old = time.time() - app_module.acquisition.OP_STALE_SECONDS - 5
    os.utime(state_file, (old, old))
    assert app_module._acq_op_running("202609") is None, "超 15 分钟 → 放行"
    assert saved["state"]["op"]["state"] == "failed"
    assert "上次运行中断" in saved["state"]["op"]["note"]


# ------------------------------------------------------------------ 疑似中断（只读 liveness）与停止下载（2026-10-19 晚）
def test_liveness_四分类(tmp_path, monkeypatch):
    """GET 只读判断：alive / dead / stale / 非 running → None（不改状态）。"""
    state_file = tmp_path / "202609.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_module.acquisition, "state_path", lambda _p: state_file)
    monkeypatch.setattr(app_module.acquisition, "pid_alive", lambda pid: pid == 4242)
    A = app_module._acq_op_liveness
    assert A("202609", {"op": {"state": "failed"}}) is None
    assert A("202609", {}) is None
    assert A("202609", {"op": {"state": "running", "pid": 4242}}) == "alive"
    assert A("202609", {"op": {"state": "running", "pid": 4243}}) == "dead"
    assert A("202609", {"op": {"state": "running"}}) == "alive"     # 无 pid 且刚动过
    old = time.time() - app_module.acquisition.OP_STALE_SECONDS - 5
    os.utime(state_file, (old, old))
    assert A("202609", {"op": {"state": "running"}}) == "stale"     # 无 pid 且太久没动静


class _Req:
    """极简请求替身：`user_route` 的登录门只读 session 里的用户。"""
    session = {"user": "admin"}


def test_停止_没有在跑的任务_409不写状态(monkeypatch):
    monkeypatch.setattr(app_module.acquisition, "load", lambda _p: {"op": {"state": "failed"}})
    writes: list = []
    monkeypatch.setattr(app_module.acquisition, "write_state", lambda p, s: writes.append(s))
    import asyncio
    r = asyncio.run(app_module.api_acq_stop(_Req(), "202609"))
    assert r.status_code == 409
    assert writes == [], "409 不得写状态"


def test_停止_僵尸直接结清(tmp_path, monkeypatch):
    """进程早没了的 running → 停不假报「停成功」，如实落「上次运行中断」。"""
    monkeypatch.setattr(app_module.acquisition, "load",
                        lambda _p: {"op": {"state": "running", "pid": 424242, "kind": "fetch"}})
    monkeypatch.setattr(app_module.acquisition, "pid_alive", lambda _pid: False)
    saved: dict = {}
    monkeypatch.setattr(app_module.acquisition, "write_state",
                        lambda p, s: saved.update(state=s))
    import asyncio
    r = asyncio.run(app_module.api_acq_stop(_Req(), "202609"))
    assert r["ok"] is True and r["stopped"] is False and r["liveness"] == "dead"
    assert saved["state"]["op"]["state"] == "failed"
    assert saved["state"]["op"]["note"].startswith("已停止")


def test_停止_真在跑_连子进程一起停(tmp_path, monkeypatch):
    """真起一个睡 60 秒的子进程（自成进程组），走停止端点 → 进程要没、状态落「已停止」。"""
    import subprocess as sp
    import sys as _sys
    import asyncio
    child = sp.Popen([_sys.executable, "-c", "import time; time.sleep(60)"],
                     start_new_session=(os.name != "nt"))
    try:
        monkeypatch.setattr(app_module.acquisition, "load",
                            lambda _p: {"op": {"state": "running", "pid": child.pid, "kind": "fetch"}})
        saved: dict = {}
        monkeypatch.setattr(app_module.acquisition, "write_state",
                            lambda p, s: saved.update(state=s))
        r = asyncio.run(app_module.api_acq_stop(_Req(), "202609"))
        assert r["ok"] is True and r["stopped"] is True and r["liveness"] == "alive"
        deadline = time.time() + 10
        while time.time() < deadline and child.poll() is None:
            time.sleep(0.2)
        assert child.poll() is not None, "子进程应已被停掉"
        assert saved["state"]["op"]["note"].startswith("已停止")
    finally:
        if child.poll() is None:
            child.kill()
