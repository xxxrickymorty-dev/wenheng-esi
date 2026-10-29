# -*- coding: utf-8 -*-
"""本地开发端口盘点：谁在占、是不是本项目的历史端口。

**只读工具**：不杀进程、不改文件。

规则见 `AGENTS.md`「本地端口」：服务只许起在 8080；前端开发态才起 5173；
临时静态预览用完就关。本工具用于「端口怎么又多了一个」时一眼看清占用者。

用法：
    uv run python tools/ports.py
    uv run python tools/ports.py --all     # 连非本项目的回环端口一起列
"""
from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys

#: 本项目用过的端口。**除 8080 外，任何一个在听都算违规**。
LEGACY = {
    5173: "vite dev（前端开发态，默认端口）",
    5180: "vite dev（历史端口，已废弃）",
    5181: "vite dev（历史端口，已废弃）",
    8080: "唯一入口（FastAPI：/ + /app/ + /api）",
    8081: "uvicorn 历史端口（部署机 nginx 后端）",
    8082: "uvicorn 历史端口",
    8091: "uvicorn 历史端口",
    8777: "http.server 静态预览（临时，用完即关）",
}

#: 不是本项目、不要动的进程
FOREIGN = {"sandbox-cli.exe", "clash", "clash-verge", "clash-verge-service"}


def parse_netstat(text: str) -> list[dict]:
    """从 `netstat -ano` 输出里挑出本机回环的 LISTENING 行。

    只认 127.0.0.1 / [::1]：对外监听属部署范畴，不在本工具范围。
    """
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or "LISTENING" not in parts[3].upper():
            continue
        proto, local, pid = parts[0], parts[1], parts[-1]
        host, _, port_s = local.rpartition(":")
        if host not in ("127.0.0.1", "[::1]"):
            continue
        if not port_s.isdigit() or not pid.isdigit():
            continue
        rows.append({"proto": proto, "host": host, "port": int(port_s), "pid": int(pid)})
    return rows


def _decode(raw: bytes) -> str:
    """Windows 控制台是 GBK，个别工具输出 UTF-8——两种都试。"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20)
        return _decode(out.stdout or b"")
    except (OSError, subprocess.SubprocessError):
        return ""


def process_names() -> dict[int, str]:
    """PID → 进程名。取不到就返回空表（工具仍可用，只是少一列）。"""
    text = _run(["tasklist", "/FO", "CSV", "/NH"])
    if not text.strip():
        return {}
    out: dict[int, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[1].strip().isdigit():
            out[int(row[1])] = row[0].strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="本地开发端口盘点（只读）")
    ap.add_argument("--all", action="store_true", help="连非本项目的回环端口一起列")
    args = ap.parse_args()

    rows = parse_netstat(_run(["netstat", "-ano"]))
    if not rows:
        print("没有回环监听端口（netstat 取不到？）。")
        return 0

    names = process_names()
    by_port: dict[int, dict] = {}
    for r in rows:
        by_port.setdefault(r["port"], r)

    if not args.all:
        shown = {p: v for p, v in by_port.items() if p in LEGACY}
        if not shown:
            print("本项目端口一个都没在听。")
            return 0
    else:
        shown = by_port

    print(f"{'端口':<6}{'PID':<8}{'进程':<16}用途")
    print("-" * 78)
    for port in sorted(shown):
        r = shown[port]
        name = names.get(r["pid"], "—")
        print(f"{port:<6}{r['pid']:<8}{name:<16}{LEGACY.get(port, '（非本项目端口）')}")

    bad = [p for p in shown if p in LEGACY and p != 8080]
    foreign = [p for p in shown if names.get(shown[p]["pid"], "").lower() in
               {f.lower() for f in FOREIGN}]
    print("-" * 78)
    if bad:
        print(f"⚠ 除 8080 外还有 {len(bad)} 个本项目端口在听：{sorted(bad)}")
        print("  AGENTS.md「本地端口」：起不来先查占用者，不要换端口试探。")
    elif 8080 in shown:
        print("✓ 只有 8080 在听，符合约定。")
    if foreign:
        print(f"（{len(foreign)} 个非本项目进程，不要关：{sorted(foreign)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
