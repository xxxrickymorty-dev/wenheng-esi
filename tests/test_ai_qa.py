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


def qa(tmp_path, question="顶尖论文 情况", *, brain=None, actor="admin", root=None,
       history=None):
    kw = {"data_root": root if root is not None else tmp_path}
    if brain is not None:
        kw["brain"] = brain
    with ai.using(**kw):
        return ai.run("qa", "202607",
                      payload={"question": question, "history": history or []},
                      actor=actor)


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


def test_越题_不引用事实_模型照发如实标注(tmp_path):
    # 2026-10-31 rick：问答必须模型作答——越题（多为澄清/概述句）照发，盾已验无游离数字
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text="本期整体情况良好。")])
    ans = qa(tmp_path, question="本期怎么样", brain=brain)
    assert ans.mode == "model" and ans.text == "本期整体情况良好。"
    assert "未引用" in ans.notice
    assert records(tmp_path)[0]["fallback"] == "off_topic"


def test_只引用问句数字也判越题_照发(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text="[[1]] 是位次。")])
    ans = qa(tmp_path, question="995 是什么", brain=brain)
    assert ans.mode == "model"
    assert records(tmp_path)[0]["fallback"] == "off_topic"


@pytest.mark.parametrize("suffix", [" 另见 7 项。", " [[999]] 无此来源。"])
def test_自由型盾_游离数字_未知标记都拒(tmp_path, suffix):
    # 2026-10-31：盾拒不顶规则版——显式失败态（规则版只留「看规则版」参照）
    seed_period(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + suffix)])
    ans = qa(tmp_path, question="995 是什么", brain=brain)
    assert ans.mode == "failed" and "没有作答" in ans.text
    assert ans.rule_text, "规则版留作参照"
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


def test_工具请求本轮不开放_显式失败(tmp_path):
    seed_period(tmp_path)
    brain = ScriptedBrain([Turn(calls=({"tool": "read_cell", "args": {}},))])
    ans = qa(tmp_path, question="本期怎么样", brain=brain)
    assert ans.mode == "failed" and "没有作答" in ans.text
    assert "工具" in ans.notice
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


def test_学科直答_阈值差与权威进入状态(tmp_path):
    """2026-10-15（rick 实问暴露）：直答段给「阈值差」与权威「进入状态」——
    原句尾「超过 100% 即已进入前 1%」的条件被模型拼成断言（"88.01%，已超过 100%"），
    且没有阈值差，模型答「无法算出」。现在两者都是确定值，条件句不再出现。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    import pandas as pd
    wide = tmp_path / "202607" / "wide"
    wide.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"202607": [1.0, 0.0, 0.0]},
                 index=["Chemistry", "Biology & Biochemistry", "Mathematics"]).to_parquet(
        wide / "entered_1pct.parquet")
    ans = qa(tmp_path, question="化学和生物学与生物化学的接近度")
    assert "高出前 1% 阈值 43907 次被引" in ans.text
    assert "距前 1% 阈值还差 2000 次被引" in ans.text
    assert "（ESI 口径：本期已进入前 1%）" in ans.text
    assert "（ESI 口径：本期未进入前 1%）" in ans.text
    assert "超过 100%" not in ans.text, "条件句不得再出现（模型会拼成断言）"
    by_val = {s.value: s for s in ans.sources}
    assert by_val["43907"].pointer == "table2.csv#Chemistry.thr_1pct_gap"
    assert by_val["2000"].pointer == "table2.csv#Biology & Biochemistry.thr_1pct_gap"


def test_学科直答_无进入状态表时不猜(tmp_path):
    """`entered_1pct.parquet` 缺 → 不写进入状态（不回落接近度推断；compute 同口径）。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    ans = qa(tmp_path, question="化学的接近度")
    assert "ESI 口径" not in ans.text
    assert "高出前 1% 阈值 43907 次被引" in ans.text


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


