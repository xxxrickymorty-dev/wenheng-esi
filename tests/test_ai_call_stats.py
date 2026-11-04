# -*- coding: utf-8 -*-
"""模型调用统计口（契约 #40，2026-11-04）：`ai._record.aggregate_calls`
与 `GET /api/ai/call-stats`。

口径（照契约冻结）：
- modes：`model`＝模型轮成功；`failed`＝模型轮回落（mode=fallback，
  原因码进 labels[].fallback）；`rule`＝其余（纯规则轮/关闭态）——
  total ＝ 三者之和；
- label 缺失按 capability 归组；labels 按 total 降序、再按名字典序；
- 只算 kind=call（switch 审计不算），坏行/坏文件跳过；
- 没有任何记录 → 全零结构，不报错。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ai                                                        # noqa: E402
from ai import _record                                           # noqa: E402
from server import app as app_module                             # noqa: E402


def _call_line(**kw):
    """一条最小调用记录（build_call 的记录面关键字段 + 覆盖项）。"""
    rec = {
        "schema": 1, "kind": "call",
        "record_id": kw.get("record_id", "ai-qa-x"),
        "ts": kw.get("ts", "2026-11-04T10:00:00"),
        "period": kw.get("period", "202607"),
        "capability": kw.get("capability", "qa"),
        "actor": "admin",
        "mode": kw.get("mode", "rule"),
        "backend": kw.get("backend", "rule"),
        "fallback": kw.get("fallback"),
        "shield": {"checked": 0, "passed": 0},
        "question": "", "text_sha256": "", "text_preview": "",
    }
    if kw.get("label") is not None:
        rec["label"] = kw["label"]
    return json.dumps(rec, ensure_ascii=False)


def _seed(root, period, lines):
    p = root / str(period) / "ai_calls.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================================ 聚合函数
def test_空记录_全零结构不报错(tmp_path):
    got = _record.aggregate_calls(tmp_path)
    assert got == {"total": 0, "modes": {"model": 0, "rule": 0, "failed": 0},
                   "labels": []}


def test_三路mode计数与total一致(tmp_path):
    _seed(tmp_path, "202607", [
        _call_line(mode="model"),
        _call_line(mode="rule"),
        _call_line(mode="fallback", fallback="brain_error:timeout"),
    ])
    got = _record.aggregate_calls(tmp_path)
    assert got["total"] == 3
    assert got["modes"] == {"model": 1, "rule": 1, "failed": 1}


def test_回落原因码进label桶(tmp_path):
    _seed(tmp_path, "202607", [
        _call_line(label="flexible/single_trend/学科概况",
                   mode="fallback", fallback="brain_error:timeout"),
        _call_line(label="flexible/single_trend/学科概况",
                   mode="fallback", fallback="guard_reject"),
        _call_line(label="flexible/single_trend/学科概况",
                   mode="fallback", fallback="brain_error:timeout"),
    ])
    got = _record.aggregate_calls(tmp_path)
    assert len(got["labels"]) == 1
    b = got["labels"][0]
    assert b["label"] == "flexible/single_trend/学科概况"
    assert b["total"] == 3 and b["failed"] == 3 and b["model"] == 0
    assert b["fallback"] == {"brain_error:timeout": 2, "guard_reject": 1}


def test_无label按capability归组_跨期次同桶(tmp_path):
    _seed(tmp_path, "202607", [_call_line(capability="qa", mode="model")])
    _seed(tmp_path, "202609", [_call_line(capability="qa", mode="rule")])
    _seed(tmp_path, "_ai", [_call_line(capability="dialog", mode="rule",
                                       period=None)])
    got = _record.aggregate_calls(tmp_path)
    names = {b["label"]: b for b in got["labels"]}
    assert names["qa"]["total"] == 2 and names["qa"]["model"] == 1
    assert names["dialog"]["total"] == 1
    assert got["total"] == 3


def test_switch审计与坏行跳过(tmp_path):
    _seed(tmp_path, "_ai", [
        json.dumps({"schema": 1, "kind": "switch", "ts": "t",
                    "capability": "qa", "from": True, "to": False},
                   ensure_ascii=False),
        "{这不是json",
        "",
        _call_line(mode="model"),
    ])
    got = _record.aggregate_calls(tmp_path)
    assert got["total"] == 1 and got["modes"]["model"] == 1


def test_labels按total降序再按名字典序(tmp_path):
    _seed(tmp_path, "202607", [
        _call_line(label="monitor/insight", mode="rule"),
        _call_line(label="b位", mode="model"), _call_line(label="b位", mode="model"),
        _call_line(label="a位", mode="model"), _call_line(label="a位", mode="model"),
    ])
    got = _record.aggregate_calls(tmp_path)
    assert [b["label"] for b in got["labels"]] == ["a位", "b位", "monitor/insight"]


def test_缺文件与缺期次目录都安静(tmp_path):
    (tmp_path / "202607").mkdir()                    # 期次目录在、没有 ai_calls
    assert _record.aggregate_calls(tmp_path)["total"] == 0


# ============================================================ 路由
class _Req:
    def __init__(self, user):
        self.session = {"user": user} if user else {}


def _route(user="admin"):
    return asyncio.run(app_module.api_ai_call_stats(_Req(user)))


def test_路由_读当前数据根_管理员可用(tmp_path):
    _seed(tmp_path, "202607", [_call_line(mode="model")])
    with ai.using(data_root=tmp_path):
        got = _route()
    assert got["total"] == 1 and got["modes"] == {
        "model": 1, "rule": 0, "failed": 0}


def test_路由_非admin拦下(tmp_path):
    # 守卫直接调用姿势拿到响应对象：匿名 401、操作员 403（与既有路由同口径）。
    assert _route(user=None).status_code == 401
    assert _route(user="operator").status_code == 403
