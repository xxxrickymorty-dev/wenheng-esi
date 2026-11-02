# -*- coding: utf-8 -*-
"""语音两端（2026-11-02）：听写与播报的口径、红线、请求形状。

口径：
- 没 key / 演示锁 → 直接说不可用，**一个字节都不发**（`_post` 不被调用）；
- 汉字数字只换 3 位以上连写（期次能认出来，「十四个学科」不被改坏）；
- 念的稿子先理干净（去 `[[n]]`、去标题符号、去表格行），且封顶；
- 请求形状照 OpenAI 兼容口径（multipart 的 file/model；json 的 input/voice）。
"""
from __future__ import annotations

import json

import pytest

from ai import _speech

# ============================================================ 能力面与红线
def test_没配key就说不可用_且不发包(monkeypatch):
    called = []
    monkeypatch.setattr(_speech, "_post", lambda *a, **k: called.append(a) or (b"", ""))
    st = _speech.status()
    assert st["ready"] is False and st["reason"], "没 key 必须给一句人话"
    assert st["asr"]["ready"] is False and st["tts"]["ready"] is False
    with pytest.raises(_speech.SpeechError) as e:
        _speech.transcribe(b"abc", filename="a.webm")
    assert "配" in str(e.value), "没配就直说没配（地址或 key），别报技术错误"
    with pytest.raises(_speech.SpeechError):
        _speech.speak("你好")
    assert called == [], "不可用时不许出网"


def test_演示锁一票否决_即使配了key(monkeypatch):
    monkeypatch.setenv("WENHENG_AI_PROFILE", "demo")
    monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
    st = _speech.status()
    assert st["ready"] is False and "演示" in st["reason"]


def test_配齐了就报可用_型号与音色从env来(monkeypatch):
    monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
    monkeypatch.setenv("WENHENG_ASR_MODEL", "Test/ASR-1")
    monkeypatch.setenv("WENHENG_TTS_VOICE", "vivian")
    st = _speech.status()
    assert st["ready"] is True and st["reason"] == ""
    assert st["asr"]["model"] == "Test/ASR-1"
    assert st["tts"]["voice"] == "vivian"
    assert "serena" in st["tts"]["voices"]


# ============================================================ 汉字数字
@pytest.mark.parametrize("heard, want", [
    ("二零二六百零九期哪些学科接近度最高", "202609期哪些学科接近度最高"),
    ("二零二六年九月的情况", "2026年九月的情况"),   # 「九月」本来就被期次识别认，不硬换
    ("十四个学科", "十四个学科"),          # 两位连写不动
    ("两个指标", "两个指标"),
    ("二零二六零九", "202609"),
])
def test_汉字数字只换三位以上连写(heard, want):
    assert _speech.normalize_numbers(heard) == want


def test_全角数字也换成半角():
    assert _speech.normalize_numbers("２０２６０９期") == "202609期"


# ============================================================ 念稿整理
def test_念稿去引用标记与标题符号():
    said = _speech.spoken("## 结论\n化学的接近度是 56.74%[[1]]，**最高**。\n- 材料其次[[2]]")
    assert "[[1]]" not in said and "[[2]]" not in said
    assert "##" not in said and "**" not in said
    assert "化学的接近度是 56.74%" in said


def test_念稿丢掉表格行():
    said = _speech.spoken("学科 | 接近度\n|---|---|\n| 化学 | 56.74 |\n正文一句。")
    assert "|" not in said
    assert "正文一句。" in said


def test_念稿封顶且带省略号():
    said = _speech.spoken("字" * (_speech.MAX_SPEAK_CHARS + 50))
    assert len(said) <= _speech.MAX_SPEAK_CHARS + 2
    assert said.endswith("……")


def test_念稿空内容为空():
    assert _speech.spoken("   \n\n  ") == ""


# ============================================================ 请求形状
def _open(monkeypatch):
    monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")


def test_听写请求是multipart_带model与file(monkeypatch):
    _open(monkeypatch)
    seen = {}

    def fake_post(url, body, ctype, cfg, *, what):
        seen.update(url=url, body=body, ctype=ctype, what=what)
        return json.dumps({"text": "二零二六百零九期"}).encode(), "application/json"

    monkeypatch.setattr(_speech, "_post", fake_post)
    got = _speech.transcribe(b"RIFFfake", filename="clip.webm", content_type="audio/webm")
    assert seen["url"] == "https://example.test/v1/audio/transcriptions"
    assert seen["ctype"].startswith("multipart/form-data; boundary=")
    assert b'name="model"' in seen["body"] and b'name="file"' in seen["body"]
    assert b"RIFFfake" in seen["body"]
    assert got["text"] == "202609期", "转写结果已把汉字数字换成阿拉伯数字"
    assert got["raw"] == "二零二六百零九期", "原文留着（界面要说「我听到的是…」）"
    assert isinstance(got["ms"], int)


def test_播报请求是json_带input与voice(monkeypatch):
    _open(monkeypatch)
    seen = {}

    def fake_post(url, body, ctype, cfg, *, what):
        seen.update(url=url, body=body, ctype=ctype)
        return b"ID3audio", "audio/mpeg"

    monkeypatch.setattr(_speech, "_post", fake_post)
    data, ctype = _speech.speak("化学最高[[1]]。")
    assert seen["url"] == "https://example.test/v1/audio/speech"
    assert seen["ctype"] == "application/json"
    payload = json.loads(seen["body"].decode("utf-8"))
    assert payload["input"] == "化学最高。"
    assert payload["voice"] == _speech.DEFAULT_TTS_VOICE
    assert payload["response_format"] == "mp3"
    assert data == b"ID3audio" and ctype == "audio/mpeg"


def test_播报回来的不是音频就说清楚(monkeypatch):
    _open(monkeypatch)
    monkeypatch.setattr(_speech, "_post",
                        lambda *a, **k: (b'{"error":1}', "application/json"))
    with pytest.raises(_speech.SpeechError) as e:
        _speech.speak("你好")
    assert "音频" in str(e.value)


def test_录音超限不发给网关(monkeypatch):
    _open(monkeypatch)
    called = []
    monkeypatch.setattr(_speech, "_post", lambda *a, **k: called.append(1) or (b"{}", ""))
    with pytest.raises(_speech.SpeechError):
        _speech.transcribe(b"x" * (_speech.MAX_UPLOAD_BYTES + 1))
    assert called == []


def test_听写没听清就说没听清(monkeypatch):
    _open(monkeypatch)
    monkeypatch.setattr(_speech, "_post",
                        lambda *a, **k: (json.dumps({"text": "  "}).encode(), "application/json"))
    with pytest.raises(_speech.SpeechError) as e:
        _speech.transcribe(b"RIFFfake")
    assert "没听清" in str(e.value)
