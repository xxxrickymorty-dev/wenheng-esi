# -*- coding: utf-8 -*-
"""系统状态库（SQLite）——签单与复核的运行期状态（ADR-0012 决定 3/6/7/8/11）。

- **边界（spec 写死）**：只装**控制面状态**（签单 / 复核）。数字一个不装（唯一事实源仍是母本
  xlsx），ESI / InCites 原始包不入库；**不存 status 列**——签单是否失效永远现场 glob + hash
  `out/<期次>/` 的产物（`server/approval.py`），库里缓存状态必然与文件不一致。
- **路径唯一口径**：`db_path()` → `out/_state/wenheng.sqlite`；`WENHENG_STATE_DB` 可覆盖
  （流水线子进程与 e2e 靠它指同一个库）。传 `out_dir` 时取它的**同级** `_state/`
  ——`out/<期次>` 解出 `out/_state`；测试把期次目录建在 tmp 下，库也就落在 tmp，互不污染。
  期次键＝期次**目录名**（`read(out_dir)` 只拿得到它），`payload.period` 另行原样保存。
- **并发**：`journal_mode=WAL` + `busy_timeout=5000`，每个写操作一个短事务；**不加跨进程锁**
  （沿用 uvicorn 单 worker + 单任务的既有约束）。真要多个写者，那是迁 pgsql 的信号。
- **迁移**：`migrations` 表 + 手写有序迁移函数。状态不可重建（重建＝丢审批），所以
  「版本不符就重建」在这里是错的；**库版本高于代码 → 只读降级**（`query_only` + 告警文案），
  不抛异常、不拒启动——拒启动会让回滚也不可能。写口在降级时返回/抛 `SchemaTooNew`，
  由调用方翻成「写入失败」的失败结果，而不是炸掉进程。
- 🔴 **不假装方言中立**：`WAL`、upsert、`AUTOINCREMENT` 都是 sqlite 专有。
  「迁 pgsql」的真实成本＝**重写本层 SQL**，不是换个连接串（ADR-0012 决定 5）。
"""
from __future__ import annotations

import contextlib
import datetime
import json
import logging
import os
import pathlib
import secrets
import sqlite3
import time

#: schema 版本（写进 meta；只增不减，见模块头的迁移说明）。
SCHEMA_VERSION = 1
#: 库文件名（`out/_state/` 下）。
DB_NAME = "wenheng.sqlite"
#: 覆盖库路径的环境变量（流水线子进程 / e2e 用）。
ENV_VAR = "WENHENG_STATE_DB"

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LOG = logging.getLogger("wenheng.state")

#: 脚手架（建库/连库都要，幂等）。逐条 execute——`executescript` 会先把在途事务 COMMIT 掉。
_SCAFFOLD = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS migrations ("
    " id TEXT PRIMARY KEY, applied_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')",
)

#: 001 的业务表。
_DDL_001 = (
    "CREATE TABLE IF NOT EXISTS approvals ("
    " period TEXT PRIMARY KEY, actor TEXT NOT NULL DEFAULT '',"
    " signed_at TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS approval_history ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL,"
    " ts TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,"
    " actor TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_approval_history_period"
    " ON approval_history(period, id)",
    "CREATE TABLE IF NOT EXISTS reviews ("
    " period TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
    " payload TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL DEFAULT '',"
    " PRIMARY KEY (period, key))",
)


class StoreError(RuntimeError):
    """状态库的显式失败（形状非法 / 迁移拒绝等）——调用方据此给失败结果，不猜。"""


class SchemaTooNew(StoreError):
    """库的 schema 版本高于本程序：已只读降级，写口拒绝。"""


