# -*- coding: utf-8 -*-
"""打部署包：代码 + `web/dist` + 演示数据（`out/202607` + `input/`），供 /opt 解包部署。

用法（在 wenheng/ 下，venv 直调）：
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py             # 演示包（含数据）
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py --no-data   # 纯代码包（只更新代码）
    .venv\\Scripts\\python.exe tools\\make_deploy_pkg.py --out D:\\wenheng-bundles

产物：`<输出目录>/wenheng-demo-YYYYMMDD.tar.gz`（默认输出目录 = 工作区根，与历史包同处），
旁边写同名 `.sha256`。包内顶层固定为 `wenheng/`——服务器上 `tar -C /opt -xzf <包>`
即解出 `/opt/wenheng`（与部署清单 §3 一致）。

进包 / 不进包（口径写死在这里，部署清单 §0 引用本文件）：
    进：pyproject.toml、CONTEXT.md、GLOSSARY.md、AGENTS.md、docs/、src/、server/、tools/、tests/、
        master/、web/dist/；演示包另加 input/、out/202607/（剔除 _superseded）、out/_jobs/
    不进：server/.env（密钥）、web/node_modules/、__pycache__/、.pytest_cache/、
        .ruff_cache/、tmp/、.git/、_superseded/、out/ 其它期次

预检（缺了直接失败——别等服务器上才白屏）：
    · `web/dist/index.html` + `web/dist/assets/`（/app 首屏，ADR-0001 要求随包带）
    · `master/` 母版 docx（fill_docx 依赖）
    · 演示包另查 `out/202607/` 首屏四件（red_slots / overview_facts / 报告初稿）与
      `input/202607/监测表.xlsx`
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys
import tarfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent      # wenheng/
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


def _excluded(rel: pathlib.Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in rel.parts):
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
        files += _tree_files(root / "out" / "_jobs", root)
    return sorted(set(files), key=lambda p: str(p.relative_to(root)))


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
                    f"input/{DATA_PERIOD}/监测表.xlsx"):
            if not (root / rel).is_file():
                problems.append(f"{rel} 缺失 —— 演示包首屏依赖它（或改走 --no-data）")
        if not list((root / "out" / DATA_PERIOD).glob("报告初稿*.docx")):
            problems.append(f"out/{DATA_PERIOD}/报告初稿*.docx 缺失 —— 对勘本要有成品可读")
    return problems


def build(root: pathlib.Path, outdir: pathlib.Path, include_data: bool = True,
          name: str | None = None) -> pathlib.Path:
    """打包并写 `.sha256`，返回 tar.gz 路径（预检请先自行调用 preflight）。"""
    files = collect(root, include_data)
    outdir.mkdir(parents=True, exist_ok=True)
    name = name or f"wenheng-{'demo' if include_data else 'deploy'}-{time.strftime('%Y%m%d')}.tar.gz"
    pkg = outdir / name
    with tarfile.open(pkg, "w:gz") as tf:
        for f in files:
            tf.add(f, arcname=str(pathlib.Path("wenheng") / f.relative_to(root)),
                   recursive=False)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="文衡部署包（代码 + web/dist + 演示数据）")
    ap.add_argument("--no-data", action="store_true",
                    help="纯代码包（不含 input/ 与 out/，只更新代码）")
    ap.add_argument("--out", default=None, help="输出目录（默认：工作区根）")
    ap.add_argument("--name", default=None, help="包名（默认按日期生成）")
    a = ap.parse_args(argv)

    include_data = not a.no_data
    problems = preflight(ROOT, include_data)
    if problems:
        for p in problems:
            print(f"[失败] {p}")
        return 1

    if git_dirty(ROOT):
        print("[警告] 工作区有未提交改动 —— 包里带的是在途代码，"
              "要打正式包先 commit（或确认这就是你要发的版本）")

    outdir = pathlib.Path(a.out) if a.out else ROOT.parent
    pkg = build(ROOT, outdir, include_data=include_data, name=a.name)
    files = collect(ROOT, include_data)
    size_mb = pkg.stat().st_size / 1e6
    print(f"已打 {pkg}")
    print(f"  {size_mb:.1f} MB · {len(files)} 个文件 · sha256 见 {pkg.name}.sha256")
    print(f"  解包：tar -C /opt -xzf {pkg.name}  →  /opt/wenheng")
    return 0


if __name__ == "__main__":
    sys.exit(main())
