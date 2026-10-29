# -*- coding: utf-8 -*-
"""tools/red_tiers.py 的用例。

含「不写 out/」两条：默认只打 stdout；显式 `--out out/...` 必须被拒。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import red_tiers as RT
from _guard_registry import skip_unless

REPO = pathlib.Path(__file__).resolve().parent.parent


def _write_slots(out_root: pathlib.Path, period: str, slots: list[dict]) -> pathlib.Path:
    d = out_root / period
    d.mkdir(parents=True, exist_ok=True)
    p = d / "red_slots.json"
    p.write_text(json.dumps(slots, ensure_ascii=False), encoding="utf-8")
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
    monkeypatch.setattr(RT, "OUT_ROOT", root)
    return root


def _sample() -> list[dict]:
    return [
        {"location": "T01/r1c0", "old": "", "new": "植物与动物学", "source": "table2.csv"},
        {"location": "T19/r2c1", "old": "", "new": "154", "source": "province.json"},
        {"location": "T20/r1c云大", "old": "", "new": "Y", "source": "matrix.json"},
        {"location": "T01/r5c0", "old": "", "new": "[图] x.png", "source": "charts/x.png"},
        {"location": "T01/表头", "old": "", "new": "学科", "source": "table2.csv"},
        {"location": "正文/p2", "old": "", "new": "本期……", "source": "sentences.py"},
        {"location": "正文/图片行距", "old": "", "new": "单倍行距", "source": "格式"},
        {"location": "T17/r0c1", "old": "5", "new": "（清除母版残留文本）", "source": "母版清理"},
        {"location": "T05/r0c0", "old": "", "new": "[图] Physics/cites.png", "source": "charts/"},
        {"location": "封面/年月", "old": "", "new": "2026年9月", "source": "期次参数"},
    ]


# ---------------------------------------------------------------- 正常路径
def test_three_tiers_split(fake_out, capsys):
    _write_slots(fake_out, "202609", _sample())
    assert RT.main(["--period", "202609", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)["202609"]
    by = {t["tier"]: t for t in rep["tiers"]}
    assert rep["total"] == 10
    # 核心 = T01/T19/T20 且无 [图]
    assert by["核心"]["count"] == 3
    assert [p["prefix"] for p in by["核心"]["prefixes"]] == ["T01", "T19", "T20"]
    # 次要 = 图(2) + 格式(1) + 清除母版(1)
    assert by["次要"]["count"] == 4
    # 支持 = 表头 + 正文段 + 封面
    assert by["支持"]["count"] == 3
    assert sum(t["count"] for t in rep["tiers"]) == rep["total"]
    assert sum(t["share"] for t in rep["tiers"]) == pytest.approx(1.0)


def test_markdown_has_order_and_counts(fake_out, capsys):
    _write_slots(fake_out, "202609", _sample())
    assert RT.main(["--period", "202609"]) == 0
    out = capsys.readouterr().out
    assert "# 红件分级 · 202609 期" in out
    assert "核心逐格" in out and "支持抽段" in out and "次要抽样" in out
    assert "合计建议核验" in out
    # 核心全查：建议条数 = 核心条数
    assert "本期待核 3 格，**全查（100%）**" in out


def test_support_header_always_full(tmp_path):
    """支持级里表头再多，建议核验条数也不低于表头条数。"""
    slots = [{"location": f"T0{i}/表头", "new": "学科", "source": "a.csv"} for i in range(5, 9)]
    slots.append({"location": "正文/p1", "new": "……", "source": "s.py"})
    rep = RT.analyse(slots)
    sup = {t["tier"]: t for t in rep["tiers"]}["支持"]
    assert sup["headers"] == 4
    assert sup["plan_count"] >= 4


def test_tier_of_rules():
    assert RT.tier_of({"location": "T01/r1c0", "new": "1"}) == RT.TIER_CORE
    assert RT.tier_of({"location": "T19/r1c0", "new": "1"}) == RT.TIER_CORE
    assert RT.tier_of({"location": "T20/r1c云大", "new": "Y"}) == RT.TIER_CORE
    # 图不看前缀：T01 的图也是次要
    assert RT.tier_of({"location": "T01/r9c9", "new": "[图] a.png"}) == RT.TIER_MINOR
    assert RT.tier_of({"location": "T02/r1c0", "new": "x"}) == RT.TIER_SUPPORT
    assert RT.tier_of({"location": "T01/表头", "new": "学科"}) == RT.TIER_SUPPORT


# ---------------------------------------------------------------- 字段缺失
def test_missing_fields_default_to_support(fake_out, capsys):
    _write_slots(fake_out, "202609", [{}, {"new": ""}, {"location": ""}, "不是字典"])
    assert RT.main(["--period", "202609", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)["202609"]
    assert rep["total"] == 3
    assert {t["tier"]: t["count"] for t in rep["tiers"]}["支持"] == 3


def test_empty_slots(fake_out, capsys):
    _write_slots(fake_out, "202609", [])
    assert RT.main(["--period", "202609"]) == 0
    assert "总槽位 0 条" in capsys.readouterr().out


def test_missing_artifact_returns_3(fake_out, capsys):
    (fake_out / "202601").mkdir()
    assert RT.main(["--period", "202601"]) == 3
    assert "缺少" in capsys.readouterr().err


# ---------------------------------------------------------------- 不写 out/
def test_default_writes_nothing(fake_out, capsys):
    _write_slots(fake_out, "202609", _sample())
    before = _snapshot(fake_out)
    RT.main(["--period", "202609"])
    RT.main(["--period", "202609", "--json"])
    assert _snapshot(fake_out) == before


def test_out_into_out_dir_is_refused(fake_out, tmp_path, capsys):
    _write_slots(fake_out, "202609", _sample())
    before = _snapshot(fake_out)
    code = RT.main(["--period", "202609", "--out", str(fake_out / "202609" / "分级.md")])
    assert code == 3
    assert "不许写进 out/" in capsys.readouterr().err
    assert _snapshot(fake_out) == before


def test_out_to_tmp_works(fake_out, tmp_path, capsys):
    _write_slots(fake_out, "202609", _sample())
    target = tmp_path / "tmp" / "分级.md"
    assert RT.main(["--period", "202609", "--out", str(target)]) == 0
    assert "已写入" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8").startswith("# 红件分级 · 202609 期")


# ---------------------------------------------------------------- 真实期次探针
def test_real_period_probe():
    p = REPO / "out" / "202609" / "red_slots.json"
    if not p.is_file():
        skip_unless("out/202609/red_slots.json 不存在（产物不入库，属正常）",
                    lambda: p.is_file())
    rep = RT.analyse(RT.load_slots(p))
    assert rep["total"] > 0
    assert sum(t["count"] for t in rep["tiers"]) == rep["total"]
