# -*- coding: utf-8 -*-
"""演示站 ↔ Agent 状态机接线测试（2026-09-15）。

背景：状态口径此前有**两份**——`src/agent/states.py` 10 态（文档要求），
`server/jobs.py` 4 态旧名（done/warn/failed/interrupted）。
两份并存的结果是演示站说的和文档承诺的不是一回事：`done` 不等于 `Completed`，
`interrupted` 是文档里根本没有的状态。

这组测试钉住「只有一份口径」这件事。最狠的一条是 `TERMINAL is states.TERMINAL`
——要求**同一个对象**，不是内容相等；复制一份出来就会红。
"""
import asyncio
import pathlib
import re
import sqlite3
import sys

import pytest

from agent import states
from src import display_path
from src import state_store

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = REPO / "server"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from server import config, jobs                                   # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_state_db(tmp_path, monkeypatch):
    """每个用例一个状态库：任务记录 2026-10-21 起只在库里（绝不碰 out/_state）。"""
    monkeypatch.setenv(state_store.ENV_VAR, str(tmp_path / "_state" / "wenheng.sqlite"))


# ============================================================ 口径唯一
def test_终态集合与状态机是同一个对象():
    """不是"内容一样"，是**同一个 frozenset**。复制一份就等于埋第二条口径。"""
    assert jobs.TERMINAL is states.TERMINAL


def test_中文名与状态机同源():
    assert config.STATUS_LABELS is states.LABELS
    assert config.STATES is states.STATES


def test_十态各有中文名():
    for s in states.STATES:
        assert states.LABELS.get(s), f"{s} 缺中文名，前端会露出英文原样"


# ============================================================ 终态判定
@pytest.mark.parametrize("status,expect", [
    ("completed", True), ("warned", True), ("escalated", True),
    ("failed", True), ("cancelled", True),
    ("running", False), ("pending", False), ("retrying", False),
    ("stalled", False), ("waiting_approval", False),
])
def test_终态判定(status, expect):
    assert jobs.is_terminal(status) is expect


def test_旧名也能判终态():
    """状态库里存的历史记录用旧名，不能因此被判成"还在跑"。"""
    assert jobs.is_terminal("done") is True
    assert jobs.is_terminal("warn") is True
    assert jobs.is_terminal("interrupted") is True
    assert jobs.is_terminal("running") is False


@pytest.mark.parametrize("old,new", [
    ("done", "completed"), ("warn", "warned"),
    ("failed", "failed"), ("interrupted", "failed"),
    ("running", "running"), ("pending", "pending"),
])
def test_旧名归一(old, new):
    assert states.normalize(old) == new


def test_状态中文名新旧都能吃():
    assert jobs.status_label("done") == "已完成"
    assert jobs.status_label("interrupted") == "失败"
    assert jobs.status_label("escalated") == "需人工接手"


def test_认不出的状态名不静默吞掉():
    """宁可原样透出，也不要假装认识——假认识会掩盖上游 bug。"""
    assert states.normalize("某个不存在的状态") == "某个不存在的状态"
    assert jobs.status_label("某个不存在的状态") == "某个不存在的状态"


# ============================================================ 退出码映射
@pytest.mark.parametrize("code,expect", [
    (0, "completed"),
    (1, "warned"),
    (2, "failed"),
    (-1, "failed"),
    (137, "failed"),
])
def test_退出码映射(code, expect):
    assert jobs.status_from_exit_code(code) == expect


def test_退出码映射的产物都是合法状态名():
    for code in (0, 1, 2, -1, 99):
        assert jobs.status_from_exit_code(code) in states.STATES


# ============================================================ 读盘归一
def _put(jobs_dir, job_id, **fields):
    """往状态库播一条任务记录（库里就是任务记录的唯一真相源）；目录按需由调用方建。"""
    state_store.put_job(state_store.db_path(), {"id": job_id, **fields})
    return jobs_dir / job_id


def test_读盘时把旧状态名归一(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path)
    _put(tmp_path, "old-1", status="done", period="202607")
    _put(tmp_path, "old-2", status="interrupted", period="202607")

    assert jobs.read_job("old-1")["status"] == "completed"
    assert jobs.read_job("old-2")["status"] == "failed"


def test_列表页也拿到归一后的状态(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path)
    _put(tmp_path, "old-1", status="warn", period="202607",
         created_at="2026-09-15 10:00:00")
    assert [j["status"] for j in jobs.list_jobs()] == ["warned"]


def test_坏记录不抛异常(tmp_path, monkeypatch):
    """库里坏行当作没有（与旧 `read_job` 读坏 json 同口径），不能把列表页炸掉。"""
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path)
    db = state_store.db_path()
    _put(tmp_path, "broken", status="completed", period="202607")
    with sqlite3.connect(str(db)) as con:
        con.execute("UPDATE jobs SET payload=? WHERE id=?", ("{ 这不是 json", "broken"))
    assert jobs.read_job("broken") is None


