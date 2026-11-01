# -*- coding: utf-8 -*-
"""Recorder：`ai_calls.jsonl` 唯一写口（路径解析 / 调用记录 / 开关审计 / 失败不抛）。"""
import json
import pathlib

import ai
from ai import _record


def _rows(path):
    p = pathlib.Path(path)
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _call(rec, **over):
    kw = dict(capability="diagnose", mode="rule", backend="rule", fallback=None,
              shield={"checked": 2, "passed": 2}, text_protected="共 [[1]] 项",
              egress_items=1, egress_bytes=10, elapsed_ms=5)
    kw.update(over)
    return rec.call(**kw)


class Test_Recorder:
    def test_调用记录落期次目录并返回记录号(self, tmp_path):
        rec = _record.Recorder(tmp_path, period="202607", actor="system")
        rid = _call(rec)
        assert rid and rid.startswith("ai-diagnose-")
        rows = _rows(tmp_path / "202607" / "ai_calls.jsonl")
        assert len(rows) == 1
        r = rows[0]
        assert r["record_id"] == rid and r["kind"] == "call"
        assert r["actor"] == "system" and r["period"] == "202607"
        assert r["egress"] == {"items": 1, "bytes": 10} and r["shield"] == {"checked": 2, "passed": 2}

    def test_无期次落_ai目录(self, tmp_path):
        _call(_record.Recorder(tmp_path, period="", actor="admin"))
        assert (tmp_path / "_ai" / "ai_calls.jsonl").is_file()

    def test_for_period_吃using覆盖(self, tmp_path):
        with ai.using(data_root=tmp_path):
            rid = _call(_record.Recorder.for_period("202607", actor="admin"))
        assert rid
        assert _rows(tmp_path / "202607" / "ai_calls.jsonl")[0]["record_id"] == rid

    def test_写失败返回None不抛(self, tmp_path):
        # 用文件占住 `_ai/`，父目录建不出来；写失败不得抛。
        (tmp_path / "_ai").write_text("x", encoding="utf-8")
        assert _call(_record.Recorder(tmp_path)) is None

    def test_开关审计落_ai且kind为switch(self, tmp_path):
        rec = _record.Recorder(tmp_path, actor="admin")
        assert rec.switch(capability="diagnose", from_=True, to=False) is True
        rows = _rows(tmp_path / "_ai" / "ai_calls.jsonl")
        assert len(rows) == 1
        assert rows[0]["kind"] == "switch" and rows[0]["from"] is True
        assert rows[0]["to"] is False and rows[0]["actor"] == "admin"

    def test_数据根缺省是仓库out(self):
        assert _record.data_root().name == "out"
        assert _record.DEFAULT_DATA_ROOT == _record.data_root()


# ============================================================ 确定性工具调用收口（C4）
class Test_工具调用收口:
    def test_回执与轨迹同源_计时进收口(self):
        events = []
        with ai.using(trace=events.append):
            with _record.tool_call("product_status", "产物核对", {"period": "202607"},
                                   trace=True) as tc:
                tc.finish(_record.product_summary(True))
        r = tc.receipt
        assert (r.tool, r.label, r.ok, r.refused) == ("product_status", "产物核对", True, False)
        assert r.summary == "该期已有成品" and r.elapsed_ms >= 0
        assert r.args_digest == _record.digest({"period": "202607"}), "args 只进 digest"
        (ev,) = events
        assert ev == {"step": 1, "tool": r.tool, "label": r.label, "summary": r.summary,
                      "ok": r.ok, "refused": r.refused, "ms": r.elapsed_ms}, \
            "轨迹一条、字段与回执同源（形状唯一出处 trace_event）"

    def test_默认不发轨迹_规则轮口径不变(self):
        """_dialog 规则轮回执只进 Answer.receipts、不发轨迹——与现状逐字一致。"""
        events = []
        with ai.using(trace=events.append):
            with _record.tool_call("scan_inventory", "盘点", {"period": "202607"}) as tc:
                tc.finish(_record.scan_summary(None, "202607"), ok=False)
        assert events == []
        assert tc.receipt.ok is False and tc.receipt.refused is False
        assert tc.receipt.summary == "该期数据状态在这里看不到"

    def test_摘要单处定义_对话两侧同源(self):
        """盘点/产物摘要唯一出处（_record）：_dialog 规则轮与 _dialog_kernel 内核轮
        共用同一函数——同一工具同一摘要；文字面钉死在既有界面文案上。"""
        assert _record.scan_summary(
            {"period": "202609", "n_pieces": 4, "n_missing": 1}) == \
            "盘点 · 202609（必需件 4 件，缺 1 件）"
        assert _record.scan_summary(
            {"period": "202607", "n_pieces": 4, "n_missing": 0}) == \
            "盘点 · 202607（必需件 4 件）"
        assert _record.scan_summary(None, "202609") == "该期数据状态在这里看不到"
        assert _record.product_summary(True) == "该期已有成品"
        assert _record.product_summary(False) == "该期暂无成品"

    def test_emit_trace_裸回执按调用名兜底_带步号(self):
        """写作位边界的鸭子读法：执行器回执可为非 Receipt（测试替身回裸串），
        缺 attr 用调用名/「查台账」兜底——与迁移前逐字一致。"""
        events = []
        with ai.using(trace=events.append):
            _record.emit_trace("r1", step=2, tool="query_series", label="查台账")
        assert events == [{"step": 2, "tool": "query_series", "label": "查台账",
                           "summary": "", "ok": True, "refused": False, "ms": 0}]

    def test_trace_event_形状键集固定(self):
        assert set(_record.trace_event(tool="t", label="l", summary="s")) == \
            {"step", "tool", "label", "summary", "ok", "refused", "ms"}
        assert _record.trace_event(tool="t", label="l", summary="s") == \
            {"step": 1, "tool": "t", "label": "l", "summary": "s",
             "ok": True, "refused": False, "ms": 0}
