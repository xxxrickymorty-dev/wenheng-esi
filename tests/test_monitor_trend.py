# -*- coding: utf-8 -*-
"""监测版 46 期趋势基建测试：单期提取同构性 + 跨期合并。

只依赖 trend.py 与本机只读源数据（数据与复现/ESI数据/202609）；不跑 build_all
（全量 46 期太慢），202609 单期提取在 module 级 fixture 里做一次。
缺源数据时按登记簿规则跳过并留探针（新 clone 环境不误报红灯）。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest                                      # noqa: E402

from _guard_registry import skip_unless            # noqa: E402
from monitor import report as mr                   # noqa: E402
from monitor import trend as mt                    # noqa: E402

_PERIOD = "202609"
_EN = "HAINAN UNIVERSITY"
_src_probe = lambda: (mr.ESI_ROOT / _PERIOD / "Institutions.xlsx").exists()   # noqa: E731


@pytest.fixture(scope="module")
def t202609():
    """202609 单期提取，全模块只跑一次（约 8 秒）。"""
    if not _src_probe():
        skip_unless("监测版源数据缺席（数据与复现/ESI数据/202609）", _src_probe)
    return mt.extract_period(_PERIOD)


def test_extract_202609_numbers(t202609):
    """海大 12 学科行、化学 m/线/行值、阈值与总表行——全部钉在只读源数据上。"""
    t = t202609
    subjects = [stem for stem, fd in t["fields"].items() if _EN in fd["schools"]]
    assert len(subjects) == 12, f"海大应上榜 12 学科，实得 {len(subjects)}"
    chem = t["fields"]["Chemistry"]
    assert chem["m"] == 2315 and chem["line"] == 231
    assert chem["line_cites"] == 99622.0
    # 行值＝[rank, cn_rank(CM∪NA 口径), papers, cites, cp, hcp, hp]；202609 化学为 15 列版式
    assert chem["schools"][_EN] == [390, 123, 3424.0, 68391.0, 19.97, 82.0, 4.0]
    assert t["thr1"]["CHEMISTRY"] == 7622.0
    assert t["n_inst"] == 10674
    assert t["inst"][_EN] == [871, 23305.0, 374063.0, 16.05]


def test_extract_schema_isomorphic_to_cache(t202609):
    """同构：trend 键（除 inst）⊆ cache 键，fields/thr1 子结构与 build_cache 完全同键。"""
    if not mr.cache_path(_PERIOD).exists():
        skip_unless("当期缓存未建（monitor_data/_cache_202609.json 缺）",
                    lambda: mr.cache_path(_PERIOD).exists())
    cache = mr.load_cache(_PERIOD)
    t = t202609
    assert set(t) == {"period", "built", "n_inst", "fields", "thr1", "inst"}
    assert set(t) - {"inst"} <= set(cache), "trend 键（除 inst）必须是 cache 键的子集"
    assert t["thr1"] == cache["thr1"], "同源阈值表应逐键相等"
    for stem, fd in t["fields"].items():
        assert set(fd) == {"m", "line", "line_cites", "schools"} == set(cache["fields"][stem])
        for en, row in fd["schools"].items():
            assert len(row) == 7 == len(cache["fields"][stem]["schools"][en])
    # cn_rank 口径差：trend 计 CHINA MAINLAND ∪ N/A，cache 只计 CHINA MAINLAND——差 1
    assert t["fields"]["Chemistry"]["schools"][_EN][1] == 123
    assert cache["fields"]["Chemistry"]["schools"][_EN][1] == 122


def test_combine_merges_ascending_and_skips_bad(tmp_path: pathlib.Path):
    """combine：手工临时期次文件按期升序合并；_index 判 bad 的期次即使有文件也不进趋势。"""

    def mk(period, rank, cites, m, chem_rank):
        return {"period": period, "built": "2026-10-31", "n_inst": 10000,
                "inst": {"TEST UNIVERSITY": [rank, 100, cites, 2.0]},
                "fields": {"Chemistry": {"m": m, "line": (m + 1) // 10, "line_cites": 900.0,
                                         "schools": {"TEST UNIVERSITY":
                                                     [chem_rank, 1, 50, cites, 2.0, None, None]}}},
                "thr1": {"CHEMISTRY": 7622.0}}

    root = tmp_path / "_trend"
    root.mkdir()
    # 故意按乱序写入：202103 先落盘、202001 后落盘
    (root / "202103.json").write_text(
        json.dumps(mk("202103", 900, 5000.0, 2000, 300)), encoding="utf-8")
    (root / "202001.json").write_text(
        json.dumps(mk("202001", 950, 4000.0, 1900, 310)), encoding="utf-8")
    (root / "202605.json").write_text(
        json.dumps(mk("202605", 800, 6000.0, 2100, 290)), encoding="utf-8")
    (root / "_index.json").write_text(json.dumps(
        {"built_at": "2026-10-31T00:00:00",
         "periods": {"202001": {"status": "ok"}, "202103": {"status": "ok"},
                     "202605": {"status": "bad", "reason": "D6"}}}), encoding="utf-8")

    out = mt.combine("TEST UNIVERSITY", root=root)
    assert out["en"] == "TEST UNIVERSITY"
    assert [p["period"] for p in out["points"]] == ["202001", "202103"]
    assert out["points"][0] == {"period": "202001", "total_rank": 950,
                                "total_cites": 4000.0, "n_inst": 10000}
    chem = out["fields"]["Chemistry"]
    assert [p["period"] for p in chem] == ["202001", "202103"]
    assert chem[1] == {"period": "202103", "rank": 300, "m": 2000, "cites": 5000.0,
                       "line_cites": 900.0, "thr1": 7622.0}