# ============================================================ 重启恢复
def test_重启把遗留running结为终态(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path)
    _put(tmp_path, "was-running", status="running", period="202607",
         started_at="2026-09-15 10:00:00", finished_at=None)
    _put(tmp_path, "already-done", status="done", period="202605",
         started_at="2026-09-14 10:00:00", finished_at="2026-09-14 10:00:20")

    jobs.recover_stale()

    recovered = jobs.read_job("was-running")
    assert jobs.is_terminal(recovered["status"]), "遗留任务必须落终态，不能挂在半途"
    assert recovered["status"] == states.FAILED
    assert recovered["recovered_from"] == "service_restart"
    assert recovered["finished_at"], "结掉的任务要有结束时间"

    # 已完成的任务不受影响（旧名归一后仍是 completed）
    assert jobs.read_job("already-done")["status"] == states.COMPLETED


def test_重启不碰非running的活跃态(tmp_path, monkeypatch):
    """`waiting_approval` 是活跃态但在等人工，重启不该把它判死。"""
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path)
    _put(tmp_path, "waiting", status="waiting_approval", period="202607")
    jobs.recover_stale()
    assert jobs.read_job("waiting")["status"] == "waiting_approval"


# ============================================================ 前端不再自造状态名
def test_每个状态都有badge样式():
    """加了状态却忘了配色，前端会退化成无样式的裸文字。"""
    css = (SERVER / "static" / "style.css").read_text(encoding="utf-8")
    for s in states.STATES:
        assert f".badge.{s}" in css, f"style.css 缺 .badge.{s} 的配色"


# ============================================================ 前端话术同源（跨栈 parity）
# 背景（2026-09-29）：老站任务页下线后，服务端渲染的 badge 不复存在；
# 「状态话术与状态机同源」这条保证改由**跨栈 parity 测试**守：
# 前端 `web/src/lib/status.ts`（GLOSSARY.md 定的唯一映射）必须与
# `src/agent/states.py` 集合、终态、逐字话术一致。漂移在这里当场红。
def _parse_ts_task_table():
    src = (REPO / "web" / "src" / "lib" / "status.ts").read_text(encoding="utf-8")
    states_block = re.search(r"export const TASK_STATES = \[(.*?)\] as const", src, re.S)
    terminal_block = re.search(
        r"export const TERMINAL_STATES: readonly TaskState\[\] = \[(.*?)\]", src, re.S)
    label_block = re.search(
        r"export const TASK_LABEL: Record<TaskState, string> = \{(.*?)\}", src, re.S)
    assert states_block and terminal_block and label_block, "status.ts 形状变了，同步本测试"
    task_states = re.findall(r"'([^']+)'", states_block.group(1))
    terminal = re.findall(r"'([^']+)'", terminal_block.group(1))
    labels = dict(re.findall(r"(\w+):\s*'([^']+)'", label_block.group(1)))
    return task_states, set(terminal), labels


def test_前端十态与后端状态机同源():
    task_states, _terminal, _labels = _parse_ts_task_table()
    assert tuple(task_states) == states.STATES, \
        "前端状态集合/顺序必须与 src/agent/states.py 一致"


def test_前端终态集合与后端同源():
    _states, terminal, _labels = _parse_ts_task_table()
    assert terminal == set(states.TERMINAL)


def test_前端话术与后端中文名逐字一致():
    _states, _terminal, labels = _parse_ts_task_table()
    diff = {k: (labels.get(k), states.LABELS.get(k))
            for k in states.LABELS if labels.get(k) != states.LABELS.get(k)}
    assert not diff, f"状态话术漂移（前端, 后端）：{diff}"


# ============================================================ 步骤级不受牵连
def test_进度文件路径失效时重定位到当前jobs目录(tmp_path, monkeypatch):
    """工作区搬过家（`…“AI+管理服务”\\wenheng` → `…\\wenheng`），历史记录里
    存的是旧绝对路径。不重定位的话，运行档案页会显示"没有进度事件"——
    读起来像这次运行没记录，其实文件一直在 `out/_jobs/<id>/` 下。"""
    monkeypatch.setattr(jobs.config, "JOBS_DIR", tmp_path)
    d = tmp_path / "j-old"
    d.mkdir()
    (d / "progress.jsonl").write_text('{"step":"parse","status":"done"}\n', encoding="utf-8")
    _put(tmp_path, "j-old", status="completed",
         progress="D://旧工作区//wenheng//out//_jobs//j-old//progress.jsonl",
         console="D://旧工作区//wenheng//out//_jobs//j-old//console.log")

    j = jobs.read_job("j-old")
    assert j["progress"] == str(d / "progress.jsonl"), "同名文件就在本职目录，应重定位"
    assert j["console"] == "D://旧工作区//wenheng//out//_jobs//j-old//console.log", \
        "文件确实不在（没建 console.log），不许假装存在——保持原值让上层显示为缺失"


