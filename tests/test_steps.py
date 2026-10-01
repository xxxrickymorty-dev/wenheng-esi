# -*- coding: utf-8 -*-
"""五步注册表（`src/steps.py`）：与 agent 步骤表防漂移、tools 转接、probe 不落盘。

步骤体的行为测试走两条既有主线：`test_pipeline_smoke`（直跑壳）与
`test_agent_flow` / `test_agent_heal`（受控壳）；这里只钉注册表本身的契约。
"""
import pytest

import steps

from agent import flow, tools


class Test_注册表:
    def test_与flow步骤表逐位一致(self):
        assert [s["id"] for s in flow.STEPS] == list(steps.STEP_IDS), \
            "flow.STEPS 与 steps.STEPS 已漂移 —— 主干顺序有两个事实源"

    def test_probe只探期次不落盘(self, latest_ledger, tmp_path):
        out = tmp_path / "_pending"
        res = steps.parse(steps.StepCtx(ledger=str(latest_ledger), out_dir=str(out),
                                        probe=True))
        assert res.data["period"] and res.data["assertions_ok"] is True
        assert not out.exists(), "probe 一个字节都不许写"

    def test_run_step按id分发(self, monkeypatch, tmp_path):
        seen = {}

        def fake(ctx):
            seen["ctx"] = ctx
            return steps.StepResult({"ok": "yes"})

        monkeypatch.setattr(steps, "compute", fake)
        # run_step 里注册的是原函数引用，替换后需重建元组？不——注册表存的是旧引用；
        # 用 monkeypatch 直接换表项，保证分发的就是当前实现。
        monkeypatch.setattr(steps, "STEPS", (
            steps.Step("parse", steps.parse), steps.Step("compute", fake),
            steps.Step("forecast", steps.forecast), steps.Step("charts", steps.charts),
            steps.Step("docx", steps.docx)))
        res = steps.run_step("compute", steps.StepCtx(out_dir=str(tmp_path)))
        assert res.data == {"ok": "yes"} and seen["ctx"].out_dir == str(tmp_path)
        with pytest.raises(KeyError):
            steps.run_step("nope", steps.StepCtx())


class Test_tools转接:
    def test_run_compute转接steps(self, monkeypatch):
        seen = {}

        def fake(ctx):
            seen["ctx"] = ctx
            return steps.StepResult({"period": "202607", "rows": 22, "table2": "x"})

        monkeypatch.setattr(steps, "compute", fake)
        got = tools.call("run_compute", out_dir="whatever")
        assert got["ok"] is True and got["period"] == "202607" and got["rows"] == 22
        assert seen["ctx"].out_dir == "whatever"

    def test_步骤错误码原样转成工具错误(self, monkeypatch):
        def boom(ctx):
            raise steps.StepError("SAMPLE_TOO_FEW", "样本不足", n=3)

        monkeypatch.setattr(steps, "forecast", boom)
        with pytest.raises(tools.ToolError) as e:
            tools.call("run_forecast", out_dir="x")
        assert e.value.code == "SAMPLE_TOO_FEW" and e.value.detail.get("n") == 3

    def test_run_parse_probe是契约里的可选参数(self):
        t = tools.REGISTRY["run_parse"]
        assert "probe" in t.args and t.args["probe"][1] is False
