# -*- coding: utf-8 -*-
"""tools/trace_coverage.py 的用例。

规矩：
  · 造假数据全部落在 `tmp_path`，**不读真实 `out/`**（唯一例外是本文件末尾那条
    真实期次探针：产物缺席时登记跳过理由 + 复核探针）。
  · 每个工具都要证明「默认不写 out/」——这里用运行前后目录快照对比来断言。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import trace_coverage as TC
from _guard_registry import skip_unless

REPO = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 夹具
def _write_slots(out_root: pathlib.Path, period: str, slots: list[dict]) -> pathlib.Path:
    d = out_root / period
    d.mkdir(parents=True, exist_ok=True)
    p = d / "red_slots.json"
    p.write_text(json.dumps(slots, ensure_ascii=False), encoding="utf-8")
    return p


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    """(相对路径 → (字节数, mtime_ns))，用来断言「一个字节都没动」。"""
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture()
def fake_out(tmp_path, monkeypatch):
    root = tmp_path / "out"
    root.mkdir()
    monkeypatch.setattr(TC, "OUT_ROOT", root)
    return root


# ---------------------------------------------------------------- 正常路径
def test_coverage_100_percent_returns_0(fake_out, capsys):
    _write_slots(fake_out, "202609", [
        {"location": "T01/r1c0", "old": "", "new": "植物与动物学", "source": "table2.csv"},
        {"location": "T01/r1c1", "old": "", "new": "69/↑1", "source": "table2.csv"},
    ])
    code = TC.main(["--period", "202609"])
    out = capsys.readouterr().out
    assert code == 0
    assert "覆盖率" in out and "100.0%" in out
    assert "每一格都能指回一份数据文件" in out


def test_four_kinds_and_exit_code_2(fake_out, capsys):
    """四类各来一条：覆盖率 25% → 退出码 2，但报告仍完整打印。"""
    _write_slots(fake_out, "202609", [
        {"location": "T01/r1c0", "new": "14", "source": "table2.csv"},
        {"location": "封面/年月", "new": "2026年9月", "source": "期次参数"},
        {"location": "T03/r0c0", "new": "[图] Chemistry/cites.png", "source": "charts/Chemistry"},
        {"location": "正文/p1", "new": "……", "source": "sentences.py（句骨架+数字槽）"},
    ])
    code = TC.main(["--period", "202609", "--json"])
    payload = json.loads(capsys.readouterr().out)
    rep = payload["202609"]
    assert code == 2
    assert rep["total"] == 4 and rep["traceable"] == 1
    assert rep["coverage"] == pytest.approx(0.25)
    assert rep["kinds"] == {"数据文件": 1, "期次参数": 1, "图表引用": 1, "其它": 1}


def test_classify_rules():
    """规则表本身：后缀 / 数据目录 / #行号 / 全角括号注释都算数据文件。"""
    assert TC.classify({"new": "1", "source": "province.json"}) == TC.KIND_DATA
    assert TC.classify({"new": "1", "source": "ESI数据/202609/institutions.xlsx#r979（Cites 列）"}) \
        == TC.KIND_DATA
    assert TC.classify({"new": "Y", "source": "数据覆盖2016-2026.06.30/Physics.xlsx（被引 9093）"}) \
        == TC.KIND_DATA
    assert TC.classify({"new": "154", "source": "ESI数据/202609/ 22 学科榜中出现 14/22 次"}) \
        == TC.KIND_DATA
    assert TC.classify({"new": "2026年9月", "source": "期次参数（上期月份）"}) == TC.KIND_PERIOD
    assert TC.classify({"new": "[图] a.png", "source": "table2.csv"}) == TC.KIND_CHART
    assert TC.classify({"new": "x", "source": "charts/Physics/rank_pct.png"}) == TC.KIND_CHART
    assert TC.classify({"new": "x", "source": "report_forecast（V1 推荐模型）"}) == TC.KIND_OTHER


