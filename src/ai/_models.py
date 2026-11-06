# -*- coding: utf-8 -*-
"""模型清单 v2（2026-11-04）：**供应商＋模型目录**（照 DSH 图二形制）。

一条供应商＝一个网关接入（地址/key/协议/自定义头）＋一份**模型目录**
（从网关拉来的可用型号里挑出来的子集，可增删）；当前模型＝
「哪条供应商＋目录里哪个型号」。问文衡输入框左下的模型菜单、
设置里的供应商卡片都从这份清单读。

为什么要有这份：部署事实（`.env` 里的地址/型号/key）只能由运维改，
而演示现场要当场换模型、当场加一个新网关。于是把「当前用哪个模型」
做成**运行期数据**——落 `out/`（不入库、不进仓库），改完下一次调用即生效。

纪律（与既有配置同一条）：
- **key 只落 `out/`，不回显**：读接口一律给掩码，日志不打印；
- **无 key 就不构造云适配器**：清单里没配 key 的供应商不会让进程出网，
  `active_credentials()` 返回 None → 回落 `.env` → 再回落规则版；
- **`WENHENG_AI_PROFILE=demo` 仍然一票否决**：演示锁规则版时清单不生效；
- 原子写（tmp + os.replace）：半截文件不可能被读到。

文件形状（schema 2）：
    {"schema": 2,
     "active": {"provider": "ynu", "model": "MiniMax/MiniMax-M2.7"},
                   # provider 空串＝用 `.env` 的部署配置
     "providers": [{"id","label","base_url","key","protocol","headers",
                    "note","added","models": ["型号", …]}],
     "updated": {"ts", "by"}}

schema 1（旧：一条＝一个型号）读入时自动迁移：每条旧记录变成
「一条供应商＋单型号目录」；落盘即写 schema 2。
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
import time

from . import _record

log = logging.getLogger("wenheng.ai")

SCHEMA = 2
#: 协议三选（2026-11-04 rick 定：照 DSH 图三，三种都真实现）
PROTOCOLS = ("openai", "openai-responses", "anthropic")
#: 模型 id 只允许小写字母数字和连字符（进 URL、进记录面，别让奇怪字符混进来）
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
#: 地址必须是 http(s)；尾部的 `/chat/completions` 由保存时剥掉（本层只存到 `/v1`）
_URL_RE = re.compile(r"^https?://[^\s/]+", re.I)
#: 自定义请求头（票 4，2026-11-03）：名字只许字母数字连字符（合法 HTTP 头字符的收紧集），
#: 最多 8 条，值不能空——有的网关要靠自定义头路由/鉴权，但头是外发面，收着来。
_HEADER_KEY_RE = re.compile(r"^[A-Za-z0-9-]+$")
_HEADERS_MAX = 8
#: 一条供应商的模型目录上限（网关动辄几十个型号，目录是挑过的子集）
_MODELS_MAX = 64
#: 请求体附加参数的白名单（`params`，2026-11-05 rick：GLM-5.3-Flash 作默认模型）。
#: 只收「软」旋钮——结构键（model / messages / max_tokens / tools…）由适配器自己写，
#: 清单条目不许覆盖。`reasoning_effort`：推理型型号的思考深度，**空/不给＝网关缺省**；
#: 实测 GLM-5.3-Flash 缺省档会把整份输出预算花在思考上（正文 0 字、50–90 秒），
#: 低档 1.7 秒出正文——报告生成能否跑通全在这一个值上。
PARAM_CHOICES = {"reasoning_effort": ("minimal", "low", "medium", "high")}


def _clean_headers(raw) -> dict[str, str]:
    """表单提交的 headers 对象 → 干净的 dict；不合法当场报错（保存前拦下，不静默清洗）。"""
    if raw is None or raw == {}:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Headers 要是「名字=值」的集合（界面上每行一条 K=V）")
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip()
        value = str(v).strip()
        if not _HEADER_KEY_RE.fullmatch(key):
            raise ValueError(f"头名字只能用字母、数字和连字符：{key or '（空名字）'}")
        if not value:
            raise ValueError(f"头「{key}」的值不能为空")
        out[key] = value
    if len(out) > _HEADERS_MAX:
        raise ValueError(f"Headers 最多 {_HEADERS_MAX} 条（现在 {len(out)} 条）")
    return out


def _clean_params(raw) -> dict[str, str]:
    """表单提交的 params 对象 → 干净的 dict（白名单键 + 取值校验，不合法当场报错）。

    形状与 `_clean_headers` 同规矩：保存前拦下，不静默清洗、不猜。
    """
    if raw is None or raw == {}:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("附加参数要是「名字=值」的集合")
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip()
        value = str(v).strip()
        if key not in PARAM_CHOICES:
            raise ValueError(f"不认识的附加参数：{key}"
                             f"（只认 {'、'.join(PARAM_CHOICES)}）")
        if not value:
            continue                                   # 空值＝不传（网关缺省）
        allowed = PARAM_CHOICES[key]
        if value not in allowed:
            raise ValueError(f"「{key}」只能是 {' / '.join(allowed)}（现在 {value}）")
        out[key] = value
    return out


def _clean_models(raw) -> list[str]:
    """模型目录：型号串列表——去空白、去重（保序）、限长限量；空目录允许（＝还没挑）。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("模型目录要是型号的列表（界面上从「获取可用模型」里挑）")
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip()
        if not s:
            continue
        if len(s) > 120:
            raise ValueError(f"型号太长（超过 120 字）：{s[:30]}…")
        if s not in out:
            out.append(s)
    if len(out) > _MODELS_MAX:
        raise ValueError(f"模型目录最多 {_MODELS_MAX} 条（现在 {len(out)} 条）")
    return out


