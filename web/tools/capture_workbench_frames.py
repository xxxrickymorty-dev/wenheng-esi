# -*- coding: utf-8 -*-
"""工作台关键帧截图：为「单页滚动原型」工作区介绍章备料（真实界面截图）。

用法（先起服务；playwright 在系统 Python 里）：
    & "$env:LOCALAPPDATA\\Programs\\Python\\Python313\\python.exe" web\\tools\\capture_workbench_frames.py
    ... capture_workbench_frames.py --base http://127.0.0.1:8080

产出（JPEG q88，1440×900，只读浏览，不做任何写操作）：
    wb-acquire    取数台
    wb-ledger     台账（19 张表）
    wb-workbench  生成台（当前期任务）
    wb-review     审核台（整篇试排 + 在线填 + 签单区；不点签单）

只读：登录、导航、截图；不触发任何写操作（不生成/不签单/不上传）。
口令只从 server/.env 读，不打印。
"""

import argparse
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]        # wenheng/
ENV = ROOT / "server" / ".env"

VIEWS = [
    ("wb-acquire", "/app/?view=acquire", 2600),
    ("wb-ledger", "/app/?view=ledger", 2000),
    ("wb-workbench", "/app/", 2200),
    ("wb-review", "/app/?view=review", 3500),
]


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
        pg.wait_for_url("**/app/**", timeout=15000)
        print("① 登录")

        for name, path, wait_ms in VIEWS:
            pg.goto(B + path, wait_until="networkidle")
            pg.wait_for_timeout(wait_ms)
            shot = out / f"{name}.jpg"
            pg.screenshot(path=str(shot), type="jpeg", quality=88)
            print(f"  ✓ {name}.jpg  {shot.stat().st_size / 1024:.0f} KB  ({path})")

        if errors:
            print("⚠ 页面报错：" + "; ".join(errors[:3]))
        b.close()

    print(f"完成 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
