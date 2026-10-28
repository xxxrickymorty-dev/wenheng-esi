# -*- coding: utf-8 -*-
"""AI 问数库（SQLite）——为「问数」工作台准备的一站式只读数据库。

事实面直接取 `out/<期次>/ledger_long.parquet`（main 线 2026-10 重构后台账事实的
唯一产物面；旧 `src/ledger_mirror.py` 已随重构移除），本库在其上补齐**查询友好的**
维度与聚合面：

| 表 | 内容 | 来源（唯一口径） |
|---|---|---|
| `dim_discipline` | 22 学科（英文名 / 中文名 / 学科指纹） | `parse_ledger.DISCIPLINES_*` |
| `dim_metric` | 指标字典（中文名 / 方向 / 来源说明） | `flexible.datasource.METRICS` |
| `dim_period` | 期次轴（期次 / 中文年月 / 期数 / 是否有数据） | `period.filled` |
| `facts` | 长表事实（学科×期次×指标×来源 → 值） | `out/<期次>/ledger_long.parquet` |
| `report_table2` | 当期报告大表 22×11（每格带来源指针） | `out/<期次>/table2.csv` |
| `report_overview` | 概述事实（键值对，含顶尖论文/排名等） | `out/<期次>/overview_facts.json` |
| `qa_log` | 问数留痕（问题 / 规格 / 行数 / 耗时） | 运行时写（唯一写表） |

红线（与镜像同款，spec 2026-10-12）：
- **单向 ETL**：本库永不回写台账 / 产物；除 `qa_log` 外全部表只读；
- **确定性重建**：同输入（同台账 sha + 同产物）→ 同 `content_sha256`；
- **数字不进模型**：模型只产白名单查询规格（零数字），值由本引擎取出；
- 路径唯一口径：`db_path()` → `out/_aidata/aiqa.sqlite`。

用法（CLI）：
  uv run python tools/build_aiqa_db.py            # 重建（默认当期）
  uv run python tools/build_aiqa_db.py --verify   # 自校验
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sqlite3
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO))
if str(REPO / "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO / "src"))

SCHEMA_VERSION = 1

#: 「写留痕」唯一授权表（其余表 ETL 时建，运行期只读）。
LOG_TABLE = "qa_log"

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS dim_discipline (
  discipline TEXT PRIMARY KEY,        -- 英文规范名（台账口径）
  discipline_cn TEXT NOT NULL DEFAULT '',
  ord INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dim_metric (
  metric TEXT PRIMARY KEY,            -- 对外指标名（白名单）
  metric_cn TEXT NOT NULL,
  better TEXT NOT NULL DEFAULT 'none' -- up=越大越好 / down=越小越好 / none
);

CREATE TABLE IF NOT EXISTS dim_period (
  period TEXT PRIMARY KEY,            -- YYYYMM
  label TEXT NOT NULL,                -- 2026年7月
  ord INTEGER NOT NULL,
  filled INTEGER NOT NULL DEFAULT 1   -- 1=该期台账有数据
);

-- 长表事实：与 out/<期次>/ledger_long.parquet 同口径
CREATE TABLE IF NOT EXISTS facts (
  discipline TEXT NOT NULL,
  period TEXT NOT NULL,
  metric TEXT NOT NULL,               -- 宽表指标名（total_cites…）或 rank/rank_pct/n_inst_1pct
  source TEXT NOT NULL DEFAULT '',    -- ''（宽表）/ new_cn / new_intl / rank_cn / rank_intl
  value REAL,
  PRIMARY KEY (discipline, period, metric, source)
);
CREATE INDEX IF NOT EXISTS idx_facts_query ON facts(metric, period, discipline);
CREATE INDEX IF NOT EXISTS idx_facts_period ON facts(period);

-- 当期报告大表（22×11）——「报告里的数」面（供问数对照报告口径）
CREATE TABLE IF NOT EXISTS report_table2 (
  period TEXT NOT NULL,
  discipline TEXT NOT NULL,
  rank_cn_change TEXT, papers INTEGER, cnci REAL, total_cites INTEGER,
  thr_1pct INTEGER, thr_1pct_gap INTEGER, thr_1permille INTEGER,
  permille_rank REAL, top_papers INTEGER, prox_change TEXT,
  PRIMARY KEY (period, discipline)
);

-- 概述事实（键值）——报告概述段数字
CREATE TABLE IF NOT EXISTS report_overview (
  period TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (period, key)
);

-- 问数留痕（**唯一运行期可写表**）
CREATE TABLE IF NOT EXISTS qa_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,                   -- ISO 时间
  user TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL,
  specs TEXT NOT NULL DEFAULT '[]',   -- 白名单查询规格 JSON
  plan_origin TEXT NOT NULL DEFAULT 'rule',
  n_rows INTEGER NOT NULL DEFAULT 0,
  elapsed_ms INTEGER NOT NULL DEFAULT 0,
  answer_text TEXT NOT NULL DEFAULT '',
  chart_kind TEXT NOT NULL DEFAULT '' -- 建议图型（bar/pie/line/''）
);
CREATE INDEX IF NOT EXISTS idx_qa_log_ts ON qa_log(ts);
"""


