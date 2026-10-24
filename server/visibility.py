# -*- coding: utf-8 -*-
"""证据面可见性：角色 × 证据类 × 动作的**唯一**决定。

`server/app.py` 里的四个下载门、三个产物清单投影、运行档案的日志包链接，
以及前端的 `canSeeAdminBits / canDownload / canEdit`，都只通过这里的
`allowed` / `visible` / `capabilities` 得到答案；门和页面只是 adapter。

证据类用**证据是什么**命名（红色件、运行日志、日志包、报告、图表……），
不是下载路由上的 key 字符串。这样新增一个门、一个清单或一个页面时，
规则只改这里，pytest 也只测这里。
"""
from __future__ import annotations

from typing import Any, Iterable

#: 证据类 → 馆员看的名字（只用于文档/测试可读性，不直接上屏）。
EVIDENCE: dict[str, str] = {
    "red_list": "红色件清单（Markdown）",
    "red_view": "红色件清单（页面）",
    "red_json": "红色件清单（JSON）",
    "runlog": "运行日志",
    "logpack": "运行日志包",
    "report": "报告初稿",
    "chart": "图表",
    "collation": "对勘本",
    "acquisition": "取数副本",
    "archive": "运行档案",
    "trace": "逐格溯源",
    "redslots": "红色件清单数据",
    "ai_calls": "模型调用留痕",
    "water": "学科水位",
    "sandbox": "沙盘故事卡",
    "ledger": "原始主台账",
}

#: 只给管理员的证据类：红色件三件、运行日志、日志包、原始主台账。
#: 这与 2026-10-11 / 2026-10-20 的契约边界一致；不是“所有写口”。
ADMIN_ONLY: frozenset[str] = frozenset({
    "red_list", "red_view", "red_json", "runlog", "logpack", "ledger",
})

#: 页面/工作区的可见性：只有原始主台账是 admin；其余证据面对操作员只读开放。
VIEWS: dict[str, str] = {
    "workbench": "user",
    "acquire": "user",
    "pick": "user",
    "report": "user",
    "review": "user",
    "analysis": "user",
    "red": "user",
    "charts": "user",
    "reading": "user",
    "trace": "user",
    "forecast": "user",
    "pano": "user",
    "archive": "user",
    "heal": "user",
    "migrate": "user",
    "ledger": "admin",
}

#: 写动作的权限：签单/出稿/取数对操作员开放（2026-10-12/10-17 政策）；
#: 在线填写、回滚、原始台账仍 admin。
ACTIONS: dict[str, str] = {
    "sign": "user",
    "run": "user",
    "acquire": "user",
    "edit": "admin",
    "rollback": "admin",
    "switch_model": "admin",
}

_ROLES = ("admin", "operator")


def _role(role: Any) -> str:
    return role if role in _ROLES else "operator"


def allowed(role: Any, evidence: str, action: str = "see") -> bool:
    """角色能否对某证据类做某动作。

    证据类的 admin-only 规则不因动作改变（看、列、下载同一条边界）；
    动作参数保留给将来“可看不可下载”的细分，目前是显式的占位。
    """
    del action
    return _role(role) == "admin" or str(evidence) not in ADMIN_ONLY


def view_allowed(role: Any, view: str) -> bool:
    return _role(role) == "admin" or VIEWS.get(str(view), "user") != "admin"


def action_allowed(role: Any, action: str) -> bool:
    return _role(role) == "admin" or ACTIONS.get(str(action), "admin") != "admin"


def visible(role: Any, items: Iterable[dict]) -> list[dict]:
    """产物清单投影：adapter 只管形状，决定仍走 allowed。"""
    return [a for a in items
            if allowed(role, str((a or {}).get("key") or ""), "list")]


def capabilities(role: Any) -> dict:
    """一个 module 的完整答案，给 `/api/me` 与前端的只读视图。

    前端不再把 `role === 'admin'` 抄在六个组件里；它读这一份表。
    """
    role = _role(role)
    return {
        "views": {name: view_allowed(role, name) for name in VIEWS},
        "see": {name: allowed(role, name, "see") for name in EVIDENCE},
        "download": {name: allowed(role, name, "download") for name in EVIDENCE},
        "actions": {name: action_allowed(role, name) for name in ACTIONS},
    }
