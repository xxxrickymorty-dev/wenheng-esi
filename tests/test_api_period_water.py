# -*- coding: utf-8 -*-
"""首屏学科水位端点（2026-10-20，决赛管理驾驶舱）。

只读 `matrix.json` 的「云大」列，把接近度翻成水尺行；不重算口径。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as app_module, config                    # noqa: E402


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


def _write(tmp_path, payload):
    d = tmp_path / "202609"
    d.mkdir()
    (d / "matrix.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return d


def test_从matrix取云大列_按接近度降序(monkeypatch, tmp_path):
    d = _write(tmp_path, {
        "period": "202609",
        "snapshot": "数据覆盖2016-2026.06.30",
        "matrix": {
            "化学": {"云大": {"v": "Y"}},
            "免疫学": {"云大": {"v": "81.97%"}},
            "空间科学": {"云大": {"v": "55.69%"}},
            "数学": {"云大": {"v": "—"}},
        },
    })
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: d if p == "202609" else None)

    out = asyncio.run(app_module.api_period_water(_Req(config.OPERATOR_USER), "202609"))

    assert out["period"] == "202609"
    assert out["snapshot"] == "数据覆盖2016-2026.06.30"
    assert [r["subject"] for r in out["rows"]] == ["化学", "免疫学", "空间科学"]
    assert out["rows"][0] == {"subject": "化学", "prox": 100.0, "state": "in"}
    assert out["rows"][1] == {"subject": "免疫学", "prox": 81.97, "state": "near"}
    assert out["rows"][2] == {"subject": "空间科学", "prox": 55.69, "state": "far"}


def test_没有矩阵_空行带说明(monkeypatch, tmp_path):
    d = tmp_path / "202609"
    d.mkdir()
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: d if p == "202609" else None)

    out = asyncio.run(app_module.api_period_water(_Req(config.ADMIN_USER), "202609"))

    assert out["rows"] == [] and "矩阵" in out["note"]


def test_匿名401(monkeypatch, tmp_path):
    d = _write(tmp_path, {"matrix": {}})
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: d if p == "202609" else None)

    out = asyncio.run(app_module.api_period_water(_Req(None), "202609"))

    assert out.status_code == 401
