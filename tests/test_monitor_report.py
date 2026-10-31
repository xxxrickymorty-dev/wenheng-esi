# -*- coding: utf-8 -*-
"""监测版（高校 ESI 报告）测试：名单完整性 + 缓存完整性 + 最简版渲染。

数据依赖 = `monitor_data/_cache_<期次>.json`（缓存入库）与 `数据与复现/ESI数据/`
（只读源）。缺缓存时按登记簿规则跳过并留探针。
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from _guard_registry import skip_unless            # noqa: E402
from monitor import report as mr                   # noqa: E402
from monitor import schools as sch                 # noqa: E402

_PERIOD = mr.latest_period()
_cache_probe = lambda: bool(_PERIOD) and mr.cache_path(_PERIOD).exists()   # noqa: E731


def test_schools_list_integrity():
    """名单自检：中文名唯一、985/211 都有量、每条带省份。"""
    cns = [s["cn"] for s in sch.SCHOOLS]
    assert len(cns) == len(set(cns)), "中文名有重复"
    n985 = sum(1 for s in sch.SCHOOLS if s["is985"])
    assert n985 == 39 and len(sch.SCHOOLS) - n985 >= 70
    assert all(s["prov"] and s["en"] for s in sch.SCHOOLS)
    assert sch.find("海南大学") is not None
    assert sch.find("不存在大学") is None


def test_cache_covers_built_in_schools():
    """缓存完整性：109 校在机构总表/学科榜里能对上号（未入册校白名单除外）。"""
    if not _PERIOD or not mr.cache_path(_PERIOD).exists():
        skip_unless("监测版期次缓存未建（monitor_data/_cache_*.json 缺）", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    known = {row[0] for row in cache["cn_inst"]}
    known |= {en for v in cache["fields"].values() for en in v["schools"]}
    missing = [s["cn"] for s in sch.SCHOOLS if s["en"] not in known]
    assert missing == ["中国政法大学"], f"名单里有缓存对不上的校：{missing}"


def test_render_minimal_report_hainan():
    """最简版渲染（海大）：12 学科行、2 个前 1‰、五段俱全、无论文层无图表。"""
    if not _PERIOD or not mr.cache_path(_PERIOD).exists():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    html = mr.render("海南大学", _PERIOD, cache)
    assert html.count('<span class="en">') == 12, "海大应上榜 12 学科"
    assert "前 1‰ 俱乐部（2 学科）" in html
    for sec in ("学科站位", "前 1‰ 俱乐部", "进位预警", "省内对比", "对标"):
        assert sec in html
    assert "期刊集中度" not in html and "高被引 / 热点论文" not in html, "最简版不含论文层章"
    assert "data:image" not in html and "<svg" not in html, "最简版不带图表"
    assert "红件清单" not in html, "监测版不借云大产线的红件清单语言"


def test_render_unregistered_school_states():
    """未入册校（中国政法大学）也出报告：如实呈现，不编数字。"""
    if not _PERIOD or not mr.cache_path(_PERIOD).exists():
        skip_unless("监测版期次缓存未建", _cache_probe)
    cache = mr.load_cache(_PERIOD)
    html = mr.render("中国政法大学", _PERIOD, cache)
    assert "未收录该校" in html
    assert "本期不出学科行" in html


def test_doctor_checks_pass_on_202609():
    """doctor D1/D2/D3/D6 对当期全绿（D3 的未入册校=政法大学，白名单内不算写法错）。"""
    from monitor import doctor as mdoc
    if not _PERIOD or not (mr.ESI_ROOT / _PERIOD).is_dir() or not mr.cache_path(_PERIOD).exists():
        skip_unless("监测版期次数据或缓存缺席", lambda: _PERIOD is not None
                    and (mr.ESI_ROOT / _PERIOD).is_dir())
    rep = mdoc.check(_PERIOD)
    assert rep["fails"] == 0, f"doctor 有 fail：{[i for i in rep['items'] if not i['ok']]}"
    d3 = next(i for i in rep["items"] if i["id"] == "D3")
    assert "未入册 1" in d3["detail"], "应恰好一所未入册校（中国政法大学）"
