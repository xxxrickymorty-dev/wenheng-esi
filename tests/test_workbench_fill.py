# -*- coding: utf-8 -*-
"""在线填 → 重出报告 的键一致性与替换语义（2026-09-20）。

这块最容易出的错是**静默失效**：工作台写下的键与 `fill_docx` 查找的键格式
不一致时，人工填了一堆、报告里一个都没变，而两边都不报错。所以这里最重的一条
是「两边键必须对得上」，而不是各自测各自的。

（真跑 docx 的端到端在 `tmp/_wb_verify.py`：幂等 + 填值生效两条性质已实测通过。）
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO / "src"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fill_docx                                                # noqa: E402
from server import workbench                                    # noqa: E402
from src import state_store                                     # noqa: E402


def _row(location, text, source="sentences.py（句骨架+数字槽）"):
    return {"location": location, "old": "", "new": text[:50],
            "new_full": text, "source": source}


# ============================================================ ① 键一致性（最重要）
def test_工作台写的键与fill_docx查的键对得上():
    """两边各写一套 key 格式 → 填了等于没填，且**两边都不报错**。"""
    row = _row("正文/p1", "……【手工：ESI发布日期】……")
    todo = workbench._todo_from_slot(row, 0)
    assert todo and todo[0]["id"] == "正文/p1::ESI发布日期"

    texts = {"p1": "……【手工：ESI发布日期】……"}
    out, n = fill_docx.apply_manual_inputs(
        texts, {todo[0]["id"]: {"value": "2026年9月27日", "by": "t", "at": "t"}})
    assert n == 1, "工作台写的键必须能被 fill_docx 查到，否则是静默失效"
    assert out["p1"] == "……2026年9月27日……"


# ============================================================ ② 替换语义
def test_只替换填过的_其余保留标记():
    texts = {"p1": "A【手工：甲】B【手工：乙】C"}
    out, n = fill_docx.apply_manual_inputs(
        texts, {"正文/p1::甲": {"value": "X", "by": "t", "at": "t"}})
    assert n == 1
    assert out["p1"] == "AXB【手工：乙】C", "没填的必须保留标记，不能抹成空白"


def test_键对不上时不动():
    texts = {"p1": "【手工：甲】"}
    out, n = fill_docx.apply_manual_inputs(
        texts, {"正文/p9::甲": {"value": "X", "by": "t", "at": "t"}})
    assert n == 0 and out["p1"] == "【手工：甲】"


def test_空值视为没填():
    """点了保存但输入框是空的 → 不能把标记吃掉。"""
    texts = {"p1": "【手工：甲】"}
    out, n = fill_docx.apply_manual_inputs(
        texts, {"正文/p1::甲": {"value": "   ", "by": "t", "at": "t"}})
    assert n == 0 and out["p1"] == "【手工：甲】"


def test_不传fills时原样返回():
    texts = {"p1": "【手工：甲】"}
    out, n = fill_docx.apply_manual_inputs(texts, None)
    assert n == 0 and out["p1"] == texts["p1"]


def test_非字符串文本不炸():
    """句骨架里可能有非字符串项（列表/None），替换要跳过而不是崩。"""
    out, n = fill_docx.apply_manual_inputs({"cover": None, "p1": "【手工：甲】"}, {})
    assert out["cover"] is None and n == 0


# ============================================================ ③ id 稳定性
def test_id不依赖序号_行序变了也不串位():
    """序号型 id（fill-3-1）在重跑流水线后会错位到别的格子。"""
    a = workbench._todo_from_slot(_row("正文/p2", "【手工：去年同期升幅%】"), 3)
    b = workbench._todo_from_slot(_row("正文/p2", "【手工：去年同期升幅%】"), 99)
    assert a[0]["id"] == b[0]["id"] == "正文/p2::去年同期升幅%"


def test_一个槽位里的多处标记各成一条():
    row = _row("正文/top_section", "【手工：学科数】【手工：学院数】")
    todo = workbench._todo_from_slot(row, 0)
    assert [t["id"] for t in todo] == ["正文/top_section::学科数",
                                       "正文/top_section::学院数"]


# ============================================================ ④ 填写入库（ADR-0012）
def test_save_fill写状态库不落期次文件(tmp_path):
    """`manual_inputs.json` 已入库（2026-10-21）：写入口只碰库，产品目录不新增文件。"""
    d = tmp_path / "out" / "202609"
    d.mkdir(parents=True)

    rec = workbench.save_fill(d, "正文/p1::甲", "X", by="馆员", at="2026-10-21 10:00:00")
    assert rec == {"ok": True, "id": "正文/p1::甲", "value": "X", "by": "馆员",
                   "at": "2026-10-21 10:00:00", "n_filled": 1}
    assert not (d / "manual_inputs.json").exists(), "期次目录不再落 manual_inputs.json"
    assert workbench.load_fills(d) == {
        "正文/p1::甲": {"value": "X", "by": "馆员", "at": "2026-10-21 10:00:00"}}


def test_三态由产物现场判_库里status不算数(tmp_path):
    """pending / applied / orphan 是**读时算**的：库里那列写什么都改不了页面的判定。"""
    d = tmp_path / "out" / "202609"
    d.mkdir(parents=True)
    rows = [
        _row("正文/p1", "据【手工：ESI发布日期】数据"),      # 标记还在 → 填了但没重出
        _row("正文/p4", "覆盖19个学科"),                    # 标记已被替换 → 已写入报告
    ]
    (d / "red_slots.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    db = state_store.db_path(d)
    fills = {
        "正文/p1::ESI发布日期": {"value": "2026年9月23日", "by": "馆员", "at": "t"},
        "正文/p4::学科数": {"value": "19", "by": "馆员", "at": "t"},
        "正文/p9::学院数": {"value": "7", "by": "馆员", "at": "t"},   # 位置不存在 → 残留
    }
    for slot, rec in fills.items():
        state_store.set_fill(db, d.name, slot, rec, status="applied")   # 故意全写 applied

    data = workbench.build(d)
    assert {f["key"]: f["state"] for f in data["fills_list"]} == {
        "正文/p1::ESI发布日期": "pending",
        "正文/p4::学科数": "applied",
        "正文/p9::学院数": "orphan",
    }
    assert (data["n_filled"], data["n_applied"], data["n_orphan"]) == (2, 1, 1)
