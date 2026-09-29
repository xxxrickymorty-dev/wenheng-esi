# -*- coding: utf-8 -*-
"""灵活报告 CLI 入口（与 `run_pipeline.py` / `run_latest.py` 同风格）。

用法（workdir=wenheng）：

    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 cross_compare
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend Engineering

    # 语言润色位（**可选**，默认关）：配了云 + 开 `WENHENG_FLEX_POLISH=1` 才生效。
    # 数字走防护盾（[[n]] 占位 + 校验 + 还原），失败或不可用一律原样回退。
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend --polish
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend --no-polish

    # 写作位（**可选**，默认关）：配了云 + 开 `WENHENG_FLEX_WRITE=1`，把叙述段
    # 按「规则稿＋事实摘要」写成分析体（数字/图表/来源链不动，失败整段回退）。
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 single_trend 化学 --write

    # 列出某期次已生成的分析稿
    .venv\\Scripts\\python.exe src\\run_flexible.py out/202607 --list

意图：`single_trend`（单学科趋势诊断）/ `cross_compare`（多学科横向对比）。
规划后端（D6 收编后）：**规则**（默认，无 LLM）/ 云端模型（配 `WENHENG_AI_*` 才启用，
经 AI 层出网、失败自动回退规则）。旧的 `ollama` / `http` 直连已废弃。

🔴 规则规划**永不调用模型** —— 演示站跑的就是它，
死板与否由 `opinion.descriptive_trend` 的句式分档决定，不靠润色。
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
    disc = argv[2] if len(argv) > 2 and not argv[2].startswith("-") else None
    if intent not in planner.INTENTS:
        print(f"未知意图 {intent!r}；可用：{sorted(planner.INTENTS)}")
        return 2
    # `--polish` / `--no-polish`：语言润色位（可选，需配云；默认关）
    polish = None
    for flag in argv[2:]:
        if flag == "--polish":
            polish = True
        elif flag in ("--no-polish", "--raw"):
            polish = False
    write = "--write" in argv
    r = report.generate(out_dir, intent, disc=disc, polish=polish, write=write)
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
