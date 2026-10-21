# -*- coding: utf-8 -*-
"""动态监测表的**契约面**：路径、指纹、沙盘副本、表清单与学科清单。

为什么有这一层
--------------
`ledger.py` 仍是路径口径的唯一实现（ADR-0007 §1）；但它只回答「母本在哪」。
换馆沙盘、自愈沙盘这类工具还要回答另外几件事，过去各写一份：

- 运行时母本 → 馆员原件的回落顺序（两个工具各有一个逐字重复的 `find_ledger`）；
- 文件名 `LEDGER_NAME`（`ledger.py` / `inventory.py` / 两个工具各一份）；
- 工作簿要读哪些表（`migration_check.REQUIRED_SHEETS` 12 张，而
  `parse_ledger.load_ledger()` 实际打开 17 张）；
- 母版路径、`数据与复现/` 下的数据源目录（`migration_check` 硬编码）；
- 沙盘副本的复制规则与文件指纹。

本模块把这些收成一个接口。**不重抄常量**：路径与文件名来自 `ledger`，
宽表来自 `parse_ledger.WIDE_SHEETS`，写链白名单来自 `ledger_merge`，
学科名单来自 `parse_ledger.DISCIPLINES_CN`。

三种表清单是三个**真实不同的作用域**，不要合并
------------------------------------------------
- `WIDE_SHEETS`（6）：学科 × 期次的宽表，解析器统一按 `parse_wide` 读；
- `READINESS_SHEETS`（17）：`parse_ledger.load_ledger()` 会打开的全部工作表。
  换馆前「表结构是否齐全」按它判——旧 readiness 只查 12 张，改名
  `高校学科发展` 时检查会放行、解析却会 `KeyError`；
- `CHAIN_SHEETS` / `SHEET_SOURCE`（17）：清洗链**会写**的工作表，含
  `InCites快照`、不含 `高校学科发展`。它是写链白名单，不是读表契约。

story JSON（`tmp/_heal_sandbox/story.json`、`tmp/_migration_sandbox/readiness.json`）
仍由两个工具按原字段写；本模块不碰它们的形状。
"""
from __future__ import annotations

import pathlib
import shutil

import ledger
import ledger_merge
import parse_ledger

#: 仓库根（`wenheng/`）；「数据与复现」在它的上一级。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 母本文件名。**同一个对象**来自 `ledger.LEDGER_NAME`，不再写第二份字面量。
LEDGER_NAME = ledger.LEDGER_NAME

#: 报告结构母版（换馆检查用；正文母版本身不随台账走）。
MASTER_NAME = "学科信息参考母版_2026第5期.docx"

#: 学科宽表（6）——解析器按 `parse_wide` 统一读的那一组。
WIDE_SHEETS = tuple(parse_ledger.WIDE_SHEETS)

#: `load_ledger()` 实际打开的全部工作表（17）。readiness 用它，不用旧的 12 张。
READINESS_SHEETS = WIDE_SHEETS + (
    "云大ESI排名", "新国际排名", "新国内排名", "国际排名", "国内排名",
    "千分之一被引阈值", "篇均被引", "Q1-Q4", "高校学科发展",
    "实际与预测差值", "学科进入时间",
)

#: 清洗链写后核对的白名单（17）——与读表契约不同作用域，见模块文档。
SHEET_SOURCE = ledger_merge.SHEET_SOURCE
CHAIN_SHEETS = ledger_merge.CHAIN_SHEETS

#: 22 个规范学科（英→中）。readiness 的「中/英任一认得出」就查这份。
DISCIPLINES_EN = tuple(parse_ledger.DISCIPLINES_EN)
DISCIPLINES_CN = parse_ledger.DISCIPLINES_CN


def runtime_path(repo_root=None) -> pathlib.Path:
    """运行时母本：`<repo>/input/<母本>`。"""
    return ledger.runtime_path(REPO_ROOT if repo_root is None else repo_root)


def source_path(repo_root=None) -> pathlib.Path:
    """馆员原件：`<工作区>/数据与复现/<母本>`。"""
    return ledger.source_path(REPO_ROOT if repo_root is None else repo_root)


def locate(repo_root=None) -> pathlib.Path | None:
    """运行时母本优先，缺失回落馆员原件；两边都没有返回 None（不猜、不扫）。"""
    root = REPO_ROOT if repo_root is None else repo_root
    for path in (ledger.runtime_path(root), ledger.source_path(root)):
        if path.is_file():
            return path
    return None


def require(repo_root=None) -> pathlib.Path:
    """同 `locate`，但缺失时按旧工具的 CLI 语义退出。"""
    path = locate(repo_root)
    if path is None:
        raise SystemExit(f"找不到台账：{LEDGER_NAME}")
    return path


def sha256(path) -> str:
    """文件指纹。实现唯一在 `ledger.sha256`（→ `xlsx_io.sha256_file`）；缺文件抛。"""
    return ledger.sha256(path)


def sandbox_copy(src, dst, *, refresh: bool = False) -> pathlib.Path:
    """把母本复制到沙盘路径；默认只在目标缺失或比源旧时复制。

    `refresh=True` 强制覆盖（自愈沙盘每次都从干净母本重做脏件）。
    """
    src = pathlib.Path(src)
    dst = pathlib.Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if refresh or not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dst)
    return dst


def data_root(repo_root=None) -> pathlib.Path:
    """`<工作区>/数据与复现/`——ESI 包、InCites 快照、馆员原件的共同父目录。"""
    root = REPO_ROOT if repo_root is None else pathlib.Path(repo_root)
    return root.parent / "数据与复现"


def esi_root(repo_root=None) -> pathlib.Path:
    """`<工作区>/数据与复现/ESI数据/`。"""
    return data_root(repo_root) / "ESI数据"


def incites_root(repo_root=None) -> pathlib.Path:
    """`<工作区>/数据与复现/incites/`。"""
    return data_root(repo_root) / "incites"


def master_path(repo_root=None) -> pathlib.Path:
    """报告结构母版：`<repo>/master/<母版名>`。"""
    root = REPO_ROOT if repo_root is None else pathlib.Path(repo_root)
    return root / "master" / MASTER_NAME
