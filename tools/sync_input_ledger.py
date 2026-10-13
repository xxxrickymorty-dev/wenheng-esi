# -*- coding: utf-8 -*-
"""把馆员原件（`../数据与复现/<母本>`）同步到运行时输入（`input/<母本>`）。

用法（在 wenheng/ 下）：
    uv run python tools\\sync_input_ledger.py

口径（2026-10-13 rick 定）：`input/` 只放母本（一份、含全部期次）；流水线/开跑口/
问答回落/盘点/部署包都只读它。「并入台账」（`tools/acquire.py merge`）成功后会自动
同步；手工改动原件后也跑一下这个。部署包预检会核对两者 sha256，不一致直接拒绝打包。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import ledger  # noqa: E402


def main() -> int:
    src = ledger.source_path(REPO)
    if not src.exists():
        print(f"[拒绝] 馆员原件不存在：{src}")
        return 1
    dst = ledger.sync(REPO)
    print(f"[sync] {src}")
    print(f"    → {dst}")
    print(f"       sha256 {ledger.sha256(dst)[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
