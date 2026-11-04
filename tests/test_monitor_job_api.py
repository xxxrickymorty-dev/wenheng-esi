# -*- coding: utf-8 -*-
"""监测版生成任务口（2026-11-04，rick 批）：同步口之外加任务制/流式。

- `POST /api/monitor/report/job`、`/api/monitor/compare/job` → 立刻回
  `{job_id, url, status:"running"}`（同参任务在跑 → 复用 `reused:true`；
  另有监测任务在跑 → 单飞 409）；
- `GET /api/monitor/jobs/{id}` 轮询三态：running → completed（产物 `url`）
  / failed（`error` 人话）；
- 失败人话：`AIRequiredError`（供应商强制语义，rick 2026-11-04）原样入
  `error`，不落半份产物（generate 本就「解读算在写盘之前」）；
- 关闭态行为不变：insight 失败照旧回落句骨架 → 任务照常 completed 出件。

仓库测试惯例是函数级（不依赖 httpx/TestClient）：路由层只是透传，
直测 `server.routes.monitor` 任务口的同步内核（`_report_job_create` 等）。
⚠ 模块双名：路由层绑 `src.monitor.*`，引擎内部绑 `monitor.*`
（两套 sys.modules 对象）——替身要打在对的模块对象上，见各用例注释。
记录落仓库 tmp/ 下自管根（本机沙箱 pytest tmp_path 清理是基线
PermissionError，见交付说明），用完即删。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import threading
import time
import urllib.parse
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from fastapi.responses import JSONResponse          # noqa: E402

import monitor.report as mr_engine                  # noqa: E402  # 引擎名
import monitor.insight as mi                        # noqa: E402  # 引擎名
from ai._attempt import AIRequiredError             # noqa: E402
from server.routes import monitor as mon_routes     # noqa: E402
from src.monitor import compare as mcmp_routes      # noqa: E402  # 路由名
from src.monitor import jobs as mjobs               # noqa: E402
from src.monitor import report as mr_routes         # noqa: E402  # 路由名


@pytest.fixture
def work_root(monkeypatch):
    """自管临时根（同 test_ai_strict 惯例）：MONITOR_ROOT 双名都指过去，
    产物与任务记录（`_jobs/`）全落 tmp，用完即删。"""
    d = (pathlib.Path(__file__).resolve().parent.parent / "tmp"
         / f"pt_mon_job_{uuid.uuid4().hex[:8]}")
    d.mkdir(parents=True)
    # 引擎名（mjobs 存储落点、compare_path 落点）＋ 路由名（routes 校验/生成）
    monkeypatch.setattr(mr_engine, "MONITOR_ROOT", d)
    monkeypatch.setattr(mr_routes, "MONITOR_ROOT", d)
    monkeypatch.setattr(mr_engine, "latest_period", lambda: "202609")
    monkeypatch.setattr(mr_routes, "latest_period", lambda: "202609")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _report_url(cn: str) -> str:
    """产物 url 形状（校名 quote，与同步口 `/monitor/report/<校名>/<期次>.html` 同形）。"""
    return f"/monitor/report/{urllib.parse.quote(cn)}/202609.html"


def _wait(job_id, timeout=10.0):
    """轮询到终态（任务口约定：前端轮询/SSE，这里同款读法）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = mjobs.read(job_id)
        if j and mjobs.is_terminal(j.get("status")):
            return j
        time.sleep(0.02)
    raise AssertionError("任务未在时限内到终态")


def _stub_report_generate(monkeypatch, work_root):
    """路由名的 generate 替身：按 generate 的真实契约落盘并返回路径。"""
    def _gen(cn, period):
        p = work_root / cn / f"{period}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<html></html>", encoding="utf-8")
        return p
    monkeypatch.setattr(mr_routes, "generate", _gen)


