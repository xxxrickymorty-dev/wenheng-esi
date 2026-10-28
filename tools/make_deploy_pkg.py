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
        out/_state/（系统状态库：签单 / 复核 / 任务记录；打包前先 `wal_checkpoint(TRUNCATE)`）、
        out/_aidata/（AI 问数库 aiqa.sqlite；期次须与 DATA_PERIOD 一致，preflight 会卡）
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

    自由文本里的人名**先清源头**（`tools/state_cleanup.py scrub-note`：备份 + 留痕 + 只改
    `payload` 一列，2026-10-22 起 202609 那条批注已清空）；`--redact-term` 是出口兜底，
    不是这件事的常规解法。

    路径与用户名（2026-10-22 第二票；判据在 `_path_checks` 与 `path_rules`）：
    同一次外发里另一类不该出现的东西是**本机绝对路径**——`C:\\Users\\<用户名>\\Desktop\\…`
    既暴露开发机账号，换个用户名/换台机器也不成立。处理与 actor 同一套「先换、再扫、漏了失败」：
      · 换：包内**副本**上把「本仓库根」前缀去掉（`out/202607/x.json` 仍指得回原处）、
        把「本机家目录」前缀换成 `~/`；数据面文本与库内所有文本列都过一遍；
      · 扫：两档范围，理由是**误伤边界不一样**——
        ① 通用形态（盘符 `C:\\` / `C:/`、`/home/`、`/Users/`）**只扫数据面 + 库内文本列**：
           代码与文档里合法地写这类前缀（docstring 举例、`.bat` 占位说明）不是泄漏；
        ② 本机实际路径（本仓库根的绝对写法、`%USERPROFILE%` / `$HOME` 展开后的家目录）
           **全包扫**：任何成员里出现这两个前缀都是本机信息，没有"合法举例"这回事。
    实测依据（定判据前跑过一遍现有仓库）：通用形态若全包扫，`tools/*.py` 里 7 处硬编码的
    开发机根目录会当场让打包失败——那批路径本身就是本机信息，已在本票里改成从 `__file__`
    推导；而扫描按上面两档分范围后，现有 950 个成员的包全绿（0 命中）。

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
import json
import os
import pathlib
import re
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

#: 「本机绝对路径」的**通用形态**：盘符（`C:\` / `C:/`）与类 Unix 的家目录前缀。
#: 前一个字符是字母数字时不算——`http://` 里的 `p:/` 不是盘符。
DRIVE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
UNIX_HOME_RE = re.compile(r"(?:(?<=^)|(?<=[\s\"'(=:：,，]))/(?:home|Users)/[A-Za-z0-9._-]+")

#: 通用形态的扫描范围：**只扫数据面 + 库内文本列**。
#: 代码与文档里合法地写 `C:/Users/xxx`（docstring 举例）不算泄漏；数据里出现就是漏了。
PATH_SCOPE_DATA = "data"
#: 本机实际路径的扫描范围：**全包**（代码里出现同样是把本机信息带出去）。
PATH_SCOPE_ALL = "all"


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
        # AI 问数库（out/_aidata/aiqa.sqlite）：同样不跟期次走——缺它「AI 问数」页
        # 只会回一句 503。`*.tmp` 是建库原子替换的中间态，进包没意义，剔掉。
        files += [p for p in _tree_files(root / "out" / "_aidata", root)
                  if p.suffix != ".tmp"]
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


def _sep_re(p) -> str:
    """把一个路径写成「分隔符两种都认」的正则片段（`[\\/]+` 顺带吃掉 JSON 里的 `\\\\`）。"""
    parts = re.split(r"[\\/]+", str(p).strip("\\/"))
    return r"[\\/]+".join(re.escape(part) for part in parts)


def _sep_forms(p) -> list[bytes]:
    """一个路径的两种字面写法（`\\` 与 `/`），给按字节扫用。"""
    text = str(p)
    return [text.encode("utf-8"), text.replace("\\", "/").encode("utf-8")]