def db_path(repo_root=REPO) -> pathlib.Path:
    """AI 问数库路径唯一口径。"""
    return pathlib.Path(repo_root) / "out" / "_aidata" / "aiqa.sqlite"


def _uri(p: pathlib.Path) -> str:
    r = p.resolve()
    return f"file:///{r.as_posix().lstrip('/')}"


def connect_ro(repo_root=REPO) -> sqlite3.Connection:
    """只读连接（缺库时报 FileNotFoundError，让调用方提示先构建）。"""
    p = db_path(repo_root)
    if not p.is_file():
        raise FileNotFoundError(f"AI 问数库不存在：{p}（先跑 tools/build_aiqa_db.py）")
    con = sqlite3.connect(_uri(p) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def connect_rw(repo_root=REPO) -> sqlite3.Connection:
    """读写连接（仅 qa_log 留痕用；表不存在时自动建表）。"""
    p = db_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_DDL)
    return con


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ============================================================ ETL（确定性重建）

#: 期次唯一形态（YYYYMM）。母本早期有少量写成小数（如 `2023.01`），语义可辨但
#: **映射不唯一**（`.3` 是 3 月还是 30 月？）。本库不猜——跳过并计数，交上游修。
_PERIOD_RE = re.compile(r"^\d{6}$")


def _rows_from_parquet(out_dir) -> tuple[list[tuple], list[str]]:
    """out/<期次>/ledger_long.parquet → (facts 行, 被跳过的异常期次名单)。

    parquet 的 `source` 在宽表指标上是 NaN（该维度不适用），落库统一成空串——
    `facts` 表该列 NOT NULL，且引擎/视图按 `source=''` 认「宽表指标」。
    缺文件给 ([], [])（不编数）。
    """
    f = pathlib.Path(out_dir) / "ledger_long.parquet"
    if not f.is_file():
        return [], []
    import pandas as pd

    df = pd.read_parquet(f)
    rows, bad = [], set()
    for r in df.itertuples(index=False):
        per = str(r.period)
        if not _PERIOD_RE.match(per):
            bad.add(per)
            continue
        src = getattr(r, "source", "")
        rows.append((
            str(r.discipline),
            per,
            str(r.metric),
            "" if pd.isna(src) else str(src),
            None if pd.isna(r.value) else float(r.value),
        ))
    # 与旧镜像 SQL 的 ORDER BY discipline, period, metric, source 同序
    return sorted(rows, key=lambda t: (t[0], t[1], t[2], t[3])), sorted(bad)


def _table2_rows(out_dir: pathlib.Path, period: str) -> list[tuple]:
    """out/<期次>/table2.csv → report_table2 行。缺文件给 []（不编数）。"""
    import csv

    f = out_dir / "table2.csv"
    if not f.is_file():
        return []
    rows = []
    with open(f, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            def _int(k):
                v = (r.get(k) or "").strip()
                return int(float(v)) if v else None
            def _float(k):
                v = (r.get(k) or "").strip()
                return float(v) if v else None
            rows.append((
                period, (r.get("discipline") or "").strip(),
                r.get("rank_cn_change") or None,
                _int("papers"), _float("cnci"), _int("total_cites"),
                _int("thr_1pct"), _int("thr_1pct_gap"), _int("thr_1permille"),
                _float("permille_rank"),
                _int("top_papers"), r.get("prox_change") or None,
            ))
    return rows


def _overview_rows(out_dir: pathlib.Path, period: str) -> list[tuple]:
    """overview_facts.json → report_overview 键值行（值 json 序列化）。"""
    f = out_dir / "overview_facts.json"
    if not f.is_file():
        return []
    data = json.loads(f.read_text(encoding="utf-8"))
    rows = []
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False)
        else:
            s = "" if v is None else str(v)
        rows.append((period, k, s))
    return rows


def _hash_rows(rows) -> str:
    h = hashlib.sha256()
    for t in rows:
        h.update("\x1f".join("" if v is None else repr(v) for v in t).encode())
        h.update(b"\n")
    return h.hexdigest()


