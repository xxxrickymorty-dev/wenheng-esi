# -*- coding: utf-8 -*-
"""动态监测表（母本）路径的**唯一口径**（2026-10-13 rick 定：`input/` 只放母本）。

- **运行时输入**：`input/云大全学科排名、阈值动态检测表.xlsx`——流水线/开跑口/问答
  回落/盘点/e2e/部署包都只认这一份；开发机与部署机同路径，零分叉。
- **馆员原件**：`../数据与复现/云大全学科排名、阈值动态检测表.xlsx`——「并入台账」
  的写入面（ADR-0004）；`sync()` 把原件同步到运行时输入，并入后调用。
- **每期不再另存表**：当期取数核对副本落 `out/_acquisition/<期次>/监测表.xlsx`
  （见 `acquisition_state.copy_path`），不叫「监测表」，也不再进 `input/`。

历史期补跑＝母本 + 目标期次（`run_pipeline.py <母本> --period <期次>`；`src/rerun_history.py`
同口径），报告各步按被补跑期切窗——"07 的报告不读 09 的数据"在消费层强制。

工具面若要「运行时优先、回落原件」的定位、沙盘副本与工作簿契约（表清单 / 母版 /
数据源目录），走 `ledger_contract`——它只组合本文件的路径，不另写字面量。
"""
from __future__ import annotations

import pathlib
import shutil

import xlsx_io

#: 母本文件名（与馆员原件同名；术语「动态监测表」见 GLOSSARY）。
LEDGER_NAME = "云大全学科排名、阈值动态检测表.xlsx"


def runtime_path(repo_root) -> pathlib.Path:
    """运行时输入：`<repo>/input/<母本>`。"""
    return pathlib.Path(repo_root) / "input" / LEDGER_NAME


def source_path(repo_root) -> pathlib.Path:
    """馆员原件：`<工作区>/数据与复现/<母本>`（并入台账的写入面）。"""
    return pathlib.Path(repo_root).parent / "数据与复现" / LEDGER_NAME


def mirror_path(repo_root) -> pathlib.Path:
    """台账镜像（SQLite，只读派生；2026-10-13 票 01）：`<repo>/out/_mirror/ledger.sqlite`。

    由 `src/ledger_mirror.py` 从母本确定性重建；**单向 ETL**，永不回写母本。
    """
    return pathlib.Path(repo_root) / "out" / "_mirror" / "ledger.sqlite"


def sha256(path) -> str:
    """文件指纹（唯一实现 `xlsx_io.sha256_file`；缺文件抛）。"""
    return xlsx_io.sha256_file(path)


def sync(repo_root) -> pathlib.Path:
    """馆员原件 → 运行时输入（并入台账后调用；部署包预检核对两者 sha）。"""
    src = source_path(repo_root)
    dst = runtime_path(repo_root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst
