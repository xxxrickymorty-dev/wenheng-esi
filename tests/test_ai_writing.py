# -*- coding: utf-8 -*-
"""写入门禁（`ai/_writing.py`）：两个位、一条判据（开关 × 模型可达）。

并钉住消费点（flexible 出稿模式 / server 按钮状态）用的是**同一条**判据——
这正是把三份重复判定收成一个 interface 要防的事。
"""
import pytest

import ai
from ai import _writing
from ai._brain import RuleBrain

from _ai_helpers import ScriptedBrain


class Test_门禁:
    def test_开关三态_默认关(self, monkeypatch):
        monkeypatch.delenv("WENHENG_FLEX_WRITE", raising=False)
        assert _writing.enabled("write") is False
        assert _writing.enabled("write", default=True) is True
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "on")
        assert _writing.enabled("write") is True
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "off")
        assert _writing.enabled("write") is False
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "yes")
        assert _writing.enabled("write") is True

    def test_两个位各认自己的开关(self, monkeypatch):
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "1")
        monkeypatch.delenv("WENHENG_FLEX_POLISH", raising=False)
        assert _writing.enabled("write") is True
        assert _writing.enabled("polish") is False

    def test_模型可达看配置(self, monkeypatch):
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "1")
        with ai.using(brain=RuleBrain()):
            st = _writing.writing_state("write")
        assert st.model is False and st.available is False        # 默认规则版＝不可用
        with ai.using(brain=ScriptedBrain([])):
            st = _writing.writing_state("write")
        assert st.model is True and st.available is True

    def test_开关关时available恒关(self, monkeypatch):
        monkeypatch.delenv("WENHENG_FLEX_POLISH", raising=False)
        with ai.using(brain=ScriptedBrain([])):
            st = _writing.writing_state("polish")
        assert st.enabled is False and st.model is True and st.available is False

    def test_HTTP形状与契约(self, monkeypatch):
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "1")
        with ai.using(brain=ScriptedBrain([])):
            assert _writing.writing_state("write").as_dict() == {"enabled": True,
                                                                 "available": True}

    def test_未知位报错(self):
        with pytest.raises(ValueError):
            _writing.writing_state("nope")

    def test_消费点同一判据(self, monkeypatch):
        """flexible 出稿模式与 server 按钮状态必须同开同关。"""
        import server.app as app_mod
        from flexible import report as flex_report
        monkeypatch.setenv("WENHENG_FLEX_WRITE", "1")
        with ai.using(brain=ScriptedBrain([])):
            assert flex_report._resolve_write_mode(None, True) == "write"
            assert app_mod._flex_write_state() == {"enabled": True, "available": True}
        with ai.using(brain=RuleBrain()):
            assert flex_report._resolve_write_mode(None, True) == "off"
            assert app_mod._flex_write_state() == {"enabled": True, "available": False}
