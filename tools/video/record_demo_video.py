# -*- coding: utf-8 -*-
"""文衡演示视频 · 分段录制（Playwright，headless，1920x1080）。

产出：tmp/video/seg_NN_<name>.webm  +  seg_list.json（含每段实际时长）
后续由 _make_video.py 统一转码 / 拼接 / 烧录字幕。

用法：
    python wenheng/tmp/_record_video.py          # 全录
    python wenheng/tmp/_record_video.py 8        # 只录第 8 段（0 起）
"""
import io, json, pathlib, sys, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = pathlib.Path(__file__).resolve().parents[3]      # 工作区根（tools/<x>/ 上溯三层）
OUT = BASE / "wenheng/tmp/video"
OUT.mkdir(parents=True, exist_ok=True)
CARDS = (BASE / "申报材料/视频静态卡/cards.html").as_uri()

SITE = "http://116.62.37.161:8080"
USER, PWD = "demo", "WhyeNpDYiVw6@26"
PERIOD = "202607"

VW, VH = 1920, 1080


# ----------------------------------------------------------------- 场景动作
def scroll_show(page, total, step=760, pause=1.6):
    """来回平滑滚动 total 秒；到底/到顶自动折返。"""
    t0 = time.time()
    down = True
    while time.time() - t0 < total:
        page.mouse.wheel(0, step if down else -step)
        page.wait_for_timeout(int(pause * 1000))
        try:
            y = page.evaluate("window.scrollY")
            maxy = page.evaluate("document.body.scrollHeight - window.innerHeight")
            if down and y >= max(maxy - 2, 0):
                down = False
            elif not down and y <= 2:
                down = True
        except Exception:
            pass


def show(page, sec):
    """静态卡：停留 sec 秒（多录 0.6s 便于裁剪）。"""
    page.wait_for_timeout(int(sec * 1000) + 600)


def card(anchor, sec):
    def _f(page):
        page.goto(f"{CARDS}#{anchor}", wait_until="load")
        page.wait_for_timeout(300)
        show(page, sec)
    return _f


def login(page):
    page.goto(f"{SITE}/login", wait_until="networkidle")
    page.wait_for_timeout(900)
    page.fill('input[name="username"]', USER)
    page.wait_for_timeout(500)
    page.fill('input[name="password"]', PWD)
    page.wait_for_timeout(1200)
    page.click('button[type="submit"]')
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    page.wait_for_timeout(2000)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(2600)
    page.mouse.wheel(0, -300)
    page.wait_for_timeout(2000)


def collation(page):
    """/  首屏即最新一期对勘本。

    ⚠ 对勘本整页只有一屏多（scrollHeight 1175 / 视口 1080），mouse.wheel 几乎不产生
    位移 —— Playwright 只录「变化帧」，没位移的等待会被压掉。
    改为点左侧导航切章节，让画面持续变化，才录得到内容。
    """
    page.goto(SITE + "/", wait_until="networkidle")
    page.wait_for_timeout(2800)
    items = page.locator("#whcNav a, #whcNav button, #whcNav li")
    n = items.count()
    print(f"  导航条目 {n}")
    t0 = time.time()
    k = 0
    while time.time() - t0 < 30:
        if n:
            try:
                items.nth(k % n).click(timeout=3000)
            except Exception:
                pass
            k += 1
        page.wait_for_timeout(2200)


def run_batch(page):
    """控制台：选 202607 → 一 键 生 成 → 等终态。"""
    page.goto(SITE + "/run", wait_until="networkidle")
    page.wait_for_timeout(2000)
    try:
        page.select_option('select[name="period_sel"]', PERIOD)
        page.wait_for_timeout(1200)
    except Exception as e:
        print("  [warn] 选期次失败:", e)
    page.wait_for_timeout(800)
    page.click('#run-form button[type="submit"]')
    deadline = time.time() + 240
    done = False
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        try:
            txt = page.inner_text("body")
            if "completed" in txt or "已完成" in txt:
                done = True
                break
        except Exception:
            pass
    print("  跑批完成" if done else "  [warn] 跑批未等到 completed")
    page.mouse.wheel(0, 900)
    page.wait_for_timeout(2500)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(1800)


def redslots(page):
    page.goto(f"{SITE}/p/{PERIOD}/redslots", wait_until="networkidle")
    page.wait_for_timeout(2000)
    scroll_show(page, 22)
    # 点开一张图看大图
    try:
        page.locator("a.chart").first.click(timeout=6000)
        page.wait_for_timeout(3200)
        page.go_back(wait_until="networkidle")
        page.wait_for_timeout(1200)
    except Exception as e:
        print("  [warn] 图表点击失败:", e)
    scroll_show(page, 14)


def archive(page):
    page.goto(f"{SITE}/p/{PERIOD}/archive", wait_until="networkidle")
    page.wait_for_timeout(2000)
    scroll_show(page, 38)