def path_rules(root: pathlib.Path):
    """本机绝对路径 → 包内写法：**只对副本**，真库/真产物一个字节不动。

    两条规则，**长的先换**（仓库根通常在家目录之下，反过来会留下 `~/…/wenheng`）：
      · 本仓库根 + 分隔符 → 空（`C:\\…\\wenheng\\out\\x.json` → `out/x.json`）。
        去掉前缀后包内相对写法仍指得回原处（部署机的根是 `/opt/wenheng`）；
      · 本机家目录 + 分隔符 → `~/`（`C:\\Users\\<用户名>\\AppData\\…` → `~/AppData/…`）。
    没被这两条覆盖的盘符路径（别的盘、`D:\\`）字面保留，由泄漏扫描兜住并让打包失败。
    """
    home = pathlib.Path.home()
    rules = []
    for base, repl in ((pathlib.Path(root), ""), (home, "~/")):
        pattern = re.compile(_sep_re(base) + r"[\\/]+",
                             re.IGNORECASE if os.name == "nt" else 0)
        rules.append((pattern, repl))
    return rules


def redact_text(text: str, terms, rules=()) -> str:
    """本机路径先换（含用户名的那段整块去掉），再逐词换操作人（长词先换）。"""
    for pattern, repl in rules:
        text = pattern.sub(repl, text)
    for term, alias in _ordered_terms(terms):
        if term in text:
            text = text.replace(term, alias)
    return text


def _portable_path(text: str, root: pathlib.Path) -> str:
    """一个**绝对路径值** → 包内写法（仓库相对 posix / `~/…`）；其余原样返回。

    与 `path_rules` 的区别：这里改的是**整个字段值**，所以能顺手把分隔符归一成 `/`
    —— 库随包搬到 Linux 后 `out\\_jobs\\j1\\progress.jsonl` 会被当成一个文件名，
    反斜杠在那里不是分隔符。日志/正文里只做前缀替换（`path_rules`），不碰分隔符。
    """
    for base, prefix in ((pathlib.Path(root), ""), (pathlib.Path.home(), "~/")):
        for form in (str(base), str(base).replace("\\", "/")):
            if not text.casefold().startswith(form.casefold()):
                continue
            rest = text[len(form):].lstrip("\\/").replace("\\", "/")
            return prefix + rest
    return text


def _walk_paths(obj, root: pathlib.Path):
    """递归把 JSON 里的绝对路径值换成包内写法（`jobs.payload` 的 `stats.input` 是嵌两层的那种）。"""
    if isinstance(obj, str):
        return _portable_path(obj, root)
    if isinstance(obj, list):
        return [_walk_paths(item, root) for item in obj]
    if isinstance(obj, dict):
        return {key: _walk_paths(value, root) for key, value in obj.items()}
    return obj


def _redact_job_paths(con, root: pathlib.Path) -> int:
    """`jobs.payload` 的路径字段（`input` / `progress` / `console` / `stats.*`）换包内写法。

    为什么不靠 `path_rules` 的正则一把梭：那只能换掉前缀，剩下的分隔符还是 Windows 的，
    Linux 上读不出来——JSON 里是**值**，可以整串归一，就按值改。
    """
    changed = 0
    for rowid, payload in con.execute("SELECT rowid, payload FROM jobs").fetchall():
        try:
            rec = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        new = _walk_paths(rec, root)
        if new == rec:
            continue
        con.execute("UPDATE jobs SET payload=? WHERE rowid=?",
                    (json.dumps(new, ensure_ascii=False), rowid))
        changed += 1
    return changed