# ================================================================ 单校任务口
class Test单校任务口:
    def test_成功三态_进行中到completed带产物url(self, monkeypatch, work_root):
        _stub_report_generate(monkeypatch, work_root)
        out = mon_routes._report_job_create("清华大学", "tester")
        assert not isinstance(out, JSONResponse)
        assert out["status"] == "running"
        assert out["url"] == f"/api/monitor/jobs/{out['job_id']}"
        job = mjobs.read(out["job_id"])
        assert job["status"] == "running"
        assert job["params"] == {"school": "清华大学", "period": "202609"}
        done = _wait(out["job_id"])
        assert done["status"] == "completed"
        assert done["url"] == _report_url("清华大学"), "产物 url（校名 quote，同同步口）"
        assert done["error"] is None
        assert (work_root / "清华大学" / "202609.html").exists(), "产物已落盘"
        assert (work_root / "_jobs" / f"{out['job_id']}.json").is_file(), \
            "任务记录落 monitor_data/_jobs/（不进 out/_state 的流水线 jobs 表）"

    def test_失败AIRequiredError_人话入error不落半份产物(self, monkeypatch,
                                                            work_root):
        # 走**真实** generate 链（替身只替数据件与 insight 模型位），
        # 供应商强制语义的穿透与「不落半份产物」一起验。
        monkeypatch.setattr(mr_routes, "load_cache", lambda p: {"period": p})

        def _boom(*a, **k):                                   # noqa: ARG002
            raise AIRequiredError("brain_error:timeout", what="监测版解读")

        monkeypatch.setattr(mi, "insight", _boom)
        out = mon_routes._report_job_create("清华大学", "tester")
        done = _wait(out["job_id"])
        assert done["status"] == "failed"
        assert "监测版解读" in done["error"], "人话（位置）"
        assert "原因码 brain_error:timeout" in done["error"], "人话（原因码）"
        assert done["url"] is None, "失败不留产物 url"
        assert not (work_root / "清华大学" / "202609.html").exists(), \
            "解读算在写盘之前：不落半份产物"

    def test_进行中可见_同参复用job_id(self, monkeypatch, work_root):
        release = threading.Event()

        def _slow(cn, period):                                # noqa: ARG002
            release.wait(10)
            p = work_root / cn / f"{period}.html"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("<html></html>", encoding="utf-8")
            return p

        monkeypatch.setattr(mr_routes, "generate", _slow)
        first = mon_routes._report_job_create("清华大学", "tester")
        assert mjobs.read(first["job_id"])["status"] == "running", "进行中可见"
        again = mon_routes._report_job_create("清华大学", "tester")
        assert again["job_id"] == first["job_id"], "同参任务在跑 → 复用"
        assert again.get("reused") is True
        assert mjobs.read(first["job_id"])["status"] == "running", \
            "复用不起第二个生成线程"
        release.set()
        done = _wait(first["job_id"])
        assert done["status"] == "completed"

    def test_单飞_不同参数409人话(self, monkeypatch, work_root):
        release = threading.Event()
        monkeypatch.setattr(
            mr_routes, "generate",
            lambda cn, period: (release.wait(10),
                                (work_root / cn / f"{period}.html"))[1])
        first = mon_routes._report_job_create("清华大学", "tester")
        busy = mon_routes._report_job_create("云南大学", "tester")
        assert isinstance(busy, JSONResponse) and busy.status_code == 409
        assert "已有监测生成任务在运行" in busy.body.decode("utf-8")
        release.set()
        _wait(first["job_id"])

    def test_名单外校_与同步口同款404不建任务(self, work_root):
        out = mon_routes._report_job_create("占星大学", "tester")
        assert isinstance(out, JSONResponse) and out.status_code == 404
        assert mjobs.list_jobs() == [], "预检不过不建任务记录"


