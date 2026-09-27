# -*- coding: utf-8 -*-
"""预测选模 module（forecast_choice）：读序、快照、留痕与严格/宽松两种校验的单一出口。

这组用例守的是「一份记录只有一种语义」：
  · 读序 primary → legacy → default 只实现一次，坏 primary 不落 legacy；
  · 快照是冻结值，写盘走同一形状；
  · 宽松读取（旧扁平形状整份忽略）与严格校验（HTTP 400 口径）共用同一组常量。
"""
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import forecast_choice  # noqa: E402


def _write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


class Test读序:
    def test_primary优先legacy回退(self, tmp_path):
        out = tmp_path / "out"
        period = "202609"
        _write(out / period / forecast_choice.CHOICE_FILE,
               {"choice": {"rank": {"物理学": "all"}}, "by": "old", "at": "old-time"})
        legacy_only = forecast_choice.read_entry(
            period, choices_dir=out / "_forecast_choices", out_dir=out)
        assert legacy_only["source"] == "legacy"
        assert legacy_only["source_path"] == f"{period}/forecast_choice.json"
        assert legacy_only["choice"] == {"rank": {"物理学": "all"}}
        assert legacy_only["by"] == "old" and legacy_only["at"] == "old-time"

        _write(out / "_forecast_choices" / f"{period}.json",
               {"choice": {"citation": {"物理学": "SARIMA模型"}},
                "by": "new", "at": "new-time"})
        primary = forecast_choice.read_entry(
            period, choices_dir=out / "_forecast_choices", out_dir=out)
        assert primary["source"] == "primary"
        assert primary["source_path"] == f"_forecast_choices/{period}.json"
        assert primary["choice"] == {"citation": {"物理学": "SARIMA模型"}}

    def test_primary坏掉不落legacy(self, tmp_path):
        """回退只看存在性：primary 存在但读不出来 ≠ 没有配置。"""
        out = tmp_path / "out"
        period = "202609"
        _write(out / period / forecast_choice.CHOICE_FILE,
               {"choice": {"citation": {"物理学": "all"}}})
        bad = out / "_forecast_choices" / f"{period}.json"
        bad.parent.mkdir(parents=True)
        bad.write_text("{不是JSON", encoding="utf-8")
        entry = forecast_choice.read_entry(
            period, choices_dir=out / "_forecast_choices", out_dir=out)
        assert entry["source"] == "primary"
        assert entry["choice"] == {} and entry["by"] == ""
        assert entry["error"]

    def test_无文件为default(self, tmp_path):
        out = tmp_path / "out"
        entry = forecast_choice.read_entry(
            "202609", choices_dir=out / "_forecast_choices", out_dir=out)
        assert entry["source"] == "default"
        assert entry["source_path"] == ""
        assert entry["choice"] == {} and entry["by"] == "" and entry["at"] == ""
        assert entry["error"] is None

    def test_类型清洗(self, tmp_path):
        out = tmp_path / "out"
        period = "202609"
        _write(out / "_forecast_choices" / f"{period}.json",
               {"choice": [1, 2], "by": 7, "at": None})
        entry = forecast_choice.read_entry(
            period, choices_dir=out / "_forecast_choices", out_dir=out)
        assert entry["choice"] == {} and entry["by"] == "" and entry["at"] == ""
        assert entry["error"] is None  # 能读、也解析成对象，只是形状脏


class Test写盘与计数:
    def test_写盘形状(self, tmp_path):
        target = forecast_choice.write_entry(
            "202609", {"citation": {"物理学": "SARIMA模型"}},
            by="librarian", at="2026-09-27 10:00:00",
            choices_dir=tmp_path / "out" / "_forecast_choices")
        record = json.loads(target.read_text(encoding="utf-8"))
        assert target.name == "202609.json"
        assert record == {"choice": {"citation": {"物理学": "SARIMA模型"}},
                          "by": "librarian", "at": "2026-09-27 10:00:00"}

    def test_count_嵌套与扁平(self):
        assert forecast_choice.count(
            {"citation": {"A": "m1", "B": "m2"}, "rank": {"C": "m3"}}) == (3, 2)
        assert forecast_choice.count({"A": "m1", "B": "m2"}) == (2, None)
        assert forecast_choice.count({}) == (0, None)


