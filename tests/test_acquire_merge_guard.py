# -*- coding: utf-8 -*-
"""取数并入的守卫（票 02）：**数据条件**拒绝重复并入 / 底座不符。

并入是全系统唯一会改台账的动作，所以守卫只看状态里的数据（副本状态、母本 sha），
不看界面在哪个视图；拒绝时**不落笔**（台账与副本一字不动）。
"""
import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import acquire as acq  # noqa: E402


def _args(tmp: pathlib.Path, period: str, **kw) -> argparse.Namespace:
    ns = dict(period=period, copy=None, snapshot=None, esi_root=None, dry=False, by="")
    ns.update(kw)
    return argparse.Namespace(**ns)


def _write_state(tmp: pathlib.Path, period: str, copy_state: dict) -> None:
    acq.A.STATE_DIR = tmp / "_acquisition"
    acq.A.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (acq.A.STATE_DIR / f"{period}.json").write_text(
        json.dumps({"period": period, "copy": copy_state}, ensure_ascii=False),
        encoding="utf-8")


def test_已并入再并_被拒且不落笔(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "台账.xlsx"
    ledger.write_bytes(b"ledger-bytes")
    monkeypatch.setattr(acq, "REPO", tmp_path)
    monkeypatch.setattr(acq, "LEDGER", ledger)
    _write_state(tmp_path, "202605", {
        "state": "merged", "path": "input/202605/监测表.xlsx",
        "merged_at": "2026-10-16 07:00:00", "merged_by": "admin"})

    rc = acq.cmd_merge(_args(tmp_path, "202605"))

    out = capsys.readouterr().out
    assert rc == 1, "已并入的期次不该再并"
    assert "已并入台账" in out and "2026-10-16 07:00:00" in out, out
    assert ledger.read_bytes() == b"ledger-bytes", "拒绝时不得动台账"


def test_副本底座不符_被拒(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "台账.xlsx"
    ledger.write_bytes(b"ledger-bytes")
    copy = tmp_path / "监测表.xlsx"
    copy.write_bytes(b"copy-bytes")
    monkeypatch.setattr(acq, "REPO", tmp_path)
    monkeypatch.setattr(acq, "LEDGER", ledger)
    _write_state(tmp_path, "202605", {
        "state": "review", "path": str(copy), "master_sha": "deadbeef"})

    rc = acq.cmd_merge(_args(tmp_path, "202605"))

    out = capsys.readouterr().out
    assert rc == 1, "底座不符必须拒绝"
    assert "底座" in out or "被改动" in out, out
    assert ledger.read_bytes() == b"ledger-bytes"


def test_没有副本_被拒(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "台账.xlsx"
    ledger.write_bytes(b"ledger-bytes")
    monkeypatch.setattr(acq, "REPO", tmp_path)
    monkeypatch.setattr(acq, "LEDGER", ledger)
    _write_state(tmp_path, "202605", {"state": "none", "path": "input/202605/监测表.xlsx"})

    rc = acq.cmd_merge(_args(tmp_path, "202605"))

    assert rc == 1
    assert "待核对" in capsys.readouterr().out
    assert ledger.read_bytes() == b"ledger-bytes"


def _fetch_args(period, **kw):
    ns = dict(period=period, groups=None, no_copy=False)
    ns.update(kw)
    return argparse.Namespace(**ns)


def _fake_scan(copy_state):
    def scan(period, snapshot=None, esi_root=None, preserve=True):
        return {"period": period, "copy": copy_state,
                "groups": [{"id": "g1", "state": "ok", "title": "第 1 组",
                            "verified": 1, "files": [{"state": "ok"}]}],
                "totals": {"groups": 1, "expected": 1, "verified": 1, "downloaded": 1, "failed": 0}}
    return scan


def test_已并入台账的期次_重下载只补文件不再合并(tmp_path, monkeypatch):
    """票 02「已并入不再改」在 fetch 侧的体现：不再自动建核对副本/合并，如实说明（2026-10-17 反馈）。"""
    _write_state(tmp_path, "202605", {"state": "merged", "path": "out/_acquisition/202605/监测表.xlsx"})
    monkeypatch.setattr(acq.A, "resolve_snapshot", lambda *a, **k: "snapshot-x")
    monkeypatch.setattr(acq.A, "scan", _fake_scan({"state": "merged"}))
    monkeypatch.setattr(acq, "_fetch_steps", lambda p, s: [("g1", ["fake-cmd"])])
    monkeypatch.setattr(acq, "_run", lambda cmd: 0)
    copies = []
    monkeypatch.setattr(acq, "cmd_copy", lambda args: copies.append(args) or 0)

    rc = acq.cmd_fetch(_fetch_args("202605"))

    assert rc == 0
    assert not copies, "已并入台账的期次不该再自动建核对副本/合并"
    st = json.loads((tmp_path / "_acquisition" / "202605.json").read_text(encoding="utf-8"))
    assert st["op"]["state"] == "done"
    assert "下载完成" in st["op"]["note"] and "未再合并" in st["op"]["note"], st["op"]


def test_未并入的期次_重下载照旧建核对副本(tmp_path, monkeypatch):
    _write_state(tmp_path, "202605", {"state": "none", "path": "input/202605/监测表.xlsx"})
    monkeypatch.setattr(acq.A, "resolve_snapshot", lambda *a, **k: "snapshot-x")
    monkeypatch.setattr(acq.A, "scan", _fake_scan({"state": "none"}))
    monkeypatch.setattr(acq, "_fetch_steps", lambda p, s: [("g1", ["fake-cmd"])])
    monkeypatch.setattr(acq, "_run", lambda cmd: 0)
    copies = []
    monkeypatch.setattr(acq, "cmd_copy", lambda args: copies.append(args) or 0)

    rc = acq.cmd_fetch(_fetch_args("202605"))

    assert rc == 0
    assert len(copies) == 1, "没并入的期次要照旧把核对副本建出来"
