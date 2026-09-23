# -*- coding: utf-8 -*-
"""派生列《接近度》 = 总被引 ÷ ESI 1% 阈值（逐学科 × 逐期）。

两列源数据都已在台账里（《总被引》《ESI被引阈值》，本条只是相除），所以本工具不下载任何东西，
只做派生 + 冲突门 + 写回。

口径（2026-09-23 反推验证，逐位一致）：
  · 202607 Chemistry        49394 / 7703 = 6.4123068934181484  ✓
  · 202607 Multidisciplinary  422 / 3354 = 0.12581991651759095 ✓（未进榜学科用 InCites 总被引）
  · 202607 Immunology        1079 / 5414 = 0.19929811599556704 ✓

用法（wenheng/ 下，.venv 的 python）：
    python tools\\derive_proximity.py 202607                  # 预览 + 与台账逐格比对
    python tools\\derive_proximity.py 202609 --out tmp\\x.xlsx # 写副本
    python tools\\derive_proximity.py 202609 --write          # 写台账（自动备份）
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import extract_incites as T                                                    # noqa: E402
import parse_ledger as PL                                                      # noqa: E402

SHEET = "接近度"


def _period_col(g, shared, period):
    h = g.get(1, {})
    return next((cn for cn, v in ((cn, str(T.gtext(g, shared, 1, cn) or "").strip()) for cn in h)
                 if v == period), None)


def collect(led: pathlib.Path, period: str) -> dict:
    """→ {学科: 接近度 或 None}，并返回 (台账现值字典, 冲突列表)。"""
    g_c, sh_c = T.read_grid(led, "总被引")
    g_t, sh_t = T.read_grid(led, "ESI被引阈值")
    g_p, sh_p = T.read_grid(led, SHEET)
    col_c, col_t, col_p = (_period_col(g_c, sh_c, period), _period_col(g_t, sh_t, period),
                           _period_col(g_p, sh_p, period))
    if col_c is None or col_t is None:
        raise SystemExit(f"[缺列] 总被引={col_c} / ESI被引阈值={col_t}（{period}）——先跑前面几步")
    vals, existing, conflicts = {}, {}, []
    for s in PL.DISCIPLINES_EN:
        def row_of(g, sh):
            return next((r for r in sorted(g)
                         if str(T.gtext(g, sh, r, "A") or "").strip() == s), None)

        rn, rn_t = row_of(g_c, sh_c), row_of(g_t, sh_t)
        rn_p = row_of(g_p, sh_p)
        if rn is None or rn_t is None:
            continue
        cites = T._num(T.gtext(g_c, sh_c, rn, col_c))
        thr = T._num(T.gtext(g_t, sh_t, rn_t, col_t))
        vals[s] = (cites / thr) if (cites and thr) else None
        if col_p is not None and rn_p is not None:
            old = T.gtext(g_p, sh_p, rn_p, col_p)
            if old not in (None, ""):
                existing[s] = old
                if vals[s] is not None and not T._eq(old, vals[s]):
                    conflicts.append((s, old, vals[s]))
    return {"vals": vals, "existing": existing, "conflicts": conflicts, "col_p": col_p}


def main() -> int:
    ap = argparse.ArgumentParser(description="派生列《接近度》= 总被引 ÷ ESI阈值")
    ap.add_argument("period")
    ap.add_argument("--ledger", default=str(T.LEDGER))
    ap.add_argument("--out", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    led = pathlib.Path(args.ledger)
    r = collect(led, args.period)
    n_ok = sum(1 for v in r["vals"].values() if v is not None)
    print(f"== {args.period} 接近度：{n_ok} 科可算（期次列={'已有' if r['col_p'] else '将新建'}）")
    for s in sorted(r["vals"], key=lambda x: -(r["vals"][x] or 0))[:6]:
        print(f"    {s}: {r['vals'][s]}")
    if r["conflicts"]:
        print(f"[!] 与台账现有值冲突 {len(r['conflicts'])} 处：")
        for loc in r["conflicts"][:8]:
            print("    ", loc)
        if not args.force:
            print("    → 拒绝写入；确认后 --force")
            return 1
    if r["existing"] and not r["conflicts"]:
        print(f"[✓] 与台账现有值逐格一致（抽查 {len(r['existing'])} 个存量格）")
    if not (args.write or args.out):
        print("\n（预览模式。--out 写副本 / --write 写台账）")
        return 0

    tx = T.LedgerTx(led)
    xml, log = T.plan_wide(tx, SHEET, args.period, r["vals"])
    tx.put_sheet(SHEET, xml)
    T._do_write(tx, led, args, tag=f"派生{args.period}接近度前", preview_log={SHEET: log})
    return 0


if __name__ == "__main__":
    sys.exit(main())
