# -*- coding: utf-8 -*-
"""运行期模型清单（2026-10-29）：落盘、掩码、当前项生效、写口校验。

口径：
- key **只落 out/**，读口只给掩码；
- 清单没配齐（地址/型号/key 缺一）→ 不算可用，回落 `.env` → 再回落规则版；
- 切当前模型＝下一次调用就生效（`cloud_config` 现读，不重建单例）。
"""
from __future__ import annotations

import json

import pytest

import ai
from ai import _config, _models

#: conftest 的 `_isolate_ai_env` 会把 `active_credentials` 蒙成 None（开发机清单隐身）；
#: 本模块就是测清单本身的，所以先留一份真函数，需要时在测试里装回去。
_REAL_ACTIVE = _models.active_credentials


def _seed(root, **kw):
    row = {"id": "", "label": "测试模型", "base_url": "https://example.test/v1",
           "model": "Test/Model-1", "key": "sk-abcdef123456", "note": ""}
    row.update(kw)
    with ai.using(data_root=root):
        return _models.upsert(row, actor="admin")


# ============================================================ 落盘与掩码
def test_保存后读口只给掩码_原文在文件里(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        got = _models.public()
    dump = json.dumps(got, ensure_ascii=False)
    assert "sk-abcdef123456" not in dump, "读口不得回显 key 原文"
    row = next(r for r in got["models"] if r["model"] == "Test/Model-1")
    assert row["key_hint"].endswith("3456") and row["ready"] is True
    raw = json.loads((tmp_path / "_ai" / "models.json").read_text(encoding="utf-8"))
    assert raw["models"][0]["key"] == "sk-abcdef123456", "key 落在 out/ 里（不入库）"


def test_第一条带key的模型自动成为当前(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        assert _models.public()["active"] == "test-model-1"


def test_key留空沿用旧key(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.upsert({"id": "test-model-1", "label": "改了名字",
                        "base_url": "https://example.test/v1",
                        "model": "Test/Model-1", "key": ""}, actor="admin")
        row = _models.read()["models"][0]
    assert row["label"] == "改了名字" and row["key"] == "sk-abcdef123456"


# ============================================================ 可用性
def test_没配齐就不可用_回落部署配置(tmp_path):
    _seed(tmp_path, key="")
    with ai.using(data_root=tmp_path):
        assert _models.active_credentials() is None
        cfg = _config.cloud_config()
    assert cfg.get("source") != "清单", "没 key 不得被当成可用模型"


def test_切当前模型_下一次调用即生效(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path, key="")
    with ai.using(data_root=tmp_path):
        _models.upsert({"id": "second", "label": "第二个",
                        "base_url": "https://example.test/v1",
                        "model": "Test/Model-2", "key": "sk-second-9876"}, actor="admin")
        _models.set_active("second", actor="admin")
        cred = _models.active_credentials()
        cfg = _config.cloud_config()
    assert cred["model"] == "Test/Model-2"
    assert cfg["backend"] == "openai" and cfg["model"] == "Test/Model-2"


def test_演示锁仍然一票否决(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path)
    monkeypatch.setenv("WENHENG_AI_PROFILE", "demo")
    with ai.using(data_root=tmp_path):
        cfg = _config.cloud_config()
        brain = _config.build_brain()
    assert cfg["profile"] == "demo" and getattr(brain, "is_rule", False), "演示站不出网"


# ============================================================ 写口校验
def test_地址不合法被拒(tmp_path):
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            _models.upsert({"model": "X", "base_url": "example.test"}, actor="admin")
        with pytest.raises(ValueError):
            _models.upsert({"model": "", "base_url": "https://a.test"}, actor="admin")


def test_地址尾部补全到v1(tmp_path):
    with ai.using(data_root=tmp_path):
        row = _models.upsert({"model": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1/chat/completions/"}, actor="admin")
    assert row["base_url"] == "https://a.test/v1"


def test_切到不存在或没配齐的模型报错(tmp_path):
    _seed(tmp_path, key="")
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            _models.set_active("nope", actor="admin")
        with pytest.raises(ValueError):
            _models.set_active("test-model-1", actor="admin")   # 没 key
        _models.remove("test-model-1", actor="admin")
        with pytest.raises(ValueError):
            _models.remove("test-model-1", actor="admin")        # 已经删了


def test_删掉当前项_回到部署配置(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.remove("test-model-1", actor="admin")
        assert _models.public()["active"] == ""
        assert _models.active_credentials() is None


def test_坏文件按空清单处理不炸(tmp_path):
    p = tmp_path / "_ai" / "models.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ 这不是 JSON", encoding="utf-8")
    with ai.using(data_root=tmp_path):
        got = _models.public()
        assert got["active"] == "" and got["models"] == [] or all(
            not m["active"] for m in got["models"])


def test_探活没key直接说清楚(tmp_path):
    out = _models.probe(base_url="https://example.test/v1", key="", model="X")
    assert out["ok"] is False and "key" in out["msg"]
