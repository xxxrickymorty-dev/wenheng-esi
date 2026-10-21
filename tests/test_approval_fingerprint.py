"""审批指纹基于受保护产物的内容，而不依赖文件时间戳。"""
import hashlib
import json
import os

import pytest

import state_import
from server import approval
from src import state_store


def _sign_data():
    return {
        "period": "202609",
        "counts": {"manual": 0},
        "assertions": {"fail": 0},
    }


def test_red_slots_content_change_with_same_size_and_mtime_makes_sign_stale(
    tmp_path,
):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    red_slots = out_dir / "red_slots.json"
    red_slots.write_bytes(b'{"value":1}')
    ok, signed = approval.sign(out_dir, "rick", _sign_data())
    assert ok
    original_stat = red_slots.stat()

    red_slots.write_bytes(b'{"value":2}')
    os.utime(
        red_slots,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    changed_stat = red_slots.stat()

    assert changed_stat.st_size == original_stat.st_size
    assert changed_stat.st_mtime_ns == original_stat.st_mtime_ns
    assert approval.fingerprint(out_dir) != signed["fingerprint"]
    assert approval.status(out_dir) == "stale"


def test_sign_records_red_slots_sha256_and_versioned_fingerprint(tmp_path):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    red_slots = out_dir / "red_slots.json"
    red_slots.write_bytes(b'{"rows":[1,2]}')

    ok, record = approval.sign(out_dir, "rick", _sign_data())

    assert ok
    expected_sha256 = hashlib.sha256(
        red_slots.read_bytes()
    ).hexdigest()
    persisted = approval.read(out_dir)
    assert persisted["red_slots_sha256"] == expected_sha256
    assert persisted["fingerprint"]["algorithm"] == "sha256"
    assert persisted["fingerprint"]["version"] == 1
    assert persisted["fingerprint"]["files"]["red_slots.json"] == persisted[
        "red_slots_sha256"
    ]


def test_sign_allows_missing_red_slots_and_records_null_hash(tmp_path):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()

    ok, record = approval.sign(out_dir, "rick", _sign_data())

    assert ok
    assert record["red_slots_sha256"] is None
    assert approval.read(out_dir)["red_slots_sha256"] is None


@pytest.mark.parametrize("legacy_format", ["size_mtime", "empty"])
def test_legacy_signed_record_is_importable_but_stale_without_backfill(
    tmp_path, legacy_format
):
    """旧 `approval.json` 由 `tools/state_import.py` **显式**导入；导入不改文件、不回填指纹。

    库里没有该期时 `approval.read` 一律返回未签单——不隐式回读文件（ADR-0012 决定 10），
    否则会同时存在两个真相。
    """
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    if legacy_format == "size_mtime":
        red_slots = out_dir / "red_slots.json"
        red_slots.write_bytes(b'{"value":1}')
        stat = red_slots.stat()
        old_fingerprint = {
            "red_slots.json": f"{stat.st_size}:{int(stat.st_mtime)}"
        }
    else:
        old_fingerprint = {}

    approval_path = out_dir / approval.APPROVAL_NAME
    old_record = {
        "signed": True,
        "fingerprint": old_fingerprint,
        "history": [],
    }
    approval_path.write_text(
        json.dumps(old_record, ensure_ascii=False), encoding="utf-8"
    )
    old_bytes = approval_path.read_bytes()

    assert approval.read(out_dir)["signed"] is False       # 导入前：库为准，不读文件
    state_import.import_period(out_dir, state_store.db_path(out_dir))

    loaded = approval.read(out_dir)

    assert loaded["fingerprint"] == old_fingerprint
    assert "red_slots_sha256" not in loaded
    assert approval.status(out_dir, loaded) == "stale"
    assert approval_path.read_bytes() == old_bytes          # 导入不删、不改原文件


def test_content_fingerprint_does_not_change_when_only_mtime_changes(tmp_path):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    table = out_dir / "table2.csv"
    table.write_bytes(b"subject,count\nA,1\n")
    before = approval.fingerprint(out_dir)
    original_stat = table.stat()
    os.utime(
        table,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 5_000_000_000),
    )

    assert table.stat().st_mtime_ns != original_stat.st_mtime_ns
    assert approval.fingerprint(out_dir) == before


@pytest.mark.parametrize("filename", ["报告初稿_测试.docx", "table2.csv"])
def test_report_artifact_content_changes_are_hashed(tmp_path, filename):
    out_dir = tmp_path / "202609"
    out_dir.mkdir()
    artifact = out_dir / filename
    artifact.write_bytes(b"first content")
    before = approval.fingerprint(out_dir)
    artifact.write_bytes(b"other content")

    assert approval.fingerprint(out_dir) != before