def build(repo_root=REPO, *, out_period=None) -> dict:
    """确定性重建 AI 问数库（原子替换：先写 .tmp 再 os.replace）。

    facts 取自 `out/<期次>/ledger_long.parquet`（main 线 2026-10 重构后台账事实的
    唯一产物面）；缺 parquet 时 facts 为空、其余面照建——**不编数**。
    `out_period` 缺省取 out/ 下最新含 table2.csv 的期次。
    """
    import ledger as ledger_mod
    import period as period_mod
    from parse_ledger import DISCIPLINES_CN, DISCIPLINES_EN

    repo_root = pathlib.Path(repo_root)
    ledger_xlsx = ledger_mod.runtime_path(repo_root)

    if out_period:
        period = str(out_period)
        out_dir = repo_root / "out" / period
    else:
        cands = sorted((d for d in (repo_root / "out").glob("*")
                        if d.is_dir() and (d / "table2.csv").is_file()
                        and d.name[:4].isdigit()),
                       key=lambda d: d.name, reverse=True)
        if not cands:
            period, out_dir = "", repo_root / "out" / "_none"
        else:
            period, out_dir = cands[0].name, cands[0]

    # 维度：学科 / 指标 / 期次
    from flexible.datasource import METRICS
    disc_rows = [(d, DISCIPLINES_CN.get(d, d), i)
                 for i, d in enumerate(DISCIPLINES_EN)]
    metric_rows = [(k, v["cn"], v["better"]) for k, v in METRICS.items()]

    facts, bad_periods = _rows_from_parquet(out_dir)
    periods_all = sorted({r[1] for r in facts})
    filled = set()
    if facts:
        # 「有数据」口径与 period.filled 同源：总被引（source=''）非空即有效
        con_tmp = {}
        for d, p, m, s, v in facts:
            if m == "total_cites" and s == "" and v is not None:
                filled.add(p)
    period_rows = []
    for i, p in enumerate(periods_all):
        y, m = p[:4], p[4:]
        period_rows.append((p, f"{y}年{int(m)}月", i, 1 if p in filled else 0))

    t2 = _table2_rows(out_dir, period)
    ov = _overview_rows(out_dir, period)

    content_rows = ([("schema_version", str(SCHEMA_VERSION)),
                     ("period", period)]
                    + sorted(facts) + sorted(t2) + sorted(ov))
    content_sha = _hash_rows(content_rows)

    target = db_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    try:
        # VACUUM 要落临时文件；若 TEMP 指向不可写目录（如 Windows 上残留的
        # `workbuddy-update-*`），会报 "unable to open database file"。
        # 临时区固定走内存——库本身只有数 MB，且跨机同口径。
        con.execute("PRAGMA temp_store = MEMORY")
        con.executescript(_DDL)
        con.executemany("INSERT OR REPLACE INTO dim_discipline "
                        "(discipline, discipline_cn, ord) VALUES (?,?,?)", disc_rows)
        con.executemany("INSERT OR REPLACE INTO dim_metric "
                        "(metric, metric_cn, better) VALUES (?,?,?)", metric_rows)
        con.executemany("INSERT OR REPLACE INTO dim_period "
                        "(period, label, ord, filled) VALUES (?,?,?,?)", period_rows)
        con.executemany("INSERT OR REPLACE INTO facts "
                        "(discipline, period, metric, source, value) VALUES (?,?,?,?,?)",
                        facts)
        con.executemany("INSERT OR REPLACE INTO report_table2 "
                        "(period, discipline, rank_cn_change, papers, cnci, total_cites,"
                        " thr_1pct, thr_1pct_gap, thr_1permille, permille_rank,"
                        " top_papers, prox_change) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", t2)
        con.executemany("INSERT OR REPLACE INTO report_overview "
                        "(period, key, value) VALUES (?,?,?)", ov)
        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "built_at": _now(),
            "period": period,
            "ledger_sha256": (ledger_mod.sha256(ledger_xlsx)
                              if ledger_xlsx.is_file() else ""),
            "n_facts": str(len(facts)),
            "bad_periods": ",".join(bad_periods),
            "n_table2": str(len(t2)),
            "n_overview": str(len(ov)),
            "content_sha256": content_sha,
        }
        con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                        sorted(meta.items()))
        con.commit()
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    os.replace(tmp, target)
    out = dict(meta)
    out["path"] = str(target)
    return out


