# -*- coding: utf-8 -*-
"""历史期次复跑：用现行台账复现过去某一期的报告内容（用于可行性验证/对样）。

用法：
    .venv\\Scripts\\python.exe src\\rerun_history.py 202605

产出（out/<期次>_复现/）：
    table2.csv            大表现值（22 学科 × 11 列）
    overview_facts.json   概述全部数字事实
    texts_preview.json    句骨架全文
    province.json         T19 省域表（源＝ESI 原始包机构总表）
    matrix.json           T20 矩阵表（源＝InCites **该期对应快照**）
    charts/               99 张图（截至该期）
    报告初稿_<期次>（复现）.docx
    red_slots.json / 红色件清单.md

⚠ 两个「不在台账里」的数据源（省域表 / 矩阵表）**必须按被复现的期次算**：
  省域表读 `ESI数据/<该期>/`，矩阵表读 `SNAP_MAP[该期]` 登记的那份 InCites 快照。
  2026-09-20 之前本脚本没接这两步 → 复现稿的 T19/T20 数据区整片空白，
  而「当期稿」（`run_pipeline`）是满的 —— 两份稿看起来只是"期次不同"，
  实际差着两张表。现在两边共用 `extract_*.write_json`，口径不再分叉。

说明：顶尖论文清单为台账外人工贴入，复现稿沿用母版清单（不随期重出）；
      与当期原件的机器 diff 由 backtest 执行。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import charts  # noqa: E402
import compute  # noqa: E402
import fill_docx  # noqa: E402
import parse_ledger  # noqa: E402
import sentences  # noqa: E402


def main(period, ledger_path="input/202607/监测表.xlsx", out_root="out"):
    out_dir = pathlib.Path(out_root) / f"{period}_复现"
    print(f"[1/5] 解析台账 → {out_dir}")
    # 先撤上版成品再重出（与 run_pipeline 同一口径，可回滚）——
    # 否则一次中途失败的复现会留下「新表格 + 旧报告」，而页面上没有任何警报。
    moved = parse_ledger.quarantine_final_products(out_dir)
    if moved:
        print(f"      已撤下上版成品：{'、'.join(moved)}")
    ok = parse_ledger.main(ledger_path, out_dir)
    if not ok:
        print("警告：断言非全绿，继续（复跑目的为对样）")

    wide, ni, nc, thr = compute.load_wide(str(out_dir))
    filled = [c for c in wide["total_cites"].columns if wide["total_cites"][c].notna().any()]
    if period not in filled:
        raise SystemExit(f"台账无 {period} 期数据（有效期次：{filled[0]}..{filled[-1]}）")
    prev = [c for c in filled if c < period][-1]
    print(f"[2/5] 复现当期={period} 上期={prev}")

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

    print(f"[3/5] 图表渲染（截至该期）")
    n = charts.render_all(ledger_dir=str(out_dir), end_period=period)

    # ---- 省域表 T19 / 矩阵表 T20：都不在台账里，且都**按被复现的期次**算 ----
    # 这两步与 run_pipeline 共用 write_json，口径不会分叉。
    # 缺 ESI 包 / 该期未登记 InCites 快照时降级跳过（服务器上没有 数据与复现/）。
    print("[4/5] 省域表 T19 + 学科×高校矩阵 T20")
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

    print("[5/5] 母版替换 → 复现报告初稿")
    docx = fill_docx.main(
        ledger_dir=str(out_dir),
        out_path=out_dir / f"报告初稿_{period}（复现）.docx",
        period_override=period,
    )
    print(f"完成：{docx}")
    return docx


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "202605"
    main(p)
