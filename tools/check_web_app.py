# -*- coding: utf-8 -*-
r"""端到端：`/app`（React 工作区）在真实浏览器里跑通「登录 → 取数 → 渲染」。

为什么单独一条：`/app` 是 ADR-0001 引入的构建产物（`web/dist`）。它的典型失败模式
——dist 没重新构建、接口 401、基路径写错、外链被断网拦掉——**都不会让 pytest 变红**，
只会在评审现场看到白屏。所以给它一条真实浏览器的端到端路径。

2026-09-24 重写：按现版两屏结构（工作台 + 陈列馆 `#/app/shelf/`）。
旧版断言挂在 9-22 骨架版（期次列表 + GSAP）上，现版首屏是工作台、全仓已无 gsap 引用，
旧断言恒失败——别再按"列表 + 动画"查，按 stable 锚点查：
  工作台：nav[aria-label="工作台"]；陈列馆：#coverArt / #flipbook。

跑法（playwright 在**系统 Python** 里，不在 `.venv`）：

    .venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8080
    & "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" tools\check_web_app.py

服务不在默认地址时用 `WENHENG_BASE` 覆盖（与 e2e_check.py 同一套约定）：
    $env:WENHENG_BASE="http://127.0.0.1:8099"; & "...\python.exe" tools\check_web_app.py

⚠ 锚点只认**结构**、不写死中文值：2026-09-24 实踩——写 `nav[aria-label="工作台"]`
  时实际值已改叫「工作区」，选择器恒 0 命中；`#coverArt` 在详情面板里初始隐藏，
  首屏可见的是 `#flipbook`。改锚点前先跑一遍，别凭记忆写。

退出码 0 = 通过；1 = 有断言失败（失败项打印在前）。
"""
import http.cookiejar
import os
import pathlib
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("WENHENG_BASE", "http://127.0.0.1:8080").rstrip("/")
USER, PASS = "demo", "wenheng@2026"
SHOT = pathlib.Path(r"C:\Users\damn\AppData\Local\Temp\opencode\wh_app.png")

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def login_cookies():
    """走真实表单登录，拿到 session cookie（Starlette SessionMiddleware 签名 cookie）。"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(BASE + "/login").read()
    data = urllib.parse.urlencode({"username": USER, "password": PASS}).encode()
    opener.open(urllib.request.Request(BASE + "/login", data=data)).read()
    return [{"name": c.name, "value": c.value, "domain": "127.0.0.1", "path": "/"}
            for c in cj]


def main():
    cookies = login_cookies()
    check("登录拿到 session cookie", any(c["name"] == "session" for c in cookies))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        problems = []
        page.on("pageerror", lambda e: problems.append("pageerror: " + str(e)))
        page.on("console", lambda m: problems.append("console.error: " + m.text)
                if m.type == "error" else None)

        # ---- 1) 首屏 = 工作台 ----
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
        page.screenshot(path=str(SHOT), full_page=False)

        # ---- 2) 陈列馆（G 的体验，挂在 /app/shelf/） ----
        resp2 = page.goto(BASE + "/app/shelf/", wait_until="networkidle")
        check("GET /app/shelf/ → 200", bool(resp2) and resp2.status == 200,
              f"got {resp2.status if resp2 else '?'}")
        try:
            page.wait_for_selector("#flipbook, #shelfView", timeout=10000)
            check("陈列馆渲染（书台/书架可见）", True)
        except Exception as e:                                       # noqa: BLE001
            check("陈列馆渲染（书台/书架可见）", False, str(e)[:80])

        # ---- 3) 零报错（覆盖上面两次导航） ----
        check("零 pageerror / console.error", not problems, "; ".join(problems[:3]))

        browser.close()

    print("结果：" + ("全部通过" if not failures else f"{len(failures)} 项失败：{failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