def test_追问_上文进任务_只用于解指代(tmp_path):
    """对话上文进模型任务（「这是几月的」靠它解指代）；上文数字不算本期事实。"""
    seed_period(tmp_path)
    _seed_table2(tmp_path)
    brain = ScriptedBrain([lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    ans = qa(tmp_path, question="这是几月的", brain=brain,
             history=[{"who": "me", "text": "查工程学的接近度，最新一期的"},
                      {"who": "wh", "text": "工程学最新一期（2026 年第 5 期）的接近度为 746.57%"}])
    task = brain.briefs[0].task
    assert "对话上文" in task and "工程学最新一期" in task
    assert "本次问题：这是几月的" in task
    assert "746.57" not in task and "2026" not in task, "上文的数字必须过盾（变标记），不外发原值"
    assert ans.mode == "model"


# ============================================================ 台账问答（2026-10-11 rick 定）
def _seed_ledger(tmp_path, monkeypatch):
    """给测试仓落一份「台账投喂副本」占位文件 + 假 load_ledger（真解析在台账测试外覆盖）。"""
    import pandas as pd
    import parse_ledger
    root = tmp_path / "repo" / "out"
    seed_period(root)
    _seed_table2(root)
    led_dir = tmp_path / "repo" / "input"
    led_dir.mkdir(parents=True, exist_ok=True)
    # 回落视图＝运行时母本（input/ 只放它；2026-10-13 起不再有 input/<期次>/监测表.xlsx）
    (led_dir / "云大全学科排名、阈值动态检测表.xlsx").write_bytes(b"placeholder")
    fake = {
        "wide": {
            "proximity_1pct": pd.DataFrame(
                {"202605": [6.1842], "202607": [6.760561]}, index=["Chemistry"]),
            "papers": pd.DataFrame({"202607": [2590.0]}, index=["Chemistry"]),
        },
        "rank_cn": pd.DataFrame([{"discipline": "Chemistry", "period": "202607",
                                  "rank": 154.0},
                                 {"discipline": "Mathematics", "period": "202607",
                                  "rank": 90.0}]),
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


# ============================================================ 票 02：规划器 / 证据装配（接口级）
class Test规则规划器:
    """问句 → QueryPlan：只出名字（指标/学科/形状），零数值、零期次。"""

    def test_学科指标编译成序列spec(self):
        from ai import _plan
        p = _plan.plan("化学的接近度最近几期怎么变的", discs=["Chemistry"])
        assert p["origin"] == "rule"
        assert p["specs"] == [{"op": "series", "metric": "proximity_1pct",
                               "disc": "Chemistry", "span": "recent"}]

    def test_进出关键词编译成事件spec(self):
        from ai import _plan
        p = _plan.plan("数学什么时候进入前1%", discs=["Mathematics"])
        assert {"op": "events", "disc": "Mathematics"} in p["specs"]

    def test_云大排名编译成整体排名spec(self):
        from ai import _plan
        p = _plan.plan("云南大学国际排名走势", discs=[])
        assert p["specs"] == [{"op": "overall_rank", "span": "recent"}]

    def test_无学科无指标为空(self):
        from ai import _plan
        assert _plan.plan("本期怎么样", discs=[])["specs"] == []

    def test_千分位优先于阈值(self):
        from ai import _plan
        assert _plan.metric_hit("化学的1‰阈值") == "threshold_1permille"
        assert _plan.metric_hit("化学的前1%阈值") == "threshold_1pct"

    def test_spec的键值都在白名单(self):
        """规划输出只含白名单名字（op / metric）；零数字外发是票 03 模型面的事。"""
        from ai import _plan
        from flexible import queries
        p = _plan.plan("化学的接近度", discs=["Chemistry"])
        for spec in p["specs"]:
            assert spec["op"] in queries.SCHEMA["kind"]
            assert spec["metric"] in queries.METRICS


class Test证据装配:
    """Result → 证据段：文本数字全部来自值，cells 由来源链直出（v1 文本逐字保持）。"""

    def _series_res(self):
        return {"kind": "series", "metric": "proximity_1pct", "metric_cn": "ESI前1%接近度",
                "disc": "Chemistry", "disc_cn": "化学", "better": "up", "n": 2,
                "points": [
                    {"period": "202605", "value": 6.1842,
                     "source": {"origin_sheet": "接近度", "discipline": "Chemistry",
                                "discipline_cn": "化学", "period": "202605"}},
                    {"period": "202607", "value": 6.760561,
                     "source": {"origin_sheet": "接近度", "discipline": "Chemistry",
                                "discipline_cn": "化学", "period": "202607"}}]}

    def test_序列渲染_与v1同款文本_到格(self):
        from ai import _evidence
        ev = _evidence.assemble([self._series_res()])
        key, text = ev["chunks"][0]
        assert key == "台账数据·化学·接近度"
        assert text == ("化学 · 接近度（台账《接近度》表，最近二期）："
                        "202605 618.42%、202607 676.06%。")
        assert ("676.06", "接近度", "化学", "202607") in ev["cells"][key]
        assert ("202605", "接近度", "化学", "202605") in ev["cells"][key]

    def test_事件_一直在内(self):
        from ai import _evidence
        res = {"kind": "events", "disc": "Chemistry", "disc_cn": "化学", "n": 0,
               "events": [], "in_since": {"Chemistry": "202607"}}
        ev = _evidence.assemble([res])
        _, text = ev["chunks"][0]
        assert "自台账最早一期（202607）起一直在前 1% 内" in text

    def test_事件_最近一次与此前(self):
        from ai import _evidence
        res = {"kind": "events", "disc": "Mathematics", "disc_cn": "数学", "n": 3,
               "events": [{"period": "202409", "type": "in"},
                          {"period": "202605", "type": "out"},
                          {"period": "202607", "type": "in"}],
               "in_since": {}}
        ev = _evidence.assemble([res])
        _, text = ev["chunks"][0]
        assert "最近一次 202607 进入；此前：202409 进入、202605 退出" in text

    def test_空结果跳过(self):
        from ai import _evidence
        assert _evidence.assemble([])["chunks"] == []
        assert _evidence.assemble([{"kind": "series", "points": []}])["chunks"] == []
        assert _evidence.assemble([{"kind": "未知"}])["chunks"] == []


# ============================================================ 票 03：模型规划器
class Test模型规划器:
    """规则先算；规则为空才问模型；合法 JSON 才用；越权/带数字/坏 JSON → 整份回退。"""

    DISC = ["Chemistry", "Physics", "Mathematics"]

    def _plan_with(self, text, *, question="最近有什么变化", discs=(), history=None):
        from ai import _plan
        brain = ScriptedBrain([Turn(text=text)])
        with ai.using(brain=brain):
            got = _plan.plan(question, discs=discs, history=history or [],
                             disciplines=self.DISC)
        return got, brain

    def test_合法JSON_别名映射_被采用(self):
        p, brain = self._plan_with(
            '{"specs": [{"op": "series", "metric": "proximity",'
            ' "disc": "Physics", "span": "recent"}]}')
        assert p["origin"] == "model" and p["note"] == ""
        assert p["specs"] == [{"op": "series", "metric": "proximity_1pct",
                               "disc": "Physics", "span": "recent"}]
        # 外发面零台账值（提示面只有名字；出网前统一过盾）
        for t in brain.briefs[0].egress_texts():
            assert not raw_digits(t), f"外发含数字原值：{t[:80]!r}"

    def test_上文解指代(self):
        p, _ = self._plan_with(
            '{"specs": [{"op": "series", "metric": "papers",'
            ' "disc": "Physics", "span": "recent"}]}',
            question="它最近怎么样", discs=(),
            history=[{"who": "me", "text": "物理学的论文数是多少"}])
        assert p["origin"] == "model" and p["specs"][0]["disc"] == "Physics"

    def test_坏JSON_回退规则(self):
        p, _ = self._plan_with("我觉得应该查一下物理。")
        assert p["origin"] == "rule" and p["specs"] == [] and p["note"] == "bad_json"

    def test_越权键_整份回退(self):
        p, _ = self._plan_with(
            '{"specs": [{"op": "series", "metric": "proximity",'
            ' "disc": "Physics", "ylim": "auto"}]}')
        assert p["origin"] == "rule" and p["specs"] == []

    def test_未知op_整份回退(self):
        p, _ = self._plan_with('{"specs": [{"op": "drop_table"}]}')
        assert p["origin"] == "rule" and p["specs"] == []

    def test_带数字_整份回退(self):
        p, _ = self._plan_with(
            '{"specs": [{"op": "series", "metric": "proximity",'
            ' "disc": "Physics", "span": "202609"}]}')
        assert p["origin"] == "rule" and p["note"] == "shield_reject"

    def test_空计划_回退规则(self):
        p, _ = self._plan_with('{"specs": []}')
        assert p["origin"] == "rule" and p["specs"] == []

    def test_非法学科项被丢弃(self):
        p, _ = self._plan_with(
            '{"specs": [{"op": "series", "metric": "proximity", "disc": "NoSuchDisc"},'
            ' {"op": "series", "metric": "papers", "disc": "Physics"}]}')
        assert p["origin"] == "model"
        assert [s["disc"] for s in p["specs"]] == ["Physics"]

    def test_规则有规格时模型不参与(self):
        from ai import _plan
        brain = ScriptedBrain([Turn(text='{"specs": [{"op": "events", "disc": "Physics"}]}')])
        with ai.using(brain=brain):
            p = _plan.plan("化学的接近度", discs=["Chemistry"], disciplines=self.DISC)
        assert p["origin"] == "rule" and brain.briefs == [], "规则已覆盖时不该外发"

    def test_规则部署不触发模型(self):
        from ai import _plan
        p = _plan.plan("最近有什么变化", disciplines=self.DISC)
        assert p["origin"] == "rule" and p["note"] == ""

    def test_经qa全链_规划轮接写作轮(self, tmp_path, monkeypatch):
        """有台账视图时：规则为空 → 规划轮问模型（解指代）→ 台账段进证据 → 写作轮照常。"""
        root = _seed_ledger(tmp_path, monkeypatch)
        brain = ScriptedBrain([
            Turn(text='{"specs": [{"op": "series", "metric": "proximity",'
                      ' "disc": "Chemistry", "span": "recent"}]}'),
            lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
        ans = qa(root, question="它最近怎么样", brain=brain,
                 history=[{"who": "me", "text": "化学的接近度是多少"}])
        assert ans.mode == "model"
        assert "台账《接近度》表" in ans.text, "模型规划的台账段应进证据"
        rec = records(root)[0]
        assert rec["plan"]["origin"] == "model"
        assert rec["plan"]["specs"][0]["metric"] == "proximity_1pct"


# ============================================================ 票 04：例子库 / 金标 / 留痕
class Test例子库与金标:
    def test_例子库零数字且白名单(self):
        from ai import _plan
        lib = _plan.load_examples()
        assert len(lib) >= 3
        for e in lib:
            assert not raw_digits(json.dumps(e["specs"], ensure_ascii=False)), e["q"]
            for s in e["specs"]:
                assert s["op"] in ("series", "events", "overall_rank")
                if "metric" in s:
                    assert s["metric"] in _plan._ALIAS, s

    def test_检索_相关问句在前(self):
        from ai import _plan
        got = _plan.retrieve_examples("化学的接近度最近怎么变", k=2)
        assert any("接近度" in e["q"] for e in got)

    def test_金标全过(self):
        """规则规划 × qa_gold.json 逐例对照（同源工具：tools/verify_qa_plan.py）。"""
        from conftest import REPO
        from ai import _plan
        cases = json.loads((REPO / "tools" / "qa_gold.json").read_text(encoding="utf-8"))
        bad = [(c["q"], got) for c in cases
               for got in [_plan.rule_specs(c["q"], c.get("discs") or ())]
               if got != c["expect"]]
        assert not bad, bad


class Test规划留痕:
    def test_记录带规划摘要(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        qa(root, question="化学的接近度最近几期怎么变的")
        rec = records(root)[0]
        assert rec["plan"]["origin"] == "rule"
        assert rec["plan"]["specs"][0]["metric"] == "proximity_1pct"

    def test_无台账_记录不带plan字段(self, tmp_path):
        seed_period(tmp_path)
        qa(tmp_path, question="顶尖论文")
        assert "plan" not in records(tmp_path)[0]


# ============================================================ 票 05：P0-1 期次目标查询
def test_点名期次_规划出单值at():
    """问句点名某一期 → 规则面出 at 单值（不铺整条序列）。"""
    from ai import _plan
    p = _plan.plan("202605 那一期的化学接近度是多少", discs=["Chemistry"], period="202605")
    assert p["specs"] == [{"op": "at", "metric": "proximity_1pct",
                           "disc": "Chemistry", "period": "202605"}]


def test_没点名期次_序列规格逐字不变():
    from ai import _plan
    p = _plan.plan("化学的接近度", discs=["Chemistry"])
    assert p["specs"] == [{"op": "series", "metric": "proximity_1pct",
                           "disc": "Chemistry", "span": "recent"}]


def test_模型面_at_不带期次_系统补(tmp_path, monkeypatch):
    """模型面 op 白名单含 at；期次由系统补（模型不写期次——零数字面）。"""
    root = _seed_ledger(tmp_path, monkeypatch)
    brain = ScriptedBrain([
        Turn(text='{"specs": [{"op": "at", "metric": "proximity", "disc": "Chemistry"}]}'),
        lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    ans = qa(root, question="它那一期呢", brain=brain,
             history=[{"who": "me", "text": "化学的接近度是多少"}])
    assert ans.mode == "model"
    assert "单期值" in ans.text and "202607" in ans.text, "at 段应进证据（期次由系统补成本轮）"
    rec = records(root)[0]
    assert rec["plan"]["specs"][0]["op"] == "at"


def test_台账问答_点名往期_单值答对(tmp_path, monkeypatch):
    """P0-1（rick 实机 T4 根子）：点名往期 → 单值 at 证据，值到格。"""
    root = _seed_ledger(tmp_path, monkeypatch)
    ans = qa(root, question="202605 那一期的化学接近度是多少")
    assert "618.42%" in ans.text and "单期值" in ans.text
    assert any(s.pointer == "台账#接近度/化学/202605" for s in ans.sources)


def test_任务首行明示指向期次(tmp_path, monkeypatch):
    """问句点名期次 → 任务里明示（写手不再自己解「5月」；数字以掩码形态进任务）。"""
    root = _seed_ledger(tmp_path, monkeypatch)
    brain = ScriptedBrain([
        lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    ans = qa(root, question="202605 那一期的化学接近度", brain=brain)
    assert ans.mode == "model"
    assert "本次问题指向期次" in brain.briefs[0].task
    assert "已解析" in brain.briefs[0].task


# ============================================================ 票 12：阶段进度流（进度回调）
def test_进度回调_模型轮有规则轮无(tmp_path, monkeypatch):
    """`ai.using(progress=…)`：模型真被调用才发 `model:*`；规则轮不发（不演）。"""
    root = _seed_ledger(tmp_path, monkeypatch)
    seen = []
    brain = ScriptedBrain([
        Turn(text='{"specs": [{"op": "series", "metric": "proximity",'
                  ' "disc": "Chemistry", "span": "recent"}]}'),
        lambda b: Turn(text=b.task + "\n\n" + "\n\n".join(b.evidence))])
    with ai.using(data_root=root, brain=brain, progress=seen.append):
        ai.run("qa", "202607",
               payload={"question": "它最近怎么样", "history": []},
               actor="admin")
    assert "model:qa-plan" in seen and "model:qa" in seen, seen

    seen.clear()
    with ai.using(data_root=root, progress=seen.append):
        ai.run("qa", "202607", payload={"question": "化学的接近度", "history": []},
               actor="admin")
    assert not any(str(s).startswith("model:") for s in seen), seen


# ============================================================ 原生工具环（2026-10-28 fc 定稿）
def _cite_last_evidence(b):
    """写作轮替身：引用工具结果（最后一段证据）里的全部标记——工具结果是 fact，不算越题。"""
    marks = re.findall(r"\[\[\d+\]\]", b.evidence[-1] if b.evidence else "")
    assert marks, "工具结果里应有占位标记（执行器已注册编号）"
    return Turn(text="化学的接近度：" + "、".join(marks) + "。")


def _cite_static(b):
    """写作轮替身：只引静态证据段（不引工具结果）。"""
    for seg in b.evidence:
        m = re.search(r"\[\[\d+\]\]", seg)
        if m:
            return Turn(text=f"答 {m.group(0)}。")
    return Turn(text="无法依据本期数据回答。")


class Test原生工具环:
    """qa 写作轮原生 function calling：模型只选（工具名+参数）不造；
    值只从引擎一条缝进来；出网零数字由构造保证；每次能力调用一条留痕。

    问句用规则规划器覆盖得到的（「化学的接近度…」）——规划轮不碰替身，
    ScriptedBrain 的第一拍留给写作轮的工具调用。
    """

    def _qa_tool(self, root, calls_then_answer, question="化学的接近度最近几期怎么变的",
                 history=None):
        brain = ScriptedBrain(calls_then_answer)
        ans = qa(root, question=question, brain=brain, history=history)
        return ans, brain

    def test_有台账视图_挂五件工具_schema零数字(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        # 替身必须引用本期事实（qa 是自由作答型：只复述问句＝越题，会回落规则版）。
        ans, brain = self._qa_tool(root, [_cite_static])
        assert ans.mode == "model"
        tools = brain.briefs[0].tools
        assert tools, "有台账视图就要挂工具"
        names = [t["function"]["name"] for t in tools]
        assert names == ["query_series", "query_at", "query_events", "query_overall_rank",
                         "query_compare"]
        blob = json.dumps(tools, ensure_ascii=False)
        assert not raw_digits(blob), f"工具 schema 必须零数字：{blob[:120]!r}"
        metric_enum = tools[0]["function"]["parameters"]["properties"]["metric"]["enum"]
        from ai import _plan
        assert set(metric_enum) == {a for a, _c, _cn in _plan.MODEL_METRICS}
        assert "Chemistry" in tools[0]["function"]["parameters"]["properties"]["disc"]["enum"]
        # 第五件：横比（谁高谁低交给引擎排序——模型看不见真值，比不了）
        cmp_fn = tools[-1]["function"]
        assert cmp_fn["name"] == "query_compare" and cmp_fn["parameters"]["required"] == ["metric"]
        assert not raw_digits(cmp_fn["description"]), "话术里不许出现数字"
        for t in brain.briefs[0].egress_texts():
            assert not raw_digits(t), f"外发含数字原值：{t[:80]!r}"

    def test_无台账视图_不挂工具_现状不变(self, tmp_path):
        seed_period(tmp_path)
        ans, brain = self._qa_tool(tmp_path, [_cite_static], question="顶尖论文")
        assert brain.briefs[0].tools == (), "视图拿不到就不挂工具"
        assert ans.mode == "model" and ans.receipts == ()

    def test_合法查询_工具环全链_数字到格_回执两头(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_series",
                "arguments": {"metric": "proximity", "disc": "Chemistry"}}
        ans, brain = self._qa_tool(root, [Turn(calls=(call,)), _cite_last_evidence])
        assert ans.mode == "model" and "676.06" in ans.text
        # 数字注册进同一 mapping：used_by 指到台账格
        src = [s for s in ans.sources if s.value == "676.06"]
        assert src and src[0].kind == "ledger_cell"
        assert src[0].pointer == "台账#接近度/化学/202607"
        # 回执：界面面有摘要（零数字），记录面只剩 digest
        assert len(ans.receipts) == 1
        r = ans.receipts[0]
        assert (r.tool, r.label, r.ok, r.refused) == ("query_series", "查台账", True, False)
        assert r.summary == "查 化学·接近度" and not raw_digits(r.summary)
        assert r.args_digest
        rec = records(root)[0]
        assert rec["mode"] == "model" and rec["fallback"] is None
        tools_rec = rec["tools"]
        assert len(tools_rec) == 1 and tools_rec[0]["tool"] == "query_series"
        assert "summary" not in tools_rec[0] and tools_rec[0]["summary_digest"]
        # 工具结果文本必须是占位面（外发零数字）
        assert not raw_digits(brain.briefs[1].evidence[-1])
        assert "618.42" not in "\n".join(brain.briefs[1].evidence), "原值不外发"

    def test_单期at_系统补当期(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_at",
                "arguments": {"metric": "proximity", "disc": "Chemistry"}}
        ans, brain = self._qa_tool(root, [Turn(calls=(call,)), _cite_last_evidence])
        assert ans.mode == "model"
        assert "单期值" in brain.briefs[1].evidence[-1], "at 段进证据（期次由系统补）"
        assert any(s.pointer == "台账#接近度/化学/202607" for s in ans.sources)

    def test_越权指标_拒不回落_模型可继续作答(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_series",
                "arguments": {"metric": "drop_table", "disc": "Chemistry"}}
        ans, brain = self._qa_tool(root, [Turn(calls=(call,)), _cite_static])
        assert ans.mode == "model", "拒答不是回落：模型收到拒答句后仍可作答"
        assert "该查询不在可查范围" in brain.briefs[1].evidence[-1]
        assert not raw_digits(brain.briefs[1].evidence[-1]), "拒答句零数字"
        r = ans.receipts[0]
        assert r.ok is False and r.refused is True
        rec = records(root)[0]
        assert rec["fallback"] is None and rec["tools"][0]["refused"] is True

    def test_越权学科_同样拒(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_series",
                "arguments": {"metric": "papers", "disc": "NoSuchDisc"}}
        ans, _ = self._qa_tool(root, [Turn(calls=(call,)), _cite_static])
        assert ans.mode == "model"
        assert ans.receipts[0].refused is True

    def test_未知工具名_拒(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "drop_table", "arguments": {}}
        ans, _ = self._qa_tool(root, [Turn(calls=(call,)), _cite_static])
        assert ans.receipts[0].refused is True

    def test_横比_一期跨学科_引擎排序后进证据(self, tmp_path, monkeypatch):
        """比较类问题的正解：谁高谁低由引擎算（按「好」的方向排），模型只读顺序——
        它看不见真值，占位编号也**不是**大小，比不出来。"""
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_compare", "arguments": {"metric": "proximity"}}   # 不填＝全部学科
        ans, brain = self._qa_tool(root, [Turn(calls=(call,)), _cite_last_evidence])
        assert ans.mode == "model"
        seg = brain.briefs[1].evidence[-1]
        assert "横向比较" in seg and "从好到差排列" in seg, seg
        assert not raw_digits(seg), "结果必须是占位面"
        r = ans.receipts[0]
        assert (r.tool, r.ok, r.refused) == ("query_compare", True, False)
        assert r.summary == "查 接近度·横比"

    def test_横比_学科名越权_拒(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_compare",
                "arguments": {"metric": "proximity", "discs": ["NoSuch"]}}
        ans, brain = self._qa_tool(root, [Turn(calls=(call,)), _cite_static])
        assert ans.mode == "model", "拒答不是回落"
        assert ans.receipts[0].refused is True
        assert "不在可查范围" in brain.briefs[1].evidence[-1]

    def test_横比_该期没有这个学科的数据_拒(self, tmp_path, monkeypatch):
        """白名单过了、引擎取不到（数学在这张接近度表里没值）→ 也走拒，不回落。"""
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_compare",
                "arguments": {"metric": "proximity", "discs": ["Mathematics"]}}
        ans, brain = self._qa_tool(root, [Turn(calls=(call,)), _cite_static])
        assert ans.mode == "model"
        assert ans.receipts[0].refused is True
        assert not raw_digits(brain.briefs[1].evidence[-1])

    def test_同规格去重_复用已注册文本不再注册(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_series",
                "arguments": {"metric": "proximity", "disc": "Chemistry"}}
        ans, brain = self._qa_tool(root, [Turn(calls=(call, call)), _cite_last_evidence])
        assert ans.mode == "model"
        b2 = brain.briefs[1]
        assert b2.evidence[-2] == b2.evidence[-1], "同规格第二次返回同一占位文本"
        # 去重＝第二次没长出新编号：总数 == 原有证据的编号 + 工具结果那一段的编号
        # （若重新注册，这里会多出一组新号——memo 命中必须原样复用已注册文本）。
        marks_two = re.findall(r"\[\[\d+\]\]", b2.evidence[-1])
        base = "\n".join(b2.evidence[:-2])
        marks_all = re.findall(r"\[\[\d+\]\]", "\n".join(b2.evidence))
        assert len(set(marks_all)) == len(set(re.findall(r"\[\[\d+\]\]", base))) + len(
            set(marks_two)), "去重不再注册新编号"
        assert len(ans.receipts) == 2 and all(r.ok for r in ans.receipts)

    def test_末轮仍calls_回落规则版(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_series",
                "arguments": {"metric": "proximity", "disc": "Chemistry"}}
        # 占满全部轮次还在要工具（turns 要比 max_steps 多一拍，否则取不到 turns 会
        # 先撞上空回复）——这才叫「连续请求工具未作答」。
        ans, _ = self._qa_tool(root, [Turn(calls=(call,)) for _ in range(6)])
        assert ans.mode == "failed" and "没有作答" in ans.text
        assert "连续请求工具未作答" in ans.notice
        assert records(root)[0]["fallback"] == "calls_unsupported"

    def test_规则部署_工具挂了但物理不执行(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        ans = qa(root, question="化学的接近度")     # 不注 brain → RuleBrain
        assert ans.mode == "rule" and ans.receipts == ()
        assert "台账《接近度》表" in ans.text, "规则版照旧（台账段走规划器）"

    def test_越题判定_只引工具结果不算越题(self, tmp_path, monkeypatch):
        root = _seed_ledger(tmp_path, monkeypatch)
        call = {"name": "query_series",
                "arguments": {"metric": "proximity", "disc": "Chemistry"}}

        def only_tool(b):
            k = re.findall(r"\[\[\d+\]\]", b.evidence[-1])[0]
            return Turn(text=f"答 {k}。")

        ans, _ = self._qa_tool(root, [Turn(calls=(call,)), only_tool])
        assert ans.mode == "model", "工具结果是 fact：只引它不算越题"
        assert records(root)[0]["fallback"] is None
