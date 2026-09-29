# -*- coding: utf-8 -*-
"""历史期次补跑：用现行台账生成过去某一期的报告（用于可行性验证/对样）。

用法：
    .venv\\Scripts\\python.exe src\\rerun_history.py 202605
    .venv\\Scripts\\python.exe src\\rerun_history.py 202605 "..\\数据与复现\\云大全学科排名、阈值动态检测表.xlsx"

产出（out/<期次>/）：
    table2.csv / overview_facts.json / texts_preview.json
    province.json（T19，源＝ESI 原始包）· matrix.json（T20，源＝InCites 该期快照）
    预测回测报告.md + forecast_backtest_*（预测回测，与当期同口径）
    charts/（期次图截至该期 + 预测图 4 张）· forecast_charts.json
    报告初稿_<期次>（试排）.docx
    red_slots.json / 红色件清单.md

⚠ 三个「台账之外」的部分必须按被补跑期算，否则会拿台账当期顶替：
  省域表读 `ESI数据/<该期>/`；矩阵表读 `SNAP_MAP[该期]` 登记的 InCites 快照；
  预测窗口截到该期（`report_forecast` 按目录名/override 自动处理，2026-09-29 修——
  此前本脚本压根不跑预测，补跑稿没有「三、趋势预测」的图与文）。

说明：顶尖论文清单为台账外人工贴入，补跑稿沿用母版清单（不随期重出）；
      与人工原件的机器 diff 由 backtest / compare_reports 执行。

命名（2026-09-29 rick 定）：产物按正常期次输出 `out/<期次>/`，不再加 `_复现`
后缀；报告文件名统一「报告初稿_<期次>（试排）.docx」。meta.json 的
`period_current/period_prev` 按被补跑期写回——facts 接口与报告屏的「本期」
标注都读它（不写回会把台账当期显示成本期）。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import charts  # noqa: E402
import compute  # noqa: E402
import fill_docx  # noqa: E402
import forecast  # noqa: E402
import parse_ledger  # noqa: E402
import report_forecast  # noqa: E402
import sentences  # noqa: E402

DEFAULT_LEDGER = r"..\数据与复现\云大全学科排名、阈值动态检测表.xlsx"


def main(period, ledger_path=DEFAULT_LEDGER, out_root="out"):
    out_dir = pathlib.Path(out_root) / period
    print(f"[1/6] 解析台账 → {out_dir}")
    # 先撤上版成品再重出（与 run_pipeline 同一口径，可回滚）——
    # 否则一次中途失败的补跑会留下「新表格 + 旧报告」，而页面上没有任何警报。
    moved = parse_ledger.quarantine_final_products(out_dir)
    if moved:
        print(f"      已撤下上版成品：{'、'.join(moved)}")
    ok = parse_ledger.main(ledger_path, out_dir)
    if not ok:
        print("警告：断言非全绿，继续（补跑目的为对样）")

    wide, ni, nc, thr = compute.load_wide(str(out_dir))
    filled = [c for c in wide["total_cites"].columns if wide["total_cites"][c].notna().any()]
    if period not in filled:
        raise SystemExit(f"台账无 {period} 期数据（有效期次：{filled[0]}..{filled[-1]}）")
    prev = [c for c in filled if c < period][-1]
    print(f"[2/6] 补跑当期={period} 上期={prev}")

    # meta.json 的「当期/上期」按被补跑期写回：facts 接口与报告屏「本期」标注读它
    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["period_current"] = period
    meta["period_prev"] = prev
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str),
                         encoding="utf-8")

    t2 = compute.build_table2(wide, ni, nc, thr, period, prev)
    t2.to_csv(out_dir / "table2.csv", index=False, encoding="utf-8-sig")
    ynd = __import__("pandas").read_parquet(f"{out_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = __import__("pandas").read_parquet(f"{out_dir}/wide/top_total.parquet").set_index("period")["total"].to_dict()
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, period, prev)
    (out_dir / "overview_facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    texts = sentences.build(facts, period, prev)
    (out_dir / "texts_preview.json").write_text(
        json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"      大表/概述/句骨架 → {out_dir}")

    print("[3/6] 预测回测（InCites + 差值校准）")
    mape = forecast.main(ledger_dir=str(out_dir), out_dir=str(out_dir))
    print(f"      整体 MAPE = {mape:.2f}%（验收线 <5%）")

    print("[4/6] 图表渲染（截至该期）")
    n = charts.render_all(ledger_dir=str(out_dir), end_period=period)
    print(f"      {n} 张期次图")

    # ---- 省域表 T19 / 矩阵表 T20：都不在台账里，且都**按被补跑期**算 ----
    # 这两步与 run_pipeline 共用 write_json，口径不会分叉。
    # 缺 ESI 包 / 该期未登记 InCites 快照时降级跳过（服务器上没有 数据与复现/）。
    print("[5/6] 省域表 T19 + 学科×高校矩阵 T20")
    try:
        import extract_province
        pdata = extract_province.write_json(period, out_dir)
        print(f"      省域表：{pdata['n_universities']} 校 × 9 列（ESI 机构总表）")
    except Exception as e:                                       # noqa: BLE001
        print(f"      省域表：跳过（{type(e).__name__}: {e}）")
    try:
        import extract_matrix
        mdata = extract_matrix.write_json(period, out_dir)
        n_cell = sum(1 for r in mdata["matrix"].values() for x in r.values() if x.get("v"))
        print(f"      矩阵表：{len(mdata['matrix'])} 学科 × 11 校 → {n_cell} 格"
              f"（InCites 快照 {mdata['snapshot']}）")
    except Exception as e:                                       # noqa: BLE001
        print(f"      矩阵表：跳过（{type(e).__name__}: {e}）")

    print("[6/6] 预测图（窗口截到该期）+ 母版替换")
    n_fc = report_forecast.generate(out_dir, period_override=period)
    print(f"      预测图：{n_fc} 张 → forecast_charts.json")
    docx = fill_docx.main(
        ledger_dir=str(out_dir),
        out_path=out_dir / f"报告初稿_{period}（试排）.docx",
        period_override=period,
    )
    print(f"完成：{docx}")
    return docx


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "202605"
    led = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LEDGER
    main(p, led)
