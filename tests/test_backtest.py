# -*- coding: utf-8 -*-
"""backtest（逐格回测）纯函数层回归：表头语义对齐 / 数字归一 / 比较 / 期次推断 / 概述锚点。

这些纯函数承载过三起实事故，全部要钉住：
① 符号方向丢失：↑↓ 只删不转 → 负号丢，202603/202605 各误报 3 行（见 _num docstring）；
② 写死列索引 / 写死 202607 具体数字 → 换期次必假报（2026-09-18 改语义对齐）；
③ 1‰ 锚点不带「前1‰」语境会抓到单学科段的「前1%接近度」（曾误报）。

main() 端到端依赖真实台账与人工原件，不在本文件（端到端口径归 tools/verify_report_cells.py）。
"""
import pathlib
import sys

import pandas as pd
import pytest
from docx import Document

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import backtest  # noqa: E402


# ---------------------------------------------------------------- _num / _norm_header

def test_num_箭头必须转为正负号():
    # 事故①的回归锚点：机器稿 fmt_pct_change 出 ↑/↓，原件写 +/-，方向不能丢
    assert backtest._num("↑2.49%") == 2.49
    assert backtest._num("↓2.49%") == -2.49
    assert backtest._num("+2.49%") == 2.49
    assert backtest._num("-2.49%") == -2.49


def test_num_千分位逗号与空格():
    assert backtest._num("1,234") == 1234
    assert backtest._num("1，234") == 1234        # 全角逗号
    assert backtest._num(" 42 ") == 42


def test_num_空与占位符表原件未填():
    for s in ("", "-", "—", "–", "－", "/", "\\", None):
        assert backtest._num(s) is None, s


def test_num_非数字串():
    assert backtest._num("abc") is None
    assert backtest._num("12.5") == 12.5


def test_norm_header_去空白换行全角空格():
    assert backtest._norm_header("ESI 学科\n排名　（1%）") == "ESI学科排名（1%）"
    assert backtest._norm_header(None) == ""
    assert backtest._norm_header("  ") == ""


# ---------------------------------------------------------------- _map_headers（列语义）

def test_第4期表头全量对齐():
    header = ["ESI学科", "国内排名/变化", "论文数", "CNCI值", "总被引频次", "1%阈值",
              "1%阈值差", "1‰阈值", "千分位", "顶尖论文", "接近度变化（较5月）"]
    mapping, unknown = backtest._map_headers(header)
    assert set(mapping) == {"rank_cn_change", "papers", "cnci", "total_cites", "thr_1pct",
                            "thr_1pct_gap", "thr_1permille", "permille_rank", "top_papers",
                            "prox_change"}
    assert mapping["prox_change"] == 10          # 「接近度变化（较5月）」按前缀识别
    assert unknown == []


def test_第1_2期表头_阈值旧称与口径演进列():
    header = ["ESI学科", "阈值", "与ESI前1%阈值差", "篇均被引", "顶尖论文",
              "高被引论文", "热点论文", "国内排名/变化", "接近度变化（较11月）"]
    mapping, unknown = backtest._map_headers(header)
    assert mapping["thr_1pct"] == 1              # 旧称「阈值」
    assert mapping["thr_1pct_gap"] == 2          # 旧称「与ESI前1%阈值差」
    assert mapping["cites_per_paper"] == 3       # 「篇均被引」
    # 高被引/热点是台账外人工列 → 记「口径演进」而非差异
    assert [h for _i, h in unknown] == ["高被引论文", "热点论文"]


def test_第3期表头_引文影响力同义篇均被引():
    mapping, _u = backtest._map_headers(["ESI学科", "引文影响力", "CNCI"])
    assert mapping["cites_per_paper"] == 1
    assert mapping["cnci"] == 2                  # 「CNCI」不带「值」也要认


def test_重复表头只认第一列_第二列进unknown():
    mapping, unknown = backtest._map_headers(["ESI学科", "论文数", "论文数"])
    assert mapping["papers"] == 1
    assert unknown == [(2, "论文数")]


def test_学科列被跳过():
    mapping, unknown = backtest._map_headers(["学科", "论文数"])
    assert "papers" in mapping
    assert unknown == []


# ---------------------------------------------------------------- _norm_rank / _mine_fmt / _cmp

def test_norm_rank_抹平写法差异():
    assert backtest._norm_rank("上升2") == "↑2"
    assert backtest._norm_rank("下降 3") == "↓3"
    assert backtest._norm_rank("↑2") == "↑2"
    assert backtest._norm_rank("") == ""


def test_mine_fmt_篇均被引现算_四舍六入到6位():
    row = {"total_cites": 100, "papers": 3}
    assert backtest._mine_fmt("cites_per_paper", row) == round(100 / 3, 6)


def test_mine_fmt_各类型归一():
    assert backtest._mine_fmt("rank_cn_change", {"rank_cn_change": "上升2"}) == "↑2"
    assert backtest._mine_fmt("top_papers", {"top_papers": "  "}) is None
    assert backtest._mine_fmt("top_papers", {"top_papers": 5}) == 5.0
    assert backtest._mine_fmt("cnci", {"cnci": 1.23456789}) == 1.234568
    assert backtest._mine_fmt("prox_change", {"prox_change": "↓2.49%"}) == -2.49
    assert backtest._mine_fmt("papers", {"papers": float("nan")}) is None
    assert backtest._mine_fmt("papers", {"papers": None}) is None


