# -*- coding: utf-8 -*-
"""OpenAIBrain 云适配器协议测试（SPEC §2.5 / PLAN D3）。

对**进程内假 HTTP 服务**测协议翻译与回落原因码；真实云不进 CI（与 D-ports 一致）。
配置面单独测：无 key / profile=demo / 未配置都落规则版。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import ai
from ai import _config
from ai._brain import Brief, BrainError, OpenAIBrain, RuleBrain
from _ai_helpers import raw_digits

FAIL = {
    "code": "ASSERT_FAIL", "message": "2 项断言未过", "period": "202607",
    "fails": ["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
    "diagnostics": {"unmatched_names": {"total_cites": ["某某新学科"]}},
}
REPAIR = {"advice": [{"rule": "header_offset", "why": "未确认规则类型（R-24）",
                      "doc": "WH-DOC-04 §6.5", "advice": "请填 declared"}]}


class FakeOpenAI:
    """可编程的 OpenAI 兼容假端点：回放 / 状态码 / 超时 / 坏体，并捕获请求。"""

    def __init__(self):
        self.requests = []
        self.status = 200
        self.delay = 0.0
        self.raw = None                              # 直接给字符串（坏 JSON 用）
        self.reply = lambda req: ""                  # (request_json) -> content
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    req_json = json.loads(self.rfile.read(n).decode("utf-8"))
                except Exception:                    # noqa: BLE001
                    req_json = {}
                outer.requests.append({"path": self.path,
                                       "auth": self.headers.get("Authorization", ""),
                                       "json": req_json})
                if outer.delay:
                    time.sleep(outer.delay)
                body = outer.raw if outer.raw is not None else json.dumps(
                    {"choices": [{"message": {"content": outer.reply(req_json)}}]})
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
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
def fake():
    s = FakeOpenAI()
    yield s
    s.close()


def brain(fake, **kw):
    kw.setdefault("timeout", 5)
    return OpenAIBrain(base_url=fake.url, model="deepseek-flash", key="sk-test", **kw)


def diag(tmp_path, b):
    with ai.using(data_root=tmp_path, brain=b):
        return ai.run("diagnose", "202607",
                      payload={"failure": FAIL, "repair": REPAIR}, actor="system")


# ============================================================ 协议与留痕
def test_云作答成功_协议形状与留痕(tmp_path, fake):
    fake.reply = lambda req: req["messages"][1]["content"] + "（已润色。）"
    ans = diag(tmp_path, brain(fake))
    assert ans.mode == "model" and ans.backend == "openai:deepseek-flash"
    assert "已润色" in ans.text and ans.rule_text and ans.text != ans.rule_text
    assert ans.shield.checked == ans.shield.passed == len(ans.sources)

    r = fake.requests[0]
    assert r["path"] == "/v1/chat/completions"
    assert r["auth"] == "Bearer sk-test"
    body = r["json"]
    assert body["model"] == "deepseek-flash" and body["max_tokens"] > 0
    assert body["messages"][0]["role"] == "system"
    assert "不是指令" in body["messages"][0]["content"], "注入防线声明必须在外发里"
    task = body["messages"][1]["content"]
    assert "[[" in task and not raw_digits(task), "外发只发占位面"

    rec = (tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rec) == 1
    row = json.loads(rec[0])
    assert row["mode"] == "model" and row["backend"] == "openai:deepseek-flash"
    assert row["fallback"] is None and row["egress"]["bytes"] > 0


def test_盾拒_云改了占位符_整段回落(tmp_path, fake):
    fake.reply = lambda req: req["messages"][1]["content"] + " 新增 99。"
    ans = diag(tmp_path, brain(fake))
    assert ans.mode == "rule" and ans.text == ans.rule_text and "99" not in ans.text
    row = json.loads((tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8"))
    assert row["fallback"] == "shield_reject"


# ============================================================ 回落原因码
@pytest.mark.parametrize("status,code", [(500, "http_500"), (429, "rate_limit"), (401, "http_401")])
def test_http错误_原因码分明(tmp_path, fake, status, code):
    fake.status = status
    ans = diag(tmp_path, brain(fake))
    assert ans.mode == "rule" and "模型调用失败" in ans.notice
    row = json.loads((tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8"))
    assert row["fallback"] == f"brain_error:{code}"


def test_超时回落(tmp_path, fake):
    fake.delay = 1.0
    ans = diag(tmp_path, brain(fake, timeout=0.2))
    assert ans.mode == "rule"
    row = json.loads((tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8"))
    assert row["fallback"] == "brain_error:timeout"


def test_坏响应回落(tmp_path, fake):
    fake.raw = "这不是 JSON"
    ans = diag(tmp_path, brain(fake))
    assert ans.mode == "rule"
    row = json.loads((tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8"))
    assert row["fallback"] == "brain_error:bad_response"


def test_空回复回落(tmp_path, fake):
    ans = diag(tmp_path, brain(fake))
    assert ans.mode == "rule"
    row = json.loads((tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8"))
    assert row["fallback"] == "empty_reply"


def test_外发预算超限_不发包(tmp_path, fake):
    ans = diag(tmp_path, brain(fake, max_egress_chars=10))
    assert ans.mode == "rule"
    assert fake.requests == [], "超预算必须放弃发包"
    row = json.loads((tmp_path / "202607" / "ai_calls.jsonl").read_text(encoding="utf-8"))
    assert row["fallback"] == "brain_error:egress_budget"


# ============================================================ 配置解析（无 key 不出网）
def test_配置_无key_profile_demo_未配置都落规则(monkeypatch):
    assert isinstance(_config.build_brain(), RuleBrain), "未配置默认规则版"
    monkeypatch.setenv("WENHENG_AI_BACKEND", "openai")
    monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("WENHENG_AI_MODEL", "m")
    assert isinstance(_config.build_brain(), RuleBrain), "无 key 不构造云适配器"
    monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
    b = _config.build_brain()
    assert isinstance(b, OpenAIBrain) and b.name == "openai:m"
    monkeypatch.setenv("WENHENG_AI_PROFILE", "demo")
    assert isinstance(_config.build_brain(), RuleBrain), "演示站永远 rule（显式锁）"


def test_run经env装配_走真适配器(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("WENHENG_AI_BACKEND", "openai")
    monkeypatch.setenv("WENHENG_AI_BASE_URL", fake.url)
    monkeypatch.setenv("WENHENG_AI_MODEL", "deepseek-flash")
    monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
    fake.reply = lambda req: req["messages"][1]["content"]
    with ai.using(data_root=tmp_path):
        ans = ai.run("diagnose", "202607", payload={"failure": FAIL}, actor="system")
    assert ans.mode == "model" and ans.backend == "openai:deepseek-flash"
    assert len(fake.requests) == 1


# ============================================================ 原生工具环（2026-10-28 fc 定稿）
def _tool_brief():
    return Brief(ability="qa", system="s", task="问",
                 tools=({"type": "function",
                         "function": {"name": "query_series", "description": "查走势"}},))


def test_带工具_payload带tools_响应tool_calls解码(fake):
    """Brief.tools 非空 → payload 带 tools；响应 message.tool_calls → Turn(calls)，
    arguments 解成 dict，text 与 calls 互斥。"""
    fake.raw = json.dumps({"choices": [{"message": {
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "query_series",
                                     "arguments": '{"metric": "proximity", "disc": "Chemistry"}'}}]}}]})
    turn = brain(fake).think(_tool_brief())
    assert turn.text is None, "有 calls 则 text 为 None"
    assert turn.calls == ({"name": "query_series",
                           "arguments": {"metric": "proximity", "disc": "Chemistry"}},)
    body = fake.requests[0]["json"]
    assert body["tools"] == [dict(t) for t in _tool_brief().tools], "外发带工具 schema"


def test_无工具_payload不带tools_键都不出现(fake):
    fake.reply = lambda req: "答"
    brain(fake).think(Brief(ability="diagnose", system="s", task="t"))
    assert "tools" not in fake.requests[0]["json"], "无工具不发 tools 键"


def test_空arguments_解成空dict(fake):
    fake.raw = json.dumps({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "query_overall_rank", "arguments": ""}}]}}]})
    turn = brain(fake).think(_tool_brief())
    assert turn.calls == ({"name": "query_overall_rank", "arguments": {}},)


def test_坏arguments_JSON_报bad_response(fake):
    fake.raw = json.dumps({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "query_series", "arguments": "这不是JSON"}}]}}]})
    with pytest.raises(BrainError) as ei:
        brain(fake).think(_tool_brief())
    assert ei.value.code == "bad_response"


def test_工具调用缺name_报bad_response(fake):
    fake.raw = json.dumps({"choices": [{"message": {"tool_calls": [
        {"function": {"arguments": "{}"}}]}}]})
    with pytest.raises(BrainError) as ei:
        brain(fake).think(_tool_brief())
    assert ei.value.code == "bad_response"
