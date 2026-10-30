# -*- coding: utf-8 -*-
"""对话层 · 他校简报（阶段 2 续，2026-10-30）：只认「去『大学』二字」的简称。

钉三件事：
  ① 句子里写「昆明理工 / 浙江工业 / 上海交通」这类去大学写法，能被认成 ≥2 所校名；
  ② 完整校名（昆明理工大学）写法照旧认得；
  ③ 混写（完整 + 简称）不重复、不漏认；
  ④ panel 把简称落到全称（昆明理工 → 昆明理工大学），三态不整体抛错。

真数据用例依赖 `数据与复现/ESI数据/202609`（不入库）；缺席按 `_guard_registry` 登记跳过。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai                                                       # noqa: E402
from ai import _dialog                                          # noqa: E402
from _guard_registry import skip_unless                         # noqa: E402

SHORT_A, SHORT_B, SHORT_C = "昆明理工", "浙江工业", "上海交通"
FULL_A, FULL_B, FULL_C = "昆明理工大学", "浙江工业大学", "上海交通大学"


def _esi_ready() -> bool:
    from flexible import peers
    return (peers.ESI_ROOT / "202609").is_dir()


# ---------- 对话层：认得出简称 ----------

def test_short_names_recognized():
    p = _dialog.parse(f"对比{SHORT_A}和{SHORT_B}最新一期学科发展")
    assert p.kind == "compare"
    assert set(p.schools) == {SHORT_A, SHORT_B}


def test_full_names_still_recognized():
    p = _dialog.parse(f"对比{FULL_A}和海南大学")
    assert p.kind == "compare"
    assert FULL_A in p.schools and "海南大学" in p.schools


def test_mixed_full_and_short_no_dup():
    p = _dialog.parse(f"对比{FULL_A}和{SHORT_B}")
    assert p.kind == "compare"
    assert FULL_A in p.schools and SHORT_B in p.schools
    # 完整校名已认出，简称不应再被当第二所重复计入
    assert p.schools.count(FULL_A) == 1


def test_metric_word_blocks_compare_even_with_short():
    p = _dialog.parse(f"对比{SHORT_A}和{SHORT_B}的化学接近度")
    assert p.kind != "compare"


# ---------- 数据层：简称落到全称 ----------

@pytest.fixture(scope="module")
def panel_result():
    if not _esi_ready():
        skip_unless("ESI 202609 数据缺失", _esi_ready)
    from flexible import panel
    return panel.panel([SHORT_A, SHORT_B, SHORT_C], period_end="202609", n=2)


def test_panel_resolves_short_to_full(panel_result):
    got = {s["query"]: s["cn"] for s in panel_result["schools"]}
    assert got[SHORT_A] == FULL_A
    assert got[SHORT_B] == FULL_B
    assert got[SHORT_C] == FULL_C
    assert all(s["status"] == "ok" for s in panel_result["schools"])


def test_panel_mixed_full_and_short_dedup():
    if not _esi_ready():
        skip_unless("ESI 202609 数据缺失", _esi_ready)
    # 同校用全称与简称各写一遍，panel 按英文名去重成一条
    from flexible import panel
    p = panel.panel([FULL_A, SHORT_A], period_end="202609", n=2)
    ok = [s for s in p["schools"] if s["status"] == "ok"]
    assert len(ok) == 1 and ok[0]["cn"] == FULL_A
