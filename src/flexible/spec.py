# -*- coding: utf-8 -*-
"""图表声明语言（chart spec）→ 复用 `charts.py` 排版设施渲染。

为什么不让 LLM 生成 matplotlib 代码（路径 ① 被否掉）：
那会让四期调优出来的排版设施（`_auto_ylim` 纯数据驱动纵轴 / `_labels` 标签避让 /
`_ov` 重叠检测）全部作废，画出来必压字 —— 而「图表专业度」是评分项。

🔴 **红线：AI 不得指定图表纵轴范围。**
本模块的 spec **没有**「上下界」这个字段 —— 不是"不推荐"，是结构上不存在。
`FORBIDDEN_KEYS` 里任何一个出现即抛 `SpecError`，包括 `ylim` / `ymin` / `ymax` /
`vmin` / `vmax` / `range` / `limits` / `axis_range` 及其大小写变体。
只允许**语义**参数：`invert`（越小越好）/ `include`（必须含的参照值）/
`zero_base` / `floor_zero`（柱状零基准）。轴范围永远由数据决定（`_auto_ylim`）。

复用关系：本模块**只调用** `charts.py` 里已参数化的 9 个图型，自己不做任何绘图装配。
"""
from __future__ import annotations

import json
import pathlib
import re

import pandas as pd

import charts

from .datasource import METRICS, DataSource, cn_name, relative_path

#: 🔴 结构上禁止出现在 spec 里的键（纵轴范围类）。任何大小写/下划线的写法都拦。
FORBIDDEN_KEYS = ("ylim", "ymin", "ymax", "vmin", "vmax", "range", "limits",
                  "axisrange", "axrange", "ylimits", "y0", "y1", "yscale", "yticks")

#: 词干匹配表 —— 光靠上面那份穷举拦不住 `y_range` / `Y-Range` / `axis_limit`
#: 这类写法（归一化后是 `yrange` / `axislimit`，不在枚举里）。
#: 🔴 合法键（kind/disc/periods/n_periods/end_period/title/why/
#: invert/include/zero_base/floor_zero）归一化后都不含下面任何词干，不会误伤。
FORBIDDEN_STEMS = ("ylim", "vmin", "vmax", "range", "limit", "yscale", "ytick",
                   "yaxis", "axis")


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def is_forbidden_key(k: str) -> bool:
    """判断键名是否属于「纵轴范围」类。`planner` 也用这个，别各写一套。"""
    nk = _norm_key(k)
    return nk in FORBIDDEN_KEYS or any(s in nk for s in FORBIDDEN_STEMS)


def _slug(en: str) -> str:
    """学科英文名 → 文件名安全串（与 charts.py 的 `_slug` 同规则）。"""
    return re.sub(r"[^A-Za-z0-9]+", "", str(en))


#: 9 个图型的 spec 登记表。
#: `needs` ＝ 需要从 `wide/` 取哪些表；`disc_scope` ＝ 单学科 / 概览（无学科）；
#: `semantic` ＝ 可接受的语义参数（None 默认＝复刻口径）。
KINDS: dict[str, dict] = {
    "rank_pct": {
        "cn": "国内外排名百分位趋势", "disc_scope": "single",
        "needs": ["rank_intl", "rank_cn"], "semantic": ("invert",),
    },
    "cnci": {
        "cn": "CNCI 变化", "disc_scope": "single",
        "needs": ["cnci"], "semantic": ("include",),
    },
    "papers_delta": {
        "cn": "新增发文量", "disc_scope": "single",
        "needs": ["papers"], "semantic": ("zero_base",),
    },
    "cites_threshold": {
        "cn": "被引频次与 ESI 阈值", "disc_scope": "single",
        "needs": ["total_cites", "threshold_1pct"], "semantic": ("zero_base", "include"),
    },
    "top_papers": {
        "cn": "顶尖论文量", "disc_scope": "single",
        "needs": ["top_papers"], "semantic": ("floor_zero",),
    },
    "cites_permille": {
        "cn": "被引频次与 ESI 前1‰ 阈值", "disc_scope": "single",
        "needs": ["total_cites", "threshold_1permille"], "semantic": ("zero_base", "include"),
    },
    "q_dist": {
        "cn": "期刊分区占比", "disc_scope": "single",
        "needs": ["q1q4"], "semantic": ("floor_zero",),
    },
    "ynd_rank": {
        "cn": "我校 ESI 排名情况", "disc_scope": "overview",
        "needs": ["ynd_rank"], "semantic": (),
    },
    "overview_1pct": {
        "cn": "ESI 前1% 接近度总览", "disc_scope": "overview",
        "needs": ["total_cites", "threshold_1pct"], "semantic": (),
    },
    "overview_1permille": {
        "cn": "ESI 前1‰ 潜力总览", "disc_scope": "overview",
        "needs": ["total_cites", "threshold_1permille", "entered_1pct"], "semantic": (),
    },
}

