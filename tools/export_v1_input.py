# -*- coding: utf-8 -*-
"""把台账派生数据导成 ESI_Workflow_Model_V1_Handoff 要求的「标准长表」。

交接包（`ESI_Workflow_Model_V1_Handoff/`）的入口只要一张 CSV 长表：

    学科,期次,总被引,ESI前1%被引阈值,云大国内排名,国内ESI前1%机构数

这四个字段全部能从仓库已有产物派生，不需要馆员手工导表：

    总被引              out/<期次>/wide/total_cites.parquet
    ESI前1%被引阈值      out/<期次>/wide/threshold_1pct.parquet
    云大国内排名         out/<期次>/ledger_long.parquet  source='rank_cn'  metric='rank'
    国内ESI前1%机构数    同上 metric='n_inst_1pct'

用法（在 wenheng/ 下，用 .venv）：

    uv run python tools/export_v1_input.py                     # 8 个潜力学科
    uv run python tools/export_v1_input.py --all               # 全部 22 学科
    uv run python tools/export_v1_input.py --period 202607 \
        --out tmp/v1_std_input.csv

只读台账派生数据，不碰台账原件。学科名用 src/parse_ledger.DISCIPLINES_CN。

⚠️ 交接包里的中文名与仓库不完全一致（`神经科学与行为科学` vs 仓库的
`神经系统科学与行为学`），本脚本以**仓库口径**为准；交接包那份基线表需要同步改名。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.parse_ledger import DISCIPLINES_CN  # noqa: E402

V1_COLUMNS = ["总被引", "ESI前1%被引阈值", "云大国内排名", "国内ESI前1%机构数"]
RANK_SOURCE = "rank_cn"


def load_frames(period: str, out_root: Path):
    """返回 {V1 列名: DataFrame(行=英文名, 列=期次)}。"""
    base = out_root / period
    wide = base / "wide"
    cites = pd.read_parquet(wide / "total_cites.parquet")
    thr = pd.read_parquet(wide / "threshold_1pct.parquet")
    prox = pd.read_parquet(wide / "proximity_1pct.parquet")

    ll = pd.read_parquet(base / "ledger_long.parquet")
    rc = ll[ll["source"] == RANK_SOURCE]
    rank = rc[rc["metric"] == "rank"].pivot_table(index="discipline", columns="period", values="value")
    ninst = rc[rc["metric"] == "n_inst_1pct"].pivot_table(index="discipline", columns="period", values="value")

    frames = {
        "总被引": cites,
        "ESI前1%被引阈值": thr,
        "云大国内排名": rank,
        "国内ESI前1%机构数": ninst,
    }
    return frames, prox


def build_long(frames, subjects, cur_period: str):
    """按学科取四列齐备的期次，拼成长表；返回 (df, 逐学科诊断)。"""
    rows, diag = [], []
    all_periods = set()
    for c in V1_COLUMNS:
        all_periods |= {str(p) for p in frames[c].columns if str(p).isdigit()}
    cand = sorted(all_periods)
    for en in subjects:
        periods, vals = [], []
        for p in cand:
            v, ok = {}, True
            for c in V1_COLUMNS:
                f = frames[c]
                if en not in f.index or p not in f.columns or pd.isna(f.loc[en, p]):
                    ok = False
                    break
                v[c] = float(f.loc[en, p])
            if ok:
                periods.append(p)
                vals.append(v)
        if not periods:
            diag.append({"学科": en, "有效期内": 0, "起始": None, "结束": None, "可用": False})
            continue
        for p, v in zip(periods, vals):
            rows.append({"学科": DISCIPLINES_CN.get(en, en), "期次": p, **v})
        diag.append({
            "学科": en, "有效期内": len(periods), "起始": periods[0], "结束": periods[-1],
            "可用": len(periods) >= 31,  # 交接包门槛 INITIAL_TRAIN_SIZE + 1
        })
    if not rows:
        return pd.DataFrame(columns=["学科", "期次", *V1_COLUMNS]), diag
    return pd.DataFrame(rows), pd.DataFrame(diag)


def main():
    ap = argparse.ArgumentParser(description="导出台账派生数据为 V1 交接包标准长表")
    ap.add_argument("--period", default="202607", help="期次目录名，默认 202607")
    ap.add_argument("--out-root", default=str(REPO / "out"), help="out 目录")
    ap.add_argument("--out", default=None, help="输出 CSV 路径（默认 tmp/v1_std_input_<期次>.csv）")
    ap.add_argument("--all", action="store_true", help="导出全部 22 学科（默认只导被引接近度<1 的潜力学科）")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    frames, prox = load_frames(args.period, out_root)

    if args.all:
        subjects = sorted(frames["总被引"].index)
        scope = "全部学科"
    else:
        if args.period not in prox.columns:
            raise SystemExit(f"proximity_1pct 无 {args.period} 列")
        cur = prox[args.period].dropna()
        subjects = sorted(cur[cur < 1].index)
        scope = f"潜力学科（{args.period} 被引接近度 < 1）"

    df, diag = build_long(frames, subjects, args.period)
    out = Path(args.out) if args.out else REPO / "tmp" / f"v1_std_input_{args.period}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"范围：{scope} → {len(subjects)} 学科")
    print(diag.to_string(index=False))
    usable = int(diag["可用"].sum())
    print(f"\n四列齐备且 ≥31 期：{usable}/{len(subjects)} 学科")
    print(f"写出 {out}  shape={df.shape}")
    if usable < len(subjects):
        print("⚠️ 有学科不足 31 期，交接包会判 FAIL：", diag.loc[~diag["可用"], "学科"].tolist())


if __name__ == "__main__":
    main()
