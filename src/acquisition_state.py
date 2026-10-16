# -*- coding: utf-8 -*-
"""取数状态（`out/_acquisition/<期次>.json`）的**唯一写入方** + 下载包逐文件核验。

- 写方：取数流程（`tools/acquire.py`；人触发）。读方：`server/acquisition.py`（取数台只读展示）。
- 状态形状见 `server/acquisition.py` 文档串（与前端 `AcquisitionState` 对齐，字段只增不改）。
- 核验口径：每个文件打开一遍，查「能读 + 表头指纹 + 行数下限」；下载了但核验不过 → `bad`，
  没取到 → `pending`；**只有 ok 才计入进度**（ADR-0004「逐文件核验、通过才计入」）。

分组与文件清单照《ESI数据下载流程.docx》两路共 9 组 64 份（与 `clarivate_*_fetch.py` 对齐）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
#: 状态目录；环境变量可覆盖（集成测试/临时演练不碰真状态）
STATE_DIR = pathlib.Path(os.environ["WENHENG_ACQ_STATE_DIR"]) \
    if os.environ.get("WENHENG_ACQ_STATE_DIR") else REPO / "out" / "_acquisition"
ESI_ROOT_DEFAULT = REPO.parent / "数据与复现" / "ESI数据"
INCITES_ROOT_DEFAULT = REPO.parent / "数据与复现" / "incites"

PERIOD_RE = re.compile(r"^\d{6}$")

if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

SUBJECTS = [
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
    "Computer Science", "Economics & Business", "Engineering", "Environment/Ecology",
    "Geosciences", "Immunology", "Materials Science", "Mathematics", "Microbiology",
    "Molecular Biology & Genetics", "Multidisciplinary", "Neuroscience & Behavior",
    "Pharmacology & Toxicology", "Physics", "Plant & Animal Science",
    "Psychiatry/Psychology", "Social Sciences, General", "Space Science",
]


# ------------------------------------------------------------------ 期次↔快照
def _snap_map() -> dict:
    try:
        from extract_matrix import SNAP_MAP                          # noqa: PLC0415
        return dict(SNAP_MAP)
    except Exception:                                                # noqa: BLE001
        return {}


def resolve_snapshot(period: str, incites_root: pathlib.Path, explicit: str | None = None) -> str:
    """期次 → InCites 快照目录名：显式指定 > SNAP_MAP 登记 > **空串**。

    2026-10-16 收紧：未登记的期次**不再退回「最新一个」快照**——那会把别期下载的文件
    算成本期的（实测只点一次「重新检查」就让未取数的 202611 凭空 26/64）。未登记一律空串，
    由调用方按「空着 + 标黄」处理。`incites_root` 仅为保持调用签名，本函数不再读它。
    """
    if explicit is not None:
        return explicit
    return _snap_map().get(period) or ""


def _snap_date(snapshot: str) -> str:
    """`数据覆盖2016-2026.06.30` → `2026-06-30`（如实取快照目录里的 WoS 截止日）。"""
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})$", snapshot or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _period_esi_label(period: str) -> str:
    return f"{period[:4]} 年 {int(period[4:6])} 月" if PERIOD_RE.match(period or "") else ""


# ------------------------------------------------------------------ 逐文件核验
def _check_xlsx(path: pathlib.Path, *, tags: tuple = (), min_rows: int = 1,
                read_only: bool = False) -> str | None:
    """→ None 表示通过；否则返回人话原因。"""
    import openpyxl                                                # noqa: PLC0415
    try:
        # ESI 新导出的 dimension 是坏的（A1）——必须普通模式才读得到全部；InCites 用只读模式省内存。
        wb = openpyxl.load_workbook(path, read_only=read_only, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            rows = []
            for i, r in enumerate(ws.iter_rows(values_only=True)):
                rows.append(r)
                if i >= 8:
                    break
            n_rows = ws.max_row
        finally:
            wb.close()
    except Exception as e:                                           # noqa: BLE001
        return f"打不开/读不动（{type(e).__name__}）"
    text = " ".join(str(c) for r in rows for c in r if c is not None)[:4000]
    for tag in tags:
        if tag.lower() not in text.lower():
            return f"表头指纹对不上（缺「{tag}」）"
    if n_rows < min_rows:
        return f"行数不足（{n_rows} < {min_rows}）"
    return None


def _check_csv(path: pathlib.Path, *, tags: tuple = (), min_lines: int = 3) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except Exception as e:                                           # noqa: BLE001
        return f"读不动（{type(e).__name__}）"
    if len(lines) < min_lines:
        return f"行数不足（{len(lines)}）"
    head = lines[0] + "\n" + (lines[1] if len(lines) > 1 else "")
    for tag in tags:
        if tag.lower() not in head.lower():
            return f"表头指纹对不上（缺「{tag}」）"
    return None


def _file_entry(path: pathlib.Path, label: str, checker, **kw) -> dict:
    if not path.exists():
        return {"name": path.name, "label": label, "state": "pending"}
    why = checker(path, **kw)
    entry = {"name": path.name, "label": label, "state": "ok" if why is None else "bad"}
    if why:
        entry["note"] = why
    return entry


def _resolve_candidates(d: pathlib.Path, names: tuple[str, ...]) -> pathlib.Path | None:
    """按候选名找文件（历史归档命名有出入：带尾空格 / WOS 前缀等），先精确后通配。"""
    for n in names:
        p = d / n
        if p.exists():
            return p
    for n in names:
        if any(ch in n for ch in "*?"):
            hit = sorted(d.glob(n))
            if hit:
                return hit[0]
    return None


def _candidates_entry(snap_dir: pathlib.Path | None, label: str, cands: tuple[str, ...],
                      checker, **kw) -> dict:
    """快照里按候选名找文件；找不到 → pending（名字如实写成第一候选）。"""
    if snap_dir is None:
        return {"name": cands[0], "label": label, "state": "pending"}
    p = _resolve_candidates(snap_dir, cands)
    if p is None:
        return {"name": cands[0], "label": label, "state": "pending"}
    return _file_entry(p, label, checker, **kw)


def _esi_subject_entry(esi_dir: pathlib.Path, subject: str) -> dict:
    fname = subject.replace("/", " ") + ".xlsx"
    path = esi_dir / fname
    if not path.exists():
        return {"name": fname, "label": subject, "state": "pending"}
    why = _check_xlsx(path, tags=("Indicators Results List", "Institutions", subject.upper()),
                      min_rows=10, read_only=False)
    entry = {"name": fname, "label": subject, "state": "ok" if why is None else "bad"}
    if why:
        entry["note"] = why
    return entry


def scan_groups(period: str, esi_root: pathlib.Path, snapshot: str) -> list[dict]:
    """按 9 组扫描两路下载包，逐文件核验。"""
    def _incites_name(s: str) -> str:
        # InCites 视图里这个名字是小写 general（与历史归档一致）
        return "Social Sciences, general" if s == "Social Sciences, General" else s

    esi = pathlib.Path(esi_root) / period
    inc = pathlib.Path(INCITES_ROOT_DEFAULT) / snapshot if snapshot else None
    subj_inc = [
        _file_entry((inc or pathlib.Path(".")) / (_incites_name(s).replace("/", " ") + ".xlsx"), s,
                    _check_xlsx, tags=("Web of Science 论文数",), min_rows=10, read_only=True)
        if inc else {"name": _incites_name(s).replace("/", " ") + ".xlsx", "label": s,
                     "state": "pending"}
        for s in SUBJECTS
    ]
    return [
        {"id": "esi-institutions", "source": "esi", "index": 1, "title": "全球机构总表",
         "files": [_file_entry(esi / "Institutions.xlsx", "全球机构总表", _check_xlsx,
                               tags=("Institutions",), min_rows=100, read_only=False)]},
        {"id": "esi-subjects", "source": "esi", "index": 2, "title": "22 学科机构表",
         "files": [_esi_subject_entry(esi, s) for s in SUBJECTS]},
        {"id": "esi-fields", "source": "esi", "index": 3, "title": "全球、中国、云大学科汇总",
         "files": [_file_entry(esi / f, label, _check_xlsx, tags=("Research Fields",),
                               min_rows=20, read_only=False)
                   for f, label in (("全球学科.xlsx", "全球学科汇总"),
                                    ("中国学科.xlsx", "中国学科汇总"),
                                    ("云大学科.xlsx", "云南大学学科汇总"))]},
        {"id": "esi-papers", "source": "esi", "index": 4, "title": "云大论文清单",
         "files": _top_papers_entries(esi)},
        {"id": "esi-thresholds", "source": "esi", "index": 5, "title": "三张阈值表",
         "files": [_file_entry(esi / f, label, _check_xlsx, tags=("Threshold",),
                               min_rows=20, read_only=False)
                   for f, label in (("ThresholdESI.xlsx", "ESI 阈值"),
                                    ("ThresholdHighlyCited.xlsx", "高被引论文阈值"),
                                    ("ThresholdHot.xlsx", "热点论文阈值"))]},
        {"id": "esi-baselines", "source": "esi", "index": 6, "title": "三张基线表",
         "files": [_file_entry(esi / f, label, _check_xlsx, min_rows=20, read_only=False)
                   for f, label in (("BaselineCitationRates.xlsx", "引用率基线"),
                                    ("BaselinePercentiles.xlsx", "百分位基线"),
                                    ("BaselineFieldRankings.xlsx", "学科排名基线"))]},
        {"id": "incites-subjects", "source": "incites", "index": 1, "title": "22 学科全球机构排名",
         "files": subj_inc},
        {"id": "incites-fields", "source": "incites", "index": 2, "title": "全球、中国、云大研究领域汇总",
         "files": [_candidates_entry(inc, label, cands, _check_xlsx,
                                     tags=("Web of Science 论文数",), min_rows=20, read_only=True)
                   for label, cands in (
                       ("全球研究领域", ("全球 研究领域.xlsx", "全球 研究领域 .xlsx", "全球研究领域.xlsx")),
                       ("中国研究领域", ("中国研究领域.xlsx",)),
                       ("云南大学研究领域", ("云南大学研究领域.xlsx", "云大 研究领域.xlsx",
                                             "云大研究领域.xlsx")))]},
        {"id": "incites-institutions", "source": "incites", "index": 3, "title": "全球机构排名表",
         # 历史快照里这份「补充包」有旧命名（WOS*.xlsx，WoS 论文明细导出）——两种都认，如实显示实际文件名
         "files": [_candidates_entry(inc, "全球机构排名", ("全球机构排名.xlsx", "WOS论文*.xlsx", "WOS*.xlsx"),
                                     _check_xlsx, min_rows=1000, read_only=True)]},
    ]


def _top_papers_entries(esi_dir: pathlib.Path) -> list[dict]:
    """论文清单：三对「数字在前」的 xlsx+同形 CSV（篇数随当期变，不写死）。"""
    pairs = [("top", "Top 论文"), ("highly cited", "高被引论文"), ("hot papers", "热点论文")]
    out: list[dict] = []
    for suffix, label in pairs:
        xlsx = sorted(esi_dir.glob(f"*{suffix}.xlsx"))
        csv = sorted(esi_dir.glob(f"*{suffix}.csv"))
        for f in xlsx:
            out.append(_file_entry(f, f"{label} · Excel", _check_xlsx,
                                   tags=("Documents Result List",), min_rows=3, read_only=False))
        for f in csv:
            out.append(_file_entry(f, f"{label} · CSV", _check_csv,
                                   tags=("Documents Result List", "Accession Number"), min_lines=3))
        if not xlsx and not csv:
            out.append({"name": f"<篇数>{suffix}.xlsx", "label": f"{label} · Excel",
                        "state": "pending"})
            out.append({"name": f"<篇数>{suffix}.csv", "label": f"{label} · CSV",
                        "state": "pending"})
    return out


def _group_state(files: list[dict]) -> tuple[str, int, int, int]:
    """→ (组状态, ok 数, 总份数, bad 数)。只有 ok 计入；下载了但核验不过 = bad。"""
    ok = sum(1 for f in files if f["state"] == "ok")
    bad = sum(1 for f in files if f["state"] == "bad")
    total = len(files)
    if bad:
        state = "fail"
    elif ok == total:
        state = "done"
    elif ok:
        state = "live"                    # 部分到齐：还在途
    else:
        state = "pending"
    # 论文清单的文件名随篇数变，出现几个算几个（不按固定份数判缺）
    return state, ok, total, bad


# ------------------------------------------------------------------ 状态读写
def state_path(period: str) -> pathlib.Path:
    return STATE_DIR / f"{period}.json"


#: 当期取数核对副本的文件名（ADR-0004 的「审的＝写的」载体；2026-10-13 起落
#: `out/_acquisition/<期次>/监测表.xlsx`，不再进 `input/`——input/ 只放母本）。
COPY_NAME = "监测表.xlsx"


def copy_path(period: str) -> pathlib.Path:
    """本期核对副本路径：`out/_acquisition/<期次>/监测表.xlsx`。"""
    return STATE_DIR / period / COPY_NAME



def load_state(period: str) -> dict | None:
    """读一期取数状态；没有/读不动 → None（界面显示「还没开始」，不编数据）。"""
    if not PERIOD_RE.match(period or ""):
        return None
    try:
        data = json.loads((STATE_DIR / f"{period}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["period"] = period
    return data


def write_state(period: str, state: dict) -> pathlib.Path:
    """原子写（tmp → replace）；补 period / updated_at。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["period"] = period
    state["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    tmp = STATE_DIR / f".{period}.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_DIR / f"{period}.json")
    return STATE_DIR / f"{period}.json"


