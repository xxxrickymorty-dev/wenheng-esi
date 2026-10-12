# -*- coding: utf-8 -*-
"""问数规划金标回测（票 04）：规则规划器 × `qa_gold.json` → 逐例对照，EXIT 0/1。

只测**规则路径**（确定性、离线；随台账/代码可跑）。模型路径的质量回测需要 key，
不在此工具内（见 spec 票 04 备注）。

用法（wenheng/ 下）：

    uv run python tools\\verify_qa_plan.py
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from ai import _plan                                              # noqa: E402

GOLD = pathlib.Path(__file__).with_name("qa_gold.json")


def evaluate(cases=None) -> tuple:
    """逐例对照规则规划。返回 `(通过数, [(问句, 实得, 期望), ...])`。"""
    if cases is None:
        cases = json.loads(GOLD.read_text(encoding="utf-8"))
    fails = []
    for c in cases:
        got = _plan.rule_specs(c["q"], c.get("discs") or ())
        if got != c["expect"]:
            fails.append((c["q"], got, c["expect"]))
    return len(cases) - len(fails), fails


def main() -> int:
    total, fails = evaluate()
    for q, got, expect in fails:
        print(f"[FAIL] {q}")
        print(f"  got   : {json.dumps(got, ensure_ascii=False)}")
        print(f"  expect: {json.dumps(expect, ensure_ascii=False)}")
    print(f"规划金标：{total}/{total + len(fails)} 通过")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
