# -*- coding: utf-8 -*-
"""tools/method_boundary.py 的用例。

除了常规路径，这里专门验两条「不硬造」：
  · 产物缺字段 → 文案出现「（本期无该字段）」，且**不出现**别的期次的数字；
  · 默认不落盘；`--out out/...` 被拒。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import method_boundary as MB
from _guard_registry import skip_unless

REPO = pathlib.Path(__file__).resolve().parent.parent

TABLE2 = (
    "discipline,papers,cnci,total_cites,thr_1pct,thr_1permille,top_papers,"
    "rank_cn_change,thr_1pct_gap,permille_rank,prox_change\n"
    "Chemistry,100,1.5,2000,900,3000,10,5/↑1,500,2.1,↑3.00%\n"
)


def _period(root: pathlib.Path, period: str = "202609") -> pathlib.Path:
    d = root / period
    d.mkdir(parents=True, exist_ok=True)
    return d


def _json(path: pathlib.Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _full_facts(d: pathlib.Path) -> None:
    _json(d / "meta.json", {"period_current": 202609, "period_prev": 202607,
                            "missing": [], "input": "input/台账.xlsx"})
    _json(d / "run_log.json", {
        "period": "202609", "prev": "202607", "input": "input/台账.xlsx",
        "ledger_sha256": "2c53131c88ef373c9838c8b9ab2ab94861a9950665b7dc68078889c22bdf6030",
        "ledger_mutated": False, "assertions_fail": 0, "assertions_ok": True,
        "predict_mape_overall": 1.266, "missing": [],
    })
    _json(d / "overview_facts.json", {"prev_label": "2026年7月",
                                      "coverage_window": "2016.1.1-2026.6.30"})
    _json(d / "province.json", {"universities": {"云南大学": {
        "国内排名": {"v": 154, "src": "ESI数据/202609/institutions.xlsx#r979"},
        "国际排名": {"v": 973, "src": "ESI数据/202609/institutions.xlsx#r979"},
    }}})
    _json(d / "matrix.json", {"period": "202609", "matrix": {
        "化学": {"云大": {"v": "Y", "src": "数据覆盖/Chemistry.xlsx"}},
        "工程学": {"云大": {"v": "81.97%", "src": "数据覆盖/Engineering.xlsx"}},
    }})
    _json(d / "forecast_charts.json", {
        "horizon": 18, "report_subjects": ["分子生物学与遗传学", "物理学"],
        "charts": [{"subject": "物理学", "rolling_mape": 1.83},
                   {"subject": "物理学", "rolling_mape": 1.64}],
    })
    (d / "forecast_backtest_summary.csv").write_text(
        "discipline,metric,mean,count\n"
        "Chemistry,cites,1.5,16\nPhysics,cites,2.5,16\n", encoding="utf-8")
    (d / "table2.csv").write_text(TABLE2, encoding="utf-8")
    _json(d / "red_slots.json", [
        {"location": "T01/r1c0", "new": "化学", "source": "table2.csv"},
        {"location": "T01/r1c1", "new": "1", "source": "table2.csv"},
        {"location": "T19/r2c0", "new": "云南大学", "source": "extract_province（人工原件）"},
    ])
    (d / "红色件清单.md").write_text(
        "# 红色件清单 · 202609 期\n\n## 仍为手工的槽位（红色件中的【手工：…】）\n"
        "- 目录页码（需 Word 分页后人工填）\n- 省级对比数据\n\n## 说明\n- 不算条目\n",
        encoding="utf-8")


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture()
def fake_out(tmp_path, monkeypatch):
    root = tmp_path / "out"
    root.mkdir()
    monkeypatch.setattr(MB, "OUT_ROOT", root)
    return root


# ---------------------------------------------------------------- 正常路径
def test_all_sections_and_facts_from_artifacts(fake_out, capsys):
    d = _period(fake_out)
    _full_facts(d)
    assert MB.main(["--period", "202609"]) == 0
    out = capsys.readouterr().out
    for name in MB.SECTIONS:
        assert name in out
    assert "# 方法与边界说明 · 202609 期" in out
    # 期次口径来自 run_log / overview
    assert "上一期 202607" in out and "2026年7月" in out
    assert "2016.1.1-2026.6.30" in out
    assert "`2c53131c88ef…`" in out
    # 三档值的边界：原值 / 派生 / 预测
    assert "原值：papers、cnci、total_cites" in out
    assert "派生：rank_cn_change" in out
    assert "派生值" in out and "T20 矩阵表" in out
    assert "外推 18 期" in out
    assert "1.266%" in out
    # 计数全部来自产物：3 条槽位
    assert "共 3 条槽位" in out


def test_manual_items_parsed_from_red_list(fake_out, capsys):
    d = _period(fake_out)
    _full_facts(d)
    MB.main(["--period", "202609"])
    out = capsys.readouterr().out
    assert "目录页码（需 Word 分页后人工填）" in out
    assert "省级对比数据" in out
    assert "不算条目" not in out          # 「## 说明」小节不混进来
    assert "2 项" in out


def test_unregistered_column_is_surfaced(fake_out, capsys):
    """口径变了要看得见：表头里多出一列，必须单列「未登记性质」。"""
    d = _period(fake_out)
    _full_facts(d)
    (d / "table2.csv").write_text(TABLE2.replace("prox_change", "prox_change,新列_x"),
                                  encoding="utf-8")
    MB.main(["--period", "202609"])
    out = capsys.readouterr().out
    assert "未登记性质（需补 `COLUMN_KIND`）：新列_x" in out


# ---------------------------------------------------------------- 字段缺失
def test_empty_period_uses_placeholder_only(fake_out, capsys):
    """一个产物都没有：四节照出，全是占位，且不出现任何别处的数字。"""
    _period(fake_out)
    assert MB.main(["--period", "202609"]) == 0
    out = capsys.readouterr().out
    for name in MB.SECTIONS:
        assert name in out
    assert MB.MISSING in out
    assert "1.266" not in out          # 真实现实里的 MAPE，不该凭空出现
    assert "2016.1.1" not in out       # 覆盖区间同理
    assert "721" not in out


def test_partial_facts_missing_only_that_field(fake_out, capsys):
    """只给 overview：上一期有、覆盖区间有，台账与预测仍走占位。"""
    d = _period(fake_out)
    _json(d / "overview_facts.json", {"prev_label": "2026年7月",
                                      "coverage_window": "2016.1.1-2026.6.30"})
    _json(d / "run_log.json", {"prev": "202607"})
    MB.main(["--period", "202609"])
    out = capsys.readouterr().out
    assert "上一期 202607（产物记为「2026年7月」）" in out
    assert f"台账路径{MB.MISSING}" in out
    assert "1.266" not in out


def test_slots_with_empty_new_are_listed(fake_out, capsys):
    d = _period(fake_out)
    _full_facts(d)
    _json(d / "red_slots.json", [
        {"location": "T01/r1c0", "new": "", "source": "table2.csv"},
        {"location": "T19/r2c0", "new": "  ", "source": "province.json"},
    ])
    MB.main(["--period", "202609"])
    out = capsys.readouterr().out
    assert "落空的槽位" in out and "T01/r1c0" in out and "T19/r2c0" in out


def test_missing_period_returns_3(fake_out, capsys):
    assert MB.main(["--period", "202601"]) == 3
    assert "缺少" in capsys.readouterr().err


# ---------------------------------------------------------------- 不写 out/
def test_default_writes_nothing(fake_out, capsys):
    d = _period(fake_out)
    _full_facts(d)
    before = _snapshot(fake_out)
    MB.main(["--period", "202609"])
    assert _snapshot(fake_out) == before


def test_out_into_out_dir_is_refused(fake_out, capsys):
    d = _period(fake_out)
    _full_facts(d)
    before = _snapshot(fake_out)
    assert MB.main(["--period", "202609", "--out", str(d / "说明.md")]) == 3
    assert "不许写进 out/" in capsys.readouterr().err
    assert _snapshot(fake_out) == before


def test_out_to_tmp_works(fake_out, tmp_path, capsys):
    d = _period(fake_out)
    _full_facts(d)
    target = tmp_path / "tmp" / "说明.md"
    assert MB.main(["--period", "202609", "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("# 方法与边界说明 · 202609 期")
    assert "已写入" in capsys.readouterr().out


# ---------------------------------------------------------------- 真实期次探针
def test_real_period_probe():
    d = REPO / "out" / "202609"
    if not (d / "overview_facts.json").is_file():
        skip_unless("out/202609/overview_facts.json 不存在（产物不入库，属正常）",
                    lambda: (d / "overview_facts.json").is_file())
    text = MB.build("202609", MB.collect(d))
    for name in MB.SECTIONS:
        assert name in text
