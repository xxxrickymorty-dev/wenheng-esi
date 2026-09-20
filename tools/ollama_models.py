# -*- coding: utf-8 -*-
"""Ollama 模型目录的**备份 / 恢复 / 体检** —— 专治「模型被清空，又要重下 2G」。

背景（2026-09-21 实查，先纠正一个误判）：
    一开始以为"模型一夜之间被删了"，其实是**两个 ollama server 抢同一个端口 11434、
    各用各的模型目录**：
      · rick 的桌面端把模型位置设在 **`F:\\models`**（qwen3:8b / bge-small-zh 都在这儿）；
      · 我从 CLI 起的 `ollama serve` 没设 `OLLAMA_MODELS` → 用默认
        `%USERPROFILE%\\.ollama\\models`（空目录）。
    谁抢到 11434，`ollama list` 就显示谁的目录 —— 于是"桌面端明明有模型，CLI 却看到空的"，
    被误读成"模型被删"。`F:\\models\\blobs` 里那个 1.93G 文件的 mtime 就是**第一次拉取的时间**，
    模型一直都在。
    ⚠ 真正的风险是：**不该有两个 server**。已把用户级 `OLLAMA_MODELS` 固定成
    `F:\\models`，与桌面端对齐 —— 谁起 server 都读同一份。

    另一件真事：Ollama 默认位置是 `%USERPROFILE%\\.ollama\\models\\blobs` ——
    一个 1.9G、无扩展名、藏在点目录里的大文件，是磁盘清理工具的典型目标。
    所以「挪出用户目录」这条路本身仍然正确（rick 已经在 F 盘了）。

用法（workdir=wenheng）：

    .venv\\Scripts\\python.exe tools\\ollama_models.py status
    .venv\\Scripts\\python.exe tools\\ollama_models.py backup            # → F:\\ollama-models-backup
    .venv\\Scripts\\python.exe tools\\ollama_models.py backup --to D:\\bk
    .venv\\Scripts\\python.exe tools\\ollama_models.py restore           # 从默认备份拷回
    .venv\\Scripts\\python.exe tools\\ollama_models.py restore --from F:\\models

🔴 恢复后**不用重新 pull**：Ollama 认的是 `manifests/` + `blobs/` 两个目录的内容，
   文件拷回来即可，重启 Ollama（退出托盘再开 / 重启电脑）就能在 `ollama list` 里看到。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import urllib.request

DEFAULT_BACKUP = r"F:\ollama-models-backup"
SERVER = "http://127.0.0.1:11434"


def model_dir() -> pathlib.Path:
    """当前生效的模型目录（即**直接含 `blobs/` 与 `manifests/` 的那个目录**）。

    ⚠ `OLLAMA_MODELS` 指的是**这一层**，不是它的 `models` 子层 ——
    rick 机上是 `OLLAMA_MODELS=F:\\models`，对应 `F:\\models\\blobs` + `F:\\models\\manifests`。
    这里顺手兼容"指到了上一级"的写法（那层下面还有 `models/blobs`）。
    """
    env = os.environ.get("OLLAMA_MODELS", "").strip()
    if env:
        p = pathlib.Path(env)
        if (p / "blobs").is_dir() or (p / "manifests").is_dir():
            return p
        if (p / "models" / "blobs").is_dir():
            return p / "models"
        return p
    return pathlib.Path.home() / ".ollama" / "models"


def _size(p: pathlib.Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GB"


def _copy(src: pathlib.Path, dst: pathlib.Path, what: str) -> int:
    n = 0
    for name in ("blobs", "manifests"):
        s, d = src / name, dst / name
        if not s.is_dir():
            continue
        d.mkdir(parents=True, exist_ok=True)
        for f in s.rglob("*"):
            if not f.is_file():
                continue
            t = d / f.relative_to(s)
            t.parent.mkdir(parents=True, exist_ok=True)
            if t.exists() and t.stat().st_size == f.stat().st_size:
                continue
            shutil.copy2(f, t)
            n += 1
            if n % 200 == 0:
                print(f"  …{what}已拷 {n} 个文件", flush=True)
    return n


def cmd_status(_a) -> int:
    md = model_dir()
    print("环境变量 OLLAMA_MODELS :", os.environ.get("OLLAMA_MODELS") or "（未设置 → 用默认 ~/.ollama）")
    print("生效模型目录           :", md)
    print("  存在:", md.is_dir(), "| 占用:", _gb(_size(md)))
    for sub in ("manifests", "blobs"):
        p = md / sub
        print(f"  {sub:10}: {_size(p) and _gb(_size(p)) or '—'}"
              f"  文件数 {sum(1 for f in p.rglob('*') if f.is_file()) if p.is_dir() else 0}")
    # 已登记模型（读本地 manifest，不依赖服务）
    mf = md / "manifests"
    names = []
    if mf.is_dir():
        for f in mf.rglob("*"):
            if f.is_file():
                parts = f.relative_to(mf).parts
                if len(parts) >= 3:                    # <registry>/library/<ns>/<model>/<tag>
                    names.append("/".join(parts[1:]) if parts[0].replace(".", "").isalnum()
                                 else "/".join(parts))
    print("  已登记模型:", sorted(names) or "（无）")
    # 服务可达性
    try:
        with urllib.request.urlopen(f"{SERVER}/api/tags", timeout=3) as r:
            tags = json.load(r).get("models", [])
        print(f"服务 {SERVER}: 可达，{len(tags)} 个模型 "
              f"{[m.get('name') for m in tags]}")
    except Exception as e:                                          # noqa: BLE001
        print(f"服务 {SERVER}: 不可达（{type(e).__name__}）—— 不影响备份/恢复")
    # 备份是否存在
    for b in (pathlib.Path(DEFAULT_BACKUP), pathlib.Path.home() / ".ollama" / "models",
              pathlib.Path(r"C:\ollama-models")):
        if b.is_dir() and _size(b) > 0:
            print(f"可用备份源: {b}  ({_gb(_size(b))})")
    return 0


def cmd_backup(a) -> int:
    src, dst = model_dir(), pathlib.Path(a.to)
    if not src.is_dir() or _size(src) == 0:
        print(f"✗ 源目录为空或不存在：{src} —— 先 ollama pull 一次")
        return 1
    print(f"备份 {src} → {dst}")
    n = _copy(src, dst, "备份")
    print(f"✓ 完成，{n} 个文件，{_gb(_size(dst))}")
    return 0


def cmd_restore(a) -> int:
    src, dst = pathlib.Path(a.frm), model_dir()
    if not src.is_dir() or _size(src) == 0:
        print(f"✗ 备份源为空或不存在：{src}")
        return 1
    dst.mkdir(parents=True, exist_ok=True)
    print(f"恢复 {src} → {dst}（不联网、不重新下载）")
    n = _copy(src, dst, "恢复")
    print(f"✓ 完成，{n} 个文件。重启 Ollama（退出托盘再开 / 重启电脑）后 ollama list 可见。")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="体检：目录位置 / 占用 / 已登记模型 / 服务可达性").set_defaults(fn=cmd_status)
    b = sub.add_parser("backup", help="备份模型目录")
    b.add_argument("--to", default=DEFAULT_BACKUP)
    b.set_defaults(fn=cmd_backup)
    r = sub.add_parser("restore", help="从备份恢复（零下载）")
    r.add_argument("--from", dest="frm", default=DEFAULT_BACKUP)
    r.set_defaults(fn=cmd_restore)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
