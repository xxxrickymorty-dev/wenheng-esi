# -*- coding: utf-8 -*-
"""会话库（票 11）· S1 单测：建/追/读/清 + 用户隔离 + 上限 + 形状非法。

一律注入 tmp 库（`tmp_path`），不碰真 `out/_sessions/`；形状非法不猜（ValueError/KeyError/PermissionError）。
"""
from __future__ import annotations

import pathlib
import re
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                    # noqa: E402

import session_store as store                                    # noqa: E402


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "sessions.sqlite"


# ============================================================ 1. 建 / 追 / 读
def test_建会话_形状与回读(db):
    sid = store.create(db, "admin")
    assert re.fullmatch(r"s-\d{8}-[0-9a-f]{8}", sid), "id 形如 s-YYYYMMDD-8hex"
    got = store.load(db, sid, "admin")
    assert got["id"] == sid and got["user"] == "admin"
    assert got["turns"] == [] and got["slots"] == {} and got["title"] == ""
    assert got["created"] and got["updated"]


def test_追加回读_顺序与形状(db):
    sid = store.create(db, "admin")
    assert store.append(db, sid, "me", "  帮我做 9 月的报告  ") == 1
    assert store.append(db, sid, "wh", "我按「数据截至 2026-09」理解 → 202609") == 2
    got = store.load(db, sid, "admin")
    assert [t["who"] for t in got["turns"]] == ["me", "wh"]
    assert got["turns"][0]["text"] == "帮我做 9 月的报告", "首尾空白收口"
    assert all(t["ts"] for t in got["turns"])
    assert got["title"] == "帮我做 9 月的报告", "标题＝第一句用户话（不编）"


def test_标题只认第一句_超长截断(db):
    sid = store.create(db, "admin")
    store.append(db, sid, "me", "帮我" * 30)
    store.append(db, sid, "me", "后来又说了别的")
    title = store.load(db, sid, "admin")["title"]
    assert len(title) == 40 and title.endswith("…")
    assert title == store.load(db, sid, "admin")["title"], "后续用户话不改标题"


def test_槽位整存整取(db):
    sid = store.create(db, "admin")
    store.save_slots(db, sid, {"period": "202607", "intent": "出报告"})
    assert store.load(db, sid, "admin")["slots"] == {"period": "202607", "intent": "出报告"}
    store.save_slots(db, sid, {"period": "", "intent": ""}, user="admin")
    assert store.load(db, sid, "admin")["slots"] == {"period": "", "intent": ""}


# ============================================================ 2. 用户隔离
def test_用户隔离_读清追加都要本人(db):
    sid = store.create(db, "admin")
    store.append(db, sid, "me", "你好")
    with pytest.raises(PermissionError):
        store.load(db, sid, "demo")
    with pytest.raises(PermissionError):
        store.drop(db, sid, "demo")
    with pytest.raises(PermissionError):
        store.append(db, sid, "me", "偷写一句", user="demo")
    with pytest.raises(PermissionError):
        store.save_slots(db, sid, {"period": "202607"}, user="demo")
    assert [t["text"] for t in store.load(db, sid, "admin")["turns"]] == ["你好"], "本人不受影响"


def test_清单只列本人_最近在前(db):
    a = store.create(db, "admin")
    b = store.create(db, "demo")
    store.append(db, a, "me", "甲")
    assert [s["id"] for s in store.list_sessions(db, "admin")] == [a]
    demo_list = store.list_sessions(db, "demo")
    assert [s["id"] for s in demo_list] == [b] and demo_list[0]["n_turns"] == 0


# ============================================================ 3. 上限（按用户保留最近 20）
def test_保留最近20个_超出删最旧含turns(db):
    ids = [store.create(db, "admin") for _ in range(store.KEEP_PER_USER)]
    store.append(db, ids[0], "me", "要被清掉的一轮")
    # 把前 5 个的 updated 固定成旧值（消除同秒歧义），再建 5 个新的
    con = sqlite3.connect(db)
    try:
        con.executemany("UPDATE sessions SET updated=? WHERE id=?",
                        [(f"2000-01-0{i + 1} 00:00:00", ids[i]) for i in range(5)])
        con.commit()
    finally:
        con.close()
    fresh = [store.create(db, "admin") for _ in range(5)]
    alive = {s["id"] for s in store.list_sessions(db, "admin")}
    assert alive == set(ids[5:]) | set(fresh), "删最旧 5 个（留最近 20）"
    with pytest.raises(KeyError):
        store.load(db, ids[0], "admin")
    con = sqlite3.connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM turns WHERE session_id=?",
                        (ids[0],)).fetchone()[0]
    finally:
        con.close()
    assert n == 0, "删会话连它的回合一起清"


def test_上限按用户各算(db):
    d = store.create(db, "demo")
    for _ in range(store.KEEP_PER_USER + 1):
        store.create(db, "admin")
    assert store.load(db, d, "demo")["id"] == d, "demo 的会话不受 admin 清理影响"


# ============================================================ 4. 删除 / 缺库 / 形状非法
def test_删除_本人可删_重复删为False(db):
    sid = store.create(db, "admin")
    store.append(db, sid, "me", "你好")
    assert store.drop(db, sid, "admin") is True
    with pytest.raises(KeyError):
        store.load(db, sid, "admin")
    assert store.drop(db, sid, "admin") is False


def test_缺库_读口不造文件(db):
    assert not db.exists()
    assert store.list_sessions(db, "admin") == []
    with pytest.raises(KeyError):
        store.load(db, "s-20260101-01234567", "admin")
    assert not db.exists(), "只读不建库（不给错路径造文件）"


def test_形状非法一律拒绝(db):
    with pytest.raises(ValueError):
        store.create(db, "   ")
    sid = store.create(db, "admin")
    with pytest.raises(ValueError):
        store.load(db, "not-a-session", "admin")
    with pytest.raises(KeyError):
        store.load(db, "s-20260101-01234567", "admin"), "形状对但不存在"
    with pytest.raises(ValueError):
        store.append(db, sid, "sys", "谁")
    with pytest.raises(ValueError):
        store.append(db, sid, "me", "   ")
    with pytest.raises(ValueError):
        store.save_slots(db, sid, ["period"])
    with pytest.raises(KeyError):
        store.append(db, "s-20260101-01234567", "me", "你好")
    with pytest.raises(ValueError):
        store.list_sessions(db, "")


def test_slots_json坏行_读成空不炸(db):
    sid = store.create(db, "admin")
    con = sqlite3.connect(db)
    try:
        con.execute("UPDATE sessions SET slots_json='[1,2]' WHERE id=?", (sid,))
        con.commit()
    finally:
        con.close()
    assert store.load(db, sid, "admin")["slots"] == {}
