# -*- coding: utf-8 -*-
"""每期一条命令：台账 xlsx → 规整数据 + 断言 + 大表 + 概述 + 预测 + 图表 + 报告初稿。

用法（新一期数据贴进台账后）：
    .venv\\Scripts\\python.exe src\\run_pipeline.py input\\202609\\监测表.xlsx

流程：
  1. parse_ledger  解析 22 sheet → out/<当期>/（含 meta.json 断言清单）
  2. compute       自动定位当期/上期 → 大表 22×11 + 概述全部数字事实
  3. forecast      预测回测（InCites+差值校准，验收 MAPE<5%）
  4. charts        98 张期次图（16 学科 × 6 + 2 概览）
  5. fill_docx     母版原地替换 → 报告初稿 + 红色件清单
"""
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pandas as pd  # noqa: E402

import charts  # noqa: E402
import compute  # noqa: E402
import fill_docx  # noqa: E402
import forecast  # noqa: E402
import parse_ledger  # noqa: E402


def _emit(step, name, status, detail=""):
    """结构化进度事件（演示站 SSE 用）：仅当设置 WENHENG_PROGRESS_FILE 时写 JSONL。"""
    path = os.environ.get("WENHENG_PROGRESS_FILE")
    if not path:
        return
    rec = {"ts": time.strftime("%H:%M:%S"), "step": step, "name": name,
           "status": status, "detail": detail, "elapsed": round(time.time() - _T0, 1)}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


_T0 = time.time()


def main(ledger_path, out_root="out", run_backtest=False):
    t0 = _T0
    p = pathlib.Path(ledger_path)

    _emit("parse", "解析台账", "start", f"输入：{p.name}")
    print(f"[1/5] 解析台账: {p}")
    ledger = parse_ledger.load_ledger(p)
    ok, report = parse_ledger.run_assertions(ledger)
    P, Q = parse_ledger._latest_periods(ledger)
    out_dir = pathlib.Path(out_root) / P
    parse_ledger.write_outputs(ledger, p, out_dir)
    n_fail = sum(1 for s, _ in report if s == "FAIL")
    print(f"      当期={P} 上期={Q} 断言={'全绿' if ok else f'{n_fail} 项 FAIL'} → {out_dir}")
    _emit("parse", "解析台账", "done" if ok else "warn",
          f"当期 {P} · 上期 {Q} · 机器断言 {'全绿' if ok else f'{n_fail} 项未过'}")

    _emit("compute", "计算大表与概述", "start")
    print("[2/5] 计算大表 + 概述事实")
    wide, ni, nc, thr = compute.load_wide(str(out_dir))
    t2 = compute.build_table2(wide, ni, nc, thr, P, Q)
    t2.to_csv(out_dir / "table2.csv", index=False, encoding="utf-8-sig")
    ynd = pd.read_parquet(f"{out_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = pd.read_parquet(f"{out_dir}/wide/top_total.parquet").set_index("period")["total"].to_dict()
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, P, Q)
    (out_dir / "overview_facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"      大表 22×11 → {out_dir}/table2.csv；概述事实 → overview_facts.json")
    _emit("compute", "计算大表与概述", "done", "大表 22 学科 × 11 列 · 概述 11 项数字事实")

    _emit("forecast", "预测回测", "start")
    print("[3/5] 预测回测（InCites+差值校准）")
    mape = forecast.main(ledger_dir=str(out_dir), out_dir=str(out_dir))
    print(f"      整体 MAPE = {mape:.2f}%（验收线 <5%）")
    _emit("forecast", "预测回测", "done", f"整体 MAPE {mape:.2f}%（验收线 <5%）")

    _emit("charts", "图表渲染", "start")
    print("[4/5] 图表渲染（16 学科 × 6 + 概览 3）")
    n_charts = charts.render_all(ledger_dir=str(out_dir))
    _emit("charts", "图表渲染", "done", f"{n_charts} 张图 · 16 学科 × 6 + 概览")

    _emit("docx", "母版替换", "start")
    print("[5/5] 母版替换 → 报告初稿")
    docx_path = fill_docx.main(ledger_dir=str(out_dir))
    _emit("docx", "母版替换", "done", f"报告初稿 + 红色件清单：{pathlib.Path(docx_path).name}")

    log = {
        "period": P, "prev": Q, "input": str(p),
        "assertions_ok": ok, "assertions_fail": n_fail,
        "predict_mape_overall": round(float(mape), 3),
        "charts": n_charts,
        "docx": str(docx_path),
        "artifacts": {
            "ledger_long": str(out_dir / "ledger_long.parquet"),
            "table2_csv": str(out_dir / "table2.csv"),
            "overview_facts": str(out_dir / "overview_facts.json"),
            "forecast_report": str(out_dir / "预测回测报告.md"),
            "red_slots": str(out_dir / "red_slots.json"),
            "red_list_md": str(out_dir / "红色件清单.md"),
        },
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (out_dir / "run_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=1))
    _emit("done", "完成", "done" if ok else "warn",
          f"全链路 {log['elapsed_sec']} 秒 · 断言 {'全绿' if ok else f'{n_fail} 项 FAIL'} · "
          f"大表 22×11 · 图 {n_charts} 张 · MAPE {mape:.2f}%")

    if run_backtest:
        import backtest
        ref = os.environ.get("WENHENG_REFERENCE_DOCX") or r"..\云南大学原报告\云南大学学科信息参考2026年第4期.docx"
        print(f"[附加] 金样回测：{ref}")
        backtest.main(ref, str(out_dir))
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = args[0] if args else r"input\202607\监测表.xlsx"
    sys.exit(main(src, run_backtest="--backtest" in sys.argv))
