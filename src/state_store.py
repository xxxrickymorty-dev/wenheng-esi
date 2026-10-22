# -*- coding: utf-8 -*-
"""系统状态库（SQLite）——签单 / 复核 / 任务记录 / 人工填写（ADR-0012 决定 3/6/7/8/11）。

- **边界（spec 写死）**：只装**控制面状态**（签单 / 复核 / 任务记录 / 人工填写）与**数据来源清单**
  （004：`../数据与复现/` 下每个文件的路径 / 大小 / 修改时间 / 指纹）。数字一个不装
  （唯一事实源仍是母本 xlsx），ESI / InCites **原始文件**不入库（只入清单，ADR-0012 决定 2）。
- **签单不存 status 列**——签单是否失效永远现场 glob + hash `out/<期次>/` 的产物
  （`server/approval.py`），库里缓存状态必然与文件不一致。
  **任务记录反过来**：`jobs.status` 是**事实本身**（跑到哪一步、谁跑的），没有第二个真相源
  要跟它比对，所以它既在 `payload` 里、又提升成列供 `active_job()` 一次查到
  （「一次只跑一期」不再扫目录）。
- **人工填写（003）**：一行一处（`period, slot`），详见 `_DDL_003` 的注释——`status` **不做真相**，
  三态仍由 `server/workbench.py::_fill_state` 现场看产物重算（与签单同理）。
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
SCHEMA_VERSION = 4
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

#: 002 的业务表：任务记录（`out/_jobs/<id>/job.json` 的唯一真相源）。
#: `payload` ＝ 原 `job.json` 的**完整字典**（往返相等，见 tests/test_state_store.py）；
#: `status / period / created_at` 只是为查询提升出来的列，`updated_at` 记最后一次落库时间
#: （不写进 payload，免得把「写库时刻」混进任务记录本身）。
_DDL_002 = (
    "CREATE TABLE IF NOT EXISTS jobs ("
    " id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT '',"
    " period TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '',"
    " updated_at TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_period ON jobs(period, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
)


#: 003 的业务表：人工填写（`out/<期次>/manual_inputs.json` 的唯一真相源）。
#: **一行一处**（`位置::标记文字`），不是一期一行——要能回答「谁在什么时候填的哪一处」。
#: `payload` ＝ 旧文件里那一项的原样字典（`{value, by, at}`；往返相等、导出逐字节可比）；
#: `value / actor / at` 是为查询与审计提升的列（`actor` 即旧文件的 `by`）。
#: 🔴 `status` 只记**落库那一刻**的三态（`pending / applied / orphan`），**不是真相**：
#: 三态由 `workbench._fill_state` 每次现场看 `red_slots.json` / 生成稿重算，
#: 读口（`get_fills`）不返回它，页面判定也不读它——同一个理由见 ADR-0012 决定 6。
#: 写入口只可能知道「刚保存、还没重出」这一档，所以 `save_fill` 写 `pending`；
#: 导入时旧文件没有这一列，同样记 `pending`（＝未经本次会话确认写进报告）。
#: 排序靠 rowid（表是普通 rowid 表，`ON CONFLICT` 不改 rowid）——旧文件的键序就是写入序，
#: 导出要逐字节相同就不能按 slot 字典序重排。
_DDL_003 = (
    "CREATE TABLE IF NOT EXISTS manual_inputs ("
    " period TEXT NOT NULL, slot TEXT NOT NULL,"
    " value TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',"
    " actor TEXT NOT NULL DEFAULT '', at TEXT NOT NULL DEFAULT '',"
    " payload TEXT NOT NULL, PRIMARY KEY (period, slot))",
)


#: 004 的业务表：**数据来源清单**（`../数据与复现/` 下每个文件的路径 / 大小 / 修改时间 / 指纹）。
#: 🔴 只装清单，**不装原始文件**（ADR-0012 决定 2）：原始包原地不动，库只有几十 KB。
#: `kind` ∈ `esi` / `incites`；`scope`＝ESI 期次目录名或 InCites 快照目录名
#: （直接躺在 kind 根下的散件记 `_root`，见 `tools/sources_index.py`）；
#: `rel_path` 相对 `../数据与复现/`。`sha256` 空串＝**只有元数据**（还没算过指纹），
#: 不是「没有这个文件」。`size` / `mtime_ns` 一起判「文件动过没有」：两项都没变时
#: `tools/sources_index.py --hash` 跳过重算（InCites 9 GB 不可能每次全量重算）。
#: `payload` 是保留位（将来深校验结论），当前写 `{}`。
#: 与 `inventory.py`（件级盘点）分工：这里判「文件是不是原来那一份」，那里判「件在不在」。
_DDL_004 = (
    "CREATE TABLE IF NOT EXISTS sources ("
    " kind TEXT NOT NULL, scope TEXT NOT NULL, rel_path TEXT NOT NULL,"
    " size INTEGER NOT NULL DEFAULT 0, mtime_ns INTEGER NOT NULL DEFAULT 0,"
    " sha256 TEXT NOT NULL DEFAULT '', scanned_at TEXT NOT NULL DEFAULT '',"
    " payload TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (kind, scope, rel_path))",
    "CREATE INDEX IF NOT EXISTS idx_sources_scope ON sources(kind, scope)",
)


class StoreError(RuntimeError):
    """状态库的显式失败（形状非法 / 迁移拒绝等）——调用方据此给失败结果，不猜。"""


class SchemaTooNew(StoreError):
    """库的 schema 版本高于本程序：已只读降级，写口拒绝。"""


#: 写口可能抛的异常（调用方统一 `except state_store.WRITE_ERRORS`，别各写一份）。
WRITE_ERRORS = (OSError, sqlite3.Error, StoreError)

#: 写库失败时**回给馆员的整句**（技术原文只进日志、不下发——ADR-0012 决定 7）。
#: 一句覆盖签单 / 撤回签单 / 标记存疑 / 在线填写：馆员只需要知道「这次没生效」和「找谁」，
#: 不需要库版本、迁移、导出工具这些字眼（看到 `tools/state_export.py` 会被引去乱执行）。
READONLY_NOTE = ("保存失败：本机数据存储版本比程序新，已进入只读模式，请联系管理员升级程序。"
                 "这次操作没有生效，你的改动没有被保存。")
WRITE_FAILED_NOTE = ("保存失败：本机数据存储现在写不进去，请联系管理员处理。"
                     "这次操作没有生效，你的改动没有被保存。")


def write_error_note(exc, *, action="保存") -> str:
    """把写库失败翻成馆员能懂的一句；**技术原文写进日志**（日志才是排障入口）。

    降级（`SchemaTooNew`）与其它写失败分开说：前者的下一步是升级程序，后者是找管理员看存储；
    两者都要说清「这次没生效」，否则馆员会以为已经存上了（这句是这条票的重点）。
    """
    note = READONLY_NOTE if isinstance(exc, SchemaTooNew) else WRITE_FAILED_NOTE
    _LOG.warning("状态库写入失败（%s）：%s: %s", action, type(exc).__name__, exc)
    return note


def is_write_failure_note(message) -> bool:
    """这句话是不是 `write_error_note()` 出的（路由据此不再追加「闸门」之类的提示）。"""
    return str(message) in (READONLY_NOTE, WRITE_FAILED_NOTE)


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


def _text(val) -> str:
    """提升列一律存字符串（`None` → 空串；数字等原样转字面量，别丢 `0`）。"""
    return "" if val is None else str(val)


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


def _migrate_002(con) -> None:
    """002：建任务记录表（`job.json` 入库；第二批的期次产物仍未做）。"""
    for stmt in _DDL_002:
        con.execute(stmt)


def _migrate_003(con) -> None:
    """003：建人工填写表（`manual_inputs.json` 入库；一期一行 → 一行一处）。"""
    for stmt in _DDL_003:
        con.execute(stmt)


def _migrate_004(con) -> None:
    """004：建数据来源清单表（文件级路径 / 大小 / 修改时间 / 指纹；原始文件不入库）。"""
    for stmt in _DDL_004:
        con.execute(stmt)


#: 有序迁移表（只增不改；id 一旦发出就不再动）。
MIGRATIONS = (
    {"id": "001-approvals-reviews", "note": "approvals / approval_history / reviews", "fn": _migrate_001},
    {"id": "002-jobs", "note": "jobs（原 out/_jobs/<id>/job.json）", "fn": _migrate_002},
    {"id": "003-manual-inputs", "note": "manual_inputs（原 out/<期次>/manual_inputs.json）",
     "fn": _migrate_003},
    {"id": "004-sources", "note": "sources（../数据与复现/ 的文件级清单与指纹）", "fn": _migrate_004},
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
                "签单、存疑与任务记录暂不可写（请升级程序；回滚请先 tools/state_export.py 导出）")
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


def list_history(db_path, period) -> list[dict]:
    """一期的审批历史（**带库内 id**，按 id 序）——审计 / 清理工具用。

    与 `get_approval()['history']` 的区别：那个是 `approval.json` 的形状（无 id），供前端与导出；
    这个要能指名删哪一行，所以把 `id` 一起给出来，`payload` 保持原样字典。
    库不存在 → `[]`（读口不造文件）。
    """
    period = str(period)
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(
                "SELECT id, ts, action, actor, payload FROM approval_history"
                " WHERE period=? ORDER BY id", (period,)).fetchall()
        except sqlite3.Error:
            if degraded:
                return []
            raise
    return [{"id": int(row["id"]), "ts": row["ts"], "action": row["action"],
             "actor": row["actor"], "payload": _loads(row["payload"], {})} for row in rows]


def get_history(db_path, period) -> list[dict]:
    """一期的审批历史，**`approval.json` 的形状**（只有 payload，不带库内 id）；按写入序。

    给「这一期已经没有签单行、只剩历史」的读口用（`server/approval.py::read()`）：
    撤回是**保留历史**的，所以历史比签单行活得久；未签不等于没发生过事。
    与 `list_history()` 的差别只在形状——那个带 id 给审计/清理指名删行。
    库不存在 → `[]`（读口不造文件）。
    """
    period = str(period)
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(
                "SELECT payload FROM approval_history WHERE period=? ORDER BY id",
                (period,)).fetchall()
        except sqlite3.Error:
            if degraded:
                return []
            raise
    return [_loads(row[0], {}) for row in rows]


def delete_history(db_path, period, ids) -> int:
    """按期次**指名**删历史行（清理工具用）；返回实际删掉的条数。

    只删 `ids` 里的行、且必须属于 `period`——防「删错期次」这类不可恢复的失误。
    """
    period = str(period)
    wanted = [int(i) for i in ids]
    if not wanted:
        return 0
    marks = ",".join("?" for _ in wanted)
    with _write(db_path) as con:
        cur = con.execute(
            f"DELETE FROM approval_history WHERE period=? AND id IN ({marks})",
            [period, *wanted])
        return cur.rowcount


def set_history_payload(db_path, period, payloads) -> int:
    """按 id **改写**历史行的 `payload`（清理工具用：只改自由文本，不动审计骨架）。

    `payloads` ＝ `{id: payload}`（整份字典，键序原样保留）。**只写 `payload` 一列**——
    提升列 `ts / action / actor` 与行本身都不动，删行更是本函数不做的事：
    审计流水宁可留一条改了批注的记录，也不能少一行（少一行＝改审计）。
    `period` 一起进 WHERE，防「改错期次」这类不可恢复的失误；返回实际改到的行数。
    """
    period = str(period)
    items = [(int(hid), payload) for hid, payload in (payloads or {}).items()]
    if not items:
        return 0
    changed = 0
    with _write(db_path) as con:
        for hid, payload in items:
            if not isinstance(payload, dict):
                raise StoreError("历史条目形状非法（payload 不是对象）")
            cur = con.execute(
                "UPDATE approval_history SET payload=? WHERE period=? AND id=?",
                (_dumps(payload), period, hid))
            changed += cur.rowcount
    return changed


def delete_approval(db_path, period) -> bool:
    """删掉一期的**当前签单行**（历史不动；e2e 残留清理用）；有行 → True。"""
    period = str(period)
    with _write(db_path) as con:
        cur = con.execute("DELETE FROM approvals WHERE period=?", (period,))
        return cur.rowcount > 0


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


# --------------------------------------------------------------- 任务记录
def get_job(db_path, job_id) -> dict | None:
    """读一条任务记录（原 `job.json` 的字典，原样）；没有 / 坏行 → None。

    库不存在 → None（读口不造文件，导入 app 时的 `recover_stale()` 不会顺手建库）。
    """
    path = pathlib.Path(db_path)
    if not path.is_file():
        return None
    with _open(path) as (con, degraded, _note):
        try:
            row = con.execute(
                "SELECT payload FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        except sqlite3.Error:
            if degraded:
                return None
            raise
        if row is None:
            return None
        try:
            rec = json.loads(row[0])
        except (TypeError, ValueError):
            return None                       # 坏行当作没有：与旧 read_job 的坏 json 同口径
        return rec if isinstance(rec, dict) else None


def put_job(db_path, job) -> None:
    """写/覆盖一条任务记录（upsert）。`job` 原样进 `payload`，一个字段都不增删。"""
    if not isinstance(job, dict):
        raise StoreError("任务记录形状非法（顶层不是对象）")
    jid = str(job.get("id") or "")
    if not jid:
        raise StoreError("任务记录缺 id")
    with _write(db_path) as con:
        con.execute(
            "INSERT INTO jobs (id, status, period, created_at, updated_at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
            " period=excluded.period, created_at=excluded.created_at,"
            " updated_at=excluded.updated_at, payload=excluded.payload",
            (jid, str(job.get("status") or ""), str(job.get("period") or ""),
             str(job.get("created_at") or ""), _now(), _dumps(job)))


def list_jobs(db_path, *, period=None, statuses=None, limit=None) -> list[dict]:
    """任务记录（`created_at` 新→旧，同秒按 id 新→旧）；库不存在 → `[]`。

    `period` 按期次过滤；`statuses` 给一组库内状态名（`IN`，供 `active_job()` 一次查到
    「在跑的那几条」——**不扫目录**）。`limit=None` = 全部。
    """
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    sql = "SELECT payload FROM jobs"
    where, args = [], []
    if period is not None:
        where.append("period=?")
        args.append(str(period))
    if statuses:
        marks = ",".join("?" for _ in statuses)
        where.append(f"status IN ({marks})")
        args.extend(str(s) for s in statuses)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(int(limit))
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(sql, args).fetchall()
        except sqlite3.Error:
            if degraded:
                return []
            raise
    out = []
    for row in rows:
        try:
            rec = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


# --------------------------------------------------------------- 人工填写（003）
#: `manual_inputs.status` 允许的三态（与 `server/workbench.py::_fill_state` 同一套词汇）。
FILL_STATES = ("pending", "applied", "orphan")


def get_fills(db_path, period) -> dict:
    """一期的填写内容：`{位置::标记: {value, by, at}}`（与旧 `manual_inputs.json` 同形）；无 → `{}`。

    库不存在 → `{}`（读口不造文件）。**按 rowid 序**返回＝旧文件的书写顺序：
    JSON 顶层键序没排过，导出要逐字节相同就不能按 slot 重排。
    `status` 列不返回——三态由 `workbench._fill_state` 现场重算（见 `_DDL_003`）。
    """
    period = str(period)
    path = pathlib.Path(db_path)
    if not path.is_file():
        return {}
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(
                "SELECT slot, payload FROM manual_inputs WHERE period=? ORDER BY rowid",
                (period,)).fetchall()
        except sqlite3.Error:
            if degraded:
                return {}
            raise
    out = {}
    for row in rows:
        item = _loads(row["payload"], {})
        if isinstance(item, dict):
            out[str(row["slot"])] = item
    return out


def set_fill(db_path, period, slot, record, *, status="pending") -> None:
    """写/覆盖一处填写（upsert）。`record` 即旧文件里那一项（`{value, by, at}`），原样进 payload。"""
    period, slot = str(period), str(slot)
    if not slot:
        raise StoreError("填写位置不能为空")
    if not isinstance(record, dict):
        raise StoreError("填写形状非法（不是对象）")
    if status not in FILL_STATES:
        raise StoreError(f"填写状态非法：{status!r}（只收 {'/'.join(FILL_STATES)}）")
    with _write(db_path) as con:
        con.execute(
            "INSERT INTO manual_inputs (period, slot, value, status, actor, at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(period, slot) DO UPDATE SET value=excluded.value,"
            " status=excluded.status, actor=excluded.actor, at=excluded.at,"
            " payload=excluded.payload",
            (period, slot, _text(record.get("value")), str(status),
             _text(record.get("by")), _text(record.get("at")), _dumps(record)))


def replace_fills(db_path, period, data) -> None:
    """整期覆盖（导入 / e2e 还原用）：`{}` = 全清；**按字典顺序落行**（导出键序由此而来）。"""
    period = str(period)
    if not isinstance(data, dict):
        raise StoreError("填写集合形状非法（不是对象）")
    for slot, item in data.items():
        if not isinstance(item, dict):
            raise StoreError(f"填写形状非法：{slot!r}")
    with _write(db_path) as con:
        con.execute("DELETE FROM manual_inputs WHERE period=?", (period,))
        for slot, item in data.items():
            con.execute(
                "INSERT INTO manual_inputs (period, slot, value, status, actor, at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (period, str(slot), _text(item.get("value")),
                 str(item.get("status") or "pending"),
                 _text(item.get("by")), _text(item.get("at")), _dumps(item)))


# --------------------------------------------------------------- 期次清单（导出用）
def periods(db_path) -> list[str]:
    """库里有状态的期次（签单 / 存疑 / 填写；字典序，即时间序）；库不存在 → `[]`。"""
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(
                "SELECT period FROM approvals UNION SELECT period FROM reviews"
                " UNION SELECT period FROM manual_inputs").fetchall()
        except sqlite3.Error:
            if degraded:
                return []
            raise
        return sorted({str(r[0]) for r in rows})


# --------------------------------------------------------------- 数据来源清单（004）
#: `sources.kind` 的合法值（与 `tools/sources_index.py` 的 kind 根一一对应）。
SOURCE_KINDS = ("esi", "incites")


def _source_row(row) -> dict:
    return {"kind": row["kind"], "scope": row["scope"], "rel_path": row["rel_path"],
            "size": int(row["size"]), "mtime_ns": int(row["mtime_ns"]),
            "sha256": row["sha256"] or "", "scanned_at": row["scanned_at"] or "",
            "payload": _loads(row["payload"], {})}


def sources_rows(db_path, *, kind=None, scope=None) -> list[dict]:
    """来源清单的行（`(kind, scope, rel_path)` 序）；库不存在 → `[]`（读口不造文件）。

    只读；降级（库版本高于程序）时同样返回 `[]`，告警看 `health()`。
    `kind` / `scope` 为过滤条件，`None` = 全部。
    """
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    sql = ("SELECT kind, scope, rel_path, size, mtime_ns, sha256, scanned_at, payload"
           " FROM sources")
    where, args = [], []
    if kind is not None:
        where.append("kind=?")
        args.append(str(kind))
    if scope is not None:
        where.append("scope=?")
        args.append(str(scope))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY kind, scope, rel_path"
    with _open(path) as (con, degraded, _note):
        try:
            rows = con.execute(sql, args).fetchall()
        except sqlite3.Error:
            if degraded:
                return []
            raise
    return [_source_row(r) for r in rows]


def put_sources(db_path, entries) -> int:
    """写/覆盖一批来源清单行（upsert，一个短事务）；返回写的行数。

    调用方（`tools/sources_index.py`）负责「哪些行真的要写」——`size + mtime_ns` 都没变的行
    它不会送进来，所以这里的 `scanned_at` 就是**最后一次看见文件变化**的时刻。
    `entries` 里每条须有 `kind / scope / rel_path`；`sha256` 缺省为空串＝只有元数据。
    """
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise StoreError("来源词条形状非法（不是对象）")
        kind = str(entry.get("kind") or "")
        scope = str(entry.get("scope") or "")
        rel_path = str(entry.get("rel_path") or "")
        if kind not in SOURCE_KINDS:
            raise StoreError(f"来源类别非法：{kind!r}（只收 {'/'.join(SOURCE_KINDS)}）")
        if not scope or not rel_path:
            raise StoreError("来源词条缺 scope / rel_path")
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            raise StoreError(f"来源附带信息形状非法：{rel_path!r}")
        rows.append((kind, scope, rel_path, int(entry.get("size") or 0),
                     int(entry.get("mtime_ns") or 0), str(entry.get("sha256") or ""),
                     str(entry.get("scanned_at") or _now()), _dumps(payload)))
    if not rows:
        return 0
    with _write(db_path) as con:
        con.executemany(
            "INSERT INTO sources (kind, scope, rel_path, size, mtime_ns, sha256,"
            " scanned_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(kind, scope, rel_path) DO UPDATE SET size=excluded.size,"
            " mtime_ns=excluded.mtime_ns, sha256=excluded.sha256,"
            " scanned_at=excluded.scanned_at, payload=excluded.payload", rows)
    return len(rows)


def delete_sources(db_path, keys) -> int:
    """删掉指名的行（`scan` 发现磁盘上已经没有时用）；返回**实际删掉**的条数。

    只删 `keys`（`(kind, scope, rel_path)`）里点名的行，别的行一概不碰——
    与 `delete_history` 同理：错删清单不致命，但错删会让人以为文件真的没了。
    """
    wanted = [(str(kind), str(scope), str(rel_path)) for kind, scope, rel_path in keys]
    if not wanted:
        return 0
    with _write(db_path) as con:
        deleted = 0
        for kind, scope, rel_path in wanted:
            cur = con.execute(
                "DELETE FROM sources WHERE kind=? AND scope=? AND rel_path=?",
                (kind, scope, rel_path))
            deleted += max(cur.rowcount or 0, 0)
        return deleted


# --------------------------------------------------------------- 自查
def selftest(db_path) -> dict:                                    # pragma: no cover - 手工排障用
    """一行健康快照（工具/排障用，不进请求路径）。"""
    info = health(db_path)
    if info["exists"]:
        info["periods"] = periods(db_path)
    return info
