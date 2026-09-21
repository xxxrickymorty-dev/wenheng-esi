# -*- coding: utf-8 -*-
r"""端到端：`/app`（React 工作区）在真实浏览器里跑通「登录 → 取数 → 渲染」。

为什么单独一条：`/app` 是 ADR-0001 引入的构建产物（`web/dist`）。它的典型失败模式
——dist 没重新构建、接口 401、基路径写错、外链被断网拦掉——**都不会让 pytest 变红**，
只会在评审现场看到白屏。所以给它一条真实浏览器的端到端路径。

跑法（playwright 在**系统 Python** 里，不在 `.venv`）：

    .venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8080
    & "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" tools\check_web_app.py

退出码：0 = 通过；1 = 有断言失败（失败项打印在前）。
"""
import http.cookiejar
import pathlib
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8080"
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

        page.goto(BASE + "/app/", wait_until="networkidle")
        page.wait_for_selector("li", timeout=10000)
        items = page.eval_on_selector_all("li", "els => els.map(e => e.innerText)")
        check("期次列表已渲染（≥1 项）", len(items) >= 1, f"{len(items)} 项")
        check("首项带期号与中文标签",
              bool(items) and "期" in items[0] and any(ch.isdigit() for ch in items[0]),
              items[0].replace("\n", " | ") if items else "")
        moving = page.eval_on_selector_all(
            "li", "els => els.filter(e => e.style.transform || e.style.opacity).length")
        check("GSAP 动画生效（列表项带内联 transform/opacity）", moving >= 1, f"{moving} 项")
        check("零 pageerror / console.error", not problems, "; ".join(problems[:3]))

        SHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT), full_page=False)
        browser.close()

    print("结果：" + ("全部通过" if not failures else f"{len(failures)} 项失败：{failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
