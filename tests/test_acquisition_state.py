# -*- coding: utf-8 -*-
"""取数状态（src/acquisition_state.py）：逐文件核验 + 状态组装。

合成一套最小两路下载包跑全量分组；另用真实 202609 包做一次带护栏的回归。
2026-10-19（ADR-0010）补：状态文件并发读锁下的写/读重试、pid 判活。
"""
import importlib
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import acquisition_state as A  # noqa: E402

from _guard_registry import skip_unless, tmp_near_repo  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


def _xlsx(path: pathlib.Path, rows: list, sheet: str = "Sheet0") -> None:
    wb = openpyxl.Workbook()
    ws = wb.worksheets[0]
    ws.title = sheet
    for r in rows:
        ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _subject_rows(tag: str, name: str, n: int = 12) -> list:
    rows = [[f"Indicators Results List: Institutions   Filter Results By: ResearchFields   "
             f"Filter Value(s): {name.upper()}   Show: Top"]]
    rows.append(["RowSeq", "Institutions", "Web of Science Documents", "Cites"])
    rows.extend([[i, f"Univ {i}", 100 + i, 200 + i] for i in range(n)])
    return rows


def _build_esi(root: pathlib.Path, period: str) -> None:
    d = root / period
    _xlsx(d / "Institutions.xlsx", [["Institutions", "Cites"]] + [[f"U{i}", i] for i in range(150)])
    for s in A.SUBJECTS:
        _xlsx(d / f"{s.replace('/', ' ')}.xlsx", _subject_rows("subjects", s))
    for f in ("全球学科.xlsx", "中国学科.xlsx", "云大学科.xlsx"):
        _xlsx(d / f, [["Research Fields", "Cites"]] + [[f"F{i}", i] for i in range(25)])
    for suffix in ("top", "highly cited", "hot papers"):
        _xlsx(d / f"7{suffix}.xlsx", [["Documents Result List: Institutions"]] +
              [["Accession Number", "Article Name"]] + [["WOS:x", "文"]] * 3)
        (d / f"7{suffix}.csv").write_text(
            "Documents Result List:  Institutions - 'YUNNAN UNIVERSITY' Show - Top Papers\n"
            "Accession Number,DOI,Article Name\n\"WOS:x\",\"10.1\",\"文\"\n", encoding="utf-8-sig")
    for f in ("ThresholdESI.xlsx", "ThresholdHighlyCited.xlsx", "ThresholdHot.xlsx"):
        _xlsx(d / f, [["Threshold", "Cites"]] + [[f"T{i}", i] for i in range(25)])
    for f in ("BaselineCitationRates.xlsx", "BaselinePercentiles.xlsx", "BaselineFieldRankings.xlsx"):
        _xlsx(d / f, [["Baseline", "Value"]] + [[f"B{i}", i] for i in range(25)])


def _build_incites(root: pathlib.Path, snap: str) -> None:
    d = root / snap
    for s in A.SUBJECTS:
        name = "Social Sciences, general" if s == "Social Sciences, General" else s
        _xlsx(d / f"{name.replace('/', ' ')}.xlsx",
              [["名称", "Web of Science 论文数", "被引频次"]] + [[f"U{i}", i, i * 2] for i in range(12)])
    _xlsx(d / "全球 研究领域.xlsx", [["名称", "Web of Science 论文数"]] + [["F", 1]] * 25)
    _xlsx(d / "中国研究领域.xlsx", [["名称", "Web of Science 论文数"]] + [["F", 1]] * 25)
    _xlsx(d / "云南大学研究领域.xlsx", [["名称", "Web of Science 论文数"]] + [["F", 1]] * 25)
    _xlsx(d / "全球机构排名.xlsx", [["名称", "Web of Science 论文数"]] +
          [[f"U{i}", i] for i in range(1001)])


@pytest.fixture()
def fake_roots(tmp_path, monkeypatch):
    esi = tmp_path / "ESI数据"
    inc = tmp_path / "incites"
    snap = "数据覆盖2016-2026.06.30"
    _build_esi(esi, "202609")
    _build_incites(inc, snap)
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    return esi, inc, snap


def test_scan_all_groups_green(fake_roots):
    esi, inc, snap = fake_roots
    state = A.scan("202609", esi_root=esi, snapshot=snap)
    assert state["totals"] == {"groups": 9, "expected": 64, "verified": 64,
                               "downloaded": 64, "failed": 0}
    assert all(g["state"] == "done" for g in state["groups"])
    assert state["data_period"]["incites"] == "2026-06-30"


