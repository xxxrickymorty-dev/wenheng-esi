# -*- coding: utf-8 -*-
"""监测版解读盾口径回归（20261104）：compose_text 走自由校验（validate_free）。

背景：原实现 anchored=True（锚定型）——要求映射表里**每个数字恰好出现一次**，
而解读提示词允许「按行文需要自由选取、可重复引用」。数字一密的场景
（多校对比 85 个数）模型稿必然整篇被拒，白等模型后回落规则稿。
修后语义：用到的 [[n]] 标记必有来源、无游离数字、无未知标记即可。

替身经 `ai.using(brain=…)` 注入（与 AI 层其余用例同一套约定）；
留痕打桩（本用例不测记录面，且避免污染 `out/_ai/ai_calls.jsonl`）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import ai                                          # noqa: E402
from _ai_helpers import ScriptedBrain              # noqa: E402
from ai._brain import Turn                         # noqa: E402
from monitor import insight as mi                  # noqa: E402

_TOPIC = "为 2 所高校的 202609 期 ESI 学科对比报告写一篇 500 字以上的总体解读。"
_FACTS = ["本次对比 2 校，按总被引排序：清华大学（第 1 名）、海南大学（第 300 名）",
          "清华大学上榜 22/22、前1% 22、前1‰ 5"]
_SAFE = "规则拼装兜底。"


def _compose(monkeypatch, brain) -> dict:
    calls: list[tuple] = []
    import ai._writer as _w
    monkeypatch.setattr(_w, "_record_call",
                        lambda *a, **k: calls.append((a, k)))
    with ai.using(brain=brain):
        return mi.compose_text(_TOPIC, _FACTS, _SAFE, label="monitor/insight_compare")


def test_compose_free_subset_marks_pass(monkeypatch):
    """模型稿只引用**部分**标记、且同一标记重复引用 → mode=model（2026-09-29 放宽）。"""
    text = "本次对比覆盖 [[1]] 所高校，[[2]] 期格局与 [[1]] 校的位次关系稳定。"
    res = _compose(monkeypatch, ScriptedBrain([Turn(text=text)]))
    assert res["mode"] == "model", "子集+重复引用必须过盾（锚定型是历史行为）"
    assert "[[" not in res["text"], "还原后不得残留标记"
    assert "2 所高校" in res["text"] and "202609" in res["text"], "标记还原为真实数字"


def test_compose_stray_digit_still_rejected(monkeypatch):
    """游离数字（未走标记）依然拒收 → 回落规则稿：零值外发红线不松。"""
    brain = ScriptedBrain([Turn(text="共 2 所高校。"),   # 游离 2
                            Turn(text="对比 3 所高校。")])  # 恢复一轮仍游离 → 定型回落
    res = _compose(monkeypatch, brain)
    assert res["mode"] == "rule" and res["text"] == _SAFE, "游离数字必须回落"


def test_compose_unknown_mark_rejected(monkeypatch):
    """模型自造映射表里没有的标记 → 拒收回落（未知标记防线不松）。"""
    res = _compose(monkeypatch, ScriptedBrain([Turn(text="格局稳定，见 [[99]]。")]))
    assert res["mode"] == "rule" and res["text"] == _SAFE
