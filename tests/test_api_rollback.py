# -*- coding: utf-8 -*-
"""回滚到上一版（票 07）：GET .../rollback-points 与 POST .../rollback。

口径（与契约 #23 一致）：
  · 只认「期次名合法 + 目录里有 `_superseded/`」——**允许当前没有成品**（重跑失败后来回滚）；
  · 回滚 = 先把当前成品撤进新的留档目录，再还原所选版本（回滚本身可再回滚）；
  · 有任务在跑 → 409；没有留档 → 404。
"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import config, jobs                      # noqa: E402
from server import app as app_module                 # noqa: E402

POINT = "20200101T000000"


class _Req:
    def __init__(self, user=None, body=None):
        self.session = {"user": user} if user else {}
        self.body = body

    async def json(self):
        return self.body


def _admin(body=None):
    return _Req(config.DEMO_USER, body)


def _mk_period(tmp_path, monkeypatch, with_points=True, with_current=True):
    out = tmp_path / "out"
    d = out / "202609"
    d.mkdir(parents=True)
    if with_current:
        (d / "red_slots.json").write_text("{}", encoding="utf-8")
        (d / "报告初稿_202609（试排）.docx").write_text("current", encoding="utf-8")
    if with_points:
        pdir = d / "_superseded" / POINT
        pdir.mkdir(parents=True)
        (pdir / "red_slots.json").write_text("{}", encoding="utf-8")
        (pdir / "报告初稿_202609（试排）.docx").write_text("old", encoding="utf-8")
        (pdir / "_来源.txt").write_text("留档说明", encoding="utf-8")
    monkeypatch.setattr(app_module.config, "OUT_DIR", out)
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: None)
    return d, out


def test_列出回滚点(tmp_path, monkeypatch):
    _mk_period(tmp_path, monkeypatch)
    r = asyncio.run(app_module.api_rollback_points(_admin(), "202609"))
    assert r["period"] == "202609"
    assert [p["id"] for p in r["points"]] == [POINT]
    files = r["points"][0]["files"]
    assert "报告初稿_202609（试排）.docx" in files
    assert all(not f.startswith("_") for f in files)      # 下划线是标记文件，不算成品


def test_回滚_还原且当前成品先撤下(tmp_path, monkeypatch):
    d, _ = _mk_period(tmp_path, monkeypatch)
    r = asyncio.run(app_module.api_rollback(_admin({"point": POINT}), "202609"))
    assert r["ok"] is True and r["point"] == POINT
    assert "报告初稿_202609（试排）.docx" in r["restored"]
    # 还原的是旧版内容
    assert (d / "报告初稿_202609（试排）.docx").read_text(encoding="utf-8") == "old"
    # 回滚前的 current 被另存成新留档（回滚可再回滚）
    assert r["pre_rollback_quarantined"]
    ids = [p["id"] for p in app_module._rollback_points(d)]
    assert POINT not in ids                                # 已消费的点不再列出
    assert len(ids) == 1                                   # 新留档点（含 current 版本）
    new_dir = d / "_superseded" / ids[0]
    assert (new_dir / "报告初稿_202609（试排）.docx").read_text(encoding="utf-8") == "current"


def test_没有留档_404(tmp_path, monkeypatch):
    _mk_period(tmp_path, monkeypatch, with_points=False)
    r = asyncio.run(app_module.api_rollback(_admin({}), "202609"))
    assert r.status_code == 404
    assert "回滚" in r.body.decode("utf-8")


def test_任务在跑_409(tmp_path, monkeypatch):
    _mk_period(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: {"period": "202607"})
    r = asyncio.run(app_module.api_rollback(_admin({"point": POINT}), "202609"))
    assert r.status_code == 409
    assert "202607" in r.body.decode("utf-8")


def test_期次名非法_404(tmp_path, monkeypatch):
    _mk_period(tmp_path, monkeypatch)
    r = asyncio.run(app_module.api_rollback_points(_admin(), "abc"))
    assert r.status_code == 404