def test_scan_marks_bad_file_and_fails_group(fake_roots):
    esi, inc, snap = fake_roots
    bad = esi / "202609" / "Chemistry.xlsx"
    bad.write_bytes(b"this is not xlsx")
    state = A.scan("202609", esi_root=esi, snapshot=snap)
    subj = next(g for g in state["groups"] if g["id"] == "esi-subjects")
    chem = next(f for f in subj["files"] if f["name"] == "Chemistry.xlsx")
    assert chem["state"] == "bad" and "打不开" in chem["note"]
    assert subj["state"] == "fail"
    assert state["totals"]["verified"] == 63 and state["totals"]["failed"] == 1


def test_scan_pending_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    state = A.scan("202609", esi_root=tmp_path / "none-esi", snapshot="")
    assert state["totals"]["verified"] == 0
    assert all(g["state"] == "pending" for g in state["groups"])


def test_unmapped_period_does_not_borrow_latest_snapshot(tmp_path, monkeypatch):
    """scan 收紧（2026-10-16）：未登记 SNAP_MAP 的期次不得借用「最新一个」InCites 快照。

    旧行为会把最新快照里的 22 学科文件算成新期次的（实测未取数的 202611 凭空 26/64）。
    """
    inc = tmp_path / "incites"
    _build_incites(inc, "数据覆盖2016-2026.06.30")            # 最新快照里有一整套文件
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    monkeypatch.setattr(A, "INCITES_ROOT_DEFAULT", inc)
    monkeypatch.setattr(A, "_snap_map", lambda: {"202609": "数据覆盖2016-2026.06.30"})
    state = A.scan("202611", esi_root=tmp_path / "none-esi")
    assert state["snapshot"] == "" and state["snapshot_registered"] is False
    assert state["data_period"]["incites"] == ""
    inc_g = next(g for g in state["groups"] if g["id"] == "incites-subjects")
    assert inc_g["state"] == "pending" and inc_g["verified"] == 0
    assert state["totals"]["verified"] == 0                   # 一个文件都不该算进来


def test_resolve_snapshot_explicit_and_mapped(monkeypatch):
    monkeypatch.setattr(A, "_snap_map", lambda: {"202609": "数据覆盖2016-2026.06.30"})
    assert A.resolve_snapshot("202609", A.INCITES_ROOT_DEFAULT) == "数据覆盖2016-2026.06.30"
    assert A.resolve_snapshot("202605", A.INCITES_ROOT_DEFAULT, "显式快照") == "显式快照"
    assert A.resolve_snapshot("202611", A.INCITES_ROOT_DEFAULT) == ""   # 未登记 → 空


def test_write_load_roundtrip_and_preserve(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    A.write_state("202609", {"totals": {"verified": 1}, "preflight": {"browser": "ok"}})
    got = A.load_state("202609")
    assert got["period"] == "202609" and got["preflight"]["browser"] == "ok"
    assert got["updated_at"]
    # 再扫一次要保留 preflight / copy（不重建时抹掉人工/流程写过的字段）
    state = A.scan("202609", esi_root=tmp_path / "none", snapshot="")
    A.write_state("202609", state)
    assert A.load_state("202609")["preflight"]["browser"] == "ok"


def test_snapshot_resolution_and_date():
    assert A._snap_date("数据覆盖2016-2026.06.30") == "2026-06-30"
    assert A._snap_date("") == ""
    assert A._period_esi_label("202609") == "2026 年 9 月"


def test_scan_real_202609():
    """真实包回归（缺件才登记跳过：探针说资源在、却跳过 = 会话收尾判失败）。"""
    period = "202609"
    esi = A.ESI_ROOT_DEFAULT / period
    if not esi.is_dir():
        skip_unless(f"真实 ESI 包不存在：{esi}", lambda: esi.is_dir())
    state = A.scan(period)
    assert state["totals"]["verified"] >= 60, state["totals"]
    assert state["totals"]["failed"] == 0


# ------------------------------------------------------------------ 并发读锁与活性（ADR-0010）
def test_write_state_撞并发读锁会重试成功(tmp_path, monkeypatch):
    """Windows 上 os.replace 撞并发读句柄会 PermissionError——重试后要成功。

    2026-10-17 取 202609 就是死在这一步（整个取数进程暴死）；实测一边读一边写
    200 次 139 次失败。
    """
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    real_replace = pathlib.Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "拒绝访问。")
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", flaky)
    A.write_state("202609", {"x": 1})
    assert calls["n"] == 3, "前两次失败后第三次应成功"
    saved = A.load_state("202609")
    assert saved is not None and saved["x"] == 1


def test_write_state_持续被占则如实抛出(tmp_path, monkeypatch):
    """重试耗尽仍被占：如实抛 PermissionError（调用方兜底落 failed），不静默丢状态。"""
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)

    def always_blocked(self, target):
        raise PermissionError(13, "拒绝访问。")

    monkeypatch.setattr(pathlib.Path, "replace", always_blocked)
    with pytest.raises(PermissionError):
        A.write_state("202609", {"x": 1})


