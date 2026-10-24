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

2026-10-11 改：guest 角色取消，改「操作员」（账号 demo/评委）——操作员**不再**被
送回陈列馆，而是进工作区。2026-10-20 起：主台账仍 admin；运行档案/红件/溯源/水位/
沙盘只读开放；签单/出稿/取数按 2026-10-12/10-17 政策开放。断言据此更新：
报告页有红件/溯源入口、无运行日志产物；红件页/运行档案无下载按钮；陈列馆翻页 ≥ 3 页。

跑法（playwright 在**系统 Python** 里，不在 `.venv`）：

    uv run python -m uvicorn server.app:app --host 127.0.0.1 --port 8080
    & "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" tools\check_web_app.py

服务不在默认地址时用 `WENHENG_BASE` 覆盖（与 e2e_check.py 同一套约定）：
    $env:WENHENG_BASE="http://127.0.0.1:8099"; & "...\python.exe" tools\check_web_app.py

退出码 0 = 通过；1 = 有断言失败（失败项打印在前）。
"""
import http.cookiejar
import json
import os
import pathlib
import re
import sys
import tempfile
import urllib.parse
import urllib.request

BASE = os.environ.get("WENHENG_BASE", "http://127.0.0.1:8080").rstrip("/")
WENHENG = pathlib.Path(__file__).resolve().parent.parent


def _env_file_value(key, default=""):
    """口令只从环境变量或 server/.env 来（2026-10-02：删掉内置默认口令）。"""
    if os.environ.get(key):
        return os.environ[key]
    env_file = WENHENG / "server" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


USER = os.environ.get("WENHENG_E2E_USER") or _env_file_value("WENHENG_USER", "admin")
PASS = os.environ.get("WENHENG_E2E_PASS") or _env_file_value("WENHENG_PASS")
#: 操作员（评委/馆员；2026-10-11 起取代 guest）——证据面只读，签单/出稿/取数
#: 按 2026-10-12/10-17 政策开放；账号/口令从 .env 或环境变量来。
OPERATOR_USER = (os.environ.get("WENHENG_E2E_OPERATOR_USER")
                 or _env_file_value("WENHENG_OPERATOR_USER", "demo"))
OPERATOR_PASS = (os.environ.get("WENHENG_E2E_OPERATOR_PASS")
                 or _env_file_value("WENHENG_OPERATOR_PASS"))
if not PASS:
    print("未找到管理员口令：请在 server/.env 设置 WENHENG_PASS，或设 WENHENG_E2E_PASS 后重跑。")
    raise SystemExit(2)
if not OPERATOR_PASS:
    print("未找到操作员口令：请在 server/.env 设置 WENHENG_OPERATOR_PASS，或设 WENHENG_E2E_OPERATOR_PASS 后重跑。")
    raise SystemExit(2)
_SHOT_DIR = pathlib.Path(tempfile.gettempdir()) / "opencode"     # 本机临时目录，不写死在仓库里
_SHOT_DIR.mkdir(parents=True, exist_ok=True)
SHOT = _SHOT_DIR / "wh_app.png"
SHOT_SHELF = _SHOT_DIR / "wh_shelf.png"

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def login_cookies(user=USER, password=PASS):
    """走真实表单登录，拿 session cookie；同时返回落点 URL
    （2026-10-12：两种角色都应落陈列馆 /app/shelf/——看 → 问 → 做）。"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(BASE + "/login").read()
    data = urllib.parse.urlencode({"username": user, "password": password}).encode()
    resp = opener.open(urllib.request.Request(BASE + "/login", data=data))
    final = resp.geturl()
    cookies = [{"name": c.name, "value": c.value, "domain": "127.0.0.1", "path": "/"}
               for c in cj]
    return cookies, final


