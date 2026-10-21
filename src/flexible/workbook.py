# -*- coding: utf-8 -*-
"""监测表 Workbook 适配器：`LedgerView` 的**回落**实现（parquet 产物缺席时用）。

只读：`parse_ledger.load_ledger` 现场解析 `input/<期次>/监测表.xlsx`（openpyxl 只读），
不写任何文件。规范名与 `DataSource`（parquet 面）对齐：转置排名表 pivot 成宽表、
千分之一阈值走宽表——因此两个适配器对取数引擎**同协议同值**
（`tests/test_flexible.py::Test两适配器同值` 有逐值等价用例）。

口径与 `src/ai/_qa.py::_ledger_for` 同源（同一套 `parse_ledger` 现场真读）；
本模块只是把它套进 `LedgerView` 的形状，供引擎统一消费。
"""
from __future__ import annotations

import pathlib

import pandas as pd

import period as period_mod
from .datasource import METRICS, cn_name, relative_path


def _pivot(df, value: str):
    """长表（discipline, period, …）→ 宽表（index=discipline, columns=period[str]）。"""
    if df is None or getattr(df, "empty", True):
        return None
    out = df.pivot(index="discipline", columns="period", values=value)
    out.columns = [str(c) for c in out.columns]
    return out


class WorkbookView:
    """`input/<期次>/监测表.xlsx` 的只读 `LedgerView`。"""

    def __init__(self, path):
        import parse_ledger                                        # noqa: PLC0415

        self.path = pathlib.Path(path)
        led = parse_ledger.load_ledger(self.path)
        self._led = led
        wide = dict(led.get("wide") or {})
        wide["threshold_1permille"] = led.get("threshold_1permille")
        wide["rank"] = _pivot(led.get("new_cn"), "rank")
        wide["rank_pct"] = _pivot(led.get("new_cn"), "rank_pct")
        wide["n_inst_1pct"] = _pivot(led.get("new_cn"), "n_inst_1pct")
        wide["rank_intl_pct"] = _pivot(led.get("new_intl"), "rank_pct")
        wide["rank_cn"] = _pivot(led.get("rank_cn"), "rank")
        wide["rank_intl"] = _pivot(led.get("rank_intl"), "rank")
        self._wide = {k: v for k, v in wide.items() if v is not None}

    # ------------------------------------------------------------------ 轴
    @property
    def _total(self):
        return self._wide.get("total_cites")

    @property
    def periods(self) -> list:
        cols = set()
        for fr in self._wide.values():
            cols.update(str(c) for c in fr.columns)
        return sorted(cols)

    @property
    def filled_periods(self) -> list:
        fr = self._total
        if fr is None:                                   # 最小夹具可能缺总被引表
            return self.periods
        return period_mod.filled({"total_cites": fr})

    @property
    def disciplines(self) -> list:
        idx = set()
        for fr in self._wide.values():
            idx.update(str(d) for d in fr.index)
        return sorted(idx)

    def current_period(self) -> str:
        return self.filled_periods[-1]

    # ---------------------------------------------------------------- 取值
    def series(self, metric: str, disc: str) -> pd.Series:
        """某学科某指标的全期次序列（index=period, 升序）。"""
        if metric not in METRICS:
            raise KeyError(f"指标 {metric} 不在白名单内：{sorted(METRICS)}")
        fr = self._wide.get(metric)
        if fr is None or disc not in getattr(fr, "index", []):
            return pd.Series(dtype=float)
        s = fr.loc[disc]
        s.index = [str(p) for p in s.index]
        return s.sort_index().dropna().astype(float)

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
        fr = self._wide.get(metric)
        if fr is None:
            return pd.Series(dtype=float)
        cols = {str(c): c for c in fr.columns}
        if str(period) not in cols:
            return pd.Series(dtype=float)
        return fr[cols[str(period)]].dropna().astype(float).sort_values()

    # -------------------------------------------------------------- 来源链
    def chain(self, metric: str, disc: str, period: str) -> dict:
        """一个数字的来源链：监测表 → 指标 → 学科 → 期次 → 台账工作表。"""
        meta = METRICS.get(metric, {})
        return {
            "dataset": relative_path(self.path),
            "metric": metric,
            "metric_cn": meta.get("cn", metric),
            "discipline": disc,
            "discipline_cn": cn_name(disc),
            "period": str(period),
            "origin_sheet": meta.get("sheet", "（派生）"),
            "locator": f"{meta.get('sheet', '（派生）')}：{cn_name(disc)} 行 × {period} 列",
        }

    # ------------------------------------------------------------------ 专表
    def ynd_rank(self) -> pd.DataFrame:
        """云大整体排名（index=period；列 rank_intl / rank_cn / rank_cn_uni）。"""
        df = self._led.get("ynd_rank")
        if df is None:
            raise KeyError("监测表缺少《云大ESI排名》表")
        return df

    def entry_events(self) -> list:
        """进出事件 `[(期次, 学科, "in"/"out")]`（《学科进入时间》流水，parse_ledger 已解析）。"""
        return [tuple(e) for e in (self._led.get("entry_events") or [])]

    def entered_1pct(self):
        """学科 × 期次的 0/1 矩阵（1＝该期已在前 1% 内）。"""
        df = self._led.get("entered_1pct")
        if df is None:
            raise KeyError("监测表缺少《学科进入时间》表")
        return df
