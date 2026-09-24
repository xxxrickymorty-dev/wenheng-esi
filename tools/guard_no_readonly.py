# -*- coding: utf-8 -*-
"""护栏：读 ESI 原始包禁 `read_only=True`。

背景：202609 起新导出的 ESI xlsx，`<dimension>` 被写成 `A1`；openpyxl 在
`read_only=True` 下据此把 1 万行读成 **1×1 空表**（`reset_dimensions` 也救不回），
而且失败是**静默**的——解析结果变成空，不报错、不抛异常。
详见 `~/.agents/skills/clarivate-fetch/references/pitfalls.md`。

本脚本静态扫 `tools/` 与 `src/`，分两档：
  [FAIL] 读 ESI 包却用 read_only=True  → 退出码 1
  [info] 其它 read_only=True            → 列出待人工确认（退出码 0）

判定「读 ESI」两条：
  1) 模块属 `PURE_ESI_MODULES`（整模块只读 ESI，任何 read_only 都判失败）；
  2) 所在作用域的标识符含 `esi` 词元（`esi_root` / `esi_dir` / `read_esi` …），
     或字符串字面量含 `ESI数据` / `ThresholdESI` / `IndicatorsExport` 等。

⚠ 混合模块（既读 ESI 又读 InCites，如 `extract_matrix.py` / `extract_incites.py`）
不能按模块一刀切，靠第 2 条的函数级词元判定——**新增 ESI 读取函数时命名请带 `esi`**。

用法：
    .venv\\Scripts\\python.exe tools\\guard_no_readonly.py
    .venv\\Scripts\\python.exe tools\\guard_no_readonly.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 整模块只读 ESI 的读取器——这里任何 `read_only=True` 都判失败。
#: 新增「只读 ESI」的模块请补进本表。
PURE_ESI_MODULES = {
    "extract_esi.py",
    "extract_1permille.py",
    "extract_province.py",
    "extract_forecast_pairs.py",
}

#: 字符串字面量里出现这些 = 在碰 ESI 包。
ESI_STRING_MARKERS = (
    "ESI数据", "ESI_数据", "ThresholdESI", "IndicatorsExport",
    "DocumentsExport", "BaselinePercentiles", "BaselineCitationRates",
    "BaselineFieldRankings",
)

#: 扫描范围（相对仓根）。
SCAN_DIRS = ("tools", "src")


def _is_esi_token(tok: str) -> bool:
    """标识符按 `_` 切词，任一词元等于 `esi` 即算 ESI 相关。"""
    return any(part.lower() == "esi" for part in tok.strip("_").split("_") if part)


def _str_marks_esi(s: str) -> bool:
    return any(m in s for m in ESI_STRING_MARKERS)


def _is_readonly_true(call: ast.Call) -> bool:
    """是不是 `…load_workbook(..., read_only=True, ...)`。"""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name != "load_workbook":
        return False
    return any(
        kw.arg == "read_only"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in call.keywords
    )


class _Scan(ast.NodeVisitor):
    """逐作用域收集标识符 / 字符串 / read_only 调用点。"""

    def __init__(self, pure: bool):
        self.pure = pure
        self.scopes: list[dict] = [{"name": "<module>", "tokens": set(), "strings": [], "calls": []}]
        self._stack = [self.scopes[0]]

    def _cur(self) -> dict:
        return self._stack[-1]

    def _note(self, tok: str) -> None:
        self._cur()["tokens"].add(tok)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        scope = {"name": node.name, "tokens": set(), "strings": [], "calls": []}
        for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            scope["tokens"].add(a.arg)
        if node.args.vararg:
            scope["tokens"].add(node.args.vararg.arg)
        if node.args.kwarg:
            scope["tokens"].add(node.args.kwarg.arg)
        self.scopes.append(scope)
        self._stack.append(scope)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node):                       # noqa: N802
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node):                  # noqa: N802
        self._visit_func(node)

    def visit_Name(self, node):                              # noqa: N802
        self._note(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):                         # noqa: N802
        self._note(node.attr)
        self.generic_visit(node)

    def visit_Constant(self, node):                          # noqa: N802
        if isinstance(node.value, str):
            self._cur()["strings"].append(node.value)

    def visit_Call(self, node):                              # noqa: N802
        if _is_readonly_true(node):
            self._cur()["calls"].append(node.lineno)
        self.generic_visit(node)

    def verdicts(self) -> list[tuple[str, int, str]]:
        out: list[tuple[str, int, str]] = []
        for sc in self.scopes:
            scope_is_esi = (
                any(_is_esi_token(t) for t in sc["tokens"])
                or any(_str_marks_esi(s) for s in sc["strings"])
            )
            for line in sc["calls"]:
                level = "FAIL" if (self.pure or scope_is_esi) else "info"
                out.append((level, line, sc["name"]))
        return out


def scan_source(src: str, pure: bool = False) -> list[tuple[str, int, str]]:
    tree = ast.parse(src)
    scanner = _Scan(pure)
    scanner.visit(tree)
    return scanner.verdicts()


def scan_file(path: pathlib.Path) -> list[tuple[str, int, str]]:
    # utf-8-sig：吃掉 BOM（仓里有几个文件带 BOM，按 utf-8 读会 ast 解析失败而漏扫）。
    src = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        return scan_source(src, pure=path.name in PURE_ESI_MODULES)
    except SyntaxError as e:
        return [("error", getattr(e, "lineno", 0) or 0, f"语法错误: {e.msg}")]


def iter_targets(root: pathlib.Path):
    for d in SCAN_DIRS:
        base = root / d
        if base.is_dir():
            yield from sorted(base.rglob("*.py"))


def run(root: pathlib.Path) -> int:
    fails: list[tuple[pathlib.Path, int, str]] = []
    infos: list[tuple[pathlib.Path, int, str]] = []
    errors: list[tuple[pathlib.Path, int, str]] = []
    for path in iter_targets(root):
        for level, line, func in scan_file(path):
            (fails if level == "FAIL" else errors if level == "error" else infos).append(
                (path, line, func)
            )

    rel = lambda p: p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)  # noqa: E731

    print(f"== 读 ESI 包禁 read_only=True 护栏（扫 {', '.join(SCAN_DIRS)}/）")
    for path, line, func in errors:
        print(f"[ERR ] {rel(path)}:{line}  {func}")
    for path, line, func in fails:
        print(f"[FAIL] {rel(path)}:{line}  {func}  —— 读 ESI 包却用 read_only=True（会读成 1×1 空表）")
    for path, line, func in infos:
        print(f"[info] {rel(path)}:{line}  {func}  —— read_only=True（非 ESI，人工确认）")

    if fails:
        print(f"\n[✗] {len(fails)} 处失败：改成 `load_workbook(path, data_only=True)`（去掉 read_only）。")
        return 1
    print(f"\n[✓] 通过：无「读 ESI 包却用 read_only」的调用点"
          f"（另有 {len(infos)} 处非 ESI 的 read_only 待人工确认）。")
    return 0


SELFTEST_CASES = [
    # (说明, 源码, 是否纯 ESI 模块, 期望：是否出现 FAIL)
    ("函数名/参数带 esi + read_only → FAIL",
     "import openpyxl\n"
     "def _esi_top_schools(esi_root, period, disc):\n"
     "    return openpyxl.load_workbook(esi_root / disc, read_only=True, data_only=True)\n",
     False, True),
    ("函数碰 esi_dir + read_only → FAIL",
     "import openpyxl\n"
     "def load(esi_dir):\n"
     "    wb = openpyxl.load_workbook(esi_dir / 'x.xlsx', read_only=True)\n",
     False, True),
    ("纯 ESI 模块里任意 read_only → FAIL",
     "import openpyxl\n"
     "def parse_ranking(path):\n"
     "    return openpyxl.load_workbook(path, read_only=True, data_only=True)\n",
     True, True),
    ("读 InCites 快照 + read_only → 不 FAIL（只 info）",
     "import openpyxl\n"
     "def _read_school_cites(snap, disc):\n"
     "    return openpyxl.load_workbook(disc, read_only=True, data_only=True)\n",
     False, False),
    ("普通模式（无 read_only）→ 无命中",
     "import openpyxl\n"
     "def _rows(p):\n"
     "    return openpyxl.load_workbook(p, data_only=True)\n",
     False, False),
]


def selftest() -> int:
    bad = 0
    for desc, src, pure, want_fail in SELFTEST_CASES:
        got_fail = any(level == "FAIL" for level, _, _ in scan_source(src, pure=pure))
        ok = got_fail == want_fail
        bad += 0 if ok else 1
        print(f"[{'✓' if ok else '✗'}] {desc}（期望 FAIL={want_fail}，实测 FAIL={got_fail}）")
    print(f"\n{'[✓] 自测通过' if not bad else f'[✗] 自测 {bad} 项不符'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="护栏：读 ESI 原始包禁 read_only=True")
    ap.add_argument("--root", default=str(ROOT), help="仓根（默认本文件上一级）")
    ap.add_argument("--selftest", action="store_true", help="用内嵌样例自证护栏有效")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run(pathlib.Path(args.root).resolve())


if __name__ == "__main__":
    sys.exit(main())
