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
    assert {"meta", "migrations", "approvals", "approval_history", "reviews"} <= _tables(db)
    health = state_store.health(db)
    assert health["schema_version"] == state_store.SCHEMA_VERSION
    assert health["degraded"] is False
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM migrations").fetchone()[0] == 1
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert not list(db.parent.glob("*.tmp-*"))                # 半截库不残留


def test_重复打开不会重跑迁移(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    state_store.put_approval(db, "202607", _rec())
    state_store.put_approval(db, "202607", _rec(note="第二次"))
    with sqlite3.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM migrations").fetchone()[0] == 1
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
    assert "写入失败" in error and "只读" in error               # 失败结果，不炸进程
