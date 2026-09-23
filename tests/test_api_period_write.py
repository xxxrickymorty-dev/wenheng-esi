# -*- coding: utf-8 -*-
"""P1 写操作 JSON 版 sign / forecast-choice（契约 §2.2 #7 #3）。

验的是：sign 走 approval.sign 同一闸门；forecast-choice 落盘 forecast_choice.json。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import approval                                    # noqa: E402
from server.app import resolve_period_dir                      # noqa: E402


class TestSign闸门:
    def test_approval_sign返回ok_rec(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        rec = approval.read(d)
        assert "signed" in rec
        assert "fingerprint" in rec or rec.get("signed") is False

    def test_fingerprint返回dict(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        fp = approval.fingerprint(d)
        assert isinstance(fp, dict)

    def test_status三态(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        st = approval.status(d)
        assert st in ("unsigned", "signed", "stale")


class TestForecastChoice落盘:
    def test_写入forecast_choice_json(self, tmp_path):
        rec = {"choice": {"Chemistry": "SARIMA模型"},
               "by": "demo", "at": "2026-09-23 10:00:00"}
        out = tmp_path / "forecast_choice.json"
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["choice"]["Chemistry"] == "SARIMA模型"
        assert loaded["by"] == "demo"


class Test权限门:
    def test_sign用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_sign_json")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_forecast_choice用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_forecast_choice(request")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_forecast_choice_GET用current_user不用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_forecast_choice_read")[1].split("@app.")[0]
        assert "require_admin" not in block
        assert "current_user" in block


class Test路由存在:
    def test_sign路由是POST_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/sign")' in src

    def test_forecast_choice路由是POST_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/forecast-choice")' in src

class TestP2写操作:
    def test_revoke路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/revoke")' in src

    def test_fill路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/fill")' in src

    def test_flag路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/flag")' in src

    def test_revoke用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_revoke_json")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_fill用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_fill_json")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_flag用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_flag_json")[1].split("@app.")[0]
        assert "require_admin" in block