class Test快照与应用:
    def test_快照冻结且带来源(self, tmp_path):
        out = tmp_path / "out"
        primary = out / "_forecast_choices" / "202609.json"
        _write(primary, {"choice": {"citation": {"物理学": "SARIMA模型"}},
                         "by": "librarian", "at": "2026-09-27 10:00:00"})
        snap = forecast_choice.snapshot(
            "202609", choices_dir=out / "_forecast_choices", out_dir=out,
            snapshot_at="2026-09-27 10:01:00")
        assert snap["request_period"] == "202609"
        assert snap["choice_period"] == "202609"
        assert snap["snapshot_source"] == "primary"
        assert snap["snapshot_source_path"] == "_forecast_choices/202609.json"
        assert snap["snapshot_at"] == "2026-09-27 10:01:00"

        _write(primary, {"choice": {}, "by": "later", "at": "later"})
        assert snap["choice"] == {"citation": {"物理学": "SARIMA模型"}}

    def test_应用到输出期次并补齐留痕(self, tmp_path):
        snap_path = tmp_path / "_jobs" / "job-1" / forecast_choice.CHOICE_FILE
        _write(snap_path, {"request_period": "202610", "choice_period": "202610",
                           "choice": {"citation": {"物理学": "SARIMA模型"}},
                           "by": "librarian", "at": "2026-09-27 10:00:00"})
        out_dir = tmp_path / "out" / "202612"
        target = forecast_choice.apply_snapshot(snap_path, out_dir, "202612")
        record = json.loads(target.read_text(encoding="utf-8"))
        assert target.name == forecast_choice.APPLIED_FILE
        assert record["request_period"] == "202610"
        assert record["choice_period"] == "202610"
        assert record["source_period"] == "202612"
        assert record["output_period"] == "202612"
        assert record["operator"] == "librarian"
        assert record["config_updated_at"] == "2026-09-27 10:00:00"

    def test_坏快照抛ValueError(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="形状无效"):
            forecast_choice.apply_snapshot(bad, tmp_path, "202609")

        missing_period = tmp_path / "np.json"
        _write(missing_period, {"choice": {}})
        with pytest.raises(ValueError, match="缺少请求期次"):
            forecast_choice.apply_snapshot(missing_period, tmp_path, "202609")

        unreadable = tmp_path / "broken.json"
        unreadable.write_text("{坏", encoding="utf-8")
        with pytest.raises(ValueError, match="读取失败"):
            forecast_choice.apply_snapshot(unreadable, tmp_path, "202609")


