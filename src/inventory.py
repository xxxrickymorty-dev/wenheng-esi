# -*- coding: utf-8 -*-
"""盘点：某期次「必需件」是否齐备（只判**件在不在**，不判**数对不对**）。

四件（GLOSSARY·盘点；顺序照五稿的盘点清单）：

    ① 动态监测表   input/<母本>（该期数据已在母本里）或当期核对副本
                   out/_acquisition/<期次>/监测表.xlsx（已建副本、还没并入）
    ② ESI 原始包   ../数据与复现/ESI数据/<期次>/（目录）或 <期次>.zip
    ③ 顶尖论文清单  out/_acquisition/<期次>/*清单* 或 ../数据与复现/<期次>*清单*.xlsx
    ④ InCites 快照 ../数据与复现/incites/<SNAP_MAP[期次]>（目录）

（2026-10-13 rick 定：input/ 只放母本，每期不再另存表；核对副本落 out/_acquisition/。）

「未发布」语义（rick 2026-10-10 定）：该期不在主台账的有效期次里＝未发布。
未发布时，**随发布才拿得到的两件**（③顶尖论文清单、④InCites 快照）一律报
「未到」，不去翻本机试排预览件；①② 照文件判（它们在本机可能已取到）。
已发布期次照实按文件 / SNAP_MAP 判。

另给「现在能做的完整一期」：参阅期次里**四件齐**的最近一期（供「两条路」文案）。
本模块只读、零副作用；路径可注入（repo_root / ledger_path / filled），测试用 tmp。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, replace

#: 仓库根（wenheng/）；「数据与复现」在它的上一级。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 主台账文件名（唯一事实源；有效期次＝列名六位且该列有数据，口径见 src/period.py）。
LEDGER_NAME = "云大全学科排名、阈值动态检测表.xlsx"

#: 四件的键与馆员话术（界面不露路径）。
LABELS = (
    ("monitor", "动态监测表"),
    ("esi", "ESI 原始包"),
    ("papers", "顶尖论文清单"),
    ("incites", "InCites 快照"),
)

#: 未发布时随发布才到的件（报「未到」，不翻本机预览件）。
_RELEASE_GATED = ("papers", "incites")

_UNRELEASED_NOTE = "未到（随发布）"


@dataclass(frozen=True)
class Piece:
    key: str
    label: str
    state: str            # ok | missing
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    def as_data(self) -> dict:
        return {"key": self.key, "label": self.label, "state": self.state, "note": self.note}


@dataclass(frozen=True)
class Inventory:
    period: str
    released: bool
    pieces: tuple[Piece, ...]
    fallback: str = ""    # 现在能做的完整一期（没有则空）

    @property
    def missing(self) -> tuple[Piece, ...]:
        return tuple(p for p in self.pieces if not p.ok)

    @property
    def n_missing(self) -> int:
        return len(self.missing)

    @property
    def ok(self) -> bool:
        return self.n_missing == 0

    def as_data(self) -> dict:
        return {"period": self.period, "released": bool(self.released),
                "pieces": [p.as_data() for p in self.pieces],
                "n_pieces": len(self.pieces), "n_missing": self.n_missing,
                "fallback": self.fallback}


# ---------------------------------------------------------------- 台账有效期次
_FILLED_CACHE: dict = {}


def _filled_for(ledger_path) -> list[str]:
    """主台账的**有效期次**（升序）。按 (路径, mtime) 缓存——台账是慢变事实。"""
    path = pathlib.Path(ledger_path)
    st = path.stat()
    key = (str(path), st.st_mtime_ns)
    hit = _FILLED_CACHE.get(key)
    if hit is None:
        import parse_ledger                                        # noqa: PLC0415
        import period as period_mod                                # noqa: PLC0415

        data = parse_ledger.load_ledger(path)
        hit = list(period_mod.filled(data["wide"]))
        _FILLED_CACHE.clear()
        _FILLED_CACHE[key] = hit
    return hit


# ---------------------------------------------------------------- 四件判据
def _data_root(repo_root) -> pathlib.Path:
    return pathlib.Path(repo_root).parent / "数据与复现"


def _has_esi(period: str, data_root: pathlib.Path) -> bool:
    root = data_root / "ESI数据"
    return (root / period).is_dir() or (root / f"{period}.zip").is_file()


def _has_papers(period: str, *, repo_root: pathlib.Path, data_root: pathlib.Path) -> bool:
    """顶尖论文清单（③）：按**流水线实际取数口**判，不只认馆员另存的 csv。

    2026-10-11 修：202609 的清单来自 Clarivate 取数落地的
    `数据与复现/<期次>论文清单.xlsx`（college_stats 的 source 可证），
    此前只查 `input/<期次>/顶尖论文清单.csv` → 把已完成的期次误报「缺 1 件」。
    2026-10-13：input/ 只放母本——当期核对区（`out/_acquisition/<期次>/`）也算取数口。
    现在的判据：核对区下有 csv/xlsx 清单，或 `数据与复现/<期次>论文清单.xlsx`。
    """
    acq_dir = repo_root / "out" / "_acquisition" / period
    if acq_dir.is_dir() and (any(acq_dir.glob("*论文清单*.xlsx"))
                             or any(acq_dir.glob("*论文清单*.csv"))):
        return True
    return any(data_root.glob(f"{period}*论文清单*.xlsx"))


def _has_incites(period: str, data_root: pathlib.Path) -> bool:
    from extract_matrix import SNAP_MAP                            # noqa: PLC0415

    snap = SNAP_MAP.get(period)
    return bool(snap) and (data_root / "incites" / snap).is_dir()


def _pieces(period: str, *, repo_root: pathlib.Path, data_root: pathlib.Path,
            released: bool, filled=None) -> tuple[Piece, ...]:
    def piece(key: str, ok: bool, note: str = "") -> Piece:
        label = dict(LABELS)[key]
        return Piece(key=key, label=label, state="ok" if ok else "missing", note=note)

    # ① 动态监测表：该期数据已在母本里（filled），或当期核对副本已建（还没并入）。
    # 副本按 repo_root 相对定位（不依赖取数状态目录的 env 覆盖，测试注入更干净）。
    monitor_ok = (repo_root / "out" / "_acquisition" / period / "监测表.xlsx").is_file() \
        or (bool(filled) and period in filled)
    out = [
        piece("monitor", monitor_ok),
        piece("esi", _has_esi(period, data_root)),
    ]
    if released:
        out.append(piece("papers", _has_papers(period, repo_root=repo_root,
                                               data_root=data_root)))
        out.append(piece("incites", _has_incites(period, data_root)))
    else:
        # 未发布：随发布才到的两件一律「未到」——不去翻本机试排预览件。
        out.append(piece("papers", False, _UNRELEASED_NOTE))
        out.append(piece("incites", False, _UNRELEASED_NOTE))
    return tuple(out)


def _complete(period: str, *, repo_root: pathlib.Path, data_root: pathlib.Path,
              filled=None) -> bool:
    """该期四件齐（已发布口径）。"""
    return all(p.ok for p in _pieces(period, repo_root=repo_root,
                                     data_root=data_root, released=True,
                                     filled=filled))


def _latest_complete(exclude: str, filled: list[str], *, repo_root: pathlib.Path,
                     data_root: pathlib.Path) -> str:
    for p in sorted(set(filled), reverse=True):
        if p != exclude and _complete(p, repo_root=repo_root, data_root=data_root,
                                      filled=filled):
            return p
    return ""


# ---------------------------------------------------------------- 入口
def scan(period: str, *, repo_root=None, ledger_path=None,
         filled=None, released=None) -> Inventory | None:
    """盘点一期。台账读不动（且未显式给 released/filled）→ 返回 None（不编）。"""
    root = pathlib.Path(repo_root) if repo_root else REPO_ROOT
    data_root = _data_root(root)
    if released is None:
        if ledger_path:
            ledger = pathlib.Path(ledger_path)
        else:
            # 运行时母本优先（input/，部署机也有）；开发机没有就回落馆员原件。
            import ledger as ledger_mod                            # noqa: PLC0415

            runtime = ledger_mod.runtime_path(root)
            ledger = runtime if runtime.exists() else data_root / LEDGER_NAME
        try:
            filled = _filled_for(ledger) if filled is None else filled
        except Exception:                                          # noqa: BLE001
            return None
        released = period in filled
    inv = Inventory(period=period, released=bool(released),
                    pieces=_pieces(period, repo_root=root, data_root=data_root,
                                   released=bool(released), filled=filled))
    if inv.ok:
        return inv
    fallback = ""
    if filled:
        fallback = _latest_complete(period, list(filled), repo_root=root,
                                    data_root=data_root)
    return replace(inv, fallback=fallback)
