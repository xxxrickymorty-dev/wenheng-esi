# -*- coding: utf-8 -*-
"""Clarivate 会话过期自动重登（ESI / InCites 取数脚本共用）。

取数脚本经 CDP 附着「取数专用浏览器」；本模块在会话过期时自动完成重登：
Chrome 已保存的密码 + 站点带出的账号（loginId）自动填表 → 脚本只点「Sign in / 登录」（可信点击）→ 等回到应用。

两条安全线（有意为之）：
- **凭据零落盘**：账号 / 密码从不写入任何仓库文件，密码也从不进入本模块；
  脚本只检查登录页输入框「有没有被填上」，填不上就停。
  唯一例外（2026-10-17，rick 明示要预填）：**账号（邮箱）**在用户显式放入
  `~/.chrome-clarivate/email.txt` 或设 `WENHENG_CLARIVATE_EMAIL` 时，用于预填登录页账号栏
  （Chrome 的保存项对本站只自动填密码、不填账号）——默认什么都不存，密码仍只靠 Chrome。
- **填不上就停**：字段没自动填充、点了没回到应用（疑似风控 / 验证码）——
  一律报「请人工登录一次」，绝不代替人做验证、绝不猜密码。

对外入口：ensure_login(page, site)；会话探测：session_alive(page, site)。
（不 import playwright：本模块可被任何解释器安全导入，类型全靠鸭子类型。）
"""
from __future__ import annotations

import os
import pathlib
import re
import time

#: 各站：应用域名（点完 Sign in 等它出现）/ 会话探测口 / 站点根（重定向出的登录页带 loginId）
_SITES = {
    "esi": {
        "app_host": "esi.clarivate.com",
        "probe": "https://esi.clarivate.com/IndicatorsAction.action?app=esi&Init=Yes",
        "root": "https://esi.clarivate.com/",
    },
    "incites": {
        "app_host": "incites.clarivate.com",
        "probe": "https://incites.clarivate.com/config",
        "root": "https://incites.clarivate.com/",
    },
}

#: 登录页的账号（邮箱）栏——实测本机 Chrome 只自动填密码、不填账号；账号靠 URL 的 loginId
_EMAIL_SEL = 'input[name="email"], input[type="email"], input[autocomplete="email"]'

_LOGIN_MARK = "access.clarivate.com/login"

#: 账号（邮箱）预填来源（**仓外**本地文件；密码无此机制）——用户显式放置才生效
_EMAIL_FILE = pathlib.Path.home() / ".chrome-clarivate" / "email.txt"


def _prefill_email() -> str:
    """显式配置的账号（邮箱）：`WENHENG_CLARIVATE_EMAIL` > `~/.chrome-clarivate/email.txt`；没有则 ""。

    只用于预填登录页账号栏（Chrome 只自动填密码不填账号，缺账号时表单校验会静默挡下）。
    **密码没有任何来源**——仍然只靠 Chrome 自己填。
    """
    env = (os.environ.get("WENHENG_CLARIVATE_EMAIL") or "").strip()
    if env:
        return env
    try:
        # utf-8-sig：Windows 编辑器/Powershell 存的文件常带 BOM，别让它混进账号
        return (_EMAIL_FILE.read_text(encoding="utf-8-sig").splitlines() or [""])[0].strip()
    except OSError:
        return ""


def _on_login_page(page) -> bool:
    return _LOGIN_MARK in page.url


def session_alive(page, site: str) -> bool:
    """带会话 cookie 探测应用：活着 = 没被带去登录页 / 拿得到会话标识。

    判据与取数台 preflight（acquire.py `_PROBE`）同款：ESI 看正文有无登录页字样；
    InCites 看 `/config` 响应头 `pssid`。
    """
    cfg = _SITES[site]
    try:
        r = page.request.get(cfg["probe"], timeout=20_000, max_redirects=3)
        if "access.clarivate.com" in r.url:
            return False
        if site == "incites":
            return bool(r.headers.get("pssid"))
        low = r.text()[:4000].lower()
        return not ("sign in" in low or "log in" in low or "password" in low)
    except Exception:                                        # noqa: BLE001
        return False


def _email_filled(page):
    """登录页账号栏是否已填：True 已填 / False 空 / None 找不到该栏（界面变体）。"""
    loc = page.locator(_EMAIL_SEL).first
    try:
        if not loc.count():
            return None
        return bool((loc.input_value() or "").strip())
    except Exception:                                        # noqa: BLE001
        return None


