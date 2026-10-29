# -*- coding: utf-8 -*-
"""tools/verify_latency.py 的用例。

重点验「降级链」：run_log 时间字段 → docx mtime；signed_at → history；都没有就
明写「未签单 / 无出稿时间」，**绝不静默跳过**。
"""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime

import pytest

import verify_latency as VL
from _guard_registry import skip_unless

REPO = pathlib.Path(__file__).resolve().parent.parent


def _period_dir(root: pathlib.Path, period: str) -> pathlib.Path:
    d = root / period
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(d: pathlib.Path, name: str, payload) -> pathlib.Path:
    p = d / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _touch_docx(d: pathlib.Path, when: datetime) -> pathlib.Path:
    p = d / f"报告初稿_{d.name}（试排）.docx"
    p.write_bytes(b"fake")
    ts = when.timestamp()
    os.utime(p, (ts, ts))
    return p


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture()
def fake_out(tmp_path, monkeypatch):
    root = tmp_path / "out"
    root.mkdir()
    monkeypatch.setattr(VL, "OUT_ROOT", root)
    return root


# ---------------------------------------------------------------- 正常路径
def test_gap_from_run_log_and_signed_at(fake_out):
    d = _period_dir(fake_out, "202609")
    _write(d, "run_log.json", {"period": "202609", "finished_at": "2026-09-28 10:00:00"})
    _write(d, "approval.json", {"signed": True, "signed_at": "2026-09-30 10:00:00"})
    row = VL.measure("202609", d)
    assert row["draft_source"] == "run_log.finished_at"
    assert row["draft_at"] == "2026-09-28 10:00:00"
    assert row["signed_at"] == "2026-09-30 10:00:00"
    assert row["gap_hours"] == pytest.approx(48.0)
    assert row["gap_text"] == "2.0 天"          # 满 48h 起按天写
    assert row["status"] == "已签单"


def test_gap_under_threshold_in_hours(fake_out):
    d = _period_dir(fake_out, "202609")
    _write(d, "run_log.json", {"finished_at": "2026-09-28 10:00:00"})
    _write(d, "approval.json", {"signed": True, "signed_at": "2026-09-28 15:30:00"})
    row = VL.measure("202609", d)
    assert row["gap_text"] == "5.5 小时"


def test_started_at_plus_elapsed(fake_out):
    """run_log 只有 started_at + elapsed_sec 时现算（现实中 run_log 无任何时间字段）。"""
    d = _period_dir(fake_out, "202609")
    _write(d, "run_log.json", {"started_at": "2026-09-28 10:00:00", "elapsed_sec": 150.0})
    _write(d, "approval.json", {"signed": True, "signed_at": "2026-09-28 12:00:00"})
    row = VL.measure("202609", d)
    assert row["draft_source"] == "run_log.started_at+elapsed_sec"
    assert row["draft_at"] == "2026-09-28 10:02:30"


def test_docx_mtime_fallback(fake_out):
    d = _period_dir(fake_out, "202605")
    _touch_docx(d, datetime(2026, 10, 1, 9, 0, 0))
    row = VL.measure("202605", d)
    assert row["draft_source"] == "docx mtime"
    assert row["draft_at"].startswith("2026-10-01 09:00")
    assert row["status"] == VL.UNSIGNED      # 没 sign 就是未签单，但出稿时刻照样给


# ---------------------------------------------------------------- 字段缺失 / 未签单
def test_unsigned_is_reported_not_skipped(fake_out, capsys):
    d = _period_dir(fake_out, "202605")
    _touch_docx(d, datetime(2026, 10, 1, 9, 0, 0))
    assert VL.main(["--period", "202605"]) == 0
    out = capsys.readouterr().out
    assert "202605" in out
    assert "未签单" in out and "无 approval.json" in out


def test_signed_at_missing_falls_back_to_history(fake_out):
    d = _period_dir(fake_out, "202609")
    _touch_docx(d, datetime(2026, 9, 1, 8, 0, 0))
    _write(d, "approval.json", {
        "signed": True,
        "signed_at": "",
        "history": [{"action": "revoke", "at": "2026-08-01 00:00:00"},
                    {"action": "sign", "at": "2026-09-02 08:00:00"}],
    })
    row = VL.measure("202609", d)
    assert row["signed_at"] == "2026-09-02 08:00:00"
    assert row["note"] == "取自 history.sign.at"
    assert row["gap_text"] == "24.0 小时"


