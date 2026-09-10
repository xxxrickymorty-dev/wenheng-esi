# -*- coding: utf-8 -*-
"""历史期次复跑：用现行台账复现过去某一期的报告内容（用于可行性验证/对样）。

用法：
    .venv\\Scripts\\python.exe src\\rerun_history.py 202605

产出（out/<期次>_复现/）：
    table2.csv            大表现值（22 学科 × 11 列）
    overview_facts.json   概述全部数字事实
    texts_preview.json    句骨架全文
    charts/               98 张图（截至该期）
    报告初稿_<期次>（复现）.docx
    red_slots.json / 红色件清单.md
说明：省表为台账当前单快照（非历史期），复现稿沿用母版结构（第 5 期骨架），
      与当期原件的机器 diff 需原件进入 云南大学原报告/ 后由 backtest 执行。
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
    print(f"[1/4] 解析台账 → {out_dir}")
    ok = parse_ledger.main(ledger_path, out_dir)
    if not ok:
        print("警告：断言非全绿，继续（复跑目的为对样）")

    wide, ni, nc, thr = compute.load_wide(str(out_dir))
    filled = [c for c in wide["total_cites"].columns if wide["total_cites"][c].notna().any()]
    if period not in filled:
        raise SystemExit(f"台账无 {period} 期数据（有效期次：{filled[0]}..{filled[-1]}）")
    prev = [c for c in filled if c < period][-1]
    print(f"[2/4] 复现当期={period} 上期={prev}")

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

    print("[3/4] 图表渲染（截至该期）")
    n = charts.render_all(ledger_dir=str(out_dir), end_period=period)

    print("[4/4] 母版替换 → 复现报告初稿")
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
