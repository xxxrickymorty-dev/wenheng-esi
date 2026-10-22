# -*- coding: utf-8 -*-
"""数据来源清单：`../数据与复现/` 下**每个文件**的路径 / 大小 / 修改时间 / 指纹（迁移 004）。

- **只装清单，不装原始文件**（ADR-0012 决定 2）：原始包原地不动，库只有几十 KB。
- **与 `src/inventory.py` 分工**：那边判「某期四件**件级**齐不齐」（服务端在用，不读库）；
  这里判「**文件级**：每个文件是不是原来那一份、换机拷全了没有」。
- 🔴 **对 `../数据与复现/` 只读**：只 `stat` + 读字节算指纹，不改名、不移动、不删除、不写回。
  清单渲染件写仓库里的 `out/_state/sources.md`，**不写进数据目录**。
- **增量指纹**：`size + mtime_ns` 与库里记的一致 → `--hash` 也不重算（InCites 9 GB 不可能
  每次全量重算）；只有本工具记过且两项都没变才跳过，缺指纹的行照算。

用法（在 `wenheng/` 下；也可 `uv run python -m tools.sources_index`）：

    uv run python tools\\sources_index.py scan --kind esi --hash   # 元数据 + 全量指纹
    uv run python tools\\sources_index.py scan --kind incites      # 只元数据（不算 9 GB）
    uv run python tools\\sources_index.py scan --kind all --scope 202609
    uv run python tools\\sources_index.py check --kind esi         # 新增 / 变了 / 没了（纯读）
    uv run python tools\\sources_index.py check --hash             # 连指纹一起比（慢）
    uv run python tools\\sources_index.py export-md                # → out/_state/sources.md

`scope`（期次目录名 / InCites 快照目录名）一律按目录名给；直接躺在 kind 根下的散件
（`ESI数据/ESI总表模板.xlsx`、`incites/…zip`）记 `_root`——不属于任何期次，但换机少一件
同样要看得见。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import atomic_io, state_store  # noqa: E402

#: `kind` → 数据目录下的子目录名（顺序＝打印顺序）。
KIND_DIRS = {"esi": "ESI数据", "incites": "incites"}
#: 默认数据根（仓库上一级的 `数据与复现/`；`--data-root` 可覆盖，测试靠它）。
DATA_ROOT = ROOT.parent / "数据与复现"
#: 清单渲染件（**在仓库里**，不写进数据目录）。
REPORT_PATH = ROOT / "out" / "_state" / "sources.md"
#: 直接躺在 kind 根下的散件的 scope（目录名不会长得像它）。
ROOT_SCOPE = "_root"
#: 算指纹的块大小（1 MB：9 GB 级别也只要一次顺序读）。
CHUNK = 1 << 20


# ---------------------------------------------------------------- 磁盘侧
def kind_root(kind: str, data_root=None) -> pathlib.Path:
    return pathlib.Path(data_root or DATA_ROOT) / KIND_DIRS[kind]


def iter_files(kind: str, data_root=None):
    """遍历一个 kind 下的全部文件：`(scope, rel_path, path)`（`rel_path` 相对数据根）。"""
    root = kind_root(kind, data_root)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_under_kind = path.relative_to(root).as_posix()
        scope = rel_under_kind.split("/")[0] if "/" in rel_under_kind else ROOT_SCOPE
        yield scope, f"{KIND_DIRS[kind]}/{rel_under_kind}", path


def sha256_file(path) -> str:
    """整个文件的 sha256（1 MB 一块顺序读；只读，不改文件）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- 打印小工具
def _mb(n: int) -> str:
    """人看的体积（MB 两位；小于 1 KB 给字节）。"""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _ts(mtime_ns: int) -> str:
    return datetime.datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _kinds(kind: str) -> list[str]:
    """`all` → 全部 kind；否则只给一个（非法值由 argparse 挡住）。"""
    return list(KIND_DIRS) if kind == "all" else [kind]


