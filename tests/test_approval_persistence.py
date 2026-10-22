"""审批记录只有成功持久化后，签发/撤回操作才报告成功。

2026-10-21 起签单落在系统状态库（`out/_state/wenheng.sqlite`，ADR-0012），
不再是 `approval.json`；所以「持久化失败」用**写库失败**注入，保留的也是库里的上一条记录。

2026-10-22 补：**未签 ≠ 没有历史**——签单行被撤（或被清理工具删掉）之后历史仍在，
`read()` 必须把历史带回来，否则人看的《审批记录.md》会渲染成空表。
"""
import asyncio
import json
import pathlib
import sqlite3

from server import approval
from server import app as app_module
from src import state_store


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


# ---------------------------------------------------------------- 未签也要看得到历史
def _seed_history_only(out_dir, entries):
    """库里只留历史、不留签单行（撤回后 / 清理 e2e 残留后的真实形态）。"""
    db = _state_db(out_dir)
    state_store.replace_approval(db, out_dir.name, {
        "period": out_dir.name, "signed": False, "history": entries})
    assert state_store.delete_approval(db, out_dir.name), "前置：签单行该删得掉"
    assert state_store.get_approval(db, out_dir.name) is None
    return db


def test_unsigned_period_still_reads_history_from_store(tmp_path):
    out_dir = tmp_path / "202607"
    out_dir.mkdir()
    _seed_history_only(out_dir, [
        {"action": "sign", "actor": "demo", "at": "2026-09-15 12:35:03",
         "note": "7 处待人工已按清单补齐，同意报送"},
        {"action": "revoke", "actor": "demo", "at": "2026-09-23 11:17:38",
         "note": "彩排误触签单，按设计路径撤回复原"},
    ])

    rec = approval.read(out_dir)

    assert rec["signed"] is False
    assert [h["action"] for h in rec["history"]] == ["sign", "revoke"]
    assert set(rec) == {"signed", "actor", "signed_at", "note", "manual_ack",
                        "snapshot", "fingerprint", "history"}, "未签态的形状不变"
    assert approval.status(out_dir, rec) == "unsigned"


def test_unsigned_record_markdown_keeps_history_rows(tmp_path):
    """未签时导出的《审批记录.md》仍要能看到历史的时间、动作与批注。"""
    out_dir = tmp_path / "202607"
    out_dir.mkdir()
    _seed_history_only(out_dir, [
        {"action": "sign", "actor": "demo", "at": "2026-09-15 12:35:03",
         "note": "7 处待人工已按清单补齐，同意报送"},
        {"action": "revoke", "actor": "demo", "at": "2026-09-23 11:17:38",
         "note": "彩排误触签单，按设计路径撤回复原"},
    ])

    approval._write_record(out_dir, approval.read(out_dir))      # noqa: SLF001

    text = (out_dir / approval.RECORD_NAME).read_text(encoding="utf-8")
    assert "未签单" in text
    assert "2026-09-15 12:35:03" in text and "签单" in text
    assert "2026-09-23 11:17:38" in text and "撤回" in text
    assert "彩排误触签单" in text

