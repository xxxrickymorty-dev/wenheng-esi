# -*- coding: utf-8 -*-
"""多校多学科面板：一条时间线 × 若干所学校 × 若干学科。

为什么另开一个模块
------------------
`flexible/` 里的 `spec.py` / `planner.py` / `report.py` / `provenance.py`（约 2289 行）
都写死「单学科 + 云大锚点」，产物按「节」组织；本模块的产物按「格」组织
（期次 × 学校 × 学科）。硬改那四个文件是全员回归，所以旁边新开，只读复用它们。

两层返回（这是红线在对比场景的落地形态）
----------------------------------------
`panel()` 一次返回两份东西：

- `summary` / `schools[].counts` / `common` / `only` / `events`：**约 20 个数字**，
  是进模型上下文的那一层。模型只能从这里抄，抄不到 `grid`。
- `grid`：完整矩阵（期次 × 学校 × 学科），只给前端画图，**不进模型上下文**。

目的很直白：模型看不到全量矩阵，就没有机会「顺手算一个数」。

三条硬约束
----------
1. **三态不整体抛错**：每校 `status ∈ {ok, absent, error}`，一所查不到其余照常。
   （`peers.compare` 是一校失败整批炸，那是单学科报告的语义，这里不能沿用。）
2. **期次只走 `period.prev_before` 链式回溯**，不做日历减法——双月出刊且允许缺口，
   `202602` 这种期次在本地根本不存在。回溯不到就停，窗口自然变短。
3. **学科只认 `discipline_list.DISCIPLINES`**，不 glob 目录。实测 202511 目录里混了
   4 个非学科文件，glob 会把上榜数多计 1–4 个而且不报错。

`absent` 与 `error` 的分界
--------------------------
- `absent`：总表、末期满血表、窗口内所有学科表**都找不到这个名字** → 该校整校未进
  ESI（或校名写法与 ESI 不一致，本地数据分不出这两种，`note` 里两说并列）。
- `error`：名字能对上、但对上了**多家**（`DALI` 会命中 27 家，因为 "OSPEDALI" 里
  含 DALI）→ 不能猜，报错让用户给全称。

取数缓存
--------
默认 6 期 × 22 学科 = 132 次读表，实测 23.5s。`_rows()` 用 `lru_cache` 缓存，
第二次调用同一组参数走内存（实测 1s 量级）。缓存的是**只读**结果，调用方不得原地改。
"""
from __future__ import annotations

import datetime as _dt
import functools
import pathlib
import sys

try:                                     # 仓库惯例：pytest 的 pythonpath 已含 src
    from discipline_list import DISCIPLINES, CN_OF, cn_of, is_discipline
    from period import PeriodUndetectable, prev_before
except ImportError:                      # 作为包被导入或独立跑脚本时兜底
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from discipline_list import DISCIPLINES, CN_OF, cn_of, is_discipline
    from period import PeriodUndetectable, prev_before

from . import events as _events
from . import peers
from .peers import PeerError, _match_ex, _norm

#: 中文名 → 文件 stem。**只做精确匹配**，不做模糊（09-20 与 `&`/`AND` 两次血泪）。
_CN_TO_STEM: dict[str, str] = {cn: stem for stem, cn in CN_OF.items()}

#: 缓存条目数：6 期 × 22 学科 = 132，留一倍余量，避免二次调用被挤掉。
_CACHE = 256


@functools.lru_cache(maxsize=_CACHE)
def _rows(period: str, disc: str) -> tuple[str, list[dict]]:
    """某期某学科的机构行 → `(实际期次, rows)`。

    `peers.fetch` 在当期缺表时会**向前回退**到更早的期次并在返回值里标明实际期次。
    趋势图不能拿上上期的数当本期的数，所以这里把「实际期次」原样交出去，由调用方
    用 `actual == period` 判断本期到底有没有数据。

    读不到（整期整学科都没有表）返回 `("", [])`——**缓存住这个失败**，
    否则「整校不在 ESI」的场景会把 132 次无效回退扫描重跑一遍。
    """
    try:
        data = peers.fetch(period, disc)
    except PeerError:
        return "", []
    return data["period"], data["rows"]


