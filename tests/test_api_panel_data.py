# -*- coding: utf-8 -*-
"""他校简报的数据口：`GET /api/periods/{period}/panel-data`（阶段 3 渲染层）。

钉三件事：
  ① `schools[].counts` 与**直接调** `flexible.panel()` 逐项相同（真数据 202609 三校）；
  ② 默认不带 `grid`，`?grid=1` 才带（`grid` 只给前端画图，不进模型上下文）；
  ③ 鉴权与邻近 `/api/periods/*` 一致：未登录 401。

为什么不用 `fastapi.testclient.TestClient`：本机 `.venv` 里没有 httpx（TestClient 的硬依赖），
装包会动环境。这里用一段极薄的 ASGI 调用直接打到 `app`——路由、查询参数、JSON 序列化
都是真跑的，只少了 httpx 那层壳。
"""
import asyncio
import json
import pathlib
import sys
import urllib.parse

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as appmod, config                      # noqa: E402


async def _asgi_get(path: str, query: str = ""):
    """一次 GET 走完整 ASGI 栈 → (状态码, 解析后的 JSON)。"""
    raw = query.encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET",
        "path": path, "raw_path": path.encode(), "query_string": raw,
        "root_path": "", "scheme": "http", "server": ("testserver", 80),
        "client": ("test", 12345),
        "headers": [(b"host", b"testserver"),
                    (b"accept", b"application/json")],
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await appmod.app(scope, receive, send)
    status = sent[0]["status"]
    body = b"".join(m.get("body", b"") for m in sent
                    if m["type"] == "http.response.body")
    return status, json.loads(body) if body else None


def _get(path: str, **params):
    return asyncio.run(_asgi_get(path, urllib.parse.urlencode(params)))


@pytest.fixture
def logged_in(monkeypatch):
    """守卫在请求时从 `server.app` 现取（late binding），patch 这里就放行。"""
    monkeypatch.setattr(appmod, "require_user", lambda request: config.ADMIN_USER)


def _panel_ready() -> bool:
    """真数据探针：ESI 目录里有 202609 才跑数据类用例（没有就如实 skip）。"""
    from flexible import peers
    return (peers.ESI_ROOT / "202609").is_dir()


def _need_data():
    if not _panel_ready():
        from _guard_registry import skip_unless
        skip_unless("ESI 数据目录里没有 202609（数据不入库，属正常）", _panel_ready)


SCHOOLS = ["昆明理工大学", "海南大学", "云南大学"]


class TestPanelData:
    def test_三校counts与直接调panel一致(self, logged_in):
        """真数据：昆工 [12]×6、海大 [9,10,11,11,11,12]、云大 [13,13,14,14,14,14]。"""
        _need_data()
        status, body = _get("/api/periods/202609/panel-data",
                            schools=",".join(SCHOOLS), n=6)
        assert status == 200, body

        from flexible.panel import panel
        direct = panel(SCHOOLS, period_end="202609", n=6)
        assert body["schools"] == direct["schools"] or \
            [(s["cn"], s["counts"]) for s in body["schools"]] == \
            [(s["cn"], s["counts"]) for s in direct["schools"]]
        got = {s["cn"]: s["counts"] for s in body["schools"]}
        assert got == {
            "昆明理工大学": [12] * 6,
            "海南大学": [9, 10, 11, 11, 11, 12],
            "云南大学": [13, 13, 14, 14, 14, 14],
        }
        assert body["periods"] == direct["periods"]

    def test_默认不带grid(self, logged_in):
        _need_data()
        status, body = _get("/api/periods/202609/panel-data",
                            schools="云南大学", n=6)
        assert status == 200
        assert "grid" not in body

    def test_grid等于1才给全量矩阵(self, logged_in):
        _need_data()
        status, body = _get("/api/periods/202609/panel-data",
                            schools="云南大学", n=6, grid=1)
        assert status == 200
        assert "grid" in body and set(body["grid"]) == {"counts", "sets"}

    def test_事件与共同差异照panel原样(self, logged_in):
        """事件标注必须来自 events（前端不算），所以这条口得原样交出去。"""
        _need_data()
        status, body = _get("/api/periods/202609/panel-data",
                            schools=",".join(SCHOOLS), n=6)
        assert status == 200
        from flexible.panel import panel
        direct = panel(SCHOOLS, period_end="202609", n=6)
        assert body["events"] == list(direct["events"])
        assert body["common"] == direct["common"]
        assert body["only"] == direct["only"]

    def test_latest取ESI最新一期(self, logged_in):
        _need_data()
        status, body = _get("/api/periods/latest/panel-data", schools="云南大学")
        assert status == 200
        assert body["period_end"] == "202609"


class TestPanelData门:
    def test_未登录401(self):
        status, body = _get("/api/periods/202609/panel-data", schools="云南大学")
        assert status == 401
        assert body["error"]

    def test_不存在的期次404(self, logged_in):
        status, _body = _get("/api/periods/199901/panel-data", schools="云南大学")
        assert status == 404

    def test_没给校名400(self, logged_in):
        status, body = _get("/api/periods/202609/panel-data")
        assert status == 400
        assert "高校" in body["error"]

    def test_不认识的学科400(self, logged_in):
        status, body = _get("/api/periods/202609/panel-data",
                            schools="云南大学", disciplines="炼丹术")
        assert status == 400
        assert "学科" in body["error"]
