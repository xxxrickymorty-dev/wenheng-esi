# -*- coding: utf-8 -*-
"""打部署包：代码 + `web/dist` + 演示数据（`out/202607` + `input/`），供 /opt 解包部署。

用法（在 wenheng/ 下，venv 直调）：
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py             # 演示包（含数据，默认脱敏）
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py --no-data   # 纯代码包（只更新代码）
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py --out D:\\wenheng-bundles
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py --no-redact  # 自用备份：不脱敏、不扫描
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py --redact-term 某某=馆员   # 批注里的人名

产物：`<输出目录>/wenheng-demo-YYYYMMDD.tar.gz`（默认输出目录 = 工作区根，与历史包同处），
旁边写同名 `.sha256`。包内顶层固定为 `wenheng/`——服务器上 `tar -C /opt -xzf <包>`
即解出 `/opt/wenheng`（与部署清单 §3 一致）。

进包 / 不进包（口径写死在这里，部署清单 §0 引用本文件）：
    进：pyproject.toml、CONTEXT.md、GLOSSARY.md、AGENTS.md、docs/、src/、server/、tools/、tests/、
        master/、web/dist/；演示包另加 input/（只放母本）、out/202607/（剔除 _superseded）、
        out/_acquisition/（取数状态 + 当期核对副本）、
        out/_jobs/（progress.jsonl / console.log / forecast_choice.json；任务记录本身已在
        `out/_state` 的 `jobs` 表里，这里不再有 job.json）、
        out/_state/（系统状态库：签单 / 复核 / 任务记录；打包前先 `wal_checkpoint(TRUNCATE)`）
    不进：server/.env（密钥）、web/node_modules/、__pycache__/、.pytest_cache/、
        .ruff_cache/、tmp/、.git/、_superseded/、out/ 其它期次、
        **out/_state/backups/（库的备份副本，含已清理的 e2e 历史；连同 -wal/-shm 一起不进包）**

演示包脱敏（2026-10-22；ADR-0012 后果段 / spec「打包脱敏」一节）：
    **外发演示包 = 外发人名**——`out/_state` 的 `actor` 列、`payload` 里的操作人、
    `out/` 与 `input/` 下数据文件里的 `actor` / `by` / `operator` 字段、`审批记录.md` 正文
    都带真实操作人。落包前做三件事，**真库一个字节都不碰**：
      ① 用 sqlite **backup API** 把主库复制到临时目录（不复制活库文件：WAL 未 checkpoint 时
         读到的是不一致快照），对**副本**替换所有文本列（`admin` → `管理员`，其余 → `馆员`；
         不是清空——演示要能看出「有人签过」），再 `VACUUM`，旧页里的原文不留；
      ② 包内每一份 `out/<期次>/审批记录.md` 用**脱敏后的库**重渲染（复用
         `server/approval.py::_write_record`，不另写一份），替换包内原件；
      ③ `out/`、`input/` 下的文本数据（.md / .json / .jsonl / .log / .csv …）同样替换。
    签单失效（`stale`）语义不受影响：指纹是对 `out/<期次>/` 的产物取 sha256，与 actor 无关。
    打包完成后按**脱敏前**采集的真实操作人名扫一遍包：数据面（`out/`、`input/`）逐个成员按字节扫、
    库另按文本列逐格扫、非 ASCII 词（真实姓名，不是 `admin`/`demo` 这类角色标识）全包扫。
    命中即删包失败并列出 member × 次数——判据是「一个真名都不剩」，不是「改了几个字段」。
    `--no-redact` 显式关闭脱敏（**同时关闭扫描**：这种包只能自用、不能外发，脚本会喊一声）。

预检（缺了直接失败——别等服务器上才白屏）：
    · `web/dist/index.html` + `web/dist/assets/`（/app 首屏，ADR-0001 要求随包带）
    · `master/` 母版 docx（fill_docx 依赖）
    · 演示包另查 `out/202607/` 首屏四件（red_slots / overview_facts / 报告初稿）与
      `input/云大全学科排名、阈值动态检测表.xlsx`（母本；并与馆员原件核对 sha）
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent      # wenheng/
sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:                              # server/ 是真包（`server.approval`）
    sys.path.insert(0, str(ROOT))

import ledger as ledger_mod  # noqa: E402
import state_store  # noqa: E402
from server import approval as approval_mod  # noqa: E402

DATA_PERIOD = "202607"                                     # 演示数据期次（首屏依赖）

INCLUDE_DIRS = ("docs", "src", "server", "tools", "tests", "master")
INCLUDE_FILES = ("pyproject.toml", "CONTEXT.md", "GLOSSARY.md", "AGENTS.md")

#: 任何一层目录名命中即排除（不看大小写）。
EXCLUDE_PARTS = frozenset({
    ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".git", "tmp", "_superseded", ".idea", ".vscode",
})
#: 文件名命中即排除（密钥 / 生成物；`server/.env.example` 不在其中，要进包）。
EXCLUDE_NAMES = frozenset({".env", "e2e_report.txt"})
#: 状态库备份目录（相对仓库根）：含已清理的 e2e 历史，只该留在本机。
STATE_BACKUP_REL = ("out", "_state", "backups")

#: 化名规则：要能看出「有人签过」，所以不清空，按角色换成化名（spec「打包脱敏」一节）。
ACTOR_ALIAS = {"admin": "管理员"}
DEFAULT_ACTOR_ALIAS = "馆员"
#: 已经算化名的词：真实操作人恰好叫这个就不再映射（否则 管理员 → 馆员）。
ALIAS_NAMES = frozenset(ACTOR_ALIAS.values()) | {DEFAULT_ACTOR_ALIAS}

#: 脱敏与扫描覆盖的**数据面**（相对仓库根）。代码与文档里的 `admin` / `demo` 是角色标识与文案，
#: 不是人名——把它们也算命中，闸门会永远红。
DATA_PREFIXES = ("out", "input")
#: 会被逐字替换的文本扩展名。**未知扩展名不替换**是有意的：漏掉就是漏掉，
#: 由泄漏扫描兜住并让打包失败，而不是悄悄放过。
TEXT_SUFFIXES = frozenset({
    ".md", ".json", ".jsonl", ".csv", ".tsv", ".txt", ".log", ".yaml", ".yml",
    ".html", ".js", ".css", ".ini", ".cfg", ".toml", ".example",
})

#: 库里可能出现操作人的列 / payload 字段（`SELECT DISTINCT` 取真实名单）。
_ACTOR_QUERIES = (
    "SELECT DISTINCT actor FROM approvals",
    "SELECT DISTINCT actor FROM approval_history",
    "SELECT DISTINCT actor FROM manual_inputs",
    "SELECT DISTINCT json_extract(payload, '$.actor') FROM jobs",
    "SELECT DISTINCT json_extract(payload, '$.by') FROM reviews",
)


class LeakError(RuntimeError):
    """包里还留着真实操作人：删包、失败退出（ADR-0012 后果段那条的验收判据）。"""

    def __init__(self, hits):
        self.hits = list(hits)
        super().__init__(f"包内仍有真实操作人：{len(self.hits)} 处")


def _excluded(rel: pathlib.Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in rel.parts):
        return True
    # 主库仍进包（ADR-0012 决定 11），备份副本不进——包是演示件，不是机房快照。
    if rel.parts[:len(STATE_BACKUP_REL)] == STATE_BACKUP_REL:
        return True
    return rel.name in EXCLUDE_NAMES


def _tree_files(base: pathlib.Path, root: pathlib.Path) -> list[pathlib.Path]:
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*")
            if p.is_file() and not _excluded(p.relative_to(root))]


def collect(root: pathlib.Path, include_data: bool = True) -> list[pathlib.Path]:
    """要进包的文件（绝对路径），已按排除表过滤，按相对路径排序。"""
    files: list[pathlib.Path] = []
    for d in INCLUDE_DIRS:
        files += _tree_files(root / d, root)
    for f in INCLUDE_FILES:
        p = root / f
        if p.is_file() and not _excluded(p.relative_to(root)):
            files.append(p)
    files += _tree_files(root / "web" / "dist", root)
    if include_data:
        files += _tree_files(root / "input", root)
        files += _tree_files(root / "out" / DATA_PERIOD, root)
        files += _tree_files(root / "out" / "_acquisition", root)
        files += _tree_files(root / "out" / "_jobs", root)
        # 系统状态库（签单/复核，ADR-0012）：与 _jobs 同级，不跟期次走。
        files += _tree_files(root / "out" / "_state", root)
    return sorted(set(files), key=lambda p: str(p.relative_to(root)))


def state_db(root: pathlib.Path) -> pathlib.Path:
    """仓库里的主状态库路径（唯一口径在 `state_store.db_path`）。"""
    return root / "out" / "_state" / state_store.DB_NAME


def checkpoint_state_db(root: pathlib.Path) -> None:
    """打包前把状态库的 WAL 并回主文件（`wal_checkpoint(TRUNCATE)`）。

    🔴 少了这一步，包里只有主文件、没有 `-wal`，最近的事务会**静默消失**（部署后
    「刚签的单子不见了」）。服务还开着时 checkpoint 可能 busy——那就明说，别装作成功：
    此时 `-wal` 会随目录一起进包，SQLite 解包后仍会重放，包不会丢数据。
    """
    db = state_db(root)
    if not db.is_file():
        return
    con = sqlite3.connect(str(db), timeout=5.0)
    try:
        busy = 1
        for _ in range(3):
            busy, _log, _done = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if not busy:
                break
            time.sleep(0.2)
    finally:
        con.close()
    if busy:
        print("[警告] 状态库 WAL 仍被占用（演示站开着？）——包里会连 -wal 一起带，"
              "SQLite 会重放；要干净的包请先停服务再打")


# --------------------------------------------------------------- 脱敏
def _copy_db(src: pathlib.Path, dst: pathlib.Path) -> None:
    """sqlite **backup API** 复制主库。

    🔴 不复制活库文件：WAL 里有未 checkpoint 的帧时，复制到的文件与 `-wal` 拼起来
    才是一致快照，单拿主文件就是半截状态。backup API 读的是连接看到的一致视图。
    只读连接读 WAL 库时会建 `-shm`（读连接删不掉它）；打包脚本只该留下库里原有的东西，
    所以**本次新建的副文件收尾时清掉**——不清就会随着 `collect()` 混进包（也不该动真库目录）。
    """
    side = [pathlib.Path(str(src) + suffix) for suffix in ("-wal", "-shm")]
    existed = {p for p in side if p.is_file()}
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(str(dst))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
        for p in side:
            if p in existed:
                continue
            if p.name.endswith("-wal") and p.is_file() and p.stat().st_size > 0:
                continue                       # 有帧＝别人的 WAL，别删（会丢事务）
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass                           # 服务正占着（Windows 句柄）——留着，别硬删


def _text_columns(con, table: str) -> list[str]:
    """表的文本列（按声明类型判；INTEGER / REAL / BLOB 列不碰）。"""
    cols = []
    for row in con.execute(f'PRAGMA table_info("{table}")'):
        decl = (row[2] or "").upper()
        if any(t in decl for t in ("INT", "REAL", "FLOA", "DOUB", "BLOB")):
            continue
        cols.append(row[1])
    return cols


def _real_actors(db_path) -> list[str]:
    """库里出现过的真实操作人（三张表的 actor 列 + jobs / reviews 的 payload 字段）。

    老 schema 缺表、坏 JSON 查不了这条就跳过（**读口不猜**）；空串与化名本身不算。
    排序从长到短——替换时先换长词，避免「子串先被换掉」。
    """
    path = pathlib.Path(db_path)
    if not path.is_file():
        return []
    names: set[str] = set()
    con = sqlite3.connect(str(path))
    try:
        for sql in _ACTOR_QUERIES:
            try:
                rows = con.execute(sql).fetchall()
            except sqlite3.Error:
                continue
            names |= {str(r[0]) for r in rows if r[0] not in (None, "")}
    finally:
        con.close()
    return sorted((n for n in names if n not in ALIAS_NAMES), key=len, reverse=True)


def redaction_terms(db_path, extra_terms=()) -> dict[str, str]:
    """真实操作人 → 化名；`extra_terms` 是 `词` 或 `词=化名`（自由文本里的人名等，默认换「馆员」）。"""
    terms = {actor: ACTOR_ALIAS.get(actor, DEFAULT_ACTOR_ALIAS) for actor in _real_actors(db_path)}
    terms.update(_extra_terms(extra_terms))
    return terms


def _extra_terms(extra_terms) -> dict[str, str]:
    """`--redact-term` 的额外词（库不在也要能换：那批词不依赖库）。"""
    terms: dict[str, str] = {}
    for raw in extra_terms:
        term, _, alias = str(raw).partition("=")
        term, alias = term.strip(), alias.strip()
        if term:
            terms.setdefault(term, alias or DEFAULT_ACTOR_ALIAS)
    return terms


def _ordered_terms(terms) -> list[tuple[str, str]]:
    return sorted(terms.items(), key=lambda kv: len(kv[0]), reverse=True)


def redact_text(text: str, terms) -> str:
    """逐词替换（长词先换）。"""
    for term, alias in _ordered_terms(terms):
        if term in text:
            text = text.replace(term, alias)
    return text


def redact_db(db_path, terms) -> int:
    """对**副本库**脱敏：所有文本列替换，然后 `VACUUM`（旧页里的原文不留）。返回改动的行数。"""
    if not terms:
        return 0
    con = sqlite3.connect(str(db_path))
    changed = 0
    try:
        con.execute("PRAGMA journal_mode=DELETE")          # 副本不跟 -wal 走
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            for column in _text_columns(con, table):
                for term, alias in _ordered_terms(terms):
                    cur = con.execute(
                        f'UPDATE "{table}" SET "{column}" = replace("{column}", ?, ?)'
                        f' WHERE instr("{column}", ?) > 0',
                        (term, alias, term))
                    changed += max(cur.rowcount or 0, 0)
        con.commit()
        con.execute("VACUUM")                              # 重建文件：自由页里的原文也清掉
    finally:
        con.close()
    for suffix in ("-wal", "-shm"):
        pathlib.Path(str(db_path) + suffix).unlink(missing_ok=True)
    return changed


@contextlib.contextmanager
def _state_db_env(db_path):
    """让 `server/approval.py` 读/写到指定库（它走 `state_store.db_path()`，env 优先）。"""
    old = os.environ.get(state_store.ENV_VAR)
    os.environ[state_store.ENV_VAR] = str(db_path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(state_store.ENV_VAR, None)
        else:
            os.environ[state_store.ENV_VAR] = old


def _render_records(root: pathlib.Path, files, db_copy: pathlib.Path,
                    stage: pathlib.Path) -> dict[pathlib.Path, pathlib.Path]:
    """包里每份 `out/<期次>/审批记录.md` 用脱敏后的库重渲染（复用签单时的渲染函数）。"""
    mapping: dict[pathlib.Path, pathlib.Path] = {}
    for f in files:
        rel = f.relative_to(root)
        if f.name != approval_mod.RECORD_NAME or rel.parts[:1] != ("out",) or len(rel.parts) != 3:
            continue
        stage_dir = stage / rel.parent
        stage_dir.mkdir(parents=True, exist_ok=True)
        for pattern in approval_mod.FINGERPRINT_GLOBS:      # 让 stale 判定与真目录一致
            for src in f.parent.glob(pattern):
                shutil.copy2(src, stage_dir / src.name)
        with _state_db_env(db_copy):
            rec = approval_mod.read(stage_dir)
            approval_mod._write_record(stage_dir, rec)
        mapping[f] = stage_dir / approval_mod.RECORD_NAME
    return mapping


def _redact_file(src: pathlib.Path, dst: pathlib.Path, terms) -> bool:
    """把一份数据文本的替换结果写到 `dst`；没变化返回 False（原件直接进包）。"""
    raw = src.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    new = redact_text(text, terms)
    if new == text:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(new.encode("utf-8"))
    return True


def stage_redacted(root: pathlib.Path, files, stage: pathlib.Path,
                   extra_terms=()) -> tuple[dict[pathlib.Path, pathlib.Path], dict[str, str], int]:
    """把要替换的文件落到临时目录，返回 `(原件→替换件, 词→化名, 改动的行数)`。

    只碰**副本**：主库走 backup API 复制（真库只读一次，名单也从副本上取），
    数据文本按 `TEXT_SUFFIXES` 换一份，`审批记录.md` 用脱敏库重渲染。
    真库、真产物一个字节都不动。
    """
    mapping: dict[pathlib.Path, pathlib.Path] = {}
    db = state_db(root)
    copy = stage / "out" / "_state" / state_store.DB_NAME
    if db.is_file():
        _copy_db(db, copy)
        terms = redaction_terms(copy, extra_terms)      # 名单从副本取：真库只读，不开写口
    else:
        terms = _extra_terms(extra_terms)               # 库不在，至少把追加词换掉
    rows = 0
    if terms and db.is_file():
        rows = redact_db(copy, terms)
        mapping[db] = copy
        mapping.update(_render_records(root, files, copy, stage))
    for f in files:
        if f in mapping:
            continue
        rel = f.relative_to(root)
        if rel.parts[:1] not in {(p,) for p in DATA_PREFIXES}:
            continue
        if f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if _redact_file(f, stage / rel, terms):
            mapping[f] = stage / rel
    return mapping, terms, rows


# --------------------------------------------------------------- 泄漏扫描
def _data_member(name: str) -> bool:
    return any(name.startswith(f"wenheng/{p}/") for p in DATA_PREFIXES)


def _scan_sqlite(raw: bytes, workdir: pathlib.Path, member: str, terms) -> list[dict]:
    """库内**所有文本列**逐格找（能报到表.列）；再比字节命中数，抓自由页残留。"""
    path = workdir / "scan.sqlite"
    path.write_bytes(raw)
    con = sqlite3.connect(str(path))
    hits: list[dict] = []
    seen_bytes = {term: 0 for term in terms}
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            for column in _text_columns(con, table):
                for term in terms:
                    needle = term.encode("utf-8")
                    rows = con.execute(
                        f'SELECT "{column}" FROM "{table}" WHERE instr("{column}", ?) > 0',
                        (term,)).fetchall()
                    if not rows:
                        continue
                    texts = [str(r[0]) for r in rows]
                    hits.append({"member": member, "where": f"{table}.{column}",
                                 "term": term,
                                 "count": sum(t.count(term) for t in texts)})
                    seen_bytes[term] += sum(t.encode("utf-8").count(needle) for t in texts)
    finally:
        con.close()
    for term in terms:
        raw_n = raw.count(term.encode("utf-8"))
        if raw_n > seen_bytes[term]:                        # VACUUM 之后不该有；有就是真的漏了
            hits.append({"member": member, "where": "文件字节（自由页残留）",
                         "term": term, "count": raw_n - seen_bytes[term]})
    return hits


def scan_package(pkg: pathlib.Path, terms) -> list[dict]:
    """包里还有没有真实操作人。`terms` 的**键**是脱敏前采集的真实名字。

    - 数据面（`out/`、`input/`）的每个成员按 UTF-8 字节扫，`.sqlite` 另按文本列逐格扫；
    - 非 ASCII 的词（真实姓名，不是 `admin` / `demo` 这类角色标识）**全包扫**：
      代码与文档里出现人名同样是外发人名；
    - `.docx` / `.parquet` 这类压缩/二进制内容扫不到——它们是产物，不是操作人记录。
    返回 `[{member, where?, term, count}]`（空 = 干净）。
    """
    ascii_terms = {t for t in terms if t.isascii()}
    name_terms = {t for t in terms if not t.isascii()}
    hits: list[dict] = []
    with tarfile.open(pkg) as tf, tempfile.TemporaryDirectory(prefix="wenheng-scan-") as td:
        workdir = pathlib.Path(td)
        for member in tf.getmembers():
            if not member.isfile():
                continue
            scope = set(name_terms)
            if _data_member(member.name):
                scope |= ascii_terms
            if not scope:
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            raw = handle.read()
            if member.name.endswith(".sqlite"):
                hits += _scan_sqlite(raw, workdir, member.name, scope)
                continue
            for term in sorted(scope):
                n = raw.count(term.encode("utf-8"))
                if n:
                    hits.append({"member": member.name, "term": term, "count": n})
    return hits


# --------------------------------------------------------------- 预检 / 打包
def preflight(root: pathlib.Path, include_data: bool = True) -> list[str]:
    """返回问题清单（空 = 可以打包）。缺件宁可现在失败，也别让首屏白屏。"""
    problems = []
    if not (root / "web" / "dist" / "index.html").is_file():
        problems.append("web/dist/index.html 缺失 —— 先在前端跑 npm run build "
                        "（服务器不装 Node，dist 必须随包带）")
    if not (root / "web" / "dist" / "assets").is_dir():
        problems.append("web/dist/assets/ 缺失 —— 同上，构建产物不完整")
    if not list((root / "master").glob("*.docx")):
        problems.append("master/ 母版 docx 缺失 —— 流水线 fill_docx 依赖它")
    if include_data:
        for rel in (f"out/{DATA_PERIOD}/red_slots.json",
                    f"out/{DATA_PERIOD}/overview_facts.json",
                    f"input/{ledger_mod.LEDGER_NAME}"):
            if not (root / rel).is_file():
                problems.append(f"{rel} 缺失 —— 演示包首屏依赖它（或改走 --no-data）")
        if not list((root / "out" / DATA_PERIOD).glob("报告初稿*.docx")):
            problems.append(f"out/{DATA_PERIOD}/报告初稿*.docx 缺失 —— 对勘本要有成品可读")
        # 运行时母本必须与馆员原件一致（否则包里的输入是旧的；并入后记得 sync）。
        rt = ledger_mod.runtime_path(root)
        src = ledger_mod.source_path(root)
        if rt.is_file() and src.is_file() and \
                ledger_mod.sha256(rt) != ledger_mod.sha256(src):
            problems.append("input/ 母本与 数据与复现 馆员原件不一致 —— "
                            "先跑 uv run python tools\\sync_input_ledger.py（或 acquire merge 自动同步）")
    return problems


def build(root: pathlib.Path, outdir: pathlib.Path, include_data: bool = True,
          name: str | None = None, *, redact: bool = True,
          extra_terms=()) -> pathlib.Path:
    """打包并写 `.sha256`，返回 tar.gz 路径（预检请先自行调用 preflight）。

    演示包默认脱敏：主库只经 backup API 复制后改动，包里落的是副本；打完后扫泄漏，
    命中就删包并抛 `LeakError`（**不留带名字的包**）。
    """
    if include_data:
        checkpoint_state_db(root)                    # 先并 WAL，再列文件
    files = collect(root, include_data)
    outdir.mkdir(parents=True, exist_ok=True)
    name = name or f"wenheng-{'demo' if include_data else 'deploy'}-{time.strftime('%Y%m%d')}.tar.gz"
    pkg = outdir / name
    terms: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="wenheng-pkg-") as td:
        stage = pathlib.Path(td)
        mapping: dict[pathlib.Path, pathlib.Path] = {}
        if include_data and redact:
            mapping, terms, rows = stage_redacted(root, files, stage, extra_terms)
            if terms:
                db = state_db(root)
                aliases = "、".join(f"{k} → {v}" for k, v in _ordered_terms(terms))
                db_note = f"已脱敏 {rows} 处（VACUUM）" if db in mapping else "不在，未复制"
                text_n = sum(1 for k in mapping if k != db)
                print(f"[脱敏] 真实操作人/指定词 {len(terms)} 个：{aliases}")
                print(f"[脱敏] 库副本：{db_note}；数据文本替换 {text_n} 个文件")
            else:
                print("[脱敏] 库里没有采集到真实操作人名——无名字可换，扫描也无从判"
                      "（要换批注里的人名请用 --redact-term）")
        with tarfile.open(pkg, "w:gz") as tf:
            for f in files:
                src = mapping.get(f, f)
                tf.add(src, arcname=str(pathlib.Path("wenheng") / f.relative_to(root)),
                       recursive=False)
        if include_data and redact:
            hits = scan_package(pkg, terms)
            if hits:
                pkg.unlink(missing_ok=True)
                (outdir / (name + ".sha256")).unlink(missing_ok=True)
                raise LeakError(hits)
            print(f"[检查] 泄漏扫描：0 命中（判据：脱敏前的真实操作人名 {len(terms)} 个）")
    digest = hashlib.sha256(pkg.read_bytes()).hexdigest()
    (outdir / (name + ".sha256")).write_text(f"{digest}  {name}\n", encoding="utf-8")
    return pkg


def git_dirty(root: pathlib.Path) -> bool:
    """工作区有没有未提交改动（有则包里带的是在途代码——打包前该知道）。"""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return False
    return bool(r.stdout.strip())


def _report_leaks(hits) -> None:
    print(f"[失败] 包内仍有真实操作人：{len(hits)} 处（包已删除，别外发）")
    for hit in hits:
        where = f"（{hit['where']}）" if hit.get("where") else ""
        print(f"  · {hit['member']}{where}：{hit['term']} × {hit['count']}")
    print("  → 脱敏没覆盖到的位置请看 tools/make_deploy_pkg.py 的 TEXT_SUFFIXES / DATA_PREFIXES；"
          "自由文本里的姓名用 --redact-term 追加")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="文衡部署包（代码 + web/dist + 演示数据）")
    ap.add_argument("--no-data", action="store_true",
                    help="纯代码包（不含 input/ 与 out/，只更新代码）")
    ap.add_argument("--out", default=None, help="输出目录（默认：工作区根）")
    ap.add_argument("--name", default=None, help="包名（默认按日期生成）")
    ap.add_argument("--no-redact", dest="redact", action="store_false", default=None,
                    help="不脱敏、也不做泄漏扫描（只给自用备份；这种包带真实操作人名，不能外发）")
    ap.add_argument("--redact", dest="redact", action="store_true", default=None,
                    help="脱敏（默认；包里有 out/_state 就该脱敏）")
    ap.add_argument("--redact-term", action="append", default=[], metavar="词[=化名]",
                    help="额外要替换的词（自由文本里的真人姓名等），可重复；化名默认「馆员」")
    a = ap.parse_args(argv)

    include_data = not a.no_data
    redact = True if a.redact is None else a.redact
    problems = preflight(ROOT, include_data)
    if problems:
        for p in problems:
            print(f"[失败] {p}")
        return 1

    if git_dirty(ROOT):
        print("[警告] 工作区有未提交改动 —— 包里带的是在途代码，"
              "要打正式包先 commit（或确认这就是你要发的版本）")
    if include_data and not redact and state_db(ROOT).is_file():
        print("[警告] --no-redact：包里会带上真实操作人名（库 actor 列 / 审批记录.md / 数据文件），"
              "**这个包不能外发**；本次不做泄漏扫描。")

    outdir = pathlib.Path(a.out) if a.out else ROOT.parent
    try:
        pkg = build(ROOT, outdir, include_data=include_data, name=a.name,
                    redact=redact, extra_terms=a.redact_term)
    except LeakError as exc:
        _report_leaks(exc.hits)
        return 1
    files = collect(ROOT, include_data)
    size_mb = pkg.stat().st_size / 1e6
    print(f"已打 {pkg}")
    print(f"  {size_mb:.1f} MB · {len(files)} 个文件 · sha256 见 {pkg.name}.sha256")
    print(f"  解包：tar -C /opt -xzf {pkg.name}  →  /opt/wenheng")
    return 0


if __name__ == "__main__":
    sys.exit(main())
