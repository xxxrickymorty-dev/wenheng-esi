# -*- coding: utf-8 -*-
"""AI 层测试替身与断言小工具（SPEC §3：Scripted / Failing 只进 tests，不进生产包）。"""
from __future__ import annotations

import json
import pathlib
import re

from ai._brain import BrainError, Turn
from src import state_store

__all__ = ["BrainError", "FailingBrain", "ScriptedBrain", "Turn", "brief_texts",
           "raw_digits", "seed_period", "tool_texts"]

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "ai"

#: 复核构建器的红件样例（每个来源类别各一条；供 seed_period 用）。
RED_SAMPLE = [
    {"location": "T01/表头", "old": "接近度较7月", "new": "接近度较5月",
     "source": "期次参数（上期月份）"},
    {"location": "T20/行22", "old": "139", "new": "135", "source": "table2.csv"},
    {"location": "T19/行03", "old": "84.5", "new": "85.2", "source": "宽表 parquet（台账派生）"},
    {"location": "正文/p4", "old": "覆盖3个学科", "new": "覆盖【手工：学科数】个学科",
     "source": "sentences.py（句骨架+数字槽）"},
    {"location": "正文/p6", "old": "9", "new": "7",
     "source": "extract_province（11 校名单来自人工原件）"},
    {"location": "图/预测", "old": "SARIMA模型", "new": "SARIMA模型",
     "source": "report_forecast（V1 推荐模型）"},
]

_MARK = re.compile(r"\[\[\d+\]\]")
_NUM = re.compile(r"\d+(?:\.\d+)?")


#: 馆员已填手工槽样例（镜像 202607 审核台 1A 实填值；供 seed_period 用）。
MANUAL_SAMPLE = {
    "正文/p1::ESI发布日期": {"value": "2026年7月9日", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/p1::当期机构总数": {"value": "10428", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/p2::去年同期升幅%": {"value": "9.72%", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/p4::学科数": {"value": "19", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/top_section::学科数": {"value": "19", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/province_p::总数": {"value": "54", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/province_p::增减": {"value": "1", "by": "demo", "at": "2026-09-29 07:41:27"},
    "正文/province_p::新晋学科描述": {"value": "云南中医药大学临床医学为新晋ESI前1%学科",
                                     "by": "demo", "at": "2026-09-29 07:41:27"},
}


def seed_period(root, period="202607", *, facts=None, meta=None, red=True, manual=True):
    """给测试数据根落一份最小可用期次产物（overview_facts + meta [+ red_slots + 填写入库]）。

    事实金样＝`tests/fixtures/ai/overview_facts_202607.json`（真产物快照，不触网）。
    `manual=False` 时不落馆员填值（状态库里没有该期行）——用来测「未填槽位整句丢」。
    填写已入库（ADR-0012）：库落在 `root/_state/wenheng.sqlite`（期次目录的同级），
    不再写 `manual_inputs.json`。
    """
    d = pathlib.Path(root) / period
    d.mkdir(parents=True, exist_ok=True)
    if facts is None:
        facts = json.loads((FIXTURES / "overview_facts_202607.json").read_text(encoding="utf-8"))
    (d / "overview_facts.json").write_text(json.dumps(facts, ensure_ascii=False),
                                           encoding="utf-8")
    if meta is None:
        meta = {"period_current": period, "period_prev": "202605",
                "assertions": [["PASS", "示例校验"]]}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if red:
        (d / "red_slots.json").write_text(json.dumps(RED_SAMPLE, ensure_ascii=False),
                                          encoding="utf-8")
    if manual:
        state_store.replace_fills(state_store.db_path(d), period, MANUAL_SAMPLE)
    return d


def raw_digits(text: str) -> list:
    """去掉 [[n]] 占位标记后仍可见的数字串（零值外发测试用）。"""
    return _NUM.findall(_MARK.sub("", text or ""))


class ScriptedBrain:
    """按脚本回放 Turn；可选 callable（拿到 Brief 现算），并捕获每次 Brief。

    `is_rule=False` —— 走「模型轮」路径；文本合规则 mode=model，不合规则回落。
    """

    def __init__(self, turns=None, *, name="scripted"):
        self.name = name
        self.is_rule = False
        self.turns = list(turns or [])
        self.briefs = []

    def think(self, brief):
        self.briefs.append(brief)
        if not self.turns:
            return Turn(text=None)
        t = self.turns.pop(0)
        if isinstance(t, BaseException):
            raise t
        if callable(t):
            t = t(brief)
        return t


class FailingBrain:
    """永远抛 `BrainError`，专门验回落链。"""

    name = "failing"
    is_rule = False

    def __init__(self, exc=None):
        self.exc = exc or BrainError("超时")

    def think(self, brief):                                    # noqa: ARG002
        raise self.exc


def brief_texts(brief) -> tuple:
    return brief.egress_texts()


def tool_texts(brief) -> list:
    """Brief.history 里 role:"tool" 消息的正文（工具结果 / 拒答句 / 同参去重句）。"""
    return [str(m.get("content") or "") for m in (brief.history or ())
            if isinstance(m, dict) and m.get("role") == "tool"]
