# -*- coding: utf-8 -*-
"""扫 web/src：每个模块用了哪些 api 函数 + 行数 → markdown。

用途：让新模型不读 89 个前端文件也能定位改动点。
输出：docs/refactor/front-map.md
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "web" / "src"

IMPORT_RE = re.compile(r"import\s+(?:type\s+)?\{([^}]*)\}\s+from\s+'([^']*api)'", re.S)
CALL_RE = re.compile(r"\b(\w+)\(")
EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?(?:function|const)\s+(\w+)", re.M)


def real_exports() -> set[str]:
    """api.ts 里真正的值导出（函数/常量），用来过滤误报的类型名。"""
    names: set[str] = set()
    for p in SRC.glob("api*.ts"):
        names |= set(EXPORT_RE.findall(p.read_text(encoding="utf-8", errors="ignore")))
    return names


def api_names(text: str) -> tuple[list[str], list[str]]:
    """返回 (值导入, 类型导入)。"""
    vals, types = [], []
    for m in IMPORT_RE.finditer(text):
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            if item.startswith("type "):
                types.append(item[5:].strip())
            else:
                vals.append(item.split(" as ")[0].strip())
    return vals, types


def main() -> None:
    real = real_exports()
    rows = []
    for p in sorted(SRC.rglob("*")):
        if p.suffix not in {".ts", ".tsx"} or p.name.endswith(".d.ts"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        n = len(text.splitlines())
        vals, types = api_names(text)
        # 只留 api 层真实导出的值（老代码有漏写 type 前缀的导入）
        vals = [v for v in vals if v in real]
        if p.name.startswith("api"):
            vals = []  # api 层自身不算依赖自己
        rows.append(
            {
                "path": str(p.relative_to(ROOT)).replace("\\", "/"),
                "lines": n,
                "api": vals,
                "types": types,
            }
        )

    rows.sort(key=lambda r: (-len(r["api"]), -r["lines"]))

    out = [
        "# 前端模块地图（自动生成）",
        "",
        f"> 扫描 `web/src`（{len(rows)} 个 ts/tsx，"
        f"{sum(r['lines'] for r in rows)} 行）。生成脚本 `tools/gen_front_map.py`。",
        "> `依赖 api` 一列就是该文件的对外耦合面——重构时按列切，不要按文件名字母序切。",
        "",
        "## 按 API 耦合数排序（改动风险最高的在前）",
        "",
        "| 文件 | 行数 | 依赖 api 函数 |",
        "|---|---:|---|",
    ]
    for r in rows:
        if not r["api"]:
            continue
        out.append(
            f"| `{r['path']}` | {r['lines']} | {', '.join(f'`{a}`' for a in r['api'])} |"
        )

    out += ["", "## 无 API 耦合（纯展示 / 纯样式 / 工具）", "", "| 文件 | 行数 |", "|---|---:|"]
    for r in rows:
        if r["api"]:
            continue
        out.append(f"| `{r['path']}` | {r['lines']} |")

    dest = ROOT / "docs" / "refactor" / "front-map.md"
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {dest} ({len(rows)} files)")


if __name__ == "__main__":
    main()
