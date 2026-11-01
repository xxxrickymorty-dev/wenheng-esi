# -*- coding: utf-8 -*-
"""监测版·校次事实层（20261101 C6）：一校在一期的站位事实，唯一派生。

输入缓存（report.load_cache / build_cache 产物）＋英文校名，输出该校在该期的事实集：
各学科上榜/未上榜、rank/cn_rank（随行值）、前 1%/前 1‰ 状态、接近度原始量、进位事件
（first1/firstpm 及其期次）。原先 report._report_data / compare._school_row /
insight.facts_of 三处平行派生、进位事件两份判定（report 趋势章时间轴与 insight 进位
事实行），自本模块起收敛为一份；report/compare/insight 只消费事实，渲染出口各留各的。
纯函数层：零 LLM、零网络、零渲染，一切数字可回溯到缓存（→包内原始表）。

差异裁决（数值派生以 report._report_data 为基准，20261101）：
- entered/near 以 prox（被引÷前 1% 阈值）判定：prox≥1 入 entered、prox<1 入 near；
  thr1 缺失或为 0 → prox 不可算（None），两名单都不进。compare/insight 原实现
  （thr1 存在才比较）与此一致；report 原实现会把 thr1 缺失行归入 near 并在渲染期
  TypeError——真实缓存 fields/thr1 同源同键，不存在该形态，无从保留。
- 进位事件取 report 版域（仅判本期在榜、序列里存在有 rank 期次的学科）；firstpm
  判定带 rank 缺失防御（原 report 版遇 m 有而 rank 缺的期会 TypeError，采纳 insight
  版的防御语义）。insight 侧随之收紧：全序列无 rank 的学科不再出进位事实行
  （真实趋势库不存在该形态）。
"""
from __future__ import annotations


def school_facts(cache: dict, en: str) -> dict:
    """一校在该期的站位事实。en＝ESI 英文校名（调用方先经 schools.find 解析）。

    名单校验不在本层（名单外校由消费者按各自语义处置：report 抛 KeyError、
    compare/insight 返回空）。返回（列表/字典保持 cache["fields"] 的键序，miss 例外
    ——按 report.STEMS 序）：
    {
      "en": en,
      "total": 机构总表行 [名称, 总排名, 论文, 总被引, 篇均, 高被引] 或 None，
      "present": {stem: 行}，22 学科榜内搜到的学科行
                 （行＝[rank, cn_rank, 论文, 被引, 篇均, 高被引, 热点]），
      "prox": {stem: float|None}，接近度＝被引÷该学科前 1% 机构阈值（thr1 缺/0→None），
      "entered": [stem…]，已进前 1%（prox≥1），
      "near": [stem…]，可判定而未进前 1%（prox<1），
      "pm": [stem…]，进前 1‰（rank≤1‰ 线），
      "miss": [stem…]，未上榜学科（STEMS 序），
      "pairs": [(stem, 行)…]，上榜学科按被引降序（稳定排序，fields 序破平），
      "mine_sum": float，上榜学科论文合计（相对强度 RCA 分母），
      "neighbors": ±3 总排名邻近窗行（缓存原样；缺席 → []），
    }
    """
    from monitor import report as mr                              # noqa: PLC0415
    # 函数级 import：report（装配层）顶层 import 本模块，这里再模块级 import 会成环
    rows = {stem: d["schools"].get(en) for stem, d in cache["fields"].items()}
    present = {stem: r for stem, r in rows.items() if r}
    total = next((r for r in cache["cn_inst"] if r[0] == en), None)
    thr1 = cache["thr1"]
    prox: dict[str, float | None] = {}
    for stem, r in present.items():
        t1 = thr1.get(mr.norm(stem))
        prox[stem] = (r[3] / t1) if t1 else None
    entered = [stem for stem, px in prox.items() if px is not None and px >= 1]
    near = [stem for stem, px in prox.items() if px is not None and px < 1]
    pm = [stem for stem, r in present.items() if r[0] <= cache["fields"][stem]["line"]]
    return {
        "en": en, "total": total, "present": present, "prox": prox,
        "entered": entered, "near": near, "pm": pm,
        "miss": [stem for stem in mr.STEMS if stem not in present],
        "pairs": sorted(present.items(), key=lambda kv: -kv[1][3]),
        "mine_sum": sum((r[2] or 0.0) for r in present.values()),
        "neighbors": cache["neighbors"].get(en) or [],
    }


def entry_events(tr: dict, present: dict | set) -> dict[str, dict]:
    """进位事件唯一判定（原 report 时间轴 f1/fpm 与 insight 事实行 first1/firstpm 收敛）。

    tr＝`trend.combine(en)` 产物；present＝本期在榜学科（school_facts()["present"]）。
    仅判「本期在榜、序列非空、且序列里存在有 rank 的期次」的学科（report 版域——
    无排名无从谈进位）。返回 {stem: 事件}：
    {"first_seen": 序列首个有 rank 的期次, "n_seq": 序列期数,
     "judge0": 首个 thr1/cites 齐备期（report 的 pre＝档案起点前已入围 判定用）,
     "first1": 首次 被引≥前 1% 阈值 的期次（无 → None）,
     "firstpm": 首次 排名≤⌊(m+1)/10⌋ 的期次（无 → None）}
    """
    out: dict[str, dict] = {}
    for stem, seq in (tr.get("fields") or {}).items():
        if stem not in present or not seq:
            continue
        fs = next((f["period"] for f in seq if f.get("rank") is not None), None)
        if fs is None:
            continue
        judge0 = next((f["period"] for f in seq
                       if f.get("thr1") is not None and f.get("cites") is not None), None)
        first1 = next((f["period"] for f in seq
                       if f.get("thr1") is not None and f.get("cites") is not None
                       and f["cites"] >= f["thr1"]), None)
        firstpm = next((f["period"] for f in seq
                        if f.get("m") and f.get("rank") is not None
                        and f["rank"] <= (f["m"] + 1) // 10), None)
        out[stem] = {"first_seen": fs, "n_seq": len(seq), "judge0": judge0,
                     "first1": first1, "firstpm": firstpm}
    return out
