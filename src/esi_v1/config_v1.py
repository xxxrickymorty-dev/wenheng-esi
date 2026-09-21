# -*- coding: utf-8 -*-
"""ESI 模型工作流 V1 固定配置。

任何关键参数、模型结构、评价规则发生变化，都必须升级版本号；
不要直接覆盖 V1。
"""

MODEL_PACKAGE_VERSION = "V1.0"
CITATION_TASK_VERSION = "V1-Citation"
RANK_TASK_VERSION = "V1-Rank"

SEASONAL_PERIODS = 6
INITIAL_TRAIN_SIZE = 30
FIT_MAPE_START_INDEX = 6

MODEL_NAMES = [
    "Holt趋势模型",
    "阻尼Holt模型",
    "季节性ETS模型",
    "SARIMA模型",
    "经验贝叶斯状态空间模型",
]

SARIMA_ORDERS = [
    (0, 1, 1),
    (1, 1, 0),
    (1, 1, 1),
]

SARIMA_SEASONAL_ORDERS = [
    (0, 0, 0, SEASONAL_PERIODS),
    (1, 0, 0, SEASONAL_PERIODS),
    (0, 0, 1, SEASONAL_PERIODS),
    (1, 0, 1, SEASONAL_PERIODS),
]

REFERENCE_MAPE_PERCENT = 5.0

COLUMN_ALIASES = {
    "学科中文": "学科",
    "学科名称": "学科",
    "ESI1%学科数": "国内ESI前1%机构数",
    "ESI5%学科数": "国内ESI前1%机构数",
}

BASELINE_RECOMMENDATIONS_202607 = {
    "citation": {
        "分子生物学与遗传学": "季节性ETS模型",
        "物理学": "经验贝叶斯状态空间模型",
        "经济与商业": "SARIMA模型",
        "免疫学": "季节性ETS模型",
        "神经科学与行为科学": "季节性ETS模型",
        "精神病学与心理学": "经验贝叶斯状态空间模型",
        "空间科学": "SARIMA模型",
        "多学科": "Holt趋势模型",
    },
    "rank": {
        "分子生物学与遗传学": "阻尼Holt模型",
        "物理学": "经验贝叶斯状态空间模型",
        "经济与商业": "阻尼Holt模型",
        "免疫学": "阻尼Holt模型",
        "神经科学与行为科学": "SARIMA模型",
        "精神病学与心理学": "SARIMA模型",
        "空间科学": "SARIMA模型",
        "多学科": "阻尼Holt模型",
    },
}