# ================================================================ 对比任务口
class Test对比任务口:
    def test_成功_completed带产物url_参数去重保序(self, monkeypatch, work_root):
        def _gen(cns, period):
            p = work_root / "_compare" / period / "cmp_x.html"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("<html></html>", encoding="utf-8")
            return p
        monkeypatch.setattr(mcmp_routes, "generate", _gen)
        out = mon_routes._compare_job_create(
            ["云南大学", "清华大学", "云南大学"], "tester")
        assert not isinstance(out, JSONResponse)
        job = mjobs.read(out["job_id"])
        assert job["params"]["schools"] == ["云南大学", "清华大学"], \
            "幂等键去重保序（与 generate 同一去重）"
        done = _wait(out["job_id"])
        assert done["status"] == "completed"
        assert done["url"] == "/monitor/compare/202609/cmp_x.html", \
            "与 compare-status 探测口同形"

    def test_失败AIRequiredError_人话_不落半份产物(self, monkeypatch, work_root):
        # 真实 generate 链：compare_path 经引擎名 mr.MONITOR_ROOT 落 tmp；
        # 解读模型位（引擎名 monitor.insight）替身直接抛。
        monkeypatch.setattr(mr_engine, "load_cache", lambda p: {"period": p})
        monkeypatch.setattr(mcmp_routes, "facts_of", lambda cns, c: ["事实行"])

        def _boom(*a, **k):                                   # noqa: ARG002
            raise AIRequiredError("brain_error:timeout", what="监测版解读")

        monkeypatch.setattr(mi, "compose_text", _boom)
        out = mon_routes._compare_job_create(["清华大学", "云南大学"], "tester")
        done = _wait(out["job_id"])
        assert done["status"] == "failed"
        assert "监测版解读" in done["error"]
        assert done["url"] is None
        assert not list((work_root / "_compare").rglob("*.html")), \
            "不落半份产物"

    def test_校验与同步口同款_少于2校400名单外404(self, work_root):
        few = mon_routes._compare_job_create(["清华大学"], "tester")
        assert isinstance(few, JSONResponse) and few.status_code == 400
        unknown = mon_routes._compare_job_create(["清华大学", "占星大学"],
                                                 "tester")
        assert isinstance(unknown, JSONResponse) and unknown.status_code == 404
        assert mjobs.list_jobs() == [], "预检不过不建任务记录"


# ================================================================ 关闭态与收口
class Test关闭态与收口:
    def test_关闭态行为不变_insight失败照旧回落出件(self, monkeypatch, work_root):
        # 关闭态（默认，未配 WENHENG_AI_*）：insight 普通失败 → 句骨架回落
        # → 任务照常 completed 出件。与 test_monitor_strict 的关闭态判定同源。
        monkeypatch.setattr(mr_routes, "load_cache", lambda p: {"period": p})
        monkeypatch.setattr(mr_routes, "render",
                            lambda *a, **k: "<html>规则稿</html>")

        def _boom(*a, **k):                                   # noqa: ARG002
            raise RuntimeError("普通炸")

        monkeypatch.setattr(mi, "insight", _boom)
        out = mon_routes._report_job_create("清华大学", "tester")
        done = _wait(out["job_id"])
        assert done["status"] == "completed", "关闭态：回落照旧，不算失败"
        assert done["url"] == _report_url("清华大学")
        assert (work_root / "清华大学" / "202609.html").exists()

    def test_普通异常_失败入档带类型摘要(self, monkeypatch, work_root):
        def _boom(cn, period):                                # noqa: ARG002
            raise ValueError("缓存坏了")

        monkeypatch.setattr(mr_routes, "generate", _boom)
        out = mon_routes._report_job_create("清华大学", "tester")
        done = _wait(out["job_id"])
        assert done["status"] == "failed"
        assert "生成失败" in done["error"] and "ValueError" in done["error"]

    def test_recover_stale_重启残留running结成failed_解除单飞(self, work_root):
        job = mjobs.create(mjobs.KIND_REPORT,
                           {"school": "清华大学", "period": "202609"},
                           "tester", period="202609")
        assert mjobs.any_running()
        n = mjobs.recover_stale()
        assert n >= 1
        rec = mjobs.read(job["id"])
        assert rec["status"] == "failed"
        assert "服务重启" in rec["error"]
        assert mjobs.any_running() is False, "单飞解除，可发起新任务"
        again = mjobs.create(mjobs.KIND_REPORT,
                             {"school": "云南大学", "period": "202609"},
                             "tester", period="202609")
        assert again["status"] == "running"
