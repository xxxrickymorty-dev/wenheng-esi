# -*- coding: utf-8 -*-
"""在榜查询口（2026-11-04，P2 分析台契约）：`GET /api/monitor/schools` 的可选
查询参数 `field`（ESI 学科英文名）。

- 带 `field` → items 每条加 `in_field`（该校该学科是否进入本期 ESI 前 1% 榜单；
  数据源＝监测期次缓存 `fields[field]["schools"]`，键＝学校英文名
  （与 `src/monitor/schools.py` 的 en 名同源匹配）），顶层回显规范 `field`；
- `field` 不在缓存 22 学科里（或本期缓存缺该学科）→ 400 人话报错；
- 不带 `field` → 行为与从前完全一致（不加字段）。

仓库测试惯例是函数级（不依赖 httpx/TestClient），直测
`server.routes.monitor._monitor_school_payload`（路由层只是透传）。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from fastapi.responses import JSONResponse          # noqa: E402

from server.routes.monitor import _monitor_school_payload   # noqa: E402
from src.monitor import report as mr                # noqa: E402


@pytest.fixture
def work_root():
    """MONITOR_ROOT 替身（不用 pytest tmp_path：本机沙箱清理是
    基线 PermissionError，见交付说明）。"""
    d = (pathlib.Path(__file__).resolve().parent.parent / "tmp"
         / f"pt_mon_field_{uuid.uuid4().hex[:8]}")
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)

_CACHE = {
    "period": "202609", "built": "2026-10-01", "n_inst": 100,
    "cn_inst": [["TSINGHUA UNIVERSITY", 1, 2, 3, 4, 5]],
    "fields": {
        "Computer Science": {"m": 100, "line": 10, "line_cites": 1.0,
                             "schools": {"TSINGHUA UNIVERSITY": [1, 1, 2, 3, 4, 5, 6],
                                         "YUNNAN UNIVERSITY": [2, 1, 2, 3, 4, 5, 6]}},
        "Chemistry": {"m": 100, "line": 10, "line_cites": 1.0,
                      "schools": {"PEKING UNIVERSITY": [1, 1, 2, 3, 4, 5, 6]}},
    },
}


def _payload(monkeypatch, work_root, field=None, cache=_CACHE):
    monkeypatch.setattr(mr, "load_cache", lambda p: cache)
    monkeypatch.setattr(mr, "latest_period", lambda: "202609")
    monkeypatch.setattr(mr, "MONITOR_ROOT", work_root)   # generated=False 全体
    return _monitor_school_payload("202609", field=field)


def test_带field_在榜与不在榜(monkeypatch, work_root):
    out = _payload(monkeypatch, work_root, field="Computer Science")
    assert not isinstance(out, JSONResponse)
    assert out["field"] == "Computer Science", "顶层回显规范名"
    by_cn = {it["cn"]: it for it in out["schools"]}
    assert by_cn["清华大学"]["in_field"] is True, "榜内校＝True"
    assert by_cn["云南大学"]["in_field"] is True, "同科在榜的其他校也 True"
    assert by_cn["北京大学"]["in_field"] is False, "该科不在榜＝False"
    assert by_cn["中国人民大学"]["in_field"] is False
    assert by_cn["中国政法大学"]["in_field"] is False, "未入册校照常给 False"


def test_带field_大小写不敏感(monkeypatch, work_root):
    out = _payload(monkeypatch, work_root, field="computer science")
    assert out["field"] == "Computer Science", "norm 归一匹配，回显规范名"


def test_非法学科_400人话(monkeypatch, work_root):
    out = _payload(monkeypatch, work_root, field="占星学")
    assert isinstance(out, JSONResponse)
    assert out.status_code == 400
    assert "占星学" in out.body.decode("utf-8")
    assert "22 学科" in out.body.decode("utf-8"), "人话里给出去处"


def test_22学科但缓存缺该科_400(monkeypatch, work_root):
    out = _payload(monkeypatch, work_root, field="Space Science")
    assert isinstance(out, JSONResponse) and out.status_code == 400
    assert "Space Science" in out.body.decode("utf-8")


def test_无缓存带field_400(monkeypatch, work_root):
    out = _payload(monkeypatch, work_root, field="Chemistry", cache=None)
    assert isinstance(out, JSONResponse) and out.status_code == 400


def test_不带field_行为与从前逐字一致(monkeypatch, work_root):
    out = _payload(monkeypatch, work_root, field=None)
    assert isinstance(out, JSONResponse) is False
    assert "field" not in out, "顶层不得多出 field"
    for it in out["schools"]:
        assert "in_field" not in it, "不带 field：items 不加字段"
    by_cn = {it["cn"]: it for it in out["schools"]}
    assert by_cn["清华大学"]["en"] == "TSINGHUA UNIVERSITY"
    assert by_cn["清华大学"]["known"] is True
    assert by_cn["清华大学"]["generated"] is False
    assert by_cn["清华大学"]["url"] is None
    assert out["period"] == "202609" and out["built"] == "2026-10-01"
