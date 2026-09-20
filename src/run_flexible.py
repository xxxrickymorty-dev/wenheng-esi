# -*- coding: utf-8 -*-
"""灵活报告 CLI 入口（与 `run_pipeline.py` / `run_latest.py` 同风格）。

用法（workdir=wenheng）：

    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend rule
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 cross_compare rule
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend rule Engineering

    # 切模型后端（本机 Ollama；不可用会自动回退 rule，不报错）
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend ollama

    # 列出某期次已生成的分析稿
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 --list

意图：`single_trend`（单学科趋势诊断）/ `cross_compare`（多学科横向对比）。
后端：`rule`（默认，无 LLM）/ `ollama` / `http`。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from flexible import planner, report  # noqa: E402


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    out_dir = argv[0]
    if "--list" in argv:
        for r in report.list_reports(out_dir):
            m = r.get("meta") or {}
            print(f"  {r['intent']:16} {r['title']:12} "
                  f"后端={m.get('backend', '?'):6} 图={m.get('n_charts', '?')} "
                  f"→ {r['path']}")
        return 0
    intent = argv[1] if len(argv) > 1 else "single_trend"
    backend = argv[2] if len(argv) > 2 else None
    disc = argv[3] if len(argv) > 3 else None
    if intent not in planner.INTENTS:
        print(f"未知意图 {intent!r}；可用：{sorted(planner.INTENTS)}")
        return 2
    r = report.generate(out_dir, intent, backend=backend, disc=disc)
    p = r["plan"]
    print(f"[灵活报告] {planner.INTENTS[intent]} → {r['report']}")
    print(f"  规划后端：{p['backend']}"
          + (f"（{p['fallback_reason']}）" if p.get("fallback_reason") else ""))
    print(f"  选中：{r['selected']}")
    print(f"  产出图 {r['n_charts']} 张；自检 {'通过 ✅' if r['check']['pass'] else '未通过 ❌'}")
    t = r["check"]["trace"]
    print(f"  数字可回溯：{t['ok']}/{t['checked']}"
          + (f"（异常 {t['bad']}）" if t["bad"] else ""))
    return 0 if r["check"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