@functools.lru_cache(maxsize=4)
def _pool(period: str) -> tuple[dict, ...]:
    """某期 22 张学科表的机构行并集——只用于校名解析，不参与计数。

    校名解析必须跨学科找：某校可能只在临床医学表里出现，拿单一学科的表去匹配
    会得到「查无此校」的假结论。
    """
    rows: list[dict] = []
    for disc in DISCIPLINES:
        actual, got = _rows(period, disc)
        if actual == period:
            rows.extend(got)
    return tuple(rows)


def _candidates(rows, nq: str) -> list[dict]:
    """子串命中集。只回答「有几家」，不做选择。"""
    if not nq:
        return []
    return [r for r in rows
            if nq in _norm(r["en"]) or (r["cn"] and nq in _norm(r["cn"]))]


def _scan_window(query: str, periods: list[str]) -> dict | None:
    """末期满血表里没有时，回窗口内所有学科表再找一次。

    不这么做的话，「只在早期上榜、后来掉出」的学校会被判成 `absent` 并清成 0，
    数字错得静默——本项目最不能接受的就是这种错。
    """
    nq = _norm(query)
    hits: dict[str, dict] = {}
    for p in periods:
        for disc in DISCIPLINES:
            actual, rows = _rows(p, disc)
            if actual != p:                              # 回退来的表不是本期的，跳过
                continue
            for r in rows:
                if nq in _norm(r["en"]) or (r["cn"] and nq in _norm(r["cn"])):
                    hits.setdefault(_norm(r["en"]),
                                    {"en": r["en"], "cn": r["cn"] or r["en"],
                                     "how": "substring"})
    if len(hits) == 1:
        return next(iter(hits.values()))
    if len(hits) > 1:
        names = "、".join(h["en"] for h in list(hits.values())[:5])
        more = f" 等 {len(hits)} 家" if len(hits) > 5 else f"（共 {len(hits)} 家）"
        raise PeerError(
            f"「{query}」在 {'–'.join((periods[0], periods[-1]))} 的学科表里对上了多家机构，"
            f"无法确定是哪一所：{names}{more}。请给出更完整的校名后重试（未改动任何数据）。")
    return None


def _resolve(query: str, name_map: dict, period_end: str,
             periods: list[str], label: str) -> dict | None:
    """查询名 → `{en, cn, how}`；`None` 表示整校不在 ESI（`absent`）。

    三级尝试，每级都只做**精确或唯一子串**，绝不取第一条：
    1. 归档总表的规范名（`map` / 去掉「大学/学院」后缀的 `trim`）——不读表，最快；
    2. 末期满血 22 张表的机构名（`table` 精确 / `substring` 唯一子串）；
    3. 窗口内所有学科表（应对「只在早期上榜」）。
    第 2、3 级若命中多家，抛 `PeerError`（`error` 态），不猜。
    """
    try:
        return _match_ex([], name_map, query)            # 只走总表：map / trim
    except PeerError:
        pass

    pool = _pool(period_end)
    try:
        return _match_ex(list(pool), name_map, query, sheet=label)
    except PeerError as exc:
        if _candidates(pool, _norm(query)):              # 对上了多家 → 真错误
            raise PeerError(str(exc)) from None
        return _scan_window(query, periods)              # 一家都没对上 → 再扩大范围


def _pick_disciplines(names) -> list[str]:
    """学科参数 → 规范 stem 列表（按 `DISCIPLINES` 的字母序，保证确定性）。

    接受英文 stem（`Clinical Medicine`）或中文名（`临床医学`），两种都是**精确匹配**；
    分隔符与校名一致（逗号、顿号、分号、`和`）。
    """
    if names is None:
        return list(DISCIPLINES)
    chosen: set[str] = set()
    for raw in peers._split_queries(names):
        text = raw.strip()
        if not text:
            continue
        if is_discipline(text):
            chosen.add(text)
        elif text in _CN_TO_STEM:
            chosen.add(_CN_TO_STEM[text])
        else:
            raise ValueError(
                f"不认识的学科：{text!r}。请用英文 stem（如 'Clinical Medicine'）"
                f"或中文名（如 '临床医学'），共 {len(DISCIPLINES)} 个学科。")
    if not chosen:
        raise ValueError("disciplines 为空——要么不传（默认 22 个学科全要），要么给至少一个学科名。")
    return [d for d in DISCIPLINES if d in chosen]


