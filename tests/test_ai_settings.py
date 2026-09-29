# -*- coding: utf-8 -*-
"""开关 settings：原子写、审计、读失败语义（SPEC §2.4 / C3）。"""
from __future__ import annotations

import json
import logging
import os
import pathlib

import pytest

import ai
from ai import _settings

FAIL = {"code": "ASSERT_FAIL", "message": "x", "period": "202607",
        "fails": ["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
        "diagnostics": {}}


def _audit(root):
    p = root / "_ai" / "ai_calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


# ============================================================ 原子写 + 审计
def test_set_switch_写文件_审计行_无残留(tmp_path):
    with ai.using(data_root=tmp_path):
        ai.set_switch("diagnose", False, actor="admin")
    p = tmp_path / "_ai" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["caps"]["diagnose"] is False and data["updated"]["by"] == "admin"
    assert not list(p.parent.glob("*.tmp-*")), "原子写不得留下半截 tmp"
    audits = [r for r in _audit(tmp_path) if r["kind"] == "switch"]
    assert len(audits) == 1
    a = audits[0]
    assert a["capability"] == "diagnose" and a["from"] is True and a["to"] is False
    assert a["actor"] == "admin" and a["ts"]


def test_set_switch_仅admin_未知能力(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(PermissionError):
            ai.set_switch("diagnose", False, actor="guest")
        with pytest.raises(PermissionError):
            ai.set_switch("diagnose", False)           # fail-closed guest
        with pytest.raises(ValueError):
            ai.set_switch("占卜", True, actor="admin")
    assert not (tmp_path / "_ai" / "settings.json").exists()
    assert not (tmp_path / "_ai").exists()


def test_写失败时旧设置原样(tmp_path, monkeypatch):
    with ai.using(data_root=tmp_path):
        ai.set_switch("diagnose", False, actor="admin")
    p = tmp_path / "_ai" / "settings.json"
    before = p.read_bytes()

    def boom(src, dst):
        raise OSError("replace 失败")
    monkeypatch.setattr(os, "replace", boom)
    with ai.using(data_root=tmp_path):
        with pytest.raises(OSError):
            ai.set_switch("diagnose", True, actor="admin")
    assert p.read_bytes() == before, "原子写失败不得伤到已生效的配置"
    assert not list(p.parent.glob("*.tmp-*"))


# ============================================================ 读失败语义
def test_读失败回退last_known_good(tmp_path):
    with ai.using(data_root=tmp_path):
        ai.set_switch("diagnose", False, actor="admin")     # 先种一份好配置
        store = _settings.store_for(tmp_path)
        assert store.read()["caps"]["diagnose"] is False
        p = tmp_path / "_ai" / "settings.json"
        p.write_text("{坏掉的 json", encoding="utf-8")
        os.utime(p, (2, 2))
        assert store.read()["caps"]["diagnose"] is False, "读失败沿用 LKG，不 fail-open"


def test_无LKG且文件坏_fail_closed全关(tmp_path, caplog):
    d = tmp_path / "_ai"
    d.mkdir(parents=True)
    (d / "settings.json").write_text("{坏掉的 json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="wenheng.ai"):
        state = _settings.store_for(tmp_path).read()
    assert not any(state["caps"].values()), "无 LKG 的读失败 → 全关，不 fail-open"
    assert caplog.records, "读失败必须留日志"


def test_未配置时默认全开(tmp_path):
    state = _settings.store_for(tmp_path).read()
    assert state["caps"]["diagnose"] is True


def test_每调用读一次_外部改文件立即生效(tmp_path):
    with ai.using(data_root=tmp_path):
        ai.set_switch("diagnose", False, actor="admin")
        assert ai.run("diagnose", "202607", payload={"failure": FAIL},
                      actor="admin").mode == "closed"
    p = tmp_path / "_ai" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["caps"]["diagnose"] = True
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 10))       # 显式推后 mtime，避开时钟粒度
    with ai.using(data_root=tmp_path):
        assert ai.run("diagnose", "202607", payload={"failure": FAIL},
                      actor="admin").mode == "rule", "开关文件变了要立即收敛"
