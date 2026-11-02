# -*- coding: utf-8 -*-
"""speech 分册：语音两端（听写 / 播报）的薄适配（2026-11-02）。

三个口，都是「转一手」——判断与红线全在 `src/ai/_speech.py`，这里只搬字节：

    GET  /api/speech               能不能听/能不能说（界面据此决定显不显示话筒与喇叭）
    POST /api/speech/transcribe    录音（multipart）→ {"text","raw","ms"}
    POST /api/speech/speak         {"text","voice"} → audio/mpeg

为什么不做流式：一轮问答本来就是「问 → 等 → 答」，语音只在两端加一拍；
流式播报要把答案切句再逐句合成，收益是省几百毫秒，代价是接错一处就念串行——不做。

失败一律 503 + 一句人话（`error`）：语音是加分件，坏了不该把对话页带崩。
"""
import json

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..guards import user_route

router = APIRouter()


def _unavailable(msg: str):
    """语音不可用/失败：503 + 人话（界面照「说不了」处理，不当成页面报错）。"""
    return JSONResponse({"error": msg}, status_code=503)


@router.get("/api/speech")
@user_route
async def api_speech_status(request: Request):
    """语音能力面（纯读配置，无副作用）：`ready=false` 时 `reason` 就是给馆员的那句话。"""
    from ai import _speech                                        # noqa: PLC0415
    return _speech.status()


@router.post("/api/speech/transcribe")
@user_route
async def api_speech_transcribe(request: Request, file: UploadFile = File(None)):
    """录音 → 文字。浏览器给什么格式就转什么格式（webm/ogg/mp4/wav 都行）。"""
    from ai import _speech                                        # noqa: PLC0415

    if file is None or not file.filename:
        return JSONResponse({"error": "没收到录音"}, status_code=400)
    data = await file.read()
    if len(data) > _speech.MAX_UPLOAD_BYTES:
        return _unavailable("这段录音太长了，说短一点")
    try:
        got = await run_in_threadpool(
            _speech.transcribe, data,
            filename=file.filename,
            content_type=file.content_type or "audio/webm")
    except _speech.SpeechError as e:
        return _unavailable(str(e))
    return got


@router.post("/api/speech/speak")
@user_route
async def api_speech_speak(request: Request):
    """一段文字 → 音频（mp3 字节）。念的稿子由 `_speech.spoken()` 理干净再发。"""
    from ai import _speech                                        # noqa: PLC0415

    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "请求内容不是 JSON"}, status_code=400)
    text = str((body or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "没有要念的内容"}, status_code=400)
    try:
        data, ctype = await run_in_threadpool(
            _speech.speak, text, voice=str((body or {}).get("voice") or ""))
    except _speech.SpeechError as e:
        return _unavailable(str(e))
    return Response(content=data, media_type=ctype,
                    headers={"Cache-Control": "no-store"})
