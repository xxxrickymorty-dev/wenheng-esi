# -*- coding: utf-8 -*-
"""状态库写不进去时，回给馆员的是人话（ADR-0012 决定 7，2026-10-22 补）。

上一票只做了页首横幅（`/api/status` 的 `state_db`）说「为什么」；这一票补的是
**操作失败那一刻**：签单 / 撤回 / 标记存疑 / 在线填 落库失败时，接口回的是
「保存失败：…这次操作没有生效」而不是库版本、迁移、`tools/state_export.py` 这些术语。
技术原文不许丢——它进服务端日志（`wenheng.state` 这个 logger），日志才是排障入口。
"""
import asyncio
import json
import logging
import sqlite3
import sys
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import app as app_module  # noqa: E402
from src import state_store  # noqa: E402

#: 馆员看不懂、看到会乱执行的词（技术原文只准出现在日志里）。
JARGON = ("schema", "Schema", "sqlite", "SQLite", "tools/", "state_export",
          "迁移", "PRAGMA", "版本号")


class _Req:
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self.body = body if body is not None else {}

    async def json(self):
        return self.body


def _sign_data():
    return {"period": "202607", "counts": {"manual": 0}, "assertions": {"fail": 0}}


def _degraded_store(tmp_path, *, signed=False):
    """`out/<期次>` 同级建一个「版本比程序新」的库；返回期次目录（不碰真数据）。"""
    out_dir = tmp_path / "202607"
    out_dir.mkdir()
    db = out_dir.parent / "_state" / "wenheng.sqlite"
    state_store.put_approval(db, "202607", {
        "period": "202607", "signed": signed, "actor": "馆员" if signed else "",
        "signed_at": "2026-10-22 09:00:00" if signed else "", "note": "",
        "manual_ack": False, "snapshot": {}, "fingerprint": {}, "history": [],
    })
    with sqlite3.connect(str(db)) as con:
        con.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    return out_dir


def _wire(monkeypatch, out_dir):
    """路由的前置：期次目录 / 管理员门 / 签单快照都指到 tmp。"""
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: out_dir)
    monkeypatch.setattr(app_module, "require_admin", lambda request: "馆员")
    monkeypatch.setattr(app_module.collation, "build", lambda period_dir: _sign_data())


def _body(response):
    return json.loads(response.body)


def _assert_human(error):
    assert error.startswith("保存失败"), error
    assert "没有生效" in error and "没有被保存" in error, error
    assert "管理员" in error, error
    for word in JARGON:
        assert word not in error, f"技术词 {word!r} 不该出现在给馆员的话里：{error}"


# ---------------------------------------------------------------- 四条写入口
def test_签单落库失败回人话且不出现技术词(tmp_path, monkeypatch, caplog):
    out_dir = _degraded_store(tmp_path)
    _wire(monkeypatch, out_dir)

    with caplog.at_level(logging.WARNING, logger="wenheng.state"):
        response = asyncio.run(app_module.api_period_sign_json(
            _Req("馆员", {"note": "", "known": True}), "202607"))

    assert response.status_code == 409
    body = _body(response)
    _assert_human(body["error"])
    assert body["hint"] == "", "写库失败不该再补「闸门」提示（会把人带偏）"
    # 技术原文完整进日志：库版本 + 本程序版本 + 异常类型
    assert "状态库写入失败" in caplog.text
    assert "schema 99" in caplog.text and "本程序" in caplog.text
    assert "SchemaTooNew" in caplog.text


def test_撤回签单落库失败回同一句人话(tmp_path, monkeypatch, caplog):
    out_dir = _degraded_store(tmp_path, signed=True)
    _wire(monkeypatch, out_dir)

    with caplog.at_level(logging.WARNING, logger="wenheng.state"):
        response = asyncio.run(app_module.api_period_revoke_json(
            _Req("馆员", {"note": "改一下"}), "202607"))

    assert response.status_code == 409
    body = _body(response)
    _assert_human(body["error"])
    assert "撤回" in caplog.text, "日志要能看出是哪一步没写成"
    assert "schema 99" in caplog.text


def test_标记存疑落库失败回人话(tmp_path, monkeypatch, caplog):
    out_dir = _degraded_store(tmp_path)
    _wire(monkeypatch, out_dir)

    with caplog.at_level(logging.WARNING, logger="wenheng.state"):
        response = asyncio.run(app_module.api_period_flag_json(
            _Req("馆员", {"loc": "T01/r9c3"}), "202607"))

    assert response.status_code == 409
    _assert_human(_body(response)["error"])
    assert "SchemaTooNew" in caplog.text


def test_在线填落库失败回人话并说清已存的那几处还在(tmp_path, monkeypatch, caplog):
    out_dir = _degraded_store(tmp_path)
    _wire(monkeypatch, out_dir)

    with caplog.at_level(logging.WARNING, logger="wenheng.state"):
        response = asyncio.run(app_module.api_period_fill_json(
            _Req("馆员", {"items": {"正文/p1::甲": "33.87"}}), "202607"))

    assert response.status_code == 409
    error = _body(response)["error"]
    _assert_human(error)
    assert "此前已保存的" not in error, "一处都没存上时不该说「已保存的仍在」"
    assert "schema 99" in caplog.text


# ---------------------------------------------------------------- 正常库不受影响
def test_正常库签单照旧成功(tmp_path, monkeypatch):
    out_dir = tmp_path / "202607"
    out_dir.mkdir()
    _wire(monkeypatch, out_dir)

    result = asyncio.run(app_module.api_period_sign_json(
        _Req("馆员", {"note": "已核对", "known": True}), "202607"))

    assert result["status"] == "signed"
    db = out_dir.parent / "_state" / "wenheng.sqlite"
    assert state_store.get_approval(db, "202607")["signed"] is True


# ---------------------------------------------------------------- 映射函数本身
@pytest.mark.parametrize("exc,note", [
    (state_store.SchemaTooNew("状态库 schema 99 高于本程序 3"), state_store.READONLY_NOTE),
    (sqlite3.OperationalError("database is locked"), state_store.WRITE_FAILED_NOTE),
    (OSError("磁盘写满"), state_store.WRITE_FAILED_NOTE),
])
def test_写失败翻成人话且技术原文进日志(exc, note, caplog):
    with caplog.at_level(logging.WARNING, logger="wenheng.state"):
        got = state_store.write_error_note(exc, action="保存")

    assert got == note
    for word in JARGON:
        assert word not in got
    assert type(exc).__name__ in caplog.text and str(exc) in caplog.text
    assert state_store.is_write_failure_note(got) is True
    assert state_store.is_write_failure_note("本期已签单，无需重复") is False
