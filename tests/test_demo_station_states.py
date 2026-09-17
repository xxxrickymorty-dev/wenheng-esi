# -*- coding: utf-8 -*-
"""演示站 ↔ Agent 状态机接线测试（2026-09-15）。

背景：状态口径此前有**两份**——`src/agent/states.py` 10 态（文档要求），
`server/jobs.py` 4 态旧名（done/warn/failed/interrupted）。
两份并存的结果是演示站说的和文档承诺的不是一回事：`done` 不等于 `Completed`，
`interrupted` 是文档里根本没有的状态。

这组测试钉住「只有一份口径」这件事。最狠的一条是 `TERMINAL is states.TERMINAL`
——要求**同一个对象**，不是内容相等；复制一份出来就会红。
"""
import json
import pathlib
import sys

import pytest

from agent import states

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = REPO / "server"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from server import config, jobs                                   # noqa: E402


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
    """`out/_jobs/` 下的历史 job.json 存的是旧名，不能因此被判成"还在跑"。"""
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
    assert jobs.status_label("escalated") == "已升级（待人工）"


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
    d = jobs_dir / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(
        json.dumps({"id": job_id, **fields}, ensure_ascii=False), encoding="utf-8")
    return d


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


def test_坏json不抛异常(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path)
    d = tmp_path / "broken"
    d.mkdir()
    (d / "job.json").write_text("{ 这不是 json", encoding="utf-8")
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


# ============================================================ 前端不另起名
def test_前端不再写死状态名单():
    js = (SERVER / "static" / "job.js").read_text(encoding="utf-8")
    assert "__STATUS_LABELS__" in js, "应从服务端注入状态中文名"
    assert "__TERMINAL__" in js, "应从服务端注入终态名单"
    assert "TERMINAL = ['done'" not in js, "前端仍在写死旧 4 态名单"
    assert "断言未过（已出稿待复核）" not in js, \
        "该文案来自已被裁决推翻的『断言未过仍出稿』，不该再出现在新品"


def test_前端保留旧名兜底():
    """老书签页 / 缓存页里可能还带着 done，前端要能自己认下来。"""
    js = (SERVER / "static" / "job.js").read_text(encoding="utf-8")
    assert "LEGACY" in js and "isTerminal" in js


@pytest.mark.parametrize("tpl", ["job.html", "index.html"])
def test_模板不再内联状态字典(tpl):
    text = (SERVER / "templates" / tpl).read_text(encoding="utf-8")
    assert "status_label(" in text, f"{tpl} 应调用服务端注入的 status_label"
    assert "已中断" not in text, f"{tpl} 仍有旧状态中文名"
    assert "'done':'完成'" not in text, f"{tpl} 仍内联状态字典"


def test_每个状态都有badge样式():
    """加了状态却忘了配色，前端会退化成无样式的裸文字。"""
    css = (SERVER / "static" / "style.css").read_text(encoding="utf-8")
    for s in states.STATES:
        assert f".badge.{s}" in css, f"style.css 缺 .badge.{s} 的配色"


# ============================================================ 步骤级不受牵连
def test_步骤进度类名没被误改成状态名():
    """job.js 里的 start/done/warn/failed 是**步骤进度**的 CSS 类，与任务状态机无关。"""
    js = (SERVER / "static" / "job.js").read_text(encoding="utf-8")
    assert "classList.remove('start', 'done', 'warn', 'failed')" in js, \
        "步骤级类名被改动会改坏五步进度的样式"


# ============================================================ 历史任务路径漂移（2026-09-17）
def test_进度文件路径失效时重定位到当前jobs目录(tmp_path, monkeypatch):
    """工作区搬过家（`…“AI+管理服务”\\wenheng` → `…\\wenheng`），历史 job.json 里
    存的是旧绝对路径。不重定位的话，运行档案页会显示"没有进度事件"——
    读起来像这次运行没记录，其实文件一直在 `out/_jobs/<id>/` 下。"""
    monkeypatch.setattr(jobs.config, "JOBS_DIR", tmp_path)
    d = tmp_path / "j-old"
    d.mkdir()
    (d / "progress.jsonl").write_text('{"step":"parse","status":"done"}\n', encoding="utf-8")
    (d / "job.json").write_text(json.dumps({
        "id": "j-old", "status": "completed",
        "progress": "D://旧工作区//wenheng//out//_jobs//j-old//progress.jsonl",
        "console": "D://旧工作区//wenheng//out//_jobs//j-old//console.log",
    }), encoding="utf-8")

    j = jobs.read_job("j-old")
    assert j["progress"] == str(d / "progress.jsonl"), "同名文件就在本职目录，应重定位"
    assert j["console"] == "D://旧工作区//wenheng//out//_jobs//j-old//console.log", \
        "文件确实不在（没建 console.log），不许假装存在——保持原值让上层显示为缺失"


def test_路径本来就对时不动它(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs.config, "JOBS_DIR", tmp_path)
    d = tmp_path / "j-new"
    d.mkdir()
    (d / "progress.jsonl").write_text("", encoding="utf-8")
    (d / "job.json").write_text(json.dumps({
        "id": "j-new", "status": "completed",
        "progress": str(d / "progress.jsonl"),
    }), encoding="utf-8")
    assert jobs.read_job("j-new")["progress"] == str(d / "progress.jsonl")