def periods() -> list[str]:
    if not STATE_DIR.exists():
        return []
    return sorted((p.stem for p in STATE_DIR.glob("*.json") if PERIOD_RE.match(p.stem)),
                  reverse=True)


# ------------------------------------------------------------------ 组装状态
def scan(period: str, *, esi_root: pathlib.Path | str | None = None,
         snapshot: str | None = None, preserve: bool = True) -> dict:
    """按两路下载包重建状态（保留 preflight / capabilities / copy / op 等既有字段）。

    期次未登记在 `SNAP_MAP`（且没显式给快照）时，**InCites 一路留空**、状态标
    `snapshot_registered=False`——不再借用「最新一个」快照，免得把别期文件算成本期的。
    """
    esi_root = pathlib.Path(esi_root) if esi_root else ESI_ROOT_DEFAULT
    snap = resolve_snapshot(period, INCITES_ROOT_DEFAULT, snapshot)
    snap_registered = snapshot is not None or bool(_snap_map().get(period))
    groups = scan_groups(period, esi_root, snap)
    verified = downloaded = failed = 0
    for g in groups:
        state, ok, total, bad = _group_state(g["files"])
        g["state"] = state
        g["verified"] = ok
        g["downloaded"] = sum(1 for f in g["files"] if f["state"] in ("ok", "bad"))
        verified += ok
        downloaded += g["downloaded"]
        failed += bad
    old = load_state(period) if preserve else None
    state = dict(old or {})
    # 历史期次（X3 之前手工并表的）：报告已出 = 数据确实已进台账，如实标注「视同已并入」
    copy_state = state.get("copy") or {"state": "none", "path": f"input/{period}/监测表.xlsx"}
    if (copy_state.get("state") in (None, "none")
            and (REPO / "out" / period / "red_slots.json").exists()):
        copy_state = {"state": "merged", "path": copy_state.get("path",
                                                               f"input/{period}/监测表.xlsx"),
                      "note": "历史期次：报告已出，视同已并入"}
    state.update({
        "data_period": {"esi": _period_esi_label(period), "incites": _snap_date(snap)},
        "snapshot": snap,
        "snapshot_registered": snap_registered,
        "groups": groups,
        "totals": {"groups": len(groups), "expected": sum(len(g["files"]) for g in groups),
                   "verified": verified, "downloaded": downloaded, "failed": failed},
        "preflight": state.get("preflight") or {"browser": "waiting", "esi": "waiting",
                                                "incites": "waiting"},
        "capabilities": state.get("capabilities") or {"start": True, "retry": True, "merge": True},
        "copy": copy_state,
    })
    return state
