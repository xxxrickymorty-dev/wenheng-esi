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


class Test权限门:
    def test_analyze用require_admin(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_analyze")[1].split("@app.")[0]
        assert "require_admin" in block

    def test_ledger_sheets用require_admin且拒绝guest(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        block = src.split("async def api_ledger_sheets")[1].split("@app.")[0]
        assert "require_admin" in block
        assert asyncio.run(app_module.api_ledger_sheets(_Req(config.GUEST_USER))).status_code == 403

    def test_analyze路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/analyze")' in src

    def test_ledger_sheets路由存在(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/ledger/sheets")' in src
