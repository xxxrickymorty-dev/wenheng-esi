# -*- coding: utf-8 -*-
"""报告接线（契约 #17 报告侧）：预测台选模 → 预测章配图。

守卫三件事：
  1. `out/<期次>/forecast_choice.json` 只认新嵌套形状（中文学科键）；旧扁平形状
     （英文键，如 `{"Chemistry": "SARIMA模型"}`）整份忽略并记警告；
  2. 逐路线覆盖：选中的 (路线, 学科) 用所选模型，未列出的保持 `"recommended"`；
  3. 所选模型运行失败 → 降级 V1 推荐并记警告（不拦停出图）。
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import report_forecast                                          # noqa: E402

SUBJECTS = ["分子生物学与遗传学", "物理学"]


def _write_choice(period_dir, choice, **provenance):
    record = {"choice": choice, "by": "demo", "at": "2026-09-24 12:00:00"}
    record.update(provenance)
    (pathlib.Path(period_dir) / report_forecast.CHOICE_FILE).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8")


def _stub_generate(monkeypatch, run_prediction):
    """把 generate 的数据源与绘图全换成桩：只验选模接线，不碰 parquet/母版。"""
    # upto：report_forecast 的补跑截断参数（2026-09-29 加）——桩照收，行为不变
    monkeypatch.setattr(report_forecast, "pick_subjects",
                        lambda d, upto=None: (list(SUBJECTS), "202607"))
    monkeypatch.setattr(report_forecast, "load_standard_input",
                        lambda d, validate=True, upto=None: (pd.DataFrame({"学科": SUBJECTS}), {}))
    monkeypatch.setattr(
        report_forecast, "subject_task_data",
        lambda data, cn, task: ([202601, 202603],
                                {col: np.ones(8) for col in
                                 ("总被引", "ESI前1%被引阈值", "云大国内排名", "国内ESI前1%机构数")}))
    monkeypatch.setattr(report_forecast, "run_prediction", run_prediction)
    monkeypatch.setattr(report_forecast, "fit_and_forecast",
                        lambda model, values, horizon: (np.ones(8), np.ones(3), {}))
    monkeypatch.setattr(report_forecast.charts, "chart_forecast", lambda *a, **k: None)


class Test读取选择:
    def test_无文件_空选择无警告(self, tmp_path):
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {} and warnings == []

    def test_新嵌套形状_逐路线(self, tmp_path):
        _write_choice(tmp_path, {"citation": {"物理学": "SARIMA模型"},
                                 "rank": {"分子生物学与遗传学": "阻尼Holt模型"}})
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {("citation", "物理学"): "SARIMA模型",
                          ("rank", "分子生物学与遗传学"): "阻尼Holt模型"}
        assert warnings == []

    def test_旧扁平形状整份忽略并警告(self, tmp_path):
        """旧文件是英文键（out/202607 现存的就是），硬接会错配到别的学科。"""
        _write_choice(tmp_path, {"Chemistry": "SARIMA模型"})
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {}
        assert len(warnings) == 1 and "旧扁平形状" in warnings[0]

    def test_未知路线忽略并警告(self, tmp_path):
        _write_choice(tmp_path, {"cites": {"物理学": "SARIMA模型"}})
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {}
        assert len(warnings) == 1 and "未知路线" in warnings[0]

    def test_未知模型忽略并警告(self, tmp_path):
        _write_choice(tmp_path, {"citation": {"物理学": "不存在的模型"}})
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {}
        assert len(warnings) == 1 and "不在可选模型里" in warnings[0]

    def test_坏JSON忽略并警告(self, tmp_path):
        (tmp_path / report_forecast.CHOICE_FILE).write_text("{不是JSON", encoding="utf-8")
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {}
        assert len(warnings) == 1 and "读取失败" in warnings[0]

    def test_带BOM的手工文件可读(self, tmp_path):
        """记事本另存会带 BOM；服务端/前端写盘不带——两种都要能读。"""
        (tmp_path / report_forecast.CHOICE_FILE).write_text(
            json.dumps({"choice": {"citation": {"物理学": "SARIMA模型"}}},
                       ensure_ascii=False), encoding="utf-8-sig")
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {("citation", "物理学"): "SARIMA模型"}
        assert warnings == []

    def test_空选择不警告(self, tmp_path):
        _write_choice(tmp_path, {})
        picked, warnings = report_forecast.load_choice(tmp_path)
        assert picked == {} and warnings == []


class Test降级:
    def test_所选模型失败降级推荐并记警告(self, monkeypatch):
        calls = []

        def fake(subject, periods, series, task, model, horizon):
            calls.append(model)
            if model == "SARIMA模型":
                raise ValueError("SARIMA 不收敛")
            return {"results": [{"model": "季节性ETS模型", "rolling_mape": 1.0}]}

        monkeypatch.setattr(report_forecast, "run_prediction", fake)
        warnings = []
        res = report_forecast._run_with_choice(
            "物理学", [202601], {}, "citation", "SARIMA模型", warnings)
        assert calls == ["SARIMA模型", "recommended"]
        assert res["results"][0]["model"] == "季节性ETS模型"
        assert len(warnings) == 1 and "已降级 V1 推荐" in warnings[0]

    def test_推荐模型失败不吞异常(self, monkeypatch):
        def fake(*a, **k):
            raise ValueError("数据不足")

        monkeypatch.setattr(report_forecast, "run_prediction", fake)
        with pytest.raises(ValueError):
            report_forecast._run_with_choice(
                "物理学", [202601], {}, "citation", "recommended", [])


class Test出图接线:
    def test_选中学科用所选模型_未选保持推荐(self, tmp_path, monkeypatch):
        calls = []

        def fake(subject, periods, series, task, model, horizon):
            calls.append((task, subject, model))
            used = "季节性ETS模型" if model == "recommended" else model
            return {"results": [{"model": used, "rolling_mape": 1.0,
                                 "first_crossing": None,
                                 "forecast": [{"period": 202609}]}]}

        _stub_generate(monkeypatch, fake)
        _write_choice(tmp_path, {"citation": {"物理学": "SARIMA模型"}})
        assert report_forecast.generate(tmp_path) == 4

        meta = json.loads((tmp_path / "forecast_charts.json").read_text(encoding="utf-8"))
        by_key = {(c["subject"], c["task"]): c for c in meta["charts"]}
        assert by_key[("物理学", "citation")]["model"] == "SARIMA模型"
        assert by_key[("分子生物学与遗传学", "citation")]["model"] == "季节性ETS模型"
        assert by_key[("物理学", "rank")]["model"] == "季节性ETS模型"
        assert meta["warnings"] == []
        # 每条留 requested 痕：未选＝recommended
        assert by_key[("物理学", "citation")]["requested"] == "SARIMA模型"
        assert by_key[("分子生物学与遗传学", "rank")]["requested"] == "recommended"
        # 逐路线逐学科各跑一次：所选学科只跑所选模型，不再跑推荐
        assert calls == [("citation", "分子生物学与遗传学", "recommended"),
                         ("rank", "分子生物学与遗传学", "recommended"),
                         ("citation", "物理学", "SARIMA模型"),
                         ("rank", "物理学", "recommended")]

    def test_所选模型失败_出图仍成且警告进产物(self, tmp_path, monkeypatch):
        def fake(subject, periods, series, task, model, horizon):
            if model == "SARIMA模型":
                raise ValueError("SARIMA 不收敛")
            return {"results": [{"model": "季节性ETS模型", "rolling_mape": 1.0,
                                 "first_crossing": None,
                                 "forecast": [{"period": 202609}]}]}

        _stub_generate(monkeypatch, fake)
        _write_choice(tmp_path, {"citation": {"物理学": "SARIMA模型"}})
        assert report_forecast.generate(tmp_path) == 4

        meta = json.loads((tmp_path / "forecast_charts.json").read_text(encoding="utf-8"))
        by_key = {(c["subject"], c["task"]): c for c in meta["charts"]}
        assert by_key[("物理学", "citation")]["model"] == "季节性ETS模型"
        assert by_key[("物理学", "citation")]["requested"] == "SARIMA模型"
        assert len(meta["warnings"]) == 1 and "已降级" in meta["warnings"][0]
        assert report_forecast.load_warnings(tmp_path) == meta["warnings"]

    def test_无持久化设置使用推荐并记录最终模型(self, tmp_path, monkeypatch):
        def fake(subject, periods, series, task, model, horizon):
            assert model == "recommended"
            return {"results": [{"model": "季节性ETS模型", "rolling_mape": 1.0,
                                 "first_crossing": None,
                                 "forecast": [{"period": 202609}]}]}

        _stub_generate(monkeypatch, fake)
        assert report_forecast.generate(tmp_path) == 4
        meta = json.loads((tmp_path / "forecast_charts.json").read_text(encoding="utf-8"))
        assert all(c["requested"] == "recommended" for c in meta["charts"])
        assert all(c["model"] == "季节性ETS模型" for c in meta["charts"])
        assert meta["warnings"] == []

    def test_预测元数据留存请求与输出期次来源(self, tmp_path, monkeypatch):
        def fake(subject, periods, series, task, model, horizon):
            return {"results": [{"model": "季节性ETS模型", "rolling_mape": 1.0,
                                 "first_crossing": None,
                                 "forecast": [{"period": 202609}]}]}

        _stub_generate(monkeypatch, fake)
        monkeypatch.setattr(report_forecast, "pick_subjects",
                            lambda d, upto=None: (list(SUBJECTS), "202612"))
        applied_choice = tmp_path / "_forecast_choice_applied.json"
        applied_choice.write_text(json.dumps({
            "choice": {"citation": {"物理学": "SARIMA模型"}},
            "request_period": "202610", "choice_period": "202610",
            "source_period": "202612", "output_period": "202612",
            "config_updated_at": "2026-09-27 10:00:00", "operator": "librarian",
            "snapshot_at": "2026-09-27 10:01:00", "snapshot_source": "primary",
        }, ensure_ascii=False), encoding="utf-8")
        assert report_forecast.generate(tmp_path, choice_path=applied_choice) == 4

        meta = json.loads((tmp_path / "forecast_charts.json").read_text(encoding="utf-8"))
        assert meta["request_period"] == "202610"
        assert meta["choice_period"] == "202610"
        assert meta["source_period"] == "202612"
        assert meta["output_period"] == "202612"
        assert meta["config_updated_at"] == "2026-09-27 10:00:00"
        assert meta["operator"] == "librarian"
        assert meta["snapshot_at"] == "2026-09-27 10:01:00"

    def test_生成失败时旧预测元数据和图已隔离(self, tmp_path, monkeypatch):
        overview = tmp_path / "charts" / "_overview"
        overview.mkdir(parents=True)
        stale_meta = tmp_path / "forecast_charts.json"
        stale_meta.write_text(json.dumps({"charts": [{"model": "旧模型"}]}), encoding="utf-8")
        stale_pngs = []
        for name in ("forecast_1_cites.png", "forecast_1_rank.png",
                     "forecast_2_cites.png", "forecast_2_rank.png"):
            path = overview / name
            path.write_bytes(b"old forecast")
            stale_pngs.append(path)

        def predicted(*args, **kwargs):
            return {"results": [{"model": "季节性ETS模型", "rolling_mape": 1.0,
                                 "first_crossing": None,
                                 "forecast": [{"period": 202609}]}]}

        def fail_after_partial_png(*args, **kwargs):
            pathlib.Path(args[-1]).write_bytes(b"partial forecast")
            raise ValueError("预测图写入失败")

        _stub_generate(monkeypatch, predicted)
        monkeypatch.setattr(report_forecast.charts, "chart_forecast", fail_after_partial_png)
        with pytest.raises(ValueError, match="预测图写入失败"):
            report_forecast.generate(tmp_path)

        assert not stale_meta.exists()
        assert all(not path.exists() for path in stale_pngs)
        archived = list((tmp_path / "_superseded" / "forecast").rglob("*"))
        assert any(p.name == stale_meta.name and p.read_text(encoding="utf-8")
                   for p in archived if p.is_file())
        assert {p.name for p in archived if p.is_file()} >= {p.name for p in stale_pngs} \
            | {stale_meta.name}
        assert any(p.is_file() and p.read_bytes() == b"partial forecast" for p in archived)


class Testrun_log留痕:
    def test_run_pipeline收走预测警告(self):
        """run_log 的 forecast_warnings 由 load_warnings 读产物而来（不重算）。"""
        src = (REPO / "src" / "run_pipeline.py").read_text(encoding="utf-8")
        assert "forecast_warnings" in src and "load_warnings" in src