def _goto_login(page, site: str) -> None:
    """把页面带到本站的登录页（走站点根——实测其重定向出的登录页会带 loginId/预填账号）。"""
    app_host = _SITES[site]["app_host"]
    try:
        page.goto(_SITES[site]["root"], wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_url(lambda u: _LOGIN_MARK in u, timeout=30_000)
    except Exception:                                        # noqa: BLE001
        if session_alive(page, site):
            return                                           # 探测误报，其实还活着（静默复登）
        raise SystemExit(
            f"[需要人工] 没能把页面带到 {app_host} 的登录页——请打开取数浏览器人工看一眼。"
        )


def _wait_for_autofill(page, timeout_s: float = 15) -> None:
    """等 Chrome 把保存的密码填进登录表单；没填上就叫停（绝不猜凭据）。

    ⚠ 实测（2026-10-14）：本机 Chrome 的保存项**只自动填密码、不填邮箱**；邮箱靠登录
    URL 的 `loginId` 参数（站点从「浏览器记住的账号」带出）。缺一，点 Sign in 会被表单
    校验静默挡下——所以邮箱栏为空时先用 `_prefill_email()`（用户显式放置的账号）预填，
    还填不上就叫停，别让它白点。
    """
    pw = page.locator('input[type="password"]').first
    try:
        pw.wait_for(state="visible", timeout=20_000)
    except Exception:                                        # noqa: BLE001
        raise SystemExit("[需要人工] 登录页上没等到密码框——请打开取数浏览器人工看一眼。")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if (pw.input_value() or "").strip():
            break
        page.wait_for_timeout(500)
    else:
        raise SystemExit(
            "[需要人工] 登录页的密码没有被自动填充——请在取数浏览器里人工登录一次"
            "（登录时保存密码，之后 Chrome 才能自动填）。"
        )
    email = page.locator(_EMAIL_SEL).first
    if email.count():                                        # 找到账号栏才拦；界面变体没有就放行
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            if (email.input_value() or "").strip():
                return
            page.wait_for_timeout(500)
        pre = _prefill_email()                               # 显式配置过账号才代填（仍不碰密码）
        if pre:
            try:
                email.fill(pre)
            except Exception:                                # noqa: BLE001
                pass
            if (email.input_value() or "").strip():
                return
        raise SystemExit(
            "[需要人工] 登录页的账号栏是空的（Chrome 没有预填账号）——"
            "请在取数浏览器里人工登录一次，或把账号放入 ~/.chrome-clarivate/email.txt。"
        )


def _click_sign_in(page, site: str, *, timeout_ms: int = 60_000) -> None:
    """点「Sign in / 登录」并等回到应用；点不动的（没反应）会再试，最多 3 次。"""
    app_host = _SITES[site]["app_host"]
    btn = page.get_by_role("button", name=re.compile(r"^\s*(Sign in|登录)\s*$")).first
    try:
        btn.wait_for(state="visible", timeout=10_000)
    except Exception:                                        # noqa: BLE001
        raise SystemExit("[需要人工] 登录页没找到「Sign in / 登录」按钮——请人工看一眼。")
    page.wait_for_timeout(1_000)                             # 等表单 handler 接稳（点太早会静默无反应）
    per_try = max(timeout_ms // 3, 15_000)
    for _ in range(3):
        btn.click(timeout=15_000)
        try:
            page.wait_for_url(lambda u: app_host in u, timeout=per_try)
            return
        except Exception:                                    # noqa: BLE001
            pass
        try:                                                 # 也许导航发生在新页签里
            if any(app_host in p.url for p in page.context.pages):
                return
        except Exception:                                    # noqa: BLE001
            pass
        if not _on_login_page(page):
            return                                           # 已离开登录页——由上层会话探测复验
        page.wait_for_timeout(1_500)
    raise SystemExit(
        "[需要人工] 点「Sign in」后一直没回到应用——可能密码已改或出现验证码；"
        "请在取数浏览器里人工处理后再重试。"
    )


def ensure_login(page, site: str, *, timeout_ms: int = 60_000) -> None:
    """会话过期（或已停在登录页）→ 自动点 Sign in 重登；会话活着 → 零动作。

    取数走 cookie（page.request），页面停在哪不影响导出：
    活 → 直接返回；死 → 把页面带到本站登录页 → 自动重登 → 复验。
    """
    if site not in _SITES:
        raise SystemExit(f"[参数错误] 未知站点 {site}（可用：{'/'.join(_SITES)}）")
    app_host = _SITES[site]["app_host"]
    if session_alive(page, site):
        print(f"[i] {app_host} 会话有效")
        return
    print(f"[i] {app_host} 会话过期——自动重登（Chrome 自动填表 + 点 Sign in）")
    page.bring_to_front()
    if not (_on_login_page(page) and f"app={site}" in page.url):
        _goto_login(page, site)                              # 不在本站登录页 → 去（重定向会带 loginId）
    if session_alive(page, site):                            # 静默复登（SSO/记住还在）——表单都不用点
        print(f"[i] {app_host} 会话有效")
        return
    if _email_filled(page) is False:
        _goto_login(page, site)                              # 账号栏空（无 loginId 版）→ 回根换带 loginId 的版本
        if session_alive(page, site):
            print(f"[i] {app_host} 会话有效")
            return
    pw = page.locator('input[type="password"]').first
    try:
        pw.wait_for(state="visible", timeout=8_000)
    except Exception:                                        # noqa: BLE001
        if session_alive(page, site):                        # 没表单 ≠ 没登录（可能刚被 SSO 静默带回去）
            print(f"[i] {app_host} 会话有效")
            return
        page.wait_for_timeout(2_000)
        if session_alive(page, site):
            print(f"[i] {app_host} 会话有效")
            return
        raise SystemExit("[需要人工] 没等到登录表单（页面卡在中间态）——请打开取数浏览器人工看一眼。")
    _wait_for_autofill(page)
    _click_sign_in(page, site, timeout_ms=timeout_ms)
    if not session_alive(page, site):
        raise SystemExit("[需要人工] 重登后会话探测仍不通过——请在取数浏览器里人工确认。")
    print(f"[i] 已自动重登 {app_host} ✓")