def sign(page):
    """对勘本：滚到签单区 → 勾选确认 → 填批注 → 确认签单 → 展示产物下载。"""
    page.goto(f"{SITE}/p/{PERIOD}", wait_until="networkidle")
    page.wait_for_timeout(2500)
    scroll_show(page, 10)
    # 签单面板默认收起，先点「钤 印 签 单」展开（按钮文本含空格，按 class 定位更稳）
    try:
        page.locator("button.whc-btn").first.click(timeout=6000)
        page.wait_for_timeout(2200)
    except Exception as e:
        print("  [warn] 展开签单面板:", e)
    try:                                     # 勾选「已知悉待人工补录项」
        ack = page.locator('input[name="ack"]')
        if ack.count() and not ack.first.is_checked():
            ack.first.check(timeout=5000)
            page.wait_for_timeout(1200)
    except Exception as e:
        print("  [warn] ack 勾选:", e)
    try:
        note = page.locator('input[name="note"]')
        if note.count():
            note.first.fill("演示签单 · 已逐条核对红色件清单")
            page.wait_for_timeout(1400)
    except Exception as e:
        print("  [warn] 批注:", e)
    try:
        page.locator("form button[type=submit]").last.click(timeout=6000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print("  [warn] 确认签单:", e)
    scroll_show(page, 10)


# ----------------------------------------------------------------- 场景表
# (段名, 动作, 是否需登录, 目标时长 s；None=不裁剪)
SCENES = [
    ("00_title",     card("s0", 8),       False, 8),
    ("01_pain1",     card("s1a", 13),     False, 13),
    ("02_pain2",     card("s1b", 13),     False, 13),
    ("03_pain3",     card("s1c", 13),     False, 13),
    ("04_login",     login,               False, None),
    ("05_collation", collation,           True,  None),
    ("06_redslots",  redslots,            True,  None),
    ("07_run",       run_batch,           True,  None),
    ("08_archive",   archive,             True,  None),
    ("09_heal",      card("s7", 45),      False, 45),
    ("10_sign",      sign,                True,  None),
    ("11_value",     card("s9", 30),      False, 30),
    ("12_demo",      card("s10", 12),     False, 12),
]


def main():
    # 命令行给段号可只录指定段（支持多个： python _record_video.py 5 6 8 10）
    only = set(int(x) for x in sys.argv[1:]) or None
    pw = sync_playwright().start()
    # 用系统 Chrome：playwright 自带 chromium 需从 cdn.playwright.dev 下 195MB（实测极慢），
    # 本机已装 Chrome，channel="chrome" 直接复用，录像能力一致。
    browser = pw.chromium.launch(channel="chrome")

    # 先登录一次，拿到 storage_state 供后续录制 context 复用
    state_file = OUT / "state.json"
    if not state_file.exists():
        c = browser.new_context(viewport={"width": VW, "height": VH})
        p = c.new_page()
        login(p)
        c.storage_state(path=str(state_file))
        c.close()
        print("登录态已保存 ->", state_file)

    segs = []
    for i, (name, action, need_login, _dur) in enumerate(SCENES):
        if only is not None and i not in only:
            continue
        vdir = OUT / f"seg_{i:02d}_{name}"
        vdir.mkdir(parents=True, exist_ok=True)
        kw = dict(viewport={"width": VW, "height": VH},
                  record_video_dir=str(vdir),
                  record_video_size={"width": VW, "height": VH})
        if need_login:
            kw["storage_state"] = str(state_file)
        ctx = browser.new_context(**kw)
        page = ctx.new_page()
        t0 = time.time()
        try:
            action(page)
        except Exception as e:
            print(f"  [ERROR] 段 {i} {name}: {type(e).__name__}: {e}")
        el = time.time() - t0
        ctx.close()  # 关闭后才落盘 webm

        vids = list(vdir.glob("*.webm"))
        segs.append({"i": i, "name": name, "dir": str(vdir),
                     "video": str(vids[0]) if vids else None,
                     "wall": round(el, 1)})
        print(f"[{i:02d}] {name:14s} 用时 {el:5.1f}s  video={vids[0].name if vids else 'NONE'}")

    # 只录部分段时，把新段合并回既有清单（避免整份清单被覆盖只剩这几段）
    list_path = OUT / "seg_list.json"
    if only and list_path.exists():
        old = json.loads(list_path.read_text(encoding="utf-8"))
        new_by_i = {s["i"]: s for s in segs}
        segs = [new_by_i.get(s["i"], s) for s in old]
    segs.sort(key=lambda s: s["i"])
    list_path.write_text(
        json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8")
    browser.close()
    pw.stop()
    print("\n段清单 ->", OUT / "seg_list.json")


if __name__ == "__main__":
    main()
