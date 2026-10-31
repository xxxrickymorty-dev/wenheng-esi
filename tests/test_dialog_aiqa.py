# -*- coding: utf-8 -*-
"""对话层 · 问数并入（2026-10-31）：对话里命中问数句式 → 直调问数引擎，**模型不碰数据路径**。

钉四件事：
  ① 问数句式（指标词）且无期次可依 → kind="qa"，直调 `aiqa_engine`——回答里的数字
     与引擎执行结果逐字一致，注入的 brain（_Bomb）一次都不该被调用（确定性，不走模型）；
  ② 他校简报（compare）不被抢走：比较类问句仍归 compare，指标词仍不归简报；
  ③ aiqa.sqlite 缺席 → 讲人话空态折进对话流（不抛 FileNotFoundError、不露技术术语）；
  ④ 有底表时：图型建议随 data["qa"] 折出、qa_log 留痕落一行；带槽位期次的查数据轮
     照旧走既有 query 路由（服务器按意图调 qa 能力的钉子不动）。

不依赖真数据——问数库用例自建最小 sqlite（dim 三表 + facts 两行），hermetic、离线可跑。
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                                   # noqa: E402

import ai                                                       # noqa: E402
from ai import _dialog                                          # noqa: E402
from _guard_registry import skip_unless, tmp_near_repo          # noqa: E402


class _Bomb:
    """被调用即炸的 brain：证明问数轮没有模型参与。"""

    name = "bomb"
    is_rule = False

    def think(self, brief):                                     # noqa: ARG002
        raise AssertionError("问数轮不该问模型")


def run_dialog(text, *, root, slot="", history=None, **ov):
    with ai.using(data_root=root, brain=_Bomb(), **ov):
        return ai.run("dialog", slot,
                      payload={"text": text, "history": history or []}, actor="admin")


# ---------------------------------------------------------------- 最小问数库
def _make_aiqa_db(data_root: pathlib.Path) -> None:
    """`data_root` 视作 out/ 一层：库按 `aiqa_db.db_path(root.parent)` 落
    `<data_root>/../out/_aidata/aiqa.sqlite`（即 data_root 自己底下的 _aidata）。"""
    from aiqa_db import _DDL

    d = data_root / "_aidata"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "aiqa.sqlite"))
    try:
        con.executescript(_DDL)
        con.executemany(
            "INSERT OR REPLACE INTO dim_discipline (discipline, discipline_cn, ord) "
            "VALUES (?,?,?)", [("Chemistry", "化学", 1)])
        con.executemany(
            "INSERT OR REPLACE INTO dim_metric (metric, metric_cn, better) VALUES (?,?,?)",
            [("proximity_1pct", "ESI前1%接近度", "up")])
        con.executemany(
            "INSERT OR REPLACE INTO dim_period (period, label, ord, filled) VALUES (?,?,?,?)",
            [("202607", "2026年7月", 0, 1), ("202609", "2026年9月", 1, 1)])
        con.executemany(
            "INSERT OR REPLACE INTO facts (discipline, period, metric, source, value) "
            "VALUES (?,?,?,?,?)",
            [("Chemistry", "202607", "proximity_1pct", "", 0.512),
             ("Chemistry", "202609", "proximity_1pct", "", 0.548)])
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def aiqa_root(tmp_path):
    """data_root = tmp_path/"out"（out/ 一层）；库在其下 _aidata/。"""
    _make_aiqa_db(tmp_path / "out")
    return tmp_path / "out"


# ============================================================ ① 路由：问数句式
class TestRoute:
    def test_问数句式_没期次可依_落qa(self):
        assert _dialog.parse("化学的CNCI").kind == "qa"

    def test_弱查词在场_照旧走既有query路由(self):
        assert _dialog.parse("化学的顶尖论文").kind == "query", "「论文」是弱查词，既有路由优先"
        assert _dialog.parse("202607 数学进 1% 了吗").kind == "query"

    def test_出稿月里的指标句_不落给写报告(self):
        assert _dialog.parse("9月出稿的接近度").kind == "qa"

    def test_比较类仍归简报_compare不被抢(self):
        assert _dialog.parse("对比昆明理工大学和海南大学最新一期学科发展").kind == "compare"

    def test_指标问句仍不归简报(self):
        assert _dialog.parse("对比昆明理工大学和海南大学的化学接近度").kind != "compare"

    def test_报告意图_无指标词_照旧写报告(self):
        assert _dialog.parse("帮我做9月份的报告").kind == "report"

    def test_序列问法_不落qa直调(self):
        assert _dialog.parse("化学的接近度最近六期怎么变的").kind == "query"


# ============================================================ ② 直调引擎：数字逐字一致
class TestDirect:
    def test_对话里问接近度_直调引擎出数(self, aiqa_root):
        ans = run_dialog("查一下化学的接近度", root=aiqa_root)
        assert ans.data["kind"] == "qa"
        assert "接近度" in ans.text and "0.548" in ans.text, ans.text
        assert ans.mode == "rule" and ans.backend == "rule", "问数轮是规则拼装，不走模型"

    def test_回答确定性_同一句两次同结果(self, aiqa_root):
        a = run_dialog("查一下化学的接近度", root=aiqa_root)
        b = run_dialog("查一下化学的接近度", root=aiqa_root)
        assert a.text == b.text
        for k in ("chart", "chart_data", "answered"):
            assert a.data["qa"][k] == b.data["qa"][k], k

    def test_图型建议随data折出(self, aiqa_root):
        ans = run_dialog("查一下化学的接近度", root=aiqa_root)
        qa = ans.data["qa"]
        assert qa["chart"]["kind"] == "line", "时间序列 → 折线"
        assert qa["chart_data"]["categories"] == ["202607", "202609"]
        assert qa["chart_data"]["series"][0]["data"] == [0.512, 0.548]
        assert qa["answered"] is True and qa["record_id"] >= 0, "留痕落了行"

    def test_来源逐数字登记_指向问数库(self, aiqa_root):
        ans = run_dialog("查一下化学的接近度", root=aiqa_root)
        assert ans.sources, "回答要带出处"
        for s in ans.sources:
            assert s.pointer.startswith("aiqa/facts/Chemistry/proximity_1pct"), s.pointer

    def test_留痕进qa_log(self, aiqa_root):
        run_dialog("查一下化学的接近度", root=aiqa_root)
        con = sqlite3.connect(str(aiqa_root / "_aidata" / "aiqa.sqlite"))
        try:
            rows = con.execute("SELECT question, chart_kind FROM qa_log").fetchall()
        finally:
            con.close()
        assert rows and rows[-1][0] == "查一下化学的接近度" and rows[-1][1] == "line"

    def test_问数轮有工具回执(self, aiqa_root):
        ans = run_dialog("查一下化学的接近度", root=aiqa_root)
        assert any(r.tool == "aiqa" and r.ok for r in ans.receipts)


# ============================================================ ③ 底表缺席：讲人话空态
class TestAbsent:
    def _run(self, tmp_path):
        if tmp_near_repo(REPO):
            skip_unless("系统 Temp 不可写，pytest 临时根落在仓库内/隔壁",
                        lambda: not tmp_near_repo(REPO))
        return run_dialog("查一下化学的接近度", root=tmp_path)

    def test_底表缺席_空态折进流不抛错(self, tmp_path):
        ans = self._run(tmp_path)
        assert ans.data["kind"] == "qa"
        assert "问数的底表还没生成" in ans.text, ans.text
        assert "下一步" in ans.text, "空态＝一句 + 下一步"
        assert ans.data.get("qa") is None, "没库就没有图块"
        assert ans.data["actions"] == [] and ans.data["run"] is None

    def test_底表缺席_回执如实为假(self, tmp_path):
        ans = self._run(tmp_path)
        assert any(r.tool == "aiqa" and not r.ok for r in ans.receipts)


# ============================================================ ④ 既有路由不被破坏
class TestPinned:
    def test_带槽位期次_仍走既有query路由(self, tmp_path):
        ans = run_dialog("查一下化学的接近度", root=tmp_path, slot="202607")
        assert ans.data["kind"] == "query"
        assert ans.data["verdict"] == "" and ans.data["inventory"] is None
        assert ans.data["run"] is None and ans.data["actions"] == []

    def test_带句中期次的弱查_仍走query不触发盘点(self, tmp_path):
        seen = []

        def pick(period):                                    # noqa: ARG001
            seen.append(period)
            return None

        with ai.using(data_root=tmp_path, brain=_Bomb(), inventory=pick):
            ans = ai.run("dialog", "", payload={"text": "202607 数学进 1% 了吗"},
                         actor="admin")
        assert ans.data["kind"] == "query" and seen == []


# ============================================================ ⑤ 服务器折进响应面
class _ReqJson:
    def __init__(self, user, body=None):
        self.session = {"user": user}
        self._body = body or {}

    async def json(self):
        return self._body


def _api_call(user, body):
    import asyncio

    from server import app as app_module
    return asyncio.run(app_module.api_dialog_turn(_ReqJson(user, body)))


_QA_DATA = {"case": "no_period", "period": "", "intent": "", "act": "", "kind": "qa",
            "verdict": "", "actions": [], "inventory": None, "run": None,
            "qa": {"chart": {"kind": "line", "x": "period", "y": [], "title": "化学接近度"},
                   "chart_data": {"kind": "line", "title": "化学接近度",
                                  "categories": ["202609"],
                                  "series": [{"name": "化学", "data": [0.548]}]},
                   "record_id": 7, "elapsed_ms": 3, "answered": True}}


class TestServerFold:
    @pytest.fixture(autouse=True)
    def _no_real_ledger(self, monkeypatch):
        import taskview
        monkeypatch.setattr(taskview, "known_periods", lambda: [])

    def _call(self, monkeypatch):
        from ai import _types
        fake = _types.Answer(
            mode="rule", backend="rule", text="化学的接近度 0.548。",
            rule_text="化学的接近度 0.548。",
            sources=(_types.Source(index=1, kind="fact",
                                   pointer="aiqa/facts/Chemistry/proximity_1pct",
                                   label="台账事实（问数库）", detail="d", value="0.548"),),
            shield=_types.Shield(1, 1), data=_QA_DATA)

        def fake_run(cap, period, *, payload=None, actor=None):   # noqa: ARG001
            assert cap == "dialog", "问数轮服务器不再另调 qa 能力"
            return fake

        monkeypatch.setattr("ai.run", fake_run)
        from server import config
        return _api_call(config.ADMIN_USER, {"text": "查一下化学的接近度"})

    def test_qa轮_回答折进answer_图块折进qa(self, monkeypatch):
        r = self._call(monkeypatch)
        assert r["kind"] == "qa"
        assert r["text"] == "", "正文由 answer 块出，顶层不整段重显"
        assert r["answer"]["text"].startswith("化学的接近度")
        assert r["answer"]["sources"][0]["pointer"].startswith("aiqa/facts")
        assert r["answer"]["shield"] == {"checked": 1, "passed": 1}
        assert r["qa"]["chart"]["kind"] == "line" and r["qa"]["record_id"] == 7

    def test_无qa块的轮次_响应面照旧(self, monkeypatch):
        from ai import _types
        fake = _types.Answer(mode="rule", backend="rule", text="反问。",
                             data={"case": "no_period", "period": "", "intent": "",
                                   "act": "", "kind": "query", "verdict": "",
                                   "actions": [], "inventory": None, "run": None})
        monkeypatch.setattr(
            "ai.run", lambda cap, period, *, payload=None, actor=None: fake)   # noqa: ARG005
        from server import config
        r = _api_call(config.ADMIN_USER, {"text": "查一下台账"})
        assert r["kind"] == "query" and r["answer"] is None and r["qa"] is None
        assert r["text"] == "反问。"
