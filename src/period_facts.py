# -*- coding: utf-8 -*-
"""期次事实：一个期次是什么、到哪一步、能不能开下一期。

这是**期次**生命周期的唯一 module：目录解析、盘点、并入、产物、签单状态、
下一期顺延、水位分类都在这里；`server.app` 的期次路由与 `taskview` 只是 adapter，
不再各自拼“out/ 目录 + red_slots + 取数状态 + 台账”的六套判据。

它只读、零副作用；路径与台账都可注入（repo_root / out_root / filled），
签单状态由调用方经 `status=` 注入（本模块不 import server）。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

import period as period_mod

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


def _out_root(root: pathlib.Path, out_root=None) -> pathlib.Path:
    return pathlib.Path(out_root) if out_root else root / "out"


def _dirs(parent: pathlib.Path) -> set:
    if not parent.is_dir():
        return set()
    return {p.name for p in parent.iterdir() if p.is_dir() and _PERIOD_DIR.fullmatch(p.name)}


def _product_dirs(out_root: pathlib.Path, *, allow_suffix: bool = False) -> set:
    """出过稿的产物目录（凭证＝`red_slots.json`，与服务器同一判据）。

    `allow_suffix=True` 用于期次列表：`202605_复现` 这类人工后缀仍是可对勘的产物；
    本期任务的选择只用严格六位（`current`），不把复现目录当成新一期。
    """
    if not out_root.is_dir():
        return set()
    rx = period_mod.PERIOD_DIR_RE if allow_suffix else _PERIOD_DIR
    return {p.name for p in out_root.iterdir()
            if p.is_dir() and rx.match(p.name)
            and (p / "red_slots.json").is_file()}


def _acq_periods(out_root: pathlib.Path) -> set:
    """取数在途的期次：`out/_acquisition` 下的六位目录（核对副本）或状态文件。"""
    d = out_root / "_acquisition"
    names = set()
    if d.is_dir():
        for p in d.iterdir():
            if p.is_dir() and _PERIOD_DIR.fullmatch(p.name):
                names.add(p.name)
            elif p.is_file() and p.suffix == ".json" and _PERIOD_DIR.fullmatch(p.stem):
                names.add(p.stem)
    return names


def _filled(root: pathlib.Path) -> list[str]:
    """主台账有效期次（按 mtime 缓存，慢变事实）。"""
    import inventory                                            # noqa: PLC0415
    import ledger as ledger_mod                                 # noqa: PLC0415

    runtime = ledger_mod.runtime_path(root)
    ledger = runtime if runtime.exists() else \
        root.parent / "数据与复现" / inventory.LEDGER_NAME
    return inventory._filled_for(ledger)


def _acquire_state(period: str, root: pathlib.Path) -> tuple:
    """四件按文件判 → (齐没齐, 缺几件)；不读台账。"""
    import inventory                                            # noqa: PLC0415

    inv = inventory.scan(period, repo_root=root, released=True)
    if inv is None:                                             # 防御：理论到不了
        return False, len(inventory.LABELS)
    return inv.ok, int(inv.n_missing)


def resolve(period, out_root=None) -> pathlib.Path | None:
    """期次字符串 → out/ 下的实际目录（允许 202605_复现 这类后缀）。"""
    if not period_mod.PERIOD_DIR_RE.match(str(period or "")):
        return None
    d = _out_root(REPO_ROOT, out_root) / str(period)
    if d.is_dir() and (d / "red_slots.json").exists():
        return d
    return None


def product_periods(out_root=None, *, allow_suffix: bool = False) -> set:
    return _product_dirs(_out_root(REPO_ROOT, out_root), allow_suffix=allow_suffix)


def has_data(period, *, root=None, out_root=None, acquisition=None,
             copy_exists: bool = False) -> bool:
    """「期次认得出」的宽松口径：产物、取数状态/副本，任一即可（还没出稿也算）。"""
    del root
    d = resolve(period, out_root)
    return bool(d is not None or acquisition or copy_exists)


def known_periods(*, repo_root=None, filled=None) -> list[str]:
    """**有数据/产物**的期次（降序）：母本有效期次 ∪ 出过稿的产物目录。

    与 `current` 的差别：那边回答「任务走到哪」，这里回答「哪一期有数可查」；
    取数在途不算。台账读不到 → `[]`（不编、不猜）。
    """
    root = pathlib.Path(repo_root) if repo_root else REPO_ROOT
    if filled is None:
        try:
            filled = _filled(root)
        except Exception:                                       # noqa: BLE001
            return []
    known = set(filled) | _product_dirs(_out_root(root))
    return sorted(known, reverse=True)


@dataclass(frozen=True)
class PeriodFacts:
    """一个期次的事实：读它是唯一入口；调用方不再自行拼 out/ 与三步。

    `steps` 是 `(key, done)` 的元组；`as_home` 才是对话首屏的 JSON 形状。
    """

    period: str
    dir: pathlib.Path | None
    released: bool
    n_missing: int
    acquire_ok: bool
    merge_ok: bool
    generate_ok: bool
    stuck: str
    prev: dict | None
    has_data: bool
    acquisition: dict = field(default_factory=dict)

    @property
    def steps(self) -> tuple[tuple[str, bool], ...]:
        return (("acquire", self.acquire_ok),
                ("merge", self.merge_ok),
                ("generate", self.generate_ok))

    def as_home(self) -> dict:
        return {
            "period": self.period,
            "released": self.released,
            "n_missing": int(self.n_missing),
            "steps": [{"key": key, "done": bool(done)} for key, done in self.steps],
            "stuck": self.stuck,
            "prev": self.prev,
        }


def facts(period, *, repo_root=None, out_root=None, filled=None, status=None,
          acquisition=None, copy_exists: bool = False) -> PeriodFacts:
    """一个期次的事实；不猜、不写。"""
    root = pathlib.Path(repo_root) if repo_root else REPO_ROOT
    out = _out_root(root, out_root)
    if filled is not None:
        filled_set = set(filled)
    else:
        try:
            filled_set = set(_filled(root))
        except Exception:                                       # noqa: BLE001
            filled_set = set()
    d = resolve(period, out)
    acq = acquisition or {}
    acquire_ok, n_missing = _acquire_state(period, root)
    merge_ok = period in filled_set
    generate_ok = bool(d is not None and (d / "red_slots.json").is_file())
    # 出过稿 ⇒ 数据取到并并入了：缺件不再把已出稿的本期倒退成「卡在取数」。
    if generate_ok:
        merge_ok = True
        acquire_ok = True
    steps = (("acquire", acquire_ok), ("merge", merge_ok), ("generate", generate_ok))
    stuck = next((key for key, done in steps if not done), "")
    if not stuck and not (status and status(period) == "signed"):
        stuck = "sign"
    prev = prev_period(period)
    return PeriodFacts(
        period=period, dir=d, released=period in filled_set,
        n_missing=int(n_missing), acquire_ok=acquire_ok, merge_ok=merge_ok,
        generate_ok=generate_ok, stuck=stuck,
        prev=({"period": prev,
               "status": str(status(prev)) if status else "unsigned"}
              if prev in filled_set else None),
        has_data=bool(d is not None or acq or copy_exists),
        acquisition=dict(acq),
    )


def current(*, repo_root=None, out_root=None, filled=None, status=None) -> PeriodFacts | None:
    """本期＝最新一个有内容的期次（台账 ∪ 出过稿 ∪ 取数四件齐）。

    只有取数状态文件、没有数据/产物的未来期次只在没有任何内容时兜底；
    三步全成且已签发 → 顺延下一期。
    """
    root = pathlib.Path(repo_root) if repo_root else REPO_ROOT
    out = _out_root(root, out_root)
    if filled is None:
        try:
            filled = _filled(root)
        except Exception:                                       # noqa: BLE001
            return None
    filled_set = set(filled)
    acq = _acq_periods(out)
    acquired = {p for p in acq if _acquire_state(p, root)[0]}
    content = filled_set | _product_dirs(out) | acquired
    known = content | _dirs(out) | acq
    if not known:
        return None
    period = max(content) if content else max(known)
    f = facts(period, repo_root=root, out_root=out, filled=filled_set, status=status)
    if f.acquire_ok and f.merge_ok and f.generate_ok and status and status(period) == "signed":
        period = next_period(period)
        f = facts(period, repo_root=root, out_root=out, filled=filled_set, status=status)
    return f


def water_rows(matrix_path) -> dict:
    """学科水位：从 matrix.json 的「云大」列取接近度，只读不重算。

    `prox`＝百分数点值（100＝刚好到线）；state＝in / near≥80 / far。
    """
    import json                                                  # noqa: PLC0415

    p = pathlib.Path(matrix_path)
    if not p.exists():
        return {"snapshot": "", "rows": [], "note": "本期没有学科矩阵（matrix.json）"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"snapshot": "", "rows": [], "note": "学科矩阵读不出来"}
    rows = []
    for subject, cells in (data.get("matrix") or {}).items():
        raw = str(((cells or {}).get("云大") or {}).get("v") or "").strip()
        if raw == "Y":
            rows.append({"subject": subject, "prox": 100.0, "state": "in"})
            continue
        if raw.endswith("%"):
            try:
                prox = float(raw[:-1])
            except ValueError:
                continue
            rows.append({"subject": subject, "prox": prox,
                         "state": "near" if prox >= 80 else "far"})
    rows.sort(key=lambda r: (-r["prox"], r["subject"]))
    return {"snapshot": str(data.get("snapshot") or ""), "rows": rows}
