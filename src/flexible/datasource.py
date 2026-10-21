# -*- coding: utf-8 -*-
"""只读数据访问层 + **来源链**。

红件（红线）在这里落地：本模块**只读** `out/<期次>/` 下的 parquet，
不 import `openpyxl`、不出现任何写调用。台账 xlsx 一个字节都不碰
（它由 `parse_ledger` 在流水线里读一次，落成 parquet 后此处只消费产物）。

`LedgerView` 是取数引擎（`queries.py`）认的**数据面协议**；本模块的 `DataSource`
是主适配器（parquet 产物），`flexible/workbook.py` 的 `WorkbookView` 是回落适配器
（`input/<期次>/监测表.xlsx` 直读，parquet 缺席时用）——两者同协议、同值。

「来源链」是灵活报告可信度的落点：每个数字都带
`{dataset, metric, discipline, period, origin_sheet}`，
与复刻报告的红件清单同构，可指回台账的工作表与期次列。
"""
from __future__ import annotations

import pathlib
from typing import Protocol

import pandas as pd

#: 允许查询的指标白名单 —— 同时也是「LLM 能看到的字段字典」。
#: 键＝对外指标名；值＝(中文名, 台账工作表, 方向说明)
#: 方向说明用于让规划器知道「哪个方向算好」（如 rank 越小越好）。
#: 排名类有两套来源：`rank/rank_pct`＝新国内排名（grouped 表）；`rank_cn/rank_intl`
#: ＝国内/国际排名（转置表，q 问文衡的排名序列用它）；`rank_intl_pct/n_inst_1pct`＝新国际排名。
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
    "rank_cn": {"cn": "国内排名（转置表）", "sheet": "国内排名", "better": "down"},
    "rank_intl": {"cn": "国际排名", "sheet": "国际排名", "better": "down"},
    "rank_intl_pct": {"cn": "国际排名百分位", "sheet": "新国际排名", "better": "down"},
    "n_inst_1pct": {"cn": "国内ESI前1%机构数", "sheet": "新国内排名", "better": "none"},
}

#: 规范名 → ledger_long 里的（metric, source）规格。缺省＝同名指标、不滤 source。
#: 排名类在长表里只有 metric ∈ {rank, rank_pct, n_inst_1pct}，靠 source 区分四张来源表：
#: new_cn/new_intl＝新国内/新国际排名；rank_cn/rank_intl＝国内/国际排名（转置）。
_LONG_SPEC = {
    "rank": ("rank", "new_cn"),
    "rank_pct": ("rank_pct", "new_cn"),
    "rank_intl_pct": ("rank_pct", "new_intl"),
    "n_inst_1pct": ("n_inst_1pct", "new_intl"),
    "rank_cn": ("rank", "rank_cn"),
    "rank_intl": ("rank", "rank_intl"),
}

#: 宽表直读（不在 ledger_long 里的指标）：千分之一阈值。
_WIDE_ONLY = ("threshold_1permille",)

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

#: 代码仓根（`src/flexible/datasource.py` → 仓库）；报告与 JSON 里的路径都以它为锚。
REPO = pathlib.Path(__file__).resolve().parents[2]


def relative_path(path) -> str:
    """把产物路径写成**仓库相对**：成品里不出现本机盘符或绝对路径。

    正常情况（`out/<期次>/…` 就在仓里）返回真实的相对路径；测试/部署把期次目录
    复制到仓外时，按产物结构还原成逻辑路径 `out/<期次>/…`——仍是可读、可交接的
    写法，绝不回落到 `C:/…`。找不到结构时只留文件名。
    """
    p = pathlib.Path(path)
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except (ValueError, OSError):
        pass
    parts = list(p.parts)
    if "out" in parts:
        i = len(parts) - 1 - parts[::-1].index("out")
        return "/".join(parts[i:])
    if p.parent.name == "wide":
        return f"out/{p.parent.parent.name}/wide/{p.name}"
    if p.name == "ledger_long.parquet":
        return f"out/{p.parent.name}/{p.name}"
    return p.name


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


