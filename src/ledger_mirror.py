# -*- coding: utf-8 -*-
"""台账镜像（SQLite）——从母本**确定性重建**的只读查询层（2026-10-13 票 01 / 02）。

- 口径：`parse_ledger.long_table()`（与 `ledger_long.parquet` 同源同函数，不复制口径）；
- 边界（spec 三条写死）：单向 ETL——db 永不回写母本；同母本（sha）→ 同 `content_sha256`；
  数字仍只出自台账口径，换算值不由 SQL 自由计算；模型不自由 SQL（只选白名单视图，票 02）；
- 路径唯一口径：`src/ledger.mirror_path()` → `out/_mirror/ledger.sqlite`；
- 白名单视图（票 02）：`VIEWS` 注册表（periods / series / at / latest）——内核只按
  「视图名 + 参数」取数；切窗是消费侧语义（`period_max`，ADR-0007）。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sqlite3

import ledger as ledger_mod
import parse_ledger

SCHEMA_VERSION = 1

_DDL = (
    "CREATE TABLE facts ("
    " discipline TEXT NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL,"
    " source TEXT NOT NULL DEFAULT '', value REAL,"
    " PRIMARY KEY (discipline, period, metric, source));"
    "CREATE INDEX idx_facts_period ON facts(period);"
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
)


def _uri(db_path) -> str:
    """SQLite 只读 URI（Windows 绝对路径要 `file:///C:/…` 三段斜杠）。"""
    p = pathlib.Path(db_path).resolve()
    return f"file:///{p.as_posix().lstrip('/')}?mode=ro"


def _connect_ro(db_path):
    """只读连接（`uri=True` 不能少——否则 URI 会被当字面文件名）。"""
    return sqlite3.connect(_uri(db_path), uri=True)


def _hash_rows(rows) -> str:
    """规范化行哈希：按 (discipline, period, metric, source) 排序后逐行 sha256。

    行＝(discipline, period, metric, source, value)；value 为 None 记空、否则 repr(float)。
    传入行必须是已排序的（写库侧排过；读库侧 SQL ORDER BY）。
    """
    h = hashlib.sha256()
    for d, p, m, s, v in rows:
        h.update(f"{d}\t{p}\t{m}\t{s}\t{'' if v is None else repr(float(v))}".encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _rows_from_ledger(ledger_path):
    """母本 → 排序好的行 + ledger dict（唯一 ETL 口径）。"""
    ledger = parse_ledger.load_ledger(pathlib.Path(ledger_path))
    long_df = parse_ledger.long_table(ledger)
    rows = []
    cols = ["discipline", "period", "metric", "source", "value"]
    for d, p, m, src, val in long_df[cols].itertuples(index=False, name=None):
        source = "" if src is None or src != src else str(src)
        value = None if val is None or val != val else float(val)
        rows.append((str(d), str(p), str(m), source, value))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    return rows, ledger


def write_facts(db_path, rows, *, ledger_sha256: str = "") -> dict:
    """把行写成只读镜像库（原子替换：先写 .tmp 再 os.replace）。返回 meta。

    `rows`＝(discipline, period, metric, source, value) 可迭代；本函数负责排序与去重
    （同键后者覆盖——与 `INSERT OR REPLACE` 一致）。
    """
    rows = sorted(
        ((str(d), str(p), str(m), str(s or ""), None if v is None else float(v))
         for d, p, m, s, v in rows),
        key=lambda r: (r[0], r[1], r[2], r[3]),
    )
    db_path = pathlib.Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_DDL)
        con.executemany(
            "INSERT OR REPLACE INTO facts (discipline, period, metric, source, value) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "ledger_sha256": str(ledger_sha256 or ""),
            "n_facts": str(len(rows)),
            "periods": ",".join(sorted({r[1] for r in rows})),
            "metrics": ",".join(sorted({r[2] for r in rows})),
            "content_sha256": _hash_rows(rows),
        }
        con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        sorted(meta.items()))
        con.commit()
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    os.replace(tmp, db_path)
    out = dict(meta)
    out["path"] = str(db_path)
    return out


def build(db_path, *, ledger_path) -> dict:
    """母本 → SQLite（确定性重建）。返回 meta（含 content_sha256 / ledger_sha256）。"""
    rows, _ = _rows_from_ledger(ledger_path)
    return write_facts(db_path, rows, ledger_sha256=ledger_mod.sha256(ledger_path))


def content_hash(db_path) -> str:
    """库内容的规范化 sha256（只读）。"""
    con = _connect_ro(db_path)
    try:
        rows = con.execute(
            "SELECT discipline, period, metric, source, value FROM facts "
            "ORDER BY discipline, period, metric, source"
        ).fetchall()
    finally:
        con.close()
    return _hash_rows(rows)


def verify(db_path, *, ledger_path=None) -> dict:
    """库自校验（行哈希 ≡ meta）；`ledger_path` 给了再重解析母本比对（确定性）。"""
    db_path = pathlib.Path(db_path)
    if not db_path.is_file():
        return {"ok": False, "reason": f"镜像不存在：{db_path}"}
    con = _connect_ro(db_path)
    try:
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        n = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    finally:
        con.close()
    got = content_hash(db_path)
    out = {"ok": got == meta.get("content_sha256") and str(n) == meta.get("n_facts"),
           "content_sha256": got, "n_facts": n}
    if not out["ok"]:
        out["reason"] = "库自校验不过（行哈希 ≠ meta）"
        return out
    if ledger_path is not None:
        rows, _ = _rows_from_ledger(ledger_path)
        fresh = _hash_rows(rows)
        out["ledger_sha256"] = meta.get("ledger_sha256", "")
        if fresh != got:
            out["ok"] = False
            out["reason"] = "重解析母本比对不过（同母本应同内容）"
    return out


def rows(db_path):
    """全量只读行（按主键序）——测试/工具用；消费面走白名单视图（票 02）。"""
    con = _connect_ro(db_path)
    try:
        return con.execute(
            "SELECT discipline, period, metric, source, value FROM facts "
            "ORDER BY discipline, period, metric, source"
        ).fetchall()
    finally:
        con.close()


def series(db_path, discipline, metric, *, source=None, period_max=None):
    """某学科某指标一列（期次升序）→ [(period, value)]；切窗 `period <= period_max`。"""
    q = ("SELECT period, value FROM facts WHERE discipline=? AND metric=?"
         + (" AND source=?" if source is not None else "")
         + (" AND period<=?" if period_max else "")
         + " ORDER BY period")
    args = [discipline, metric]
    if source is not None:
        args.append(source)
    if period_max:
        args.append(str(period_max))
    con = _connect_ro(db_path)
    try:
        return con.execute(q, args).fetchall()
    finally:
        con.close()


# ============================================================ 白名单视图（票 02）
# 供 pi 内核等消费方按「视图名 + 参数」取数（spec 边界 2：模型不自由 SQL）。
# 共同口径：只读连接（mode=ro）；排序确定；空结果给空（[] / {} / None），形状非法照常抛错。
# `db` 由调用方绑定，不进 VIEWS 的 params。


def periods(db):
    """全部期次（字符串降序，YYYYMM 字典序即时间序）；空库给 []。"""
    con = _connect_ro(db)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM facts ORDER BY period DESC")]
    finally:
        con.close()


def at(db, discipline, period):
    """某学科某期全部指标 → {metric: value}。

    - source 为空的指标：键＝`metric`（如 total_cites）；
    - source 非空的指标：键＝`metric@source`（如 rank@rank_cn），同指标多来源不互相覆盖；
    - 值可能是 None（台账空单元格，不填充、不丢行）；该学科该期无任何行 → {}。
    """
    con = _connect_ro(db)
    try:
        cur = con.execute(
            "SELECT metric, source, value FROM facts WHERE discipline=? AND period=? "
            "ORDER BY metric, source",
            (str(discipline), str(period)))
        return {(f"{m}@{s}" if s else m): v for m, s, v in cur}
    finally:
        con.close()


def latest(db, metric=None, *, source=None):
    """最近期次（YYYYMM 字符串）；空库或查无 → None。

    - 不给 metric：facts 里（该来源下）的最大期次——期次在台账出现即算，值可为空；
    - 给 metric：该指标（source 给定时再限定来源）**有非空值**的最大期次；
    - source=None 不过滤来源；source="" 只查无来源指标；给定值只查该来源。
    """
    where, args = [], []
    if metric is not None:
        where.append("metric=?")
        args.append(str(metric))
        where.append("value IS NOT NULL")
    if source is not None:
        where.append("source=?")
        args.append(str(source))
    q = "SELECT MAX(period) FROM facts"
    if where:
        q += " WHERE " + " AND ".join(where)
    con = _connect_ro(db)
    try:
        return con.execute(q, args).fetchone()[0]
    finally:
        con.close()


VIEWS = {
    "periods": {
        "doc": "全部期次（字符串降序）；空库给 []。",
        "params": [],
        "fn": periods,
    },
    "series": {
        "doc": ("某学科某指标一列 (period, value)，期次升序；source 给定时只取该来源，"
                "period_max 切窗。"),
        "params": [
            {"name": "discipline", "required": True,
             "doc": "学科名（与 ledger_long.discipline 同口径）"},
            {"name": "metric", "required": True,
             "doc": "指标名（与 ledger_long.metric 同口径）"},
            {"name": "source", "required": False, "default": None,
             "doc": "来源（'', new_cn/new_intl/rank_cn/rank_intl）；None＝不过滤，"
                    "同指标多来源会并入一列"},
            {"name": "period_max", "required": False, "default": None,
             "doc": "切窗：只保留 period <= period_max（YYYYMM 字符串）；None＝全量"},
        ],
        "fn": series,
    },
    "at": {
        "doc": ("某学科某期全部指标 → {metric: value}；source 非空的键写作 "
                "\"metric@source\"（如 rank@rank_cn），值可为 None。"),
        "params": [
            {"name": "discipline", "required": True, "doc": "学科名"},
            {"name": "period", "required": True, "doc": "期次（YYYYMM）"},
        ],
        "fn": at,
    },
    "latest": {
        "doc": ("最近期次：不给 metric ＝ 库中（该来源下）最大期次；给 metric ＝ 该指标"
                "有非空值的最大期次；空库/查无 → None。"),
        "params": [
            {"name": "metric", "required": False, "default": None,
             "doc": "指标名；None＝不限定指标（期次出现即算）"},
            {"name": "source", "required": False, "default": None,
             "doc": "来源限定（'' / new_cn / …）；None＝不过滤"},
        ],
        "fn": latest,
    },
}


def describe_views():
    """白名单视图清单（name/doc/params，不含 fn）——供 CLI / 内核工具列示。"""
    return [{"name": name, "doc": spec["doc"], "params": spec["params"]}
            for name, spec in VIEWS.items()]
