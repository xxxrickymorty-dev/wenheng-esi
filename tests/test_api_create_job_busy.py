# -*- coding: utf-8 -*-
"""创建任务时，运行中的任务必须先于任何输入写入被拒绝。"""
import asyncio

from server import config
from server import app as app_module


class _Req:
    def __init__(self):
        self.session = {"user": config.DEMO_USER}


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


def test_读取后出现运行任务也不覆盖原输入(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INPUT_DIR", tmp_path / "input")
    original = config.INPUT_DIR / "202609" / "监测表.xlsx"
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


def test_忙碌时不上传也不创建任务(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: _busy())
    monkeypatch.setattr(app_module.jobs, "create_job",
                        lambda *_args: (_ for _ in ()).throw(AssertionError("不应创建任务")))

    response = asyncio.run(app_module.api_create_job(_Req(), "202610", None))
    assert response.status_code == 409
    assert not (config.INPUT_DIR / "202610").exists()


def test_忙碌时不创建新输入目录(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: _busy())

    response = asyncio.run(app_module.api_create_job(_Req(), "202610", _Upload(b"new")))
    assert response.status_code == 409
    assert not (config.INPUT_DIR / "202610").exists()


def test_空闲时仍写入并创建任务(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(app_module.jobs, "active_job", lambda: None)
    called = {}

    def create(period, input_path, actor, backtest):
        called.update(period=period, input_path=input_path, actor=actor, backtest=backtest)
        return {"id": "job-new"}

    monkeypatch.setattr(app_module.jobs, "create_job", create)
    response = asyncio.run(app_module.api_create_job(_Req(), "202610", _Upload(b"new"), "1"))
    target = config.INPUT_DIR / "202610" / "监测表.xlsx"
    assert response == {"job_id": "job-new", "url": "/jobs/job-new"}
    assert target.read_bytes() == b"new"
    assert called == {"period": "202610", "input_path": target,
                      "actor": config.DEMO_USER, "backtest": True}