def db_path(out_dir=None, *, out_root=None) -> pathlib.Path:
    """状态库路径唯一口径；环境变量优先，其次 `out_dir` 同级 `_state/`，最后仓库 `out/_state`。

    `out_root` 给「仓库根」这类已知根（工具 / 部署脚本）：解出 `<根>/out/_state/wenheng.sqlite`。
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return pathlib.Path(override)
    if out_root is not None:
        return pathlib.Path(out_root) / "out" / "_state" / DB_NAME
    if out_dir is not None:
        return pathlib.Path(out_dir).parent / "_state" / DB_NAME
    return _default_path()


def _default_path() -> pathlib.Path:
    return _ROOT / "out" / "_state" / DB_NAME


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(raw, default):
    """坏行读成默认值——库里从不写坏，防御而已。"""
    try:
        val = json.loads(raw or "")
    except (TypeError, ValueError):
        return default
    return val if isinstance(val, type(default)) else default


# --------------------------------------------------------------- 迁移
def _migrate_001(con) -> None:
    """001：建四张业务表（meta / migrations 是脚手架，见 `_scaffold`）。"""
    for stmt in _DDL_001:
        con.execute(stmt)


#: 有序迁移表（只增不改；id 一旦发出就不再动）。
MIGRATIONS = (
    {"id": "001-approvals-reviews", "note": "approvals / approval_history / reviews", "fn": _migrate_001},
)


def _scaffold(con) -> None:
    for stmt in _SCAFFOLD:
        con.execute(stmt)


def _read_version(con) -> int:
    try:
        row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.Error:
        return 0
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


@contextlib.contextmanager
def _txn(con):
    """一个短事务（显式 BEGIN/COMMIT；**别**用隐式事务，DDL 不会自己开事务）。"""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def _apply_migrations(con) -> tuple[bool, str]:
    """跑未应用的有序迁移。返回 `(degraded, note)`；版本高于代码时**只读降级**。"""
    db_version = _read_version(con)
    if db_version > SCHEMA_VERSION:
        note = (f"状态库 schema {db_version} 高于本程序 {SCHEMA_VERSION}：已降级为只读，"
                "签单与存疑暂不可写（请升级程序；回滚请先 tools/state_export.py 导出）")
        _LOG.warning(note)
        return True, note
    _scaffold(con)
    applied = {row[0] for row in con.execute("SELECT id FROM migrations")}
    pending = [m for m in MIGRATIONS if m["id"] not in applied]
    if pending:
        with _txn(con):
            for m in pending:
                m["fn"](con)
                con.execute("INSERT INTO migrations (id, applied_at, note) VALUES (?, ?, ?)",
                            (m["id"], _now(), m["note"]))
            con.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),))
    return False, ""


def _new_db(path: pathlib.Path) -> None:
    """原子建库：同目录唯一 tmp 里建好 schema，再一次 `os.replace`——不留半截表。"""
    try:
        from src import atomic_io                               # 仓根在 sys.path 上（server/tests）
    except ImportError:                                          # 只有 src/ 在 sys.path 上
        import atomic_io                                        # type: ignore[no-redef]

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = atomic_io.tmp_path(path)
    con = sqlite3.connect(str(tmp))
    try:
        _scaffold(con)
        with _txn(con):
            for m in MIGRATIONS:
                m["fn"](con)
                con.execute("INSERT INTO migrations (id, applied_at, note) VALUES (?, ?, ?)",
                            (m["id"], _now(), m["note"]))
            con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),))
    finally:
        con.close()
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # 另一个进程先建好了：库还是空的，用它的即可（Windows 上替换被占句柄会报这个）。
            if path.is_file():
                tmp.unlink(missing_ok=True)
                return
            if attempt == 4:
                raise
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def _connect(db_path, *, create: bool = False):
    """连库并跑迁移。返回 `(con, degraded, note)`；库不存在且 `create=False` → `KeyError`。"""
    path = pathlib.Path(db_path)
    if not path.is_file():
        if not create:
            raise KeyError("状态库不存在")
        _new_db(path)
    con = sqlite3.connect(str(path), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA journal_mode=WAL")
    degraded, note = _apply_migrations(con)
    if degraded:
        con.execute("PRAGMA query_only=ON")
    return con, degraded, note


@contextlib.contextmanager
def _open(db_path, *, create: bool = False):
    con, degraded, note = _connect(db_path, create=create)
    try:
        yield con, degraded, note
    finally:
        con.close()


@contextlib.contextmanager
def _write(db_path):
    """写口：降级时拒绝（不静默丢写）。"""
    with _open(db_path, create=True) as (con, degraded, note):
        if degraded:
            raise SchemaTooNew(note)
        with _txn(con):
            yield con


def health(db_path=None) -> dict:
    """库的健康状况：`{path, exists, schema_version, code_version, degraded, note}`。

    库不存在不算病（还没签过单）；高版本才是降级——告警文案就在这里，页面/工具直接展示。
    """
    target = pathlib.Path(db_path) if db_path is not None else _default_path()
    out = {"path": str(target), "exists": target.is_file(), "schema_version": 0,
           "code_version": SCHEMA_VERSION, "degraded": False, "note": ""}
    if not out["exists"]:
        return out
    try:
        with _open(target) as (con, degraded, note):
            out["schema_version"] = _read_version(con)
    except sqlite3.Error as exc:                       # 库损坏：如实报，不装作健康
        out["degraded"] = True
        out["note"] = f"状态库打不开：{exc}"
        return out
    out["degraded"] = degraded
    out["note"] = note
    return out


# --------------------------------------------------------------- 审批（签单）
def _history_rows(con, period) -> list[dict]:
    rows = con.execute(
        "SELECT payload FROM approval_history WHERE period=? ORDER BY id", (period,)).fetchall()
    return [_loads(r[0], {}) for r in rows]


def get_approval(db_path, period) -> dict | None:
    """读一期签单记录（payload + 历史，形状与旧 `approval.json` 一致）；没有 → None。

    库不存在 → None（读口不造文件）；降级时读不成也返回 None（告警在 `health()`）。
    """
    period = str(period)
    path = pathlib.Path(db_path)
    if not path.is_file():
        return None
    with _open(path) as (con, degraded, _note):
        try:
            row = con.execute(
                "SELECT payload FROM approvals WHERE period=?", (period,)).fetchone()
        except sqlite3.Error:
            if degraded:
                return None
            raise
        if row is None:
            return None
        rec = _loads(row[0], {})
        rec["history"] = _history_rows(con, period)
        return rec


def put_approval(db_path, period, record, *, history_entry=None) -> dict:
    """写一期签单记录（payload，忽略传入的 `history`）+ 追加一条历史；返回合并后的记录。

    调用方负责闸门与 `history` 的语义（`server/approval.py`）；本函数只管落库，事务里两笔同生共死。
    """
    period = str(period)
    if not isinstance(record, dict):
        raise StoreError("审批记录形状非法（顶层不是对象）")
    payload = {k: v for k, v in record.items() if k != "history"}
    with _write(db_path) as con:
        con.execute(
            "INSERT INTO approvals (period, actor, signed_at, payload) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(period) DO UPDATE SET actor=excluded.actor,"
            " signed_at=excluded.signed_at, payload=excluded.payload",
            (period, str(payload.get("actor") or ""), str(payload.get("signed_at") or ""),
             _dumps(payload)))
        if history_entry is not None:
            if not isinstance(history_entry, dict):
                raise StoreError("历史条目形状非法（不是对象）")
            con.execute(
                "INSERT INTO approval_history (period, ts, action, actor, payload)"
                " VALUES (?, ?, ?, ?, ?)",
                (period, str(history_entry.get("at") or ""),
                 str(history_entry.get("action") or ""),
                 str(history_entry.get("actor") or ""), _dumps(history_entry)))
        merged = dict(payload)
        merged["history"] = _history_rows(con, period)
    return merged


def replace_approval(db_path, period, record) -> None:
    """整期覆盖（e2e 还原用）：`record` 含 history；`None` = 删掉该期全部行。"""
    period = str(period)
    with _write(db_path) as con:
        con.execute("DELETE FROM approval_history WHERE period=?", (period,))
        con.execute("DELETE FROM approvals WHERE period=?", (period,))
        if record is None:
            return
        if not isinstance(record, dict):
            raise StoreError("审批记录形状非法（顶层不是对象）")
        payload = {k: v for k, v in record.items() if k != "history"}
        con.execute(
            "INSERT INTO approvals (period, actor, signed_at, payload) VALUES (?, ?, ?, ?)",
            (period, str(payload.get("actor") or ""), str(payload.get("signed_at") or ""),
             _dumps(payload)))
        for entry in record.get("history") or []:
            if not isinstance(entry, dict):
                raise StoreError("历史条目形状非法（不是对象）")
            con.execute(
                "INSERT INTO approval_history (period, ts, action, actor, payload)"
                " VALUES (?, ?, ?, ?, ?)",
                (period, str(entry.get("at") or ""), str(entry.get("action") or ""),
                 str(entry.get("actor") or ""), _dumps(entry)))


# --------------------------------------------------------------- 复核（存疑）
def get_reviews(db_path, period) -> dict:
    """一期的存疑标记：`{位置: {state, by, at}}`（与旧 `review.json` 同形）；无 → `{}`。"""
    period = str(period)
    path = pathlib.Path(db_path)
    if not path.is_file():
        return {}
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(
                "SELECT key, value, payload FROM reviews WHERE period=? ORDER BY key",
                (period,)).fetchall()
        except sqlite3.Error:
            if degraded:
                return {}
            raise
        out = {}
        for row in rows:
            item = _loads(row["payload"], {})
            item = {"state": row["value"], **item}
            out[row["key"]] = item
        return out


def set_review(db_path, period, key, payload, *, value="doubt", updated_at="") -> None:
    """写/覆盖一处的存疑（upsert）。"""
    period, key = str(period), str(key)
    if not key:
        raise StoreError("存疑位置不能为空")
    if not isinstance(payload, dict):
        raise StoreError("存疑形状非法（payload 不是对象）")
    with _write(db_path) as con:
        con.execute(
            "INSERT INTO reviews (period, key, value, payload, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(period, key) DO UPDATE SET value=excluded.value,"
            " payload=excluded.payload, updated_at=excluded.updated_at",
            (period, key, str(value), _dumps(payload), str(updated_at or _now())))


def clear_review(db_path, period, key) -> bool:
    """取消一处的存疑；有行删掉 → True，本来没有 → False。"""
    period, key = str(period), str(key)
    with _write(db_path) as con:
        cur = con.execute("DELETE FROM reviews WHERE period=? AND key=?", (period, key))
        return cur.rowcount > 0


def replace_reviews(db_path, period, data) -> None:
    """整期覆盖（e2e 还原用）：`{}` = 全清。"""
    period = str(period)
    if not isinstance(data, dict):
        raise StoreError("存疑集合形状非法（不是对象）")
    with _write(db_path) as con:
        con.execute("DELETE FROM reviews WHERE period=?", (period,))
        for key, item in data.items():
            if not isinstance(item, dict):
                raise StoreError(f"存疑条目形状非法：{key!r}")
            con.execute(
                "INSERT INTO reviews (period, key, value, payload, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (period, str(key), str(item.get("state") or "doubt"),
                 _dumps({k: v for k, v in item.items() if k != "state"}),
                 str(item.get("at") or "")))


# --------------------------------------------------------------- 期次清单（导出用）
def periods(db_path) -> list[str]:
    """库里有签单或存疑的期次（字典序，即时间序）；库不存在 → `[]`。"""
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(
                "SELECT period FROM approvals UNION SELECT period FROM reviews").fetchall()
        except sqlite3.Error:
            if degraded:
                return []
            raise
        return sorted({str(r[0]) for r in rows})


# --------------------------------------------------------------- 自查
def selftest(db_path) -> dict:                                    # pragma: no cover - 手工排障用
    """一行健康快照（工具/排障用，不进请求路径）。"""
    info = health(db_path)
    if info["exists"]:
        info["periods"] = periods(db_path)
    return info
