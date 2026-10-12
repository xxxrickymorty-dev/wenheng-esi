# -*- coding: utf-8 -*-
"""P1 写操作 JSON 版 sign / forecast-choice（契约 §2.2 #7 #3）。

验的是：sign 走 approval.sign 同一闸门；forecast-choice 落盘 forecast_choice.json。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import approval                                    # noqa: E402
from server.app import resolve_period_dir                      # noqa: E402
from server import app as app_module, config                   # noqa: E402


class _Req:
    def __init__(self, user, method="GET", body=None):
        self.session = {"user": user}
        self.method = method
        self.body = body

    async def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


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
    def test_新请求期次无产物目录也可保存并读回(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        choices_dir = out_dir / "_forecast_choices"
        monkeypatch.setattr(config, "OUT_DIR", out_dir)
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", choices_dir)
        monkeypatch.setattr(app_module.forecasting, "page_context",
                            lambda: {"subjects": ["物理学"]})

        choice = {"citation": {"物理学": "SARIMA模型"}}
        saved = asyncio.run(app_module.api_forecast_choice(
            _Req(config.ADMIN_USER, "POST", {"choice": choice}), "202609"))
        assert isinstance(saved, dict)
        assert saved["ok"] is True
        assert saved["saved"] == 1
        assert saved["path"] == "_forecast_choices/202609.json"
        assert (choices_dir / "202609.json").is_file()
        assert not (out_dir / "202609").exists()

        loaded = asyncio.run(app_module.api_forecast_choice_get(
            _Req(config.ADMIN_USER), "202609"))
        assert isinstance(loaded, dict)
        assert loaded["period"] == "202609"
        assert loaded["choice"] == choice
        assert loaded["by"] == config.ADMIN_USER
        assert loaded["at"]

    def test_POST保存后缀期次时保留原名(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        choices_dir = out_dir / "_forecast_choices"
        monkeypatch.setattr(config, "OUT_DIR", out_dir)
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", choices_dir)
        period = "202605_复现"

        saved = asyncio.run(app_module.api_forecast_choice(
            _Req(config.ADMIN_USER, "POST", {"choice": {}}), period))
        assert saved["path"] == f"_forecast_choices/{period}.json"
        assert (choices_dir / f"{period}.json").is_file()
        assert not (out_dir / "202605").exists()

    def test_POST按ForecastMeta_subjects接受动态候选(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", tmp_path / "choices")
        monkeypatch.setattr(app_module.forecasting, "page_context",
                            lambda: {"subjects": ["运行期候选学科"]})
        result = asyncio.run(app_module.api_forecast_choice(
            _Req(config.ADMIN_USER, "POST", {
                "choice": {"citation": {"运行期候选学科": "SARIMA模型"}},
            }), "202609"))
        assert result["ok"] is True
        assert result["saved"] == 1

    def test_POST拒绝不在ForecastMeta_subjects中的学科(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", tmp_path / "choices")
        monkeypatch.setattr(app_module.forecasting, "page_context",
                            lambda: {"subjects": ["物理学"]})
        response = asyncio.run(app_module.api_forecast_choice(
            _Req(config.ADMIN_USER, "POST", {
                "choice": {"citation": {"候选缺失": "SARIMA模型"}},
            }), "202609"))
        assert response.status_code == 400

    def test_GET兼容读取旧文件但不迁移且新配置优先(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        choices_dir = out_dir / "_forecast_choices"
        period = "202605_复现"
        old_choice = {"citation": {"物理学": "SARIMA模型"}}
        new_choice = {"rank": {"物理学": "recommended"}}
        old_file = out_dir / period / "forecast_choice.json"
        old_file.parent.mkdir(parents=True)
        old_file.write_text(json.dumps({
            "choice": old_choice, "by": "old-admin", "at": "old-time",
        }, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(config, "OUT_DIR", out_dir)
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", choices_dir)

        old = asyncio.run(app_module.api_forecast_choice_get(
            _Req(config.ADMIN_USER), period))
        assert old == {
            "period": period, "choice": old_choice,
            "by": "old-admin", "at": "old-time",
        }
        assert not choices_dir.exists()
        assert json.loads(old_file.read_text(encoding="utf-8"))["choice"] == old_choice

        new_file = choices_dir / f"{period}.json"
        new_file.parent.mkdir(parents=True)
        new_file.write_text(json.dumps({
            "choice": new_choice, "by": "new-admin", "at": "new-time",
        }, ensure_ascii=False), encoding="utf-8")
        preferred = asyncio.run(app_module.api_forecast_choice_get(
            _Req(config.ADMIN_USER), period))
        assert preferred["choice"] == new_choice
        assert preferred["by"] == "new-admin"

    def test_空选择表示全部使用推荐(self, tmp_path, monkeypatch):
        choices_dir = tmp_path / "out" / "_forecast_choices"
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", choices_dir)
        monkeypatch.setattr(app_module.forecasting, "page_context",
                            lambda: {"subjects": []})
        result = asyncio.run(app_module.api_forecast_choice(
            _Req(config.ADMIN_USER, "POST", {"choice": {}}), "202609"))
        assert result["ok"] is True
        assert result["saved"] == 0
        assert json.loads((choices_dir / "202609.json").read_text(encoding="utf-8"))["choice"] == {}

    def test_POST拒绝无效JSON形状和期次路径(self, tmp_path, monkeypatch):
        choices_dir = tmp_path / "out" / "_forecast_choices"
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", choices_dir)
        monkeypatch.setattr(app_module.forecasting, "page_context",
                            lambda: {"subjects": ["物理学"]})
        invalid_bodies = [
            [],
            {"choice": []},
            {"choice": {"unknown": {"物理学": "SARIMA模型"}}},
            {"choice": {"citation": []}},
            {"choice": {"citation": {"不存在的学科": "SARIMA模型"}}},
            {"choice": {"citation": {"物理学": "不存在的模型"}}},
            {"choice": {"citation": {"物理学": []}}},
            json.JSONDecodeError("bad JSON", "", 0),
        ]
        for body in invalid_bodies:
            response = asyncio.run(app_module.api_forecast_choice(
                _Req(config.ADMIN_USER, "POST", body), "202609"))
            assert response.status_code == 400

        response = asyncio.run(app_module.api_forecast_choice(
            _Req(config.ADMIN_USER, "POST", {"choice": {}}), "202609/../../outside"))
        assert response.status_code == 400
        assert not (tmp_path / "outside.json").exists()

    def test_POST只允许管理员(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", tmp_path / "choices")
        response = asyncio.run(app_module.api_forecast_choice(
            _Req(config.OPERATOR_USER, "POST", {"choice": {}}), "202609"))
        assert response.status_code == 403
        response = asyncio.run(app_module.api_forecast_choice(
            _Req(None, "POST", {"choice": {}}), "202609"))
        assert response.status_code == 401


class Test权限门:
    def test_sign放行操作员_匿名401(self):
        """2026-10-12：审批对操作员开放——不存在的期次回 404（不是 403）。"""
        assert asyncio.run(app_module.api_period_sign_json(
            _Req(config.OPERATOR_USER, "POST", {}), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_sign_json(
            _Req(None, "POST", {}), "199901")).status_code == 401

    def test_forecast_choice用require_admin(self):
        assert asyncio.run(app_module.api_forecast_choice(
            _Req(config.OPERATOR_USER, "POST", {"choice": {}}), "202609")).status_code == 403
        assert asyncio.run(app_module.api_forecast_choice(
            _Req(None, "POST", {"choice": {}}), "202609")).status_code == 401

    def test_forecast_choice_GET放行操作员_匿名401(self):
        # 2026-10-11：读回选择是只读，操作员放行（拿到条目形状即证明门已放行）。
        r = asyncio.run(app_module.api_forecast_choice_get(
            _Req(config.OPERATOR_USER), "202609"))
        assert r["period"] == "202609"
        assert asyncio.run(app_module.api_forecast_choice_get(
            _Req(None), "202609")).status_code == 401


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

    def test_revoke放行操作员_匿名401(self):
        """2026-10-12：撤回随审批一并对操作员开放——不存在的期次回 404（不是 403）。"""
        assert asyncio.run(app_module.api_period_revoke_json(
            _Req(config.OPERATOR_USER, "POST", {}), "199901")).status_code == 404
        assert asyncio.run(app_module.api_period_revoke_json(
            _Req(None, "POST", {}), "199901")).status_code == 401

    def test_fill用require_admin(self):
        assert asyncio.run(app_module.api_period_fill_json(
            _Req(config.OPERATOR_USER, "POST", {}), "202609")).status_code == 403
        assert asyncio.run(app_module.api_period_fill_json(
            _Req(None, "POST", {}), "202609")).status_code == 401

    def test_flag用require_admin(self):
        assert asyncio.run(app_module.api_period_flag_json(
            _Req(config.OPERATOR_USER, "POST", {}), "202609")).status_code == 403
        assert asyncio.run(app_module.api_period_flag_json(
            _Req(None, "POST", {}), "202609")).status_code == 401

class TestForecastChoice计数:
    """#17：嵌套形状 {route: {学科: 模型}} 下 len(choice) 恒为路线数——saved 要数学科。"""

    def test_嵌套形状按学科求和(self):
        from server.app import _count_forecast_choice
        n, routes = _count_forecast_choice(
            {"citation": {"A": "m1", "B": "m2"}, "rank": {"C": "m3"}})
        assert n == 3 and routes == 2          # 验收：saved=3

    def test_旧扁平形状按条目数(self):
        from server.app import _count_forecast_choice
        n, routes = _count_forecast_choice({"A": "m1", "B": "m2"})
        assert n == 2 and routes is None

    def test_空选择(self):
        from server.app import _count_forecast_choice
        assert _count_forecast_choice({}) == (0, None)

