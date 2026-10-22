# -*- coding: utf-8 -*-
"""验证恢复后的「12:46 版」—— CSS 3D 书架 + 三条交互。

判据：
  A. 首屏 shelf 态；.sbook 4 本；色板非空；三册色各不相同
  B. 点书架上的书 → stand（抽取）
  C. 点书封 → reading，翻书 8 页
  D. 点背景 → stand（合上）      ← 需求①「点背景合上」
  E. 点背景 → shelf（归架）      ← 需求②「点背景回退书架」
  F. 全程零 pageerror / console.error
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

G = (Path(__file__).resolve().parents[2] / "设计文档" / "前端设计预览"
     / "G-复刻WorkingVolumes")
SHOTS = G / "预览截图"
SHOTS.mkdir(exist_ok=True)
URL = (G / "index.html").as_uri()


async def click_xy(page, x, y):
    await page.mouse.click(x, y)


async def main() -> int:
    fails, notes = [], []
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        p = await b.new_page(viewport={"width": 1560, "height": 900}, device_scale_factor=1)
        errs = []
        p.on("console", lambda m: errs.append([m.type, m.text[:200]]) if m.type == "error" else None)
        p.on("pageerror", lambda e: errs.append(["pageerror", str(e)[:200]]))
        await p.goto(URL)
        await p.wait_for_timeout(2200)

        # ── A 首屏 ────────────────────────────────────────────────
        st = await p.evaluate("WH_VOL.state()")
        n = await p.evaluate("document.querySelectorAll('.sbook').length")
        pal = await p.evaluate("WH_VOL.palette()")
        scs = await p.evaluate("""() => Array.from(document.querySelectorAll('.sbook'))
            .map(b => getComputedStyle(b).getPropertyValue('--sc').trim())""")
        notes.append(f"A 首屏 state={st} .sbook={n} 色={pal['vol']} 各册色={scs}")
        if st != "shelf":
            fails.append(f"A 首屏应为 shelf，实为 {st}")
        if n != 4:
            fails.append(f"A .sbook 应为 4，实为 {n}")
        if not pal["vol"]:
            fails.append("A 卷色为空")
        if len(set(scs)) != len(scs):
            fails.append(f"A 各册书脊色有重复：{scs}")
        await p.screenshot(path=str(SHOTS / "R1-书架.png"))

        # ── B 点书架上的书 → 抽取 ────────────────────────────────
        rect = await p.evaluate("""() => {
          const b = document.querySelectorAll('.sbook')[1];
          const r = b.getBoundingClientRect();
          return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
        }""")
        notes.append(f"B 第2本 屏幕中心=({rect['x']:.0f},{rect['y']:.0f}) {rect['w']:.0f}x{rect['h']:.0f}")
        await click_xy(p, rect["x"], rect["y"])
        await p.wait_for_timeout(1400)
        st = await p.evaluate("WH_VOL.state()")
        idx = await p.evaluate("WH_VOL.index()")
        notes.append(f"B 抽取后 state={st} 索引={idx}")
        if st != "stand":
            fails.append(f"B 点书应进入 stand，实为 {st}")
        await p.screenshot(path=str(SHOTS / "R2-已抽取.png"))

        # ── C 点书封 → 开卷 ──────────────────────────────────────
        # ⚠ 必须用真实鼠标事件：dispatchEvent(new PointerEvent('pointerup')) 不够
        # （页面用 pointerdown/up 区分拖拽与点击，合成事件缺 pressed 状态会被忽略）。
        c = await p.evaluate("""() => {
          const e = document.querySelector('.book3d .f-cover') || document.querySelector('.book3d');
          const r = e.getBoundingClientRect();
          return {x: r.left + r.width/2, y: r.top + r.height/2};
        }""")
        notes.append(f"C 书封中心=({c['x']:.0f},{c['y']:.0f})")
        await click_xy(p, c["x"], c["y"])
        await p.wait_for_timeout(2400)
        st = await p.evaluate("WH_VOL.state()")
        pages = await p.evaluate("document.querySelectorAll('#flipbook .page').length")
        notes.append(f"C 开卷后 state={st} 页数={pages}")
        if st != "reading":
            fails.append(f"C 开卷后应为 reading，实为 {st}")
        if pages != 8:
            fails.append(f"C 翻书页数应为 8，实为 {pages}")
        await p.screenshot(path=str(SHOTS / "R3-翻书.png"))

        # ── D 点背景 → 合上（需求①）────────────────────────────
        bg = await p.evaluate("""() => {
          const f = document.querySelector('#flipWrap').getBoundingClientRect();
          const y = Math.round(f.top + f.height / 2);
          const x = Math.max(20, Math.round(f.left) - 70);
          const el = document.elementFromPoint(x, y);
          return {x, y, onPage: !!(el && el.closest('.flip-wrap'))};
        }""")
        notes.append(f"D 背景取点=({bg['x']},{bg['y']}) 落在书页上={bg['onPage']}")
        if bg["onPage"]:
            fails.append("D 背景取点砸在书页上了（测试坐标问题）")
        else:
            await click_xy(p, bg["x"], bg["y"])
            await p.wait_for_timeout(1600)
            st = await p.evaluate("WH_VOL.state()")
            notes.append(f"D 点背景后 state={st}")
            if st != "stand":
                fails.append(f"D 点背景合上后应为 stand，实为 {st}")
        await p.screenshot(path=str(SHOTS / "R4-合上.png"))

        # ── E 点背景 → 归架（需求②）────────────────────────────
        bg2 = await p.evaluate("""() => {
          const b = document.querySelector('.book3d').getBoundingClientRect();
          const s = document.querySelector('.stage').getBoundingClientRect();
          const x = Math.min(b.right + 40, s.right - 24);
          const y = Math.max(s.top + 40, Math.min(b.top + b.height / 2, s.bottom - 40));
          const el = document.elementFromPoint(x, y);
          return {x, y, onBook: !!(el && el.closest('.book3d'))};
        }""")
        notes.append(f"E 背景取点=({bg2['x']:.0f},{bg2['y']:.0f}) 落在书上={bg2['onBook']}")
        if bg2["onBook"]:
            fails.append("E 背景取点砸在书上了（测试坐标问题）")
        else:
            await click_xy(p, bg2["x"], bg2["y"])
            await p.wait_for_timeout(1600)
            st = await p.evaluate("WH_VOL.state()")
            notes.append(f"E 点背景后 state={st}")
            if st != "shelf":
                fails.append(f"E 点背景归架后应为 shelf，实为 {st}")
        await p.screenshot(path=str(SHOTS / "R5-归架.png"))

        # ── F 零报错 ─────────────────────────────────────────────
        real = [e for e in errs if "ReadPixels" not in e[1]]
        notes.append(f"F 报错数={len(real)}")
        if real:
            for e in real[:3]:
                fails.append(f"F {e[0]}: {e[1]}")

        await b.close()

    print("─" * 66)
    for x in notes:
        print(" ·", x)
    print("─" * 66)
    if fails:
        print(f"❌ {len(fails)} 项不过：")
        for x in fails:
            print("   ✗", x)
        return 1
    print("✅ 全部通过（CSS 书架 4 本 / 抽取 / 开卷 8 页 / 点背景合上 / 点背景归架 / 零报错）")
    return 0


sys.exit(asyncio.run(main()))