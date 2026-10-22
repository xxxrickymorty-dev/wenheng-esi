# -*- coding: utf-8 -*-
"""清 e2e 审批流水（`tools/state_cleanup.py`）：**判据只认证据，分不清的一律保留**。

清理的是签单历史——不可重建。所以这里钉三件事：命中证据才删、空批注只有秒级成对才算证据、
当前签单行只在它自己是 e2e 产物时才删；dry-run 一次都不写库。
"""
import pytest

import state_cleanup
from src import state_store


def _row(i, ts, action, note=""):
    return {"id": i, "ts": ts, "action": action, "actor": "demo",
            "payload": {"action": action, "at": ts, "actor": "demo", "note": note}}


def _verdicts(rows):
    return {v["row"]["id"]: v["delete"] for v in state_cleanup.classify(rows)}


def test_classify_deletes_only_what_has_evidence():
    rows = [
        _row(1, "2026-09-15 13:40:27", "sign", "e2e 验收"),
        _row(2, "2026-09-15 13:40:27", "revoke", "e2e 撤回"),
        _row(3, "2026-09-15 13:40:28", "sign", ""),           # 空批注，但与 #2（e2e）1 秒成对
        _row(4, "2026-09-15 12:35:04", "revoke", "复核数据来源"),   # 人话 → 留
        _row(5, "2026-09-30 05:15:14", "sign", ""),           # 空批注又不成对 → 留
        _row(6, "2026-09-30 05:17:40", "revoke", ""),
        _row(7, "2026-09-29 21:18:28", "sign", "probe"),      # 探针自述也算证据
    ]
    assert _verdicts(rows) == {1: True, 2: True, 3: True, 4: False, 5: False, 6: False, 7: True}


def test_empty_note_pairs_only_within_window():
    """空批注离 e2e 行 60 秒：不是秒级成对，不能算证据。"""
    rows = [_row(1, "2026-09-15 13:40:27", "revoke", "e2e 撤回"),
            _row(2, "2026-09-15 13:41:27", "sign", "")]
    assert _verdicts(rows) == {1: True, 2: False}


def test_classify_approval_needs_e2e_marks_on_every_field():
    assert state_cleanup.classify_approval(None) == (False, "库里没有这一期的签单行（本来就是未签）")
    delete, _ = state_cleanup.classify_approval(
        {"signed": False, "note": "e2e 验收", "revoke_note": "e2e 撤回"})
    assert delete
    # 有一个字段是人话（或全为空）就分不清 → 保留
    assert not state_cleanup.classify_approval(
        {"signed": False, "note": "e2e 验收", "revoke_note": "复核后撤回"})[0]
    assert not state_cleanup.classify_approval({"signed": False, "note": "", "revoke_note": ""})[0]
    assert not state_cleanup.classify_approval({"signed": True, "note": "通过"})[0]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """tmp 版仓库根（`run_period` 按 ROOT 找 `out/<期次>`）+ 指到 tmp 的状态库。"""
    monkeypatch.setattr(state_cleanup, "ROOT", tmp_path)
    monkeypatch.setenv(state_store.ENV_VAR, str(tmp_path / "out" / "_state" / state_store.DB_NAME))
    out_dir = tmp_path / "out" / "209901"
    out_dir.mkdir(parents=True)
    return tmp_path, out_dir


def _seed(db, period, entries, record=None):
    for entry in entries:
        state_store.put_approval(db, period, {"period": period, "signed": False},
                                 history_entry=entry)
    if record is not None:
        state_store.put_approval(db, period, record)


def _entry(ts, action, note=""):
    return {"action": action, "actor": "demo", "at": ts, "note": note}


def test_dry_run_writes_nothing_then_apply_deletes_only_evidence(repo, capsys):
    root, out_dir = repo
    period = out_dir.name
    db = state_store.db_path(out_dir)
    _seed(db, period, [
        _entry("2026-09-15 13:40:27", "sign", "e2e 验收"),
        _entry("2026-09-15 13:40:27", "revoke", "e2e 撤回"),
        _entry("2026-09-15 12:35:04", "sign", "复核通过，同意报送"),
    ], record={"period": period, "signed": False, "note": "e2e 验收", "revoke_note": "e2e 撤回"})
    before = [(r["id"], state_cleanup._note(r)) for r in state_store.list_history(db, period)]

    assert state_cleanup.run_period(period, db) == 0                  # dry-run
    assert [(r["id"], state_cleanup._note(r)) for r in state_store.list_history(db, period)] == before
    assert state_store.get_approval(db, period) is not None, "dry-run 不许动签单行"
    assert not (out_dir / "审批记录.md").exists(), "dry-run 不许写导出件"

    removed = state_cleanup.run_period(period, db, apply=True)
    assert removed == 2
    left = state_store.list_history(db, period)
    assert [state_cleanup._note(r) for r in left] == ["复核通过，同意报送"]
    assert state_store.get_approval(db, period) is None, "e2e 签单行删掉 → 这一期回到「未签」"
    assert (out_dir / "审批记录.md").exists(), "导出件必须跟着库变"
    assert "未签单" in (out_dir / "审批记录.md").read_text(encoding="utf-8")

    assert state_cleanup.run_period(period, db, apply=True) == 0, "第二次跑应当已经干净"
    assert len(state_store.list_history(db, period)) == 1


def test_apply_keeps_approval_row_when_it_is_not_e2e(repo):
    _root, out_dir = repo
    period = out_dir.name
    db = state_store.db_path(out_dir)
    _seed(db, period, [_entry("2026-09-15 13:40:27", "sign", "e2e 验收")],
          record={"period": period, "signed": True, "note": "通过", "signed_at": "2026-09-15 13:40:27"})

    assert state_cleanup.run_period(period, db, apply=True) == 1
    rec = state_store.get_approval(db, period)
    assert rec is not None and rec.get("signed") is True, "真签单行不许被清理工具碰"
