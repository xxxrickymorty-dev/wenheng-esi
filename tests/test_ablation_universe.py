# -*- coding: utf-8 -*-
"""消融实验数字化白名单：人工填写读**状态库**，不读 `manual_inputs.json`。

2026-10-22 起填写内容在 `manual_inputs` 表（schema 003），磁盘上那份文件停写停读、只是导出件。
`build_universe()` 原先扫文件——文件还在，所以**不报错，只会慢慢失效**（新填的值永远进不了
白名单）。这条用例钉住「库是真相源」：库里填了 → 白名单有；只改文件 → 白名单没有。
"""
import json

import pytest

import ablation_qa
from src import state_store


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    """一期目录 + 指到 tmp 的状态库（不碰仓库里那份，`db_path` 解得 `<out>/../_state`）。"""
    d = tmp_path / "out" / "202607"
    d.mkdir(parents=True)
    monkeypatch.setenv(state_store.ENV_VAR, str(tmp_path / "out" / "_state" / state_store.DB_NAME))
    return d


def _export_file(out_dir, data):
    """按 `state_export` 的写法落一份导出件（indent=1、中文不转义）。"""
    (out_dir / "manual_inputs.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def test_fills_are_read_from_state_store(out_dir):
    """库里填的 19 进白名单；导出件里的旧值 7 不进（读文件就会反过来）。"""
    db = state_store.db_path(out_dir)
    state_store.set_fill(db, "202607", "正文/p4::学科数",
                         {"value": "19", "by": "馆员", "at": "2026-10-22 09:00:00"})
    _export_file(out_dir, {"正文/p4::学科数": {"value": "7", "by": "馆员",
                                              "at": "2026-10-19 14:48:00"}})

    fills = ablation_qa.fill_records(out_dir, "202607")
    assert fills == {"正文/p4::学科数": {"value": "19", "by": "馆员",
                                        "at": "2026-10-22 09:00:00"}}

    universe = set()
    ablation_qa.walk_numbers(fills, universe)
    assert ablation_qa.num_forms(19.0) <= universe, "库里填的值必须在白名单里"
    assert not (ablation_qa.num_forms(7.0) & universe), "导出件里的旧值不该被读到"


def test_file_only_fill_is_not_in_universe(out_dir):
    """只改文件、库里没有 → 白名单不含它（这就是原先那条会静默失效的读路径）。"""
    _export_file(out_dir, {"正文/province_p::总数": {"value": "42", "by": "馆员",
                                                     "at": "2026-10-22 09:00:00"}})

    fills = ablation_qa.fill_records(out_dir, "202607")
    assert fills == {}, "库里没有就不该有内容（读口也不该顺手建库）"
    universe = set()
    ablation_qa.walk_numbers(fills, universe)
    assert not (ablation_qa.num_forms(42.0) & universe)
    assert not (state_store.db_path(out_dir)).exists(), "读口不造库"
