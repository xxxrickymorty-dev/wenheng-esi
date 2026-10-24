# -*- coding: utf-8 -*-
"""从 server/app.py 提取路由清单 → markdown 表格。

用途：让新模型不读 3000 行 app.py 也能知道有哪些接口。
输出：docs/refactor/route-map.md
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "server" / "app.py"

DEC = re.compile(r"^@app\.(get|post|put|delete|patch|api_route)\((.*)$")
FUNC = re.compile(r"^async def (\w+)|^def (\w+)")


def main() -> None:
    lines = APP.read_text(encoding="utf-8").splitlines()
    hits: list[dict] = []
    for i, line in enumerate(lines):
        if not line.startswith("@app."):
            continue
        m = DEC.match(line)
        if not m:
            continue
        method = m.group(1).upper()
        if method == "API_ROUTE":
            mm = re.search(r"methods=\[([^\]]*)\]", m.group(2))
            method = "/".join(
                x.strip().strip('"\'') for x in mm.group(1).split(",")
            ) if mm else "?"
        args = m.group(2).rstrip(")")
        # 路由字符串
        rm = re.search(r'"([^"]*)"', args)
        path = rm.group(1) if rm else "?"
        # 向后找 8 行内的函数名
        name = "?"
        for j in range(i + 1, min(i + 9, len(lines))):
            fm = FUNC.match(lines[j])
            if fm:
                name = fm.group(1) or fm.group(2)
                hits.append(
                    {
                        "line": i + 1,
                        "method": method,
                        "path": path,
                        "name": name,
                        "span": 0,
                    }
                )
                break

    # 相邻相减得到大致块长
    for k, h in enumerate(hits):
        end = hits[k + 1]["line"] if k + 1 < len(hits) else len(lines)
        h["span"] = end - h["line"]

    out = [
        "# 后端路由清单（自动生成）",
        "",
        f"> 来源 `server/app.py`（{len(lines)} 行，{len(hits)} 个路由）。",
        "> 生成脚本 `tools/gen_route_map.py`。**不要手改本文件**，改 app.py 后重跑。",
        "> `行号区间` 是该处理函数的大致位置——排查时只读这一段，不要读全文。",
        "",
        "| # | 方法 | 路径 | 处理函数 | 行号区间 | 行数 |",
        "|---:|---|---|---|---|---:|",
    ]
    for k, h in enumerate(hits, 1):
        span = h["span"]
        out.append(
            f"| {k} | {h['method']} | `{h['path']}` | `{h['name']}` | "
            f"{h['line']}–{h['line'] + span - 1} | {span} |"
        )

    # 分组统计
    groups: dict[str, int] = {}
    for h in hits:
        p = h["path"]
        if p.startswith("/api/"):
            seg = p.split("/")
            key = "/".join(seg[:3]) if len(seg) > 2 else p
        elif p.startswith("/p/"):
            key = "/p/{period}/*"
        else:
            key = p
        groups[key] = groups.get(key, 0) + 1

    out += ["", "## 分组计数", "", "| 前缀 | 路由数 |", "|---|---:|"]
    for key, n in sorted(groups.items(), key=lambda kv: -kv[1]):
        out.append(f"| `{key}` | {n} |")

    dest = ROOT / "docs" / "refactor" / "route-map.md"
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {dest} ({len(hits)} routes, {len(lines)} lines)")


if __name__ == "__main__":
    main()
