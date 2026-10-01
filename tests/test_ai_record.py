# -*- coding: utf-8 -*-
"""Recorder：`ai_calls.jsonl` 唯一写口（路径解析 / 调用记录 / 开关审计 / 失败不抛）。"""
import json
import pathlib

import ai
from ai import _record


def _rows(path):
    p = pathlib.Path(path)
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _call(rec, **over):
    kw = dict(capability="diagnose", mode="rule", backend="rule", fallback=None,
              shield={"checked": 2, "passed": 2}, text_protected="共 [[1]] 项",
              egress_items=1, egress_bytes=10, elapsed_ms=5)
    kw.update(over)
    return rec.call(**kw)


class Test_Recorder:
    def test_调用记录落期次目录并返回记录号(self, tmp_path):
        rec = _record.Recorder(tmp_path, period="202607", actor="system")
        rid = _call(rec)
        assert rid and rid.startswith("ai-diagnose-")
        rows = _rows(tmp_path / "202607" / "ai_calls.jsonl")
        assert len(rows) == 1
        r = rows[0]
        assert r["record_id"] == rid and r["kind"] == "call"
        assert r["actor"] == "system" and r["period"] == "202607"
        assert r["egress"] == {"items": 1, "bytes": 10} and r["shield"] == {"checked": 2, "passed": 2}

    def test_无期次落_ai目录(self, tmp_path):
        _call(_record.Recorder(tmp_path, period="", actor="admin"))
        assert (tmp_path / "_ai" / "ai_calls.jsonl").is_file()

    def test_for_period_吃using覆盖(self, tmp_path):
        with ai.using(data_root=tmp_path):
            rid = _call(_record.Recorder.for_period("202607", actor="admin"))
        assert rid
        assert _rows(tmp_path / "202607" / "ai_calls.jsonl")[0]["record_id"] == rid

    def test_写失败返回None不抛(self, tmp_path):
        # 用文件占住 `_ai/`，父目录建不出来；写失败不得抛。
        (tmp_path / "_ai").write_text("x", encoding="utf-8")
        assert _call(_record.Recorder(tmp_path)) is None

    def test_开关审计落_ai且kind为switch(self, tmp_path):
        rec = _record.Recorder(tmp_path, actor="admin")
        assert rec.switch(capability="diagnose", from_=True, to=False) is True
        rows = _rows(tmp_path / "_ai" / "ai_calls.jsonl")
        assert len(rows) == 1
        assert rows[0]["kind"] == "switch" and rows[0]["from"] is True
        assert rows[0]["to"] is False and rows[0]["actor"] == "admin"

    def test_数据根缺省是仓库out(self):
        assert _record.data_root().name == "out"
        assert _record.DEFAULT_DATA_ROOT == _record.data_root()
