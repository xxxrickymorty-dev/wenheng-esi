# -*- coding: utf-8 -*-
"""对内嵌报告内容的静态文件补上角色门。"""
import inspect
from pathlib import PurePosixPath

from starlette.responses import JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from . import config


class AdminStaticFiles(StaticFiles):
    """仅匹配到的静态文件限管理员；其余页面与素材保持原有可访问性。"""

    def __init__(self, *args, protected_paths=(), guest_responses=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.protected_paths = {self._normal_path(p) for p in protected_paths}
        self.guest_responses = {
            self._normal_path(path): callback for path, callback in (guest_responses or {}).items()
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
        if protected:
            user = scope.get("session", {}).get("user")
            if not user:
                return RedirectResponse("/login", status_code=303,
                                        headers={"Cache-Control": "no-store"})
            if config.role_of(user) != "admin":
                guest_response = self.guest_responses.get(self._normal_path(path))
                if guest_response:
                    response = guest_response()
                    if inspect.isawaitable(response):
                        response = await response
                    response.headers["Cache-Control"] = "private, no-store"
                    response.headers["Vary"] = "Cookie"
                    return response
                return JSONResponse(
                    {"error": "需要管理员权限", "hint": "游客不能查看报告内容"},
                    status_code=403, headers={"Cache-Control": "no-store"})
        response = await super().get_response(path, scope)
        if protected:
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Cookie"
        return response
