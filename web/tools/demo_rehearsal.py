# -*- coding: utf-8 -*-
"""演示彩排：把 10 分钟动线在真实浏览器里走一遍，逐步计时并断言。

用法（先起服务；playwright 在系统 Python 里）：
    & "$env:LOCALAPPDATA\\Programs\\Python\\Python313\\python.exe" web\\tools\\demo_rehearsal.py
    ... demo_rehearsal.py --generate    # 把「真实生成」那一步也走一遍（约 20 秒，会重跑当期流水线）
    ... demo_rehearsal.py --base http://127.0.0.1:8080

这个脚本**不写任何数据**：补录只填不保存，签单只看不点（签单会留下记录，由演示人自己决定）。
加 --generate 才会真的跑一次流水线（产物确定性一致，是既有验收步骤）。
"""

import argparse
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]        # wenheng/
ENV = ROOT / "server" / ".env"

STEPS: list[tuple[str, str, float, str]] = []             # (步骤, 判据说明, 秒, OK/FAIL)
FAILED: list[str] = []
PAGE_ERRORS: list[str] = []


def check(name: str, ok: bool, detail: str = "", t0: float | None = None) -> None:
    secs = (time.time() - t0) if t0 else 0.0
    STEPS.append((name, detail, secs, "OK" if ok else "FAIL"))
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--generate", action="store_true", help="把真实生成也走一遍（约 20 秒）")
    ap.add_argument("--shot", default="", help="截图目录（可选）")
    args = ap.parse_args()
    B = args.base.rstrip("/")

    m = re.search(r"^WENHENG_USER=(.*)$", ENV.read_text(encoding="utf-8"), re.M)
    p = re.search(r"^WENHENG_PASS=(.*)$", ENV.read_text(encoding="utf-8"), re.M)
    if not m or not p:
        print("读不到 server/.env 里的演示账号"); return 2
    U, P = m.group(1).strip(), p.group(1).strip()

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True,
                               args=["--use-gl=angle", "--enable-unsafe-swiftshader"])
        pg = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1).new_page()
        pg.on("pageerror", lambda e: PAGE_ERRORS.append(str(e)))

        t = time.time()
        pg.goto(B + "/login", wait_until="networkidle")
        pg.fill("input[name=username]", U); pg.fill("input[name=password]", P)
        pg.click("button[type=submit]"); pg.wait_for_load_state("networkidle")
        check("① 登录", "工作台" in pg.inner_text("body"), "", t)

        # ② 生成台：第一屏就回答「我现在该做什么」
        t = time.time()
        pg.goto(B + "/app/", wait_until="networkidle"); pg.wait_for_timeout(1200)
        txt = pg.inner_text("main")
        check("② 生成台首屏有焦点块与三步条", "生成" in txt and ("取数贴表" in txt), "", t)

        if args.generate:
            t = time.time()
            pg.evaluate("() => { const x=[...document.querySelectorAll('button')].find(e=>e.innerText.includes('生成')); x && x.click(); }")
            for _ in range(120):
                pg.wait_for_timeout(1000)
                if "已出稿" in pg.inner_text("main") or "完成" in pg.inner_text("main"):
                    break
            check("②b 真实生成跑完（约 20 秒）", "已出稿" in pg.inner_text("main"),
                  f"{time.time()-t:.0f} 秒")

        # ③ 报告屏：读数带 / 对勘 / 朱批 / 图册
        t = time.time()
        pg.goto(B + "/app/?view=report", wait_until="networkidle"); pg.wait_for_timeout(2000)
        vals = pg.eval_on_selector_all(".readout .v", "e => e.map(x=>x.innerText.trim())")
        txt = pg.inner_text("main")
        check("③ 读数带是真实数字", vals[:4] == ["995", "130", "14", "274"], " / ".join(vals), t)
        check("③ 数字体检通过", "54 项核对全部通过" in txt)
        check("③ 对勘分区 + 待补 + 图册都在", "对勘分区" in txt and "待你补" in txt and "图册" in txt)

        # ④ 分析台：分节解读 + 数字防护盾
        t = time.time()
        pg.goto(B + "/app/?view=analysis", wait_until="networkidle"); pg.wait_for_timeout(1200)
        pg.evaluate("() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.includes('生成解读')); b && b.click(); }")
        pg.wait_for_timeout(4000)
        arts = pg.eval_on_selector_all("article", "e => e.length")
        shields = pg.eval_on_selector_all(".pill", "e => e.filter(x=>x.innerText.includes('盾')).length")
        check("④ 分节解读 + 数字防护盾", arts >= 5 and shields >= 5, f"{arts} 节 / {shields} 盾", t)

        # ⑤ 审核台：只读核对（🔴 签单是写操作，脚本不替你签——
        #    2026-09-23 踩过：旧版这里点了「钤印签单」，后端闸门当时已改成
        #    「勾选知悉即可签」，于是真写进了一条签单记录，只能按设计路径撤回。
        #    要现场签单，由演示人自己点。）
        t = time.time()
        pg.goto(B + "/app/?view=review", wait_until="networkidle"); pg.wait_for_timeout(2000)
        txt = pg.inner_text("main")
        inputs = pg.eval_on_selector_all("input[type=text]", "e => e.length")
        check("⑤ 在线填 16 处待补录", inputs == 16 and "待补录 16 处" in txt, f"{inputs} 个框", t)
        check("⑤ 签单区说明了会绑指纹",
              "指纹" in txt and "钤印签单" in txt, "（脚本不点它）")

        # ⑥ 台账
        t = time.time()
        pg.goto(B + "/app/?view=ledger", wait_until="networkidle"); pg.wait_for_timeout(1500)
        rows = pg.eval_on_selector_all("table tbody tr", "e => e.length")
        check("⑥ 台账 19 张表", rows == 19, f"{rows} 行", t)

        # ⑦ 陈列馆
        t = time.time()
        pg.goto(B + "/app/shelf/", wait_until="networkidle"); pg.wait_for_timeout(2500)
        books = pg.eval_on_selector_all("#shelfRail > *", "e => e.length")
        check("⑦ 陈列馆出册位 + 回工作台入口", books >= 4, f"{books} 册位", t)

        # ⑧ 救场卡：八态都能直接打开，且都标明「这不是真实状态」
        t = time.time()
        ok_n = 0
        for st in ["empty", "ready", "running", "done", "fail-ledger", "fail-other", "stalled", "signed"]:
            pg.goto(f"{B}/app/?demo={st}", wait_until="networkidle"); pg.wait_for_timeout(900)
            body = pg.inner_text("body")
            if "演示模式" in body and "这不是真实状态" in body:
                ok_n += 1
        check("⑧ 八个救场状态都可用且如实标注", ok_n == 8, f"{ok_n}/8", t)

        if args.shot:
            d = pathlib.Path(args.shot); d.mkdir(parents=True, exist_ok=True)
            for st in ["ready", "running", "done", "fail-ledger"]:
                pg.goto(f"{B}/app/?demo={st}", wait_until="networkidle"); pg.wait_for_timeout(800)
                pg.screenshot(path=str(d / f"demo-{st}.png"), full_page=False)
            print(f"  截图已存 → {d}")

        check("全程零页面报错", not PAGE_ERRORS, "; ".join(PAGE_ERRORS[:2]))
        b.close()

    total = sum(s for _, _, s, _ in STEPS)
    print("\n—— 机器耗时（不含讲解）——")
    for name, detail, secs, st in STEPS:
        if secs >= 0.3:
            print(f"  {secs:5.1f}s  {st:4}  {name}")
    print(f"  合计 {total:.1f}s；失败 {len(FAILED)} 项")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
