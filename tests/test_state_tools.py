# -*- coding: utf-8 -*-
"""状态库与旧文件之间的两个工具：`state_import`（导入）与 `state_export`（导出）。

判据：幂等（重跑结果一致）、不删原文件、形状非法不落行、
**反向 e2e**（库 → 导出 → 新库导入 → 逐字段相等，ADR-0012 后果段要求的兜底）。
"""
import json

import pytest

import state_export
import state_import
from src import state_store


def _record(period, history=True):
    rec = {
        "signed": True, "actor": "馆员", "signed_at": "2026-10-20 11:16:42",
        "note": "e2e 验收", "manual_ack": True, "period": period,
        "snapshot": {"counts": {"total": 712, "manual": 4},
                     "assertions": {"total": 48, "fail": 0}, "bigtable": {}},
        "fingerprint": {"algorithm": "sha256", "version": 1,
                        "files": {"red_slots.json": "ab" * 32}},
        "red_slots_sha256": "ab" * 32, "revoked_at": "",
    }
    if history:
        rec["history"] = [
            {"action": "sign", "actor": "馆员", "at": "2026-10-20 11:16:42",
             "note": "e2e 验收", "manual_ack": True, "manual_open": 4},
            {"action": "revoke", "actor": "馆员", "at": "2026-10-20 11:16:43",
             "note": "e2e 撤回"},
        ]
    return rec


@pytest.fixture
def repo(tmp_path):
    """最小仓库：out/202607（签单+存疑）、out/202603（形状非法）、out/_jobs（非期次，不该被扫）。"""
    out = tmp_path / "out"
    d = out / "202607"
    d.mkdir(parents=True)
    (d / "approval.json").write_text(json.dumps(_record("202607"), ensure_ascii=False),
                                     encoding="utf-8")
    (d / "review.json").write_text(json.dumps({
        "正文/p1": {"state": "doubt", "by": "馆员", "at": "2026-10-20 11:00:00"},
    }, ensure_ascii=False), encoding="utf-8")

    bad = out / "202603"
    bad.mkdir()
    (bad / "approval.json").write_text("[1, 2, 3]", encoding="utf-8")

    (out / "_jobs" / "job-1").mkdir(parents=True)
    (out / "_jobs" / "job-1" / "approval.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _db(root):
    return root / "out" / "_state" / "wenheng.sqlite"


def test_导入幂等且不删原文件(repo):
    db = _db(repo)
    files = [repo / "out" / "202607" / n for n in ("approval.json", "review.json")]
    before = {p: p.read_bytes() for p in files}

    first = "\n".join(state_import.import_period(repo / "out" / "202607", db))
    assert "导入 2 条历史" in first
    assert "导入 1 处存疑" in first
    assert {p: p.read_bytes() for p in files} == before          # 原文件一字未改

    rec = state_store.get_approval(db, "202607")
    assert rec["actor"] == "馆员"
    assert [h["action"] for h in rec["history"]] == ["sign", "revoke"]
    assert state_store.get_reviews(db, "202607")["正文/p1"]["state"] == "doubt"

    second = "\n".join(state_import.import_period(repo / "out" / "202607", db))
    assert "已存在跳过" in second
    assert state_store.get_approval(db, "202607") == rec         # 重跑不改库


def test_形状非法逐期报错且不落行(repo):
    db = _db(repo)
    lines = "\n".join(state_import.import_period(repo / "out" / "202603", db))
    assert "形状非法" in lines and "未导入" in lines
    assert state_store.get_approval(db, "202603") is None


def test_空复核文件不算已导入(repo):
    out = repo / "out" / "202609"
    out.mkdir()
    (out / "review.json").write_text("{}", encoding="utf-8")
    lines = "\n".join(state_import.import_period(out, _db(repo)))
    assert "空文件" in lines
    assert state_store.get_reviews(_db(repo), "202609") == {}


def test_命令入口扫描期次目录且跳过非期次(repo, capsys):
    assert state_import.main(["--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "202607" in out and "202603" in out
    assert "_jobs" not in out
    assert state_store.periods(_db(repo)) == ["202607"]


def test_导出回原格式且字节稳定(repo):
    db = _db(repo)
    state_import.import_period(repo / "out" / "202607", db)
    out_dir = repo / "out" / "202607"
    (out_dir / "approval.json").unlink()
    (out_dir / "review.json").unlink()

    state_export.export_period(out_dir, db)
    first = (out_dir / "approval.json").read_bytes()
    assert json.loads(first) == _record("202607")                 # 形状与原文件一致
    assert json.loads((out_dir / "review.json").read_text(encoding="utf-8"))["正文/p1"]["state"] == "doubt"

    state_export.export_period(out_dir, db)
    assert (out_dir / "approval.json").read_bytes() == first      # 幂等：字节一致
    assert state_store.get_approval(db, "202607") is not None      # 不删库


def test_反向e2e_导出再导入到新库逐字段相等(repo, tmp_path):
    """回退路径的兜底用例：库 → `state_export` → 新库 `state_import` → 记录相等。"""
    src_db = _db(repo)
    state_import.import_period(repo / "out" / "202607", src_db)
    out_dir = repo / "out" / "202607"
    (out_dir / "approval.json").unlink()
    (out_dir / "review.json").unlink()
    state_export.export_period(out_dir, src_db)

    dst_db = tmp_path / "attic" / "wenheng.sqlite"
    state_import.import_period(out_dir, dst_db)

    assert state_store.get_approval(dst_db, "202607") == state_store.get_approval(src_db, "202607")
    assert state_store.get_reviews(dst_db, "202607") == state_store.get_reviews(src_db, "202607")


def test_导出命令只导库里有的期次(repo, capsys):
    db = _db(repo)
    state_import.import_period(repo / "out" / "202607", db)
    (repo / "out" / "202607" / "approval.json").unlink()
    (repo / "out" / "202607" / "review.json").unlink()
    empty = repo / "out" / "202611"
    empty.mkdir()
    assert state_export.main(["--root", str(repo)]) == 0
    assert (repo / "out" / "202607" / "approval.json").is_file()
    assert (repo / "out" / "202607" / "review.json").is_file()
    assert not (empty / "approval.json").exists()             # 库里没有 → 不造文件
