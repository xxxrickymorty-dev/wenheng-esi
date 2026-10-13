# -*- coding: utf-8 -*-
"""并发保护：任务运行时，上传的数据表与任何写入都被拒绝。"""
import asyncio

from server import config
from server import app as app_module
from src import acquisition_state as acq_state


class _Req:
    def __init__(self):
        self.session = {"user": config.ADMIN_USER}


class _Upload:
    filename = "new.xlsx"

    def __init__(self, data, after_read=None):
        self.data = data
        self.after_read = after_read

    async def read(self):
        if self.after_read:
            self.after_read()
        return self.data


def _busy(period="202607"):
    return {"id": "running", "period": period}


def _patch_state_dir(monkeypatch, tmp_path):
    """上传/开跑的当期核对副本落 out/_acquisition/<期次>/监测表.xlsx（STATE_DIR 可注入）。"""
    monkeypatch.setattr(acq_state, "STATE_DIR", tmp_path / "out" / "_acquisition")


def test_读取文件后才忙起来也不动原件(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    original = acq_state.copy_path("202609")
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original")
    state = {"busy": None}
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: state["busy"])
    monkeypatch.setattr(app_module.jobs, "create_job",
                        lambda *_args: (_ for _ in ()).throw(AssertionError("不应创建任务")))

    response = asyncio.run(app_module.api_create_job(
        _Req(), "202609", _Upload(b"replacement", lambda: state.update(busy=_busy()))))
    assert response.status_code == 409
    assert original.read_bytes() == b"original"


def test_忙时无上传也不建任何目录(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: _busy())
    monkeypatch.setattr(app_module.jobs, "create_job",
                        lambda *_args: (_ for _ in ()).throw(AssertionError("不应创建任务")))

    response = asyncio.run(app_module.api_create_job(_Req(), "202610", None))
    assert response.status_code == 409
    assert not (acq_state.STATE_DIR / "202610").exists()


def test_忙时上传不落任何目录(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: _busy())

    response = asyncio.run(app_module.api_create_job(_Req(), "202610", _Upload(b"new")))
    assert response.status_code == 409
    assert not (acq_state.STATE_DIR / "202610").exists()


def test_空闲时写入并正常创建任务(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: None)
    called = {}

    def create(period, input_path, actor, backtest):
        called.update(period=period, input_path=input_path, actor=actor, backtest=backtest)
        return {"id": "job-new"}

    monkeypatch.setattr(app_module.jobs, "create_job", create)
    response = asyncio.run(app_module.api_create_job(_Req(), "202610", _Upload(b"new"), "1"))
    target = acq_state.copy_path("202610")
    assert response == {"job_id": "job-new", "url": "/jobs/job-new"}
    assert target.read_bytes() == b"new"
    assert called == {"period": "202610", "input_path": target,
                      "actor": config.ADMIN_USER, "backtest": True}
