# -*- coding: utf-8 -*-
"""端到端冒烟：台账 → 产物 → 大表 → 概述事实。

分两档：
  · 主链路（默认跑）—— parse → 写产物 → compute。几秒钟，覆盖数据主路径。
  · 全链路（@slow）—— 完整 run_pipeline，含 98 张图表渲染与母版替换，约 1 分钟。

跑全链路：`uv run pytest -m slow`
"""
import json
import re

import pandas as pd
import pytest

import compute
import parse_ledger
import run_pipeline

T2_COLUMNS = [
    "discipline", "rank_cn_change", "papers", "cnci", "total_cites",
    "thr_1pct", "thr_1pct_gap", "thr_1permille", "permille_rank",
    "top_papers", "prox_change",
]


def test_台账到产物主链路(latest_ledger, tmp_path):
    ledger = parse_ledger.load_ledger(latest_ledger)
    ok, _ = parse_ledger.run_assertions(ledger)
    assert ok, "断言闸未过，主链路不应继续"

    P, Q = parse_ledger._latest_periods(ledger)
    out = tmp_path / P
    parse_ledger.write_outputs(ledger, latest_ledger, out)
    assert (out / "ledger_long.parquet").exists(), "未写出 ledger_long.parquet"
    assert (out / "meta.json").exists(), "未写出 meta.json"

    wide, ni, nc, thr = compute.load_wide(str(out))
    t2 = compute.build_table2(wide, ni, nc, thr, P, Q)

    assert len(t2) == 22, f"大表应 22 学科，实得 {len(t2)}"
    assert list(t2.columns) == T2_COLUMNS, f"大表列口径漂移：{list(t2.columns)}"
    assert t2["discipline"].is_unique, "大表学科有重复"

    ynd = pd.read_parquet(out / "wide" / "ynd_rank.parquet").set_index("period")
    top_total = (pd.read_parquet(out / "wide" / "top_total.parquet")
                 .set_index("period")["total"].to_dict())
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, P, Q)

    # 概述数字事实：关键键必须齐全，且数值可序列化（供 fill_docx / 前端消费）
    for key in ("rank_intl_now", "rank_cn_inst_now", "n_disc_1pct",
                "top_papers_now", "best_1permille", "coverage_window", "prev_label"):
        assert key in facts, f"概述缺键 {key}"
    json.dumps(facts, ensure_ascii=False, default=str)      # 不抛异常即通过
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}-\d{4}\.\d{1,2}\.\d{1,2}",
                        facts["coverage_window"]), \
        f"覆盖窗口格式异常：{facts['coverage_window']!r}"
    assert re.fullmatch(r"\d{4}年\d{1,2}月", facts["prev_label"]), \
        f"上期标签格式异常：{facts['prev_label']!r}"
    assert 0 <= facts["n_disc_1pct"] <= 22


@pytest.mark.slow
def test_端到端全链路(latest_ledger, tmp_path):
    """真跑一遍流水线（图表 + 母版替换），确认它能在干净目录里从零产出。"""
    out_root = tmp_path / "out"
    rc = run_pipeline.main(str(latest_ledger), out_root=str(out_root))
    assert rc == 0, "流水线返回非 0（断言未过）"

    ledger = parse_ledger.load_ledger(latest_ledger)
    P, _ = parse_ledger._latest_periods(ledger)
    d = out_root / P

    log = json.loads((d / "run_log.json").read_text(encoding="utf-8"))
    assert log["assertions_ok"] is True
    assert log["charts"] > 0

    for name in ("table2.csv", "overview_facts.json", "red_slots.json",
                 "红色件清单.md", "预测回测报告.md"):
        assert (d / name).exists(), f"缺产物 {name}"
    assert list(d.glob("报告初稿*.docx")), "未生成报告初稿 docx"
