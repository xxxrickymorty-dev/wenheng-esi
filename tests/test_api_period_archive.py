# -*- coding: utf-8 -*-
"""GET /api/periods/{period}/archive 运行档案 JSON（契约 §2.2 #16）。

与档案页同源（archive.build）；安全要求：不回服务器绝对路径。
另锁一个 2026-09-24 修的既有 bug：期次上下文的「对勘本」产物链接
原拼成 /p/{期次}/collation（无此路由）→ 现指回 /p/{期次}。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import archive, jobs                              # noqa: E402
from server.app import resolve_period_dir                     # noqa: E402


class Test产物链接修复:
    def test_期次上下文对勘本链接指回期次页(self, repo):
        d = resolve_period_dir("202607")
        if d is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
        arts = jobs.collect_period_artifacts(d.name)
        coll = next((a for a in arts if a["key"] == "collation"), None)
        if coll is None:
            return
        assert coll["url"] == "/p/202607", f"got {coll['url']}"
        assert coll["url"] != "/p/202607/collation"


class TestArchive组装:
    def test_build含六块(self, repo):
        d = resolve_period_dir("202607")
        if d is None:
            from _guard_registry import skip_unless
            skip_unless("out/202607 不存在", lambda: resolve_period_dir("202607") is not None)
        view = archive.build(d, job=None,
                             artifacts=jobs.collect_period_artifacts(d.name))
        for k in ("period", "waterfall", "replay", "audit", "env", "logpack", "artifacts"):
            assert k in view, k
        assert view["logpack"]["key"] == "logpack"

    def test_接口层剥掉绝对路径(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_archive")[1].split("@app.")[0]
        assert 'view.pop("out_dir"' in block
        assert 'view.pop("progress_path"' in block
        assert '"logpack_url"' in block


class Test权限:
    def test_用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_period_archive")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_路由是GET(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/archive")' in src