class Test宽松读取:
    def test_primary与legacy同序(self, tmp_path):
        """直接跑流水线（无 applied 快照）也要按服务端读序拿到 primary 的选择。"""
        out = tmp_path / "out"
        period = "202609"
        _write(out / "_forecast_choices" / f"{period}.json",
               {"choice": {"citation": {"物理学": "SARIMA模型"}}})
        picked, warnings = forecast_choice.load(out / period)
        assert picked == {("citation", "物理学"): "SARIMA模型"}
        assert warnings == []

    def test_旧扁平形状整份忽略(self, tmp_path):
        period_dir = tmp_path / "out" / "202609"
        _write(period_dir / forecast_choice.CHOICE_FILE,
               {"choice": {"Chemistry": "SARIMA模型"}})
        picked, warnings = forecast_choice.load(period_dir)
        assert picked == {}
        assert len(warnings) == 1 and "旧扁平形状" in warnings[0]

    def test_未知路线与模型逐条忽略(self, tmp_path):
        period_dir = tmp_path / "out" / "202609"
        _write(period_dir / forecast_choice.CHOICE_FILE,
               {"choice": {"cites": {"物理学": "SARIMA模型"},
                           "citation": {"物理学": "不存在的模型"}}})
        picked, warnings = forecast_choice.load(period_dir)
        assert picked == {}
        assert len(warnings) == 2

    def test_显式路径只读它(self, tmp_path):
        period_dir = tmp_path / "out" / "202609"
        _write(period_dir / forecast_choice.CHOICE_FILE,
               {"choice": {"citation": {"物理学": "all"}}})
        applied = tmp_path / forecast_choice.APPLIED_FILE
        _write(applied, {"choice": {"rank": {"物理学": "SARIMA模型"}}})
        picked, warnings = forecast_choice.load(period_dir, choice_path=applied)
        assert picked == {("rank", "物理学"): "SARIMA模型"}
        assert warnings == []

    def test_BOM可读(self, tmp_path):
        period_dir = tmp_path / "out" / "202609"
        period_dir.mkdir(parents=True)
        (period_dir / forecast_choice.CHOICE_FILE).write_text(
            json.dumps({"choice": {"citation": {"物理学": "SARIMA模型"}}}),
            encoding="utf-8-sig")
        picked, warnings = forecast_choice.load(period_dir)
        assert picked == {("citation", "物理学"): "SARIMA模型"}
        assert warnings == []

    def test_读取失败记警告(self, tmp_path):
        period_dir = tmp_path / "out" / "202609"
        period_dir.mkdir(parents=True)
        (period_dir / forecast_choice.CHOICE_FILE).write_text("{坏", encoding="utf-8")
        picked, warnings = forecast_choice.load(period_dir)
        assert picked == {}
        assert len(warnings) == 1 and "读取失败" in warnings[0]


class Test留痕:
    def test_应用快照的留痕字段(self, tmp_path):
        period_dir = tmp_path / "out" / "202612"
        applied = period_dir / forecast_choice.APPLIED_FILE
        _write(applied, {"choice": {"citation": {"物理学": "SARIMA模型"}},
                         "request_period": "202610", "choice_period": "202610",
                         "source_period": "202612", "output_period": "202612",
                         "config_updated_at": "2026-09-27 10:00:00",
                         "operator": "librarian",
                         "snapshot_at": "2026-09-27 10:01:00",
                         "snapshot_source": "primary"})
        prov = forecast_choice.provenance(period_dir, "202612", choice_path=applied)
        assert prov["request_period"] == "202610"
        assert prov["choice_period"] == "202610"
        assert prov["source_period"] == "202612"
        assert prov["output_period"] == "202612"
        assert prov["operator"] == "librarian"
        assert prov["config_updated_at"] == "2026-09-27 10:00:00"
        assert prov["snapshot_at"] == "2026-09-27 10:01:00"
        assert prov["snapshot_source"] == "primary"

    def test_无文件回落数据期次(self, tmp_path):
        period_dir = tmp_path / "out" / "202609"
        period_dir.mkdir(parents=True)
        prov = forecast_choice.provenance(period_dir, "202609")
        assert prov["request_period"] == "202609"
        assert prov["choice_period"] == "202609"
        assert prov["source_period"] == "202609"
        assert prov["output_period"] == "202609"
        assert prov["operator"] == "" and prov["snapshot_source"] == ""


class Test严格校验与常量:
    def test_validate_合法(self):
        ok, error = forecast_choice.validate(
            {"citation": {"物理学": "SARIMA模型"}}, subjects={"物理学"})
        assert ok and error == ""

    def test_validate_拒绝路线学科与模型(self):
        subjects = {"物理学"}
        for bad in ({"unknown": {"物理学": "SARIMA模型"}},
                    {"citation": {"不存在的学科": "SARIMA模型"}},
                    {"citation": {"物理学": "不存在的模型"}},
                    {"citation": []}):
            ok, error = forecast_choice.validate(bad, subjects=subjects)
            assert not ok and error

    def test_server常量与module一致(self):
        """server/forecasting 的展示表与 module 常量必须同值，防两处各自漂移。"""
        from server import forecasting
        assert set(forecast_choice.ROUTES) == {r["value"] for r in forecasting.ROUTES}
        assert set(forecast_choice.VALID_MODELS) == \
            {m["value"] for m in forecasting.MODEL_OPTIONS}
