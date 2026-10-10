# -*- coding: utf-8 -*-
"""只读数据访问层 + **来源链**。

红件（红线）在这里落地：本模块**只读** `out/<期次>/` 下的 parquet，
不 import `openpyxl`、不出现任何写调用。台账 xlsx 一个字节都不碰
（它由 `parse_ledger` 在流水线里读一次，落成 parquet 后此处只消费产物）。

「来源链」是灵活报告可信度的落点：每个数字都带
`{dataset, metric, discipline, period, origin_sheet}`，
与复刻报告的红件清单同构，可指回台账的工作表与期次列。
"""
from __future__ import annotations

import pathlib

import pandas as pd

#: 允许查询的指标白名单 —— 同时也是「LLM 能看到的字段字典」。
#: 键＝对外指标名；值＝(中文名, 台账工作表, 方向说明)
#: 方向说明用于让规划器知道「哪个方向算好」（如 rank 越小越好）。
METRICS: dict[str, dict] = {
    "total_cites": {"cn": "总被引频次", "sheet": "总被引", "better": "up"},
    "papers": {"cn": "论文数", "sheet": "论文数", "better": "up"},
    "cnci": {"cn": "CNCI", "sheet": "CNCI", "better": "up"},
    "proximity_1pct": {"cn": "ESI前1%接近度", "sheet": "接近度", "better": "up"},
    "threshold_1pct": {"cn": "ESI前1%被引阈值", "sheet": "ESI被引阈值", "better": "none"},
    "top_papers": {"cn": "顶尖论文数", "sheet": "TOP论文", "better": "up"},
    "threshold_1permille": {"cn": "ESI前1‰被引阈值", "sheet": "千分之一被引阈值", "better": "none"},
    # 以下三项来自 grouped 表（新国内/新国际排名），source 列区分口径
    "rank": {"cn": "国内排名", "sheet": "新国内排名", "better": "down"},
    "rank_pct": {"cn": "国内排名百分位", "sheet": "新国内排名", "better": "down"},
    "rank_intl": {"cn": "国际排名", "sheet": "云大ESI排名", "better": "down"},
    "rank_intl_pct": {"cn": "国际排名百分位", "sheet": "新国际排名", "better": "down"},
    "n_inst_1pct": {"cn": "国内ESI前1%机构数", "sheet": "新国内排名", "better": "none"},
}

#: 宽表名 → 台账工作表（`wide/<name>.parquet` 的溯源）
WIDE_SHEET = {
    "total_cites": "总被引", "papers": "论文数", "cnci": "CNCI",
    "proximity_1pct": "接近度", "threshold_1pct": "ESI被引阈值", "top_papers": "TOP论文",
    "threshold_1permille": "千分之一被引阈值", "q1q4": "Q1-Q4",
    "ynd_rank": "云大ESI排名", "top_total": "TOP论文", "entered_1pct": "学科进入时间",
    "province": "高校学科发展", "forecast_gap": "实际与预测差值",
}

#: 学科中文名（与复刻报告同一份映射，绝不另建一套）
try:
    from parse_ledger import DISCIPLINES_CN, DISCIPLINES_EN
except ImportError:                                            # 直接以脚本方式运行时的兜底
    DISCIPLINES_CN, DISCIPLINES_EN = {}, []

import period as period_mod                                    # noqa: E402  期次口径唯一来源


def cn_name(en: str) -> str:
    return DISCIPLINES_CN.get(en, en)


def period_label(p) -> str:
    """`202607` → `2026年7月`（口径在 `period.label`）。"""
    return period_mod.label(p)


def prev_period(periods, p):
    """列表里严格早于 p 的最近一期（没有则 None）——口径在 `period.prev_before`。"""
    try:
        return period_mod.prev_before([str(x) for x in periods], p)
    except period_mod.PeriodUndetectable:
        return None


def shift_period(p, n_newer_targets):
    """按双月步长平移期次：n_newer_targets>0 取今后的第 n 期。

    期次恒为单数月（202601/202603/…），故步长 2 个月。
    """
    p = str(p)
    y, m = int(p[:4]), int(p[4:])
    for _ in range(abs(int(n_newer_targets))):
        if n_newer_targets > 0:
            m += 2
            if m > 12:
                m -= 12
                y += 1
        else:
            m -= 2
            if m < 1:
                m += 12
                y -= 1
    return f"{y}{m:02d}"


