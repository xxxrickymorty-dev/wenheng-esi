# -*- coding: utf-8 -*-
"""对话层内核（pi）（票 03）：兜底补槽的 Scripted 测试——全离线（零网络）。

覆盖：正常补槽（指代 → 期次）、槽位覆盖、报告/推进路、工具白名单与多步 loop、
坏输出拒、数字泄漏拒、期次不在列表拒、超时回落、异常回落、无 key / demo /
qa 关不启内核、留痕（mode=model|fallback 如实）。真实模型联网验收留给票 04。

内核经 `ai.using(dialog_kernel=<StreamFn>)` 注入脚本流；pi 的类型从 vendored
快照导入（与生产同一条 loop，只是流是脚本化的）。
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

import ai
from ai import _dialog_kernel
from _vendor import pi_agent_core as pi

TODAY = "2026-10-10"
PERIODS = ["202609", "202607", "202605"]

_LABELS = (("monitor", "动态监测表"), ("esi", "ESI 原始包"),
           ("papers", "顶尖论文清单"), ("incites", "InCites 快照"))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """测试不依赖开发机环境：清掉云配置（无 key＝规则部署，内核默认不启）。"""
    for k in ("WENHENG_AI_PROFILE", "WENHENG_AI_BACKEND", "WENHENG_AI_BASE_URL",
              "WENHENG_AI_MODEL", "WENHENG_AI_KEY", "WENHENG_AI_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)


def fake_inventory(period, *, released=True, missing=(), fallback=""):
    pieces = [{"key": k, "label": lb,
               "state": "missing" if k in missing else "ok",
               "note": "未到（随发布）" if (k in missing and not released) else ""}
              for k, lb in _LABELS]
    return {"period": period, "released": released, "pieces": pieces,
            "n_pieces": len(pieces), "n_missing": len(missing), "fallback": fallback}


# ---------------------------------------------------------------- Scripted 流
def _final(text):
    return pi.AssistantMessage(content=[pi.TextContent(text=text)], stop_reason="stop")


def _tool(name, args=None):
    return pi.AssistantMessage(
        content=[pi.ToolCall(id=f"call-{name}", name=name, arguments=args or {})],
        stop_reason="toolUse")


class ScriptedStream:
    """按脚本回放：str → 终答；AssistantMessage → 原样；异常 → 抛出。零网络。"""

    name = "scripted"

    def __init__(self, turns, name="scripted"):
        self.name = name
        self.turns = list(turns)
        self.contexts = []

    def __call__(self, model, context, options):                   # noqa: ARG002
        self.contexts.append(context)
        t = self.turns.pop(0) if self.turns else _final("{}")
        if isinstance(t, BaseException):
            raise t
        if isinstance(t, str):
            t = _final(t)

        async def events():
            yield pi.StreamDoneEvent(reason=t.stop_reason, message=t)

        async def result():
            return t

        return {"events": events(), "result": result}


class HangStream:
    """首答即挂起：验超时回落（wait_for 取消）。"""

    name = "hang"

    def __call__(self, model, context, options):                   # noqa: ARG002
        async def events():
            await asyncio.sleep(30)
            yield None

        async def result():
            return _final("{}")

        return {"events": events(), "result": result}


class BombStream:
    """被调用即炸：证明该路径零外发。"""

    name = "bomb"

    def __call__(self, model, context, options):                   # noqa: ARG002
        raise AssertionError("内核不该被触发/外发")


# ---------------------------------------------------------------- 工具
def run_dialog(text, *, root, period="", actor="admin", today=TODAY, inventory=None,
               history=None, periods=None, kernel=None, **ov):
    payload = {"text": text, "today": today, "history": history or []}
    if periods is not None:
        payload["periods"] = periods
    ovs = {"data_root": root, "inventory": (lambda _p: inventory)}
    if kernel is not None:
        ovs["dialog_kernel"] = kernel
    ovs.update(ov)
    with ai.using(**ovs):
        return ai.run("dialog", period, payload=payload, actor=actor)


def records(root, period):
    """该期次目录下的调用记录（滤掉开关审计行）。"""
    p = pathlib.Path(root) / period / "ai_calls.jsonl"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(ln)
        if r.get("kind") == "call":
            out.append(r)
    return out


# ============================================================ 1. 正常补槽
def test_上上期呢_内核补槽落期次_记录mode_model(tmp_path):
    stream = ScriptedStream([json.dumps({"period": "202607", "intent": ""})])
    ans = run_dialog("上上期呢", root=tmp_path, kernel=stream, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的化学接近度"}])
    assert ans.data["case"] == "period" and ans.data["period"] == "202607"
    assert ans.data["kind"] == "query"
    assert "查哪一期" not in ans.text, "补到期次后不再反问"
    assert ans.mode == "rule" and ans.backend == "rule", "正文仍是规则拼装（徽标不变）"
    recs = records(tmp_path, "202607")
    assert len(recs) == 1 and recs[0]["capability"] == "dialog"
    assert recs[0]["mode"] == "model" and recs[0]["backend"] == "scripted"
    assert recs[0]["fallback"] is None
    # 内核看到的：三个白名单工具 + 原句 + 上文 + 槽位
    ctx = stream.contexts[0]
    assert [t.name for t in ctx.tools] == ["list_periods", "scan_inventory", "product_status"]
    user_text = ctx.messages[0].content[0].text
    assert "上上期呢" in user_text and "查最新的化学接近度" in user_text


def test_指代句_覆盖槽位旧期次(tmp_path):
    """「上上期」相对会话槽位（202609）解——内核给 202605，覆盖旧槽位。"""
    stream = ScriptedStream([json.dumps({"period": "202605", "intent": ""})])
    ans = run_dialog("上上期呢", root=tmp_path, period="202609", kernel=stream,
                     periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的化学接近度"}])
    assert ans.data["period"] == "202605"
    assert records(tmp_path, "202605")[0]["mode"] == "model"


def test_做上上期的报告_走报告路并盘点(tmp_path):
    seen = []

    def pick(period):
        seen.append(period)
        return fake_inventory(period, released=True)

    stream = ScriptedStream([json.dumps({"period": "202607", "intent": "出报告"},
                                        ensure_ascii=False)])
    with ai.using(data_root=tmp_path, inventory=pick, dialog_kernel=stream):
        ans = ai.run("dialog", "", payload={
            "text": "做上上期的报告", "today": TODAY,
            "history": [{"who": "me", "text": "做 202609 的报告"}],
            "periods": PERIODS}, actor="admin")
    assert ans.data["kind"] == "report" and ans.data["period"] == "202607"
    assert ans.data["verdict"] == "ready" and "盘点 · 202607" in ans.text
    assert seen == ["202607"], "盘点按补出的期次来"
    assert records(tmp_path, "202607")[0]["mode"] == "model"


def test_推进路_目标用补出的期次(tmp_path):
    inv = fake_inventory("202607", released=True)
    stream = ScriptedStream([json.dumps({"period": "202607", "intent": ""})])
    ans = run_dialog("那期接着出稿", root=tmp_path, kernel=stream, periods=PERIODS,
                     inventory=inv, history=[{"who": "me", "text": "查 202609 的化学"}])
    assert ans.data["kind"] == "proceed"
    assert ans.data["run"] == {"period": "202607", "auto": True, "intent": "single_trend"}
    assert "开始出稿" in ans.text


# ============================================================ 2. 工具（只读、零台账数值）
def test_工具调用_多步loop_先工具后终答(tmp_path):
    turns = [_tool("list_periods"),
             json.dumps({"period": "202607", "intent": ""})]
    stream = ScriptedStream(turns)
    ans = run_dialog("上上期呢", root=tmp_path, kernel=stream, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的"}])
    assert len(stream.contexts) == 2, "先工具、后终答"
    assert ans.data["period"] == "202607"
    assert ans.data["kernel"]["tools"] == ["list_periods"]
    tool_result = stream.contexts[1].messages[-1]
    assert json.loads(tool_result.content[0].text) == PERIODS, "list_periods 给的就是注入的期次表"


def test_工具scan_inventory_用注入盘点_只报件在不在(tmp_path):
    seen = []

    def pick(period):
        seen.append(period)
        return fake_inventory(period, released=True, missing=("papers",))

    turns = [_tool("scan_inventory", {"period": "202607"}),
             json.dumps({"period": "202607", "intent": ""})]
    stream = ScriptedStream(turns)
    with ai.using(data_root=tmp_path, inventory=pick, dialog_kernel=stream):
        ans = ai.run("dialog", "", payload={
            "text": "那期能出吗", "today": TODAY,
            "history": [{"who": "me", "text": "查 202609 的化学"}],
            "periods": PERIODS}, actor="admin")
    assert seen == ["202607"], "scan_inventory 走既有盘点注入"
    assert ans.data["kernel"]["tools"] == ["scan_inventory"]
    payload = json.loads(stream.contexts[1].messages[-1].content[0].text)
    assert payload["missing"] == ["顶尖论文清单"] and payload["released"] is True
    assert "n_missing" not in payload and "n_pieces" not in payload, "工具面零台账数值/计数"


def test_工具product_status_有无产物(tmp_path):
    (tmp_path / "202607").mkdir()
    (tmp_path / "202607" / "red_slots.json").write_text("[]", encoding="utf-8")
    turns = [_tool("product_status", {"period": "202607"}),
             json.dumps({"period": "", "intent": ""})]
    stream = ScriptedStream(turns)
    ans = run_dialog("那期出过吗", root=tmp_path, kernel=stream, periods=PERIODS,
                     history=[{"who": "me", "text": "查 202607"}])
    payload = json.loads(stream.contexts[1].messages[-1].content[0].text)
    assert payload == {"period": "202607", "has_products": True}
    assert ans.data["kernel"]["tools"] == ["product_status"]


# ============================================================ 3. 坏输出 / 数字泄漏（拒）
def test_坏输出_拒_回落原规则含候选(tmp_path):
    stream = ScriptedStream(["这不是 JSON"])
    ans = run_dialog("上上期呢", root=tmp_path, kernel=stream, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的化学接近度"}])
    assert ans.data["case"] == "no_period" and ans.data["period"] == ""
    assert ans.data["kind"] == "query"
    assert "最近有效期次是 202609" in ans.text, "回落＝原规则反问"
    assert {"kind": "send", "text": "查最新的"} in ans.data["actions"], "含「查最新的」候选"
    recs = records(tmp_path, "_ai")
    assert recs[-1]["mode"] == "fallback"
    assert recs[-1]["fallback"] == "brain_error:bad_response"
    assert ans.data["kernel"]["mode"] == "fallback"


def test_数字泄漏与越界期次_全拒(tmp_path):
    bads = (
        '{"period": "202607", "intent": "查 2026 年的"}',   # intent 带数字
        '{"period": "202607", "intent": "有 139 篇"}',      # 数字泄漏
        '{"period": "202001", "intent": ""}',               # 不在 payload.periods
        '{"period": 202607, "intent": ""}',                 # 非字符串期次
        '{"period": "202607", "note": "139"}',              # 白名单外键且值带数字
        "[]",                                               # 非对象
    )
    for bad in bads:
        stream = ScriptedStream([bad])
        ans = run_dialog("上上期呢", root=tmp_path, kernel=stream, periods=PERIODS,
                         history=[{"who": "me", "text": "查最新的"}])
        assert ans.data["period"] == "", bad
        assert records(tmp_path, "_ai")[-1]["mode"] == "fallback", bad


def test_parse_slots_白名单直测():
    periods = ("202609", "202607")
    assert _dialog_kernel.parse_slots(
        '{"period": "202607", "intent": "出报告"}', periods) == ("202607", "出报告")
    assert _dialog_kernel.parse_slots('{"period": ""}', periods) == ("", "")
    assert _dialog_kernel.parse_slots(
        '```json\n{"period": "202607", "intent": ""}\n```', periods) == ("202607", "")
    assert _dialog_kernel.parse_slots("{}", periods) == ("", "")
    # 2026-10-14 加固：围栏/前后白话容忍；intent 归一（查询类→空串）；纯文字多余键忽略
    assert _dialog_kernel.parse_slots(
        '上上期是 202607。\n{"period": "202607", "intent": "查数据"}',
        periods) == ("202607", "")
    assert _dialog_kernel.parse_slots(
        '{"period": "202607", "intent": "报告", "reason": "结合上文"}',
        periods) == ("202607", "出报告")
    for bad in ("", "嗯", "[]", '{"period": "202001"}', '{"period": "202607", "x": 1}'):
        assert _dialog_kernel.parse_slots(bad, periods) is None, bad


# ============================================================ 4. 超时 / 异常回落
def test_超时_回落(tmp_path, monkeypatch):
    monkeypatch.setenv("WENHENG_AI_TIMEOUT", "0.05")
    ans = run_dialog("上上期呢", root=tmp_path, kernel=HangStream(), periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的"}])
    assert ans.data["period"] == "" and ans.data["kind"] == "query"
    recs = records(tmp_path, "_ai")
    assert recs[-1]["mode"] == "fallback" and recs[-1]["fallback"] == "brain_error:timeout"


def test_流异常_回落(tmp_path):
    stream = ScriptedStream([RuntimeError("boom")])
    ans = run_dialog("上上期呢", root=tmp_path, kernel=stream, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的"}])
    assert ans.data["period"] == ""
    assert records(tmp_path, "_ai")[-1]["fallback"] == "brain_error:RuntimeError"


# ============================================================ 5. 离线不启（零外发）
def test_无key_内核不启_零外发(tmp_path, monkeypatch):
    def boom(*a, **k):                                             # noqa: ARG001
        raise AssertionError("无 key 不该装配真实流/发包")

    monkeypatch.setattr(_dialog_kernel, "_make_openai_stream", boom)
    with ai.using(data_root=tmp_path):
        assert _dialog_kernel.available() is False
    ans = run_dialog("上上期呢", root=tmp_path, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的"}])
    assert ans.data["period"] == "" and "查哪一期" in ans.text
    assert "kernel" not in ans.data, "未启用＝不留内核记录面"
    recs = records(tmp_path, "_ai")
    assert recs[0]["mode"] == "rule" and recs[0]["fallback"] is None


def test_demo_profile_有key也不启(tmp_path, monkeypatch):
    monkeypatch.setenv("WENHENG_AI_PROFILE", "demo")
    monkeypatch.setenv("WENHENG_AI_BACKEND", "openai")
    monkeypatch.setenv("WENHENG_AI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("WENHENG_AI_MODEL", "m")
    monkeypatch.setenv("WENHENG_AI_KEY", "sk-test")
    with ai.using(data_root=tmp_path):
        assert _dialog_kernel.available() is False
    ans = run_dialog("上上期呢", root=tmp_path, periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的"}])
    assert ans.data["period"] == ""
    assert "kernel" not in ans.data


def test_qa开关关_注入流也不启(tmp_path):
    with ai.using(data_root=tmp_path):
        ai.set_switch("qa", False, actor="admin")
    ans = run_dialog("上上期呢", root=tmp_path, kernel=BombStream(), periods=PERIODS,
                     history=[{"who": "me", "text": "查最新的"}])
    assert ans.data["period"] == "" and ans.data["kind"] == "query"
    assert "kernel" not in ans.data
    assert records(tmp_path, "_ai")[0]["mode"] == "rule"


# ============================================================ 6. 触发点（何时不问内核）
def test_规则命中_不问内核(tmp_path):
    for text in ("做 9 月的报告", "查 202607 的化学接近度", "最新的", "做9月出稿的报告"):
        stream = ScriptedStream([json.dumps({"period": "202607"})])
        run_dialog(text, root=tmp_path, kernel=stream, periods=PERIODS,
                   history=[{"who": "me", "text": "查最新的"}])
        assert stream.contexts == [], text


def test_无上文_不问内核(tmp_path):
    stream = ScriptedStream([json.dumps({"period": "202607"})])
    ans = run_dialog("上上期呢", root=tmp_path, kernel=stream, periods=PERIODS)
    assert stream.contexts == []
    assert ans.data["case"] == "no_period" and ans.data["period"] == ""


def test_短应诺_不问内核(tmp_path):
    stream = ScriptedStream([json.dumps({"period": "202605"})])
    ans = run_dialog("对啊", root=tmp_path, period="202607", kernel=stream,
                     periods=PERIODS, history=[{"who": "me", "text": "做 202607 的报告"}])
    assert stream.contexts == [], "短应诺＝规则确定性命中"
    assert ans.data["kind"] == "proceed"


# ============================================================ 7. 内核静态纪律
def test_系统提示零数字():
    assert not any(ch.isdigit() for ch in _dialog_kernel.KERNEL_SYSTEM)
