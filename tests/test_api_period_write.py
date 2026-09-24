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
        block = src.split("async def api_forecast_choice(request")[1].split("@app.")[0]
        assert "request.method" in block
        assert "current_user" in block


class Test路由存在:
    def test_sign路由是POST_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/sign")' in src

    def test_forecast_choice读回路由是GET_api(self):
        """读回是 GET。2026-09-24 修：曾被误挂成 @app.post，把保存请求抢走了。"""
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/forecast-choice")' in src
        assert '@app.post("/api/periods/{period}/forecast-choice")' not in src


class Test路由顺序不打架:
    """FastAPI 按注册顺序匹配：同一路径上，先注册的窄方法路由会抢走后注册的宽方法路由。

    `forecast-choice` 就是这么坏的——读回被误挂成 `@app.post` 又注册在前面，
    POST 全被它接走，保存从不落盘（源串断言看不出来，只有按注册顺序模拟匹配才抓得到）。
    """

    @staticmethod
    def _first_hit(path, method):
        from server.app import app
        for r in app.routes:
            if getattr(r, "path", "") == path and method in (getattr(r, "methods", None) or set()):
                return r.endpoint.__name__
        return None

    def test_POST_forecast_choice由写入处理器接住(self):
        assert self._first_hit("/api/periods/{period}/forecast-choice", "POST") == "api_forecast_choice"

    def test_GET_forecast_choice由读回处理器接住(self):
        assert self._first_hit("/api/periods/{period}/forecast-choice", "GET") == "api_forecast_choice_get"

    def test_写入处理器真的落盘(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_forecast_choice(request")[1].split("@app.")[0]
        assert "forecast_choice.json" in block and "write_text" in block

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
