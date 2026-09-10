# -*- coding: utf-8 -*-
"""出报告入口：自动取 input/ 下最新的监测表，跑全链路。

用法：双击 一键出报告.bat，或命令行
    .venv\\Scripts\\python.exe src\\run_latest.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import run_pipeline  # noqa: E402


def find_latest_ledger(input_root="input"):
    root = pathlib.Path(input_root)
    cands = sorted(root.glob("*/监测表.xlsx"), key=lambda p: p.parent.name)
    if not cands:
        raise SystemExit(f"未找到输入：{root}/*/监测表.xlsx（请把新一期台账放进 input\\<期次>\\）")
    return cands[-1]


if __name__ == "__main__":
    ledger = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_ledger()
    print(f">>> 使用输入：{ledger}")
    sys.exit(run_pipeline.main(str(ledger)))
