# -*- coding: utf-8 -*-
"""只读跑一次审计预检，取「交签前拦截的存疑项」真实数字（不写回 out/）。"""
import io, pathlib, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO = pathlib.Path(__file__).resolve().parent.parent   # wenheng/
for sub in ("src", "tools"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from agent import audit

OUT = REPO / "out" / "202607"
LED = REPO / "out" / "_acquisition" / "202607" / "监测表.xlsx"   # 202607 当期核对副本
led = LED if LED.exists() else None
print("台账:", led)

rec = audit.run_audit(OUT, ledger=led)
print("\n总判定:", rec.get("verdict") or rec.get("overall"))
print("keys:", list(rec))
for k, v in rec.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v)} 条")
    elif isinstance(v, dict):
        print(f"  {k}: {v}")
    else:
        print(f"  {k}: {v}")

print("\n===== 渲染稿 =====")
print(audit.render_md(rec))
