"""审批记录只有成功持久化后，签发/撤回操作才报告成功。

2026-10-21 起签单落在系统状态库（`out/_state/wenheng.sqlite`，ADR-0012），
不再是 `approval.json`；所以「持久化失败」用**写库失败**注入，保留的也是库里的上一条记录。
"""
import asyncio
import json
import pathlib
import sqlite3

from server import approval
from server import app as app_module


def _sign_data():
    return {
        "period": "202609",
        "counts": {"manual": 0},
        "assertions": {"fail": 0},
    }


def _state_db(out_dir):
    """`out/<期次>` 同级的 `_state/`（与 `approval` 内部口径一致）。"""
    return out_dir.parent / "_state" / "wenheng.sqlite"


def _fail_store_write(monkeypatch, message="simulated persistence failure"):
    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(approval.state_store, "put_approval", boom)


def test_sign_fails_and_preserves_last_record_when_store_write_fails(
    tmp_path, monkeypatch
):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    ok, _ = approval.sign(out_dir, "rick", _sign_data())
    assert ok
    ok, _ = approval.revoke(out_dir, "rick", "修正")
    assert ok
    before = approval.read(out_dir)

    _fail_store_write(monkeypatch)

    ok, error = approval.sign(out_dir, "rick", _sign_data(), note="再次签发")

    assert not ok
    assert "写入失败" in error
    after = approval.read(out_dir)
    assert after["signed"] is False
    assert [item["action"] for item in after["history"]] == ["sign", "revoke"]
    assert after["history"] == before["history"]          # 上一条记录原样保留
    assert not list((tmp_path / "_state").glob("*.tmp-*"))  # 半截库/临时文件不残留
    assert not (out_dir / approval.APPROVAL_NAME).exists()  # 文件不再是真相


def test_sign_persists_state_and_history_for_a_fresh_read(tmp_path):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    data = _sign_data()
    data["counts"]["manual"] = 2

    ok, _ = approval.sign(
        out_dir, "rick", data, note="已核对", manual_ack=True
    )

    assert ok
    persisted = approval.read(out_dir)
    assert persisted["signed"] is True
    assert persisted["actor"] == "rick"
    assert persisted["note"] == "已核对"
    assert persisted["manual_ack"] is True
    assert [item["action"] for item in persisted["history"]] == ["sign"]
    assert persisted["history"][0]["manual_open"] == 2
    assert approval.status(out_dir, persisted) == "signed"
    # 库是真身；导出件只有人可读的 Markdown
    assert _state_db(out_dir).is_file()
    assert (out_dir / approval.RECORD_NAME).is_file()


def test_revoke_fails_without_changing_signed_record_when_store_write_fails(
    tmp_path, monkeypatch
):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    ok, _ = approval.sign(out_dir, "rick", _sign_data())
    assert ok
    before = approval.read(out_dir)

    _fail_store_write(monkeypatch)

    ok, error = approval.revoke(out_dir, "rick", "修正")

    assert not ok
    assert "写入失败" in error
    assert approval.read(out_dir) == before               # 签名与历史一字未动
    assert before["signed"] is True
    assert not list((tmp_path / "_state").glob("*.tmp-*"))


def test_sign_succeeds_when_derived_markdown_write_fails(tmp_path, monkeypatch):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    real_write = approval.atomic_io.write_text_atomic

    def fail_record_write(path, text, *args, **kwargs):
        if pathlib.Path(path).name == approval.RECORD_NAME:
            raise OSError("simulated Markdown write failure")
        return real_write(path, text, *args, **kwargs)

    monkeypatch.setattr(approval.atomic_io, "write_text_atomic", fail_record_write)

    ok, _ = approval.sign(out_dir, "rick", _sign_data())

    assert ok
    assert approval.read(out_dir)["signed"] is True


def test_sign_route_returns_409_when_approval_persistence_fails(
    tmp_path, monkeypatch
):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    monkeypatch.setattr(app_module, "require_admin", lambda request: "rick")
    monkeypatch.setattr(app_module, "resolve_period_dir", lambda period: out_dir)
    monkeypatch.setattr(app_module.collation, "build", lambda period_dir: _sign_data())
    _fail_store_write(monkeypatch)

    class _Request:
        session = {"user": "rick"}

        async def json(self):
            return {"note": "", "known": False}

    response = asyncio.run(
        app_module.api_period_sign_json(_Request(), "202609")
    )

    assert response.status_code == 409
    assert "写入失败" in json.loads(response.body)["error"]
    assert approval.read(out_dir)["signed"] is False
