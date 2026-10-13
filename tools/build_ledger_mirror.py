# -*- coding: utf-8 -*-
"""台账镜像（SQLite）构建/校验 CLI（2026-10-13 票 01）。

用法：
  uv run python tools/build_ledger_mirror.py                 # 重建 out/_mirror/ledger.sqlite
  uv run python tools/build_ledger_mirror.py --verify        # 自校验 + 重解析母本比对
  uv run python tools/build_ledger_mirror.py --out tmp/m.sqlite --repo-root .

母本路径走 `src/ledger.py`（唯一口径）；镜像只读派生、永不回写母本。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ledger as ledger_mod                                      # noqa: E402
import ledger_mirror                                             # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="台账镜像（SQLite）：确定性重建 / 校验")
    ap.add_argument("--repo-root", default=str(REPO), help="仓库根（默认本仓）")
    ap.add_argument("--out", default="", help="镜像路径（默认 out/_mirror/ledger.sqlite）")
    ap.add_argument("--verify", action="store_true", help="只校验：自校验 + 重解析母本比对")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.repo_root)
    db = pathlib.Path(args.out) if args.out else ledger_mod.mirror_path(root)
    ledger_path = ledger_mod.runtime_path(root)
    if not ledger_path.is_file():
        ledger_path = ledger_mod.source_path(root)
    if not ledger_path.is_file():
        print(f"找不到母本（{ledger_mod.LEDGER_NAME}）：input/ 与 数据与复现/ 都没有")
        return 2

    if args.verify:
        out = ledger_mirror.verify(db, ledger_path=ledger_path)
        print(("✓ " if out["ok"] else "✗ ") + "台账镜像校验：" + str(out))
        return 0 if out["ok"] else 1

    meta = ledger_mirror.build(db, ledger_path=ledger_path)
    print(f"✓ 台账镜像已重建：{meta['path']}")
    print(f"  n_facts={meta['n_facts']}  periods={meta['periods'].count(',') + 1}"
          f"  content_sha256={meta['content_sha256'][:16]}…"
          f"  ledger_sha256={meta['ledger_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
