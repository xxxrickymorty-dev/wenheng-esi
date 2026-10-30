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


def test_开新一期操作员可用_未登录仍拦(tmp_path, monkeypatch):
    """2026-10-17 rick：demo（操作员）放开取数权限——开新一期不再仅管理员。"""
    r, _ = _call(monkeypatch, tmp_path, "202611", user=config.OPERATOR_USER)
    assert isinstance(r, dict), r
    saved = A.load_state("202611")
    assert saved["opened"]["by"] == config.OPERATOR_USER
    r, _ = _call(monkeypatch, tmp_path, "202611", user=None)
    assert r.status_code == 401


class Test路由:
    """两条判据都是「这条 POST 到底注册上没有」，不绑具体实现文件。

    2026-10-30 修：取数台路由 2026-10-25 从 `app.py` 迁到 `server/routes/acquisition.py`
    （`@router.post`），且 FastAPI 0.141 起 `include_router` 只往 `app.routes` 里放一个
    惰性的 `_IncludedRouter`，**不再把子路由摊平**——原来遍历 `app.routes` 找 `.path`
    的写法会静默返回 None。改成看 OpenAPI（公开契约，跨版本稳）与 router 上的 APIRoute。
    """

    ROUTE = "/api/periods/{period}/acquisition/open"

    def test_open路由是POST_api(self):
        from server.app import app
        ops = app.openapi()["paths"].get(self.ROUTE) or {}
        assert "post" in ops, f"OpenAPI 里没有 {self.ROUTE} 的 POST，只有 {sorted(ops)}"

    def test_open由本处理器接住(self):
        from server.routes import acquisition as acq_routes
        hit = next((r.endpoint.__name__ for r in acq_routes.router.routes
                    if getattr(r, "path", "") == self.ROUTE
                    and "POST" in (getattr(r, "methods", None) or set())), None)
        assert hit == "api_acq_open"
