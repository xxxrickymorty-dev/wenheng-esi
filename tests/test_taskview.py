# -*- coding: utf-8 -*-
"""票 06 · 本期任务视图（`src/taskview.py`）：第一屏三步条的状态从**既有产物**判。

三步（UX.md §七）：①取数 → ②核对并并入 → ③一键生成——
- ① 四件文件在（按文件判，不受「未并入」影响：取数本来就先于人工作出）；
- ② 该期在主台账有效期次里（并入的凭证）；
- ③ `out/<期次>/red_slots.json` 在（出过稿的凭证）。
本期＝最新六位期次目录（台账 ∪ input ∪ out）；三步全成**且已签发** → 顺延下一期。

全部注入（tmp + filled + status 替身）：不读真台账、不碰真 out。只读、零副作用。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import taskview                                                 # noqa: E402


def _roots(tmp_path):
    """造一个最小仓库：wenheng/（input、out）+ 同级 数据与复现/。"""
    root = tmp_path / "wenheng"
    data_root = tmp_path / "数据与复现"
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "out").mkdir(parents=True, exist_ok=True)
    (data_root / "ESI数据").mkdir(parents=True, exist_ok=True)
    (data_root / "incites").mkdir(parents=True, exist_ok=True)
    return root, data_root


def _give_all_pieces(root, data_root, period, *, snap="数据覆盖2016-2026.06.30"):
    """四件按文件齐位（不受 released 影响）；2026-10-13 起核对副本落 out/_acquisition/。"""
    d = root / "out" / "_acquisition" / period
    d.mkdir(parents=True, exist_ok=True)
    (d / "监测表.xlsx").write_text("x", encoding="utf-8")
    (d / "顶尖论文清单.csv").write_text("x", encoding="utf-8")
    (data_root / "ESI数据" / period).mkdir(parents=True, exist_ok=True)
    (data_root / "incites" / snap).mkdir(parents=True, exist_ok=True)


def _gen(root, period):
    (root / "out" / period).mkdir(parents=True, exist_ok=True)
    (root / "out" / period / "red_slots.json").write_text("[]", encoding="utf-8")


# ============================================================ 1. 本期选择与顺延
def test_啥都没有_返回None(tmp_path):
    root, _ = _roots(tmp_path)
    assert taskview.scan(repo_root=root, filled=[]) is None


def test_三步全成且已签发_顺延下一期(tmp_path):
    root, data_root = _roots(tmp_path)
    _give_all_pieces(root, data_root, "202609")
    _gen(root, "202609")
    out = taskview.scan(repo_root=root, filled=["202609"],
                        status=lambda p: "signed" if p == "202609" else "unsigned")
    assert out["period"] == "202611", "本期做完（含签发）要看下一期"
    assert [s["done"] for s in out["steps"]] == [False, False, False]
    assert out["stuck"] == "acquire"
    assert out["prev"] == {"period": "202609", "status": "signed"}


def test_年内顺延与跨年顺延(tmp_path, monkeypatch):
    root, data_root = _roots(tmp_path)
    import extract_matrix
    monkeypatch.setattr(extract_matrix, "SNAP_MAP",
                        {**extract_matrix.SNAP_MAP, "202611": "数据覆盖2016-2026.08.31"})
    _give_all_pieces(root, data_root, "202611", snap="数据覆盖2016-2026.08.31")
    _gen(root, "202611")
    out = taskview.scan(repo_root=root,
                        filled=["202611"], status=lambda p: "signed")
    assert out["period"] == "202701", "11 月下一期是次年 1 月"


def test_全成未签发_卡在签单_不顺延(tmp_path):
    root, data_root = _roots(tmp_path)
    _give_all_pieces(root, data_root, "202609")
    _gen(root, "202609")
    out = taskview.scan(repo_root=root,
                        filled=["202607", "202609"], status=lambda p: "stale" if p == "202609" else "signed")
    assert out["period"] == "202609", "没签发就不算做完：本期还停在它"
    assert [s["done"] for s in out["steps"]] == [True, True, True]
    assert out["stuck"] == "sign"
    assert out["prev"] == {"period": "202607", "status": "signed"}


# ============================================================ 2. 卡在哪一步
def test_新期未取数_卡在取数_数据未到(tmp_path):
    root, data_root = _roots(tmp_path)
    (root / "out" / "_acquisition" / "202611").mkdir(parents=True)   # 取数在途：还没取到
    out = taskview.scan(repo_root=root,
                        filled=["202609"], status=lambda p: "signed")
    assert out["period"] == "202611"
    assert out["stuck"] == "acquire"
    assert out["released"] is False and out["n_missing"] == 4
    assert [s["done"] for s in out["steps"]] == [False, False, False]


def test_四件齐未并入_卡在核对_且不受未发布影响(tmp_path):
    """🔴 取数先于人工作出：四件文件在就是取数完成（不被「不在台账」判成没到）。"""
    root, data_root = _roots(tmp_path)
    _give_all_pieces(root, data_root, "202609")
    out = taskview.scan(repo_root=root,
                        filled=["202607"], status=lambda p: "signed")
    assert out["period"] == "202609"
    assert out["stuck"] == "merge"
    assert [s["done"] for s in out["steps"]] == [True, False, False]


def test_已并入未出稿_卡在一键生成(tmp_path):
    root, data_root = _roots(tmp_path)
    _give_all_pieces(root, data_root, "202609")
    out = taskview.scan(repo_root=root,
                        filled=["202607", "202609"], status=lambda p: "unsigned")
    assert out["stuck"] == "generate"
    assert [s["done"] for s in out["steps"]] == [True, True, False]


def test_取数缺件_卡在取数_给出缺件数(tmp_path):
    root, data_root = _roots(tmp_path)
    _give_all_pieces(root, data_root, "202609")
    (root / "out" / "_acquisition" / "202609" / "顶尖论文清单.csv").unlink()
    out = taskview.scan(repo_root=root,
                        filled=["202609"], status=lambda p: "unsigned")
    assert out["stuck"] == "acquire"
    assert out["n_missing"] == 1


# ============================================================ 3. 只读
def test_扫描不改任何文件(tmp_path):
    root, data_root = _roots(tmp_path)
    _give_all_pieces(root, data_root, "202609")
    _gen(root, "202609")
    before = sorted((p.name, p.stat().st_mtime_ns)
                    for p in (root / "out" / "202609").iterdir())
    taskview.scan(repo_root=root, filled=["202609"],
                  status=lambda p: "signed")
    after = sorted((p.name, p.stat().st_mtime_ns)
                   for p in (root / "out" / "202609").iterdir())
    assert after == before


# ============================================================ 4. 已知期次（票 10）
def test_已知期次_降序并集(tmp_path):
    root, _ = _roots(tmp_path)
    (root / "out" / "202607").mkdir()
    (root / "out" / "202607" / "red_slots.json").write_text("[]", encoding="utf-8")
    (root / "out" / "_acquisition" / "202611").mkdir(parents=True)
    got = taskview.known_periods(repo_root=root, filled=["202601", "202609"])
    assert got == ["202609", "202607", "202601"], "降序：母本有效期次 ∪ 出过稿产物目录"


def test_已知期次_没产物的目录不算(tmp_path):
    """取数在途、只记过对话的目录都没有数据——不算一期（202611 实况：只有 ai_calls）。"""
    root, _ = _roots(tmp_path)
    d = root / "out" / "202611"
    d.mkdir()
    (d / "ai_calls.jsonl").write_text("", encoding="utf-8")
    (root / "out" / "_acquisition" / "202611").mkdir(parents=True)
    assert taskview.known_periods(repo_root=root, filled=["202609"]) == ["202609"]


def test_已知期次_啥都没有_空列表(tmp_path):
    root, _ = _roots(tmp_path)
    assert taskview.known_periods(repo_root=root, filled=[]) == []
