# -*- coding: utf-8 -*-
"""`server/artifacts.py`：产物读取的唯一面（回落 / 守卫 / 计数 / kind）。"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import artifacts                                       # noqa: E402


class TestReadJson:
    def test_正常对象(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"k": 1}), encoding="utf-8")
        assert artifacts.read_json(f) == {"k": 1}

    def test_坏文件与错形状都None(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{oops", encoding="utf-8")
        arr = tmp_path / "arr.json"
        arr.write_text("[1,2]", encoding="utf-8")
        assert artifacts.read_json(bad) is None
        assert artifacts.read_json(arr) is None
        assert artifacts.read_json(tmp_path / "missing.json") is None

    def test_BOM容错(self, tmp_path):
        f = tmp_path / "bom.json"
        f.write_text(json.dumps({"k": "v"}), encoding="utf-8-sig")
        assert artifacts.read_json(f) == {"k": "v"}


class TestReadSlots:
    def test_只收dict行(self, tmp_path):
        (tmp_path / "red_slots.json").write_text(
            json.dumps([{"location": "正文/p1"}, "junk", 3, None]), encoding="utf-8")
        assert artifacts.read_slots(tmp_path) == [{"location": "正文/p1"}]

    def test_缺与坏都空表(self, tmp_path):
        assert artifacts.read_slots(tmp_path) == []
        (tmp_path / "red_slots.json").write_text("{oops", encoding="utf-8")
        assert artifacts.read_slots(tmp_path) == []
        (tmp_path / "red_slots.json").write_text(json.dumps({"not": "list"}),
                                                 encoding="utf-8")
        assert artifacts.read_slots(tmp_path) == []


class TestReadOthers:
    def test_meta与facts缺坏都空dict(self, tmp_path):
        assert artifacts.read_meta(tmp_path) == {} and artifacts.read_facts(tmp_path) == {}

    def test_table2读取与容错(self, tmp_path):
        (tmp_path / "table2.csv").write_text(
            "discipline,papers\nChemistry,3\n", encoding="utf-8-sig")
        assert artifacts.read_table2(tmp_path) == [{"discipline": "Chemistry", "papers": "3"}]
        assert artifacts.read_table2(tmp_path / "nope") == []


class TestAssertionCounts:
    def test_严格口径_非PASS皆fail(self):
        meta = {"assertions": [["PASS", "ok"], ["FAIL", "x"], [], None, "junk", ["PASS"]]}
        assert artifacts.assertion_counts(meta) == {"total": 6, "fail": 4}

    def test_非list给零(self):
        assert artifacts.assertion_counts({"assertions": {"a": 1}}) == {"total": 0, "fail": 0}
        assert artifacts.assertion_counts({}) == {"total": 0, "fail": 0}
        assert artifacts.assertion_counts(None) == {"total": 0, "fail": 0}


class TestSlotFields:
    def test_full优先新键_预览只用截断键(self):
        slot = {"new": "截断…", "new_full": "完整正文", "old": "旧", "old_full": "旧全文"}
        assert artifacts.slot_text(slot, "new") == "完整正文"
        assert artifacts.slot_text(slot, "new", full=False) == "截断…"
        assert artifacts.slot_text(slot, "old") == "旧全文"
        assert artifacts.slot_text({"new": "x"}, "old_full") == ""

    def test_kind以图占位为准(self):
        assert artifacts.slot_kind({"location": "正文/图片行距", "new": "1 个图段改为…"}) == "text"
        assert artifacts.slot_kind({"location": "正文/1%接近度图", "new": "[图] charts/x.png"}) == "chart"
        assert artifacts.slot_kind({"location": "T01/r1c2", "new": "3"}) == "cell"
        assert artifacts.slot_kind({"location": "封面/期数", "new": "2026年第4期"}) == "text"
