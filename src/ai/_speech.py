# -*- coding: utf-8 -*-
"""语音两端（ASR / TTS）：让「问文衡」能听能说（2026-11-02 rick 定）。

**为什么单独一层**：语音不是 AI 能力，它不进 `run()` 的能力表——`run()` 是
「读证据出句」，语音只是把话搬进/搬出，两边都不该看见台账。所以本模块只做两件事：
音频 → 文字（ASR）、文字 → 音频（TTS）。

红线（与 `_config` / `_models` 同一条，别越）：
1. **没 key 或 `WENHENG_AI_PROFILE=demo` → 不出网**：`status()` 直接说不可用，
   界面照「没配」显示；绝不静默降级成假语音（假语音比没有更坏）。
2. **语音不进数据路径**：ASR 只把人说的话变成字；TTS 只把**已经过盾、已经在屏幕上**
   的那段答案念出来。两者都不取数、不出句、不算数——数字仍只来自引擎。
3. **外发面只有答案正文**：TTS 发出去的字符＝用户已看见的那段（剥掉 `[[n]]` 引用标记、
   标题符号、表格行），不发提示词、不发证据单、不发台账；上限 `MAX_SPEAK_CHARS`。

网关按 OpenAI 兼容口径（new-api 两者都通）：
    POST {base}/audio/transcriptions   multipart(file, model)        → {"text": …}
    POST {base}/audio/speech           json(model, input, voice)     → audio/mpeg

部署（`.env`，都可选；不配就用默认值，网关与 key 跟模型清单共用同一个）：
    WENHENG_ASR_MODEL=Qwen/Qwen3-ASR-1.7B
    WENHENG_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
    WENHENG_TTS_VOICE=serena
    WENHENG_SPEECH_TIMEOUT=60
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger("wenheng.ai")

#: 默认型号（2026-11-02 在校内网关上实测：这句转写带标点、ESI 也不拆字母）
DEFAULT_ASR_MODEL = "Qwen/Qwen3-ASR-1.7B"
DEFAULT_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
#: 默认音色（该型号支持的音色见 `VOICES`；说错音色网关会 400 并把可选值列出来）
DEFAULT_TTS_VOICE = "serena"
VOICES = ("serena", "vivian", "aiden", "dylan", "eric", "ono_anna", "ryan", "sohee", "uncle_fu")

#: 一次录音的上限（8MB ≈ 几分钟的 webm/opus）；超了直接说，不发给网关
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
#: 一次播报的字符上限：念三分钟以上就是噪音，长答案只念开头，界面会说「只念了开头」
MAX_SPEAK_CHARS = 600


class SpeechError(RuntimeError):
    """语音不可用/失败——`str(e)` 就是给馆员看的那句话（人话，不含技术词）。"""


# ---------------------------------------------------------------- 配置
def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _cfg() -> dict:
    """语音用的网关与型号（每次现读：切模型/改 .env 下一句就生效）。"""
    from . import _config                                        # noqa: PLC0415

    cloud = _config.cloud_config()
    why = ""
    if cloud.get("profile") == "demo":
        why = "演示站锁了「只跑规则版」，语音也不联网"
    elif not cloud.get("base_url"):
        why = "还没配语音服务地址"
    elif not cloud.get("key"):
        why = "还没配语音服务的 key"
    return {
        "base_url": str(cloud.get("base_url") or "").rstrip("/"),
        "key": str(cloud.get("key") or ""),
        "asr_model": _env("WENHENG_ASR_MODEL", DEFAULT_ASR_MODEL),
        "tts_model": _env("WENHENG_TTS_MODEL", DEFAULT_TTS_MODEL),
        "voice": _env("WENHENG_TTS_VOICE", DEFAULT_TTS_VOICE),
        "timeout": float(_env("WENHENG_SPEECH_TIMEOUT", "60") or 60),
        "why": why,
    }


def status() -> dict:
    """界面读的能力面：能不能听、能不能说、为什么不能。纯读配置，无副作用。"""
    cfg = _cfg()
    ready = not cfg["why"]
    return {
        "ready": ready,
        "reason": cfg["why"],
        "asr": {"model": cfg["asr_model"], "ready": ready},
        "tts": {"model": cfg["tts_model"], "voice": cfg["voice"], "ready": ready,
                "voices": list(VOICES)},
    }


# ---------------------------------------------------------------- 文字整理
_CN_DIGIT = str.maketrans("零〇一二三四五六七八九", "00123456789")
_FW_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")
_CN_DIGITS = "零〇一二三四五六七八九"
#: 连着三个以上「数字字」的片段才算数字串（「十四个」「两个」根本不进来）
_CN_RUN = re.compile(r"[零〇一二三四五六七八九十百千]{3,}")
_CITE = re.compile(r"\[\[\d+\]\]")


def _digits_only(m: re.Match) -> str:
    """数字串 → 逐字念的那串数字。

    为什么要丢掉「百/十/千」：ASR 会把「202609」念成「二零二**百**零九」
    （2026-11-02 实测）——中间那个「百」是它自己加的读法，不是数值。
    只认**四个以上数字字**的片段（期次是六位，年份是四位），
    「十四个学科」「二十四篇」这类真数值一律原样不动。
    """
    run = m.group(0)
    digits = "".join(ch for ch in run if ch in _CN_DIGITS)
    if len(digits) < 4:
        return run
    return digits.translate(_CN_DIGIT)


def normalize_numbers(text: str) -> str:
    """语音转写里的汉字数字 → 阿拉伯数字（只动 4 位以上的数字串）。

    为什么必须做：期次识别认 `202609` / `2026年9月`，而 ASR 把「二零二六零九」
    原样吐汉字；不换的话语音问「二零二六零九期」会被当成没听出期次。
    只动数字串，是为了不碰「十四个学科」「两期」这类正常说法。
    """
    s = str(text or "").translate(_FW_DIGIT)
    return _CN_RUN.sub(_digits_only, s)


def spoken(text: str) -> str:
    """答案正文 → 能念的句子：去引用标记、去标题符号、去表格行、压空白、封顶。"""
    out = []
    for line in str(text or "").splitlines():
        if "|" in line:
            continue                                  # 表格念出来是噪音（「竖线」满天飞）
        line = _CITE.sub("", line)
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)  # 小标题符号
        line = re.sub(r"^\s{0,3}[-*+]\s+", "", line)   # 列表符号
        line = line.replace("**", "").replace("`", "")
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            out.append(line)
    s = "\n".join(out).strip()
    if len(s) > MAX_SPEAK_CHARS:
        s = s[:MAX_SPEAK_CHARS].rstrip() + "……"
    return s


# ---------------------------------------------------------------- HTTP（urllib，零依赖）
def _multipart(fields: dict, files: tuple) -> tuple[bytes, str]:
    boundary = "----wenheng" + uuid.uuid4().hex
    buf = bytearray()
    for k, v in fields.items():
        buf += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode("utf-8")
    for name, filename, ctype, data in files:
        buf += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
        buf += data + b"\r\n"
    buf += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


def _post(url: str, body: bytes, ctype: str, cfg: dict, *, what: str) -> tuple[bytes, str]:
    """发一次请求，返回 (响应体, content-type)。失败一律转成人话。"""
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {cfg['key']}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:   # noqa: S310
            return r.read(), str(r.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            payload = json.loads(e.read().decode("utf-8", "replace"))
            detail = str(((payload or {}).get("error") or {}).get("message") or "")
        except Exception:                                        # noqa: BLE001
            detail = ""
        if e.code in (401, 403):
            raise SpeechError(f"{what}没通过鉴权：key 不对或没有这个模型的权限") from e
        if e.code == 404:
            raise SpeechError(f"这个网关没有{what}接口（地址末尾一般要带 /v1）") from e
        raise SpeechError(f"{what}被拒绝了：{detail or f'HTTP {e.code}'}") from e
    except (TimeoutError, socket.timeout) as e:
        raise SpeechError(f"{what}超时了（{cfg['timeout']:g} 秒没回应），再说一次") from e
    except (urllib.error.URLError, OSError) as e:
        raise SpeechError(f"连不上{what}服务：{e}") from e


# ---------------------------------------------------------------- 听
def transcribe(data: bytes, *, filename: str = "clip.webm",
               content_type: str = "audio/webm", language: str = "zh") -> dict:
    """录音 → 文字。返回 `{"text", "raw", "ms"}`：`text` 已把汉字数字换成阿拉伯数字，
    `raw` 是原样（界面要说「我听到的是…」时用原文）。"""
    cfg = _cfg()
    if cfg["why"]:
        raise SpeechError(cfg["why"])
    if not data:
        raise SpeechError("没收到录音")
    if len(data) > MAX_UPLOAD_BYTES:
        raise SpeechError("这段录音太长了，说短一点")
    body, ctype = _multipart(
        {"model": cfg["asr_model"], "language": language, "response_format": "json"},
        (("file", filename or "clip.webm", content_type or "audio/webm", data),))
    t0 = time.perf_counter()
    raw_bytes, _ = _post(f"{cfg['base_url']}/audio/transcriptions", body, ctype, cfg,
                         what="听写")
    ms = int((time.perf_counter() - t0) * 1000)
    try:
        payload = json.loads(raw_bytes.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SpeechError("听写返回的不是文字（检查地址是否带 /v1）") from e
    heard = str((payload or {}).get("text") or "").strip()
    if not heard:
        raise SpeechError("没听清，再说一次")
    return {"text": normalize_numbers(heard), "raw": heard, "ms": ms}


# ---------------------------------------------------------------- 说
def speak(text: str, *, voice: str = "", fmt: str = "mp3") -> tuple[bytes, str]:
    """文字 → 音频字节（默认 mp3）。念之前先按 `spoken()` 把稿子理干净。"""
    cfg = _cfg()
    if cfg["why"]:
        raise SpeechError(cfg["why"])
    said = spoken(text)
    if not said:
        raise SpeechError("这段没有能念的内容")
    body = json.dumps({
        "model": cfg["tts_model"], "input": said,
        "voice": voice or cfg["voice"], "response_format": fmt,
    }, ensure_ascii=False).encode("utf-8")
    data, ctype = _post(f"{cfg['base_url']}/audio/speech", body,
                        "application/json", cfg, what="播报")
    if not ctype.startswith("audio/"):
        raise SpeechError("播报返回的不是音频（网关可能不认这个型号）")
    return data, ctype