# ---------------------------------------------------------------- scan
def scan(db_path, *, kind="all", scope=None, do_hash=False, data_root=None, emit=print) -> dict:
    """遍历 → 写/更新清单；返回 `{kind: {"files", "bytes", "added", "updated", "kept",
    "hashed", "hash_skipped", "removed"}}`。

    幂等：`size + mtime_ns`（以及算过的 `sha256`）都没变的行**不重写**，`scanned_at` 不动；
    重跑同样的目录，库内容逐行不变。该 scope 里磁盘上已经没有的行**移除**并逐条打印
    ——清单是磁盘的镜子，留着幽灵行会让 `check` 永远报差异。
    """
    db_path = pathlib.Path(db_path)
    summary: dict = {}
    for one in _kinds(kind):
        root = kind_root(one, data_root)
        if not root.is_dir():
            emit(f"[跳过] {KIND_DIRS[one]}：目录不存在（{root}）")
            continue
        existing = {(r["scope"], r["rel_path"]): r
                    for r in state_store.sources_rows(db_path, kind=one, scope=scope)}
        stat = {"files": 0, "bytes": 0, "added": 0, "updated": 0, "kept": 0,
                "hashed": 0, "hash_skipped": 0, "removed": 0}
        per_scope: dict[str, dict] = {}
        rows = []
        seen = set()
        for sc, rel_path, path in iter_files(one, data_root):
            if scope is not None and sc != scope:
                continue
            st = path.stat()
            seen.add((sc, rel_path))
            bucket = per_scope.setdefault(
                sc, {"files": 0, "bytes": 0, "added": 0, "updated": 0, "kept": 0,
                     "hashed": 0, "hash_skipped": 0})
            bucket["files"] += 1
            bucket["bytes"] += st.st_size
            stat["files"] += 1
            stat["bytes"] += st.st_size
            old = existing.get((sc, rel_path))
            same_meta = old is not None and old["size"] == st.st_size \
                and old["mtime_ns"] == st.st_mtime_ns
            sha = old["sha256"] if old else ""
            if do_hash:
                if same_meta and old["sha256"]:
                    stat["hash_skipped"] += 1
                    bucket["hash_skipped"] += 1
                else:
                    sha = sha256_file(path)
                    stat["hashed"] += 1
                    bucket["hashed"] += 1
            if same_meta and (not do_hash or sha == (old["sha256"] or "")):
                stat["kept"] += 1
                bucket["kept"] += 1
                continue
            bucket["updated" if old else "added"] += 1
            stat["updated" if old else "added"] += 1
            rows.append({"kind": one, "scope": sc, "rel_path": rel_path,
                         "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                         "sha256": sha, "scanned_at": _now()})
        gone = [key for key in existing if key not in seen]
        if gone:
            removed = state_store.delete_sources(
                db_path, [(one, sc, rel) for sc, rel in gone])
            stat["removed"] = removed
            for sc, rel in gone:
                emit(f"  移除：{one} · {sc} · {rel}（磁盘上已没有）")
        state_store.put_sources(db_path, rows)
        for sc in sorted(per_scope):
            b = per_scope[sc]
            emit(f"  {one} · {sc}：{b['files']} 文件 · {_mb(b['bytes'])}"
                 f" · 新增 {b['added']} · 更新 {b['updated']} · 不变 {b['kept']}"
                 f" · 算指纹 {b['hashed']} · 跳过重算 {b['hash_skipped']}")
        emit(f"{one} 合计：{stat['files']} 文件 · {_mb(stat['bytes'])}"
             f" · 新增 {stat['added']} · 更新 {stat['updated']} · 不变 {stat['kept']}"
             f" · 算指纹 {stat['hashed']} · 跳过重算 {stat['hash_skipped']}"
             f" · 移除 {stat['removed']}")
        summary[one] = stat
    return summary


# ---------------------------------------------------------------- check
def check(db_path, *, kind="all", scope=None, do_hash=False, data_root=None,
          emit=print) -> dict:
    """对比磁盘与库：`{added, changed, removed, hashed_mismatch}`（每项一条人话）。

    **纯读**：库不存在只提示、**不建库**、不删任何东西（同 `state_export` 的「没库 ≠ 库里没有」）。
    默认只比元数据（大小 / 修改时间）——一次 `check` 不该等于 9 GB 的重算；
    `--hash` 才连指纹一起比（能发现「大小与修改时间都没变、内容被换过」）。
    """
    db_path = pathlib.Path(db_path)
    result: dict = {"added": [], "changed": [], "removed": [], "db_exists": db_path.is_file()}
    if not result["db_exists"]:
        emit(f"[提示] 状态库不存在：{db_path}（没有清单可对比；不建库、不动任何文件）")
        return result
    for one in _kinds(kind):
        root = kind_root(one, data_root)
        if not root.is_dir():
            emit(f"[跳过] {KIND_DIRS[one]}：目录不存在（{root}）")
            continue
        known = {(r["scope"], r["rel_path"]): r
                 for r in state_store.sources_rows(db_path, kind=one, scope=scope)}
        seen = set()
        for sc, rel_path, path in iter_files(one, data_root):
            if scope is not None and sc != scope:
                continue
            st = path.stat()
            seen.add((sc, rel_path))
            old = known.get((sc, rel_path))
            if old is None:
                result["added"].append(
                    f"{one} · {sc} · {rel_path}（{_mb(st.st_size)}）")
                continue
            why = []
            if old["size"] != st.st_size:
                why.append(f"大小 {old['size']} → {st.st_size}")
            if old["mtime_ns"] != st.st_mtime_ns:
                why.append(f"修改时间 {_ts(old['mtime_ns'])} → {_ts(st.st_mtime_ns)}")
            if do_hash and old["sha256"]:
                now_sha = sha256_file(path)
                if now_sha != old["sha256"]:
                    why.append(f"指纹 {old['sha256'][:12]}… → {now_sha[:12]}…")
            if why:
                result["changed"].append(
                    f"{one} · {sc} · {rel_path}（{'；'.join(why)}）")
        for (sc, rel_path) in sorted(set(known) - seen):
            result["removed"].append(f"{one} · {sc} · {rel_path}")

    for label, key in (("新增", "added"), ("变了", "changed"), ("没了", "removed")):
        items = result[key]
        emit(f"{label} {len(items)}")
        for line in items:
            emit(f"  {line}")
    total = len(result["added"]) + len(result["changed"]) + len(result["removed"])
    emit("结论：无变化（磁盘与清单一致）" if total == 0
         else f"结论：新增 {len(result['added'])} · 变了 {len(result['changed'])}"
              f" · 没了 {len(result['removed'])}")
    return result


# ---------------------------------------------------------------- export-md
def render_md(db_path, *, kind="all", scope=None) -> str:
    """把清单渲染成 markdown（汇总表 + 逐文件明细）；库里没有 → 空清单说明。"""
    rows = state_store.sources_rows(db_path, kind=None if kind == "all" else kind, scope=scope)
    lines = [
        "# 数据来源清单（sources）",
        "",
        f"> 由 `tools/sources_index.py export-md` 于 {_now()} 从状态库渲染。",
        "> 只记路径 / 大小 / 修改时间 / 指纹；**原始文件不入库**，原始包原地不动（ADR-0012 决定 2）。",
        "> `scope` 是期次目录名或 InCites 快照目录名；`_root`＝直接躺在该目录根下的散件。",
        "> 与 `src/inventory.py`（件级盘点：某期四件齐不齐）分工不同：这份判「每个文件是不是原来那一份」。",
        "",
    ]
    if not rows:
        lines += ["（库里还没有清单：先跑 `tools\\sources_index.py scan`。）", ""]
        return "\n".join(lines)

    for one in [k for k in KIND_DIRS if kind in ("all", k)]:
        mine = [r for r in rows if r["kind"] == one]
        if not mine:
            continue
        total = sum(r["size"] for r in mine)
        hashed = sum(1 for r in mine if r["sha256"])
        dirs = {r["scope"] for r in mine}
        lines += [
            f"## {KIND_DIRS[one]}（`kind={one}`）",
            "",
            f"- 范围 {len(dirs)} 个 · 文件 {len(mine)} 个 · 总大小 {_mb(total)}"
            f" · 已算指纹 {hashed} 个",
            "",
            "| scope | 文件 | 大小 | 已算指纹 | 最近扫描 |",
            "|---|---:|---:|---:|---|",
        ]
        by_scope: dict[str, list[dict]] = {}
        for r in mine:
            by_scope.setdefault(r["scope"], []).append(r)
        for sc in sorted(by_scope):
            items = by_scope[sc]
            lines.append(
                f"| `{sc}` | {len(items)} | {_mb(sum(i['size'] for i in items))}"
                f" | {sum(1 for i in items if i['sha256'])}"
                f" | {max(i['scanned_at'] for i in items)} |")
        lines.append("")

        for sc in sorted(by_scope):
            items = by_scope[sc]
            lines += [
                f"### {KIND_DIRS[one]} · `{sc}`（{len(items)} 文件 ·"
                f" {_mb(sum(i['size'] for i in items))}）",
                "",
                "| 相对 `数据与复现/` 的路径 | 大小 | 修改时间 | sha256 |",
                "|---|---:|---|---|",
            ]
            for r in items:
                lines.append(f"| `{r['rel_path']}` | {_mb(r['size'])}"
                             f" | {_ts(r['mtime_ns'])} | `{r['sha256'] or '—'}` |")
            lines.append("")
    return "\n".join(lines)


def export_md(db_path, out_path=None, *, kind="all", scope=None, emit=print) -> pathlib.Path:
    """渲染并**原子写**到 `out/_state/sources.md`（默认）；返回写到的路径。"""
    target = pathlib.Path(out_path or REPORT_PATH)
    text = render_md(db_path, kind=kind, scope=scope)
    atomic_io.write_text_atomic(target, text)
    n = len(text.splitlines())
    emit(f"已写入 {target}（{n} 行）")
    return target


# ---------------------------------------------------------------- 入口
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="数据来源清单：扫描 / 对比 / 渲染（原始文件只读）")
    ap.add_argument("--db", default=None, help="状态库路径（默认 out/_state/wenheng.sqlite）")
    ap.add_argument("--data-root", default=None, help="数据根（默认上一级 数据与复现/）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--kind", default="all", choices=["esi", "incites", "all"])
        p.add_argument("--scope", default=None, help="只处理这一期 / 这个快照（目录名）")
        p.add_argument("--hash", action="store_true", help="算 / 比 sha256（慢；默认只元数据）")

    common(sub.add_parser("scan", help="遍历目录，写/更新清单"))
    common(sub.add_parser("check", help="对比磁盘与库（纯读）：新增 / 变了 / 没了"))
    p_md = sub.add_parser("export-md", help="渲染成 out/_state/sources.md")
    common(p_md)
    p_md.add_argument("--out", default=None, help=f"输出路径（默认 {REPORT_PATH}）")
    args = ap.parse_args(argv)

    db = pathlib.Path(args.db) if args.db else state_store.db_path(out_root=ROOT)
    data_root = pathlib.Path(args.data_root) if args.data_root else None

    if args.cmd == "scan":
        print(f"状态库：{db}")
        print(f"数据根：{data_root or DATA_ROOT}（只读）")
        scan(db, kind=args.kind, scope=args.scope, do_hash=args.hash, data_root=data_root)
        info = state_store.health(db)
        print(f"库状态：schema {info['schema_version']}/{info['code_version']}"
              f"{' · 降级只读：' + info['note'] if info['degraded'] else ''}")
        return 0
    if args.cmd == "check":
        print(f"状态库：{db}")
        print(f"数据根：{data_root or DATA_ROOT}（只读）")
        check(db, kind=args.kind, scope=args.scope, do_hash=args.hash, data_root=data_root)
        return 0
    export_md(db, args.out, kind=args.kind, scope=args.scope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
