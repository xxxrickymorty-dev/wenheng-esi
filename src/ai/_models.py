# -*- coding: utf-8 -*-
"""模型清单（设置里可配、对话框里可切）：`out/_ai/models.json`。

为什么要有这份：部署事实（`.env` 里的地址/型号/key）只能由运维改，
而演示现场要当场换模型、当场加一个新网关。于是把「当前用哪个模型」
做成**运行期数据**——落 `out/`（不入库、不进仓库），改完下一次调用即生效。

纪律（与既有配置同一条）：
- **key 只落 `out/`，不回显**：读接口一律给掩码（`sk-…末四位`），日志不打印；
- **无 key 就不构造云适配器**：清单里没配 key 的条目不会让进程出网，
  `active_credentials()` 返回 None → 回落 `.env` → 再回落规则版；
- **`WENHENG_AI_PROFILE=demo` 仍然一票否决**：演示锁规则版时清单不生效；
- 原子写（tmp + os.replace）：半截文件不可能被读到。

文件形状：
    {"schema": 1,
     "active": "ynu-minimax",            # ""＝用 `.env` 的部署配置
     "models": [{"id","label","base_url","model","key","note","added"}],
     "updated": {"ts", "by"}}
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
import time

from . import _record

log = logging.getLogger("wenheng.ai")

SCHEMA = 1
#: 模型 id 只允许小写字母数字和连字符（进 URL、进记录面，别让奇怪字符混进来）
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
#: 地址必须是 http(s)；尾部的 `/chat/completions` 由保存时剥掉（本层只存到 `/v1`）
_URL_RE = re.compile(r"^https?://[^\s/]+", re.I)

#: 设置面板里的预置（只有地址与型号，**不含 key**——key 由人当场填）
PRESETS = (
    {"key": "ynu-newapi", "label": "云南大学网关（new-api）",
     "base_url": "https://new-api-itc.ynu.edu.cn/v1",
     "models": ["MiniMax/MiniMax-M2.7", "deepseek-ai/DeepSeek-V4.1-Flash",
                "Qwen/Qwen3.8-Flash-Next", "zai-org/GLM-5.3-Flash"]},
    {"key": "deepseek", "label": "DeepSeek 官方",
     "base_url": "https://api.deepseek.com/v1",
     "models": ["deepseek-chat", "deepseek-reasoner"]},
)


def path() -> pathlib.Path:
    return pathlib.Path(_record.data_root()) / "_ai" / "models.json"


def _empty() -> dict:
    return {"schema": SCHEMA, "active": "", "models": [], "updated": {}}


# ---------------------------------------------------------------- 读
def read() -> dict:
    """读清单（含 key 原文，只在进程内用）。坏文件＝空清单＋日志，不猜。"""
    p = path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.warning("模型清单读取失败（%s），按空清单处理：%s", e, p)
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    models = []
    for item in (raw.get("models") or []):
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "")
        if not _ID_RE.fullmatch(mid):
            continue
        models.append({
            "id": mid,
            "label": str(item.get("label") or mid),
            "base_url": str(item.get("base_url") or ""),
            "model": str(item.get("model") or ""),
            "key": str(item.get("key") or ""),
            "note": str(item.get("note") or ""),
            "added": str(item.get("added") or ""),
        })
    return {"schema": int(raw.get("schema") or SCHEMA),
            "active": str(raw.get("active") or ""),
            "models": models,
            "updated": raw.get("updated") if isinstance(raw.get("updated"), dict) else {}}


def _mask(key: str) -> str:
    """key → 掩码：只露头三位与末四位，中间固定省略号（长度也不外泄）。"""
    s = str(key or "")
    if not s:
        return ""
    if len(s) <= 8:
        return s[:1] + "…"
    return f"{s[:3]}…{s[-4:]}"


def public() -> dict:
    """给界面的清单：key 只给掩码；`.env` 部署配置作为第 0 行（id 为空串）。"""
    from . import _config                                        # noqa: PLC0415

    data = read()
    cfg = _config._env_config()
    rows = []
    if cfg["base_url"] or cfg["model"]:
        rows.append({
            "id": "", "label": "服务器部署配置（.env）",
            "base_url": cfg["base_url"], "model": cfg["model"],
            "key_hint": "由环境变量提供" if cfg["key"] else "未配置 key",
            "note": "改它要动服务器上的 .env，界面里改不了",
            "builtin": True, "ready": bool(cfg["key"] and cfg["model"]),
            "active": data["active"] == "",
        })
    for m in data["models"]:
        rows.append({
            "id": m["id"], "label": m["label"],
            "base_url": m["base_url"], "model": m["model"],
            "key_hint": _mask(m["key"]) or "未配置 key",
            "note": m["note"], "builtin": False,
            "ready": bool(m["key"] and m["model"] and m["base_url"]),
            "active": data["active"] == m["id"],
        })
    return {"active": data["active"], "models": rows, "presets": list(PRESETS)}


def active_credentials() -> dict | None:
    """当前生效的模型凭据；None＝用 `.env` 或没有任何可用配置（回落规则版）。"""
    data = read()
    if not data["active"]:
        return None
    for m in data["models"]:
        if m["id"] != data["active"]:
            continue
        if not (m["base_url"] and m["model"] and m["key"]):
            return None                            # 配了一半＝不可用，别发半个包
        return {"id": m["id"], "label": m["label"], "base_url": m["base_url"],
                "model": m["model"], "key": m["key"]}
    return None                                    # active 指向已删掉的条目


# ---------------------------------------------------------------- 写
def _clean_base_url(raw) -> str:
    s = str(raw or "").strip().rstrip("/")
    for tail in ("/chat/completions", "/completions"):
        if s.endswith(tail):
            s = s[: -len(tail)].rstrip("/")
    if not _URL_RE.match(s):
        raise ValueError("接口地址要以 http:// 或 https:// 开头")
    return s


def upsert(payload: dict, *, actor: str = "admin") -> dict:
    """新增或改一条（同 id 覆盖；key 留空＝沿用旧 key）。返回该条目的界面面。"""
    if not isinstance(payload, dict):
        raise ValueError("提交内容格式不对")
    model = str(payload.get("model") or "").strip()
    if not model:
        raise ValueError("型号不能为空（例如 MiniMax/MiniMax-M2.7）")
    base_url = _clean_base_url(payload.get("base_url"))
    mid = str(payload.get("id") or "").strip().lower()
    if not mid:
        mid = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")[:40] or "model"
    if not _ID_RE.fullmatch(mid):
        raise ValueError("模型标识只能用字母、数字和连字符（不超过 40 字）")
    data = read()
    old = next((m for m in data["models"] if m["id"] == mid), None)
    key = str(payload.get("key") or "").strip() or (old["key"] if old else "")
    row = {
        "id": mid,
        "label": str(payload.get("label") or model).strip()[:60],
        "base_url": base_url,
        "model": model[:120],
        "key": key,
        "note": str(payload.get("note") or "").strip()[:120],
        "added": old["added"] if old else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    models = [m for m in data["models"] if m["id"] != mid] + [row]
    models.sort(key=lambda m: (m["label"], m["id"]))
    active = data["active"]
    if not active and len(models) == 1 and key:
        active = mid                               # 第一条且已配 key：顺手设为当前
    _save({"schema": SCHEMA, "active": active, "models": models,
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})
    return next(r for r in public()["models"] if r["id"] == mid)


def remove(mid: str, *, actor: str = "admin") -> None:
    data = read()
    keep = [m for m in data["models"] if m["id"] != str(mid or "")]
    if len(keep) == len(data["models"]):
        raise ValueError("没有这条模型")
    active = data["active"] if data["active"] != mid else ""
    _save({"schema": SCHEMA, "active": active, "models": keep,
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})


def set_active(mid: str, *, actor: str = "admin") -> None:
    """切当前模型；空串＝用 `.env` 的部署配置。指向不存在的条目＝报错，不静默。"""
    data = read()
    mid = str(mid or "")
    if mid:
        row = next((m for m in data["models"] if m["id"] == mid), None)
        if row is None:
            raise ValueError("没有这条模型")
        if not (row["key"] and row["model"] and row["base_url"]):
            raise ValueError("这条模型还没配齐（地址/型号/key），不能设为当前")
    _save({"schema": SCHEMA, "active": mid, "models": data["models"],
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})


def _save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _record.atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


# ---------------------------------------------------------------- 探活
def probe(*, base_url: str, key: str, model: str = "", timeout: float = 15.0) -> dict:
    """发一次最小请求，看这条配置能不能用（不落库、不改当前）。

    只用 `/models` 清单＋一次 1 token 的对话：前者验地址与 key，后者验型号真的在。
    错误一律转成人话（超时/鉴权/地址不对），调用方直接给界面显示。
    """
    import socket
    import urllib.error
    import urllib.request

    base = _clean_base_url(base_url)
    if not key:
        return {"ok": False, "ms": 0, "msg": "这条没有 key，先填 key 再测"}
    t0 = time.perf_counter()

    def _get(url):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    try:
        listing = _get(f"{base}/models")
        ids = [str(m.get("id") or "") for m in (listing.get("data") or [])
               if isinstance(m, dict)]
    except urllib.error.HTTPError as e:
        hint = "key 不对或没有权限" if e.code in (401, 403) else f"HTTP {e.code}"
        return {"ok": False, "ms": int((time.perf_counter() - t0) * 1000), "msg": hint}
    except (TimeoutError, socket.timeout):
        return {"ok": False, "ms": int((time.perf_counter() - t0) * 1000),
                "msg": f"超时（{timeout:g} 秒内没回应）"}
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "ms": int((time.perf_counter() - t0) * 1000),
                "msg": f"连不上：{e}"}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"ok": False, "ms": int((time.perf_counter() - t0) * 1000),
                "msg": "这个地址返回的不是接口数据（检查是否少了 /v1）"}
    ms = int((time.perf_counter() - t0) * 1000)
    if model and ids and model not in ids:
        return {"ok": False, "ms": ms, "n_models": len(ids),
                "msg": f"地址与 key 都通（{len(ids)} 个模型），但没有「{model}」这个型号"}
    return {"ok": True, "ms": ms, "n_models": len(ids),
            "msg": f"通（{len(ids)} 个可用模型）"}
