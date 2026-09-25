# -*- coding: utf-8 -*-
"""管理员书架只从部署产物按请求生成完整数据。"""
import json
from pathlib import Path

from server import shelf_data


def _write_period(root, period="202607", *, valid=True):
    target = root / period
    target.mkdir()
    (target / "overview_facts.json").write_text(json.dumps({
        "coverage_window": "2026年5月—2026年7月", "prev_label": "2026年5月",
        "rank_intl_now": 118, "rank_intl_delta": 2, "rank_cn_uni_now": 12,
        "top_papers_now": 24, "top_papers_delta": 1, "top3_by_top_papers": ["Chemistry"],
        "best_1permille": ["Chemistry"], "top2_not_entered": [], "n_disc_1pct": 3,
    }), encoding="utf-8")
    (target / "meta.json").write_text(json.dumps({
        "assertions": [["PASS"], ["FAIL"]], "top_total_by_period": {"202607": 24},
    }), encoding="utf-8")
    if valid:
        table = ("discipline,papers,total_cites,cnci,top_papers,thr_1pct,thr_1pct_gap,prox_change,rank_cn_change\n"
                 "Chemistry,10,20,2.5,3,1,0,+1,-\n")
    else:
        table = "discipline,papers\nwrong,1\n"
    (target / "table2.csv").write_text(table, encoding="utf-8")


def test_管理员数据只纳入完整的已部署期次(tmp_path):
    _write_period(tmp_path, "202607")
    _write_period(tmp_path, "202609", valid=False)
    payload = shelf_data.build_data([{"period": "202609"}, {"period": "202607"}], out_dir=tmp_path)
    assert [book["period"] for book in payload["books"]] == ["202607"]
    book = payload["books"][0]
    assert (book["no"], book["label"], book["n_assert_pass"], book["n_assert_total"]) == (38, "2026年7月", 1, 2)
    assert book["table"] == [{"en": "Chemistry", "cn": "化学", "papers": 10, "cites": 20,
                               "cnci": 2.5, "top": 3, "thr": 1, "gap": 0,
                               "prox": "+1", "rank": "-"}]
    assert payload["trend"] == {"202607": 24}


def test_所有期次异常仍返回有效且无指标来源的_js(tmp_path, monkeypatch):
    monkeypatch.setattr(shelf_data.config, "OUT_DIR", tmp_path)
    response = shelf_data.javascript_response([{"period": "202609"}])
    assert response.media_type == "application/javascript"
    assert response.body == b'window.WH_DATA = {"books":[],"trend":{}};\n'


def test_入库的静态空壳不再携带完整指标():
    root = Path(__file__).resolve().parents[1]
    prohibited = ("rank_intl_now", "cnci", "top_papers_now", "table2.csv")
    for path in (root / "web" / "public" / "shelf" / "data.js",
                 root / "web" / "dist" / "shelf" / "data.js"):
        content = path.read_text(encoding="utf-8-sig")
        assert "window.WH_DATA" in content
        assert not any(token in content for token in prohibited)