def _window(avail: list[str], period_end: str, n: int) -> list[str]:
    """`period_end` 往前数 n 期的升序期次，**只走 `prev_before` 链**。

    不用日历减法：双月出刊，`202602` / `202604` 在本地不存在，减出来的期次
    永远不会命中目录，窗口会静默变短且没人发现。回溯不到就停（窗口短于 n）。
    """
    got = [period_end]
    for _ in range(n - 1):
        try:
            got.insert(0, prev_before(avail, got[0]))
        except PeriodUndetectable:
            break
    return got


def _scan(period: str, discs: list[str], targets: dict[str, dict]) -> tuple[dict, bool]:
    """一期扫描 → `({规范英文名: {学科}}, 本期是否真有数据)`。

    `targets` 是 `{规范英文名: 学校记录}`，只关心这几家，不建全量索引。
    """
    got: dict[str, set[str]] = {k: set() for k in targets}
    real = False
    for disc in discs:
        actual, rows = _rows(period, disc)
        if actual != period:                             # 本期无此表（或回退），不计
            continue
        real = True
        have = {_norm(r["en"]) for r in rows}
        for key in targets:
            if key in have:
                got[key].add(disc)
    return got, real


def _cn_key(stem: str) -> tuple[str, str]:
    """学科排序键：先中文名，再英文原名（同名也不乱）。"""
    return (cn_of(stem), stem)