def test_prefix_coverage_table(fake_out, capsys):
    _write_slots(fake_out, "202609", [
        {"location": "T19/r2c0", "new": "云南大学", "source": "extract_province（人工原件）"},
        {"location": "T19/r2c1", "new": "154", "source": "ESI数据/202609/institutions.xlsx#r979"},
        {"location": "T20/r1c云大", "new": "Y", "source": "数据覆盖/Physics.xlsx"},
    ])
    TC.main(["--period", "202609", "--json"])
    rep = json.loads(capsys.readouterr().out)["202609"]
    rows = {r["prefix"]: r for r in rep["by_prefix"]}
    assert rows["T19"] == {"prefix": "T19", "total": 2, "traceable": 1, "ratio": 0.5}
    assert rows["T20"]["ratio"] == 1.0


# ---------------------------------------------------------------- 字段缺失
def test_missing_fields_do_not_crash(fake_out, capsys):
    """缺 source / 缺 new / 缺 location / 非 dict 混进来，一律降级为「其它」。"""
    path = _write_slots(fake_out, "202609", [{"location": "T01/r1c0"}])
    path.write_text(json.dumps([
        {"location": "T01/r1c0"},
        {"source": "table2.csv"},
        {"new": "", "source": ""},
        "不是字典",
    ], ensure_ascii=False), encoding="utf-8")
    code = TC.main(["--period", "202609", "--json"])
    rep = json.loads(capsys.readouterr().out)["202609"]
    assert code == 2  # 只有 1 条能追溯 → 覆盖率 33%
    assert rep["total"] == 3  # 非 dict 被丢弃
    assert rep["kinds"] == {"数据文件": 1, "期次参数": 0, "图表引用": 0, "其它": 2}
    # 缺 location 的两条归到「（空）」；其中带 table2.csv 的那条仍算可追溯
    assert {"prefix": "（空）", "total": 2, "traceable": 1, "ratio": 0.5} in rep["by_prefix"]


def test_empty_slots_gives_zero_coverage(fake_out, capsys):
    _write_slots(fake_out, "202609", [])
    code = TC.main(["--period", "202609", "--json"])
    rep = json.loads(capsys.readouterr().out)["202609"]
    assert code == 2
    assert rep["total"] == 0 and rep["coverage"] == 0.0


def test_missing_artifact_returns_3(fake_out, capsys):
    (fake_out / "202601").mkdir()
    code = TC.main(["--period", "202601"])
    cap = capsys.readouterr()
    assert code == 3
    assert "缺少" in cap.out and "缺产物" in cap.err


def test_all_scans_every_period(fake_out, capsys):
    _write_slots(fake_out, "202603", [{"location": "T01/r1c0", "new": "1", "source": "a.csv"}])
    _write_slots(fake_out, "202609", [{"location": "T01/r1c0", "new": "1", "source": "sentences.py"}])
    code = TC.main(["--all", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["202603"]["coverage"] == 1.0
    assert payload["202609"]["coverage"] == 0.0


# ---------------------------------------------------------------- 不写 out/
def test_never_writes_out_root(fake_out, capsys):
    """只读工具：跑完 out/ 下文件集合、大小、mtime 全部不变，也没多出文件。"""
    _write_slots(fake_out, "202609", [
        {"location": "T01/r1c0", "new": "1", "source": "table2.csv"},
    ])
    before = _snapshot(fake_out)
    TC.main(["--period", "202609"])
    TC.main(["--period", "202609", "--json"])
    TC.main(["--all"])
    assert _snapshot(fake_out) == before


# ---------------------------------------------------------------- 真实期次探针
def test_real_period_probe():
    """唯一允许碰真实 out/ 的地方：只验「能读、能算」，不锁死数字。"""
    p = REPO / "out" / "202609" / "red_slots.json"
    if not p.is_file():
        skip_unless("out/202609/red_slots.json 不存在（产物不入库，属正常）",
                    lambda: p.is_file())
    rep = TC.analyse(TC.load_slots(p))
    assert rep["total"] > 0
    assert 0.0 <= rep["coverage"] <= 1.0
    assert sum(rep["kinds"].values()) == rep["total"]
