# -*- coding: utf-8 -*-
"""文衡演示站 · 「这一期下载的数据」打包下载（2026-10-19 馆员需求）。

把一期已取到的**原始下载数据**打成一个 zip，给馆员/操作员存回本地：

    ESI数据/<期次>/…         （数据与复现/ESI数据/<期次>，只读）
    InCites数据/<快照>/…      （数据与复现/incites/<当期快照>，只读）
    说明.txt                  （期次、数据期、打包时间、件数、只读说明）

三条约束（与运行档案的日志包同族，但数据源不同）：

1. **只读源**：不碰台账、不写 out/；zip 落系统临时目录，响应结束即删（调用方挂后台任务）。
2. **ZIP_STORED**：xlsx/csv 本身已是压缩包，再 deflate 只费 CPU 不省体积；
   一个当期包 150–300 MB，stored 打包秒级完成。
3. **包内中文、包名 ASCII**：zip 文件名保持 ASCII（个别浏览器中文名会乱码，与日志包同口径）；
   包内目录与说明用中文（`zipfile` 自带 UTF-8 标记）。

本模块只打包，不碰 FastAPI；路径与快照名由调用方解析后传入。
"""
from __future__ import annotations

import datetime as dt
import pathlib
import zipfile

README_NAME = "说明.txt"
ESI_ARC_ROOT = "ESI数据"
INCITES_ARC_ROOT = "InCites数据"


class EmptyPack(Exception):
    """一个文件都没打到（源目录不存在或为空）——别发一个空包出去。"""


def _dir_stats(d: pathlib.Path | str | None) -> tuple[int, int]:
    """→ (文件数, 字节数)；目录不存在按 (0, 0)。"""
    if not d:
        return 0, 0
    p = pathlib.Path(d)
    if not p.is_dir():
        return 0, 0
    files = [x for x in p.rglob("*") if x.is_file()]
    return len(files), sum(x.stat().st_size for x in files)


def _mb(n: int) -> str:
    return f"约 {n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"约 {max(1, round(n / 1024))} KB"


def build_readme(*, period: str, snapshot: str = "", verified: int | None = None,
                 expected: int | None = None, esi_dir: pathlib.Path | str | None = None,
                 incites_dir: pathlib.Path | str | None = None) -> str:
    """人话说明（放在包里的 `说明.txt`）。所有数字都来自实扫与状态，不编。

    只带一路（拆包下载的常态）时标题自动标「ESI 部分 / InCites 部分」。
    """
    n_esi, b_esi = _dir_stats(esi_dir)
    n_inc, b_inc = _dir_stats(incites_dir)
    title = "文衡 · 下载数据包"
    if n_esi and not n_inc:
        title += "（ESI 部分）"
    elif n_inc and not n_esi:
        title += "（InCites 部分）"
    lines = [
        title,
        "=" * 18,
        f"期次：{period}",
        f"数据期（InCites 快照）：{snapshot or '未登记'}",
        f"打包时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if verified is not None and expected:
        lines.append(f"本期取数进度：已取到 {verified} / {expected}")
    lines += [
        "",
        "包内内容",
        "-" * 18,
    ]
    if n_esi:
        lines.append(f"ESI数据/{period}/　　{n_esi} 份文件（{_mb(b_esi)}）")
    if n_inc:
        lines.append(f"InCites数据/{snapshot}/　　{n_inc} 份文件（{_mb(b_inc)}）")
    lines += [
        "",
        "说明",
        "-" * 18,
        "· 本包是当期「已下载的原始数据」原件（从两个数据站导出的文件），只读留存用；",
        "· 不含台账、报告与核对副本——那些在文衡工作区里生成；",
        "· 没下全的期次，包里就是已下载的部分（件数见上）。",
    ]
    return "\n".join(lines) + "\n"


def pack(out_path: pathlib.Path | str, *, period: str, esi_dir: pathlib.Path | str | None = None,
         incites_dir: pathlib.Path | str | None = None, readme: str = "") -> dict:
    """把一期数据写到 `out_path`（zip）。返回 {files, esi_files, incites_files, bytes}。

    源目录只读；一个文件都没有时抛 `EmptyPack`（并删掉半成品）。
    """
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    stats = {"files": 0, "esi_files": 0, "incites_files": 0, "bytes": 0}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        if readme:
            z.writestr(README_NAME, readme)
        for arc_root, src in ((ESI_ARC_ROOT, esi_dir), (INCITES_ARC_ROOT, incites_dir)):
            if not src:
                continue
            src = pathlib.Path(src)
            if not src.is_dir():
                continue
            for p in sorted(src.rglob("*")):
                if not p.is_file():
                    continue
                z.write(p, f"{arc_root}/{src.name}/{p.relative_to(src).as_posix()}")
                stats["files"] += 1
                if arc_root == ESI_ARC_ROOT:
                    stats["esi_files"] += 1
                else:
                    stats["incites_files"] += 1
    if not stats["files"]:
        out.unlink(missing_ok=True)
        raise EmptyPack(f"{period}：没有可打包的文件")
    stats["bytes"] = out.stat().st_size
    return stats
