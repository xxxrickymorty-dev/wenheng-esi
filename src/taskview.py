# -*- coding: utf-8 -*-
"""本期任务视图（票 06）：第一屏「我现在该做什么」的三步状态。

三步（UX.md §七：取数 → 核对并并入 → 一键生成）**全部从既有产物判**，不新算：

- ① 取数：四件**按文件**判（动态监测表 / ESI 原始包 / 顶尖论文清单 / InCites 快照）——
  取数先于人工作出，「在不在台账」不影响这一步（复用 `inventory` 的件判据）；
- ② 核对并并入：该期在主台账**有效期次**里（并入的凭证）；
- ③ 一键生成：`out/<期次>/red_slots.json` 在（出过稿的凭证）。

本期＝**最新一期**（台账有效期次 ∪ 取数在途 ∪ out 目录里最新的六位数字目录）。
取数在途＝`out/_acquisition/<期次>/`（核对副本已建）或 `out/_acquisition/<期次>.json`
（状态已写）——2026-10-13 起 input/ 只放母本，旧的「input 六位目录」信号退役。
它三步全成**且已签发** → 顺延到下一期（双月序列，+2 个月）——把「等发布」摆上来；
三步全成但没签发 → 停在本期、卡在「签单」（下一步是复核并签，不是开新期）。

签发是 server 层的账（`approval`）——调用方经 `status=` 注入（signed/stale/unsigned），
本模块不 import server。只读、零副作用；路径与台账都可注入（repo_root / filled），测试用 tmp。
"""
from __future__ import annotations

import pathlib
import re

#: 仓库根（wenheng/）；input 与 out 都在它下面（数据与复现 在上一级）。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 六位期次目录名（`_superseded` 等不会被当成一期）。
_PERIOD_DIR = re.compile(r"^20\d{4}$")

#: 三步（顺序即展示顺序；键是稳定标识）。
STEPS = ("acquire", "merge", "generate")


def next_period(period: str) -> str:
    """下一期＝+2 个月（双月序列；11 月的下期是次年 1 月）。"""
    year, month = int(period[:4]), int(period[4:6])
    month += 2
    if month > 12:
        month -= 12
        year += 1
    return f"{year:04d}{month:02d}"


def prev_period(period: str) -> str:
    """上一期＝−2 个月（1 月的上期是前一年 11 月）。"""
    year, month = int(period[:4]), int(period[4:6])
    month -= 2
    if month < 1:
        month += 12
        year -= 1
    return f"{year:04d}{month:02d}"


def _dirs(parent: pathlib.Path) -> set:
    if not parent.is_dir():
        return set()
    return {p.name for p in parent.iterdir() if p.is_dir() and _PERIOD_DIR.fullmatch(p.name)}


def _acq_periods(root: pathlib.Path) -> set:
    """取数在途的期次：`out/_acquisition` 下的六位目录（核对副本）或状态文件。"""
    d = root / "out" / "_acquisition"
    names = set()
    if d.is_dir():
        for p in d.iterdir():
            if p.is_dir() and _PERIOD_DIR.fullmatch(p.name):
                names.add(p.name)
            elif p.is_file() and p.suffix == ".json" and _PERIOD_DIR.fullmatch(p.stem):
                names.add(p.stem)
    return names


def _product_dirs(root: pathlib.Path) -> set:
    """出过稿的产物目录（凭证＝`red_slots.json`，与服务器 `resolve_period_dir` 同一判据）。"""
    d = root / "out"
    if not d.is_dir():
        return set()
    return {p.name for p in d.iterdir()
            if p.is_dir() and _PERIOD_DIR.fullmatch(p.name)
            and (p / "red_slots.json").is_file()}


def known_periods(*, repo_root=None, filled=None) -> list[str]:
    """**有数据/产物的期次**（**降序**）：母本有效期次 ∪ 出过稿的产物目录。

    「最新的」解析用它（服务端注入 `payload.periods`，2026-10-13 票 10）——期次＝数据截止月：
    **取数在途、只记过对话的目录都不算**（没数据，不算一期）。与「本期任务」（`scan`，含在途）
    的差别仅此一处：那边回答「任务走到哪」，这边回答「哪一期有数可查」。台账读不到 → `[]`（不编、不猜）。
    """
    root = pathlib.Path(repo_root) if repo_root else REPO_ROOT
    if filled is None:
        import inventory                                        # noqa: PLC0415
        import ledger as ledger_mod                             # noqa: PLC0415

        runtime = ledger_mod.runtime_path(root)
        ledger = runtime if runtime.exists() else \
            root.parent / "数据与复现" / inventory.LEDGER_NAME
        try:
            filled = inventory._filled_for(ledger)
        except Exception:                                       # noqa: BLE001
            return []
    known = set(filled) | _product_dirs(root)
    return sorted(known, reverse=True)


def _acquire_state(period: str, root: pathlib.Path) -> tuple:
    """四件**按文件**判 → (齐没齐, 缺几件)。复用 inventory（released 显式给，不读台账）。"""
    import inventory                                            # noqa: PLC0415

    inv = inventory.scan(period, repo_root=root, released=True)
    if inv is None:                                             # 防御：理论到不了
        return False, len(inventory.LABELS)
    return inv.ok, int(inv.n_missing)


def scan(*, repo_root=None, filled=None, status=None) -> dict | None:
    """本期任务扫描。没有任何期次痕迹 → None（界面退回普通问候，不编）。

    `filled`：主台账有效期次（测试注入；缺省走 `inventory._filled_for` 的 mtime 缓存）。
    `status`：`period -> 签发状态`（"signed"｜"stale"｜"unsigned"…）——server 层注入
    `approval`；缺省视为未签。只有 `signed` 才算做完（stale＝重签前的真空）。
    """
    root = pathlib.Path(repo_root) if repo_root else REPO_ROOT
    if filled is None:
        import inventory                                        # noqa: PLC0415
        import ledger as ledger_mod                             # noqa: PLC0415

        runtime = ledger_mod.runtime_path(root)
        ledger = runtime if runtime.exists() else \
            root.parent / "数据与复现" / inventory.LEDGER_NAME
        try:
            filled = inventory._filled_for(ledger)
        except Exception:                                       # noqa: BLE001
            return None
    filled_set = set(filled)

    def is_signed(period: str) -> bool:
        return bool(status and status(period) == "signed")

    known = filled_set | _dirs(root / "out") | _acq_periods(root)
    if not known:
        return None
    period = max(known)

    acquire_ok, n_missing = _acquire_state(period, root)
    merge_ok = period in filled_set
    generate_ok = (root / "out" / period / "red_slots.json").is_file()
    if acquire_ok and merge_ok and generate_ok and is_signed(period):
        # 本期做完（含签发）→ 看下一期（等发布）
        period = next_period(period)
        acquire_ok, n_missing = _acquire_state(period, root)
        merge_ok = period in filled_set
        generate_ok = (root / "out" / period / "red_slots.json").is_file()

    steps = [{"key": "acquire", "done": bool(acquire_ok)},
             {"key": "merge", "done": bool(merge_ok)},
             {"key": "generate", "done": bool(generate_ok)}]
    stuck = next((s["key"] for s in steps if not s["done"]), "")
    if not stuck and not is_signed(period):
        stuck = "sign"
    prev = prev_period(period)
    return {"period": period,
            "released": period in filled_set,
            "n_missing": int(n_missing),
            "steps": steps,
            "stuck": stuck,
            "prev": ({"period": prev,
                      "status": str(status(prev)) if status else "unsigned"}
                     if prev in filled_set else None)}
