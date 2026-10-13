# -*- coding: utf-8 -*-
"""出报告入口（双击「一键出报告.bat」）：跑动态监测表（母本）的最新一期。

用法（双击 bat，或命令行）：
    .venv\\Scripts\\python.exe src\\run_latest.py
    .venv\\Scripts\\python.exe src\\run_latest.py --period 202607   # 历史期补跑

2026-10-13 起 `input/` 只放母本（一份、含全部期次）：当期 = 母本里最新有数据的期次
（判定在 `src/period.py`，唯一口径）；历史期补跑用 `--period`（母本 + 目标期切窗）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import ledger  # noqa: E402
import run_pipeline  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]


def find_ledger(repo_root=None):
    """运行时动态监测表（母本）：`<repo>/input/<母本>`；不在就直接报错（不猜、不扫）。"""
    root = pathlib.Path(repo_root) if repo_root else REPO
    p = ledger.runtime_path(root)
    if not p.exists():
        raise SystemExit(f"未找到动态监测表：{p}（请把母本放入 input/）")
    return p


if __name__ == "__main__":
    argv = sys.argv[1:]
    period = None
    if "--period" in argv:
        i = argv.index("--period")
        period = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    positional = [a for a in argv if not a.startswith("--")]
    ledger_path = pathlib.Path(positional[0]) if positional else find_ledger()
    print(f">>> 使用输入：{ledger_path}")
    sys.exit(run_pipeline.main(str(ledger_path), period=period))
