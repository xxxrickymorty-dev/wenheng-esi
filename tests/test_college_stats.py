# -*- coding: utf-8 -*-
"""学院统计（论文清单解析）回归：机构名别名合并 + 口径版本化缓存。

钉的是 2026-09-24 对照出版件发现的真问题：
  清单里「天文研究所」与「中国（西南）天文研究所」各占一行 → 报告出现两行；
  出版件是一行 **6 篇 / 625 引**。别名表在 `college_stats.UNIT_ALIAS`。
"""
from __future__ import annotations

import json
import pathlib
import sys

import openpyxl

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO / "src"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import college_stats as cs                                        # noqa: E402

HDR = ["序号", "WOS收录号", "被引频次", "ESI学科", "出版年", "云大作者", "热点论文"]
ROWS = [
    [1, "W1", 617, "Physics", 2025, "Zhu, Lei//天文研究所", ""],
    [2, "W2", 8, "Physics", 2025, "Li, Wei//中国（西南）天文研究所", ""],
    [3, "W3", 10, "Chemistry", 2025, "Wang//化学科学与工程学院", ""],
]


def _make_list(tmp_path, name="202609论文清单.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HDR)
    for r in ROWS:
        ws.append(r)
    p = pathlib.Path(tmp_path) / name
    wb.save(p)
    return p


def test_同一机构两种写法合并成一行(tmp_path):
    st = cs.parse(_make_list(tmp_path))
    units = {u["unit"]: (u["papers"], u["cites"]) for u in st["units"]}
    assert units["中国（西南）天文研究所"] == (2, 625), "别名没合并"
    assert "天文研究所" not in units
    assert st["n_papers"] == 3 and st["n_cites"] == 635


def test_口径版本不同的缓存会重解析(tmp_path, monkeypatch):
    d = pathlib.Path(tmp_path) / "202609"
    d.mkdir()
    p = _make_list(tmp_path)
    # find_list 会先命中仓库里的 input/202609（真清单）→ 测试里必须把它钉到合成件上
    monkeypatch.setattr(cs, "find_list", lambda *a, **k: p)
    # 老版本缓存（parser=1）里写一对脏数：load 不能直接吃
    (d / "college_stats.json").write_text(
        json.dumps({"parser": 1, "units": [], "n_papers": 999, "n_cites": 999},
                   ensure_ascii=False), encoding="utf-8")
    st = cs.load(d, "202609", save=True)
    assert st["n_papers"] == 3, "旧口径缓存被当成新数据用了"
    assert json.loads((d / "college_stats.json").read_text(encoding="utf-8"))["parser"] \
        == cs._PARSER_VERSION
