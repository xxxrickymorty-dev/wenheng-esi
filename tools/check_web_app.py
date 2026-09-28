# -*- coding: utf-8 -*-
r"""端到端：`/app`（React 工作区）在真实浏览器里跑通「登录 → 取数 → 渲染」。

为什么单独一条：`/app` 是 ADR-0001 引入的构建产物（`web/dist`）。它的典型失败模式
——dist 没重新构建、接口 401、基路径写错、外链被断网拦掉——**都不会让 pytest 变红**，
只会在评审现场看到白屏。所以给它一条真实浏览器的端到端路径。

2026-09-27 修：陈列馆一段改用 **guest** 账号（demo 是 admin，进 /app/shelf/ 会被
前端送回工作台，旧断言恒超时），并跟随现版结构——陈列馆首页等 `.home-hero`，
点第一本馆藏后等 `#flipbook`（翻页阅读器宿主）。锚点只认结构，不写死中文值。

2026-09-28 增：工作区与陈列馆各自独立——管理员工作区不再出现陈列馆入口/文案
（断言无 `/app/shelf/` 链接、无「陈列馆」字样）；游客访问 /app/?view=... 必须被
前端送回 `/app/shelf/`。

跑法（playwright 在**系统 Python** 里，不在 `.venv`）：

    .venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8080
    & "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" tools\check_web_app.py

服务不在默认地址时用 `WENHENG_BASE` 覆盖（与 e2e_check.py 同一套约定）：
    $env:WENHENG_BASE="http://127.0.0.1:8099"; & "...\python.exe" tools\check_web_app.py

退出码 0 = 通过；1 = 有断言失败（失败项打印在前）。
"""
import http.cookiejar
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("WENHENG_BASE", "http://127.0.0.1:8080").rstrip("/")
USER, PASS = "demo", "wenheng@2026"
GUEST_USER, GUEST_PASS = "guest", "guest@2026"
SHOT = pathlib.Path(r"C:\Users\damn\AppData\Local\Temp\opencode\wh_app.png")
SHOT_SHELF = pathlib.Path(r"C:\Users\damn\AppData\Local\Temp\opencode\wh_shelf.png")

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def login_cookies(user=USER, password=PASS):
    """走真实表单登录，拿到 session cookie（Starlette SessionMiddleware 签名 cookie）。"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(BASE + "/login").read()
    data = urllib.parse.urlencode({"username": user, "password": password}).encode()
    opener.open(urllib.request.Request(BASE + "/login", data=data)).read()
    return [{"name": c.name, "value": c.value, "domain": "127.0.0.1", "path": "/"}
            for c in cj]


def main():
    from playwright.sync_api import sync_playwright

    cookies = login_cookies()
    check("登录拿到 session cookie", any(c["name"] == "session" for c in cookies))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        # ---- 0) 未登录：/app/** 导航显示「请先登录」页（不跳转，按钮去 /login） ----
        anon_ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        anon = anon_ctx.new_page()
        anon.goto(BASE + "/app/", wait_until="networkidle")
        anon_text = anon.inner_text("body")
        check("未登录 /app/ 显示「请先登录」页",
              "请先登录" in anon_text and "前往登录" in anon_text
              and anon.url.rstrip("/").endswith("/app"), f"url={anon.url}")
        anon.goto(BASE + "/app/shelf/", wait_until="networkidle")
        check("未登录 /app/shelf/ 同样显示「请先登录」页",
              "请先登录" in anon.inner_text("body"), f"url={anon.url}")

        # ---- 1) 首屏 = 工作台（admin） ----
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        problems = []
        page.on("pageerror", lambda e: problems.append("pageerror: " + str(e)))
        page.on("console", lambda m: problems.append("console.error: " + m.text)
                if m.type == "error" else None)

        resp = page.goto(BASE + "/app/", wait_until="networkidle")
        check("GET /app/ → 200", bool(resp) and resp.status == 200,
              f"got {resp.status if resp else '?'}")
        try:
            page.wait_for_selector("nav[aria-label]", timeout=10000)
            check("工作区导航已渲染（nav[aria-label]，不写死具体值）", True)
        except Exception as e:                                       # noqa: BLE001
            check("工作区导航已渲染（nav[aria-label]，不写死具体值）", False, str(e)[:80])
        n_blocks = page.eval_on_selector_all("section, li, article", "els => els.length")
        check("工作台渲染出内容块（section/li/article ≥ 1）", n_blocks >= 1, f"{n_blocks} 块")
        shelf_links = page.eval_on_selector_all('a[href="/app/shelf/"]', "els => els.length")
        check("工作区有陈列馆入口（/app/shelf/ 链接）", shelf_links >= 1, f"{shelf_links} 个")
        body_text = page.inner_text("body")
        check("工作区导航含「陈列馆」", "陈列馆" in body_text)
        page.screenshot(path=str(SHOT))

        # ---- 1b) 管理员进陈列馆（2026-09-28：入口移入工作区导航；看同一份访客投影，不再弹回） ----
        admin_ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        admin_ctx.add_cookies(login_cookies())
        admin_shelf = admin_ctx.new_page()
        admin_shelf_problems = []
        admin_shelf.on("pageerror", lambda e: admin_shelf_problems.append("pageerror: " + str(e)))
        admin_shelf.on("console", lambda m: admin_shelf_problems.append("console.error: " + m.text)
                       if m.type == "error" else None)
        resp3 = admin_shelf.goto(BASE + "/app/shelf/", wait_until="networkidle")
        check("管理员 GET /app/shelf/ → 200", bool(resp3) and resp3.status == 200,
              f"got {resp3.status if resp3 else '?'}")
        try:
            admin_shelf.wait_for_selector(".home-book-item", timeout=15000)
            check("管理员进陈列馆能看到册位（不弹回）", True)
        except Exception as e:                                       # noqa: BLE001
            check("管理员进陈列馆能看到册位（不弹回）", False,
                  f"url={admin_shelf.url} {str(e)[:60]}")
        # 管理员开书应看到全内容册页（数字体检 / 学科大表 / 双路线预测）
        try:
            admin_shelf.click(".home-book-item")
            admin_shelf.wait_for_selector("#flipbook", timeout=15000)
            pages_text = admin_shelf.evaluate(
                "() => document.querySelector('.flip-page-templates')?.textContent ?? ''")
            check("管理员开书含全内容册页（数字体检 / 学科大表 / 双路线预测）",
                  all(token in pages_text for token in ("数字体检", "学科大表", "双路线预测")),
                  f"templates={len(pages_text)} 字")
        except Exception as e:                                       # noqa: BLE001
            check("管理员开书含全内容册页（数字体检 / 学科大表 / 双路线预测）", False, str(e)[:80])

        # ---- 1c) 界面禁用词（票 09）：词表单源 web/src/lib/banned.ts ----
        # 策略：只扫**前端自撰区块**（标题/导语/提示/按钮/空错态等），不扫数据表、日志、
        # 进度明细与带 data-src="backend" 的后端文字——那类内容由后端措辞负责，误报会淹掉真信号。
        def banned_terms():
            src = pathlib.Path(__file__).resolve().parent.parent / "web" / "src" / "lib" / "banned.ts"
            if not src.exists():
                return []
            text = src.read_text(encoding="utf-8")
            block = text.split("string[] = [", 1)[-1].split("]", 1)[0]
            return re.findall(r"'([^']+)'", block)

        terms = banned_terms()
        check("禁用词表可读（banned.ts ≥ 20 条）", len(terms) >= 20, f"{len(terms)} 条")
        AUTHORED = ("h1,h2,h3,p.hint,p.fc-lead,p.lead,button,.pending-box,.banner,.degraded,"
                    "label,summary,.note")
        extract = ("els => els.filter(e => !e.closest('[data-src=backend]'))"
                   ".map(e => e.innerText).join('\\n')")
        hits = {}
        for v in ("workbench", "report", "review", "ledger", "analysis", "forecast",
                  "charts", "reading", "trace", "red", "archive"):
            url = BASE + ("/app/?period=202607" if v == "workbench"
                          else f"/app/?view={v}&period=202607")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            text = page.eval_on_selector_all(AUTHORED, extract)
            found = sorted({x for x in terms if x in text})
            if found:
                hits[v] = found
        check("工作区各页自撰文案无禁用词（只扫标题/导语/提示/按钮等）",
              not hits, str(hits))

        # 自证有效：往自撰区块注入一个禁用词，必须能抓到（再移除）
        page.evaluate("() => { const p = document.createElement('p');"
                      " p.className = 'hint'; p.id = 'banned-canary';"
                      " p.textContent = 'canary run_parse'; document.body.appendChild(p); }")
        canary = sorted({x for x in terms if x in page.eval_on_selector_all(AUTHORED, extract)})
        check("黑名单检查自证有效（注入 run_parse 能抓到）", "run_parse" in canary, str(canary[:3]))
        page.evaluate("() => document.getElementById('banned-canary')?.remove()")

        # ---- 1d) 预测台减负回归（票 13）：路线一套控件 / 打开即出图 / 切路线自动恢复 / 改选亮保存 ----
        # 只读：改选只动内存，不点保存、不写任何数据。
        try:
            page.goto(BASE + "/app/?view=forecast&period=202607", wait_until="domcontentloaded")
            page.wait_for_selector(".fc-band", timeout=20000)
            page.wait_for_selector(".fc-band .fc-seg button", timeout=30000)   # 等模型清单到位（路线控件随之出现）
            n_seg = page.locator(".fc-band .fc-seg button").count()
            n_save = page.locator(".fc-band button.btn.primary").count()
            check("预测台页头带：路线一套控件 + 保存一处", n_seg == 2 and n_save == 1,
                  f"seg={n_seg} save={n_save}")
            page.wait_for_selector(".fc-gal img", timeout=120000)      # 打开即出图（五模型）
            n0 = page.locator(".fc-gal .fc-model").count()
            check("预测台打开即出图（五模型卡）", n0 >= 5, f"{n0} 卡")
            page.click(".fc-band .fc-seg button:nth-child(2)")         # 切到路线 2：应自动重跑
            page.wait_for_selector(".fc-gal img", state="detached", timeout=60000)   # 旧图先撤下
            page.wait_for_selector(".fc-gal img", timeout=120000)                    # 新图自动回来
            page.wait_for_timeout(300)
            n1 = page.locator(".fc-gal .fc-model").count()
            check("切路线后图区自动恢复（不再空图）", n1 >= 5, f"{n1} 卡")
            pick = page.locator(".fc-gal .fc-model .fc-actions .btn.primary").first
            if pick.count():
                pick.click()
                page.wait_for_timeout(250)
                state = page.inner_text(".fc-band-state")
                check("改选后保存带亮起（有未保存改动）",
                      "未保存" in state and not page.is_disabled(".fc-band button.btn.primary"), state)
            else:
                check("改选后保存带亮起（有未保存改动）", False, "没有可改选的模型卡")
        except Exception as e:                                          # noqa: BLE001
            check("预测台减负回归（票 13）", False, str(e)[:100])

        # ---- 2) 陈列馆（/app/shelf/；管理员与游客都看同一份访客投影） ----
        guest_ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        guest_ctx.add_cookies(login_cookies(GUEST_USER, GUEST_PASS))
        guest = guest_ctx.new_page()
        guest_problems = []
        guest.on("pageerror", lambda e: guest_problems.append("pageerror: " + str(e)))
        guest.on("console", lambda m: guest_problems.append("console.error: " + m.text)
                 if m.type == "error" else None)

        guest.goto(BASE + "/app/?view=report", wait_until="domcontentloaded")
        try:
            guest.wait_for_url("**/app/shelf/**", timeout=10000)
            check("游客访问工作区被送回陈列馆", True)
        except Exception:                                            # noqa: BLE001
            check("游客访问工作区被送回陈列馆", False, f"url={guest.url}")

        resp2 = guest.goto(BASE + "/app/shelf/", wait_until="networkidle")
        check("GET /app/shelf/ → 200", bool(resp2) and resp2.status == 200,
              f"got {resp2.status if resp2 else '?'}")
        try:
            guest.wait_for_selector(".home-hero", timeout=10000)
            check("陈列馆首页渲染（.home-hero）", True)
        except Exception as e:                                       # noqa: BLE001
            check("陈列馆首页渲染（.home-hero）", False, str(e)[:80])
        try:
            guest.click(".home-book-item")
            guest.wait_for_selector("#flipbook", timeout=10000)
            n_pages = guest.eval_on_selector_all(".flip-page", "els => els.length")
            check("翻页阅读器打开（#flipbook 带页）", n_pages >= 3, f"{n_pages} 页")
        except Exception as e:                                       # noqa: BLE001
            check("翻页阅读器打开（#flipbook 带页）", False, str(e)[:80])
        guest.screenshot(path=str(SHOT_SHELF))

        # ---- 3) 零报错（覆盖上面几次导航） ----
        check("工作台零 pageerror / console.error", not problems, "; ".join(problems[:3]))
        check("陈列馆（管理员）零 pageerror / console.error", not admin_shelf_problems,
              "; ".join(admin_shelf_problems[:3]))
        check("陈列馆零 pageerror / console.error", not guest_problems,
              "; ".join(guest_problems[:3]))

        browser.close()

    print("结果：" + ("全部通过" if not failures else f"{len(failures)} 项失败：{failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
