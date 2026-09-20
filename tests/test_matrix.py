# -*- coding: utf-8 -*-
"""学科×高校矩阵 T20 的复现口径（2026-09-20）。

口径（由人工原件逐格反推，四期各 11/11 验证）：
    接近度 = InCites(该期快照) 该机构该学科被引 ÷ 该学科**当期** ESI 1% 阈值
    `Y` = 该机构在 ESI 该学科的 1% 榜内（**不是**"接近度 ≥ 1" ——
    原件里存在 102.41% 这种 >100% 却仍显示百分比的格子）

🔴 本组测试守的都是**静默失效**：串了机构、取错快照、用错判据，都不会抛异常，
   只会把错的数安静地填进报告。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO / "src"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import extract_matrix as em                                     # noqa: E402
from _guard_registry import skip_unless                         # noqa: E402

INC = REPO.parent / "数据与复现" / "incites"
LEDGER = REPO.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
ESI = REPO.parent / "数据与复现" / "ESI数据"
ORIG = REPO.parent / "云南大学原报告" / "云南大学学科信息参考2026年第4期.docx"


_CACHE = {}


def _data():
    """算一次，全程复用 —— compute 要打开 22 个快照文件，每个用例各算一遍会把
    pytest 拖到超时（实测 SIGTERM）。"""
    _need()
    if "d" not in _CACHE:
        _CACHE["d"] = em.compute(INC, LEDGER, "202607", esi_root=ESI)
    return _CACHE["d"]


def _need():
    if not (INC / em.SNAP_MAP["202607"]).is_dir():
        skip_unless("缺 InCites 快照（数据与复现/incites）",
                    (INC / em.SNAP_MAP["202607"]).is_dir())


# ============================================================ ① 机构同名判定
def test_云大不会被前缀串到云南财经或中医药():
    """`yunnan university` 是「云南财经大学」「云南中医药大学」的前缀 ——
    串了就把云大的值取成别人的，且不报错。"""
    u = em._norm("Yunnan University")
    assert em._same_school(u, em._norm("Yunnan University"))
    assert em._same_school(u, em._norm("YUNNAN UNIVERSITY"))          # 大小写
    assert not em._same_school(em._norm("Yunnan University of Finance & Economics"), u)
    assert not em._same_school(em._norm("Yunnan University of Chinese Medicine"), u)
    # 「西林」的全称带后缀，应当仍算同一家
    assert em._same_school(em._norm("Southwest Forestry University - China"),
                           em._norm("Southwest Forestry"))


def test_快照映射是逐期验证过的():
    """映射不能外推：没登记就报错，别默默用最近快照（猜错一期整张表都错）。"""
    assert set(em.SNAP_MAP) >= {"202601", "202603", "202605", "202607", "202609"}
    try:
        em.compute(INC, LEDGER, "209901")
        raise AssertionError("未登记的期次应当直接报错")
    except SystemExit as e:
        assert "没有登记" in str(e)


# ============================================================ ② 逐格一致（核心）
def test_与人工原件逐格比对():
    data = _data()
    ok, total, diffs = em.compare_with_original(data, ORIG)
    assert total > 200, f"应比 200 格以上，实为 {total}"
    # 已知分歧 1 格（社会科学·财大，原件口径与其余 230 格不一致）
    known = {(d["disc"], d["school"]) for d in data.get("known_diffs") or []}
    got = {(cn, s) for cn, s, _ in diffs}
    assert got <= known, f"出现了已知之外的差异：{sorted(got - known)[:5]}"
    assert ok >= total - len(known)


# ============================================================ ③ Y 的判据
def test_Y的单元格必然在ESI榜内():
    """直接钉判据：凡是标了 `Y` 的，该机构就必须真的在那份 ESI 1% 榜里。

    为什么不是"接近度 ≥ 1"：原件里存在 >100% 却仍显示百分比的格子
    （社会科学·财大 102.41%），说明判据是"在不在榜"，不是数值大小。
    """
    data = _data()
    top = em._esi_top_schools(ESI, "202607", "Chemistry")
    assert top, "读不到 ESI 化学榜"
    for short, en_key in em.UNIVERSITIES:
        v = (data["matrix"]["化学"].get(short) or {}).get("v")
        in_list = any(em._same_school(x, em._norm(en_key)) for x in top)
        if v == "Y":
            assert in_list, f"{short} 标了 Y 却不在 ESI 化学榜里（判据被改坏了）"


# ============================================================ ④ 溯源
def test_每格带溯源且指回快照():
    data = _data()
    src = data["matrix"]["化学"]["昆医"]["src"]
    assert "被引" in src and "阈值" in src
    assert data["snapshot"] in src


def test_脏文件名的学科表也能找到():
    """InCites 导出有脏写法：`Agricultural Sciencesxlsx.xlsx`、`Social Sciences, general`。"""
    snap = INC / em.SNAP_MAP["202607"]
    p = em._disc_file(snap, "Agricultural Sciences")
    assert p is not None and p.exists(), "农业科学的表没找到（文件名尾巴粘了 xlsx）"
    p2 = em._disc_file(snap, "Social Sciences, general")
    assert p2 is not None, "社会科学（小写 general）没找到"
