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


@pytest.mark.parametrize("suffix", [" 另见 7 项。", " [[999]] 无此来源。"])
def test_自由型盾_游离数字_未知标记都拒(tmp_path, suffix):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + suffix)])
    ans = qa(tmp_path, question="995 是什么", brain=brain)
    assert ans.mode == "rule" and "数字校验" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "shield_reject"


def test_自由型盾_重复引用同一来源放行(tmp_path):
    """真实模型写「前 [[1]]%…前 [[1]]%」很自然——重复引用不产生新事实，放行。"""
    seed_period(tmp_path)

    def dup(brief):
        m = re.search(r"\[\[\d+\]\]", "\n".join(brief.evidence))
        assert m, "证据里应有占位符"
        marker = m.group(0)
        return Turn(text=f"参考数据里，{marker} 与 {marker} 都是本期事实。")

    ans = qa(tmp_path, question="顶尖论文", brain=ScriptedBrain([dup]))
    assert ans.mode == "model" and ans.text.count("274") == 2
    assert records(tmp_path)[0]["fallback"] is None


def test_工具请求本轮不开放_回落(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([Turn(calls=({"tool": "read_cell", "args": {}},))])
    ans = qa(tmp_path, question="本期怎么样", brain=brain)
    assert ans.mode == "rule" and "工具" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "calls_unsupported"


# ============================================================ 学科问题直答（2026-10-11 rick 定）
_TABLE_FIELDS = ["discipline", "rank_cn_change", "papers", "cnci", "total_cites",
                 "thr_1pct", "thr_1pct_gap", "thr_1permille", "permille_rank",
                 "top_papers", "prox_change"]


def _seed_table2(tmp_path):
    """给测试期次落一份 table2.csv（两行：化学 / 生物学与生物化学）。"""
    import csv
    d = tmp_path / "202607"
    d.mkdir(exist_ok=True)
    with (d / "table2.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_TABLE_FIELDS)
        w.writeheader()
        w.writerow({"discipline": "Chemistry", "rank_cn_change": "154/↓1", "papers": "2590",
                    "cnci": "1.454", "total_cites": "51529", "thr_1pct": "7622",
                    "thr_1pct_gap": "43907", "thr_1permille": "99622",
                    "permille_rank": "2.384", "top_papers": "44", "prox_change": "↑34.83%"})
        w.writerow({"discipline": "Biology & Biochemistry", "rank_cn_change": "301/↑1",
                    "papers": "900", "cnci": "1.10", "total_cites": "9000", "thr_1pct": "7000",
                    "thr_1pct_gap": "-2000", "thr_1permille": "90000",
                    "permille_rank": "10.0", "top_papers": "9", "prox_change": "↑1.00%"})
        w.writerow({"discipline": "Mathematics", "rank_cn_change": "90/↓1", "papers": "902",
                    "cnci": "1.08", "total_cites": "5568", "thr_1pct": "5185",
                    "thr_1pct_gap": "-383", "thr_1permille": "21080",
                    "permille_rank": "26.4", "top_papers": "9", "prox_change": "↑3.54%"})


def test_学科问题直答_数字来源到格(tmp_path):
    """问「化学的接近度」→ 直答该学科数据行（规则版也直答），数字回指 table2 的格。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    ans = qa(tmp_path, question="查一下化学的接近度")
    assert ans.mode == "rule"
    assert "化学（Chemistry）" in ans.text and "676.06" in ans.text, ans.text[:160]
    by_val = {s.value: s for s in ans.sources}
    assert by_val["51529"].pointer == "table2.csv#Chemistry.total_cites"
    assert by_val["2590"].pointer == "table2.csv#Chemistry.papers"
    assert by_val["676.06"].pointer.startswith("table2.csv#Chemistry（总被引÷阈值）")
    assert by_val["676.06"].label.endswith("前 1% 接近度（系统换算）")
    assert "国际排名" not in ans.text, "学科直答不把整本报告倒出来"


def test_学科长名优先_不被子串截胡(tmp_path):
    """「生物学与生物化学」先被长名吃掉，不让「化学」子串误命中 Chemistry。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    ans = qa(tmp_path, question="生物学与生物化学怎么样")
    assert "生物学与生物化学（Biology & Biochemistry）" in ans.text
    assert "化学（Chemistry）" not in ans.text


def test_学科问题_模型轮证据带学科段(tmp_path):
    """模型轮：学科段排在证据最前，外发面仍是占位（零数字原值）。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    ans = qa(tmp_path, question="化学的接近度是多少", brain=brain)
    ev = brain.briefs[0].evidence
    assert ev and ev[0].startswith("化学（Chemistry）"), "学科段必须在证据最前"
    for t in brain.briefs[0].egress_texts():
        assert not raw_digits(t), f"外发含数字原值：{t!r}"
    assert ans.mode == "model" and "676.06" in ans.text


def test_无学科问句_行为与旧版一致(tmp_path):
    """没点学科时没有学科段——命中段作答（不回归）。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    ans = qa(tmp_path, question="顶尖论文")
    assert "顶尖论文" in ans.text and "化学（Chemistry）" not in ans.text


# ============================================================ 台账问答（2026-10-11 rick 定）
def _seed_ledger(tmp_path, monkeypatch):
    """给测试仓落一份「台账投喂副本」占位文件 + 假 load_ledger（真解析在台账测试外覆盖）。"""
    import pandas as pd
    import parse_ledger
    root = tmp_path / "repo" / "out"
    seed_period(root)
    _seed_table2(root)
    led_dir = tmp_path / "repo" / "input" / "202607"
    led_dir.mkdir(parents=True, exist_ok=True)
    (led_dir / "监测表.xlsx").write_bytes(b"placeholder")
    fake = {
        "wide": {
            "proximity_1pct": pd.DataFrame(
                {"202605": [6.1842], "202607": [6.760561]}, index=["Chemistry"]),
            "papers": pd.DataFrame({"202607": [2590.0]}, index=["Chemistry"]),
        },
        "rank_cn": pd.DataFrame([{"discipline": "Chemistry", "period": "202607",
                                  "rank": 154.0}]),
        "entry_events": [("202409", "Mathematics", "in"), ("202605", "Mathematics", "out"),
                         ("202607", "Mathematics", "in")],
        "entered_1pct": pd.DataFrame({"202607": [1.0]}, index=["Chemistry"]),
        "ynd_rank": pd.DataFrame({"rank_intl": [995.0], "rank_cn": [155.0],
                                  "rank_cn_uni": [130.0]}, index=["202607"]),
    }
    monkeypatch.setattr(parse_ledger, "load_ledger", lambda path: fake)
    return root


def test_台账问答_学科指标历史到格(tmp_path, monkeypatch):
    root = _seed_ledger(tmp_path, monkeypatch)
    ans = qa(root, question="化学的接近度最近几期怎么变的")
    assert "台账《接近度》表" in ans.text and "676.06%" in ans.text
    led = {s.pointer: s for s in ans.sources if s.kind == "ledger_cell"}
    assert "台账#接近度/化学/202607" in led, led.keys()
    assert led["台账#接近度/化学/202607"].value == "676.06"
    assert any(s.pointer == "台账#接近度/化学/202605" for s in ans.sources)


def test_台账问答_论文数与国内排名(tmp_path, monkeypatch):
    root = _seed_ledger(tmp_path, monkeypatch)
    ans = qa(root, question="化学的论文数")
    assert "台账《论文数》表" in ans.text and "2590" in ans.text
    ans2 = qa(root, question="化学的国内排名")
    assert "台账《国内排名》表" in ans2.text and "154" in ans2.text
    assert any(s.pointer == "台账#国内排名/化学/202607" for s in ans2.sources)


def test_台账问答_云大排名走势(tmp_path, monkeypatch):
    root = _seed_ledger(tmp_path, monkeypatch)
    ans = qa(root, question="云南大学国际排名走势")
    assert "台账《云大ESI排名》表" in ans.text and "995" in ans.text
    assert any(s.pointer == "台账#云大ESI排名/云南大学/202607" for s in ans.sources)


def test_台账问答_进出前百分之一事件(tmp_path, monkeypatch):
    root = _seed_ledger(tmp_path, monkeypatch)
    ans = qa(root, question="数学什么时候进入前1%")
    assert "台账《学科进入时间》表" in ans.text
    assert "202607 进入" in ans.text and "202605 退出" in ans.text
    assert any(s.pointer == "台账#学科进入时间/数学/202607" for s in ans.sources)


def test_台账缺件时_静默回落报告产物(tmp_path, monkeypatch):
    """没有投喂副本 → 不报错、不编数——照旧用报告产物作答。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    ans = qa(tmp_path, question="化学的接近度")
    assert "台账《" not in ans.text
    assert all(s.kind != "ledger_cell" for s in ans.sources)


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


# ============================================================ 检索与手工槽（2026-09-29 修）
def test_无空格整句问热点论文_命中顶尖论文段(tmp_path):
    """rick 实问暴露：整句无空格旧版零命中；「热点论文」报告口径＝「顶尖论文」。"""
    seed_period(tmp_path)
    ans = qa(tmp_path, question="云南大学热点论文数量有多少")
    assert "顶尖论文" in ans.text and "274" in ans.text, ans.text[:120]


def test_手工槽已填回填_未填分句丢_同句数据保留(tmp_path):
    seed_period(tmp_path)                                   # 有馆员填值
    ans = qa(tmp_path, question="ESI数据覆盖时间和机构总数")
    assert "2026年7月9日" in ans.text and "10428" in ans.text
    assert "【手工：" not in ans.text, "已填槽位不该再露裸占位符"
    assert "【手工：" not in ans.rule_text

    other = tmp_path / "nom"
    seed_period(other, manual=False)                        # 没有填值文件
    ans2 = qa(other, question="ESI数据覆盖时间和机构总数")
    assert "【手工：" not in ans2.text, "未填槽位该丢，不端给读者"
    assert "ESI最新数据" not in ans2.text, "含未填槽位的分句要丢"
    # 2026-10-11：同句里没槽位的分句保留（否则「顶尖论文 274 篇」这类总数会被连坐丢掉）
    ans3 = qa(other, question="顶尖论文")
    assert "274" in ans3.text, "同句无槽位的分句必须保留"


def test_未填学科数时_顶尖论文总数仍在(tmp_path):
    """202609 实况（金样总数 291；测试夹具 274）：manual_inputs 缺「学科数」——
    分句级丢弃后总数必须答得出来，且不露「覆盖…个学科」残句。"""
    seed_period(tmp_path, manual=False)
    ans = qa(tmp_path, question="本期顶尖论文有多少篇")
    assert "274" in ans.text and "覆盖" not in ans.text, ans.text[:120]


def test_模型证据含全量段_命中段排前(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    ans = qa(tmp_path, question="云南大学热点论文数量有多少", brain=brain)
    ev = brain.briefs[0].evidence
    assert any("顶尖论文" in e for e in ev), "命中段必须在证据里"
    assert len(ev) >= 10, "证据应为全量段（命中段排前），模型才找得到报告里的内容"
    assert ans.mode == "model" and "274" in ans.text
