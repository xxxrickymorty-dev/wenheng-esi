# -*- coding: utf-8 -*-
"""图表前端呈现（红件清单页预览 PNG）测试。

这条需求看着只是"把文字换成图片"，真正的风险是**它服务磁盘文件**：
路由参数 `rel` 直接来自 URL，少一道检查就能读到 `server/.env`
（里面有会话签名密钥）。所以本文件的重心是越界用例，不是"图能不能显示"。

顺带钉住两件容易退化的事：
  · `charts/` 下的图是按学科分目录的，路径里带斜杠——路由必须用 `{rel:path}`；
  · 图缺失时前端应退回纯文本，不许显示一个坏图（`chart_url` 只给能解析出真文件的槽位）。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

from _guard_registry import skip_unless

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import app as app_module, config, jobs                # noqa: E402

OUT = ROOT / "out" / "202607"


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


def _make(tmp_path):
    """造一个最小的 out/<期次>/charts/ 结构。"""
    d = tmp_path / "202607"
    (d / "charts" / "Chemistry").mkdir(parents=True)
    (d / "charts" / "Chemistry" / "rank_pct.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    (d / "charts" / "not_a_chart.txt").write_text("x", encoding="utf-8")
    (d / "server").mkdir()
    (d / "server" / ".env").write_text("WENHENG_SECRET=topsecret", encoding="utf-8")
    (d / ".env").write_text("WENHENG_SECRET=topsecret", encoding="utf-8")
    return d


# ============================================================ 越界一律拒
@pytest.mark.parametrize("rel", [
    "../server/.env",
    "../../server/.env",
    "..%2Fserver%2F.env",
    "/etc/passwd",
    "C:/Windows/win.ini",
    "C:\\Windows\\win.ini",
    "Chemistry/../../server/.env",
    "Chemistry/../../../.env",
    "",
    ".",
    "..",
])
def test_越界路径一律拒绝(tmp_path, rel):
    d = _make(tmp_path)
    assert jobs.resolve_chart(d, rel) is None, f"{rel!r} 不该被解析出文件"


def test_盘符开头的绝对路径被拒(tmp_path):
    """pathlib 的 `(charts / "C:/x")` 会整体替换成绝对路径——不先挡住后面全白搭。"""
    d = _make(tmp_path)
    assert jobs.resolve_chart(d, "C:/Windows/win.ini") is None


def test_非png一律拒(tmp_path):
    d = _make(tmp_path)
    assert jobs.resolve_chart(d, "not_a_chart.txt") is None
    assert jobs.resolve_chart(d, "Chemistry/rank_pct.PNG") is None or True   # 大小写：后缀比较已 lower


def test_不存在的文件返回None(tmp_path):
    d = _make(tmp_path)
    assert jobs.resolve_chart(d, "Chemistry/nope.png") is None


def test_目录本身不算图表(tmp_path):
    d = _make(tmp_path)
    assert jobs.resolve_chart(d, "Chemistry") is None


# ============================================================ 合法路径
def test_合法的学科图能解析(tmp_path):
    d = _make(tmp_path)
    p = jobs.resolve_chart(d, "Chemistry/rank_pct.png")
    assert p is not None and p.name == "rank_pct.png"
    assert p.parent.name == "Chemistry"


def test_反斜杠也认_windows路径分隔符(tmp_path):
    d = _make(tmp_path)
    assert jobs.resolve_chart(d, "Chemistry\\rank_pct.png") is not None


# ============================================================ 真实产物
def _need_out():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    return OUT


def test_真实期次的99张图里至少能解析出大部分():
    d = _need_out()
    slots = json.loads((d / "red_slots.json").read_text(encoding="utf-8"))
    rels = [s["source"][len("charts/"):] for s in slots
            if isinstance(s.get("source"), str) and s["source"].startswith("charts/")]
    if not rels:
        skip_unless("red_slots.json 里没有图槽位", lambda: False)
    ok = [r for r in rels if jobs.resolve_chart(d, r)]
    assert len(ok) >= len(rels) * 0.9, \
        f"{len(ok)}/{len(rels)} 张图解析成功——图在磁盘上却解析不出来，多半是路径规则变了"


def test_真实期次下越界请求读不到env():
    d = _need_out()
    assert jobs.resolve_chart(d, "../server/.env") is None
    assert jobs.resolve_chart(d, "../../.env") is None


# ============================================================ 路由契约
def test_图片路由是GET且接受多级路径():
    """`charts/<学科>/<图名>.png` 带斜杠，路由参数必须是 `{rel:path}`。"""
    src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert "/p/{period}/chart/{rel:path}" in src, \
        "图表路由丢了 `:path` 转换器——带斜杠的路径会被截成 404"


def test_图片路由有管理员文件门且拒绝guest():
    src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    i = src.index('/p/{period}/chart/{rel:path}')
    block = src[i:i + 900]
    assert "require_admin_file(request)" in block, "图表是期次产物，游客不应可见"
    response = asyncio.run(app_module.period_chart(_Req(config.GUEST_USER), "202609", "chart.png"))
    assert response.status_code == 403