DEFAULT_WINDOW = 7          # 与复刻报告一致：当期往前 7 期（含当期）


class SpecError(Exception):
    """spec 非法（含纵轴范围类键、未知 kind、不支持的语义参数）。"""


def validate(spec: dict) -> dict:
    """校验 spec 并返回规范化结果。**唯一的闸**，渲染前必过。"""
    if not isinstance(spec, dict):
        raise SpecError(f"spec 必须是对象，实为 {type(spec).__name__}")
    for k in spec:
        if is_forbidden_key(k):
            raise SpecError(
                f"spec 不允许出现「{k}」：AI 不得指定图表纵轴范围，"
                f"轴范围一律由数据决定（charts._auto_ylim）。"
                f"只允许语义参数 invert / include / zero_base / floor_zero。")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise SpecError(f"未知图型 {kind!r}；可用：{sorted(KINDS)}")
    meta = KINDS[kind]
    allowed = {"kind", "disc", "periods", "n_periods", "end_period", "title", "why"} \
        | set(meta["semantic"])
    unknown = set(spec) - allowed
    if unknown:
        raise SpecError(
            f"{kind} 不接受参数 {sorted(unknown)}；"
            f"允许：{sorted(allowed)}（语义参数仅 {list(meta['semantic']) or '无'}）")
    if meta["disc_scope"] == "single":
        if not spec.get("disc"):
            raise SpecError(f"{kind} 需要 disc（学科英文名）")
    elif spec.get("disc"):
        raise SpecError(f"{kind} 是概览图，不应带 disc")
    if spec.get("n_periods") is not None:
        n = spec["n_periods"]
        if not isinstance(n, int) or not (2 <= n <= 30):
            raise SpecError(f"n_periods 必须是 2–30 的整数，实为 {n!r}")
    return spec


def _window(src: DataSource, spec: dict, ledger_dir) -> tuple[list[str], list[str]]:
    """算出出图窗口。返回 (periods, extra_period)。

    🔴 用 `filled_periods`（有数据的期次），不是 `periods` —— 空表头列
    （台账里先建好表头、数据没到）会让差分图多算一格、并让「7 期」与实际期数对不上。
    `papers_delta` 需要窗口外多一期（差分），由 `extra` 带回。
    """
    allp = src.periods
    if spec.get("periods"):
        ps = [str(p) for p in spec["periods"]]
        bad = [p for p in ps if p not in allp]
        if bad:
            raise SpecError(f"期次 {bad} 不在数据范围内（{allp[0]}–{allp[-1]}）")
        ps = sorted(set(ps))
        filled = src.filled_periods
        prev = filled[filled.index(ps[0]) - 1] if ps[0] in filled else None
        return ps, ([prev] if prev else [])
    filled = src.filled_periods
    end = str(spec.get("end_period") or src.current_period())
    usable = [p for p in filled if p <= end]
    n = int(spec.get("n_periods") or DEFAULT_WINDOW)
    return usable[-n:], usable[-(n + 1):-n]          # 后一项＝窗口外上一期（差分用）