def test_load_state_替换空窗里的坏读会重试(tmp_path, monkeypatch):
    """写方原子替换的空窗：第一次读可能半截/读不动——load_state 重试 ≤3 次。"""
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    A.write_state("202609", {"x": 1})
    real_read = pathlib.Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **kw):
        if self.name == "202609.json" and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("sharing violation")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pathlib.Path, "read_text", flaky)
    got = A.load_state("202609")
    assert got is not None and got["x"] == 1 and calls["n"] == 1


# ------------------------------------------------------------------ 核对副本路径（2026-10-22）
def test_默认核对副本路径落仓库相对写法(tmp_path, monkeypatch):
    """常态（`STATE_DIR` 就是 `REPO/out/_acquisition`）：落 JSON 的默认值是**仓库相对**——
    不含盘符与用户名，换台机器也成立（状态文件在部署包白名单里）。"""
    monkeypatch.setattr(A, "STATE_DIR", REPO / "out" / "_acquisition")
    state = A.scan("209912", esi_root=tmp_path / "none", snapshot="")
    path = state["copy"]["path"]
    assert state["copy"]["state"] == "none"
    assert path == "out/_acquisition/209912/监测表.xlsx"
    assert path.startswith("out/_acquisition/")
    assert ":" not in path and not path.startswith("/")        # 没有盘符
    assert pathlib.Path.home().name not in path                # 不带用户名
    assert not pathlib.PurePath(path).is_absolute()


def test_状态目录指到仓库外时默认值退回绝对路径(tmp_path, monkeypatch):
    """`WENHENG_ACQ_STATE_DIR` 指到仓库外（临时演练/集成测试）：判据「不在 `REPO` 之下」，
    只能给绝对路径；读写仍走真实路径，照常可用。"""
    if tmp_near_repo(REPO):
        skip_unless("系统 Temp 不可写，pytest 临时根落在仓库内/隔壁——「状态目录指到仓库外」这个前提测不了",
                    lambda: not tmp_near_repo(REPO))
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    state = A.scan("202611", esi_root=tmp_path / "none", snapshot="")
    path = pathlib.Path(state["copy"]["path"])
    assert path.is_absolute() and path == A.copy_path("202611")
    assert not A.repo_display_path(A.copy_path("202611")).startswith("out/")
    A.write_state("202611", {"copy": {"state": "review", "path": state["copy"]["path"]}})
    assert A.load_state("202611")["copy"]["path"] == path.as_posix()
    assert (tmp_path / "out" / "_acquisition" / "202611.json").is_file()


def test_环境变量指到仓库外时默认值也是绝对路径(tmp_path, monkeypatch):
    """同一条判据走真实入口（环境变量在 import 时读）：这里重载模块模拟换进程。"""
    if tmp_near_repo(REPO):
        skip_unless("系统 Temp 不可写，pytest 临时根落在仓库内/隔壁——「环境变量指到仓库外」这个前提测不了",
                    lambda: not tmp_near_repo(REPO))
    monkeypatch.setenv("WENHENG_ACQ_STATE_DIR", str(tmp_path / "acq"))
    importlib.reload(A)
    try:
        assert A.STATE_DIR == tmp_path / "acq"
        assert A.repo_display_path(A.copy_path("202611")) == A.copy_path("202611").as_posix()
        assert pathlib.Path(A.repo_display_path(A.copy_path("202611"))).is_absolute()
    finally:
        monkeypatch.delenv("WENHENG_ACQ_STATE_DIR")
        importlib.reload(A)
    assert A.STATE_DIR == REPO / "out" / "_acquisition"
    assert A.repo_display_path(A.copy_path("202611")) == "out/_acquisition/202611/监测表.xlsx"


def test_旧状态里的旧副本路径原样读出不炸(tmp_path, monkeypatch):
    """迁移前落的状态文件里可能还存着 `input/<期次>/监测表.xlsx`：读进来照原样，不猜、不改写。"""
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "out" / "_acquisition")
    A.write_state("202611", {"copy": {"state": "review", "path": "input/202611/监测表.xlsx"}})
    state = A.scan("202611", esi_root=tmp_path / "none", snapshot="")
    assert state["copy"] == {"state": "review", "path": "input/202611/监测表.xlsx"}


def test_pid_alive_本进程真_不存在与坏值假():
    assert A.pid_alive(os.getpid()) is True
    assert A.pid_alive(999999999) is False          # 不存在的 pid
    assert A.pid_alive(0) is False
    assert A.pid_alive(-1) is False
    assert A.pid_alive(None) is False
    assert A.pid_alive("不是数字") is False
