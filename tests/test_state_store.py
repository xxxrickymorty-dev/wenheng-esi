# -*- coding: utf-8 -*-
"""系统状态库（`src/state_store.py`，ADR-0012）：路径口径 / 迁移 / 签单与复核往返 / 降级。"""
import json
import pathlib
import sqlite3

import pytest

from server import approval
from src import state_store


def _rec(**extra):
    rec = {"signed": True, "actor": "rick", "signed_at": "2026-10-21 10:00:00",
           "note": "", "manual_ack": False, "snapshot": {}, "fingerprint": {},
           "revoked_at": ""}
    rec.update(extra)
    return rec


def _tables(db):
    with sqlite3.connect(str(db)) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ---------------------------------------------------------------- 路径口径
def test_db_path_从期次目录解出同级_state(tmp_path):
    out_dir = tmp_path / "out" / "202607"
    out_dir.mkdir(parents=True)
    assert state_store.db_path(out_dir) == tmp_path / "out" / "_state" / "wenheng.sqlite"


def test_db_path_环境变量优先(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "s.sqlite"
    monkeypatch.setenv(state_store.ENV_VAR, str(target))
    assert state_store.db_path(tmp_path / "out" / "202607") == target
    assert state_store.db_path(out_root=tmp_path) == target
    assert state_store.db_path() == target


def test_db_path_已知根解出仓库口径(tmp_path):
    assert state_store.db_path(out_root=tmp_path) == tmp_path / "out" / "_state" / "wenheng.sqlite"


# ---------------------------------------------------------------- 建库与迁移
def test_首次写时原子建库且带版本与迁移记录(tmp_path):
    db = tmp_path / "_state" / "wenheng.sqlite"
    assert state_store.get_approval(db, "202607") is None      # 读口不造文件
    assert not db.exists()

    state_store.put_approval(db, "202607", _rec())

    assert db.is_file()
    assert {"meta", "migrations", "approvals", "approval_history", "reviews",
            "jobs", "manual_inputs"} <= _tables(db)
    health = state_store.health(db)
    assert health["schema_version"] == state_store.SCHEMA_VERSION
    assert health["degraded"] is False
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM migrations").fetchone()[0] == \
            len(state_store.MIGRATIONS)
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert not list(db.parent.glob("*.tmp-*"))                # 半截库不残留


def test_重复打开不会重跑迁移(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.put_approval(db, "202607", _rec())
    state_store.put_approval(db, "202607", _rec(note="第二次"))
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM migrations").fetchone()[0] == \
            len(state_store.MIGRATIONS)
        assert con.execute("SELECT COUNT(*) FROM meta WHERE key='schema_version'").fetchone()[0] == 1


# ---------------------------------------------------------------- 签单
def test_签单记录往返且历史按序(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    first = state_store.put_approval(
        db, "202607", _rec(),
        history_entry={"action": "sign", "actor": "rick", "at": "t1", "manual_open": 0})
    assert first["history"] == [{"action": "sign", "actor": "rick", "at": "t1", "manual_open": 0}]

    second = state_store.put_approval(
        db, "202607", _rec(signed=False),
        history_entry={"action": "revoke", "actor": "rick", "at": "t2"})
    assert [h["action"] for h in second["history"]] == ["sign", "revoke"]
    assert state_store.get_approval(db, "202607")["signed"] is False
    # 结构化列与 payload 同源（actor / signed_at 供查询）
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT actor, signed_at FROM approvals").fetchone() == (
            "rick", "2026-10-21 10:00:00")


def test_replace_approval_覆盖与清空(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.put_approval(db, "202607", _rec(),
                             history_entry={"action": "sign", "at": "t1"})
    snapshot = state_store.get_approval(db, "202607")

    state_store.replace_approval(db, "202607", {"signed": True, "actor": "x",
                                                "history": [{"action": "sign", "at": "t9"}]})
    rec = state_store.get_approval(db, "202607")
    assert rec["actor"] == "x"
    assert rec["history"] == [{"action": "sign", "at": "t9"}]

    state_store.replace_approval(db, "202607", None)
    assert state_store.get_approval(db, "202607") is None
    assert snapshot is not None


def test_形状非法不落行(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.put_approval(db, "202607", _rec())
    with pytest.raises(state_store.StoreError):
        state_store.put_approval(db, "202607", ["not-a-dict"])
    assert state_store.get_approval(db, "202607")["actor"] == "rick"


# ---------------------------------------------------------------- 复核
def test_存疑增删与整期覆盖(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    assert state_store.get_reviews(db, "202607") == {}        # 无库 → 空，不造文件

    state_store.set_review(db, "202607", "正文/p1", {"by": "rick", "at": "t1"})
    state_store.set_review(db, "202607", "正文/p2", {"by": "rick", "at": "t2"})
    assert state_store.get_reviews(db, "202607") == {
        "正文/p1": {"state": "doubt", "by": "rick", "at": "t1"},
        "正文/p2": {"state": "doubt", "by": "rick", "at": "t2"},
    }

    assert state_store.clear_review(db, "202607", "正文/p1") is True
    assert state_store.clear_review(db, "202607", "不存在的") is False
    assert list(state_store.get_reviews(db, "202607")) == ["正文/p2"]

    state_store.replace_reviews(db, "202607", {})
    assert state_store.get_reviews(db, "202607") == {}
    assert state_store.periods(db) == []                      # 只有复核行，没有签单 → 不算期次
    state_store.put_approval(db, "202607", _rec())
    assert state_store.periods(db) == ["202607"]


# ---------------------------------------------------------------- 任务记录（第二批）
def _job(**extra):
    job = {"id": "20261021-101500-ab12", "period": "202607", "input": "input/x.xlsx",
           "actor": "rick", "backtest": False, "status": "running",
           "created_at": "2026-10-21 10:15:00", "started_at": "2026-10-21 10:15:00",
           "finished_at": None, "exit_code": None,
           "progress": "C:/旧工作区/out/_jobs/20261021-101500-ab12/progress.jsonl",
           "console": "C:/旧工作区/out/_jobs/20261021-101500-ab12/console.log"}
    job.update(extra)
    return job


def test_任务记录往返相等(tmp_path):
    """`payload` 必须能**无损**还原成原 `job.json` 字典（null、布尔、数值、嵌套 stats 都要扛住）。"""
    db = tmp_path / "wenheng.sqlite"
    job = _job(status="completed", exit_code=0, finished_at="2026-10-21 10:18:00",
               out_period="202607",
               stats={"assertions": {"total": 48, "fail": 0}, "missing": [],
                      "elapsed_sec": 96.5})
    state_store.put_job(db, job)
    assert state_store.get_job(db, job["id"]) == job


def test_任务记录覆盖写不新增行(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    job = _job()
    state_store.put_job(db, job)
    state_store.put_job(db, {**job, "status": "completed", "exit_code": 0})
    assert state_store.get_job(db, job["id"])["status"] == "completed"
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        # 提升列与 payload 同源（active_job 的查询只认这两列）
        assert con.execute("SELECT status, period FROM jobs").fetchone() == ("completed", "202607")


def test_任务列表按创建时间新到旧且可按期次与状态过滤(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.put_job(db, _job(id="a", created_at="2026-10-01 10:00:00", status="completed"))
    state_store.put_job(db, _job(id="b", created_at="2026-10-20 10:00:00", status="running",
                                 period="202609"))
    state_store.put_job(db, _job(id="c", created_at="2026-10-21 10:00:00", status="failed"))
    assert [j["id"] for j in state_store.list_jobs(db)] == ["c", "b", "a"]
    assert [j["id"] for j in state_store.list_jobs(db, limit=2)] == ["c", "b"]
    assert [j["id"] for j in state_store.list_jobs(db, period="202607")] == ["c", "a"]
    assert [j["id"] for j in state_store.list_jobs(db, statuses=("running", "pending"))] == ["b"]


def test_任务库不存在时读口不造文件(tmp_path):
    """导入 `server.app` 会跑 `recover_stale()`——它不能顺手把库建出来。"""
    db = tmp_path / "_state" / "wenheng.sqlite"
    assert state_store.get_job(db, "x") is None
    assert state_store.list_jobs(db) == []
    assert not db.exists()


def test_任务记录形状非法不落行(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    with pytest.raises(state_store.StoreError):
        state_store.put_job(db, ["not-a-dict"])
    with pytest.raises(state_store.StoreError):
        state_store.put_job(db, {"period": "202607"})     # 没有 id 就没有幂等键
    assert state_store.list_jobs(db) == []


def test_旧库升级到最新schema不丢已有签单(tmp_path):
    """手工造一个 001 时代的库 → 打开即补齐后续迁移；签单不动，迁移不重跑。"""
    db = tmp_path / "wenheng.sqlite"
    con = sqlite3.connect(str(db))
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL,"
                    " note TEXT NOT NULL DEFAULT '')")
        state_store._migrate_001(con)
        con.execute("INSERT INTO approvals (period, actor, signed_at, payload)"
                    " VALUES (?, ?, ?, ?)", ("202607", "rick", "t", json.dumps({"signed": True})))
        con.execute("INSERT INTO migrations (id, applied_at, note)"
                    " VALUES ('001-approvals-reviews', 't', '')")
        con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        con.commit()
    finally:
        con.close()

    assert state_store.get_approval(db, "202607")["signed"] is True
    assert state_store.get_job(db, "x") is None
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM migrations").fetchone()[0] == \
            len(state_store.MIGRATIONS)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "manual_inputs"} <= tables


def test_旧库002升级到003不丢前两批数据(tmp_path):
    """002 库（签单 / 存疑 / 任务都在）→ 打开即补 003；三批各行一条不少。"""
    db = tmp_path / "wenheng.sqlite"
    con = sqlite3.connect(str(db))
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL,"
                    " note TEXT NOT NULL DEFAULT '')")
        state_store._migrate_001(con)
        state_store._migrate_002(con)
        con.execute("INSERT INTO approvals (period, actor, signed_at, payload)"
                    " VALUES (?, ?, ?, ?)",
                    ("202607", "rick", "t", json.dumps({"signed": True}, ensure_ascii=False)))
        con.execute("INSERT INTO reviews (period, key, value, payload, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)", ("202607", "正文/p1", "doubt", "{}", "t"))
        con.execute("INSERT INTO jobs (id, status, period, created_at, updated_at, payload)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    ("job-1", "done", "202607", "t", "t", json.dumps({"id": "job-1"})))
        con.execute("INSERT INTO migrations (id, applied_at, note) VALUES ('001-approvals-reviews', 't', '')")
        con.execute("INSERT INTO migrations (id, applied_at, note) VALUES ('002-jobs', 't', '')")
        con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")
        con.commit()
    finally:
        con.close()

    assert state_store.get_fills(db, "202607") == {}             # 打开即补 003
    assert state_store.get_approval(db, "202607")["signed"] is True
    assert state_store.get_reviews(db, "202607")["正文/p1"]["state"] == "doubt"
    assert state_store.get_job(db, "job-1")["id"] == "job-1"
    assert state_store.health(db)["schema_version"] == state_store.SCHEMA_VERSION

    state_store.set_fill(db, "202607", "正文/p4::学科数",
                         {"value": "19", "by": "rick", "at": "t"})
    assert state_store.get_fills(db, "202607")["正文/p4::学科数"]["value"] == "19"


# ---------------------------------------------------------------- 人工填写（第三批）
def _fill(value="19", by="馆员", at="2026-10-21 11:00:00"):
    return {"value": value, "by": by, "at": at}


def test_填写往返形状与旧文件一致(tmp_path):
    """`get_fills` 必须原样还原旧 `manual_inputs.json` 的 `{value, by, at}`——不带 status。"""
    db = tmp_path / "wenheng.sqlite"
    assert state_store.get_fills(db, "202607") == {}          # 无库 → 空，不造文件
    assert not db.exists()

    state_store.replace_fills(db, "202607", {
        "正文/province_p::总数": _fill("54"),
        "正文/p4::学科数": _fill(),
    })
    got = state_store.get_fills(db, "202607")
    assert got == {"正文/province_p::总数": _fill("54"), "正文/p4::学科数": _fill()}
    # 键序＝写入序（导出逐字节可比的前提；JSON 顶层键序不是排过的）
    assert list(got) == ["正文/province_p::总数", "正文/p4::学科数"]
    # 三态不进读口：status 由 workbench 现场判（`_DDL_003`）
    assert set(got["正文/p4::学科数"]) == {"value", "by", "at"}


def test_填写覆盖写同一位置不新增行且查得到谁何时(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.set_fill(db, "202607", "正文/p4::学科数", _fill())
    state_store.set_fill(db, "202607", "正文/p4::学科数",
                         _fill("20", by="rick", at="2026-10-21 12:00:00"))

    assert state_store.get_fills(db, "202607") == {
        "正文/p4::学科数": {"value": "20", "by": "rick", "at": "2026-10-21 12:00:00"}}
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM manual_inputs").fetchone()[0] == 1
        # 提升列与 payload 同源：actor 即旧文件的 by；status 记落库时的态
        row = con.execute("SELECT value, status, actor, at FROM manual_inputs").fetchone()
        assert row == ("20", "pending", "rick", "2026-10-21 12:00:00")


def test_填写按period隔离(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.set_fill(db, "202607", "正文/p4::学科数", _fill())
    state_store.set_fill(db, "202609", "正文/p4::学科数", _fill("20"))

    assert state_store.get_fills(db, "202607")["正文/p4::学科数"]["value"] == "19"
    assert state_store.get_fills(db, "202609")["正文/p4::学科数"]["value"] == "20"
    assert state_store.get_fills(db, "202611") == {}
    assert state_store.periods(db) == ["202607", "202609"]


def test_填写状态只收三态且形状非法不落行(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    with pytest.raises(state_store.StoreError):
        state_store.set_fill(db, "202607", "正文/p4::学科数", _fill(), status="done")
    with pytest.raises(state_store.StoreError):
        state_store.set_fill(db, "202607", "", _fill())                    # 位置不能空
    with pytest.raises(state_store.StoreError):
        state_store.set_fill(db, "202607", "正文/p4::学科数", "19")         # 不是对象
    with pytest.raises(state_store.StoreError):
        state_store.replace_fills(db, "202607", {"正文/p4::学科数": "19"})
    assert state_store.get_fills(db, "202607") == {}


# ---------------------------------------------------------------- 降级
def test_库版本高于代码只读降级不抛异常(tmp_path, monkeypatch):
    db = tmp_path / "wenheng.sqlite"
    state_store.put_approval(db, "202607", _rec())
    with sqlite3.connect(str(db)) as con:
        con.execute("UPDATE meta SET value='99' WHERE key='schema_version'")

    health = state_store.health(db)
    assert health["schema_version"] == 99
    assert health["degraded"] is True
    assert "只读" in health["note"]

    with pytest.raises(state_store.SchemaTooNew):
        state_store.put_approval(db, "202607", _rec())
    assert state_store.get_approval(db, "202607") is not None   # 读仍可用（降级不是坏）

    monkeypatch.setenv(state_store.ENV_VAR, str(db))
    out_dir = tmp_path / "202607"
    out_dir.mkdir()
    ok, error = approval.sign(out_dir, "rick", {"counts": {}, "assertions": {}})
    assert ok is False
    # 失败结果，不炸进程；给的是人话（库版本/迁移这些词只进日志）
    assert error == state_store.READONLY_NOTE
    assert "只读" in error and "schema" not in error