def redact_db(db_path, terms, rules=(), root=None) -> int:
    """对**副本库**脱敏：所有文本列改写（操作人 → 化名、本机路径 → 包内写法），
    然后 `VACUUM`（旧页里的原文不留）。返回改动的行数。

    逐行读改写而不是 `UPDATE … replace()`：路径要按正则换（两种分隔符、前后缀），
    SQL 的 `replace` 做不到；行数只有百级，代价可忽略。
    `root` 给定时另跑一遍 `_redact_job_paths`（任务记录的路径值要整串归一成 posix）。
    """
    if not terms and not rules and root is None:
        return 0
    con = sqlite3.connect(str(db_path))
    changed = 0
    try:
        con.execute("PRAGMA journal_mode=DELETE")          # 副本不跟 -wal 走
        if root is not None:
            try:
                changed += _redact_job_paths(con, pathlib.Path(root))
            except sqlite3.Error:                          # 老库缺 jobs 表
                pass
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            for column in _text_columns(con, table):
                rows = con.execute(
                    f'SELECT rowid, "{column}" FROM "{table}"').fetchall()
                for rowid, value in rows:
                    if not isinstance(value, str) or not value:
                        continue
                    new = redact_text(value, terms, rules)
                    if new == value:
                        continue
                    con.execute(
                        f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (new, rowid))
                    changed += 1
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


