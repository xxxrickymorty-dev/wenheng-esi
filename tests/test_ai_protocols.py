# -*- coding: utf-8 -*-
"""三协议云适配器协议测试（2026-11-04，rick 定：三种都真实现）。

对**进程内假 HTTP 服务**测 Responses / Anthropic 两条新协议的翻译
（payload 形状、鉴权头、工具环、截断如实带出）；回落原因码与外发预算
的语义三家同源（`_HTTPBrain` 一份），OpenAI 那份在 `test_ai_openai.py` 钉着。
真实云不进 CI（与 D-ports 一致）。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import ai
from ai import _models
from ai._brain import (AnthropicBrain, Brief, BrainError, OpenAIBrain,
                       ResponsesBrain, make_brain)

#: conftest 的 `_isolate_ai_env` 会把 `active_credentials` 蒙成 None；本文件
#: 有一例要真函数（与 test_ai_models 同一姿势）。
_REAL_ACTIVE = _models.active_credentials


class FakeGateway:
    """可编程假网关：记录请求，按编程好的体回（Responses/Anthropic 形状自定）。"""

    def __init__(self):
        self.requests = []
        self.raw = None                              # 直接给字符串（原样回）
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    req_json = json.loads(self.rfile.read(n).decode("utf-8"))
                except Exception:                    # noqa: BLE001
                    req_json = {}
                outer.requests.append({"path": self.path,
                                       "headers": dict(self.headers.items()),
                                       "json": req_json})
                body = outer.raw if outer.raw is not None else "{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *a):               # noqa: ARG002
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def gw():
    s = FakeGateway()
    yield s
    s.close()


TOOL_BRIEF = Brief(ability="qa", system="s", task="问",
                   tools=({"type": "function",
                           "function": {"name": "query_series",
                                        "description": "查走势",
                                        "parameters": {"type": "object",
                                                       "properties": {}}}},))
HISTORY = ({"role": "assistant", "content": "上一轮的话",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "query_series",
                                         "arguments": '{"metric": "x"}'}}]},
           {"role": "tool", "tool_call_id": "c1", "content": "查得 [[1]]。"})


# ============================================================ make_brain 分派
def test_按协议装配_认不出报错():
    assert isinstance(make_brain(base_url="https://a/v1", model="m",
                                 key="k", protocol="openai"), OpenAIBrain)
    assert isinstance(make_brain(base_url="https://a/v1", model="m",
                                 key="k", protocol="openai-responses"), ResponsesBrain)
    assert isinstance(make_brain(base_url="https://a/v1", model="m",
                                 key="k", protocol="anthropic"), AnthropicBrain)
    assert make_brain(base_url="https://a/v1", model="m",
                      key="k").name == "openai:m", "缺省 openai"
    assert make_brain(base_url="https://a/v1", model="m",
                      key="k", protocol="anthropic").name == "anthropic:m"
    with pytest.raises(ValueError):
        make_brain(base_url="https://a/v1", model="m", key="k", protocol="gemini")


def test_清单协议随当前项传进brain(tmp_path, monkeypatch):
    """active 供应商是什么协议，build_brain 就装配哪一家（端到端口径）。"""
    from ai import _config, _models
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    with ai.using(data_root=tmp_path):
        _models.upsert({"id": "cla-prov", "label": "cla", "key": "sk-k" * 3,
                        "base_url": "https://a.test/v1", "protocol": "anthropic",
                        "models": ["claude-x"]}, actor="admin")
        _models.set_active("cla-prov", "claude-x", actor="admin")
        brain = _config.build_brain()
    assert isinstance(brain, AnthropicBrain)


# ============================================================ OpenAI Responses
def test_responses_请求形状与解析(gw):
    gw.raw = json.dumps({"output": [{"type": "message",
                                     "content": [{"type": "output_text",
                                                  "text": "占 [[1]]%。"}]}],
                         "status": "completed"})
    turn = ResponsesBrain(base_url=gw.url, model="gpt-x", key="sk-r").think(
        Brief(ability="qa", system="s", task="问"))
    assert turn.text == "占 [[1]]%。" and turn.calls == ()
    r = gw.requests[0]
    assert r["path"] == "/v1/responses"
    assert r["headers"].get("Authorization") == "Bearer sk-r"
    body = r["json"]
    assert body["model"] == "gpt-x" and body["instructions"] == "s"
    assert body["max_output_tokens"] > 0 and "max_tokens" not in body
    assert body["input"][0]["content"][0]["type"] == "input_text"
    assert body["input"][0]["content"][0]["text"] == "问"


def test_responses_工具环_translation(gw):
    gw.raw = json.dumps({"output": [
        {"type": "function_call", "call_id": "fc1", "name": "query_series",
         "arguments": '{"metric": "proximity"}'}],
        "status": "completed"})
    turn = ResponsesBrain(base_url=gw.url, model="gpt-x", key="sk-r").think(
        Brief(ability="qa", system="s", task="问", tools=TOOL_BRIEF.tools,
              history=HISTORY))
    assert turn.text is None
    assert turn.calls == ({"name": "query_series",
                           "arguments": {"metric": "proximity"}, "id": "fc1"},)
    body = gw.requests[0]["json"]
    assert body["tools"] == [{"type": "function", "name": "query_series",
                              "description": "查走势",
                              "parameters": {"type": "object", "properties": {}}}], \
        "OpenAI 包装形状被摊平"
    kinds = [(i.get("type"), i.get("call_id")) for i in body["input"]]
    assert kinds == [(None, None), (None, None), ("function_call", "c1"),
                     ("function_call_output", "c1")], \
        f"user 任务、assistant 文本、工具调用、工具结果按序翻译：{kinds}"
    fc = next(i for i in body["input"] if i.get("type") == "function_call")
    assert fc["name"] == "query_series" and fc["arguments"] == '{"metric": "x"}'
    out = next(i for i in body["input"] if i.get("type") == "function_call_output")
    assert out["call_id"] == "c1" and out["output"] == "查得 [[1]]。"


def test_responses_截断如实带出(gw):
    gw.raw = json.dumps({"output": [{"type": "message",
                                     "content": [{"type": "output_text", "text": ""}]}],
                         "status": "incomplete",
                         "incomplete_details": {"reason": "max_output_tokens"}})
    turn = ResponsesBrain(base_url=gw.url, model="gpt-x", key="sk-r").think(
        Brief(ability="qa", system="s", task="问"))
    assert turn.finish == "length", "内核据此报 truncated"


def test_responses_坏形状_报bad_response(gw):
    gw.raw = json.dumps({"nope": True})
    with pytest.raises(BrainError) as ei:
        ResponsesBrain(base_url=gw.url, model="gpt-x", key="sk-r").think(
            Brief(ability="qa", system="s", task="问"))
    assert ei.value.code == "bad_response"


# ============================================================ Anthropic Messages
def test_anthropic_鉴权头与必填参数(gw):
    gw.raw = json.dumps({"content": [{"type": "text", "text": "占 [[2]]%。"}],
                         "stop_reason": "end_turn"})
    turn = AnthropicBrain(base_url=gw.url, model="claude-x", key="sk-a",
                          extra_headers={"X-Org": "ynu"}).think(
        Brief(ability="qa", system="s", task="问"))
    assert turn.text == "占 [[2]]%。"
    h = {k.lower(): v for k, v in gw.requests[0]["headers"].items()}
    assert h.get("x-api-key") == "sk-a" and h.get("anthropic-version")
    assert h.get("x-org") == "ynu", "entry headers 只叠加，Anthropic 也一样"
    body = gw.requests[0]["json"]
    assert body["system"] == "s" and body["max_tokens"] > 0, "system 单独走键、max_tokens 必填"
    assert body["messages"][0]["role"] == "user"


def test_anthropic_消息交替_工具结果回传(gw):
    gw.raw = json.dumps({"content": [{"type": "text", "text": "好"}],
                         "stop_reason": "end_turn"})
    AnthropicBrain(base_url=gw.url, model="claude-x", key="sk-a").think(
        Brief(ability="qa", system="s", task="问", history=HISTORY))
    body = gw.requests[0]["json"]
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"], "user/assistant 严格交替"
    asst = body["messages"][1]["content"]
    assert {"type": "text", "text": "上一轮的话"} in asst
    tu = next(b for b in asst if b["type"] == "tool_use")
    assert tu["id"] == "c1" and tu["name"] == "query_series"
    assert tu["input"] == {"metric": "x"}, "arguments 解回对象再发"
    tr = body["messages"][2]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "c1"
    assert tr["content"][0]["text"] == "查得 [[1]]。"


def test_anthropic_工具环_工具schema与tool_use解码(gw):
    gw.raw = json.dumps({"content": [
        {"type": "tool_use", "id": "tu1", "name": "query_series",
         "input": {"metric": "proximity"}}],
        "stop_reason": "tool_use"})
    turn = AnthropicBrain(base_url=gw.url, model="claude-x", key="sk-a").think(
        Brief(ability="qa", system="s", task="问", tools=TOOL_BRIEF.tools))
    assert turn.text is None
    assert turn.calls == ({"name": "query_series",
                           "arguments": {"metric": "proximity"}, "id": "tu1"},)
    body = gw.requests[0]["json"]
    assert body["tools"] == [{"name": "query_series", "description": "查走势",
                              "input_schema": {"type": "object", "properties": {}}}]


def test_anthropic_截断如实带出(gw):
    gw.raw = json.dumps({"content": [{"type": "text", "text": "半"}],
                         "stop_reason": "max_tokens"})
    turn = AnthropicBrain(base_url=gw.url, model="claude-x", key="sk-a").think(
        Brief(ability="qa", system="s", task="问"))
    assert turn.finish == "length"


def test_anthropic_坏形状_报bad_response(gw):
    gw.raw = json.dumps({"nothing": []})
    with pytest.raises(BrainError) as ei:
        AnthropicBrain(base_url=gw.url, model="claude-x", key="sk-a").think(
            Brief(ability="qa", system="s", task="问"))
    assert ei.value.code == "bad_response"
