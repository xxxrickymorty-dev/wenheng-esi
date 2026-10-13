# -*- coding: utf-8 -*-
"""一键清洗：两路数据 → 动态监测表当期列（母本），顺序跑三个既有工具。

    1. extract_esi.py             —— ESI 侧：云大ESI排名 / 总被引·论文数·TOP论文（在榜学科）/ 篇均三列 / ESI被引阈值
                                   （+ 在榜学科进/退事件核对，--append-events 可落表）
    2. extract_incites.py         —— InCites 侧：新·国际/国内排名、CNCI、未进榜学科的总被引·论文数·篇均、Q1-Q4
    3. derive_proximity.py        —— 派生列《接近度》＝总被引 ÷ ESI 1% 阈值（两列都已由 1/2 步写好）
    4. extract_1permille.py       —— 千分之一被引阈值（ESI 各科榜取位）
    5. extract_forecast_pairs.py  —— 《实际与预测差值》三行（incite/esi/差值）＝方法B 预测的校准语料

五个工具各自带「冲突拒写 + 自动备份 + zip 级 XML 自检」，本脚本只做顺序调度与汇总。

用法（wenheng/ 下，.venv 的 python）：
    python tools\\clean_ledger.py 202609                    # 只预览（不写）：三个工具各自的比对/预览
    python tools\\clean_ledger.py 202609 --out tmp\\x.xlsx   # 产出「清洗后副本」（原台账不动）
    python tools\\clean_ledger.py 202609 --write            # 顺序写台账（每个工具各自备份）

    （--snapshot / --esi-root 透传给 extract_incites / extract_1permille；--skip-permille 跳过第 3 步）
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / "Scripts" / "python.exe"
LEDGER = REPO.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
SCRATCH = REPO / "tmp"


def run(script: str, args: list) -> int:
    p = REPO / "tools" / script
    if not p.exists():
        p = REPO / "src" / script                               # 1‰ 工具在 src/
    cmd = [str(PY), str(p), *[str(a) for a in args]]
    print(f"\n===== {p.relative_to(REPO)} {' '.join(str(a) for a in args)} =====", flush=True)
    return subprocess.call(cmd, cwd=str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser(description="一键清洗：ESI + InCites → 台账")
    ap.add_argument("period")
    ap.add_argument("--snapshot", default=None, help="InCites 快照目录名（默认走 SNAP_MAP 登记）")
    ap.add_argument("--esi-root", default=None, help="ESI 原始包根目录（默认 ../数据与复现/ESI数据）")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--out", default=None, help="产出清洗后副本（原台账不动）")
    ap.add_argument("--write", action="store_true", help="顺序写台账")
    ap.add_argument("--skip-permille", action="store_true", help="跳过第 3 步（千分之一被引阈值）")
    ap.add_argument("--append-events", action="store_true",
                    help="在榜核对发现新进/退出时，追加到《学科进入时间》（默认只提示不写）")
    args = ap.parse_args()
    period = args.period
    ledger = pathlib.Path(args.ledger)

    incites_args = [period]
    if args.snapshot:
        incites_args += ["--snapshot", args.snapshot]
    if args.esi_root:
        incites_args += ["--esi-root", args.esi_root]
    perm_args = [period]
    if args.esi_root:
        perm_args += ["--data-root", args.esi_root]
    esi_args = [period] + (["--esi-root", args.esi_root] if args.esi_root else [])
    if args.append_events:
        esi_args += ["--append-events"]
    pairs_args = [period] + (["--snapshot", args.snapshot] if args.snapshot else [])
    if args.esi_root:
        pairs_args += ["--esi-root", args.esi_root]
    prox_args = [period]

    if not (args.out or args.write):
        r1 = run("extract_esi.py", esi_args)
        r2 = run("extract_incites.py", incites_args)
        rp = run("derive_proximity.py", prox_args)
        r3 = 0 if args.skip_permille else run("extract_1permille.py", perm_args)
        r4 = run("extract_forecast_pairs.py", pairs_args)
        bad = [n for n, r in (("extract_esi", r1), ("extract_incites", r2), ("derive_proximity", rp),
                              ("extract_1permille", r3), ("extract_forecast_pairs", r4)) if r]
        print(f"\n[预览汇总] 非零退出：{bad or '无'}")
        return 1 if bad else 0

    if args.write:
        rs = [run("extract_esi.py", esi_args + ["--write"]),
              run("extract_incites.py", incites_args + ["--write"]),
              run("derive_proximity.py", prox_args + ["--ledger", str(ledger), "--write"])]
        if not args.skip_permille:
            rs.append(run("extract_1permille.py", perm_args + ["--ledger", str(ledger), "--write"]))
        rs.append(run("extract_forecast_pairs.py", pairs_args + ["--ledger", str(ledger), "--write"]))
        bad = [r for r in rs if r]
        print(f"\n[写台账汇总] 非零退出 {len(bad)} 个（每个工具各自备份在 归档/台账备份/）")
        return 1 if bad else 0

    # 副本模式：链路走 tmp 工作目录，最后复制到 --out
    wd = SCRATCH / f"_clean_{period}"
    wd.mkdir(parents=True, exist_ok=True)
    step1, step2, step2b, step3, step4 = (wd / "1_esi.xlsx", wd / "2_incites.xlsx",
                                          wd / "2b_proximity.xlsx", wd / "3_permille.xlsx",
                                          wd / "4_pairs.xlsx")
    rs = [run("extract_esi.py", esi_args + ["--ledger", str(ledger), "--out", str(step1)]),
          run("extract_incites.py", incites_args + ["--ledger", str(step1), "--out", str(step2)]),
          run("derive_proximity.py", prox_args + ["--ledger", str(step2), "--out", str(step2b)])]
    last = step2b
    if not args.skip_permille:
        shutil.copy2(step2b, step3)
        rs.append(run("extract_1permille.py", perm_args + ["--ledger", str(step3), "--write"]))
        last = step3
    shutil.copy2(last, step4)
    rs.append(run("extract_forecast_pairs.py",
                  pairs_args + ["--ledger", str(step4), "--out", str(step4)]))
    last = step4
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(last, out)
    bad = [r for r in rs if r]
    print(f"\n[副本汇总] 非零退出：{bad or '无'}；清洗后副本 → {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