def _redact_file(src: pathlib.Path, dst: pathlib.Path, terms, rules=()) -> bool:
    """把一份数据文本的替换结果写到 `dst`；没变化返回 False（原件直接进包）。"""
    raw = src.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    new = redact_text(text, terms, rules)
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

    本机路径（`path_rules`）与操作人**共用**这条管线，但开关分得开：库里没有真实操作人时
    名字不换，路径照样要换——老的 `jobs.payload` 里存的就是绝对路径。
    """
    mapping: dict[pathlib.Path, pathlib.Path] = {}
    db = state_db(root)
    copy = stage / "out" / "_state" / state_store.DB_NAME
    rules = path_rules(root)
    if db.is_file():
        _copy_db(db, copy)
        terms = redaction_terms(copy, extra_terms)      # 名单从副本取：真库只读，不开写口
    else:
        terms = _extra_terms(extra_terms)               # 库不在，至少把追加词换掉
    rows = 0
    if db.is_file():
        rows = redact_db(copy, terms, rules, root)
        mapping[db] = copy
        if terms:
            mapping.update(_render_records(root, files, copy, stage))
    for f in files:
        if f in mapping:
            continue
        rel = f.relative_to(root)
        if rel.parts[:1] not in {(p,) for p in DATA_PREFIXES}:
            continue
        if f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if _redact_file(f, stage / rel, terms, rules):
            mapping[f] = stage / rel
    return mapping, terms, rows


# --------------------------------------------------------------- 泄漏扫描
def _data_member(name: str) -> bool:
    return any(name.startswith(f"wenheng/{p}/") for p in DATA_PREFIXES)


def _path_checks(root: pathlib.Path | None = None) -> list[dict]:
    """要扫的「绝对路径 / 本机信息」判据：`[{label, scope, literal?/pattern?}]`。

    两档范围（理由写在模块头「路径与用户名」）：
      · `PATH_SCOPE_ALL`——本机实际路径（仓库根与家目录的两种字面写法）：全包扫。
        代码里写死开发机根目录同样是外发本机信息（`tools/*.py` 那 7 处就是这么来的）。
      · `PATH_SCOPE_DATA`——通用形态（盘符 / `/home/` / `/Users/`）：只扫数据面与库。
        代码/文档里的 `C:\\Users\\xxx` 是举例与占位，不是泄漏。
    """
    base = pathlib.Path(root) if root is not None else ROOT
    home = pathlib.Path.home()
    checks: list[dict] = []
    for label, path in (("本机工作区路径", base), ("本机用户目录", home)):
        for form in dict.fromkeys(_sep_forms(path)):      # 无反斜杠的路径两种写法相同，别重复报
            checks.append({"label": label, "scope": PATH_SCOPE_ALL, "literal": form})
    for label, pattern in (("盘符路径", DRIVE_RE), ("用户目录路径", UNIX_HOME_RE)):
        checks.append({"label": label, "scope": PATH_SCOPE_DATA, "pattern": pattern})
    return checks


def _text_hits(text: str, checks) -> list[dict]:
    """一段文本里命中了几次、第一个样本长什么样（报告里要能直接看出漏的是什么）。"""
    hits = []
    for check in checks:
        if "literal" in check:
            needle = check["literal"].decode("utf-8")
            n = text.count(needle)
            sample = needle
        else:
            found = check["pattern"].findall(text)
            n = len(found)
            first = check["pattern"].search(text)
            sample = first.group(0) if first else ""
        if n:
            hits.append({"term": check["label"], "count": n, "sample": sample})
    return hits


def _is_text_member(name: str) -> bool:
    """正文类成员（判据按扩展名，与 `TEXT_SUFFIXES` 同一张表）。

    🔴 正则判据**只扫正文**：`.png` / `.docx` / `.parquet` / `.xlsx` 是压缩或二进制，
    按 `errors="ignore"` 解出来的"文本"里会随机出现 `X:/` 这样的字节巧合
    （实测 202607 报告初稿 docx 命中 98 次），那会把闸门变成噪声。
    本机路径这类**字面**判据不受此限——它们按字节扫，二进制里也认得出来。
    """
    return pathlib.PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES


def _scan_sqlite(raw: bytes, workdir: pathlib.Path, member: str, terms,
                 checks=()) -> list[dict]:
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
                if not checks:
                    continue
                texts = [str(r[0]) for r in con.execute(
                    f'SELECT "{column}" FROM "{table}"').fetchall()
                    if isinstance(r[0], str)]
                for hit in _text_hits("\n".join(texts), checks):
                    hits.append({"member": member, "where": f"{table}.{column}", **hit})
    finally:
        con.close()
    for term in terms:
        raw_n = raw.count(term.encode("utf-8"))
        if raw_n > seen_bytes[term]:                        # VACUUM 之后不该有；有就是真的漏了
            hits.append({"member": member, "where": "文件字节（自由页残留）",
                         "term": term, "count": raw_n - seen_bytes[term]})
    return hits


def scan_package(pkg: pathlib.Path, terms, root: pathlib.Path | None = None) -> list[dict]:
    """包里还有没有真实操作人与本机绝对路径。`terms` 的**键**是脱敏前采集的真实名字。

    - 数据面（`out/`、`input/`）的每个成员按 UTF-8 字节扫，`.sqlite` 另按文本列逐格扫；
    - 非 ASCII 的词（真实姓名，不是 `admin` / `demo` 这类角色标识）**全包扫**：
      代码与文档里出现人名同样是外发人名；
    - 路径判据按 `_path_checks()` 的两档范围扫（本机实际路径全包、通用形态只看数据面）；
    - `.docx` / `.parquet` 这类压缩/二进制内容扫不到——它们是产物，不是操作人记录。
    返回 `[{member, where?, term, count}]`（空 = 干净）；路径命中另有 `sample`。
    """
    ascii_terms = {t for t in terms if t.isascii()}
    name_terms = {t for t in terms if not t.isascii()}
    all_checks = _path_checks(root)
    hits: list[dict] = []
    with tarfile.open(pkg) as tf, tempfile.TemporaryDirectory(prefix="wenheng-scan-") as td:
        workdir = pathlib.Path(td)
        for member in tf.getmembers():
            if not member.isfile():
                continue
            data = _data_member(member.name)
            scope = set(name_terms)
            if data:
                scope |= ascii_terms
            checks = [c for c in all_checks if data or c["scope"] == PATH_SCOPE_ALL]
            if not scope and not checks:
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            raw = handle.read()
            if member.name.endswith(".sqlite"):
                hits += _scan_sqlite(raw, workdir, member.name, scope, checks)
                continue
            for term in sorted(scope):
                n = raw.count(term.encode("utf-8"))
                if n:
                    hits.append({"member": member.name, "term": term, "count": n})
            for check in checks:
                if "literal" not in check:          # 正则判据只扫正文，见 `_is_text_member`
                    continue
                n = raw.count(check["literal"])
                if n:
                    hits.append({"member": member.name, "term": check["label"],
                                 "count": n, "sample": check["literal"].decode("utf-8")})
            pattern_checks = [c for c in checks if "pattern" in c]
            if pattern_checks and _is_text_member(member.name):
                for hit in _text_hits(raw.decode("utf-8", errors="ignore"), pattern_checks):
                    hits.append({"member": member.name, **hit})
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
        # AI 问数库：期次必须与演示期一致（report_table2 / report_overview 按当期建）。
        # 缺了、或建的不是演示期，演示站进「AI 问数」只会看到一句 503。
        aiqa_sqlite = root / "out" / "_aidata" / "aiqa.sqlite"
        if not aiqa_sqlite.is_file():
            problems.append("out/_aidata/aiqa.sqlite 缺失 —— 先跑 "
                            f"uv run python tools\\build_aiqa_db.py --period {DATA_PERIOD}")
        else:
            period_in_db = ""
            try:
                con = sqlite3.connect(str(aiqa_sqlite))
                try:
                    row = con.execute(
                        "SELECT value FROM meta WHERE key='period'").fetchone()
                    period_in_db = row[0] if row else ""
                finally:
                    con.close()
            except sqlite3.Error as e:
                problems.append(f"out/_aidata/aiqa.sqlite 读不出 meta（{e}）—— 重跑 "
                                f"uv run python tools\\build_aiqa_db.py --period {DATA_PERIOD}")
            if period_in_db and period_in_db != DATA_PERIOD:
                problems.append(
                    f"out/_aidata/aiqa.sqlite 建的是 {period_in_db} 期，演示期是 "
                    f"{DATA_PERIOD} —— 重跑 uv run python tools\\build_aiqa_db.py "
                    f"--period {DATA_PERIOD}")
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
            db = state_db(root)
            if terms:
                aliases = "、".join(f"{k} → {v}" for k, v in _ordered_terms(terms))
                print(f"[脱敏] 真实操作人/指定词 {len(terms)} 个：{aliases}")
            else:
                print("[脱敏] 库里没有采集到真实操作人名——无名字可换，扫描也无从判"
                      "（要换批注里的人名请用 --redact-term）")
            db_note = f"已改写 {rows} 行（VACUUM）" if db in mapping else "不在，未复制"
            text_n = sum(1 for k in mapping if k != db)
            print(f"[脱敏] 库副本：{db_note}；数据文本改写 {text_n} 个文件"
                  "（操作人化名 + 本机绝对路径 → 仓库相对 / `~/`）")
        with tarfile.open(pkg, "w:gz") as tf:
            for f in files:
                src = mapping.get(f, f)
                tf.add(src, arcname=str(pathlib.Path("wenheng") / f.relative_to(root)),
                       recursive=False)
        if include_data and redact:
            hits = scan_package(pkg, terms, root)
            if hits:
                pkg.unlink(missing_ok=True)
                (outdir / (name + ".sha256")).unlink(missing_ok=True)
                raise LeakError(hits)
            print(f"[检查] 泄漏扫描：0 命中（判据：操作人名 {len(terms)} 个 + "
                  "本机路径全包 / 通用绝对路径数据面）")
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
    print(f"[失败] 包内仍有不该外发的内容：{len(hits)} 处（包已删除，别外发）")
    for hit in hits:
        where = f"（{hit['where']}）" if hit.get("where") else ""
        sample = f"  「{hit['sample']}」" if hit.get("sample") else ""
        print(f"  · {hit['member']}{where}：{hit['term']} × {hit['count']}{sample}")
    print("  → 脱敏没覆盖到的位置请看 tools/make_deploy_pkg.py 的 TEXT_SUFFIXES / DATA_PREFIXES；"
          "自由文本里的姓名用 --redact-term 追加；扫描范围与理由见 `_path_checks`")


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
        print("[警告] --no-redact：包里会带上真实操作人名（库 actor 列 / 审批记录.md / 数据文件）"
              "与本机绝对路径（库内 jobs.payload / 运行日志），"
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