def meta(repo_root=REPO) -> dict:
    """读库 meta（键值）；缺库给 {}。"""
    p = db_path(repo_root)
    if not p.is_file():
        return {}
    con = connect_ro(repo_root)
    try:
        return dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()


def verify(repo_root=REPO) -> dict:
    """自校验：meta 存在 + facts 计数一致 + dim 三表非空（有数据时）。"""
    p = db_path(repo_root)
    if not p.is_file():
        return {"ok": False, "reason": f"库不存在：{p}"}
    m = meta(repo_root)
    con = connect_ro(repo_root)
    try:
        n = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        n_disc = con.execute("SELECT COUNT(*) FROM dim_discipline").fetchone()[0]
        n_metric = con.execute("SELECT COUNT(*) FROM dim_metric").fetchone()[0]
        n_period = con.execute("SELECT COUNT(*) FROM dim_period").fetchone()[0]
    finally:
        con.close()
    ok = (str(n) == m.get("n_facts") and n_disc > 0
          and n_metric > 0 and n_period > 0)
    return {"ok": ok, "n_facts": n, "n_discipline": n_disc,
            "n_metric": n_metric, "n_period": n_period,
            "content_sha256": m.get("content_sha256", "")}


# ============================================================ 白名单视图（引擎用）

def view_periods(con: sqlite3.Connection) -> list[str]:
    """全部有数据期次（升序）。"""
    return [r[0] for r in con.execute(
        "SELECT period FROM dim_period WHERE filled=1 ORDER BY ord")]


def view_disciplines(con: sqlite3.Connection) -> list[dict]:
    """学科名单（含中文名，按台账序）。"""
    return [{"discipline": r[0], "discipline_cn": r[1]}
            for r in con.execute(
                "SELECT discipline, discipline_cn FROM dim_discipline ORDER BY ord")]


def view_metrics(con: sqlite3.Connection) -> list[dict]:
    """指标白名单（含中文名与方向）。"""
    return [{"metric": r[0], "metric_cn": r[1], "better": r[2]}
            for r in con.execute(
                "SELECT metric, metric_cn, better FROM dim_metric ORDER BY metric")]


def view_series(con, metric, disc, *, source=None, period_max=None,
                source_alias=None):
    """某学科某指标一列（期次升序）→ [{period, value}]。

    `metric` 是对外指标名（白名单）；排名类按 `_LONG_SPEC` 同款规则映射到
    (metric, source)。`period_max` 切窗（期次 <= 该值）。
    """
    from flexible.datasource import _LONG_SPEC
    if metric in _LONG_SPEC:
        m, src = _LONG_SPEC[metric]
        if source and source != src:
            return []
    else:
        m, src = metric, ""
    q = ("SELECT period, value FROM facts "
         "WHERE metric=? AND source=? AND discipline=?")
    args: list = [m, src, disc]
    if period_max:
        q += " AND period<=?"
        args.append(str(period_max))
    q += " ORDER BY period"
    return [{"period": r[0], "value": r[1]} for r in con.execute(q, args)]


def view_cross(con, metric, period) -> list[dict]:
    """某期某指标跨学科截面（按台账学科序）。"""
    from flexible.datasource import _LONG_SPEC
    if metric in _LONG_SPEC:
        m, src = _LONG_SPEC[metric]
    else:
        m, src = metric, ""
    return [{"discipline": r[0], "discipline_cn": r[1], "value": r[2]}
            for r in con.execute(
                "SELECT f.discipline, d.discipline_cn, f.value "
                "FROM facts f JOIN dim_discipline d ON d.discipline=f.discipline "
                "WHERE f.metric=? AND f.source=? AND f.period=? "
                "ORDER BY d.ord", (m, src, str(period)))]


def log_qa(repo_root, *, user, question, specs, plan_origin, n_rows,
           elapsed_ms, answer_text, chart_kind="") -> int:
    """问数留痕（唯一写口）。库未建 / 写失败 → 返回 -1（不阻塞查询）。"""
    try:
        con = connect_rw(repo_root)
    except Exception:                                          # noqa: BLE001
        return -1
    try:
        cur = con.execute(
            "INSERT INTO qa_log (ts, user, question, specs, plan_origin,"
            " n_rows, elapsed_ms, answer_text, chart_kind) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (_now(), str(user or ""), str(question or ""),
             json.dumps(specs, ensure_ascii=False), str(plan_origin or "rule"),
             int(n_rows or 0), int(elapsed_ms or 0),
             str(answer_text or "")[:500], str(chart_kind or "")))
        con.commit()
        return int(cur.lastrowid)
    except Exception:                                          # noqa: BLE001
        return -1
    finally:
        con.close()
