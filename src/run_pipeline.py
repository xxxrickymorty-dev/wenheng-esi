# -*- coding: utf-8 -*-
"""每期一条命令：台账 xlsx → 规整数据 + 机器断言 + 大表 + 概述事实 + 预测回测。

用法（新一期数据贴进台账后）：
    .venv\\Scripts\\python.exe src\\run_pipeline.py input\\202609\\监测表.xlsx

流程：
  1. parse_ledger  解析 22 sheet → out/<当期>/（含 meta.json 断言清单）
  2. compute       自动定位当期/上期 → 大表 22×11 + 概述全部数字事实
  3. forecast      预测回测（InCites+差值校准，验收 MAPE<5%）
  4. 输出三件套之数据件：out/<当期>/run_log.json（供后续图表/Word 装配层使用）

注：图表重绘与 Word 母版替换（charts.py / fill_docx.py）为 W2 范围；
本入口先把"数据就绪 + 校验 + 数字事实"全链路跑通。
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pandas as pd  # noqa: E402

import compute  # noqa: E402
import forecast  # noqa: E402
import parse_ledger  # noqa: E402


def main(ledger_path, out_root="out", run_backtest=False):
    t0 = time.time()
    p = pathlib.Path(ledger_path)
    print(f"[1/4] 解析台账: {p}")
    ledger = parse_ledger.load_ledger(p)
    ok, report = parse_ledger.run_assertions(ledger)
    P, Q = parse_ledger._latest_periods(ledger)
    out_dir = pathlib.Path(out_root) / P
    parse_ledger.write_outputs(ledger, p, out_dir)
    n_fail = sum(1 for s, _ in report if s == "FAIL")
    print(f"      当期={P} 上期={Q} 断言={'全绿' if ok else f'{n_fail} 项 FAIL'} → {out_dir}")

    print("[2/4] 计算大表 + 概述事实")
    wide, ni, nc, thr = compute.load_wide(str(out_dir))
    t2 = compute.build_table2(wide, ni, nc, thr, P, Q)
    t2.to_csv(out_dir / "table2.csv", index=False, encoding="utf-8-sig")
    ynd = pd.read_parquet(f"{out_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = pd.read_parquet(f"{out_dir}/wide/top_total.parquet").set_index("period")["total"].to_dict()
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, P, Q)
    (out_dir / "overview_facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"      大表 22×11 → {out_dir}/table2.csv；概述事实 → overview_facts.json")

    print("[3/4] 预测回测（InCites+差值校准）")
    mape = forecast.main(ledger_dir=str(out_dir), out_dir=str(out_dir))
    print(f"      整体 MAPE = {mape:.2f}%（验收线 <5%）")

    print("[4/4] 运行日志")
    log = {
        "period": P, "prev": Q, "input": str(p),
        "assertions_ok": ok, "assertions_fail": n_fail,
        "predict_mape_overall": round(float(mape), 3),
        "artifacts": {
            "ledger_long": str(out_dir / "ledger_long.parquet"),
            "table2_csv": str(out_dir / "table2.csv"),
            "overview_facts": str(out_dir / "overview_facts.json"),
            "forecast_report": str(out_dir / "预测回测报告.md"),
        },
        "elapsed_sec": round(time.time() - t0, 1),
        "note": "charts+docx（W2）未接入；数据链路已就绪",
    }
    (out_dir / "run_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=1))

    if run_backtest:
        import backtest
        print("[附加] 第 4 期金样回测")
        backtest.main(r"..\云南大学原报告\云南大学学科信息参考2026年第4期.docx", str(out_dir))
    return 0 if ok else 1


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else r"input\202607\监测表.xlsx"
    sys.exit(main(src))
