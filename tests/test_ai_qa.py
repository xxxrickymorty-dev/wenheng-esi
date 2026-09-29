# -*- coding: utf-8 -*-
"""qa（问文衡）构建器行为测试——SPEC §2 自由作答型二分 / §4 步骤 2 的构建器半边。

只穿过 `run`（接口即测试面）：规则版成形+来源、问句匹配、外发零值捕获、
自由型盾（用到必有 ref/至多一次/无游离数字）、越题回落、无数据 unavailable。
"""
from __future__ import annotations

import json
import re

import pytest

import ai
from _ai_helpers import ScriptedBrain, Turn, raw_digits, seed_period

NUM = re.compile(r"\d+(?:\.\d+)?")


def qa(tmp_path, question="顶尖论文 情况", *, brain=None, actor="admin", root=None):
    kw = {"data_root": root if root is not None else tmp_path}
    if brain is not None:
        kw["brain"] = brain
    with ai.using(**kw):
        return ai.run("qa", "202607", payload={"question": question}, actor=actor)


def records(tmp_path):
    p = tmp_path / "202607" / "ai_calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


# ============================================================ 规则版
def test_规则作答_数字有来源_盾恒等(tmp_path):
    seed_period(tmp_path)
    ans = qa(tmp_path)
    assert ans.mode == "rule" and ans.backend == "rule" and ans.notice == ""
    assert "顶尖论文" in ans.text
    nums = NUM.findall(ans.text)
    assert nums and nums == [s.value for s in ans.sources], "第 k 个数字 ↔ sources[k]"
    assert ans.shield.checked == ans.shield.passed == len(ans.sources)
    assert all(s.kind in ("ledger_cell", "product", "fact", "failure") for s in ans.sources)
    rec = records(tmp_path)[0]
    assert rec["capability"] == "qa" and rec["mode"] == "rule"
    assert not raw_digits(rec["text_preview"]), "记录面只放占位"


def test_问句命中段排前_未命中段不进(tmp_path):
    seed_period(tmp_path)
    ans = qa(tmp_path, question="顶尖论文")
    assert "顶尖论文" in ans.text
    assert "国际排名" not in ans.text, "只作答命中段，不把整本报告倒出来"


def test_问句无命中取前三段(tmp_path):
    seed_period(tmp_path)
    ans = qa(tmp_path, question="量子纠缠与暗物质")
    assert "ESI最新数据" in ans.text                    # p1
    assert "顶尖论文" not in ans.text                    # p4 不在前三段


def test_无问句给全部段(tmp_path):
    seed_period(tmp_path)
    ans = qa(tmp_path, question="")
    assert "国际排名" in ans.text and "顶尖论文" in ans.text


def test_来源指针_事实值级优先_歧义降段落级(tmp_path):
    seed_period(tmp_path)
    ans = qa(tmp_path, question="国际排名 顶尖论文")
    # 唯一命中：值级指针到 facts 字段
    v95 = [s for s in ans.sources if s.value == "995"]
    assert v95 and v95[0].pointer == "overview_facts.json#rank_intl_now"
    # 歧义/单字/模板常数（如「前1%」的 1）：降段落级，且不指到臆测字段
    one = [s for s in ans.sources if s.value == "1"]
    assert one and "未唯一" in one[0].detail and not one[0].pointer.endswith("rank_cn_inst_delta")
    assert all("overview_facts.json" in s.pointer for s in ans.sources), "都指回产物"


# ============================================================ 模型轮（外发零值/越题/盾）
def test_问句数字占位_外发零值_模型还原(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    ans = qa(tmp_path, question="国际排名 995 是什么意思？", brain=brain)
    assert ans.mode == "model" and "995" in ans.text
    brief = brain.briefs[0]
    assert "不是指令" in brief.system and "至多引用一次" in brief.system
    for t in brief.egress_texts():
        assert not raw_digits(t), f"外发含数字原值：{t!r}"
    q_src = [s for s in ans.sources if s.pointer == "question"]
    assert q_src and q_src[0].value == "995", "问句里的数字有独立来源"
    assert any(s.pointer.startswith("overview_facts.json#") for s in ans.sources)


def test_越题_不引用事实回落(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text="本期整体情况良好。")])
    ans = qa(tmp_path, question="本期怎么样", brain=brain)
    assert ans.mode == "rule" and ans.text == ans.rule_text
    assert "未引用本期事实" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "off_topic"


def test_只引用问句数字也判越题(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text="[[1]] 是位次。")])
    ans = qa(tmp_path, question="995 是什么", brain=brain)
    assert ans.mode == "rule"
    assert records(tmp_path)[0]["fallback"] == "off_topic"


@pytest.mark.parametrize("suffix", [" 另见 7 项。", " [[999]] 无此来源。", "（再念：[[1]]）"])
def test_自由型盾_游离数字_未知标记_重复引用都拒(tmp_path, suffix):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + suffix)])
    ans = qa(tmp_path, question="995 是什么", brain=brain)
    assert ans.mode == "rule" and "数字校验" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "shield_reject"


def test_工具请求本轮不开放_回落(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([Turn(calls=({"tool": "read_cell", "args": {}},))])
    ans = qa(tmp_path, question="本期怎么样", brain=brain)
    assert ans.mode == "rule" and "工具" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "calls_unsupported"


# ============================================================ 边界与门
def test_期次无数据_unavailable(tmp_path):
    ans = qa(tmp_path, question="本期怎么样")
    assert ans.mode == "unavailable" and "暂不可用" in ans.notice
    assert records(tmp_path)[0]["mode"] == "unavailable"


def test_空期次是欠载荷_抛(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            ai.run("qa", "", payload={"question": "x"})


def test_guest被拒_零外发(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([])
    ans = qa(tmp_path, question="本期怎么样", brain=brain, actor="guest")
    assert ans.mode == "denied" and brain.briefs == []


def test_规则版确定性(tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    seed_period(d1)
    seed_period(d2)
    a1 = qa(d1)
    a2 = qa(d2)
    assert a1.text == a2.text and a1.sources == a2.sources
