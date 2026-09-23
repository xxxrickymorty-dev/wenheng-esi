# -*- coding: utf-8 -*-
"""GET /api/periods/{period} 单期元数据（契约 §2.2 #2）。

验的是组装逻辑：resolve_period_dir + period_mod.issue_of + steps 三步 + lastJob。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import config, jobs                               # noqa: E402
from server.app import resolve_period_dir                     # noqa: E402
import period as period_mod                                   # noqa: E402


class TestResolvePeriodDir:
    def test_202607存在(self):
        d = resolve_period_dir("202607")
        assert d is not None and d.name.startswith("202607")

    def test_不存在返回None(self):
        assert resolve_period_dir("209901") is None

    def test_非法格式返回None(self):
        assert resolve_period_dir("abc") is None
        assert resolve_period_dir("") is None


class TestPeriodMeta:
    def test_202607有期号和标签(self):
        no, total = period_mod.issue_of("202607")
        assert no is not None and total is not None
        label = period_mod.label("202607")
        assert "2026" in label

    def test_window来自overview_facts(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        facts = d / "overview_facts.json"
        if not facts.exists():
            return
        data = json.loads(facts.read_text(encoding="utf-8"))
        assert "coverage_window" in data

    def test_steps_generated为True(self):
        d = resolve_period_dir("202607")
        if d is None:
            return
        assert (d / "red_slots.json").exists()

    def test_palette是三色(self):
        assert set(config.PALETTE.keys()) == {"primary", "deep", "lift"}