class LedgerView(Protocol):
    """取数引擎（`queries.py`）认的**只读数据面协议**。

    两适配器同协议、同值：
    - `DataSource`（本模块）＝ `out/<期次>/` parquet 产物，主；
    - `WorkbookView`（`flexible/workbook.py`）＝ `input/<期次>/监测表.xlsx` 直读，回落。
    引擎只调这组读方法——不碰文件系统、不 import openpyxl。
    """

    @property
    def periods(self) -> list: ...
    @property
    def filled_periods(self) -> list: ...
    @property
    def disciplines(self) -> list: ...

    def current_period(self) -> str: ...
    def series(self, metric: str, disc: str) -> pd.Series: ...
    def at(self, metric: str, disc: str, period: str) -> float | None: ...
    def cross(self, metric: str, period: str) -> pd.Series: ...
    def chain(self, metric: str, disc: str, period: str) -> dict: ...
    def entered_1pct(self) -> pd.DataFrame: ...
    def entry_events(self) -> list: ...
    def ynd_rank(self) -> pd.DataFrame: ...


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
        if metric in _WIDE_ONLY:
            fr = self.wide(metric)
            if disc not in getattr(fr, "index", []):
                return pd.Series(dtype=float)
            s = fr.loc[disc]
            s.index = [str(p) for p in s.index]
            return s.sort_index().dropna().astype(float)
        lm, src_filter = _LONG_SPEC.get(metric, (metric, None))
        sub = self.long[(self.long.metric == lm) & (self.long.discipline == disc)]
        if src_filter:
            sub = sub[sub.source == src_filter]
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
        if metric in _WIDE_ONLY:
            fr = self.wide(metric)
            cols = {str(c): c for c in fr.columns}
            if str(period) not in cols:
                return pd.Series(dtype=float)
            return fr[cols[str(period)]].dropna().astype(float).sort_values()
        lm, src_filter = _LONG_SPEC.get(metric, (metric, None))
        sub = self.long[(self.long.metric == lm)
                        & (self.long.period.astype(str) == str(period))]
        if src_filter:
            sub = sub[sub.source == src_filter]
        s = sub.set_index("discipline")["value"].dropna()
        return s.astype(float).sort_values()

    def ynd_rank(self) -> pd.DataFrame:
        """云大整体排名（index=period；列 rank_intl / rank_cn / rank_cn_uni）。"""
        df = self.wide("ynd_rank").set_index("period")
        df.index = [str(p) for p in df.index]
        return df.sort_index()

    def entry_events(self) -> list:
        """进出事件 `[(期次, 学科, "in"/"out")]`（由 0/1 矩阵跳变推导——parquet 面无流水表）。"""
        ent = self.entered_1pct().astype(float)
        cols = [str(c) for c in ent.columns]
        out = []
        for d in ent.index:
            row = ent.loc[d]
            for i in range(1, len(cols)):
                a, b = float(row.iloc[i - 1]), float(row.iloc[i])
                if a != b:
                    out.append((cols[i], str(d), "in" if b == 1.0 else "out"))
        return out

    def entered_1pct(self) -> pd.DataFrame:
        return self.wide("entered_1pct")

    # ------------------------------------------------------------ 来源链
    def chain(self, metric: str, disc: str, period: str) -> dict:
        """一个数字的来源链：数据集 → 指标 → 学科 → 期次 → 台账工作表。

        `dataset` 一律是**仓库相对**路径（`relative_path`）：它会原样进
        `flex_sources.json` 与报告附录，不能把本机盘符带进成品。
        """
        meta = METRICS.get(metric, {})
        return {
            "dataset": relative_path(self.dir / "ledger_long.parquet"),
            "metric": metric,
            "metric_cn": meta.get("cn", metric),
            "discipline": disc,
            "discipline_cn": cn_name(disc),
            "period": str(period),
            "origin_sheet": meta.get("sheet", "（派生）"),
            "locator": f"{meta.get('sheet', '（派生）')}：{cn_name(disc)} 行 × {period} 列",
        }
