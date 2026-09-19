# -*- coding: utf-8 -*-
"""《诊断报告》叙事层（B 档）· 2026-09-19。

钉的是四类失效，每一类都静默：
  ① 后端配错 / 依赖缺失 → 报告写不出来（诊断报告是升级态唯一交接物）
  ② 模型改了数字 → 人工照着错的数去核对
  ③ 规则库 howto 里写错占位符名（如 {sheetname}）→ 那句永远拼不出来，且没报错
  ④ 「本次实况」没点名期次与学科 → 又退回"回去自己数 22 行"
"""
from __future__ import annotations

import pathlib
import re

import pytest

from agent import heal, narrator

#: 一条"学科名认不出来"的失败（与 tests/test_agent_heal.py 同形态）
FAIL = {
    "code": "ASSERT_FAIL",
    "message": "2 项断言未过",
    "period": "202607",
    "fails": ["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
    "diagnostics": {"unmatched_names": {"total_cites": ["某某新学科"]}},
}
REC = {"rule": "discipline_alias_map", "why": "未确认规则类型（R-24）",
       "doc": "WH-DOC-04 §6.5", "advice": "请馆员核对该学科归属后填 approved_by"}


def ctx_of(failure=None):
    return narrator.extract_context(failure or FAIL)


# ============================================================ 1. 后端选择
def test_默认后端是规则_演示站零依赖(monkeypatch):
    monkeypatch.delenv(narrator.ENV_BACKEND, raising=False)
    assert narrator.backend_of() == "rule"
    assert narrator.backend_of(None) == "rule"


def test_未知后端名回落规则_不抛(monkeypatch):
    assert narrator.backend_of("gpt-4o") == "rule"
    monkeypatch.setenv(narrator.ENV_BACKEND, "GPT4")
    assert narrator.backend_of() == "rule"


# ============================================================ 2. 上下文抽取
def test_实况点名期次工作表名与期望实际():
    ctx = ctx_of()
    assert ctx["period"] == "202607"
    assert ctx["sheet"] == "总被引", "宽表指标名要翻成台账工作表中文名"
    assert (ctx["expect"], ctx["actual"]) == ("22", "21")
    line = narrator._fact_line(ctx)
    assert line and "202607" in line and "总被引" in line and "22" in line


def test_期次从失败对象取_文本里没有也不丢(monkeypatch):
    """`run_parse` 一定在 ToolError 上挂 period；断言消息里未必有。"""
    f = {"code": "ASSERT_FAIL", "message": "1 项断言未过",
         "period": "202605", "fails": ["新国际排名 期组数≥5"], "diagnostics": {}}
    assert narrator.extract_context(f)["period"] == "202605"


def test_认不出的学科名被点名():
    ctx = ctx_of()
    assert ctx["names"] and "某某新学科" in ctx["names"], \
        "升级交给人工的报告里，认不出的名字是唯一能直接下手的线索"


def test_上下文缺失时为None_不编造():
    ctx = narrator.extract_context({"code": "ASSERT_FAIL", "message": "x"})
    assert ctx["period"] is None and ctx["sheet"] is None
    assert narrator._fact_line(ctx) is None, "没有实况就不写实况，别写「None 期」"


# ============================================================ 3. 按句降级
def test_缺上下文时只丢那一句_动作说明主体保留():
    """表头偏移这类失败拿不到期望/实际，但"去数表头在第几行"才是最有用的。"""
    f = {"code": "ASSERT_FAIL", "message": "1 项断言未过", "period": "202607",
         "fails": ["新国际排名 期组数≥5"], "diagnostics": {}}
    rec = {"rule": "header_offset", "why": "馆员尚未声明参数", "doc": "§6.5",
           "advice": "请填 declared"}
    lines, meta = narrator.advise(rec, narrator.extract_context(f))
    text = "\n".join(lines)
    assert "怎么核对" in text and "第几行" in text, "主体动作不能因为缺数字就整段消失"
    assert "期望" not in text, "缺 expect/actual 时那句该被丢掉，而不是写「期望 None」"


def test_字面示例占位符不被吃掉():
    """规则库里 `{工作表名: 行号}` 是给人看的示例，不能被当成待填占位符。"""
    rec = {"rule": "header_offset", "why": "x", "doc": "x", "advice": "x"}
    ctx = {"sheet": "新国际排名", "period": "202607", "expect": "22", "actual": "21"}
    lines, _ = narrator.advise(rec, ctx)
    assert "{工作表名: 行号}" in "\n".join(lines)


# ============================================================ 4. 模型后端与防护盾
def test_模型改了数字就回退规则输出(monkeypatch):
    monkeypatch.setattr(narrator, "_model_generate",
                        lambda p, b: "本次期望 99 个学科、实际认出 11 个，请打开「化学」表。")
    lines, meta = narrator.advise(REC, ctx_of(), backend="ollama")
    text = "\n".join(lines)
    assert meta["mode"] == "fallback"
    assert "99" not in text and "11" not in text, "模型改数字 → 整段回退，一个字都不采信"
    assert "规则库口径" in text


def test_模型调用失败也回退(monkeypatch):
    def boom(p, b):
        raise RuntimeError("ollama 没起")
    monkeypatch.setattr(narrator, "_model_generate", boom)
    lines, meta = narrator.advise(REC, ctx_of(), backend="ollama")
    assert meta["mode"] == "fallback" and "ollama" in meta["reason"]
    assert "怎么核对" in "\n".join(lines), "回退后仍要有可用的指引"


def test_润色通过时数字原样保留(monkeypatch):
    """阳性对照：没动数字的润色应当被采纳（否则后端接了等于没接）。"""
    def ok(p, b):
        # 原样返回含占位符的文本 —— 模拟"只改了措辞"
        return p.split("原文：")[-1].strip() + "，请尽快处理。"
    monkeypatch.setattr(narrator, "_model_generate", ok)
    lines, meta = narrator.advise(REC, ctx_of(), backend="ollama")
    assert meta["mode"] == "polished"
    text = "\n".join(lines)
    assert "22" in text and "21" in text, "数字必须还在"


def test_规则后端不调模型(monkeypatch):
    monkeypatch.setattr(narrator, "_model_generate",
                        lambda p, b: pytest.fail("rule 后端不该碰模型"))
    lines, meta = narrator.advise(REC, ctx_of(), backend="rule")
    assert meta["mode"] == "rule"


# ============================================================ 5. 规则库口径
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


# ============================================================ 6. 与《诊断报告》的接缝
def test_实况成节且不与规则小节重复(tmp_path):
    """`FAIL` 的形态必然让 header_offset / split_column_group 被拒（未批准），
    advice 因此非空 —— 不需要 skip，缺了就是真坏了。"""
    repair = heal.attempt(dict(FAIL), {"run_dir": str(tmp_path)})
    seg, meta = narrator.compose(dict(FAIL), repair)
    assert seg, "该失败形态下必然有需人工项（两条未批准规则被拒）"
    text = "\n".join(seg)
    assert "本次失败实况" in text
    assert text.count("本次失败实况") == 1, "实况属于整次失败，只该出现一次"
    assert meta["backend"] == "rule"


def test_写诊断报告时叙事层抛异常也不影响报告产出(tmp_path, monkeypatch):
    """兜底路径：宁可贴回静态文案，也不能让《诊断报告》写不出来。"""
    from agent import flow

    def boom(*a, **k):
        raise RuntimeError("narrator 炸了")
    monkeypatch.setattr(narrator, "compose", boom)
    repair = heal.attempt(dict(FAIL), {"run_dir": str(tmp_path)})
    p = flow._write_diagnosis(str(tmp_path), "x.xlsx",
                              {"id": "parse", "label": "解析台账", "tool": "run_parse"},
                              dict(FAIL), 1, repair=repair)
    doc = pathlib.Path(p).read_text(encoding="utf-8")
    assert "# 诊断报告" in doc
    if repair and repair.get("advice"):
        assert "需人工" in doc, "异常时要退回旧写法，建议一条都不能少"


def test_报告末尾交代有没有经模型加工(tmp_path):
    """报告里出现模型生成的内容必须可追溯 —— 不能靠读代码猜。"""
    from agent import flow
    repair = heal.attempt(dict(FAIL), {"run_dir": str(tmp_path)})
    p = flow._write_diagnosis(str(tmp_path), "x.xlsx",
                              {"id": "parse", "label": "解析台账", "tool": "run_parse"},
                              dict(FAIL), 1, repair=repair)
    doc = pathlib.Path(p).read_text(encoding="utf-8")
    assert ("未经过模型加工" in doc) or ("后端" in doc)