class DataSource:
    """`out/<期次>/` 的只读视图。所有取值都带来源链。"""

    def __init__(self, out_dir):
        self.dir = pathlib.Path(out_dir)
        if not (self.dir / "ledger_long.parquet").is_file():
            raise FileNotFoundError(
                f"{self.dir}/ledger_long.parquet 不存在。灵活报告只消费流水线产物，"
                f"请先对该期次跑 parse_ledger（或 run_pipeline）。")
        self._long = None
        self._wide_cache: dict[str, pd.DataFrame] = {}

    # ---------------------------------------------------------------- 基础
    @property
    def long(self) -> pd.DataFrame:
        if self._long is None:
            self._long = pd.read_parquet(self.dir / "ledger_long.parquet")
        return self._long

    def wide(self, name: str) -> pd.DataFrame:
        if name not in self._wide_cache:
            p = self.dir / "wide" / f"{name}.parquet"
            if not p.is_file():
                raise KeyError(f"派生表 {name} 不存在（{p}）")
            df = pd.read_parquet(p)
            # 宽表：index=discipline, columns=period（q1q4/province/ynd_rank 等长表原样返回）
            self._wide_cache[name] = df
        return self._wide_cache[name]

    @property
    def disciplines(self) -> list[str]:
        return sorted(self.long.discipline.dropna().unique().tolist())

    @property
    def periods(self) -> list[str]:
        """台账里出现过的**全部**期次（含先建好的空表头列——数据没到的期次）。"""
        ps = [str(p) for p in self.long.period.dropna().unique()]
        return sorted(ps)

    @property
    def filled_periods(self) -> list[str]:
        """**有数据**的期次（总被引表该列非全空）。

        🔴 出图窗口与报告窗口一律用这个，不用 `periods` —— 空表头列
        （台账里先建好了表头但数据没到）会让窗口多出一期空档：
        图上不会画（`charts._avail` 会滤掉），但「窗口 7 期」的表述会与实际画出的
        期数对不上，且差分图会多算一格。口径同 `compute.detect_periods`。
        """
        return period_mod.filled({"total_cites": self.wide("total_cites")})

    def current_period(self) -> str:
        """当期＝总被引表最后一个有数据的期次（口径唯一在 `period`）。"""
        return period_mod.filled({"total_cites": self.wide("total_cites")})[-1]

    # ---------------------------------------------------------------- 取值
    def series(self, metric: str, disc: str) -> pd.Series:
        """某学科某指标的全期次序列（index=period, 升序）。"""
        if metric not in METRICS:
            raise KeyError(f"指标 {metric} 不在白名单内：{sorted(METRICS)}")
        df = self.long
        sub = df[(df.metric == metric) & (df.discipline == disc)]
        if metric in ("rank", "rank_pct"):
            sub = sub[sub.source == "new_cn"]
        elif metric in ("rank_intl_pct", "n_inst_1pct"):
            sub = sub[sub.source == "new_intl"]
        s = sub.set_index("period")["value"]
        s.index = [str(p) for p in s.index]
        return s.sort_index().dropna()

    def at(self, metric: str, disc: str, period: str):
        """单个值（取不到返回 None）。"""
        s = self.series(metric, disc)
        p = str(period)
        if p not in s.index:
            return None
        v = s.loc[p]
        return None if pd.isna(v) else float(v)

    def cross(self, metric: str, period: str) -> pd.Series:
        """某一期、某指标、全学科横截面（index=discipline）。"""
        if metric not in METRICS:
            raise KeyError(f"指标 {metric} 不在白名单内：{sorted(METRICS)}")
        df = self.long
        sub = df[(df.metric == metric) & (df.period.astype(str) == str(period))]
        if metric in ("rank", "rank_pct"):
            sub = sub[sub.source == "new_cn"]
        elif metric in ("rank_intl_pct", "n_inst_1pct"):
            sub = sub[sub.source == "new_intl"]
        s = sub.set_index("discipline")["value"].dropna()
        return s.astype(float).sort_values()

    def rank_intl_series(self) -> pd.Series:
        """云大国际排名序列（来自 `云大ESI排名` 表）。"""
        df = self.wide("ynd_rank").set_index("period")["rank_intl"]
        df.index = [str(p) for p in df.index]
        return df.dropna().sort_index()

    def entered_1pct(self) -> pd.DataFrame:
        return self.wide("entered_1pct")

    # ------------------------------------------------------------ 来源链
    def chain(self, metric: str, disc: str, period: str) -> dict:
        """一个数字的来源链：数据集 → 指标 → 学科 → 期次 → 台账工作表。"""
        meta = METRICS.get(metric, {})
        return {
            "dataset": f"{self.dir.as_posix()}/ledger_long.parquet",
            "metric": metric,
            "metric_cn": meta.get("cn", metric),
            "discipline": disc,
            "discipline_cn": cn_name(disc),
            "period": str(period),
            "origin_sheet": meta.get("sheet", "（派生）"),
            "locator": f"{meta.get('sheet', '（派生）')}：{cn_name(disc)} 行 × {period} 列",
        }
