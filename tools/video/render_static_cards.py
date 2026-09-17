# -*- coding: utf-8 -*-
"""静态卡截图：cards.html 各 section → 1920x1080 PNG。

为什么不用 Playwright 录像录静态卡：它只写「变化帧」，静止页面几秒不重绘
就只有 1 秒素材（实测 00_title 录成 1.00s）。截图 + ffmpeg 定长合成才是可控的。
"""
import io, pathlib, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = pathlib.Path(__file__).resolve().parents[3]      # 工作区根（tools/<x>/ 上溯三层）
CARDS = (BASE / "申报材料/视频静态卡/cards.html").as_uri()
OUT = BASE / "wenheng/tmp/video/cards"
OUT.mkdir(parents=True, exist_ok=True)

ANCHORS = ["s0", "s1a", "s1b", "s1c", "s7", "s9", "s10"]

pw = sync_playwright().start()
b = pw.chromium.launch(channel="chrome")
c = b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
p = c.new_page()
p.goto(CARDS, wait_until="load")
p.wait_for_timeout(1500)          # 等中文字体/宋体渲染到位
for a in ANCHORS:
    p.goto(f"{CARDS}#{a}", wait_until="load")
    p.wait_for_timeout(700)
    dst = OUT / f"{a}.png"
    p.locator(f"#{a}").screenshot(path=str(dst))
    print(a, "->", dst.name, dst.stat().st_size // 1024, "KB")
b.close()
pw.stop()
