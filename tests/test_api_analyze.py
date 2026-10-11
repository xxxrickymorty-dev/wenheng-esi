# -*- coding: utf-8 -*-
"""Batch 6 测试：ledger/sheets + analyze（契约 §2.2 #9 #10）。"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _guard_registry import skip_unless                         # noqa: E402
import sentences                                              # noqa: E402
import local_llm                                              # noqa: E402
from server.app import resolve_period_dir                     # noqa: E402
from server import app as app_module, config                  # noqa: E402


class _Req:
    def __init__(self, user):
        self.session = {"user": user}


class TestSentences组装:
    def test_build返回dict_of_texts(self, repo):
        outs = sorted((repo / "out").glob("20*/overview_facts.json")) if (repo / "out").exists() else []
        if not outs:
            skip_unless("out/ 无 overview_facts.json", lambda: bool(list((repo / "out").glob("20*/overview_facts.json"))))
        facts = json.loads(outs[-1].read_text(encoding="utf-8"))
        meta_file = outs[-1].parent / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        P = meta.get("period_current", "202607")
        Q = meta.get("period_prev", "202605")
        texts = sentences.build(facts, P, Q)
        assert isinstance(texts, dict)
        assert len(texts) > 0
        for v in texts.values():
            assert isinstance(v, str)

    def test_build不依赖LLM(self):
        """sentences.build 是纯函数组装，不调 Ollama/网络。"""
        import inspect
        src = inspect.getsource(sentences.build)
        assert "urllib" not in src
        assert "requests" not in src
        assert "ollama" not in src.lower()


class Test数字防护盾:
    def test_protect把数字换成占位符(self):
        text = "我校共有5个学科进入ESI前1%，接近度为33.87%。"
        protected, mapping = local_llm.protect(text)
        assert "[[1]]" in protected
        assert "[[2]]" in protected
        assert "[[3]]" in protected
        assert "5" not in protected
        assert "33.87" not in protected
        assert len(mapping) == 3  # "5"、"1"（前1%）、"33.87" 三个数字

    def test_restore还原(self):
        text = "我校共有5个学科进入ESI前1%。"
        protected, mapping = local_llm.protect(text)
        restored = local_llm.restore(protected, mapping)
        assert restored == text

    def test_validate通过(self):
        text = "共有5个学科。"
        protected, mapping = local_llm.protect(text)
        ok, detail = local_llm.validate(protected, mapping)
        assert ok is True

    def test_validate捕获篡改(self):
        text = "共有5个学科。"
        protected, mapping = local_llm.protect(text)
        tampered = protected.replace("[[1]]", "99")
        ok, detail = local_llm.validate(tampered, mapping)
        assert ok is False
        assert detail["missing"] or detail["stray"]


class TestQa薄适配:
    """D2（2026-09-29）：/api/analyze 变薄——Answer 字段面原样透出，故障映射 404。"""

    class _ReqJson:
        def __init__(self, user, body):
            self.session = {"user": user}
            self._body = body

        async def json(self):
            return self._body

    def test_Answer原样透出且参数正确(self, monkeypatch, tmp_path):
        from ai import _types
        fake = _types.Answer(
            mode="rule", backend="rule", text="本期…", rule_text="本期…",
            sources=(_types.Source(index=1, kind="product",
                                   pointer="overview_facts.json#rank_intl_now",
                                   value="995"),),
            shield=_types.Shield(1, 1), record_id="rec-1")
        seen = {}

        def fake_run(cap, period, *, payload=None, actor=None):
            seen.update(cap=cap, period=period, payload=payload, actor=actor)
            return fake

        monkeypatch.setattr("ai.run", fake_run)
        monkeypatch.setattr(app_module, "resolve_period_dir",
                            lambda p: tmp_path / p if p == "202607" else None)
        r = asyncio.run(app_module.api_analyze(
            self._ReqJson(config.ADMIN_USER, {"period": "202607", "question": "顶尖论文"})))
        assert r["mode"] == "rule" and r["text"] == "本期…"
        assert r["sources"][0]["index"] == 1 and r["shield"]["checked"] == 1
        assert seen == {"cap": "qa", "period": "202607",
                        "payload": {"question": "顶尖论文"}, "actor": "admin"}, \
            "路由只做转译：能力/期次/问句/角色原样交给 ai.run（用户名经 config.role_of）"

    def test_无产物映射404(self, monkeypatch, tmp_path):
        from ai import _types
        fake = _types.Answer(mode="unavailable", backend="rule",
                             notice="该期数据暂不可用，无法作答。")
        monkeypatch.setattr("ai.run", lambda *a, **k: fake)
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: tmp_path / p)
        r = asyncio.run(app_module.api_analyze(
            self._ReqJson(config.ADMIN_USER, {"period": "202607", "question": "x"})))
        assert r.status_code == 404

    def test_关闭映射409(self, monkeypatch, tmp_path):
        from ai import _types
        fake = _types.Answer(mode="closed", backend="rule", notice="此功能已由管理员关闭。")
        monkeypatch.setattr("ai.run", lambda *a, **k: fake)
        monkeypatch.setattr(app_module, "resolve_period_dir", lambda p: tmp_path / p)
        r = asyncio.run(app_module.api_analyze(
            self._ReqJson(config.ADMIN_USER, {"period": "202607", "question": "x"})))
        assert r.status_code == 409


class Test权限门:
    def test_analyze放行操作员_匿名401(self):
        """2026-10-11：问文衡是只读查询，操作员放行（404＝门放行后未找到期次）。"""
        class _ReqJson:
            def __init__(self, user):
                self.session = {"user": user} if user else {}

            async def json(self):
                return {"period": "199901", "question": "x"}

        assert asyncio.run(app_module.api_analyze(
            _ReqJson(config.OPERATOR_USER))).status_code == 404
        assert asyncio.run(app_module.api_analyze(_ReqJson(None))).status_code == 401

    def test_ledger_sheets用require_admin且拒绝操作员(self):
        assert asyncio.run(app_module.api_ledger_sheets(
            _Req(config.OPERATOR_USER))).status_code == 403
        assert asyncio.run(app_module.api_ledger_sheets(_Req(None))).status_code == 401

    def test_analyze路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/analyze")' in src

    def test_ledger_sheets路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/ledger/sheets")' in src
