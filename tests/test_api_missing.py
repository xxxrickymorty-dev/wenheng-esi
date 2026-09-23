# -*- coding: utf-8 -*-
"""结构化失败 missing（契约 §2.3）。

run_assertions 返回 (ok, report, missing)，missing 是 [{sheet, column, note}]。
全链路：parse_ledger -> meta.json -> run_log.json -> job dict -> GET /api/jobs/{id}。
"""
import json
import sys
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import parse_ledger                                           # noqa: E402


class TestMissing结构:
    def test_run_assertions返回三元组(self, latest_ledger):
        ledger = parse_ledger.load_ledger(latest_ledger)
        ok, report, missing = parse_ledger.run_assertions(ledger)
        assert isinstance(ok, bool)
        assert isinstance(report, list)
        assert isinstance(missing, list)

    def test_missing每项有sheet_column_note(self, latest_ledger):
        ledger = parse_ledger.load_ledger(latest_ledger)
        _ok, _report, missing = parse_ledger.run_assertions(ledger)
        for m in missing:
            assert "sheet" in m
            assert "column" in m
            assert "note" in m

    def test_pass时missing为空(self, latest_ledger):
        ledger = parse_ledger.load_ledger(latest_ledger)
        ok, _report, missing = parse_ledger.run_assertions(ledger)
        if ok:
            assert missing == []

    def test_fail时missing非空(self, latest_ledger):
        ledger = parse_ledger.load_ledger(latest_ledger)
        ok, _report, missing = parse_ledger.run_assertions(ledger)
        if not ok:
            assert len(missing) > 0

    def test_write_outputs写missing到meta(self, latest_ledger, tmp_path):
        ledger = parse_ledger.load_ledger(latest_ledger)
        ok, _meta = parse_ledger.write_outputs(ledger, latest_ledger, tmp_path)
        meta_file = tmp_path / "meta.json"
        assert meta_file.exists()
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        assert "missing" in data, "meta.json 缺 missing 字段"
        assert isinstance(data["missing"], list)
        if ok:
            assert data["missing"] == []
