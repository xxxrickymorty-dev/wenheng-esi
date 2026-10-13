# -*- coding: utf-8 -*-
"""陈列馆关键帧截图：为「单页滚动原型」（假 3D）与降级图备料。

用法（先起服务；playwright 在系统 Python 里）：
    & "$env:LOCALAPPDATA\\Programs\\Python\\Python313\\python.exe" web\\tools\\capture_shelf_frames.py
    ... capture_shelf_frames.py --out web\\mockups\\陈列馆原型-帧     # 默认输出目录
    ... capture_shelf_frames.py --base http://127.0.0.1:8080

产出（JPEG q88，1440×900，画面只留 3D/书，DOM 导航与按钮已临时隐藏）：
    f0-exterior-front  幕0 门前（外景正面）
    f1-exterior-near   幕1 走近（滚轮推近一档）
    f2-exterior-door   幕2 门前（推近两档）
    f9-exterior-aerial 备用：鸟瞰
    f3-room-wide       幕3 入室（室内全景）
    f4-platform-near   幕4 展台近景（室内推近）
    f5-reader-cover    幕4 翻书：封面
    f6-reader-spread   幕4 翻书：内页对开

只读：登录、点击、截图；不触发任何写操作（不生成/不签单）。
口令只从 server/.env 读，不打印。
"""

import argparse
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]        # wenheng/
ENV = ROOT / "server" / ".env"

HIDE_CSS = """
body.cap-hide .topbar,
body.cap-hide .entry-content,
body.cap-hide .model-controls,
body.cap-hide .room-ui,
body.cap-hide .room-catalog-list,
body.cap-hide .site-footer,
body.cap-hide .returning-note,
body.cap-hide .reader-hint { visibility: hidden !important; }
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--out", default=str(ROOT / "web" / "mockups" / "陈列馆原型-帧"))
    args = ap.parse_args()
    B = args.base.rstrip("/")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    env_text = ENV.read_text(encoding="utf-8-sig")   # .env 可能带 BOM（首行会吃掉匹配）
    m = re.search(r"^WENHENG_USER=(.*)$", env_text, re.M)
    p = re.search(r"^WENHENG_PASS=(.*)$", env_text, re.M)
    if not m or not p:
        print("读不到 server/.env 里的管理员账号（WENHENG_USER / WENHENG_PASS）")
        return 2
    U, P = m.group(1).strip(), p.group(1).strip()

    def shot(pg, name: str) -> None:
        path = out / f"{name}.jpg"
        pg.screenshot(path=str(path), type="jpeg", quality=88)
        print(f"  ✓ {name}.jpg  {path.stat().st_size / 1024:.0f} KB")

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True,
                               args=["--use-gl=angle", "--enable-unsafe-swiftshader"])
        pg = b.new_context(viewport={"width": 1440, "height": 900},
                           device_scale_factor=1).new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        pg.goto(B + "/login", wait_until="networkidle")
        pg.fill(".login-form input[name=username]", U)
        pg.fill(".login-form input[name=password]", P)
        pg.click(".login-form button[type=submit]")
        pg.wait_for_url("**/app/shelf/**", timeout=15000)
        pg.wait_for_selector(".home-book-item", timeout=15000)
        print("① 登录并落到陈列馆首页")

        pg.add_style_tag(content=HIDE_CSS)

        def hide(on: bool) -> None:
            pg.evaluate(f"document.body.classList.toggle('cap-hide', {str(on).lower()})")

        # —— 外景：幕 0–2 ——
        pg.click(".header-entrance")
        pg.wait_for_selector("canvas", timeout=20000)
        pg.wait_for_timeout(3200)
        hide(True)
        shot(pg, "f0-exterior-front")

        pg.mouse.move(720, 450)
        for i in range(2):
            pg.mouse.wheel(0, -300)
            pg.wait_for_timeout(700)
            shot(pg, f"{'f1-exterior-near' if i == 0 else 'f2-exterior-door'}")

        hide(False)
        pg.click(".model-controls button:has-text('鸟瞰')")
        pg.wait_for_timeout(1400)
        hide(True)
        shot(pg, "f9-exterior-aerial")

        # —— 入室：幕 3–4 ——
        hide(False)
        pg.click(".model-controls button:has-text('正面')")
        pg.wait_for_timeout(1200)
        pg.click(".primary-button")
        pg.wait_for_timeout(2600)
        hide(True)
        shot(pg, "f3-room-wide")

        pg.mouse.move(720, 450)
        for _ in range(2):
            pg.mouse.wheel(0, -300)
            pg.wait_for_timeout(700)
        shot(pg, "f4-platform-near")

        # —— 翻书：幕 4 ——
        hide(False)
        pg.click(".room-catalog-list summary")
        pg.wait_for_timeout(400)
        pg.locator(".room-catalog-list button").last.click()   # 打开最新一期
        pg.wait_for_selector("#flipbook", timeout=15000)
        pg.wait_for_timeout(2200)
        hide(True)
        shot(pg, "f5-reader-cover")

        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(1000)
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(1000)
        shot(pg, "f6-reader-spread")

        if errors:
            print("⚠ 页面报错：" + "; ".join(errors[:3]))
        b.close()

    print(f"完成 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
