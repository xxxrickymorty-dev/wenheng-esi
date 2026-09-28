# -*- coding: utf-8 -*-
"""对内嵌报告内容的静态文件补上角色门。"""
import inspect
from pathlib import PurePosixPath

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from . import config


def _wants_html(scope):
    """导航请求（浏览器地址栏/链接）才给登录门页面；fetch/素材照旧 303。"""
    for name, value in scope.get("headers") or ():
        if name == b"accept":
            return b"text/html" in value.lower()
    return False


def _login_gate_response():
    """未登录导航请求：显示「请先登录」页（不跳转），按钮指向 /login。"""
    try:
        html = (config.SERVER_DIR / "static" / "gate.html").read_text(encoding="utf-8")
    except OSError:
        html = ("<!doctype html><meta charset='utf-8'>"
                "<h1>请先登录</h1><p><a href=\"/login\">前往登录</a></p>")
    return HTMLResponse(html, status_code=200, headers={"Cache-Control": "no-store"})


class AdminStaticFiles(StaticFiles):
    """挂载级门 + 单文件角色门。

    - `require_login=True`：**整个挂载只许已登录**（游客或管理员），未登录一律 303 回
      `/login`——`/app` 用它挡住「直接输网址进工作区」；找不到的文件也先回登录页，
      不泄漏路径存在性。
    - `protected_paths`：挂载内个别文件的角色门（照旧；组合使用时先过登录门）。
    """

    def __init__(self, *args, protected_paths=(), guest_responses=None,
                 admin_responses=None, require_login=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_login = require_login
        self.protected_paths = {self._normal_path(p) for p in protected_paths}
        self.guest_responses = {
            self._normal_path(path): callback for path, callback in (guest_responses or {}).items()
        }
        self.admin_responses = {
            self._normal_path(path): callback for path, callback in (admin_responses or {}).items()
        }

    @staticmethod
    def _normal_path(path):
        """生成与 Windows 文件系统别名一致的相对路径。"""
        normalized = PurePosixPath(str(path).replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            return None
        if not normalized.parts:
            return ""
        parts = [part.rstrip(" .").casefold() for part in normalized.parts]
        if any(not part for part in parts):
            return None
        return "/".join(parts)

    def _is_protected(self, path):
        normalized = self._normal_path(path)
        if normalized is None:
            return None
        return normalized in self.protected_paths

    async def get_response(self, path, scope):
        protected = self._is_protected(path)
        if protected is None:
            return JSONResponse({"error": "文件路径不合法"}, status_code=404)
        user = scope.get("session", {}).get("user")
        if self.require_login and not user:
            if _wants_html(scope):
                return _login_gate_response()
            return RedirectResponse("/login", status_code=303,
                                    headers={"Cache-Control": "no-store"})
        if protected:
            if not user:
                return RedirectResponse("/login", status_code=303,
                                        headers={"Cache-Control": "no-store"})
            normalized_path = self._normal_path(path)
            callback = (self.admin_responses if config.role_of(user) == "admin"
                        else self.guest_responses).get(normalized_path)
            if callback:
                response = callback()
                if inspect.isawaitable(response):
                    response = await response
                response.headers["Cache-Control"] = "private, no-store"
                response.headers["Vary"] = "Cookie"
                return response
            if config.role_of(user) != "admin":
                return JSONResponse(
                    {"error": "需要管理员权限", "hint": "游客不能查看报告内容"},
                    status_code=403, headers={"Cache-Control": "no-store"})
        response = await super().get_response(path, scope)
        if protected:
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Cookie"
        return response
