# -*- coding: utf-8 -*-
"""运行期模型清单（2026-10-29；2026-11-04 v2 供应商＋模型目录）：
落盘、掩码、当前项生效、写口校验、旧清单迁移。

口径：
- key **只落 out/**，读口只给掩码；
- 供应商没配齐（地址/key/目录缺一）→ 不算可用，回落 `.env` → 再回落规则版；
- 当前模型＝「哪条供应商＋目录里哪个型号」，切完下一次调用就生效
  （`cloud_config` 现读，不重建单例）。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import ai
from ai import _config, _models, _writing

#: conftest 的 `_isolate_ai_env` 会把 `active_credentials` 蒙成 None（开发机清单隐身）；
#: 本模块就是测清单本身的，所以先留一份真函数，需要时在测试里装回去。
_REAL_ACTIVE = _models.active_credentials


def _seed(root, **kw):
    row = {"id": "test-prov", "label": "测试模型", "base_url": "https://example.test/v1",
           "key": "sk-abcdef123456", "note": "", "models": ["Test/Model-1"]}
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
    row = got["providers"][0]
    assert row["key_hint"].endswith("3456") and row["ready"] is True
    assert row["models"] == ["Test/Model-1"], "模型目录随供应商读出"
    raw = json.loads((tmp_path / "_ai" / "models.json").read_text(encoding="utf-8"))
    assert raw["providers"][0]["key"] == "sk-abcdef123456", "key 落在 out/ 里（不入库）"


def test_第一条配齐的供应商自动成为当前(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        active = _models.public()["active"]
    assert active["provider"] == "test-prov" and active["model"] == "Test/Model-1"


def test_名字能拼id就用名字_拼不出用主机名(tmp_path):
    with ai.using(data_root=tmp_path):
        row = _models.upsert({"label": "云南大学网关（new-api）", "key": "k" * 10,
                              "base_url": "https://new-api-itc.ynu.edu.cn/v1",
                              "models": ["MiniMax/MiniMax-M2.7"]}, actor="admin")
        assert row["id"] == "new-api", "名字里的西文拼出 id"
        row = _models.upsert({"label": "云南大学网关", "key": "k" * 10,
                              "base_url": "https://new-api-itc.ynu.edu.cn/v1",
                              "models": ["MiniMax/MiniMax-M2.7"]}, actor="admin")
        assert row["id"] == "new-api-itc-ynu-edu-cn", "纯中文名拼不出，用主机名"


def test_key留空沿用旧key(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.upsert({"id": "test-prov", "label": "改了名字",
                        "base_url": "https://example.test/v1",
                        "models": ["Test/Model-1"], "key": ""}, actor="admin")
        row = _models.read()["providers"][0]
    assert row["label"] == "改了名字" and row["key"] == "sk-abcdef123456"


def test_目录去重保序_型号限量(tmp_path):
    with ai.using(data_root=tmp_path):
        row = _models.upsert({"id": "t1", "label": "网关", "key": "k" * 10,
                              "base_url": "https://a.test/v1",
                              "models": ["B", "A", "B", " ", "A"]}, actor="admin")
        assert row["models"] == ["B", "A"], "去重保序，空白丢弃"
        with pytest.raises(ValueError):
            _models.upsert({"id": "t1", "label": "网关", "key": "k" * 10,
                            "base_url": "https://a.test/v1",
                            "models": [f"m{i}" for i in range(65)]}, actor="admin")


# ============================================================ 可用性
def test_没配齐就不可用_回落部署配置(tmp_path):
    _seed(tmp_path, key="")
    with ai.using(data_root=tmp_path):
        assert _models.active_credentials() is None
        cfg = _config.cloud_config()
    assert cfg.get("source") != "清单", "没 key 不得被当成可用模型"


def test_目录空也不可用(tmp_path):
    _seed(tmp_path, models=[])
    with ai.using(data_root=tmp_path):
        assert _models.active_credentials() is None
        assert _models.public()["providers"][0]["ready"] is False


def test_切当前模型_下一次调用即生效(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path, key="")
    with ai.using(data_root=tmp_path):
        _models.upsert({"id": "second", "label": "第二个",
                        "base_url": "https://example.test/v1",
                        "key": "sk-second-9876",
                        "models": ["Test/Model-2", "Test/Model-3"]}, actor="admin")
        _models.set_active("second", "Test/Model-3", actor="admin")
        cred = _models.active_credentials()
        cfg = _config.cloud_config()
    assert cred["model"] == "Test/Model-3"
    assert cfg["backend"] == "openai" and cfg["model"] == "Test/Model-3"


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
            _models.upsert({"label": "X", "base_url": "example.test"}, actor="admin")
        with pytest.raises(ValueError):
            _models.upsert({"label": "X", "base_url": "https://"}, actor="admin")


def test_地址尾部补全到v1(tmp_path):
    with ai.using(data_root=tmp_path):
        row = _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1/chat/completions/",
                              "models": ["X"]}, actor="admin")
        assert row["base_url"] == "https://a.test/v1"
        row = _models.upsert({"id": "t2", "label": "Y", "key": "k" * 10,
                              "base_url": "https://b.test/v1/messages",
                              "models": ["Y"]}, actor="admin")
        assert row["base_url"] == "https://b.test/v1", "anthropic 系尾部一并剥掉"


def test_协议三选_保存读取_非法拒收(tmp_path):
    with ai.using(data_root=tmp_path):
        for p in ("openai", "openai-responses", "anthropic"):
            row = _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                                  "base_url": "https://a.test/v1",
                                  "protocol": p, "models": ["X"]}, actor="admin")
            assert row["protocol"] == p
        row = _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1",
                              "models": ["X"]}, actor="admin")
        assert row["protocol"] == "openai", "不给协议＝缺省 openai"
        with pytest.raises(ValueError):
            _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                            "base_url": "https://a.test/v1", "protocol": "gemini",
                            "models": ["X"]}, actor="admin")


def test_切到不存在或没配齐的报错(tmp_path):
    _seed(tmp_path, key="")
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            _models.set_active("nope", actor="admin")
        with pytest.raises(ValueError):
            _models.set_active("test-prov", actor="admin")   # 没 key
        _models.remove("test-prov", actor="admin")
        with pytest.raises(ValueError):
            _models.remove("test-prov", actor="admin")        # 已经删了


def test_切到目录外的型号报错(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            _models.set_active("test-prov", "Test/Not-In-Catalog", actor="admin")


# ============================================================ 思考深度（2026-11-06：输入框菜单与表单同值）
def test_思考深度_写到当前供应商_下一读即生效(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path, params={"reasoning_effort": "low"})
    with ai.using(data_root=tmp_path):
        _models.set_reasoning_effort("high", actor="admin")
        cred = _models.active_credentials()
        cfg = _config.cloud_config()
    assert cred["params"]["reasoning_effort"] == "high"
    assert cfg["params"]["reasoning_effort"] == "high", "cloud_config 现读，下一次调用即生效"


def test_思考深度_空串清掉_参数键不落(tmp_path):
    _seed(tmp_path, params={"reasoning_effort": "low"})
    with ai.using(data_root=tmp_path):
        _models.set_reasoning_effort("", actor="admin")
        row = _models.read()["providers"][0]
        raw = json.loads((tmp_path / "_ai" / "models.json").read_text(encoding="utf-8"))
    assert "reasoning_effort" not in (row.get("params") or {})
    assert "params" not in raw["providers"][0], "清空后盘上不落空 params 键（与 upsert 同形）"


def test_思考深度_非法档拒收(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            _models.set_reasoning_effort("ultra", actor="admin")


def test_思考深度_当前是部署配置行_拒收并指路(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.set_active("", actor="admin")            # 回到 .env 部署配置
        with pytest.raises(ValueError, match="\\.env"):
            _models.set_reasoning_effort("low", actor="admin")
        row = _models.read()["providers"][0]
    assert (row.get("params") or {}).get("reasoning_effort") is None, "拒绝时一个字节都不写"


def test_删掉当前项_回到部署配置(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.remove("test-prov", actor="admin")
        got = _models.public()
        assert got["active"]["provider"] == ""
        assert _models.active_credentials() is None


def test_目录改了_当前型号跟着目录走(tmp_path):
    _seed(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.upsert({"id": "test-prov", "label": "测试模型",
                        "base_url": "https://example.test/v1",
                        "key": "sk-abcdef123456",
                        "models": ["Test/Model-9"]}, actor="admin")
        active = _models.read()["active"]
    assert active["model"] == "Test/Model-9", "原型号被移出目录＝回目录第一个"


def test_坏文件按空清单处理不炸(tmp_path):
    p = tmp_path / "_ai" / "models.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ 这不是 JSON", encoding="utf-8")
    with ai.using(data_root=tmp_path):
        got = _models.public()
        assert got["providers"] == [] and got["active"]["provider"] == ""


# ============================================================ 旧清单迁移（schema 1 → 2）
def test_schema1旧清单自动迁移(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    p = tmp_path / "_ai" / "models.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "schema": 1, "active": "ynu-minimax",
        "models": [
            {"id": "ynu-deepseek", "label": "DeepSeek", "note": "",
             "base_url": "https://a.test/v1", "model": "deepseek-ai/DeepSeek-V4.1-Flash",
             "key": "sk-v1key123456", "added": "2026-10-29"},
            {"id": "ynu-minimax", "label": "MiniMax", "note": "",
             "base_url": "https://a.test/v1", "model": "MiniMax/MiniMax-M2.7",
             "key": "sk-v1key123456", "added": "2026-10-29"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    with ai.using(data_root=tmp_path):
        data = _models.read()
        assert data["schema"] == 2
        assert len(data["providers"]) == 2
        mini = next(q for q in data["providers"] if q["id"] == "ynu-minimax")
        assert mini["models"] == ["MiniMax/MiniMax-M2.7"], "旧型号进目录"
        pub = _models.public()
        assert pub["active"] == {"provider": "ynu-minimax",
                                 "model": "MiniMax/MiniMax-M2.7"}, \
            "旧的当前项迁移成「供应商＋型号」"
        cred = _models.active_credentials()
    assert cred is not None and cred["model"] == "MiniMax/MiniMax-M2.7"


# ============================================================ 探活／获取可用模型
def test_探活没key直接说清楚(tmp_path):
    out = _models.probe(base_url="https://example.test/v1", key="", model="X")
    assert out["ok"] is False and "key" in out["msg"]


def test_fetch_models_拉回型号清单(tmp_path):
    seen: dict[str, str] = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.update(dict(self.headers.items()))
            body = json.dumps({"data": [{"id": "MiniMax/MiniMax-M2.7"},
                                        {"id": "deepseek-ai/DeepSeek-V4.1-Flash"},
                                        {"id": ""}]}).encode("utf-8")
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
        out = _models.fetch_models(base_url=url, key="sk-fetch")
        assert out["ok"] is True
        assert out["ids"] == ["MiniMax/MiniMax-M2.7",
                              "deepseek-ai/DeepSeek-V4.1-Flash"], "空 id 丢弃"
    finally:
        httpd.server_close()


# ============================================================ 界面真实形状（2026-11-04 回归：/api/models/save 400）
def test_界面真实形状payload_保存成功(tmp_path):
    """rick 2026-11-04 两次保存 400 的回归钉：v2 表单交的是
    `{label,base_url,key,protocol,note,models:[…],headers:{}}`——**没有 `model`
    字段**。旧 v1 后端（478965a9）的 upsert 要求 `model` 字符串、为空即 400
    「型号不能为空」；这条用例钉死 v2 校验必须照 v2 表单形状收
    （探活 /api/models/test 在 v1 就存在，所以当时「test 200、save 400」）。"""
    form = {"label": "云南大学网关（new-api）",                    # 预置名：纯中文＋括号英文
            "base_url": "https://new-api-itc.ynu.edu.cn/v1",
            "key": "sk-form-test-key", "note": "",
            "protocol": "openai",
            "models": ["MiniMax/MiniMax-M2.7", "deepseek-ai/DeepSeek-V4.1-Flash"],
            "headers": {}}
    with ai.using(data_root=tmp_path):
        row = _models.upsert(form, actor="admin")
        assert row["id"] == "new-api", "中文名拼不出 id → 用地址主机名（new-api）"
        assert row["models"] == form["models"] and row["protocol"] == "openai"
        # 编辑流：key 留空＝沿用；headers 空对象＝没有自定义头
        row2 = _models.upsert({**form, "id": row["id"], "key": "",
                                "protocol": "anthropic"}, actor="admin")
        raw = json.loads((tmp_path / "_ai" / "models.json").read_text("utf-8"))
        kept = raw["providers"][0]
        assert kept["key"] == "sk-form-test-key", "key 留空沿用旧 key"
        assert kept["protocol"] == "anthropic" and "headers" not in kept


# ============================================================ headers（票 4，2026-11-03）
def test_headers保存读取round_trip(tmp_path):
    """供应商可选 headers：保存什么读回什么（read 原样回）；public 也带给界面（改时预填）。"""
    _seed(tmp_path, headers={"X-Org": "ynu", "X-Trace-Id": "abc-123"})
    with ai.using(data_root=tmp_path):
        row = _models.read()["providers"][0]
        assert row["headers"] == {"X-Org": "ynu", "X-Trace-Id": "abc-123"}
        pub = _models.public()["providers"][0]
        assert pub["headers"] == {"X-Org": "ynu", "X-Trace-Id": "abc-123"}
        assert pub["protocol"] == "openai"


def test_headers没给就不落字段_清空即删(tmp_path):
    with ai.using(data_root=tmp_path):
        row = _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1",
                              "models": ["X"]}, actor="admin")
        assert "headers" not in row, "没配 headers＝不出现这个字段"
        _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                        "base_url": "https://a.test/v1", "models": ["X"],
                        "headers": {"X-Org": "ynu"}}, actor="admin")
        row = _models.upsert({"id": "t1", "label": "X", "key": "k" * 10,
                              "base_url": "https://a.test/v1",
                              "models": ["X"]}, actor="admin")
        assert "headers" not in row, "再存一次不带 headers＝清掉（表单删了行就是删了头）"


def test_非法headers拒收(tmp_path):
    with ai.using(data_root=tmp_path):
        for bad in ({"坏 头": "v"},                       # 名字带空格
                    {"X_下划线": "v"},                    # 下划线不在允许集
                    {"X-Ok": ""},                        # 空值
                    {"X-Ok": "   "},                     # 全空白值
                    {f"X-H{i}": "v" for i in range(9)}):  # 超过 8 条
            with pytest.raises(ValueError):
                _models.upsert({"label": "X", "key": "k" * 10,
                                "base_url": "https://a.test/v1", "headers": bad,
                                "models": ["X"]}, actor="admin")
        with pytest.raises(ValueError):
            _models.upsert({"label": "X", "key": "k" * 10,
                            "base_url": "https://a.test/v1", "headers": "X-Org=ynu",
                            "models": ["X"]}, actor="admin")   # headers 要是对象，不是字符串


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


# ============================================================ params（2026-11-05，GLM 适配）
def test_params保存读取round_trip(tmp_path):
    """推理型型号的思考深度随供应商保存；读口/界面面都带出来（改时预填）。"""
    _seed(tmp_path, params={"reasoning_effort": "low"})
    with ai.using(data_root=tmp_path):
        assert _models.read()["providers"][0]["params"] == {"reasoning_effort": "low"}
        assert _models.public()["providers"][0]["params"] == {"reasoning_effort": "low"}
    raw = json.loads((tmp_path / "_ai" / "models.json").read_text(encoding="utf-8"))
    assert raw["providers"][0]["params"] == {"reasoning_effort": "low"}, "落在 out/ 清单里"


def test_params不给就沿用_给空即清空(tmp_path):
    """三态：不给＝沿用旧值（别静默抹掉别人的调参）；给 {} ＝明确清空（回网关缺省）。"""
    _seed(tmp_path, params={"reasoning_effort": "low"})
    with ai.using(data_root=tmp_path):
        kept = _models.upsert({"id": "test-prov", "label": "测试模型", "key": "",
                               "base_url": "https://example.test/v1",
                               "models": ["Test/Model-1"]}, actor="admin")
        assert kept["params"] == {"reasoning_effort": "low"}, "没提 params＝沿用"
        gone = _models.upsert({"id": "test-prov", "label": "测试模型", "key": "",
                               "base_url": "https://example.test/v1",
                               "models": ["Test/Model-1"], "params": {}}, actor="admin")
        assert "params" not in gone, "给空对象＝清掉（回网关缺省）"


def test_params白名单与取值校验(tmp_path):
    with ai.using(data_root=tmp_path):
        for bad in ({"temperature": "0.9"},                  # 不认识的结构键
                    {"reasoning_effort": "huge"},            # 取值不在四档里
                    "reasoning_effort=low"):                 # 形状不对（要对象）
            with pytest.raises(ValueError):
                _models.upsert({"label": "X", "key": "k" * 10,
                                "base_url": "https://a.test/v1", "params": bad,
                                "models": ["X"]}, actor="admin")


def test_当前条目的params传进brain(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path, params={"reasoning_effort": "low"})
    with ai.using(data_root=tmp_path):
        brain = _config.build_brain()
        assert brain._extra_params == {"reasoning_effort": "low"}, "清单条目的调参随调用发出"
    _seed(tmp_path, params={})          # 明确清空（不给＝沿用，见上一条用例）
    with ai.using(data_root=tmp_path):
        assert _config.build_brain()._extra_params == {}, "没配＝不发（网关缺省）"


# ============================================================ 位级型号覆盖（2026-11-07）
def _seed_b(root):
    """第二条供应商（写作位覆盖测试用，与 active 不同源）。"""
    with ai.using(data_root=root):
        _models.upsert({"id": "prov-b", "label": "写作位专用",
                        "base_url": "https://b.test/v1", "key": "k" * 10,
                        "models": ["Write/Model-9"], "params": {}}, actor="admin")


def test_位级覆盖_写入读取清除(tmp_path):
    _seed(tmp_path)
    _seed_b(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.set_position_model("write", "prov-b", "Write/Model-9", actor="admin")
        ov = _models.position_credentials("write")
        assert ov and ov["model"] == "Write/Model-9"
        assert ov["base_url"] == "https://b.test/v1", "凭据整套来自位级供应商"
        assert _models.public()["positions"]["write"]["provider"] == "prov-b"
        _models.set_position_model("write", "", actor="admin")       # 空＝清除
        assert _models.position_credentials("write") is None


def test_位级覆盖_校验不静默(tmp_path):
    _seed(tmp_path)
    _seed_b(tmp_path)
    with ai.using(data_root=tmp_path):
        with pytest.raises(ValueError):
            _models.set_position_model("qa", "prov-b", actor="admin")   # 未登记的位
        with pytest.raises(ValueError):
            _models.set_position_model("write", "no-such", actor="admin")
        with pytest.raises(ValueError):
            _models.set_position_model("write", "prov-b", "No/Such", actor="admin")


def test_切当前模型不抹位级覆盖(tmp_path):
    _seed(tmp_path)
    _seed_b(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.set_position_model("write", "prov-b", "Write/Model-9", actor="admin")
        _models.set_active("test-prov", "Test/Model-1", actor="admin")
        _models.set_reasoning_effort("low", actor="admin")
        assert _models.position_credentials("write")["model"] == "Write/Model-9", \
            "普通写口不感知位级键，不得顺手抹掉"


def test_失效覆盖读口自动清(tmp_path):
    _seed(tmp_path)
    _seed_b(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.set_position_model("write", "prov-b", "Write/Model-9", actor="admin")
        _models.remove("prov-b", actor="admin")
        assert _models.position_credentials("write") is None, "指向已删供应商＝清掉"


def test_flex_model_优先级_位级大于env大于当前(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path)
    _seed_b(tmp_path)
    with ai.using(data_root=tmp_path):
        assert _writing.flex_model() == "Test/Model-1", "无覆盖＝跟随当前模型"
        monkeypatch.setenv("WENHENG_FLEX_MODEL", "Env/Model")
        assert _writing.flex_model() == "Env/Model", "env 显式覆盖次之"
        _models.set_position_model("write", "prov-b", "Write/Model-9", actor="admin")
        assert _writing.flex_model() == "Write/Model-9", "清单位级覆盖最高"


def test_flex_brain用位级凭据_预算仍写作位(tmp_path, monkeypatch):
    monkeypatch.setattr(_models, "active_credentials", _REAL_ACTIVE)
    _seed(tmp_path)
    _seed_b(tmp_path)
    with ai.using(data_root=tmp_path):
        _models.set_position_model("write", "prov-b", "Write/Model-9", actor="admin")
        brain = _writing.flex_brain()
        assert brain.name == "openai:Write/Model-9", "型号取位级覆盖"
        assert brain.base_url == "https://b.test/v1", "地址/key 整套用位级供应商"
        assert brain.timeout == _writing.FLEX_TIMEOUT, "预算仍写作位专用（180s）"
        assert brain.max_tokens == _writing.FLEX_MAX_TOKENS
