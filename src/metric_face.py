# -*- coding: utf-8 -*-
"""指标脸面表（唯一口径）——别名、规范名、中文名、话术，一行一指标。

谁在吃这张表（20261101 施工单 C5：原三张表——`ai/_plan.MODEL_METRICS`、
`ai/_qa._METRIC_FACE`、`aiqa_engine._METRIC_ALIAS`——收敛于此，数据唯一来源只有一处）：
- `src/ai/_plan.py`：模型面规划词汇（无数字别名 → 规范名 → 中文名）；
  `MODEL_METRICS` 只是本表 `model` 非空行的视图（顺序＝本表顺序）；
- `src/ai/_qa.py`：工具 schema 与回执摘要的短名/话术（零数字面）；
- `src/aiqa_engine.py`：问数问法的中文别名 → 规范名（`ask` 列）。

叶子模块（先例 `shield_primitives.py`）：不 import 任何仓内模块——`ai/` 与
`aiqa_engine` 两个方向都能安全引我，不成环。

两套别名刻意分行不混用：
- `model`＝模型规划面的**无数字别名**（进 prompt 与工具 schema，防盾占位往返的碎边界）；
- `ask`＝问数引擎的中文问法（进 `_metric_of` 的包含匹配，按长度降序防截胡）。
问数库独有指标（`rank` / `rank_pct` / `n_inst_1pct` / `avg_cites` / `permille_rank`）
只有问数别名，中文名在问数库 `dim_metric`（ETL 唯一口径源自
`flexible.datasource.METRICS`），模型规划面（台账口径）不认识它们。

接近度口径（单处声明）：**接近度＝总被引 ÷ 阈值 × 100**（百分数，渲染取两位小数）。
`proximity_pct()` 是 ai 层唯一的换算出口（`ai/_qa.py` 的学科直答段与来源索引同吃）；
charts / fill_docx / monitor 等产物侧另有各自的实现，不在本表管辖。
"""
from __future__ import annotations

#: 一行一个指标。键义：
#: - ``canon``  规范名（引擎/白名单通用键；问数库独有指标也是它的事实键）
#: - ``cn``     中文名（报告口径；问数库独有指标留空——中文名在 dim_metric）
#: - ``short``  短名（进回执摘要，给人看；零数字）
#: - ``hint``   话术（进工具说明，给模型看；零数字）
#: - ``model``  模型面无数字别名；空串＝该指标不进模型规划面
#: - ``ask``    问数引擎的中文问法别名（元组；空＝无问数问法）
FACE = (
    {"canon": "proximity_1pct", "cn": "接近度", "short": "接近度",
     "hint": "接近度（被引与门槛的比值）", "model": "proximity",
     "ask": ("接近度", "前1%接近度", "esipref1接近度")},
    {"canon": "threshold_1pct", "cn": "前 1% 被引阈值", "short": "前百分之一阈值",
     "hint": "进入前百分之一所需的被引门槛", "model": "threshold",
     "ask": ("阈值", "前1%阈值", "被引阈值", "前百分之一阈值")},
    {"canon": "threshold_1permille", "cn": "前 1‰ 被引阈值", "short": "前千分之一阈值",
     "hint": "进入前千分之一所需的被引门槛", "model": "threshold_permille",
     "ask": ("千分之一阈值", "前1‰阈值")},
    {"canon": "total_cites", "cn": "总被引频次", "short": "总被引频次",
     "hint": "总被引频次", "model": "total_cites",
     "ask": ("总被引", "总被引频次", "被引", "被引频次", "引用", "引用频次")},
    {"canon": "papers", "cn": "论文数", "short": "论文数", "hint": "论文数",
     "model": "papers", "ask": ("论文", "论文数", "发文", "发文量")},
    {"canon": "cnci", "cn": "CNCI", "short": "CNCI", "hint": "篇均被引影响力",
     "model": "cnci", "ask": ("cnci", "学科规范化的引文影响力")},
    {"canon": "top_papers", "cn": "顶尖论文", "short": "顶尖论文", "hint": "顶尖论文数",
     "model": "top_papers",
     "ask": ("顶尖论文", "顶尖论文数", "热点论文", "高被引论文", "高被引")},
    {"canon": "rank_cn", "cn": "国内排名", "short": "国内排名", "hint": "国内排名",
     "model": "rank_cn", "ask": ()},
    {"canon": "rank_intl", "cn": "国际排名", "short": "国际排名", "hint": "国际排名",
     "model": "rank_intl", "ask": ("国际排名", "世界排名")},
    # ---- 问数库独有（模型规划面不认识；中文名在 dim_metric）----
    {"canon": "rank", "cn": "", "short": "", "hint": "", "model": "",
     "ask": ("国内排名", "排名")},
    {"canon": "rank_pct", "cn": "", "short": "", "hint": "", "model": "",
     "ask": ("百分位", "排名百分位")},
    {"canon": "n_inst_1pct", "cn": "", "short": "", "hint": "", "model": "",
     "ask": ("前1%机构数", "机构数")},
    {"canon": "avg_cites", "cn": "", "short": "", "hint": "", "model": "",
     "ask": ("篇均被引",)},
    {"canon": "permille_rank", "cn": "", "short": "", "hint": "", "model": "",
     "ask": ("千分位",)},
)


def proximity_pct(cites, thr):
    """接近度（百分数）＝总被引 ÷ 阈值 × 100 —— ai 层唯一换算出口。

    调用方先判空（`thr` 为 0/None 不进来，由既有条件守着）；算式与两处旧实现
    逐位一致（先除后乘 100），渲染侧照旧 `:.2f`。
    """
    return cites / thr * 100