def panel(schools, disciplines=None, period_end=None, n: int = 6) -> dict:
    """多校多学科面板。参数与返回结构见模块 docstring 与 `评审文档` 的 §3 spec。

    参数
    ----
    schools：校名列表，或「昆工和海南大学」这类带分隔符的字符串。
    disciplines：学科 stem / 中文名的列表或字符串；`None` = 22 个全要。
    period_end：窗口末期次，`None` = ESI 数据目录里最新的那期。
    n：窗口期数（含末期），默认 6。

    返回
    ----
    见模块 docstring「两层返回」。除 `source.generated_at` 外全部确定性。
    """
    discs = _pick_disciplines(disciplines)
    queries = peers._split_queries(schools)
    if not queries:
        raise ValueError("没有指定要对比的高校——至少给一所（如 ['昆明理工大学', '海南大学']）。")

    avail = peers._period_dirs()
    if not avail:
        raise ValueError(f"ESI 数据目录下没有任何期次：{peers.ESI_ROOT}")
    period_end = str(period_end) if period_end else avail[-1]
    if period_end not in avail:
        tail = "、".join(avail[-6:])
        raise ValueError(
            f"没有 {period_end} 这一期的 ESI 数据。可用期次（最近 6 期）：{tail}。"
            f"请确认期次是否已取数（未改动任何数据）。")
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ValueError(f"n 必须是整数，收到 {n!r}") from None
    if n < 1:
        raise ValueError(f"n 至少为 1，收到 {n}")

    periods = _window(avail, period_end, n)

    tpl = peers._latest_template()
    name_map = peers._name_map(str(tpl)) if tpl else {}
    label = f"{period_end} 期 {len(DISCIPLINES)} 个学科表"

    # ---- 校名解析（先解析再扫描：扫描要按规范英文名做集合判断）
    records: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        rec = {"query": query, "cn": query, "en": "", "status": "ok",
               "match": "map", "counts": None, "entered": [], "exited": [], "note": ""}
        try:
            got = _resolve(query, name_map, period_end, periods, label)
        except PeerError as exc:
            rec.update({"status": "error", "match": "error", "note": str(exc)})
            records.append(rec)
            continue
        if got is None:
            rec.update({
                "status": "absent", "match": "absent",
                "note": (f"{periods[0]}–{periods[-1]} 的 {len(DISCIPLINES)} 个学科表里都没有"
                         f"「{query}」。本地数据分不清两种情形：① 该校整校未进入 ESI；"
                         f"② 校名写法与 ESI 不一致（简写、多「学院/大学」后缀、中英文名不同）。"
                         f"请核对后重试；若该校确实未上榜，本节可留空（未改动任何数据）。"),
            })
            records.append(rec)
            continue
        key = _norm(got["en"])
        if key in seen:                                  # 同一所写两遍，只留一次
            continue
        seen.add(key)
        rec.update({"cn": got["cn"] or query, "en": got["en"], "match": got["how"]})
        records.append(rec)

    ok = [r for r in records if r["status"] == "ok"]
    targets = {_norm(r["en"]): r for r in ok}

    # ---- 逐期扫描
    scanned: dict[str, tuple[dict, bool]] = {p: _scan(p, discs, targets) for p in periods}
    missing = [p for p in periods if not scanned[p][1]]

    # ---- 填 counts：窗口内无数据的期次填 None（**不填 0**——0 是「本期没上榜」，语义不同）
    # 解析失败（absent / error）的学校也填 None：名字没对上时我们并不知道它上没上榜，
    # 填 0 等于替它下结论，图上会画出一条贴底的假曲线。
    for rec in records:
        if rec["status"] != "ok":
            rec["counts"] = [None] * len(periods)
            continue
        key = _norm(rec["en"])
        rec["counts"] = [None if p in missing else len(scanned[p][0][key]) for p in periods]

    # ---- 学科进出（相对上一期；相邻两期任一缺数据就跳过，不猜）
    for rec in ok:
        key = _norm(rec["en"])
        entered: list[dict] = []
        exited: list[dict] = []
        for i in range(1, len(periods)):
            prev, cur = scanned[periods[i - 1]], scanned[periods[i]]
            if not prev[1] or not cur[1]:
                continue
            before, now = prev[0][key], cur[0][key]
            for disc in sorted(now - before, key=_cn_key):
                entered.append({"period": periods[i], "disc": disc, "cn": cn_of(disc)})
            for disc in sorted(before - now, key=_cn_key):
                exited.append({"period": periods[i], "disc": disc, "cn": cn_of(disc)})
        rec["entered"], rec["exited"] = entered, exited

    # ---- 末期交集与「本校另有」
    last = periods[-1]
    sets_last = {r["cn"]: scanned[last][0][_norm(r["en"])] for r in ok} if last not in missing else {}
    common_set = set.intersection(*sets_last.values()) if sets_last else set()
    common = [d for d in discs if d in common_set]
    only = {cn: [d for d in discs if d in stems and d not in common_set]
            for cn, stems in sets_last.items()}

    # ---- 事件：窗口有缺口时整段不出（趋势语义已断，硬算出来的「拐点」是假的）
    if missing:
        found = _events.Events([], {"error": f"窗口内缺数据：{'、'.join(missing)}，不出事件"})
    else:
        found = _events.detect(
            periods,
            {r["cn"]: list(r["counts"]) for r in ok},
            {r["cn"]: {p: sorted(scanned[p][0][_norm(r["en"])]) for p in periods} for r in ok},
        )

    grid = {
        "counts": {r["cn"]: list(r["counts"]) for r in records},
        "sets": {r["cn"]: {p: sorted(scanned[p][0][_norm(r["en"])], key=_cn_key)
                           for p in periods} for r in ok},
    }

    summary = {
        "periods": periods,
        "schools": [{"cn": r["cn"], "status": r["status"], "counts": r["counts"]}
                    for r in records],
        "common_count": len(common),
        "events": [e["text"] for e in found],
    }

    return {
        "periods": periods,
        "missing": missing,
        "period_end": period_end,
        "disciplines": discs,
        "schools": records,
        "common": common,
        "only": only,
        "events": found,                    # Events（list 子类），保留 .meta 里的错误说明
        "grid": grid,
        "summary": summary,
        "source": {
            "dataset": peers._display_path(period_end, "").rstrip("/"),
            "period": period_end,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        },
    }
