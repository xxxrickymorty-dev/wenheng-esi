# -*- coding: utf-8 -*-
"""票 05：取数台「开新一期」入口（`POST /api/periods/{period}/acquisition/open`）。

验的是：六位 + 双月校验、只落空壳（**不 scan、不取数**）、空壳进期次列表，
且**不算「取过数」**（不把当前期误判成往期只读）。
"""
import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import acquisition_state as A                        # noqa: E402
from server import acquisition, app as app_module, config     # noqa: E402


class _Req:
    def __init__(self, user, method="POST", body=None):
        self.session = {"user": user} if user else {}
        self.method = method
        self.body = body

    async def json(self):
        return self.body or {}


def _call(monkeypatch, tmp_path, period, user=config.ADMIN_USER):
    st_dir = tmp_path / "_acquisition"
    monkeypatch.setattr(A, "STATE_DIR", st_dir)
    monkeypatch.setattr(acquisition, "STATE_DIR", st_dir)
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    return asyncio.run(app_module.api_acq_open(_Req(user), period)), st_dir


def test_开新一期落空壳不进取数动静(tmp_path, monkeypatch):
    r, st_dir = _call(monkeypatch, tmp_path, "202611")
    assert r["ok"] is True and r["period"] == "202611"
    saved = A.load_state("202611")
    assert saved["preflight"] == {"browser": "waiting", "esi": "waiting", "incites": "waiting"}
    assert saved["opened"]["at"] and saved["opened"]["by"] == config.ADMIN_USER
    # 不 scan、不取数：不落 groups/totals
    assert "groups" not in saved and "totals" not in saved
    assert (st_dir / "202611.json").is_file()
    # 空壳进期次列表，但不算「取过数」→ 不把当前期误判成往期只读
    assert any(x["period"] == "202611" for x in app_module._acquisition_only_periods(set()))
    assert app_module._acq_opened("202611") is True
    assert app_module._acq_touched("202611") is False
    assert app_module._acq_mode("202609") == "collect"


def test_开新一期拒绝非双月与非法期次(tmp_path, monkeypatch):
    for bad in ("202612", "202602", "20261", "20261x", "abcd12"):
        r, st_dir = _call(monkeypatch, tmp_path, bad)
        assert r.status_code == 400, bad
        assert not (st_dir / f"{bad}.json").exists(), bad


def test_开新一期需要管理员(tmp_path, monkeypatch):
    r, _ = _call(monkeypatch, tmp_path, "202611", user=config.OPERATOR_USER)
    assert r.status_code == 403
    r, _ = _call(monkeypatch, tmp_path, "202611", user=None)
    assert r.status_code == 401
