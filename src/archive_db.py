# -*- coding: utf-8 -*-
"""历史档案库（SQLite）——ESI / InCites 原始包的解析副本（ADR-0015）。

- **边界（ADR-0015）**：装的是 `../数据与复现/` 原始包的**解析副本**（机构级明细），
  不是原件也不是事实源；原件一字不动（对数据目录只读），单向 ETL 永不回写；
  运行期任何环节不读它——流水线读数只走动态监测表。
- **可确定性重建**：与状态库相反，档案库是派生物——删了从原件重导即可，
  同输入 → 同 `content_sha256`。字节级备份责任仍在原件与 sources 清单。
- **三库分工**：状态库＝控制面（零数字）；问数库＝云大指标事实查询面；
  档案库＝原始包解析副本（谁 × 哪科 × 哪期什么数）。一词一义见 GLOSSARY。
- **InCites 列漂移**：45 个快照跨多个导出版本（老版 59 列中文表头 → 新版变体），
  `incites_subject_rows` 按「表头字典并集」动态建列：每个出现过的表头 → 一个 slug 列
  （`incites_metrics` 记 slug ↔ 原样表头），导入按文件表头映射填列，缺列 NULL。
  列集合只增不改；重建按相同导入顺序重放 → 同 schema 同数据同指纹。
- **损坏件**：最老 8 快照 219 件表头乱码（0x3F 顶字节不可逆），由
  `archive_import.OLD_LAYOUTS` 按 `数据说明.txt` 的老版列序做**位置恢复**，标 `recovered`。
- 🔴 不假装方言中立：WAL / upsert / ALTER TABLE 均为 sqlite 专有（ADR-0012 决定 5 同款）。

路径唯一口径：`db_path()` → 工作区根 `档案库/wenheng_archive.sqlite`；
`WENHENG_ARCHIVE_DB` 可覆盖（测试用）。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sqlite3
import unicodedata

REPO = pathlib.Path(__file__).resolve().parent.parent

#: schema 版本（写进 meta）。档案库可整体重建，版本不符 → reset 重建，不做迁移。
SCHEMA_VERSION = 1
#: 库文件名。
DB_NAME = "wenheng_archive.sqlite"
#: 覆盖库路径的环境变量（测试用）。
ENV_VAR = "WENHENG_ARCHIVE_DB"
#: 库目录（工作区根下，与 `数据与复现/` 同级；目录不存在由 connect 前的调用方建）。
ARCHIVE_DIR = REPO.parent / "档案库"
#: InCites 指标列 slug 数量护栏：表头字典并集超过它 → 报错停（防脏表头炸表 / 防 4.3GB 库炸宽表）。
#: 实测依据（阶段 3b，2026-11-06）：45 个 InCites 快照学科机构榜（含云大22学科总体）表头字典并集——
#:   当前 norm_label 并集 = 326（正是阶段 3 全量导入触发 1108 件 InCites failed 的根因：326 > 200）；
#:   归一化年份/时间窗口片段（见 `norm_label`）后并集 = 290。
#: 取 400：覆盖实测 290 并留 ~38% 余量（防个别快照模板微小漂移、未来快照），
#: 远低于 SQLite 默认 2000 列上限，宽表 = 身份列 9 + ≤400 指标列，库体积可控。
#: 🔴 这是护栏不是上限封顶——保留它才能在真脏表头（并集异常暴涨）时仍 FAIL 而非静默写坏。
MAX_METRIC_COLUMNS = 400

#: 静态表 DDL（动态的 `incites_subject_rows` 由 `ensure_subject_columns` 管）。
_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",

    # ① 文件清单：100% 登记（含锁文件 / zip 重复件 / 派生件），解析结果也挂在这
    "CREATE TABLE IF NOT EXISTS files ("
    " id INTEGER PRIMARY KEY,"
    " kind TEXT NOT NULL,"            # esi | incites | misc
    " scope TEXT NOT NULL,"           # 期次目录名 / 快照目录名 / _root
    " rel_path TEXT NOT NULL,"        # 相对 数据与复现/
    " size INTEGER NOT NULL,"
    " mtime_ns INTEGER NOT NULL,"
    " sha256 TEXT NOT NULL DEFAULT '',"
    " role TEXT NOT NULL DEFAULT '',"       # 受控值见 archive_import.ROLES
    " parse_status TEXT NOT NULL DEFAULT 'pending',"  # parsed/recovered/empty/corrupted/skipped_duplicate/derived_no_parse/failed/pending
    " parse_rows INTEGER NOT NULL DEFAULT 0,"
    " parse_error TEXT NOT NULL DEFAULT '',"
    " note TEXT NOT NULL DEFAULT '',"
    " UNIQUE(kind, scope, rel_path))",

    # ② 维度层
    "CREATE TABLE IF NOT EXISTS periods ("
    " period TEXT PRIMARY KEY,"       # 202607
    " download_meta TEXT NOT NULL DEFAULT '')",   # _下载信息.json 原文
    "CREATE TABLE IF NOT EXISTS snapshots ("
    " snapshot TEXT PRIMARY KEY,"     # 数据覆盖2016-2026.08.31
    " window_start TEXT NOT NULL DEFAULT '',"
    " window_end TEXT NOT NULL DEFAULT '',"
    " note TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS period_snapshot ("
    " period TEXT PRIMARY KEY,"
    " snapshot TEXT NOT NULL,"
    " source TEXT NOT NULL DEFAULT '')",          # snap_map | manual

    # ③ ESI 结构化层（file_id → files.id，每行可溯源）
    "CREATE TABLE IF NOT EXISTS esi_discipline_rank ("
    " period TEXT NOT NULL, discipline TEXT NOT NULL,"
    " rank_no INTEGER, institution TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',"
    " documents INTEGER, cites INTEGER, cites_per_paper REAL,"
    " top_papers INTEGER, top_pct REAL,"
    " highly_cited INTEGER, highly_cited_pct REAL,"
    " hot_papers INTEGER, hot_pct REAL,"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",
    "CREATE INDEX IF NOT EXISTS idx_edr_query ON esi_discipline_rank(period, discipline)",
    "CREATE INDEX IF NOT EXISTS idx_edr_inst ON esi_discipline_rank(institution)",
    "CREATE TABLE IF NOT EXISTS esi_institutions ("
    " period TEXT NOT NULL, seq INTEGER,"
    " institution TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",
    "CREATE TABLE IF NOT EXISTS esi_thresholds ("
    " period TEXT NOT NULL, kind TEXT NOT NULL,"   # esi_1pct | highly_cited | hot
    " discipline TEXT NOT NULL, value REAL,"
    " file_id INTEGER NOT NULL, row_no INTEGER,"
    " PRIMARY KEY (file_id, row_no))",
    "CREATE TABLE IF NOT EXISTS esi_baselines ("
    " period TEXT NOT NULL, kind TEXT NOT NULL,"   # citation_rates | field_rankings | percentiles
    " discipline TEXT NOT NULL, col_label TEXT NOT NULL, value REAL,"
    " file_id INTEGER NOT NULL, row_no INTEGER,"
    " PRIMARY KEY (file_id, row_no, col_label))",  # 宽转长：一行源数据出多列值
    "CREATE TABLE IF NOT EXISTS esi_papers ("
    " period TEXT NOT NULL, kind TEXT NOT NULL,"   # top | highly_cited | hot | school_list
    " title TEXT NOT NULL DEFAULT '', authors TEXT NOT NULL DEFAULT '',"
    " source TEXT NOT NULL DEFAULT '', pub_year INTEGER, pub_date TEXT NOT NULL DEFAULT '',"
    " times_cited INTEGER, discipline TEXT NOT NULL DEFAULT '',"
    " raw_json TEXT NOT NULL DEFAULT '',"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",
    "CREATE TABLE IF NOT EXISTS esi_research_fields ("
    " period TEXT NOT NULL, scope TEXT NOT NULL,"  # global | china | ynu
    " discipline TEXT NOT NULL DEFAULT '', cites_per_paper REAL,"
    " q1 REAL, q2 REAL, q3 REAL, q4 REAL,"
    " raw_json TEXT NOT NULL DEFAULT '',"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",

    # ④ InCites 结构化层
    "CREATE TABLE IF NOT EXISTS incites_metrics ("
    " slug TEXT PRIMARY KEY,"          # m01 / m02 …（首次遇到的顺序，确定性重放）
    " label TEXT NOT NULL,"            # 原样表头
    " label_norm TEXT NOT NULL UNIQUE,"# 归一化表头（查找键）
    " note TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS incites_research_fields ("
    " snapshot TEXT NOT NULL, scope TEXT NOT NULL,"
    " discipline TEXT NOT NULL DEFAULT '', q1 REAL, q2 REAL, q3 REAL, q4 REAL,"
    " raw_json TEXT NOT NULL DEFAULT '',"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",
    "CREATE TABLE IF NOT EXISTS incites_ynu_papers ("
    " snapshot TEXT NOT NULL, discipline TEXT NOT NULL DEFAULT '',"
    " title TEXT NOT NULL DEFAULT '', times_cited INTEGER,"
    " raw_json TEXT NOT NULL DEFAULT '',"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",
    "CREATE TABLE IF NOT EXISTS incites_global_institutions ("
    " snapshot TEXT NOT NULL, rank_no INTEGER,"
    " institution TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',"
    " raw_json TEXT NOT NULL DEFAULT '',"
    " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
    " PRIMARY KEY (file_id, row_no))",

    # ⑤ 兜底层：没有专属表的原件逐行原样（行 → JSON）
    "CREATE TABLE IF NOT EXISTS misc_rows ("
    " file_id INTEGER NOT NULL, sheet TEXT NOT NULL DEFAULT '', row_no INTEGER NOT NULL,"
    " raw_json TEXT NOT NULL,"
    " PRIMARY KEY (file_id, sheet, row_no))",
)

#: 逐表主键（content_sha256 的排序依据；顺序固定 → 同内容同指纹）。
_TABLE_PKS: dict[str, tuple[str, ...]] = {
    "files": ("id",),
    "periods": ("period",),
    "snapshots": ("snapshot",),
    "period_snapshot": ("period",),
    "esi_discipline_rank": ("file_id", "row_no"),
    "esi_institutions": ("file_id", "row_no"),
    "esi_thresholds": ("file_id", "row_no"),
    "esi_baselines": ("file_id", "row_no", "col_label"),
    "esi_papers": ("file_id", "row_no"),
    "esi_research_fields": ("file_id", "row_no"),
    "incites_metrics": ("slug",),
    "incites_subject_rows": ("file_id", "row_no"),
    "incites_research_fields": ("file_id", "row_no"),
    "incites_ynu_papers": ("file_id", "row_no"),
    "incites_global_institutions": ("file_id", "row_no"),
    "misc_rows": ("file_id", "sheet", "row_no"),
}
#: content_sha256 覆盖的表序（meta 不算——它装的是指纹与构建时间本身）。
TABLE_ORDER: tuple[str, ...] = tuple(_TABLE_PKS)


def db_path() -> pathlib.Path:
    """库路径唯一口径：工作区根 `档案库/wenheng_archive.sqlite`；`WENHENG_ARCHIVE_DB` 可覆盖。"""
    custom = os.environ.get(ENV_VAR)
    if custom:
        return pathlib.Path(custom)
    return ARCHIVE_DIR / DB_NAME


def connect(db_path) -> sqlite3.Connection:
    """连库（WAL + busy_timeout；调用方负责先建目录）。"""
    db_path = pathlib.Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure(conn: sqlite3.Connection) -> None:
    """建表（幂等）。逐条 execute——`executescript` 会先把在途事务 COMMIT 掉。"""
    for stmt in _DDL:
        conn.execute(stmt)
    conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                 "ON CONFLICT(key) DO NOTHING", (str(SCHEMA_VERSION),))
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """清空重建（档案库是派生物，删了可重导——与状态库相反）。"""
    names = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%'")]
    for name in names:
        conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.commit()
    ensure(conn)


# ---------------------------------------------------------------- files 清单
def register_file(conn, *, kind: str, scope: str, rel_path: str, size: int,
                  mtime_ns: int, sha256: str = "", role: str = "") -> int:
    """登记/更新一个文件，返回 file_id（幂等键 = kind+scope+rel_path）。"""
    conn.execute(
        "INSERT INTO files(kind, scope, rel_path, size, mtime_ns, sha256, role)"
        " VALUES(?,?,?,?,?,?,?)"
        " ON CONFLICT(kind, scope, rel_path) DO UPDATE SET"
        " size=excluded.size, mtime_ns=excluded.mtime_ns,"
        " sha256=excluded.sha256, role=excluded.role",
        (kind, scope, rel_path, size, mtime_ns, sha256, role))
    row = conn.execute(
        "SELECT id FROM files WHERE kind=? AND scope=? AND rel_path=?",
        (kind, scope, rel_path)).fetchone()
    return int(row["id"])


def set_file_parse(conn, file_id: int, *, status: str, rows: int = 0,
                   error: str = "", note: str = "", role: str | None = None) -> None:
    """回写一个文件的解析结果。"""
    conn.execute(
        "UPDATE files SET parse_status=?, parse_rows=?, parse_error=?, note=?"
        + (", role=?" if role is not None else "")
        + " WHERE id=?",
        (status, rows, error, note, *([role] if role is not None else []), file_id))


# ---------------------------------------------------------------- InCites 列字典
#: 跨期漂移的年份/时间窗口片段：同概念列（如「% First Author (2008-Present)」）在不同快照
#: 仅窗口终点不同（Present / 2020 / 2021 / 2024），归一化成占位符让同名表头复用 slug，
#: 否则 45 快照表头字典并集从 ~92 撑到 326，触发 MAX_METRIC_COLUMNS 护栏（阶段 3 实测
#: 1108 件 InCites 因触顶 200 而 failed）。半角/全角括号都覆盖。
_YEAR_WINDOW = re.compile(
    r"[\(（]\s*\d{4}\s*[-–—]\s*(?:\d{4}(?:\.\d{1,2}(?:\.\d{1,2})?)?|present)\s*[\)）]",
    re.IGNORECASE)


def norm_label(label) -> str:
    """表头归一化：NFC + 年份/时间窗口片段归一 + 去首尾空白 + 压内部空白。

    年份窗口（如 `(2008-Present)` / `(2008-2024)` / `（2008-2020）`）跨快照仅终点不同、概念
    相同，归一成 `(WINDOW)` 让同名表头复用 slug——否则表头字典并集（incites_metrics）被撑爆。
    确定性不变：同输入 → 同 slug（content_sha256 依赖重放顺序）。
    """
    s = unicodedata.normalize("NFC", str(label)).strip()
    s = _YEAR_WINDOW.sub("(WINDOW)", s)
    return " ".join(s.split())


def metric_slug(conn, label: str) -> str:
    """原样表头 → slug 列名（首次见到即分配 m01/m02…，查过即复用）。"""
    lab_norm = norm_label(label)
    row = conn.execute("SELECT slug FROM incites_metrics WHERE label_norm=?",
                       (lab_norm,)).fetchone()
    if row:
        return str(row["slug"])
    n = conn.execute("SELECT COUNT(*) AS n FROM incites_metrics").fetchone()["n"]
    if n >= MAX_METRIC_COLUMNS:
        raise RuntimeError(f"InCites 表头字典超过 {MAX_METRIC_COLUMNS} 列上限（疑似脏表头），停止")
    slug = f"m{n + 1:02d}"
    conn.execute("INSERT INTO incites_metrics(slug, label, label_norm) VALUES(?,?,?)",
                 (slug, str(label), lab_norm))
    ensure_subject_columns(conn, [slug])
    return slug


def ensure_subject_columns(conn, slugs) -> None:
    """保证 `incites_subject_rows` 有这些 slug 列（缺则 ALTER TABLE 补，列集合只增不改）。"""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(incites_subject_rows)")}
    if not have:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS incites_subject_rows ("
            " snapshot TEXT NOT NULL, discipline TEXT NOT NULL,"
            " rank_no INTEGER, institution TEXT NOT NULL DEFAULT '',"
            " country TEXT NOT NULL DEFAULT '', org_type TEXT NOT NULL DEFAULT '',"
            " province TEXT NOT NULL DEFAULT '',"
            " file_id INTEGER NOT NULL, row_no INTEGER NOT NULL,"
            " PRIMARY KEY (file_id, row_no))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_isr_query"
                     " ON incites_subject_rows(snapshot, discipline)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_isr_inst"
                     " ON incites_subject_rows(institution)")
        have = {r["name"] for r in conn.execute("PRAGMA table_info(incites_subject_rows)")}
    for slug in slugs:
        if slug not in have:
            conn.execute(f"ALTER TABLE incites_subject_rows ADD COLUMN {slug} REAL")


# ---------------------------------------------------------------- 批量写
def insert_rows(conn, table: str, columns, rows) -> int:
    """executemany 批量插一行迭代器，返回行数（调用方控制事务粒度）。"""
    cols = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    conn.executemany(f"INSERT OR REPLACE INTO {table}({cols}) VALUES({marks})", rows)
    return len(rows)


def put_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?,?)"
                 " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_meta(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else None


# ---------------------------------------------------------------- 对账
def table_counts(conn) -> dict[str, int]:
    """逐表行数（verify / 报告用）。"""
    out = {}
    for table in TABLE_ORDER:
        out[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    return out


def _cell_repr(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def content_sha256(conn, *, emit=None) -> str:
    """全库内容指纹：逐表按主键序扫行、逐列拼规范串。

    🔴 只认**输入决定的内容**：meta 不参与（它装指纹与构建时间本身）。
    同输入重建 → 同指纹；导入顺序确定（文件按 rel_path 排序）→ schema 与行序也确定。
    """
    h = hashlib.sha256()
    for table in TABLE_ORDER:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        pk = _TABLE_PKS[table]
        order = ", ".join(pk)
        sel = ", ".join(f'"{c}"' for c in cols)
        n = 0
        for row in conn.execute(f"SELECT {sel} FROM {table} ORDER BY {order}"):
            h.update(table.encode("utf-8"))
            h.update("\x1f".join(_cell_repr(v) for v in tuple(row)).encode("utf-8"))
            h.update(b"\x1e")
            n += 1
            if emit and n % 2_000_000 == 0:
                emit(f"    …{table} 已扫 {n} 行")
    return h.hexdigest()