def _clean_protocol(raw) -> str:
    p = str(raw or "openai").strip()
    if p not in PROTOCOLS:
        raise ValueError(f"协议只认这三种：{' / '.join(PROTOCOLS)}")
    return p


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40]


def _id_for(label: str, base_url: str) -> str:
    """供应商 id：名字能拼就拼名字（拉丁字母），拼不出用地址主机名，再不行给常量。"""
    return _slug(label) or _slug(re.sub(r"^https?://", "", base_url).split("/")[0]) \
        or "provider"


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
    return {"schema": SCHEMA, "active": {"provider": "", "model": ""},
            "providers": [], "updated": {}}


# ---------------------------------------------------------------- 读
def _provider_item(item: dict) -> dict | None:
    """文件里一条供应商 → 干净的进程内形状；id 不合法＝丢弃（与 v1 同口径）。"""
    mid = str(item.get("id") or "")
    if not _ID_RE.fullmatch(mid):
        return None
    return {
        "id": mid,
        "label": str(item.get("label") or mid),
        "base_url": str(item.get("base_url") or ""),
        "key": str(item.get("key") or ""),
        "note": str(item.get("note") or ""),
        "added": str(item.get("added") or ""),
        "protocol": str(item.get("protocol") or "openai"),
        # headers 原样回（票 4）：保存前已校验过，读口不再清洗
        "headers": {str(k): str(v) for k, v in item["headers"].items()}
        if isinstance(item.get("headers"), dict) else {},
        # params 同规矩（2026-11-05）：只回白名单键，脏键丢弃不猜
        "params": {str(k): str(v) for k, v in item["params"].items()
                   if str(k) in PARAM_CHOICES} if isinstance(item.get("params"), dict) else {},
        "models": [str(m) for m in (item.get("models") or [])
                   if str(m or "").strip()],
    }


