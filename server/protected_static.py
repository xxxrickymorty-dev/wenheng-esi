# -*- coding: utf-8 -*-
"""对内嵌报告内容的静态文件补上角色门。"""
from pathlib import PurePosixPath

from starlette.responses import JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from . import config


class AdminStaticFiles(StaticFiles):
    """仅匹配到的静态文件限管理员；其余页面与素材保持原有可访问性。"""

    def __init__(self, *args, protected_paths=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.protected_paths = {self._normal_path(p) for p in protected_paths}

    @staticmethod
    def _normal_path(path):
        return "/".join(PurePosixPath(path.replace("\\", "/")).parts)

    def _is_protected(self, path):
        normalized = self._normal_path(path)
        parts = PurePosixPath(normalized).parts
        if ".." in parts:
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
                return JSONResponse(
                    {"error": "需要管理员权限", "hint": "游客不能查看报告内容"},
                    status_code=403, headers={"Cache-Control": "no-store"})
        return await super().get_response(path, scope)
