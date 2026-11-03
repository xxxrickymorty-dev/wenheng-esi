# -*- coding: utf-8 -*-
"""运行期模型清单（2026-10-29）：落盘、掩码、当前项生效、写口校验。

口径：
- key **只落 out/**，读口只给掩码；
- 清单没配齐（地址/型号/key 缺一）→ 不算可用，回落 `.env` → 再回落规则版；
- 切当前模型＝下一次调用就生效（`cloud_config` 现读，不重建单例）。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


# ============================================================ headers（票 4，2026-11-03）
def test_headers保存读取round_trip(tmp_path):
    """条目可选 headers：保存什么读回什么（read 原样回）；public 也带给界面（改时预填）。"""
    _seed(tmp_path, headers={"X-Org": "ynu", "X-Trace-Id": "abc-123"})
    with ai.using(data_root=tmp_path):
        row = _models.read()["models"][0]
        assert row["headers"] == {"X-Org": "ynu", "X-Trace-Id": "abc-123"}
        pub = next(r for r in _models.public()["models"] if r["model"] == "Test/Model-1")
        assert pub["headers"] == {"X-Org": "ynu", "X-Trace-Id": "abc-123"}
        assert pub["protocol"] == "openai"


def test_headers没给就不落字段_清空即删(tmp_path):
    with ai.using(data_root=tmp_path):
        row = _models.upsert({"id": "t1", "model": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1"}, actor="admin")
        assert "headers" not in row, "没配 headers＝不出现这个字段"
        _models.upsert({"id": "t1", "model": "X", "key": "k" * 10,
                        "base_url": "https://a.test/v1",
                        "headers": {"X-Org": "ynu"}}, actor="admin")
        row = _models.upsert({"id": "t1", "model": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1"}, actor="admin")
        assert "headers" not in row, "再存一次不带 headers＝清掉（表单删了行就是删了头）"


def test_非法headers拒收(tmp_path):
    with ai.using(data_root=tmp_path):
        for bad in ({"坏 头": "v"},                       # 名字带空格
                    {"X_下划线": "v"},                    # 下划线不在允许集
                    {"X-Ok": ""},                        # 空值
                    {"X-Ok": "   "},                     # 全空白值
                    {f"X-H{i}": "v" for i in range(9)}):  # 超过 8 条
            with pytest.raises(ValueError):
                _models.upsert({"model": "X", "key": "k" * 10,
                                "base_url": "https://a.test/v1", "headers": bad},
                               actor="admin")
        with pytest.raises(ValueError):
            _models.upsert({"model": "X", "key": "k" * 10,
                            "base_url": "https://a.test/v1", "headers": "X-Org=ynu"},
                           actor="admin")                    # headers 要是对象，不是字符串


def test_当前条目的headers传进brain(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path, headers={"X-Org": "ynu"})
    with ai.using(data_root=tmp_path):
        brain = _config.build_brain()
        assert brain._merge_headers()["X-Org"] == "ynu", "清单条目的自定义头要随调用发出"
        assert brain._merge_headers()["Authorization"] == "Bearer sk-abcdef123456"
    # 条目没配 headers：合并结果与从前一致（只有鉴权与内容类型）
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        brain = _config.build_brain()
        assert brain._merge_headers() == {"Authorization": "Bearer sk-abcdef123456",
                                          "Content-Type": "application/json"}


def test_探活透传headers_鉴权头不被覆盖(tmp_path):
    """probe 的 headers＝要真发的那套自定义头；Authorization 由探活自己出（测的就是这把 key）。"""
    seen: dict[str, str] = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.update(dict(self.headers.items()))
            body = json.dumps({"data": [{"id": "X"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):                       # noqa: ARG002
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
        out = _models.probe(base_url=url, key="sk-probe", model="X",
                            headers={"X-Org": "ynu", "Authorization": "Bearer evil"})
        assert out["ok"] is True
        assert seen.get("X-Org") == "ynu", "自定义头随探活发出"
        assert seen.get("Authorization") == "Bearer sk-probe", "鉴权头不许被覆盖"
    finally:
        httpd.server_close()