def main():
    from playwright.sync_api import sync_playwright

    cookies, login_final = login_cookies()
    check("登录拿到 session cookie", any(c["name"] == "session" for c in cookies))
    check("管理员登录先落陈列馆（/app/shelf/）",
          login_final.rstrip("/").endswith("/app/shelf"), f"final={login_final}")

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
        admin_cookies, _admin_final = login_cookies()
        admin_ctx.add_cookies(admin_cookies)
        admin_shelf = admin_ctx.new_page()
        admin_shelf_problems = []
        admin_shelf.on("pageerror", lambda e: admin_shelf_problems.append("pageerror: " + str(e)))
        admin_shelf.on("console", lambda m: admin_shelf_problems.append("console.error: " + m.text)
                       if m.type == "error" else None)
        resp3 = admin_shelf.goto(BASE + "/app/shelf/", wait_until="networkidle")
        check("管理员 GET /app/shelf/ → 200", bool(resp3) and resp3.status == 200,
              f"got {resp3.status if resp3 else '?'}")
        try:
            admin_shelf.wait_for_selector(".sl-cover", timeout=15000)
            check("管理员进陈列馆能看到册位（不弹回）", True)
        except Exception as e:                                       # noqa: BLE001
            check("管理员进陈列馆能看到册位（不弹回）", False,
                  f"url={admin_shelf.url} {str(e)[:60]}")
        # 管理员开书应看到全内容册页（数字体检 / 学科大表 / 双路线预测）
        try:
            admin_shelf.click(".sl-cover")
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
        for v in ("workbench", "acquire", "report", "review", "ledger", "analysis", "forecast",
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

        # ---- 1e) 审核台知悉闸（票 14）：未勾选 → 签单禁用；勾选 → 可用（只读，不点签单） ----
        # 闸门只为「待人工空位」而设：先按真实数据取空位数（2026-09-29 修——202607 重出后
        # 待人工=0，写死「必禁用」会在干净数据上假失败，e2e 同批已改按状态分支）。
        try:
            manual = 0
            try:
                secs = (page.request.get(BASE + "/api/periods/202607/collation?full=true")
                        .json().get("sections") or [])
                manual = sum(int(s.get("manual") or 0) for s in secs)
            except Exception:                                           # noqa: BLE001
                manual = 0
            page.goto(BASE + "/app/?view=review&period=202607", wait_until="domcontentloaded")
            page.wait_for_selector(".rv-grid", timeout=30000)
            if manual == 0:
                check("审核台知悉闸（本期无待人工空位，闸门不适用）", True, "0 处待人工")
            elif page.locator(".rv-lead .pill", has_text="已签单").count():
                check("审核台知悉闸（本期已签单，按钮态不适用）", True, "已签单")
            else:
                page.wait_for_selector(".rv-ack input", timeout=15000)
                sign = page.locator("#rv-sign button.btn.primary").first
                page.wait_for_selector("#rv-sign button.btn.primary", timeout=15000)
                disabled_before = sign.is_disabled()
                page.locator(".rv-ack input").check()
                page.wait_for_timeout(200)
                enabled_after = not sign.is_disabled()
                page.locator(".rv-ack input").uncheck()
                page.wait_for_timeout(200)
                disabled_again = sign.is_disabled()
                check("审核台知悉闸：未勾禁用 / 勾选可用 / 取消再禁用",
                      disabled_before and enabled_after and disabled_again,
                      f"before={disabled_before} after={enabled_after} again={disabled_again}")
        except Exception as e:                                          # noqa: BLE001
            check("审核台知悉闸（票 14）", False, str(e)[:100])

        # ---- 1f) 取数台（X2·票 12｜2026-10-15 新 IA）：左栏＝4 主区；出报告步骤条 ① 在 ③ 前 ----
        try:
            page.goto(BASE + "/app/?view=acquire&period=202609", wait_until="domcontentloaded")
            page.wait_for_selector(".aq-head", timeout=20000)
            navs = page.eval_on_selector_all("nav[aria-label='工作区'] a", "els => els.map(e => e.innerText.trim())")
            check("导航前四项（出报告 / 可视化工作流 / 灵活报告 / 问文衡；2026-10-24 加全景、导航瘦身）",
                  navs[:4] == ["出报告", "可视化工作流", "灵活报告", "问文衡"], str(navs))
            check("导航已瘦身（主台账 / 自愈沙盘 / 换馆沙盘不在导航；2026-10-24 rick，深链保留）",
                  not any(n in navs for n in ("主台账", "自愈沙盘", "换馆沙盘")) and "运行档案" in navs,
                  str(navs))
            steps = page.eval_on_selector_all(
                "nav[aria-label='出报告步骤'] a, nav[aria-label='出报告步骤'] span",
                "els => els.map(e => e.innerText.trim())")
            i_take = next((i for i, s in enumerate(steps) if "取数" in s), -1)
            i_gen = next((i for i, s in enumerate(steps) if "生成" in s), -1)
            check("出报告步骤条：① 取数核验 在 生成初稿 之前",
                  i_take >= 0 and i_gen >= 0 and i_take < i_gen, str(steps[:4]))
            # 采集/并入台账解耦：**当期**（已并入）仍要有整期重取入口（2026-10-16 票 01）
            has_refetch = page.eval_on_selector_all(
                "button", "els => els.some(e => /重新取这一期/.test(e.innerText))")
            check("当期（已并入）仍有整期重取入口（采集与并入台账解耦）",
                  has_refetch, f"found={has_refetch}")
            # 往期档案只读（票 03）：不再有取数入口，且写明缘由
            page.goto(BASE + "/app/?view=acquire&period=202605", wait_until="domcontentloaded")
            page.wait_for_selector(".aq-head", timeout=20000)
            ro_refetch = page.eval_on_selector_all(
                "button", "els => els.some(e => /重新取这一期|开始取数/.test(e.innerText))")
            ro_text = page.eval_on_selector_all("body", "els => els.map(e => e.textContent).join('')")
            check("往期档案只读：没有取数入口，且写明缘由",
                  (not ro_refetch) and "往期档案只读" in ro_text,
                  f"fetchBtn={ro_refetch} note={'往期档案只读' in ro_text}")
            # 三段式门禁（2026-10-19 rick 定）：没检查过 → 取数段锁着、不给「开始取数」
            page.goto(BASE + "/app/?view=acquire&period=202611", wait_until="domcontentloaded")
            page.wait_for_selector(".aq-head", timeout=20000)
            gate_txt = page.inner_text("main")
            gate_btn = page.eval_on_selector_all(
                "button", "els => els.some(e => /开始取数/.test(e.innerText))")
            check("三段式门禁：没检查过 → 取数段锁着（无「开始取数」，写明等检查）",
                  (not gate_btn) and ("等 ① 检查通过" in gate_txt), f"btn={gate_btn}")
            page.goto(BASE + "/app/?view=acquire&period=202609", wait_until="domcontentloaded")
            page.wait_for_selector(".aq-head", timeout=20000)
            # 拍板 2026-10-16 中午：头条去重——只留**采集**进度行；「已并入（期次 列）」的结论归焦点卡。
            # （此前头条与焦点卡各写一句「已并入（202609 列）」，是重复。）
            head_txt = page.inner_text(".aq-head")
            flow_txt = page.inner_text(".flow")
            check("取数台头条去重：只留采集行（无「并入台账 ·」），并入结论归三段条",
                  ("采集 ·" in head_txt) and ("并入台账" not in head_txt)
                  and ("已并入" in flow_txt),
                  f"head={head_txt[:70]!r} flow={flow_txt[:40]!r}")
            txt = page.inner_text("main")
            check("取数台：期次数据状态与开始前检查都在",
                  "取数核验" in txt and "开始前检查" in txt, "")
            check("开始前检查四灯齐全（浏览器 / ESI / InCites / 数据期）",
                  all(s in txt for s in ("浏览器", "ESI 登录", "InCites 登录", "数据期")), "")
            # 三段式（2026-10-19）：② 收起后明细从「取数清单」按钮点开；展开态常驻同一份
            page.locator("button", has_text="取数清单").first.click()
            page.wait_for_timeout(300)
            n_groups = page.locator(".aq-g").count()
            has_empty = "还没有取数记录" in page.inner_text("main")
            check("取数台：清单展开（有组卡，或如实说没有记录）", n_groups > 0 or has_empty,
                  f"groups={n_groups}")
            page.goto(BASE + "/app/?period=202607", wait_until="domcontentloaded")
            page.wait_for_selector(".story .cell", timeout=15000)
            page.wait_for_timeout(1500)   # 故事条开场按真实顺序回放，等首格就位再读 href（曾两次时序抖动）
            href = page.get_attribute(".story .cell", "href")
            check("生成台故事条第一步可点入取数台", bool(href) and "view=acquire" in href, str(href))
        except Exception as e:                                          # noqa: BLE001
            check("取数台回归（X2）", False, str(e)[:100])

        # ---- 1f0) 可视化工作流 · 产线全景（2026-10-24 rick 定）：真相面板 + 工厂场景，数字为真值 ----
        try:
            page.goto(BASE + "/app/?view=pano&period=202609", wait_until="domcontentloaded")
            page.wait_for_selector(".pano-stage svg", timeout=20000)
            pano_txt = page.inner_text("main")
            check("产线全景：真相面板五段齐（取数 / 中台 / 产线 / 质检 / 签发）",
                  all(k in pano_txt for k in ("取数", "中台", "产线", "质检", "签发")), "")
            check("产线全景：真值声明在场（不新增数字、不演没发生的动画）",
                  ("不新增数字" in pano_txt) and ("红色件清单" in pano_txt), "")
            cams = page.eval_on_selector_all(".pano-cams button", "els => els.map(e => e.innerText.trim())")
            check("产线全景：相机按钮在（全景 / 左转 / 右转 / 拉近 / 拉远）",
                  cams == ["全景", "左转", "右转", "拉近", "拉远"], str(cams))
            vb0 = page.eval_on_selector(".pano-stage svg", "el => el.getAttribute('viewBox')")
            page.click(".pano-cams button:has-text('拉近')")
            vb1 = page.eval_on_selector(".pano-stage svg", "el => el.getAttribute('viewBox')")
            check("产线全景：相机只动 viewBox（不动数据）", vb0 != vb1, f"{vb0} -> {vb1}")
        except Exception as e:                                          # noqa: BLE001
            check("产线全景（2026-10-24）", False, str(e)[:100])

        # ---- 1f1) 开新一期（票 05）：入口在，非法期次当场挡下（不落状态） ----
        try:
            page.goto(BASE + "/app/?view=acquire&period=202609", wait_until="domcontentloaded")
            page.wait_for_selector(".aq-head", timeout=15000)
            has_open = page.locator("button", has_text="开新一期").count() > 0
            check("取数台：有「开新一期」入口", has_open, "")
            if has_open:
                page.locator("button", has_text="开新一期").first.click()
                page.fill("#aq-new-period", "202612")
                page.locator("button", has_text="开这一期").first.click()
                page.wait_for_timeout(300)
                err = page.inner_text(".aq-open")
                check("开新一期：非双月当场挡下", "1 / 3 / 5 / 7 / 9 / 11" in err,
                      err.replace("\n", " ")[:50])
        except Exception as e:                                          # noqa: BLE001
            check("开新一期入口回归（票 05）", False, str(e)[:100])

        # ---- 1f2) 运行档案能看到「并入台账」的留痕（票 02：谁/何时并的） ----
        try:
            page.goto(BASE + "/app/?view=archive&period=202607", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            # 留痕在默认收起的折叠里，innerText 读不到——用 textContent（含隐藏）
            txt = page.eval_on_selector_all("body", "els => els.map(e => e.textContent).join('')")
            trace = re.search(r"已并入主台账[^\n]{0,60}", txt)
            check("运行档案显示并入台账的留痕", trace is not None,
                  (trace.group(0)[:60] if trace else "没看到「已并入主台账…」"))
            story = page.inner_text(".ar-story") if page.query_selector(".ar-story") else ""
            check("运行档案五步故事条有步骤（不报 0 步）",
                  "步" in story and "0 步" not in story, story[:80])
        except Exception as e:                                          # noqa: BLE001
            check("运行档案并入留痕", False, str(e)[:100])

        # ---- 1g) 未出稿的取数期次（ADR-0004）：临时状态文件，验证列表补录 / 详情 / 零 404 ----
        fx = None
        try:
            st_dir = pathlib.Path(__file__).resolve().parent.parent / "out" / "_acquisition"
            st_dir.mkdir(parents=True, exist_ok=True)
            fx = st_dir / "209911.json"
            fx.write_text(json.dumps({
                "period": "209911", "updated_at": "临时核对用",
                "data_period": {"esi": "临时", "incites": "临时"},
                "preflight": {"browser": "ok", "esi": "ok", "incites": "ok"},
                "capabilities": {"start": False, "retry": False, "merge": False},
                "groups": [{"id": "g1", "source": "esi", "index": 1, "title": "临时组",
                            "state": "done", "verified": 1, "downloaded": 1,
                            "files": [{"name": "a.xlsx", "label": "临时", "state": "ok"}]}],
                "totals": {"groups": 1, "expected": 1, "verified": 1, "downloaded": 1, "failed": 0},
                "copy": {"state": "review", "path": "out/_acquisition/209911/监测表.xlsx"},
                "review": {"sheets": [{"name": "临时表", "added": "临时列", "content": "临时", "source": "临时"}]},
            }, ensure_ascii=False), encoding="utf-8")
            page.goto(BASE + "/app/?view=acquire&period=209911", wait_until="domcontentloaded")
            page.wait_for_selector(".aq-head", timeout=15000)
            txt = page.inner_text("main")
            check("取数台：未出稿期次也能看（待核对态）",
                  "待核对" in txt and "核对表" in txt, "")
            page.goto(BASE + "/app/?period=209911", wait_until="domcontentloaded")
            page.wait_for_timeout(900)
            txt = page.inner_text("main")
            check("生成台：未出稿期次引导去取数（不假装已生成）",
                  "先去下载数据" in txt and "数据还没取齐" in txt, txt[:30].replace("\n", " "))
        except Exception as e:                                          # noqa: BLE001
            check("未出稿取数期次回归（X2）", False, str(e)[:100])
        finally:
            if fx is not None:
                fx.unlink(missing_ok=True)

        # ---- 2) 操作员（只读）：进工作区不被送走；写按钮不出现；陈列馆同看全内容 ----
        op_ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        op_cookies, op_final = login_cookies(OPERATOR_USER, OPERATOR_PASS)
        check("操作员登录也先落陈列馆（/app/shelf/）",
              op_final.rstrip("/").endswith("/app/shelf"), f"final={op_final}")
        op_ctx.add_cookies(op_cookies)
        operator = op_ctx.new_page()
        op_problems = []
        operator.on("pageerror", lambda e: op_problems.append("pageerror: " + str(e)))
        operator.on("console", lambda m: op_problems.append("console.error: " + m.text)
                    if m.type == "error" else None)

        operator.goto(BASE + "/app/?view=report", wait_until="networkidle")
        check("操作员进工作区不被送回陈列馆",
              "/app/shelf" not in operator.url, f"url={operator.url}")
        try:
            operator.wait_for_selector(".app-nav", timeout=10000)    # 2026-10-17 庚壳：导航进顶栏
            nav_text = operator.inner_text(".app-nav")
            check("操作员导航无「下载数据」", "下载数据" not in nav_text, nav_text.replace("\n", " "))
        except Exception as e:                                       # noqa: BLE001
            check("操作员导航无「下载数据」", False, str(e)[:80])

        # 隐藏屏直开 → 「操作员不可见」空态（前端守卫）
        operator.goto(BASE + "/app/?view=ledger", wait_until="domcontentloaded")
        operator.wait_for_timeout(600)
        check("操作员直开台账 → 不可见空态",
              "操作员不可见" in operator.inner_text("main"), "")
        # 2026-10-17 rick：demo 放开取数核验与选章节（后端同批改 @user_route）
        operator.goto(BASE + "/app/?view=acquire&period=202609", wait_until="networkidle")
        operator.wait_for_timeout(600)
        acq_txt = operator.inner_text("main")
        check("操作员可进取数核验（2026-10-17 放开）",
              "操作员不可见" not in acq_txt and "取数核验" in acq_txt, "")
        operator.goto(BASE + "/app/?view=pick&period=202609", wait_until="networkidle")
        operator.wait_for_timeout(600)
        check("操作员可进选章节（2026-10-17 放开）",
              "操作员不可见" not in operator.inner_text("main")
              and "选章节" in operator.inner_text("main"), "")
        # 报告页：红件/溯源入口只读开放；红件三件与运行日志的下载产物仍过滤
        operator.goto(BASE + "/app/?view=report", wait_until="networkidle")
        operator.wait_for_timeout(600)
        rep_text = operator.inner_text("main")
        check("操作员报告页有红件/溯源入口（只读开放）",
              "红色件清单" in rep_text and "逐格溯源" in rep_text, "")
        check("操作员报告页无运行日志产物", "运行日志" not in rep_text, "")
        # 红件页：能看清单，但没有「下载 Markdown」下载口（仍 admin）
        operator.goto(BASE + "/app/?view=red&period=202607", wait_until="networkidle")
        operator.wait_for_timeout(600)
        red_txt = operator.inner_text("main")
        check("操作员可看红件清单（只读开放）", "红色件清单" in red_txt, "")
        check("操作员红件页无下载按钮",
              not operator.query_selector('a[href*="/download/red_list"]'), "")
        # 运行档案：能看，但没有「下载日志包」入口（仍 admin）
        operator.goto(BASE + "/app/?view=archive&period=202607", wait_until="networkidle")
        operator.wait_for_timeout(800)
        check("操作员运行档案无日志包下载按钮",
              not operator.query_selector('a[href*="/download/logpack"]'), "")
        # 生成台：2026-10-12 起操作员也有出报告权限——不再出现「操作员只读」提示
        operator.goto(BASE + "/app/", wait_until="networkidle")
        operator.wait_for_timeout(600)
        wb_text = operator.inner_text("main")
        check("操作员生成台不再提示「操作员只读」", "操作员只读" not in wb_text, "")

        # 审核台：操作员可签单（提示文案 + 签单按钮都在；在线填/重出仍只管理员）
        operator.goto(BASE + "/app/?view=review&period=202607", wait_until="networkidle")
        operator.wait_for_timeout(800)
        rv_text = operator.inner_text("body")
        check("操作员审核台可签单（提示与按钮都在）",
              "操作员可以签单与撤回" in rv_text and "签单" in rv_text
              and "操作员只读" not in rv_text, "")
        # 核验页目录：吸顶避开顶栏，跳转目标留出顶栏高度（2026-10-20）
        operator.goto(BASE + "/app/?view=review&period=202609", wait_until="networkidle")
        operator.wait_for_timeout(1200)
        try:
            toc = operator.query_selector(".rv-toc")
            top = operator.eval_on_selector(".rv-toc", "el => getComputedStyle(el).top") if toc else ""
            margin = (operator.eval_on_selector("[id^='rv-b-']",
                                               "el => getComputedStyle(el).scrollMarginTop")
                      if operator.query_selector("[id^='rv-b-']") else "")
            check("核验页目录吸顶避开顶栏、跳转留出高度",
                  bool(toc) and top == "68px" and margin == "76px",
                  f"top={top} margin={margin}")
        except Exception as e:                                          # noqa: BLE001
            check("核验页目录吸顶", False, str(e)[:100])

        resp2 = operator.goto(BASE + "/app/shelf/", wait_until="networkidle")
        check("GET /app/shelf/ → 200", bool(resp2) and resp2.status == 200,
              f"got {resp2.status if resp2 else '?'}")
        try:
            operator.wait_for_selector(".home-hero", timeout=10000)
            check("陈列馆首页渲染（.home-hero）", True)
        except Exception as e:                                       # noqa: BLE001
            check("陈列馆首页渲染（.home-hero）", False, str(e)[:80])
        try:
            has_band = bool(operator.query_selector("#ask .sl-askform"))
            has_nav = bool(operator.query_selector('.sl-back[href="/app/dialog/"]'))
            check("陈列馆有「问文衡」条带与导航入口", has_band and has_nav, "")
        except Exception as e:                                       # noqa: BLE001
            check("陈列馆有「问文衡」条带与导航入口", False, str(e)[:80])
        try:
            operator.click(".sl-cover")
            operator.wait_for_selector("#flipbook", timeout=10000)
            n_pages = operator.eval_on_selector_all(".flip-page", "els => els.length")
            check("翻页阅读器打开（#flipbook 带页）", n_pages >= 3, f"{n_pages} 页")
        except Exception as e:                                       # noqa: BLE001
            check("翻页阅读器打开（#flipbook 带页）", False, str(e)[:80])
        operator.screenshot(path=str(SHOT_SHELF))

        # ---- 2b) 对话页（2026-10-12）：空态＝文衡首页；顶栏＝去生成台；?ask= 自动发送 ----
        operator.goto(BASE + "/app/dialog/", wait_until="networkidle")
        operator.wait_for_timeout(900)
        dlg_text = operator.inner_text("body")
        check("对话页空态有大标题", "文衡，帮你做报告、查数据" in dlg_text, "")
        n_pills = operator.eval_on_selector_all(".dlg-land-pill", "els => els.length")
        check("对话页空态有示例胶囊（≥6）", n_pills >= 6, f"{n_pills} 个")
        check("对话页顶栏是「去生成台」（无工作台下拉）",
              "去生成台" in dlg_text and "工作台 ▾" not in dlg_text, "")
        operator.goto(BASE + "/app/dialog/?ask=" + urllib.parse.quote("查一下化学的接近度"),
                      wait_until="networkidle")
        try:
            operator.wait_for_selector(".dlg-turn.me", timeout=8000)
            turn_text = operator.inner_text(".dlg-turn.me")
            check("?ask= 自动发送（用户话已入对话）", "化学的接近度" in turn_text, turn_text[:40])
        except Exception as e:                                       # noqa: BLE001
            check("?ask= 自动发送（用户话已入对话）", False, str(e)[:80])
        # 2026-10-12：操作员有出报告权限——说「做 9 月的报告」→ 给「覆盖重出」（run 动作）
        operator.goto(BASE + "/app/dialog/", wait_until="networkidle")
        operator.wait_for_timeout(700)
        operator.fill(".dlg-box textarea", "帮我做 9 月的报告")
        operator.click(".dlg-send")
        operator.wait_for_timeout(2500)
        dlg3 = operator.inner_text("body")
        check("操作员可出报告（对话里给「覆盖重出」）",
              "覆盖重出" in dlg3 and "出稿仅管理员可用" not in dlg3, "")

        # ---- 3) 零报错（覆盖上面几次导航） ----
        check("工作台零 pageerror / console.error", not problems, "; ".join(problems[:3]))
        check("陈列馆（管理员）零 pageerror / console.error", not admin_shelf_problems,
              "; ".join(admin_shelf_problems[:3]))
        check("操作员零 pageerror / console.error", not op_problems,
              "; ".join(op_problems[:3]))

        browser.close()

    print("结果：" + ("全部通过" if not failures else f"{len(failures)} 项失败：{failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