def test_路径本来就对时不动它(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs.config, "JOBS_DIR", tmp_path)
    d = tmp_path / "j-new"
    d.mkdir()
    (d / "progress.jsonl").write_text("", encoding="utf-8")
    _put(tmp_path, "j-new", status="completed", progress=str(d / "progress.jsonl"))
    assert jobs.read_job("j-new")["progress"] == str(d / "progress.jsonl")


def test_反斜杠旧路径也能重定位(tmp_path, monkeypatch):
    """记录随部署包跨平台走：Windows 反斜杠路径在 Linux 上也必须认得出文件名。"""
    monkeypatch.setattr(jobs.config, "JOBS_DIR", tmp_path)
    d = tmp_path / "j-win"
    d.mkdir()
    (d / "console.log").write_text("ok\n", encoding="utf-8")
    _put(tmp_path, "j-win", status="completed",
         console="C:\\旧工作区\\wenheng\\out\\_jobs\\j-win\\console.log")
    assert jobs.read_job("j-win")["console"] == str(d / "console.log")


# ============================================================ 任务记录的路径写法（2026-10-22）
# 背景：`jobs.payload.input` 此前存绝对路径（`C:\\Users\\<用户名>\\Desktop\\…`）。
# 记录随部署包走，换台机器就不成立，还把开发机用户名打进了包——与
# `out/_acquisition/*.json` 上一票修的是同一类问题。
def test_旧记录的用户目录绝对路径能重定位(tmp_path, monkeypatch):
    """历史记录写的是 `C:\\Users\\<用户名>\\…\\out\\_jobs\\<id>\\…`：用户名与工作区都换过
    之后指针失效，但文件就在本职目录里——读出来必须还指得回真文件。"""
    monkeypatch.setattr(jobs.config, "JOBS_DIR", tmp_path)
    d = tmp_path / "j-user"
    d.mkdir()
    (d / "progress.jsonl").write_text('{"step": "parse"}\n', encoding="utf-8")
    old = r"C:\Users\someone\Desktop\首届高校图书馆\wenheng"
    _put(tmp_path, "j-user", status="completed",
         progress=old + r"\out\_jobs\j-user\progress.jsonl",
         console=old + r"\out\_jobs\j-user\console.log")

    j = jobs.read_job("j-user")
    assert j["progress"] == str(d / "progress.jsonl"), "同名文件在本职目录，应重定位"
    assert j["console"] == old + r"\out\_jobs\j-user\console.log", \
        "文件确实不在（没建 console.log），不许假装存在——保持原值让上层显示为缺失"


def test_仓库相对记录在部署机上能还原(tmp_path, monkeypatch):
    """新记录存仓库相对写法；读出来必须能直接用（档案页/SSE/日志包都当真实路径使）。"""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "out" / "_jobs")
    d = tmp_path / "out" / "_jobs" / "j-rel"
    d.mkdir(parents=True)
    (d / "progress.jsonl").write_text('{"step": "parse"}\n', encoding="utf-8")
    _put(tmp_path, "j-rel", status="completed",
         input="input/云大全学科排名、阈值动态检测表.xlsx",
         progress="out/_jobs/j-rel/progress.jsonl",
         console="out/_jobs/j-rel/console.log")

    j = jobs.read_job("j-rel")
    assert j["progress"] == str(d / "progress.jsonl")
    assert j["console"] == str(d / "console.log")
    assert j["input"] == str(tmp_path / "input" / "云大全学科排名、阈值动态检测表.xlsx")


def test_新建任务记录里不含盘符与用户名(tmp_path, monkeypatch):
    """写侧那条：新建任务的 `input`/`progress`/`console` 一律仓库相对。"""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "out" / "_jobs")
    monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", tmp_path / "out" / "_forecast_choices")
    monkeypatch.setattr(jobs, "_running", set())
    monkeypatch.setattr(jobs, "active_job", lambda: None)

    async def no_run(_job):
        return None

    monkeypatch.setattr(jobs, "_run", no_run)
    ledger = tmp_path / "input" / "云大全学科排名、阈值动态检测表.xlsx"
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b"x")

    async def create():
        return jobs.create_job("209903", ledger, "tester")

    job = asyncio.run(create())
    for key in jobs.PATH_KEYS:
        value = job[key]
        assert not display_path.is_absolute(value), f"{key} 仍存绝对路径：{value}"
        assert "Users" not in value, f"{key} 带上了本机用户目录：{value}"
    assert job["input"] == "input/云大全学科排名、阈值动态检测表.xlsx"

