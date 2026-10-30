# -*- coding: utf-8 -*-
"""`charts.chart_multi_line`（多系列折线）的验收用例。

这个图型是**纯追加**的（他校简报要一张「各校 × 各期」的折线），所以这里守两件事：

1. **新图型**：确定性、缺数据不连线、事件点进图例、坏事件不炸；
2. **老图型一个字节没动**：既有 11 个图型的**签名**逐个锁死（改名/挪位置/加必填参数
   都会红），再拿 `chart_cnci` 实拍两次验字节稳定。这条是「只许追加可选参数、
   默认值＝原行为」的落地判据——复刻报告的 PNG 哈希就是靠它不被打翻的。
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

import charts

PERIODS = ["202511", "202601", "202603"]

#: 既有图型的签名快照（参数名 + 顺序）。**只许追加 `*` 之后的可选参数**，
#: 改这里等于改复刻报告的出图口径 —— 先跑全套图表验收再动。
FROZEN = {
    "chart_rank_pct": ("rank_intl", "rank_cn", "disc", "out_png", "periods", "invert"),
    "chart_cnci": ("cnci", "disc", "out_png", "periods", "include"),
    "chart_papers_delta": ("papers", "disc", "out_png", "periods", "zero_base"),
    "chart_cites_threshold": ("cites", "threshold", "disc", "out_png", "periods",
                              "zero_base", "include"),
    "chart_top_papers": ("top", "disc", "out_png", "periods", "floor_zero"),
    "chart_q_dist": ("q1q4", "disc", "out_png", "period", "floor_zero"),
    "chart_rank_table": ("ynd_rank", "out_png", "end_period", "n"),
    "chart_ynd_rank": ("ynd_rank", "out_png", "end_period", "n"),
    "chart_trend_table": ("cites", "thr_1permille", "out_png", "end_period", "n",
                          "top_k", "entered"),
    "chart_top_by_year": ("by_year", "out_png", "period"),
    "chart_top_by_subject": ("top_papers", "out_png", "period"),
    "chart_college_pie": ("stats", "out_png", "mode"),
    "chart_overview_1pct": ("cites", "threshold", "out_png", "period"),
    "chart_overview_1pct_v0": ("cites", "threshold", "out_png", "period"),
    "chart_overview_1permille": ("cites", "thr_1permille", "entered_1pct", "out_png", "period"),
    "chart_forecast": ("hist_periods", "hist", "model_hist", "fut_periods", "fut",
                       "labels", "colors", "out_png", "grid", "figsize"),
}


def _series() -> dict:
    return {"昆明理工大学": [12] * 3, "海南大学": [9, 10, 11]}


def _events() -> list:
    return [
        {"school": "海南大学", "index": 2, "value": 11, "kind": "enter"},
        {"school": "昆明理工大学", "index": 2, "value": 12, "kind": "overtake"},
        {"school": "昆明理工大学", "index": 2, "value": 12, "kind": "flat"},
    ]


# ------------------------------------------------------------------ 老图型：只许追加

@pytest.mark.parametrize("name,params", sorted(FROZEN.items()))
def test_既有图型签名未变(name, params):
    got = tuple(inspect.signature(getattr(charts, name)).parameters)
    assert got == params, f"{name} 的签名变了，复刻报告出图会跟着变"


def test_既有图型同输入逐字节一致(tmp_path):
    """不传任何新参数时，老图型的产出稳定（同一进程两次实拍字节相同）。"""
    df = pd.DataFrame({"202511": [1.20], "202601": [1.31], "202603": [1.44]},
                      index=["Chemistry"])
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    charts.chart_cnci(df, "Chemistry", a, PERIODS)
    charts.chart_cnci(df, "Chemistry", b, PERIODS)
    assert a.read_bytes() == b.read_bytes()


# ------------------------------------------------------------------ 新图型

def test_多系列折线_出图且确定性(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    charts.chart_multi_line(_series(), a, PERIODS)
    charts.chart_multi_line(_series(), b, PERIODS)
    assert a.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert a.read_bytes() == b.read_bytes()


def test_多系列折线_默认参数等于显式传None(tmp_path):
    """可选参数的默认值必须等于「什么都不加」——否则「默认＝原行为」不成立。"""
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    charts.chart_multi_line(_series(), a, PERIODS)
    charts.chart_multi_line(_series(), b, PERIODS, events=None, kind_labels=None)
    assert a.read_bytes() == b.read_bytes()


def test_多系列折线_缺数据不连线也不炸(tmp_path):
    out = tmp_path / "gap.png"
    charts.chart_multi_line({"甲校": [1, None, 3], "乙校": [None, None, None]}, out, PERIODS)
    assert out.is_file() and out.stat().st_size > 0


def test_多系列折线_事件进图例且同坐标只留一个(tmp_path):
    """`flat` 与 `overtake` 撞在同一坐标时只画叉：方块盖住叉会让读者以为图上没有交叉。"""
    out = tmp_path / "ev.png"
    charts.chart_multi_line(_series(), out, PERIODS, events=_events(),
                            kind_labels={"enter": "新进", "overtake": "名次交叉",
                                         "flat": "持平"})
    assert out.is_file() and out.stat().st_size > 0


def test_多系列折线_坏事件静默跳过(tmp_path):
    """事件表是辅助信息，坏了不能把整张图带崩。"""
    out = tmp_path / "bad.png"
    charts.chart_multi_line(
        _series(), out, PERIODS,
        events=[{"school": "查无此校", "index": 0, "value": 1, "kind": "enter"},
                {"school": "海南大学", "index": 99, "value": 1, "kind": "enter"},
                {"school": "海南大学", "index": 0, "value": None, "kind": "flat"},
                {"school": "海南大学", "index": "x", "value": 1, "kind": "flat"}])
    assert out.is_file() and out.stat().st_size > 0


def test_多系列折线_空输入不炸(tmp_path):
    out = tmp_path / "empty.png"
    charts.chart_multi_line({}, out, [])
    assert out.is_file() and out.stat().st_size > 0