def make(src: DataSource, spec: dict, out_dir, *, ledger_dir=None) -> dict:
    """按 spec 渲染一张图。返回 {path, kind, spec, semantic, periods, sources}。

    🔴 `sources` 列出本图用到的数据来源（数据集 + 指标 + 学科 + 期次），供报告层附链。
    """
    spec = validate(spec)
    kind = spec["kind"]
    meta = KINDS[kind]
    ld = pathlib.Path(ledger_dir or src.dir)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 图文件名：默认按 kind 命名，避免覆盖复刻报告的 charts/
    # 🔴 学科名要去掉空格与 &（`Molecular Biology & Genetics` 直接进 markdown 图片路径
    #    会断链），与 charts.py 的 `_slug` 同一套规则。
    disc = spec.get("disc")
    stem = f"{kind}__{_slug(disc)}" if disc else kind
    title = spec.get("title")
    path = out_dir / f"{stem}.png"

    periods, extra = _window(src, spec, ld)
    if not periods:
        raise SpecError(f"窗口为空（end_period={spec.get('end_period')}）")

    # 语义参数：只把 spec 里**显式给了**的传下去；没给就不传 → 走复刻口径
    kw = {k: spec[k] for k in meta["semantic"] if k in spec}

    if kind == "rank_pct":
        charts.chart_rank_pct(_t(ld, "rank_intl"), _t(ld, "rank_cn"), disc, path, periods, **kw)
    elif kind == "cnci":
        charts.chart_cnci(_t(ld, "cnci"), disc, path, periods, **kw)
    elif kind == "papers_delta":
        charts.chart_papers_delta(_t(ld, "papers"), disc, path, periods + extra, **kw)
    elif kind == "cites_threshold":
        charts.chart_cites_threshold(_t(ld, "total_cites"), _t(ld, "threshold_1pct"),
                                     disc, path, periods, **kw)
    elif kind == "cites_permille":
        charts.chart_cites_threshold(_t(ld, "total_cites"), _t(ld, "threshold_1permille"),
                                     disc, path, periods, **kw)
    elif kind == "top_papers":
        charts.chart_top_papers(_t(ld, "top_papers"), disc, path, periods, **kw)
    elif kind == "q_dist":
        charts.chart_q_dist(_q1q4(ld), disc, path, periods[-1], **kw)
    elif kind == "ynd_rank":
        charts.chart_ynd_rank(_ynd(ld), path, end_period=periods[-1], n=len(periods))
    elif kind == "overview_1pct":
        charts.chart_overview_1pct(_t(ld, "total_cites"), _t(ld, "threshold_1pct"),
                                   path, periods[-1])
    elif kind == "overview_1permille":
        charts.chart_overview_1permille(_t(ld, "total_cites"), _tp(ld),
                                        _ent(ld), path, periods[-1])
    else:                                                        # pragma: no cover
        raise SpecError(f"图型 {kind} 未接线")

    # 数据来源（供报告层附链；概览图无学科）。
    # 🔴 路径一律仓库相对：图源会随账本进 `flex_sources.json` 与报告附录。
    sources = []
    for n in meta["needs"]:
        ledger_table = n in _PIVOT_FROM_LONG
        p = ld / ("ledger_long.parquet" if ledger_table else f"wide/{n}.parquet")
        sheet = _origin_sheet(n)
        sources.append({
            "dataset": relative_path(p),
            "table": "ledger_long（透视）" if ledger_table else n,
            "origin_sheet": sheet,
            "discipline": disc, "discipline_cn": cn_name(disc) if disc else None,
            "periods": periods,
            "locator": f"{sheet}：{(disc and cn_name(disc)) or '全学科'} "
                       f"{periods[0]}–{periods[-1]}",
        })

    return {
        "path": str(path), "kind": kind, "kind_cn": meta["cn"],
        "spec": spec,
        "semantic": (kw if kw else {"口径": "复刻默认（未指定语义参数）"}),
        "periods": periods, "sources": sources,
        "note": "轴范围由数据决定（charts._auto_ylim）；本图不含任何 AI 指定的轴界。",
    }


# ------------------------------------------------------------- 取表助手
_CACHE: dict[tuple, pd.DataFrame] = {}

#: 这两张**不是** `wide/` 下的独立 parquet，而是从 `ledger_long` 里按 source 透视出来的
#: （与 `charts.render_all` 同口径 —— 别去找 `wide/rank_intl.parquet`，它不存在）。
_PIVOT_FROM_LONG = {"rank_intl", "rank_cn"}


def _long(ld) -> pd.DataFrame:
    key = (str(ld), "__long__")
    if key not in _CACHE:
        _CACHE[key] = pd.read_parquet(pathlib.Path(ld) / "ledger_long.parquet")
    return _CACHE[key]


def _t(ld, name):
    key = (str(ld), name)
    if key not in _CACHE:
        if name in _PIVOT_FROM_LONG:
            lg = _long(ld)
            sub = lg[(lg.source == name) & (lg.metric == "rank_pct")]
            _CACHE[key] = sub.pivot_table(index="discipline", columns="period",
                                          values="value")
        else:
            _CACHE[key] = pd.read_parquet(pathlib.Path(ld) / "wide" / f"{name}.parquet")
    return _CACHE[key]


def _q1q4(ld):
    return _t(ld, "q1q4")


def _tp(ld):
    return _t(ld, "threshold_1permille")


def _ent(ld):
    return _t(ld, "entered_1pct")


def _ynd(ld):
    return _t(ld, "ynd_rank")


def _origin_sheet(w: str) -> str:
    from .datasource import METRICS, WIDE_SHEET
    # rank_intl / rank_cn 不是 wide/ 下的独立表（由 ledger_long 透视），
    # 工作表名取指标白名单里的口径，不能落成「（派生）」。
    return WIDE_SHEET.get(w) or METRICS.get(w, {}).get("sheet", "（派生）")


def catalog() -> list[dict]:
    """给规划器/前端看的图型目录（**只有语义参数，没有轴范围**）。"""
    return [{"kind": k, "cn": v["cn"], "disc_scope": v["disc_scope"],
             "semantic": list(v["semantic"]),
             "semantic_cn": {"invert": "反向轴（数值越小越好）",
                             "include": "必须含的参照值",
                             "zero_base": "把 0 纳入轴范围",
                             "floor_zero": "下界钉死 0（柱状零基准）"}}
            for k, v in KINDS.items()]


def dump(spec: dict, path) -> str:
    """把 spec 落盘（可存、可回放、可复现）。"""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)