def test_signed_true_without_any_time(fake_out):
    d = _period_dir(fake_out, "202609")
    _write(d, "approval.json", {"signed": True})
    row = VL.measure("202609", d)
    assert row["status"] == VL.UNSIGNED
    assert "无可用时间字段" in row["note"]


def test_signed_false(fake_out):
    d = _period_dir(fake_out, "202609")
    _write(d, "approval.json", {"signed": False, "signed_at": "2026-09-02 08:00:00"})
    assert VL.measure("202609", d)["status"] == VL.UNSIGNED


def test_broken_approval_json(fake_out):
    d = _period_dir(fake_out, "202609")
    (d / "approval.json").write_text("{不是 json", encoding="utf-8")
    row = VL.measure("202609", d)
    assert row["status"] == VL.UNSIGNED
    assert "解析失败" in row["note"]


def test_no_draft_at_all(fake_out):
    d = _period_dir(fake_out, "202609")
    _write(d, "approval.json", {"signed": True, "signed_at": "2026-09-02 08:00:00"})
    row = VL.measure("202609", d)
    assert row["status"] == VL.NO_DRAFT
    assert row["draft_source"] == VL.NO_DRAFT


def test_inverted_gap_is_flagged(fake_out):
    """签单后又重出稿 → 负间隔，必须标「倒挂」而不是当成正常值。"""
    d = _period_dir(fake_out, "202609")
    _touch_docx(d, datetime(2026, 10, 27, 8, 0, 0))
    _write(d, "approval.json", {"signed": True, "signed_at": "2026-10-17 13:51:33"})
    row = VL.measure("202609", d)
    assert row["gap_hours"] < 0
    assert row["status"] == "倒挂"
    assert "签单时刻早于出稿时刻" in row["note"]


def test_parse_time_variants():
    assert VL.parse_time("2026-10-17 13:51:33") == datetime(2026, 10, 17, 13, 51, 33)
    assert VL.parse_time("2026-10-17T13:51:33") == datetime(2026, 10, 17, 13, 51, 33)
    assert VL.parse_time("").__class__ is type(None)
    assert VL.parse_time(None) is None
    assert VL.parse_time(12345) is None
    assert VL.parse_time("看不懂的时间") is None


# ---------------------------------------------------------------- 输出 / 不写 out/
def test_all_scans_and_json(fake_out, capsys):
    a = _period_dir(fake_out, "202603")
    _touch_docx(a, datetime(2026, 10, 13, 15, 0, 0))
    _write(a, "approval.json", {"signed": True, "signed_at": "2026-10-13 15:13:30"})
    b = _period_dir(fake_out, "202605")
    _touch_docx(b, datetime(2026, 10, 1, 9, 0, 0))
    assert VL.main(["--all", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["period"] for r in rows] == ["202603", "202605"]
    assert rows[0]["status"] == "已签单"
    assert rows[1]["status"] == VL.UNSIGNED


def test_missing_period_dir_returns_3(fake_out, capsys):
    _period_dir(fake_out, "202603")
    assert VL.main(["--period", "202601"]) == 3
    assert "没有这些期次目录" in capsys.readouterr().err


def test_never_writes_out_root(fake_out, capsys):
    d = _period_dir(fake_out, "202609")
    _touch_docx(d, datetime(2026, 10, 27, 8, 0, 0))
    _write(d, "approval.json", {"signed": True, "signed_at": "2026-10-17 13:51:33"})
    before = _snapshot(fake_out)
    VL.main(["--all"])
    VL.main(["--all", "--json"])
    assert _snapshot(fake_out) == before


# ---------------------------------------------------------------- 真实期次探针
def test_real_period_probe():
    d = REPO / "out" / "202609"
    if not d.is_dir():
        skip_unless("out/202609 不存在（产物不入库，属正常）", lambda: d.is_dir())
    row = VL.measure("202609", d)
    assert row["period"] == "202609"
    assert row["status"] in ("已签单", "倒挂", VL.UNSIGNED, VL.NO_DRAFT)
