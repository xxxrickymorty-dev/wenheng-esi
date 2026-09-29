# -*- coding: utf-8 -*-
"""能力开关：`out/_ai/settings.json`（SPEC §2.4 / C3）。

- **原子写**：tmp（同目录）+ `os.replace`；半截文件不可能被读到。
- `run` 每调用读一次（mtime 缓存，毫秒级）——「关闭立即生效」不靠重建单例。
- 读失败：回退 **last-known-good**＋日志（不 fail-open）；没有 LKG 时按 fail-closed 全关。
- 每次变更追加一条审计行（kind=switch：ts/actor/capability/from/to）→ `out/_ai/ai_calls.jsonl`。
"""
from __future__ import annotations

import json
import logging
import pathlib
import time

from . import _record

log = logging.getLogger("wenheng.ai")

SCHEMA = 1


def defaults() -> dict:
    """默认开关：ready 能力全开（planned 能力不经开关，走 closed-未上线）。"""
    from . import _specs                                         # noqa: PLC0415

    return {c.id: bool(c.default_enabled) for c in _specs.CAPABILITIES}


class SwitchStore:
    """一份 settings.json 的读取缓存与写口。路径固定，实例可按 root 复用。"""

    def __init__(self, root):
        self.path = pathlib.Path(root) / "_ai" / "settings.json"
        self._mtime: float | None = None
        self._data: dict | None = None            # last-known-good

    # ---------------------------------------------------------------- 读
    def read(self) -> dict:
        try:
            st = self.path.stat()
        except OSError:
            # 文件不存在 = 从未配置 → 默认值；已有 LKG 则继续用 LKG（不 fail-open）。
            return self._data if self._data is not None else self._empty()
        if self._data is not None and self._mtime == st.st_mtime_ns:
            return self._data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("caps"), dict):
                raise ValueError("settings.json 形状不对")
            data = {"schema": int(raw.get("schema") or SCHEMA),
                    "caps": {k: bool(v) for k, v in raw["caps"].items()},
                    "updated": raw.get("updated") or {}}
        except (OSError, ValueError, json.JSONDecodeError) as e:
            if self._data is not None:
                log.warning("ai settings 读取失败（%s），沿用 last-known-good：%s", e, self.path)
                return self._data
            log.warning("ai settings 读取失败且无 last-known-good（%s），fail-closed 全关：%s",
                        e, self.path)
            return self._empty(enabled=False)
        self._mtime = st.st_mtime_ns
        self._data = data
        return data

    def _empty(self, enabled: bool = True) -> dict:
        caps = defaults()
        if not enabled:
            caps = {k: False for k in caps}
        return {"schema": SCHEMA, "caps": caps, "updated": {}}

    # ---------------------------------------------------------------- 写
    def set(self, capability: str, enabled: bool, *, actor: str) -> None:
        """唯一写口；仅 admin（调用方已判）。原子写 + 审计行。"""
        cur = self.read()
        old = bool(cur["caps"].get(capability, False))
        caps = dict(cur["caps"])
        caps[capability] = bool(enabled)
        payload = {"schema": SCHEMA, "caps": caps,
                   "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}}
        _record.atomic_write_text(self.path,
                                  json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        self._mtime = self.path.stat().st_mtime_ns
        self._data = {"schema": SCHEMA, "caps": caps, "updated": payload["updated"]}
        audit = _record.build_switch(ts=payload["updated"]["ts"], actor=actor,
                                     capability=capability, from_=old, to=enabled)
        if not _record.append(_record.switch_path(self.path.parent.parent), audit):
            log.warning("ai 开关审计写失败（开关本身已生效）：%s", capability)


_STORES: dict[str, SwitchStore] = {}


def store_for(root) -> SwitchStore:
    """按 root 复用（保留 mtime 缓存）；进程内并发读安全（GIL 下 dict 读）。"""
    key = str(pathlib.Path(root).resolve())
    st = _STORES.get(key)
    if st is None:
        st = SwitchStore(root)
        _STORES[key] = st
    return st
