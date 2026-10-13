# -*- coding: utf-8 -*-
"""会话库（SQLite）——对话前门的服务端会话持久化（2026-10-13 票 11）。

- 边界（spec 写死）：只存会话（对话文本/槽位/时间/用户）；**不存任何台账数值、不进数据路径**；
- 路径唯一口径：`store_path(repo_root)` → `<repo>/out/_sessions/sessions.sqlite`（stdlib、原子、备份＝复制）；
- 函数一律注入 `db_path`（测试用 tmp）；`load/list/drop` 校验归属——他人读不到；
  按用户保留最近 `KEEP_PER_USER` 个（超出删最旧，含其 turns）；
- 形状非法（id / who / text / slots）一律 `ValueError`，不猜；id 形如 `s-YYYYMMDD-8hex`（secrets 生成）。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import secrets
import sqlite3

#: schema 版本（写入 meta，便于将来无痛升级）。
SCHEMA_VERSION = 1
#: 每用户保留的会话数（默认；超出删最旧，含其 turns）。
KEEP_PER_USER = 20
#: 会话 id 形状：`s-YYYYMMDD-8hex`（与前端 URL 参数 `s` 的校验同口径）。
_ID_RE = re.compile(r"^s-\d{8}-[0-9a-f]{8}$")
#: 回合说话人：me＝用户 / wh＝文衡（对话层没有 sys 回合）。
_WHO = ("me", "wh")

_DDL = (
    "CREATE TABLE IF NOT EXISTS sessions ("
    " id TEXT PRIMARY KEY, user TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',"
    " slots_json TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL, updated TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS turns ("
    " session_id TEXT NOT NULL, seq INTEGER NOT NULL, who TEXT NOT NULL,"
    " text TEXT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY (session_id, seq));"
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);"
)


def store_path(repo_root) -> pathlib.Path:
    """会话库路径唯一口径：`<repo>/out/_sessions/sessions.sqlite`。"""
    return pathlib.Path(repo_root) / "out" / "_sessions" / "sessions.sqlite"


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path, *, create=False):
    """连库（顺带建表/写 schema 版本）。`create=False` 时库不存在 → KeyError（读口不造文件）。"""
    db_path = pathlib.Path(db_path)
    if not db_path.is_file() and not create:
        raise KeyError("会话库不存在")
    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    con.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),))
    return con


def _check_id(session_id) -> str:
    sid = str(session_id or "").strip()
    if not _ID_RE.fullmatch(sid):
        raise ValueError(f"会话 id 形状非法：{session_id!r}")
    return sid


def _check_user(user) -> str:
    u = str(user or "").strip()
    if not u:
        raise ValueError("user 不能为空")
    return u


def _owner(con, session_id, user=None):
    """取会话行并校验归属：不存在 KeyError、非本人 PermissionError。"""
    row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise KeyError("会话不存在")
    if user is not None and row["user"] != _check_user(user):
        raise PermissionError("会话不属于当前用户")
    return row


def _parse_slots(raw) -> dict:
    """slots_json 坏行读成空——库里从不写坏，防御而已。"""
    try:
        slots = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return slots if isinstance(slots, dict) else {}


def _title(text: str) -> str:
    """标题＝第一句用户话（空白折叠、40 字截断）——与前端 `conversationTitle` 同口径。"""
    t = " ".join(text.split())
    return t[:39] + "…" if len(t) > 40 else t


def _prune(con, user: str) -> int:
    """按用户保留最近 KEEP_PER_USER 个：超出删最旧（含其 turns）。返回删了几个。"""
    rows = con.execute(
        "SELECT id FROM sessions WHERE user=? ORDER BY updated DESC, rowid DESC LIMIT -1 OFFSET ?",
        (user, KEEP_PER_USER)).fetchall()
    for (sid,) in rows:
        con.execute("DELETE FROM turns WHERE session_id=?", (sid,))
        con.execute("DELETE FROM sessions WHERE id=?", (sid,))
    return len(rows)


def create(db_path, user) -> str:
    """建新会话（归属 user），返回 id；超出保留数删最旧（含其 turns）。"""
    user = _check_user(user)
    now_dt = datetime.datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    session_id = f"s-{now_dt:%Y%m%d}-{secrets.token_hex(4)}"
    con = _connect(db_path, create=True)
    try:
        con.execute(
            "INSERT INTO sessions (id, user, title, slots_json, created, updated) "
            "VALUES (?, ?, '', '{}', ?, ?)", (session_id, user, now, now))
        _prune(con, user)
        con.commit()
    finally:
        con.close()
    return session_id


def append(db_path, session_id, who, text, *, user=None) -> int:
    """追加一回合（who: me/wh），返回 seq（从 1 起）。

    会话不存在 KeyError、非本人 PermissionError、形状非法 ValueError；标题取第一句用户话。
    """
    sid = _check_id(session_id)
    who = str(who or "").strip()
    if who not in _WHO:
        raise ValueError(f"who 形状非法：{who!r}")
    body = str(text or "").strip()
    if not body:
        raise ValueError("text 不能为空")
    con = _connect(db_path)
    try:
        row = _owner(con, sid, user)
        seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE session_id=?",
                          (sid,)).fetchone()[0]
        now = _now()
        con.execute("INSERT INTO turns (session_id, seq, who, text, ts) VALUES (?, ?, ?, ?, ?)",
                    (sid, seq, who, body, now))
        if who == "me" and not (row["title"] or ""):
            con.execute("UPDATE sessions SET title=?, updated=? WHERE id=?",
                        (_title(body), now, sid))
        else:
            con.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))
        con.commit()
        return seq
    finally:
        con.close()


def load(db_path, session_id, user) -> dict:
    """读一个会话（仅 owner）：`{id, user, title, slots, turns, created, updated}`。

    turns＝`[{who, text, ts}]` 按 seq 升序；不存在 KeyError、非本人 PermissionError、形状非法 ValueError。
    """
    sid = _check_id(session_id)
    user = _check_user(user)
    try:
        con = _connect(db_path)
    except KeyError:
        raise KeyError("会话不存在") from None
    try:
        row = _owner(con, sid, user)
        turns = [{"who": r["who"], "text": r["text"], "ts": r["ts"]} for r in con.execute(
            "SELECT who, text, ts FROM turns WHERE session_id=? ORDER BY seq", (sid,))]
        return {"id": sid, "user": row["user"], "title": row["title"],
                "slots": _parse_slots(row["slots_json"]), "turns": turns,
                "created": row["created"], "updated": row["updated"]}
    finally:
        con.close()


def save_slots(db_path, session_id, slots, *, user=None) -> None:
    """整存槽位（`{period,intent}`）：非 dict ValueError；不存在 KeyError、非本人 PermissionError。"""
    sid = _check_id(session_id)
    if not isinstance(slots, dict):
        raise ValueError("slots 必须是对象（dict）")
    try:
        payload = json.dumps({str(k): str(v) for k, v in slots.items()}, ensure_ascii=False)
    except TypeError as exc:
        raise ValueError(f"slots 形状非法：{exc}") from exc
    con = _connect(db_path)
    try:
        _owner(con, sid, user)
        con.execute("UPDATE sessions SET slots_json=?, updated=? WHERE id=?",
                    (payload, _now(), sid))
        con.commit()
    finally:
        con.close()


def list_sessions(db_path, user) -> list[dict]:
    """某用户的会话清单（最近在前）：`[{id, title, slots, n_turns, created, updated}]`。"""
    user = _check_user(user)
    db_path = pathlib.Path(db_path)
    if not db_path.is_file():
        return []
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT s.id, s.title, s.slots_json, s.created, s.updated,"
            " (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) AS n_turns"
            " FROM sessions s WHERE s.user=? ORDER BY s.updated DESC, s.rowid DESC",
            (user,)).fetchall()
        return [{"id": r["id"], "title": r["title"], "slots": _parse_slots(r["slots_json"]),
                 "n_turns": int(r["n_turns"]), "created": r["created"], "updated": r["updated"]}
                for r in rows]
    finally:
        con.close()


def drop(db_path, session_id, user) -> bool:
    """删会话（含其 turns）；仅 owner。删了 True、不存在 False、非本人 PermissionError。"""
    sid = _check_id(session_id)
    user = _check_user(user)
    db_path = pathlib.Path(db_path)
    if not db_path.is_file():
        return False
    con = _connect(db_path)
    try:
        row = con.execute("SELECT user FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            return False
        if row["user"] != user:
            raise PermissionError("会话不属于当前用户")
        con.execute("DELETE FROM turns WHERE session_id=?", (sid,))
        con.execute("DELETE FROM sessions WHERE id=?", (sid,))
        con.commit()
        return True
    finally:
        con.close()
