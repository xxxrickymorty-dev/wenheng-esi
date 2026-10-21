"""审批记录只有成功持久化后，签发/撤回操作才报告成功。"""
import asyncio
import json
import os
from pathlib import Path

from server import approval
from server import app as app_module


def _sign_data():
    return {
        "period": "202609",
        "counts": {"manual": 0},
        "assertions": {"fail": 0},
    }


def _fail_replace_for(target_name):
    real_replace = os.replace

    def fail_replace(source, target):
        if Path(target).name == target_name:
            raise OSError("simulated persistence failure")
        return real_replace(source, target)

    return fail_replace


def test_sign_fails_and_preserves_last_record_when_approval_replace_fails(
    tmp_path, monkeypatch
):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    ok, _ = approval.sign(out_dir, "rick", _sign_data())
    assert ok
    ok, _ = approval.revoke(out_dir, "rick", "修正")
    assert ok

    approval_path = out_dir / approval.APPROVAL_NAME
    old_bytes = approval_path.read_bytes()
    monkeypatch.setattr(os, "replace", _fail_replace_for(approval.APPROVAL_NAME))

    ok, error = approval.sign(out_dir, "rick", _sign_data(), note="再次签发")

    assert not ok
    assert "写入失败" in error
    assert approval_path.read_bytes() == old_bytes
    persisted = approval.read(out_dir)
    assert persisted["signed"] is False
    assert [item["action"] for item in persisted["history"]] == ["sign", "revoke"]
    assert not list(out_dir.glob(f".{approval.APPROVAL_NAME}.*.tmp"))


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


def test_revoke_fails_without_changing_signed_record_when_replace_fails(
    tmp_path, monkeypatch
):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    ok, _ = approval.sign(out_dir, "rick", _sign_data())
    assert ok

    approval_path = out_dir / approval.APPROVAL_NAME
    old_bytes = approval_path.read_bytes()
    monkeypatch.setattr(os, "replace", _fail_replace_for(approval.APPROVAL_NAME))

    ok, error = approval.revoke(out_dir, "rick", "修正")

    assert not ok
    assert "写入失败" in error
    assert approval_path.read_bytes() == old_bytes
    persisted = approval.read(out_dir)
    assert persisted["signed"] is True
    assert [item["action"] for item in persisted["history"]] == ["sign"]
    assert not list(out_dir.glob(f".{approval.APPROVAL_NAME}.*.tmp"))


def test_sign_succeeds_when_derived_markdown_write_fails(tmp_path, monkeypatch):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    real_write = approval.atomic_io.write_text_atomic

    def fail_record_write(path, text, *args, **kwargs):
        if Path(path).name == approval.RECORD_NAME:
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
    monkeypatch.setattr(os, "replace", _fail_replace_for(approval.APPROVAL_NAME))

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
