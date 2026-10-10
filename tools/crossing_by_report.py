# -*- coding: utf-8 -*-
"""按两份报告各自指定的「最优模型」计算预计过线时间，产出可直接回填「表11」的单元格文本。

与 `src/forecast_select.py` 的分工：后者按**我们自己的选模结果**选模型；
本脚本按**报告行内已写明的模型**算，保证同一行「最优模型」与「预计过线时间」自洽。

用法：uv run python tools/crossing_by_report.py [out/202607]

回填口径（2026-09-16 定）：
  过线  →  `{最可能}（{最早}～{最晚}）`；最晚未在窗内出现时写 `2030-07+`
  未过线 →  `2030-07 前未过线`
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import forecast_select as fs  # noqa: E402

OUT = "out/202607"

# 报告用词 → 模块模型名
NAME_MAP = {
    "季节性ETS模型": "季节性ETS",
    "经验贝叶斯状态空间模型": "经验贝叶斯状态空间",
    "SARIMA模型": "SARIMA",
    "阻尼Holt模型": "阻尼Holt",
    "阻尼Holt模型（临时基线）": "阻尼Holt",
    "Holt趋势模型": "Holt",
}

EN = {
    "分子生物学与遗传学": "Molecular Biology & Genetics",
    "物理学": "Physics",
    "经济与商业": "Economics & Business",
    "免疫学": "Immunology",
    "神经科学与行为科学": "Neuroscience & Behavior",
    "精神病学与心理学": "Psychiatry/Psychology",
    "空间科学": "Space Science",
    "多学科": "Multidisciplinary",
}

# 报告① 表11（被引维度）
R1 = [
    ("分子生物学与遗传学", "季节性ETS模型"),
    ("物理学", "经验贝叶斯状态空间模型"),
    ("经济与商业", "SARIMA模型"),
    ("免疫学", "季节性ETS模型"),
    ("神经科学与行为科学", "季节性ETS模型"),
    ("精神病学与心理学", "经验贝叶斯状态空间模型"),
    ("空间科学", "SARIMA模型"),
    ("多学科", "Holt趋势模型"),
]

# 报告② 表11（排名维度）
R2 = [
    ("分子生物学与遗传学", "阻尼Holt模型"),
    ("物理学", "经验贝叶斯状态空间模型"),
    ("经济与商业", "阻尼Holt模型"),
    ("免疫学", "阻尼Holt模型"),
    ("神经科学与行为科学", "SARIMA模型"),
    ("精神病学与心理学", "SARIMA模型"),
    ("空间科学", "SARIMA模型"),
    ("多学科", "阻尼Holt模型（临时基线）"),
]


def main(out_dir=OUT):
    series = fs.load_series(out_dir)
    for tag, rows, dim_name in (("报告①被引维度", R1, "被引维度"),
                                ("报告②排名维度", R2, "排名维度")):
        dim = fs.DIMS[dim_name]
        print(f"\n=== {tag} ===")
        print(f"{'学科':<14} {'报告模型':<16} {'当前':>8} {'最早':>9} {'最可能':>9} {'最晚':>9}  单元格文本")
        for zh, rep_model in rows:
            d = EN[zh]
            model = NAME_MAP[rep_model]
            ct = fs.crossing_time(series[d], dim, model)
            f = lambda p: f"{p[:4]}-{p[4:]}" if isinstance(p, str) else "—"
            win_end = f"{ct['horizon_end'][:4]}-{ct['horizon_end'][4:]}"
            upper = f(ct["latest"]) if ct["latest"] else win_end + "+"
            cell = (f"{f(ct['likely'])}（{f(ct['earliest'])}～{upper}）"
                    if ct["likely"] else f"{win_end} 前未过线")
            print(f"{zh:<14} {model:<16} {ct['cur_ratio']*100:>7.2f}% "
                  f"{f(ct['earliest']):>9} {f(ct['likely']):>9} {f(ct['latest']):>9}  {cell}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else OUT)
