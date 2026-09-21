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
import parse_ledger                                             # noqa: E402
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
                    lambda: (INC / em.SNAP_MAP["202607"]).is_dir())


def _need_esi():
    if not ESI.is_dir():
        skip_unless("缺 ESI 原始包（数据与复现/ESI数据）", lambda: ESI.is_dir())


def _need_orig():
    if not ORIG.exists():
        skip_unless("缺人工原件（云南大学原报告/2026年第4期）", lambda: ORIG.exists())


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
    _need_orig()
    ok, total, diffs = em.compare_with_original(data, ORIG)
    # 22 学科 × 11 校 = 242，写**精确值**而不是「大于 200」：少一行也要红。
    # 2026-09-20 之前这里是 `> 200`，而实际只比了 231 格 —— 原件「植物学与动物学」
    # 那一行因行名与台账规范名不一致被 `continue` 跳过，比对少 11 格却仍报"全对"。
    assert total == 22 * 11, f"应覆盖全部 {22 * 11} 格，实为 {total}（有行名没匹配上）"
    # 唯一差异是「社会科学·财大」——已由 rick 与馆员核对确认**原件有误**
    # （原件 102.41% 的原料 2169 不属于任何一期 InCites 快照，而其余 230 格
    #  用当期快照全部吻合）。这不是"容忍误差"，是"差异已查清并确认"。
    known = {(d["disc"], d["school"]) for d in data.get("known_diffs") or []}
    assert known == {("社会科学", "财大")}, "已确认分歧清单变了，需重新核查"
    got = {(cn, s) for cn, s, _ in diffs}
    assert got <= known, f"出现了已确认之外的差异：{sorted(got - known)[:5]}"
    assert ok >= total - len(known)


# ============================================================ ③ Y 的判据
def test_Y的单元格必然在ESI榜内():
    """直接钉判据：凡是标了 `Y` 的，该机构就必须真的在那份 ESI 1% 榜里。

    为什么不是"接近度 ≥ 1"：原件里存在 >100% 却仍显示百分比的格子
    （社会科学·财大 102.41%），说明判据是"在不在榜"，不是数值大小。
    """
    data = _data()
    _need_esi()
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
    _need()
    snap = INC / em.SNAP_MAP["202607"]
    p = em._disc_file(snap, "Agricultural Sciences")
    assert p is not None and p.exists(), "农业科学的表没找到（文件名尾巴粘了 xlsx）"
    p2 = em._disc_file(snap, "Social Sciences, general")
    assert p2 is not None, "社会科学（小写 general）没找到"


# ============================================================ ⑤ 行名归一（2026-09-20 加）
def test_原件每行行名都能归一命中我们算的矩阵():
    """🔴 守住「整行静默跳过」这一类失效。

    母版与历期原件把「植物与动物学」写作「植物**学**与动物学」；台账规范名没有那个
    「学」字。按行名精确匹配的后果是**两端一起哑**：
      · 上游 `fill_docx.fill_matrix` 查不到 → 整行 11 格不填（报告留白）；
      · 下游 `compare_with_original` 查不到 → `continue` 跳过 → 少比 11 格还报"全对"。
    所以判据是：**原件 T20 的 22 个行名，归一后必须一个不少地查到数据。**
    """
    from docx import Document                                  # noqa: PLC0415

    _need_orig()
    d = Document(str(ORIG))
    t = next((x for x in d.tables
              if "云大" in [c.text.strip() for c in x.rows[0].cells]), None)
    assert t is not None, "原件里找不到 T20 矩阵表"
    data = _data()
    names = [r.cells[0].text.strip() for r in t.rows[1:]]
    missed = [n for n in names if parse_ledger.norm_disc_cn(n) not in data["matrix"]]
    assert not missed, f"这些行名归一后仍查不到矩阵数据（会静默留白）：{missed}"
    assert len(names) == 22, f"原件 T20 应有 22 个学科行，实为 {len(names)}"


def test_学科中文名别名表只做显式映射():
    """别名表是显式的：不认识的写法原样返回，绝不做模糊包含匹配 ——
    「生物与生物化学」会被「化学」截胡（`_cn2en` 踩过同一个坑）。"""
    assert parse_ledger.norm_disc_cn("植物学与动物学") == "植物与动物学"
    assert parse_ledger.norm_disc_cn("植物与动物学") == "植物与动物学"
    assert parse_ledger.norm_disc_cn("化学") == "化学"
    assert parse_ledger.norm_disc_cn("生物与生物化学") == "生物与生物化学"
    assert parse_ledger.norm_disc_cn("  化学  ") == "化学"
    assert parse_ledger.norm_disc_cn(None) == ""
    # 别名表的值必须都是台账规范名，别把规范名指到别的写法上
    assert set(parse_ledger.DISC_CN_ALIAS.values()) <= set(parse_ledger.DISCIPLINES_CN.values())