def test_cmp_数值容差含边界():
    _f, _p, tol = None, None, 0.006
    assert backtest._cmp("cnci", 1.0, "1.004", tol)[0] is True
    assert backtest._cmp("cnci", 1.0, "1.006", tol)[0] is True       # 恰好在容差上
    assert backtest._cmp("cnci", 1.0, "1.0061", tol)[0] is False
    assert backtest._cmp("cnci", 0.0, "0.0", tol)[0] is True


def test_cmp_空值三种情形():
    assert backtest._cmp("cnci", None, "—", 0)[0] is None            # 两边皆空
    assert backtest._cmp("cnci", 1.0, "—", 0)[0] is None             # 原件未填 → 不可判
    ok, note = backtest._cmp("cnci", None, "5", 0)                   # 计算空原件有 → 差异
    assert ok is False and "计算=空" in note


def test_cmp_排名变化先归一再比():
    assert backtest._cmp("rank_cn_change", "↑2", "上升2", None)[0] is True
    assert backtest._cmp("rank_cn_change", "↑2", "下降2", None)[0] is False
    assert backtest._cmp("rank_cn_change", "↑2", "", None)[0] is None


# ---------------------------------------------------------------- 期次推断

def test_detect_period_从目录名取期次():
    assert backtest.detect_period_from_dir("out/202601_复现") == "202601"
    assert backtest.detect_period_from_dir(r"D:\x\out\202605") == "202605"
    assert backtest.detect_period_from_dir("out/试跑") is None


def _wide(df_cols):
    return {"total_cites": pd.DataFrame(df_cols)}


def test_prev_period_取最近的有效期次():
    wide = _wide({"202601": [1.0, 2.0], "202603": [None, None], "202605": [3.0, 4.0],
                  "备注": ["a", "b"]})
    # 202603 全空 → 跳过；非数字列不参与
    assert backtest.prev_period(wide, "202605") == "202601"
    assert backtest.prev_period(wide, "202603") == "202601"


def test_prev_period_没有更早期次则退出():
    wide = _wide({"202605": [1.0]})
    with pytest.raises(SystemExit):
        backtest.prev_period(wide, "202605")


# ---------------------------------------------------------------- 概述锚点（语义正则）

def test_锚点_国际排名句式():
    text = "根据2026年5月的ESI数据，我校位于第995位，较上期上升2位。"
    assert backtest._grab(r"我校位于第(\d+)位", text) == ("995",)
    assert backtest._grab(r"我校位于第\d+位[，,]\s*较上期上升(\d+)位", text) == ("2",)


def test_锚点_排名升降持平三连句():
    text = "有12个学科排名上升，3个学科排名下降，7个学科排名与上月持平。"
    assert backtest._grab(r"有(\d+)个学科排名上升", text) == ("12",)
    assert backtest._grab(r"(\d+)个学科排名下降", text) == ("3",)
    assert backtest._grab(r"(\d+)个学科排名与\S+持平", text) == ("7",)


def test_锚点_千分位接近度必须带语境_不得误抓前百分之一():
    pat = r"前1‰接近度较高的学科为\S+?，接近度为([\d.]+)%"
    good = "其中前1‰接近度较高的学科为植物与动物科学，接近度为38.52%，位列全球第9。"
    bad = "某学科ESI前1%接近度为66.96%，保持稳定。"          # 事故③：1% ≠ 1‰
    assert backtest._grab(pat, good) == ("38.52",)
    assert backtest._grab(pat, bad) is None
    name = backtest._grab(r"前1‰接近度较高的学科为(\S+?)，接近度", good)
    assert name == ("植物与动物科学",)


def test_锚点_顶尖论文增减措辞():
    text = "本期我校共有274篇顶尖论文，较上期总数增加12篇。"
    assert backtest._grab(r"本期我校共有(\d+)篇顶尖论文", text) == ("274",)
    assert backtest._grab(r"较上期总数(增加|减少)(\d+)篇", text) == ("增加", "12")


# ---------------------------------------------------------------- load_doc_tables

def _save_doc(tmp_path, tables_rows, name="t.docx"):
    d = Document()
    for rows in tables_rows:
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                t.rows[i].cells[j].text = v
    p = tmp_path / name
    d.save(p)
    return p


def test_load_doc_tables_按表头语义挑大表和省表(tmp_path):
    big = [["ESI学科", "论文数", "总被引频次"], ["工程学", "123", "4567"]]
    decoy = [["说明", "备注"], ["x", "y"]]
    prov = [["机构名称", "国内排名", "国际排名"], ["云南大学", "196", "995"]]
    p = _save_doc(tmp_path, [decoy, big, prov])
    _d, got_big, got_prov = backtest.load_doc_tables(p)
    assert got_big.rows[0].cells[0].text.startswith("ESI学科")
    assert got_prov.rows[0].cells[0].text.startswith("机构名称")


def test_load_doc_tables_无语义表头时回退到宽表(tmp_path):
    t1 = [[f"c{j}" for j in range(11)]]
    t2 = [[f"d{j}" for j in range(11)]]
    p = _save_doc(tmp_path, [t1, t2])
    _d, big, prov = backtest.load_doc_tables(p)
    assert big.rows[0].cells[0].text == "c0"          # 第一个 ≥10 列
    assert prov.rows[0].cells[0].text == "d0"         # 第二个 ≥10 列


def test_load_doc_tables_只有一个宽表_省表为None(tmp_path):
    t1 = [["ESI学科"] + [f"c{j}" for j in range(10)], ["工程学"] + ["1"] * 10]
    p = _save_doc(tmp_path, [t1])
    _d, big, prov = backtest.load_doc_tables(p)
    assert big is not None and prov is None
