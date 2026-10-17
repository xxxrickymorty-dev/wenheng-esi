# -*- coding: utf-8 -*-
"""登录页账号（邮箱）预填（2026-10-17，rick 明示）与「填不上就停」的边界。

背景：本机 Chrome 的保存项对 Clarivate 登录页**只自动填密码、不填账号**（2026-10-14 实测），
账号栏为空时表单校验会静默挡下 Sign in。模块只代填**显式放置**的账号
（`~/.chrome-clarivate/email.txt` 或 `WENHENG_CLARIVATE_EMAIL`）；密码仍只靠 Chrome，
没有任何来源——「凭据零落盘」的红线只对账号开了显式例外。
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

import pytest                                                            # noqa: E402

import clarivate_login as cl                                             # noqa: E402


class _Clock:
    """单调递增的假时钟：让「等 5 秒」的轮询在几轮内走完。"""

    def __init__(self):
        self.n = 0.0

    def monotonic(self) -> float:
        self.n += 1.0
        return self.n


class _Loc:
    def __init__(self, value: str = ""):
        self._v = value
        self.filled: str | None = None

    @property
    def first(self):                                       # page.locator(...).first
        return self

    def wait_for(self, **kw):
        return None

    def count(self) -> int:
        return 1

    def input_value(self) -> str:
        return self._v

    def fill(self, v: str) -> None:
        self.filled = v
        self._v = v


class _Page:
    def __init__(self, *, pw: str = "saved-by-chrome", email: str = ""):
        self.pw = _Loc(pw)
        self.email = _Loc(email)

    def locator(self, sel: str):
        return self.pw if "password" in sel else self.email

    def wait_for_timeout(self, ms: int) -> None:
        return None


# ------------------------------------------------------------------ 账号来源
def test_预填来源_环境变量优先(tmp_path, monkeypatch):
    monkeypatch.setenv("WENHENG_CLARIVATE_EMAIL", "env@x.com")
    monkeypatch.setattr(cl, "_EMAIL_FILE", tmp_path / "email.txt")
    (tmp_path / "email.txt").write_text("file@x.com\n", encoding="utf-8")
    assert cl._prefill_email() == "env@x.com"


def test_预填来源_文件兜底_带BOM也认(tmp_path, monkeypatch):
    monkeypatch.delenv("WENHENG_CLARIVATE_EMAIL", raising=False)
    monkeypatch.setattr(cl, "_EMAIL_FILE", tmp_path / "email.txt")
    (tmp_path / "email.txt").write_bytes("\ufefflauvblue@163.com\r\n第二行不看\n".encode("utf-8"))
    assert cl._prefill_email() == "lauvblue@163.com"


def test_预填来源_都没有就空串(tmp_path, monkeypatch):
    monkeypatch.delenv("WENHENG_CLARIVATE_EMAIL", raising=False)
    monkeypatch.setattr(cl, "_EMAIL_FILE", tmp_path / "nope" / "email.txt")
    assert cl._prefill_email() == ""


# ------------------------------------------------------------------ _wait_for_autofill 的代填行为
def test_账号栏空_显式配置过就代填(monkeypatch):
    monkeypatch.setattr(cl.time, "monotonic", _Clock().monotonic)
    monkeypatch.setenv("WENHENG_CLARIVATE_EMAIL", "lauvblue@163.com")
    pg = _Page(email="")
    cl._wait_for_autofill(pg)
    assert pg.email.filled == "lauvblue@163.com"


def test_账号栏空_没配置就叫停并指路(monkeypatch):
    monkeypatch.setattr(cl.time, "monotonic", _Clock().monotonic)
    monkeypatch.delenv("WENHENG_CLARIVATE_EMAIL", raising=False)
    monkeypatch.setattr(cl, "_EMAIL_FILE", pathlib.Path("Z:/nonexistent/email.txt"))
    pg = _Page(email="")
    with pytest.raises(SystemExit) as e:
        cl._wait_for_autofill(pg)
    assert "账号栏是空的" in str(e.value) and "email.txt" in str(e.value)
    assert pg.email.filled is None, "没配置就绝不代填"


def test_账号栏已有值_不覆盖(monkeypatch):
    monkeypatch.setattr(cl.time, "monotonic", _Clock().monotonic)
    monkeypatch.setenv("WENHENG_CLARIVATE_EMAIL", "other@x.com")
    pg = _Page(email="already@x.com")
    cl._wait_for_autofill(pg)
    assert pg.email.filled is None, "站点/Chrome 已带出的账号不许覆盖"


def test_密码没被填_照旧叫停_不碰密码(monkeypatch):
    monkeypatch.setattr(cl.time, "monotonic", _Clock().monotonic)
    monkeypatch.setenv("WENHENG_CLARIVATE_EMAIL", "lauvblue@163.com")
    pg = _Page(pw="", email="")
    with pytest.raises(SystemExit) as e:
        cl._wait_for_autofill(pg, timeout_s=0)
    assert "密码没有被自动填充" in str(e.value)
    assert pg.email.filled is None, "密码没过不许先填账号"
