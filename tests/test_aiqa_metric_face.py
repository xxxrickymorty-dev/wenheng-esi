# -*- coding: utf-8 -*-
"""指标脸面表唯一口径（20261101 施工单 C5）＋ 单行渲染口。

钉四件事：
① `metric_face.FACE` 是三张旧表的唯一数据源：问数别名表（原 `aiqa_engine._METRIC_ALIAS`
   的 37 对）逐条重建自 FACE 的 `ask` 列；`_plan.MODEL_METRICS` 是 FACE 模型面行的
   视图，顺序与内容逐条钉死；
② `_qa._metric_index` 的短名/话术全部来自 FACE 且**零数字**（工具 schema 红线的根）；
③ `render_row` 单行口：渲染不出的行＝空串，**永不产出整块兜底句**；兜底句只属
   `render_text`（整块口）；
④ 接近度换算单处声明：`metric_face.proximity_pct`（总被引 ÷ 阈值 × 100）。

不依赖真数据——内存 sqlite 装最小 dim 两表，hermetic、离线可跑。
"""
from __future__ import annotations

import pathlib
import re
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import metric_face                                              # noqa: E402
from ai import _plan, _qa                                       # noqa: E402

_FALLBACK = "没有查到匹配的数据"

#: 原字面量表的 37 对（C5 收敛前 `aiqa_engine._METRIC_ALIAS` 的全部内容）——
#: 测试里故意留一份全量拷贝：共享表改了别名而忘了改问法行为，这里会先炸。
_EXPECT_ASK = {
    "总被引": "total_cites", "总被引频次": "total_cites", "被引": "total_cites",
    "被引频次": "total_cites", "引用": "total_cites", "引用频次": "total_cites",
    "论文": "papers", "论文数": "papers", "发文": "papers", "发文量": "papers",
    "cnci": "cnci", "学科规范化的引文影响力": "cnci",
    "接近度": "proximity_1pct", "前1%接近度": "proximity_1pct",
    "esipref1接近度": "proximity_1pct",
    "阈值": "threshold_1pct", "前1%阈值": "threshold_1pct",
    "被引阈值": "threshold_1pct", "前百分之一阈值": "threshold_1pct",
    "顶尖论文": "top_papers", "顶尖论文数": "top_papers",
    "热点论文": "top_papers", "高被引论文": "top_papers", "高被引": "top_papers",
    "千分之一阈值": "threshold_1permille", "前1‰阈值": "threshold_1permille",
    "千分位": "permille_rank",
    "国内排名": "rank", "排名": "rank",
    "国际排名": "rank_intl", "世界排名": "rank_intl",
    "百分位": "rank_pct", "排名百分位": "rank_pct",
    "前1%机构数": "n_inst_1pct", "机构数": "n_inst_1pct",
    "篇均被引": "avg_cites",
}

#: `_plan.MODEL_METRICS` 收敛前的原样（模型面 9 行，顺序即 prompt 词汇顺序）。
_EXPECT_MODEL = (
    ("proximity", "proximity_1pct", "接近度"),
    ("threshold", "threshold_1pct", "前 1% 被引阈值"),
    ("threshold_permille", "threshold_1permille", "前 1‰ 被引阈值"),
    ("total_cites", "total_cites", "总被引频次"),
    ("papers", "papers", "论文数"),
    ("cnci", "cnci", "CNCI"),
    ("top_papers", "top_papers", "顶尖论文"),
    ("rank_cn", "rank_cn", "国内排名"),
    ("rank_intl", "rank_intl", "国际排名"),
)


# ---------------------------------------------------------------- ① 唯一口径
def test_face重建问数别名表_逐对一致():
    got = {alias: row["canon"] for row in metric_face.FACE for alias in row["ask"]}
    assert got == _EXPECT_ASK

    import aiqa_engine
    assert aiqa_engine._METRIC_ALIAS == _EXPECT_ASK, "引擎问法表必须整表重建自 FACE"


def test_model_metrics是face的模型面视图():
    assert _plan.MODEL_METRICS == _EXPECT_MODEL
    assert _plan._ALIAS == {a: c for a, c, _cn in _EXPECT_MODEL}
    # 模型面**别名**零数字（中文名本就带「1%」——短名/话术的存在理由，见 ③）
    for alias, _canon, _cn in _plan.MODEL_METRICS:
        assert not re.search(r"\d", alias), alias


def test_metric_index短名话术全来自face且零数字():
    idx = _qa._metric_index()
    assert set(idx) == {a for a, _c, _cn in _EXPECT_MODEL}
    for alias, (canon, short, hint) in idx.items():
        assert short and hint, alias
        assert not re.search(r"\d", short) and not re.search(r"\d", hint), alias
    assert idx["proximity"] == ("proximity_1pct", "接近度", "接近度（被引与门槛的比值）")
    assert idx["threshold"] == ("threshold_1pct", "前百分之一阈值",
                                "进入前百分之一所需的被引门槛")
    assert idx["cnci"][2] == "篇均被引影响力"


# ---------------------------------------------------------------- ④ 换算单处
def test_接近度换算单处声明():
    assert metric_face.proximity_pct(2, 8) == 25.0
    # 与旧两处实现的算式逐位一致（先除后乘 100；渲染照旧 :.2f）
    for cites, thr in ((9134, 21073), (21073, 23105)):
        assert f"{metric_face.proximity_pct(cites, thr):.2f}" == \
            f"{cites / thr * 100:.2f}"


def test_qa接近度换算走唯一出口():
    src = pathlib.Path(_qa.__file__).read_text(encoding="utf-8")
    assert "proximity_pct" in src
    assert "cites / thr" not in src, "换算应收敛到 metric_face.proximity_pct"


# ---------------------------------------------------------------- ③ 单行渲染口
def _con():
    con = sqlite3.connect(":memory:")
    from aiqa_db import _DDL
    con.executescript(_DDL)
    con.execute("INSERT INTO dim_discipline (discipline, discipline_cn, ord) "
                "VALUES ('Chemistry', '化学', 1)")
    con.execute("INSERT INTO dim_metric (metric, metric_cn, better) "
                "VALUES ('proximity_1pct', 'ESI前1%接近度', 'up')")
    return con


def test_单行口_空行_空串且不漏兜底句():
    from aiqa_engine import render_row

    for row in ({"type": "table2", "period": "202607", "rows": []},
                {"type": "overview", "period": "202607", "facts": {}},
                {"type": "overview", "facts": {"unknown_key": 1}}):
        body = render_row(None, row)
        assert body == "" and _FALLBACK not in body, row


def test_单行口_行渲染与整块口一致_兜底句只属整块口():
    from aiqa_engine import render_row, render_text

    con = _con()
    try:
        series = {"type": "series", "metric": "proximity_1pct", "disc": "Chemistry",
                  "points": [{"period": "202607", "value": 0.512},
                             {"period": "202609", "value": 0.548}]}
        empty = {"type": "overview", "period": "202607", "facts": {}}
        assert render_row(con, series) == render_text(con, "", {"rows": [series]})
        # 多行结果＝各行拼接；渲染不出的行不占位
        assert render_text(con, "", {"rows": [series, empty]}) == render_row(con, series)
        # 兜底句只在整块口、且只在整块空结果时出现
        assert _FALLBACK in render_text(con, "", {"rows": []})
        assert _FALLBACK not in render_row(con, empty)
    finally:
        con.close()
