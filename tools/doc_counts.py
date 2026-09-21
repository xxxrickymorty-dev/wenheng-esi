# -*- coding: utf-8 -*-
"""文档计数同步：把「用例数 / e2e 断言数」的实测值同步进 CONTEXT.md。

背景：文档里的精确计数最容易过期（CONTEXT 曾写「全量 203 例」，实测已 400+；
「96 断言」实测已 257）。评审现场对不上会很尴尬，而人工维护又必然漂。

用法：
    python tools/doc_counts.py           # 只打印「文档写的 vs 实测」，不写盘
    python tools/doc_counts.py --write   # 把 CONTEXT.md 的两处计数改成实测值

实测口径：
    用例数 = pytest --collect-only（含参数化展开；全量 = 放开 slow marker）
    断言数 = server/e2e_report.txt 里最近一次「全部通过（N 项断言）」
             （没有报告文件时不改这一处，不猜）

安全：--write 时每处必须**恰好命中一次**，命中数不符就不写盘（防正则改错地方）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = REPO / "CONTEXT.md"
E2E_REPORT = REPO / "server" / "e2e_report.txt"

RE_TESTS = re.compile(r"全量\s*\d+\s*例（默认\s*\d+\s*例，\s*\d+\s*个 slow 被 marker 排除）")
RE_E2E = re.compile(r"只读\s*\d+\s*断言")


def _collect(markexpr):
    """pytest --collect-only 的用例数（实测，不是数 def）。"""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", f"-m {markexpr}"]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = r.stdout or ""
    # 有 marker 排除时 pytest 打「473/477 tests collected (4 deselected)」，
    # 要的是分子（实际会跑的），不是总数。
    m = re.search(r"(\d+)/\d+\s+tests?\s+collected", out) \
        or re.search(r"(\d+)\s+tests?\s+collected", out)
    if not m:
        raise SystemExit(f"[拒绝] 解析不出用例数：{out[-300:]}")
    return int(m.group(1))


def _e2e_asserts():
    if not E2E_REPORT.exists():
        return None
    text = E2E_REPORT.read_text(encoding="utf-8", errors="replace")
    m = None
    for m in re.finditer(r"（(\d+)\s*项断言）", text):
        pass
    return int(m.group(1)) if m else None


def _replace_once(text, pattern, new, label):
    hits = len(pattern.findall(text))
    if hits != 1:
        raise SystemExit(f"[拒绝] {label} 命中 {hits} 处（应为 1），不写盘")
    return pattern.sub(new, text, count=1)


def main():
    ap = argparse.ArgumentParser(description="文档计数同步（CONTEXT.md）")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    full = _collect("slow or not slow")
    default = _collect("not slow")
    slow = full - default
    e2e = _e2e_asserts()

    doc = CONTEXT.read_text(encoding="utf-8")
    m_tests = RE_TESTS.search(doc)
    m_e2e = RE_E2E.search(doc)
    print(f"实测：全量 {full} 例（默认 {default} 例，{slow} 个 slow）"
          f"；e2e 断言 {e2e if e2e is not None else '（无报告）'}")
    print(f"文档：{m_tests.group(0) if m_tests else '（没找到用例数）'}"
          f" / {m_e2e.group(0) if m_e2e else '（没找到断言数）'}")

    if not a.write:
        print("（只读；要同步加 --write）")
        return 0

    doc = _replace_once(doc, RE_TESTS,
                        f"全量 {full} 例（默认 {default} 例，{slow} 个 slow 被 marker 排除）",
                        "用例数")
    if e2e is not None:
        doc = _replace_once(doc, RE_E2E, f"只读 {e2e} 断言", "断言数")
    CONTEXT.write_text(doc, encoding="utf-8")
    print("已写回 CONTEXT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
