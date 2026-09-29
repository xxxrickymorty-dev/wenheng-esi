# -*- coding: utf-8 -*-
"""diagnose 迁移验收与行为测试（SPEC §4 步骤 1）。

- **逐字对拍**：rule 输出 vs 迁移前金样（`tests/fixtures/ai/`）——diff 为空；
- 行为钉子（原 `test_agent_narrator.py` 迁来，改从接口观察）：实况点名 / 缺上下文不编造 /
  按句降级 / 字面示例保留 / 规则库 howto 白名单；
- 接缝：flow 尾注判定（segments）、叙事层故障兜底、过渡 shim 与 ai 同文。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

import ai
from agent import flow, heal, narrator

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "ai"
CASES = json.loads((FIX / "diagnose_rule_cases.json").read_text(encoding="utf-8"))

FAIL = CASES["alias"]["failure"]
REPAIR = CASES["alias"]["repair"]


def run_diag(tmp_path, failure, repair, period=None):
    with ai.using(data_root=tmp_path):
        return ai.run("diagnose", period if period is not None else (failure.get("period") or ""),
                      payload={"failure": failure, "repair": repair}, actor="system")


# ============================================================ 1. 逐字对拍（迁移验收）
@pytest.mark.parametrize("name", sorted(CASES))
def test_rule输出与迁移前逐字一致(name, tmp_path):
    case = CASES[name]
    ans = run_diag(tmp_path, case["failure"], case["repair"])
    assert ans.mode == "rule"
    assert ans.text == case["text"], f"[{name}] rule 输出必须 diff 为空"
    assert ans.rule_text == ans.text


def test_诊断报告全文与迁移前逐字一致(tmp_path):
    case = CASES["alias"]
    golden = (FIX / "diagnose_report_alias.md").read_text(encoding="utf-8")
    p = flow._write_diagnosis(tmp_path, "x.xlsx",
                              {"id": "parse", "label": "解析台账", "tool": "run_parse"},
                              dict(case["failure"]), 1,
                              repair=dict(case["repair"]), out_root=tmp_path)
    assert pathlib.Path(p).read_text(encoding="utf-8") == golden, "报告全文 diff 必须为空"


def test_过渡shim与ai同文(tmp_path):
    case = CASES["header"]
    lines, meta = narrator.compose(dict(case["failure"]), case["repair"], data_root=tmp_path)
    ans = run_diag(tmp_path, case["failure"], case["repair"])
    assert "\n".join(lines) == ans.text
    assert meta["backend"] == "rule" and meta["mode"] == "rule"
    assert meta["record_id"].startswith("ai-diagnose-") and ans.record_id


# ============================================================ 2. 行为钉子（从接口观察）
def test_实况点名期次工作表名与期望实际(tmp_path):
    ans = run_diag(tmp_path, FAIL, REPAIR)
    assert "202607" in ans.text and "总被引" in ans.text and "22" in ans.text
    assert "某某新学科" in ans.text, "认不出的名字是人工唯一能直接下手的线索"
    assert ans.text.count("本次失败实况") == 1, "实况属于整次失败，只该出现一次"


def test_期次从失败对象取_文本里没有也不丢(tmp_path):
    f = {"code": "ASSERT_FAIL", "message": "1 项断言未过", "period": "202605",
         "fails": ["新国际排名 期组数≥5"], "diagnostics": {}}
    ans = run_diag(tmp_path, f, None)
    assert "202605" in ans.text
    assert ans.sources[0].pointer == "failure#period" and ans.sources[0].value == "202605"


def test_缺上下文不编造(tmp_path):
    ans = run_diag(tmp_path, {"code": "ASSERT_FAIL", "message": "x"}, None)
    assert ans.text == "", "没有实况就不写实况，别写「None 期」"
    assert ans.mode == "rule" and ans.record_id


def test_按句降级_缺期望实际只丢那一句(tmp_path):
    f = {"code": "ASSERT_FAIL", "message": "1 项断言未过", "period": "202607",
         "fails": ["新国际排名 期组数≥5"], "diagnostics": {}}
    rec = {"rule": "header_offset", "why": "馆员尚未声明参数", "doc": "§6.5",
           "advice": "请填 declared"}
    ans = run_diag(tmp_path, f, {"advice": [rec]})
    assert "怎么核对" in ans.text and "第几行" in ans.text, "主体动作不能因缺数字就整段消失"
    assert "期望" not in ans.text, "缺 expect/actual 时那句该被丢掉，而不是写「期望 None」"


def test_字面示例占位符不被吃掉(tmp_path):
    f = {"code": "ASSERT_FAIL", "message": "1 项断言未过", "period": "202607",
         "fails": ["新国际排名 期组数≥5"], "diagnostics": {}}
    rec = {"rule": "header_offset", "why": "x", "doc": "x", "advice": "x"}
    ans = run_diag(tmp_path, f, {"advice": [rec]})
    assert "{工作表名: 行号}" in ans.text, "规则库里给人看的示例不能被当成待填占位符"


# ============================================================ 3. 数字与来源一一对应
def test_每个数字都有来源_计数一致(tmp_path):
    ans = run_diag(tmp_path, FAIL, REPAIR)
    n_digits = len(re.findall(r"\d+(?:\.\d+)?", ans.text))
    assert n_digits == len(ans.sources) == ans.shield.checked == ans.shield.passed
    kinds = {s.kind for s in ans.sources}
    assert kinds <= {"ledger_cell", "product", "fact", "failure"}
    assert "failure" in kinds and "fact" in kinds, "失败回执与规则库原文都要能指向"
    assert [s.index for s in ans.sources] == list(range(1, len(ans.sources) + 1))


# ============================================================ 4. 规则库体检（原 narrator 测试迁入）
def test_所有规则的howto占位符都是白名单键():
    """`{sheetname}` 这类拼错的键会**静默**让整句拼不出来 —— 只能靠扫一遍钉住。"""
    allowed = {"sheet", "metric", "period", "expect", "actual", "missing", "names"}
    bad = []
    for r in heal.load_rules():
        tpl = r.get("howto")
        if not tpl:
            bad.append(f"{r['id']}: 缺 howto")
            continue
        for key in {k for k in re.findall(r"\{([^{}]+)\}", str(tpl)) if k.isidentifier()}:
            if key not in allowed and not key.startswith("工作表"):
                bad.append(f"{r['id']}: 未知占位符 {{{key}}}")
    assert not bad, "规则库 howto 有拼错/未登记的占位符：" + "；".join(bad)


def test_每条规则都有howto():
    missing = [r["id"] for r in heal.load_rules() if not r.get("howto")]
    assert not missing, f"这些规则没有核对动作模板：{missing}"


# ============================================================ 5. flow 尾注接缝（segments 判定）
def _report(tmp_path, *, repair, monkeypatch_brain=None):
    case = CASES["alias"]
    scope = ai.using(data_root=tmp_path, brain=monkeypatch_brain) if monkeypatch_brain \
        else ai.using(data_root=tmp_path)
    with scope:
        p = flow._write_diagnosis(tmp_path, "x.xlsx",
                                  {"id": "parse", "label": "解析台账", "tool": "run_parse"},
                                  dict(case["failure"]), 1,
                                  repair=dict(repair or case["repair"]), out_root=tmp_path)
    return pathlib.Path(p).read_text(encoding="utf-8")


def test_规则态尾注_未经过模型加工(tmp_path):
    from _ai_helpers import Turn, ScriptedBrain
    # 默认 RuleBrain（不注入）——尾注必须与迁移前逐字一致
    doc = _report(tmp_path, repair=REPAIR)
    assert "未经过模型加工。" in doc


def test_模型段尾注_交代润色与留痕(tmp_path):
    from _ai_helpers import Turn, ScriptedBrain
    brain = ScriptedBrain([lambda brief: Turn(text=brief.task)])
    doc = _report(tmp_path, repair=REPAIR, monkeypatch_brain=brain)
    assert "后端润色" in doc and "留痕 ai-diagnose-" in doc
    assert "未经过模型加工" not in doc


def test_叙事层抛异常也不影响报告产出(tmp_path, monkeypatch):
    """兜底路径：宁可贴回静态文案，也不能让《诊断报告》写不出来。"""

    def boom(*a, **k):
        raise RuntimeError("ai 炸了")
    monkeypatch.setattr(ai, "run", boom)
    doc = _report(tmp_path, repair=REPAIR)
    assert "# 诊断报告" in doc
    assert "需人工" in doc, "异常时要退回旧写法，建议一条都不能少"