def _migrate_v1(raw: dict) -> dict:
    """schema 1（一条＝一个型号）→ schema 2：每条旧记录变成单型号供应商。"""
    providers = []
    for item in (raw.get("models") or []):
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        providers.append({**item, "models": [model] if model else []})
    active = str(raw.get("active") or "")
    return {"schema": SCHEMA,
            "active": {"provider": active, "model": ""},
            "providers": providers,
            "updated": raw.get("updated") if isinstance(raw.get("updated"), dict) else {}}


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
    if str(raw.get("schema") or "") == "1" or isinstance(raw.get("models"), list):
        raw = _migrate_v1(raw)                      # 旧清单（含 schema 未写全的）
    active_raw = raw.get("active")
    if isinstance(active_raw, dict):
        active = {"provider": str(active_raw.get("provider") or ""),
                  "model": str(active_raw.get("model") or "")}
    else:                                           # 只有 v1 迁移前的字符串形状
        active = {"provider": str(active_raw or ""), "model": ""}
    providers = [p for p in (_provider_item(i)
                             for i in (raw.get("providers") or [])
                             if isinstance(i, dict)) if p]
    # 当前型号必须真在目录里；不在＝回「该供应商第一个」（或清空）
    if active["provider"]:
        prov = next((q for q in providers if q["id"] == active["provider"]), None)
        if prov is None:
            active = {"provider": "", "model": ""}
        elif active["model"] not in prov["models"]:
            active["model"] = prov["models"][0] if prov["models"] else ""
    return {"schema": SCHEMA, "active": active,
            "providers": providers,
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
    """给界面的清单：key 只给掩码；`.env` 部署配置作为第 0 条供应商（id 为空串）。"""
    from . import _config                                        # noqa: PLC0415

    data = read()
    cfg = _config._env_config()
    rows = []
    if cfg["base_url"] or cfg["model"]:
        env_models = [cfg["model"]] if cfg["model"] else []
        rows.append({
            "id": "", "label": "服务器部署配置（.env）",
            "base_url": cfg["base_url"], "protocol": "openai",
            "key_hint": "由环境变量提供" if cfg["key"] else "未配置 key",
            "note": "改它要动服务器上的 .env，界面里改不了",
            "builtin": True, "models": env_models,
            "ready": bool(cfg["key"] and cfg["model"]),
            "active": data["active"]["provider"] == "",
            "active_model": cfg["model"] if data["active"]["provider"] == "" else "",
        })
    for p in data["providers"]:
        is_on = data["active"]["provider"] == p["id"]
        row = {
            "id": p["id"], "label": p["label"],
            "base_url": p["base_url"], "protocol": p["protocol"],
            "key_hint": _mask(p["key"]) or "未配置 key",
            "note": p["note"], "builtin": False,
            "models": list(p["models"]),
            "ready": bool(p["key"] and p["base_url"] and p["models"]),
            "active": is_on,
            "active_model": (data["active"]["model"] if is_on and data["active"]["model"]
                             else (p["models"][0] if p["models"] else "")),
        }
        if p["headers"]:
            row["headers"] = dict(p["headers"])    # 界面面只在配了时带（可选字段）
        if p["params"]:
            row["params"] = dict(p["params"])      # 同上：只配了才带
        rows.append(row)
    return {"active": dict(data["active"]), "providers": rows,
            "presets": list(PRESETS)}


def active_credentials() -> dict | None:
    """当前生效的模型凭据；None＝用 `.env` 或没有任何可用配置（回落规则版）。"""
    data = read()
    pid = data["active"]["provider"]
    if not pid:
        return None
    for p in data["providers"]:
        if p["id"] != pid:
            continue
        model = data["active"]["model"] or (p["models"][0] if p["models"] else "")
        if not (p["base_url"] and p["key"] and model):
            return None                            # 配了一半＝不可用，别发半个包
        return {"provider_id": p["id"], "label": p["label"],
                "base_url": p["base_url"], "model": model, "key": p["key"],
                "protocol": p["protocol"] or "openai",
                "headers": dict(p.get("headers") or {}),
                "params": dict(p.get("params") or {})}
    return None                                    # active 指向已删掉的供应商


# ---------------------------------------------------------------- 写
def _clean_base_url(raw) -> str:
    s = str(raw or "").strip().rstrip("/")
    for tail in ("/chat/completions", "/completions", "/messages", "/responses"):
        if s.endswith(tail):
            s = s[: -len(tail)].rstrip("/")
    if not _URL_RE.match(s):
        raise ValueError("接口地址要以 http:// 或 https:// 开头")
    return s


def upsert(payload: dict, *, actor: str = "admin") -> dict:
    """新增或改一条供应商（同 id 覆盖；key 留空＝沿用旧 key）。
    `models`＝整份模型目录（界面保存时随表单一起交）。返回该条的界面面。"""
    if not isinstance(payload, dict):
        raise ValueError("提交内容格式不对")
    base_url = _clean_base_url(payload.get("base_url"))
    models = _clean_models(payload.get("models"))
    protocol = _clean_protocol(payload.get("protocol"))
    label = str(payload.get("label") or "").strip()[:60]
    pid = str(payload.get("id") or "").strip().lower() or _id_for(label, base_url)
    if not _ID_RE.fullmatch(pid):
        raise ValueError("供应商标识只能用字母、数字和连字符（不超过 40 字）")
    data = read()
    old = next((p for p in data["providers"] if p["id"] == pid), None)
    key = str(payload.get("key") or "").strip() or (old["key"] if old else "")
    headers = _clean_headers(payload.get("headers"))
    # params 三态（2026-11-05）：不给＝沿用旧值；给 {}＝清空；给值＝整份替换。
    params = (_clean_params(payload.get("params")) if payload.get("params") is not None
              else dict(old.get("params") or {}) if old else {})
    row = {
        "id": pid,
        "label": label or pid,
        "base_url": base_url,
        "key": key,
        "note": str(payload.get("note") or "").strip()[:120],
        "added": old["added"] if old else time.strftime("%Y-%m-%dT%H:%M:%S"),
        "protocol": protocol,
        "models": models,
    }
    if headers:
        row["headers"] = headers
    if params:
        row["params"] = params
    providers = [p for p in data["providers"] if p["id"] != pid] + [row]
    providers.sort(key=lambda p: (p["label"], p["id"]))
    active = dict(data["active"])
    if not active["provider"] and len(providers) == 1 and key and models:
        active = {"provider": pid, "model": models[0]}   # 第一条且配齐：顺手设为当前
    if active["provider"] == pid:
        if models and active["model"] not in models:
            active["model"] = models[0]           # 目录改了：当前型号跟着目录走
        if not models or not key:
            active = {"provider": "", "model": ""}  # 目录清空/没了 key＝不再当前
    _save({"schema": SCHEMA, "active": active, "providers": providers,
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})
    return next(r for r in public()["providers"] if r["id"] == pid)


def remove(pid: str, *, actor: str = "admin") -> None:
    data = read()
    keep = [p for p in data["providers"] if p["id"] != str(pid or "")]
    if len(keep) == len(data["providers"]):
        raise ValueError("没有这条供应商")
    active = dict(data["active"])
    if active["provider"] == str(pid or ""):
        active = {"provider": "", "model": ""}     # 删掉当前项＝回到部署配置
    _save({"schema": SCHEMA, "active": active, "providers": keep,
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})


def set_active(pid: str, model: str = "", *, actor: str = "admin") -> None:
    """切当前模型（哪条供应商＋目录里哪个型号）；供应商空串＝用 `.env` 部署配置。
    指向不存在的供应商／不在目录里的型号＝报错，不静默。"""
    data = read()
    pid = str(pid or "")
    if not pid:
        _save({"schema": SCHEMA, "active": {"provider": "", "model": ""},
               "providers": data["providers"],
               "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})
        return
    row = next((p for p in data["providers"] if p["id"] == pid), None)
    if row is None:
        raise ValueError("没有这条供应商")
    if not (row["key"] and row["base_url"] and row["models"]):
        raise ValueError("这条供应商还没配齐（地址/key/模型目录），不能设为当前")
    model = str(model or "").strip() or row["models"][0]
    if model not in row["models"]:
        raise ValueError(f"「{model}」不在这条供应商的模型目录里")
    _save({"schema": SCHEMA, "active": {"provider": pid, "model": model},
           "providers": data["providers"],
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})


def set_reasoning_effort(effort: str, *, actor: str = "admin") -> None:
    """改「当前供应商」的思考深度（reasoning_effort；空串＝清掉＝网关缺省）。

    输入框菜单（2026-11-06，照 DSH 输入框的推理等级位）与供应商表单里的
    「思考深度」写的是**同一个值**：当前项的 `params.reasoning_effort`——
    一处存，两处改，下一句话即生效（`cloud_config` 现读）。
    当前项是 `.env` 部署配置（provider 空串）时拒绝：那行按 2026-11-05
    的决定不带 params（不给运维加第二个旋钮），要改去服务器 `.env`。
    """
    effort = str(effort or "").strip().lower()
    if effort and effort not in PARAM_CHOICES["reasoning_effort"]:
        raise ValueError("思考深度只认 minimal / low / medium / high"
                          "（或清掉＝用网关缺省）")
    data = read()
    pid = str(data["active"]["provider"] or "")
    if not pid:
        raise ValueError("当前用的是服务器部署配置（.env）——"
                          "思考深度在服务器的 .env 里配，界面改不了")
    row = next((p for p in data["providers"] if p["id"] == pid), None)
    if row is None:
        raise ValueError("没有这条供应商")
    params = dict(row.get("params") or {})
    if effort:
        params["reasoning_effort"] = effort
    else:
        params.pop("reasoning_effort", None)
    if params:
        row["params"] = params
    else:
        row.pop("params", None)                    # 空了就不落这个键（与 upsert 同形）
    _save({"schema": SCHEMA, "active": dict(data["active"]),
           "providers": data["providers"],
           "updated": {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": actor}})


def _save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _record.atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


# ---------------------------------------------------------------- 探活／拉型号
def _list_remote(*, base_url: str, key: str, headers: dict | None = None,
                 timeout: float = 15.0) -> tuple[list[str], int, str]:
    """拉网关的型号清单：`(ids, 耗时毫秒, 错误话)`——错了 ids 为空、错误话非空。"""
    import socket
    import urllib.error
    import urllib.request

    base = _clean_base_url(base_url)
    extra = _clean_headers(headers)
    if not key:
        return [], 0, "这条没有 key，先填 key 再测"
    t0 = time.perf_counter()

    def _get(url):
        req = urllib.request.Request(url, headers={**extra, "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    try:
        listing = _get(f"{base}/models")
        ids = [str(m.get("id") or "") for m in (listing.get("data") or [])
               if isinstance(m, dict) and str(m.get("id") or "").strip()]
    except urllib.error.HTTPError as e:
        hint = "key 不对或没有权限" if e.code in (401, 403) else f"HTTP {e.code}"
        return [], int((time.perf_counter() - t0) * 1000), hint
    except (TimeoutError, socket.timeout):
        return [], int((time.perf_counter() - t0) * 1000), f"超时（{timeout:g} 秒内没回应）"
    except (urllib.error.URLError, OSError) as e:
        return [], int((time.perf_counter() - t0) * 1000), f"连不上：{e}"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], int((time.perf_counter() - t0) * 1000), \
            "这个地址返回的不是接口数据（检查是否少了 /v1）"
    return ids, int((time.perf_counter() - t0) * 1000), ""


def fetch_models(*, base_url: str, key: str, headers: dict | None = None,
                 timeout: float = 15.0) -> dict:
    """「获取可用模型」（图二按钮）：拉网关型号清单给界面挑。不落库、不改当前。"""
    ids, ms, err = _list_remote(base_url=base_url, key=key,
                                headers=headers, timeout=timeout)
    if err:
        return {"ok": False, "ms": ms, "msg": err, "ids": []}
    return {"ok": True, "ms": ms, "msg": f"取到 {len(ids)} 个型号", "ids": ids}


def probe(*, base_url: str, key: str, model: str = "",
          headers: dict | None = None, timeout: float = 15.0) -> dict:
    """发一次最小请求，看这条配置能不能用（不落库、不改当前）。

    只用 `/models` 清单：验地址与 key；给了 `model` 再验型号真的在网关上。
    `headers`＝供应商条目/表单的自定义头（票 4）：与请求头合并探活，但 Authorization
    由这里出（测的就是这把 key），不许被覆盖。错误一律转成人话（超时/鉴权/地址不对），
    调用方直接给界面显示。
    """
    ids, ms, err = _list_remote(base_url=base_url, key=key,
                                headers=headers, timeout=timeout)
    if err:
        return {"ok": False, "ms": ms, "msg": err}
    if model and ids and model not in ids:
        return {"ok": False, "ms": ms, "n_models": len(ids),
                "msg": f"地址与 key 都通（{len(ids)} 个模型），但没有「{model}」这个型号"}
    return {"ok": True, "ms": ms, "n_models": len(ids),
            "msg": f"通（{len(ids)} 个可用模型）"}
