# -*- coding: utf-8 -*-
"""清 e2e 审批流水（`tools/state_cleanup.py`）：**判据只认证据，分不清的一律保留**。

清理的是签单历史——不可重建。所以这里钉三件事：命中证据才删、空批注只有秒级成对才算证据、
当前签单行只在它自己是 e2e 产物时才删；dry-run 一次都不写库。
"""
import json
import sqlite3

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


# ------------------------------------------------------- scrub-note（清批注里的人名）
# 用占位姓名：真名不该进代码仓（这类姓名就是本工具要清的东西，测试里不需要真的）。
NAME = "张三"
CLEAN_NOTE = "复核通过，同意报送"


def _scrub_fixture(tmp_path, monkeypatch):
    """两期：目标期（两条人名批注 + 一条人话）与别的期（同样有人名，不该被碰）。"""
    monkeypatch.setattr(state_cleanup, "ROOT", tmp_path)
    monkeypatch.setenv(state_store.ENV_VAR, str(tmp_path / "out" / "_state" / state_store.DB_NAME))
    target, other = tmp_path / "out" / "202609", tmp_path / "out" / "202607"
    target.mkdir(parents=True)
    other.mkdir(parents=True)
    db = state_store.db_path(target)
    _seed(db, "202609", [
        {"action": "sign", "actor": "admin", "at": "2026-10-16 15:02:13",
         "note": f"{NAME}修改了学科数", "manual_ack": True, "manual_open": 0},
        _entry("2026-10-17 13:23:57", "sign", CLEAN_NOTE),
    ])
    _seed(db, "202607", [
        {"action": "sign", "actor": "admin", "at": "2026-09-15 12:35:03",
         "note": f"{NAME}审过", "manual_ack": True, "manual_open": 7},
    ])
    return db, target, other


def test_scrub_terms_parse_repeated_and_comma_separated():
    assert state_cleanup.parse_terms(["甲,乙", "丙", "甲", " 乙 "]) == ["甲", "乙", "丙"]
    assert state_cleanup.parse_terms(["甲，乙"]) == ["甲", "乙"], "中文逗号也认"
    with pytest.raises(state_cleanup.ScrubError):
        state_cleanup.parse_terms(["", " , "])


def test_scrub_dry_run_writes_nothing(tmp_path, monkeypatch):
    db, target, _other = _scrub_fixture(tmp_path, monkeypatch)
    before = state_store.list_history(db, "202609")

    assert state_cleanup.run_scrub("202609", db, [NAME]) == 1, "dry-run 只报告将改几条"

    assert state_store.list_history(db, "202609") == before, "dry-run 一个字节都不许写"
    assert not (db.parent / "backups").exists(), "dry-run 不写备份"
    assert not (tmp_path / "tmp").exists(), "dry-run 不写 before.json"
    assert not (target / "审批记录.md").exists(), "dry-run 不写导出件"


def test_scrub_apply_clears_only_target_period_and_term(tmp_path, monkeypatch):
    db, target, other = _scrub_fixture(tmp_path, monkeypatch)
    before = state_store.list_history(db, "202609")
    dirty = next(r for r in before if r["payload"].get("note") == f"{NAME}修改了学科数")

    assert state_cleanup.run_scrub("202609", db, [NAME], apply=True) == 1

    after = state_store.list_history(db, "202609")
    assert len(after) == len(before), "清批注不许少行"
    hit = next(r for r in after if r["id"] == dirty["id"])
    assert hit["payload"]["note"] == "", "整条清空，不换替身文案"
    # 其余字段一字不动（提升列 + payload 除 note 外的键）
    assert (hit["ts"], hit["action"], hit["actor"]) == (dirty["ts"], dirty["action"], dirty["actor"])
    assert {k: v for k, v in hit["payload"].items() if k != "note"} == \
           {k: v for k, v in dirty["payload"].items() if k != "note"}
    # 同一期里不含该词的批注不动；别的期次同样不动
    assert any(r["payload"].get("note") == CLEAN_NOTE for r in after)
    assert state_store.list_history(db, "202607")[0]["payload"]["note"] == f"{NAME}审过"

    # 备份：一致性副本 + before.json 留痕
    backups = sorted((db.parent / "backups").glob("wenheng-*-pre-note-scrub.sqlite"))
    assert len(backups) == 1
    con = sqlite3.connect(str(backups[0]))
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT payload FROM approval_history WHERE id=?",
                       (dirty["id"],)).fetchone()[0].count(NAME) == 1, "备份里仍是原批注"
    con.close()
    saved = json.loads((tmp_path / "tmp" / "_cleanup_202609_note" / "before.json")
                       .read_text(encoding="utf-8"))
    assert saved["terms"] == [NAME]
    assert saved["rows"][0]["payload"]["note"] == f"{NAME}修改了学科数"

    record = (target / "审批记录.md").read_text(encoding="utf-8")
    assert NAME not in record, "导出件按库重渲染，名字不该还在"
    assert CLEAN_NOTE in record


def test_scrub_second_apply_is_zero_and_writes_no_backup(tmp_path, monkeypatch):
    db, _target, _other = _scrub_fixture(tmp_path, monkeypatch)
    assert state_cleanup.run_scrub("202609", db, [NAME], apply=True) == 1
    assert state_cleanup.run_scrub("202609", db, [NAME], apply=True) == 0, "第二次跑应当归零"
    assert len(list((db.parent / "backups").glob("*.sqlite"))) == 1, "没有改动就不该再备份"


def test_scrub_touches_only_note_not_other_free_text(tmp_path, monkeypatch):
    """`actor` 里出现同一个词也不许被本工具改（只授权批注）。"""
    monkeypatch.setattr(state_cleanup, "ROOT", tmp_path)
    monkeypatch.setenv(state_store.ENV_VAR, str(tmp_path / "out" / "_state" / state_store.DB_NAME))
    out_dir = tmp_path / "out" / "202609"
    out_dir.mkdir(parents=True)
    db = state_store.db_path(out_dir)
    _seed(db, "202609", [{"action": "sign", "actor": NAME, "at": "2026-10-16 15:02:13",
                          "note": "通过"}])

    assert state_cleanup.run_scrub("202609", db, [NAME], apply=True) == 0
    row = state_store.list_history(db, "202609")[0]
    assert row["actor"] == NAME and row["payload"]["note"] == "通过"
