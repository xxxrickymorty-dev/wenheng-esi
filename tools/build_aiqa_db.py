# -*- coding: utf-8 -*-
"""AI 问数库（SQLite）构建/校验 CLI。

用法：
  uv run python tools/build_aiqa_db.py            # 重建（台账镜像 + 当期产物 → out/_aidata/aiqa.sqlite）
  uv run python tools/build_aiqa_db.py --period 202607   # 指定报告期次（打演示包前用）
  uv run python tools/build_aiqa_db.py --verify   # 自校验
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiqa_db                                                # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 问数库：确定性重建 / 校验")
    ap.add_argument("--repo-root", default=str(REPO))
    ap.add_argument("--period", default="", help="指定报告期次（默认取最新）")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.repo_root)
    if args.verify:
        r = aiqa_db.verify(root)
        print(("✓ " if r["ok"] else "✗ ") + str(r))
        return 0 if r["ok"] else 2
    m = aiqa_db.build(root, out_period=args.period or None)
    print(f"✓ AI 问数库已重建：{m['path']}")
    print(f"  期次={m['period']}  事实={m['n_facts']}  "
          f"大表行={m['n_table2']}  概述键={m['n_overview']}")
    print(f"  content_sha256={m['content_sha256'][:16]}…")
    v = aiqa_db.verify(root)
    print(("✓ 自校验通过" if v["ok"] else "✗ 自校验失败：" + str(v)))
    return 0 if v["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
