# -*- coding: utf-8 -*-
"""qa 构建器（问文衡；SPEC §4 步骤 2 的构建器半边）。

规则版：报告同款句骨架 `sentences.build()` 出段 → 问句检索排序（命中段排前；
问句为空＝全部段；无命中＝前 3 段）→ 命中段文本即规则版正文。

三处口径（2026-09-29 修，rick 实问暴露）：
- **检索**：中文 2–4 字滑窗 + 报告别名（热点论文/高被引 → 顶尖论文），
  不再要求问句里带空格（旧版整句无空格＝零命中）；
- **手工槽**：状态库 `manual_inputs`（原 `out/<期次>/manual_inputs.json`）里馆员已填的值回填 `【手工：X】`；
  未填的槽位**所在分句丢掉**（2026-10-11 由「整句丢」放宽）——不把裸占位符端给读者，
  也不让模型看见，同时保住同句里没槽位的数据（如顶尖论文总数）；
- **证据**：模型轮看**全量段**（命中段排前），规则版仍只出命中段——
  问「热点论文」这类报告里有、命中算法可能够不着的题，模型也能找到段落作答。

2026-10-11 修（rick：「回答太死板，可溯源即可」）：
- **学科问题直答**：问句点到某个学科（如「化学的接近度」）时，从 `table2.csv` 拼一条
  **该学科的学科数据段**（论文/被引/CNCI/顶尖/阈值/**接近度（总被引÷阈值，系统换算）**/
  位次变化），规则版与模型轮都优先用它——不再只能倒报告段落或答「无法回答」；
- **来源到格**：学科段里的数字按值回指 `table2.csv#<学科>.<列>`（唯一命中）或
  `table2.csv#<学科>`（行级）；换算出的接近度指回「总被引÷阈值」；
- 系统提示同步放开：先直接答所问、语言简洁自然，数字仍一律走占位标记（可溯源）。

2026-10-12（票 02，行为保持）：
- **台账段换内核**：规则规划器（`_plan`）→ 取数引擎（`flexible.queries`，白名单规格）→
  证据装配（`_evidence`：文本 + 精确格指针，来源链直出）。数据面：本期 parquet 优先、
  监测表回落（`_view_for`）；台账缺/坏、单条规格失败 → 静默跳过（与 v1 一致）。
  对外行为与 v1 逐字一致（既有用例钉着；`_ledger_segments` 等手写段装配退休）。

2026-10-28（fc 定稿，写作轮原生工具环）：
- 模型可以**自主拉证据**：`_qa_tools` 给四件只读工具（series/at/events/overall_rank），
  schema 只发名字与馆员话术（零数字）；执行器校验参数（越权→拒：无数字人话＋refused
  回执，不回落）→ 与 `_ledger_evidence` 同款切窗 → 引擎取数 → 证据装配 →
  `NumberedText.append` 续号注册（精确台账格，fact=True）→ 返回占位面文本。
  模型只选（工具名+参数）不造；值只从引擎一条缝进来；同规格 memo 去重。
  视图拿不到就不挂工具（现状回落路径不变）；规则部署物理上无工具环。

来源登记：问句里的数字 → `question`；事实段里的数字 → 按值匹配 `overview_facts.json`
的具体键（product 指针），匹配不到的（句骨架里算出来的期号等）降到段落级指针。
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import time

from . import _record, _shield
from ._draft import RuleDraft
from ._numbered import NumberedText
from ._types import Receipt

try:                                        # 仓根在 sys.path 上（server / tests）
    from src import state_store
except ImportError:                         # 只有 src/ 在 sys.path 上（流水线内部）
    import state_store                      # type: ignore[no-redef]

#: 检索词里没有信息量的常见词（切词后过滤）。
_STOP = {"什么", "多少", "几门", "几个", "哪些", "这期", "本期", "请问", "怎么", "如何",
         "情况", "数量", "是多少", "有没有", "云南大学", "我校"}

#: 报告口径别名：题目里的近义说法 → 扩成报告用词（只扩检索词，不改原文）。
_ALIAS = {
    "热点论文": "顶尖论文", "高被引论文": "顶尖论文", "高被引": "顶尖论文", "顶刊": "顶尖论文",
    "百分之一": "前 1%", "前1%": "前 1%", "千分之一": "1‰",
}

#: 学科行字段 → 中文名（学科数据段与来源标签共用）。
_FIELD_CN = {
    "papers": "论文数", "total_cites": "总被引频次", "cnci": "CNCI",
    "top_papers": "顶尖论文", "thr_1pct": "前 1% 阈值", "thr_1pct_gap": "前 1% 阈值差",
    "thr_1permille": "前 1‰ 阈值", "permille_rank": "千分位",
    "prox_change": "接近度较上期", "rank_cn_change": "国内排名",
}

#: 数据面视图缓存（`_view_for`；键含 mtime/体积，台账一改自动失效）。
_VIEW_CACHE: dict = {}


def _view_for(root, period):
    """数据面视图装配（票 02 已定；2026-10-13 起回落改母本）：本期 parquet 优先 → 母本回落 → None。

    - 本期 `out/<期次>/ledger_long.parquet` 在 → `DataSource`（该快照覆盖本期）；
    - 否则 `input/<母本>` 在 → `WorkbookView`（现场只读解析，带 mtime 缓存；
      消费侧按 `<= period` 切窗，母本里更晚的期次读不到——"07 不读 09"）；
    - 都没有 → None（调用方静默回落报告产物——不报错、不编数）。
    """
    out_root = pathlib.Path(root)
    d = out_root / str(period)
    if (d / "ledger_long.parquet").is_file():
        try:
            from flexible.datasource import DataSource             # noqa: PLC0415
            return DataSource(d)
        except Exception:                                          # noqa: BLE001
            return None
    import ledger as ledger_mod                                    # noqa: PLC0415
    path = ledger_mod.runtime_path(out_root.parent)
    if not path.exists():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _VIEW_CACHE:
        return _VIEW_CACHE[key]
    try:
        from flexible.workbook import WorkbookView                 # noqa: PLC0415
        view = WorkbookView(path)
    except Exception:                                              # noqa: BLE001
        return None
    _VIEW_CACHE.clear()
    _VIEW_CACHE[key] = view
    return view


def _ledger_evidence(root, period, question, disc_items, history=(), focus_period="",
                     view=None):
    """台账证据（票 02/03 内核）：规划（规则→模型）→ 引擎取数 → 证据装配。

    `focus_period`＝问句点名的那一期（P0-1，2026-10-14）：规则面据此出 `at` 单值规格。
    `view`＝调用方已装配的数据面视图（build 与工具面共用一次 `_view_for`；None＝自取）。

    返回 `(texts, cells, plan)`：`{段key: 文本}`、`{段key: [(数字串, 表, 学科, 期次)]}`
    与规划摘要（票 04 进留痕）。台账缺/坏 → `({}, {}, None)`；单条 spec 失败静默跳过
    （回落报告产物，与 v1 行为一致）。
    """
    from . import _evidence, _plan                               # noqa: PLC0415

    if view is None:
        view = _view_for(root, period)
    if view is None:
        return {}, {}, None
    try:
        from flexible import queries                             # noqa: PLC0415
    except Exception:                                            # noqa: BLE001
        return {}, {}, None
    plan = _plan.plan(question, discs=[it["en"] for it in disc_items],
                      history=list(history or []), disciplines=list(view.disciplines),
                      period=str(focus_period or ""))
    results = []
    for spec in plan["specs"]:
        op = spec.get("op")
        args = {k: v for k, v in spec.items() if k != "op"}
        span = args.pop("span", None)
        if span == "recent":
            # 「最近六期」= **截至当期**的期次轴最后六列（与 v1 台账段同口径；空列由引擎按缺数跳过）。
            # 2026-10-13：数据面可能是全史母本（含更晚期次），必须按 <= 当期切窗——
            # "07 的报告不能读 09 的数据"在消费层强制。
            args["periods"] = [str(p) for p in view.periods if str(p) <= str(period)][-6:]
        if op == "at" and not args.get("period"):
            # 模型面 at 不带期次（零数字面）：系统补——本轮期次（2026-10-14 P0-1）。
            args["period"] = str(period)
        try:
            results.append(queries.execute(view, op, **args))
        except Exception:                                        # noqa: BLE001
            continue
    ev = _evidence.assemble(results, question)
    texts = {key: text for key, text in ev["chunks"]}
    return texts, ev["cells"], plan


def _ledger_source(cells, key, value):
    """cells → 台账来源字段（唯一命中到格；多期同值降行级；否则段落级）。

    `_ledger_evidence` 的编号注册与工具环的续号注册共用这一份指针语义
    （kind=ledger_cell、fact=True——工具结果也是本期事实，越题判定据此放行）。
    """
    hits = [(sheet, subj, p) for (v, sheet, subj, p) in cells if v == value]
    if len(hits) == 1:
        sheet, subj, p = hits[0]
        return {"kind": "ledger_cell",
                "pointer": f"台账#{sheet}/{subj}/{p}",
                "label": f"台账 · {sheet} · {subj} · {p}",
                "detail": "云大监测表（台账，运行期只读；与逐格溯源同一读取面）",
                "fact": True}
    if hits:
        sheet, subj, _p = hits[0]
        return {"kind": "ledger_cell", "pointer": f"台账#{sheet}/{subj}",
                "label": f"台账 · {sheet} · {subj}",
                "detail": "多期同值，未唯一到格", "fact": True}
    return {"kind": "ledger_cell", "pointer": f"台账#{key}",
            "label": f"台账 · {key}",
            "detail": "数字属于该台账序列", "fact": True}


# ================================================================ 原生工具环（2026-10-28）

#: 模型可见的**五件**只读工具（名字 → 引擎 op）。全部只读：没有写操作这一支。
#: 第五件 `query_compare` 是为什么加的（2026-10-29 实测）：模型看不见真值、只看得见
#: 占位标记，比较类问题（「谁的 CNCI 更高」）它算不了——把「谁好谁差」交回引擎排序，
#: 模型只读这个顺序。**系统不替模型算，模型也不替读者臆断。**
_TOOL_OPS = {"query_series": "series", "query_at": "at",
             "query_events": "events", "query_overall_rank": "overall_rank",
             "query_compare": "compare"}

#: 指标脸面（工具面零数字——`MODEL_METRICS` 的中文名带「1%」，不能直接进 schema）：
#: 别名 → (短名, 话术)。短名进回执摘要（给人看），话术进工具说明（给模型看）。
_METRIC_FACE = {
    "proximity": ("接近度", "接近度（被引与门槛的比值）"),
    "threshold": ("前百分之一阈值", "进入前百分之一所需的被引门槛"),
    "threshold_permille": ("前千分之一阈值", "进入前千分之一所需的被引门槛"),
    "total_cites": ("总被引频次", "总被引频次"),
    "papers": ("论文数", "论文数"),
    "cnci": ("CNCI", "篇均被引影响力"),
    "top_papers": ("顶尖论文", "顶尖论文数"),
    "rank_cn": ("国内排名", "国内排名"),
    "rank_intl": ("国际排名", "国际排名"),
}

#: 默认看最近若干期（与台账段「最近六期」同口径）。
_SPAN_N = 6


def _metric_index() -> dict:
    """别名 → (引擎规范名, 短名, 话术)：与 `_plan.MODEL_METRICS` 同一张表（唯一口径）。"""
    from . import _plan                                        # noqa: PLC0415

    out = {}
    for alias, canon, _cn in _plan.MODEL_METRICS:
        short, hint = _METRIC_FACE.get(alias, (canon, canon))
        out[alias] = (canon, short, hint)
    return out


def _fn(name, desc, props, required) -> dict:
    """一件工具的 OpenAI function schema（只有名字与话术，零数字）。"""
    return {"type": "function",
            "function": {"name": name, "description": desc,
                         "parameters": {"type": "object", "properties": props,
                                        "required": required}}}


def _qa_tools(view) -> tuple:
    """五件只读工具的 schema：模型只看见「能查什么」，看不见任何数值。"""
    metrics = _metric_index()
    discs = [str(d) for d in (view.disciplines or ())]
    span = {"type": "string", "enum": ["recent", "all"],
            "description": "recent＝最近若干期（默认）；all＝台账里的全部期次"}
    metric = {"type": "string", "enum": sorted(metrics),
              "description": "；".join(f"{a}＝{face[2]}" for a, face in metrics.items())}
    disc = {"type": "string", "enum": discs, "description": "学科（英文名；只能从里面选）"}
    return (
        _fn("query_series", "查某学科某指标在最近若干期的取值序列（问走势、变化时用）",
            {"metric": metric, "disc": disc, "span": span}, ["metric", "disc"]),
        _fn("query_at", "查某学科某指标在本期的单值（期次由系统补，不要自己写期次）",
            {"metric": metric, "disc": disc}, ["metric", "disc"]),
        _fn("query_events", "查某学科进出 ESI 前百分之一名单的事件",
            {"disc": disc}, ["disc"]),
        _fn("query_overall_rank", "查本校整体排名（国际/国内）在最近若干期的序列",
            {"span": span}, []),
        _fn("query_compare",
            "查若干学科在同一期的某个指标谁高谁低（结果已按从好到差排好，读完就能比；"
            "要比的学科放 discs，不填就是全部学科）",
            {"metric": metric,
             "discs": {"type": "array", "items": {"enum": discs},
                       "description": "要比的学科（英文名列表）"}}, ["metric"]),
    )


def _qa_executor(view, period, number):
    """宿主执行器（写作轮原生工具环）：校验 → 切窗 → 引擎取数 → 装配 → 续号注册。

    - **越权/取不到 → 拒**：返回一句无数字人话 + `refused` 回执，**不回落**——
      模型收到拒答句后仍可作答（拒不是失败）；
    - 取到 → 结果文本先经 `NumberedText.append` 续号注册（数字进同一套编号，
      来源指到台账格），交出去的已经是占位面——外发零数字由构造保证；
    - 同规格 memo：第二次直接复用已注册的占位文本，不再注册新编号。
    """
    metrics = _metric_index()
    memo: dict = {}

    def receipt(name, args, summary, t0, *, ok, refused):
        return Receipt(tool=name, label="查台账", args_digest=_record.digest(args),
                       summary=summary, ok=ok, refused=refused,
                       elapsed_ms=int((time.time() - t0) * 1000))

    def refuse(name, args, why, t0):
        return (f"该查询不在可查范围（{why}）。请依据已有数据作答。",
                receipt(name, args, "查台账", t0, ok=False, refused=True))

    def disc_cn(en):
        try:
            from flexible.datasource import cn_name               # noqa: PLC0415

            return cn_name(en)
        except Exception:                                         # noqa: BLE001
            return str(en or "")

    def run(call):
        t0 = time.time()
        name = str((call or {}).get("name") or "")
        args = (call or {}).get("arguments") or {}
        args = dict(args) if isinstance(args, dict) else {}
        op = _TOOL_OPS.get(name)
        if op is None:
            return refuse(name, args, "未登记的查询", t0)
        canon, metric_cn = "", ""
        picked: list = []          # compare 要比的学科；其余 op 恒空（qargs 字面量全体求值）
        disc = str(args.get("disc") or "")
        if op in ("series", "at"):
            got = metrics.get(str(args.get("metric") or ""))
            if got is None:
                return refuse(name, args, "指标不在可查范围", t0)
            canon, metric_cn, _hint = got
        elif op == "compare":
            got = metrics.get(str(args.get("metric") or ""))
            if got is None:
                return refuse(name, args, "指标不在可查范围", t0)
            canon, metric_cn, _hint = got
            got_picked = args.get("discs")
            picked = ([str(x) for x in got_picked] if isinstance(got_picked, list) else [])
            bad = [d for d in picked if d not in set(view.disciplines or ())]
            if bad:
                return refuse(name, args, "学科不在可查范围", t0)
        span = str(args.get("span") or "recent")
        if span not in ("recent", "all"):
            return refuse(name, args, "期次范围不在可查范围", t0)
        if op in ("series", "at", "events") and disc not in set(view.disciplines or ()):
            return refuse(name, args, "学科不在可查范围", t0)

        # 切窗：数据面可能是全史母本——"本期报告不读更晚期次"（与台账段同款）。
        window = [str(p) for p in (view.periods or ()) if str(p) <= str(period)]
        if span == "recent":
            window = window[-_SPAN_N:]
        qargs = {"series": {"metric": canon, "disc": disc, "periods": window},
                 "at": {"metric": canon, "disc": disc, "period": str(period)},
                 "events": {"disc": disc},
                 "compare": {"metric": canon, "discs": picked or None,
                             "period": str(period)},
                 "overall_rank": {"periods": window}}[op]
        summary = ("查 云大整体排名" if op == "overall_rank"
                   else f"查 {disc_cn(disc)}·进出事件" if op == "events"
                   else f"查 {metric_cn}·横比" if op == "compare"
                   else f"查 {disc_cn(disc)}·{metric_cn}")
        memo_key = (op, tuple(sorted((k, str(v)) for k, v in qargs.items())))
        if memo_key in memo:
            return memo[memo_key], receipt(name, args, summary, t0, ok=True, refused=False)

        try:
            from flexible import queries                          # noqa: PLC0415
            from . import _evidence                               # noqa: PLC0415

            res = queries.execute(view, op, **qargs)
            ev = _evidence.assemble([res], "")
        except Exception:                                         # noqa: BLE001
            return refuse(name, args, "本期无可用数据", t0)
        chunks = list(ev.get("chunks") or [])
        if not chunks:
            return refuse(name, args, "本期无可用数据", t0)
        key, text = chunks[0]
        cells = (ev.get("cells") or {}).get(key) or []
        nt = NumberedText.append(number, [text],
                                 lambda _ti, _pos, value: _ledger_source(cells, key, value))
        protected = nt.texts[-1]
        memo[memo_key] = protected
        return protected, receipt(name, args, summary, t0, ok=True, refused=False)

    return run


def _load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _terms(question: str) -> list:
    """问句 → 检索词：空格词 + 中文 2–4 字滑窗（过滤停用词），并做别名扩展。"""
    q = str(question)
    for src, dst in _ALIAS.items():
        if src in q:
            q = q + " " + dst
    terms = set()
    for w in re.split(r"[，。？、！；：\s]+", q):
        w = w.strip()
        if len(w) < 2 or w in _STOP:
            continue
        terms.add(w)
        for n in (2, 3, 4):
            for i in range(len(w) - n + 1):
                g = w[i:i + n]
                if g not in _STOP:
                    terms.add(g)
    return sorted(terms)


def _match(texts: dict, question: str) -> dict:
    """命中按分数降序（长词权重高）；无命中取前 3 段（与旧版行为一致）。"""
    if not question:
        return dict(texts)
    terms = _terms(question)
    scored = {}
    for k, v in texts.items():
        hay = f"{k}\n{v}"
        score = sum(len(t) for t in terms if t in hay)
        if score > 0:
            scored[k] = score
    if scored:
        return {k: texts[k] for k in sorted(scored, key=lambda x: -scored[x])}
    return dict(list(texts.items())[:3])


#: 规则版排版（2026-10-29 rick：规则作答是一堵墙，要分段落＋小标题，像助手答卷）。
#: 键 → 小标题；连续同类只出一次标题（不认识的键＝无标题，只当普通段落）。
#: ⚠ 标签不得含测试断言为「不应出现」的词（如「国际排名」「顶尖论文」只在对应段存在时才出）。
_SECTION_OF = {
    "p1": "总体情况", "p2": "排名变化", "p3": "排名变化", "p4": "排名变化",
    "trend": "排名变化",
    "situation_head": "学科进展", "situation": "学科进展",
    "forecast_p1": "学科预测", "forecast_p2": "学科预测", "forecast_p3": "学科预测",
    "top_section": "顶尖论文", "province_p": "省域情况",
}
#: 报告封面元数据（期号 / 月份 / 表题）——聊天回答里是噪音，规则版不出。
_META_SKIP = {"cover_issue", "cover_month", "table2_title"}


def _section_label(key):
    """键 → 小标题（无则空串）。学科段用学科名、台账段用「台账取数」。"""
    if key in _SECTION_OF:
        return _SECTION_OF[key]
    sk = str(key)
    if sk.startswith("学科数据·"):
        return sk.split("·", 1)[1]
    if sk.startswith("台账"):
        return "台账取数"
    return ""


def _format_rule(keys, texts):
    """规则段 → 带小标题的多段正文。只加标题与空行，不动数字、不动顺序。"""
    out, last = [], ""
    for k in keys:
        if k in _META_SKIP or k not in texts:
            continue
        sec = _section_label(k)
        if sec and sec != last:
            out.append(f"### {sec}")
            last = sec
        out.append(texts[k])
    return "\n\n".join(out)


def _disc_rows(d):
    """`table2.csv` → `[{en, cn, row}]`（缺件/坏件 → []；不猜）。"""
    try:
        with (pathlib.Path(d) / "table2.csv").open(encoding="utf-8-sig", newline="") as f:
            raw = [dict(r) for r in csv.DictReader(f)]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    try:
        from parse_ledger import DISCIPLINES_CN                     # noqa: PLC0415
    except ImportError:                                             # pragma: no cover
        DISCIPLINES_CN = {}
    out = []
    for row in raw:
        en = str(row.get("discipline") or "").strip()
        if not en:
            continue
        out.append({"en": en, "cn": DISCIPLINES_CN.get(en, en), "row": row})
    return out


def _disc_hits(question, rows):
    """问句点到的学科（中文名整词命中优先长名；英文名同样认）。可多科。"""
    q = str(question or "")
    low = q.lower()
    masked = q
    hits = []
    for item in sorted(rows, key=lambda x: -len(x["cn"])):
        if item["cn"] in masked or (item["en"] and item["en"].lower() in low):
            hits.append(item)
            masked = masked.replace(item["cn"], "＃")               # 长名先吃，防「化学」截胡「生物与生物化学」
    return hits


def _row_num(row, key, cast=float):
    """行里的数值字段 → cast(值)；空/坏 → None（不猜）。默认 float（CNCI 等小数）。"""
    try:
        return cast(float(str(row.get(key, "")).strip()))
    except (TypeError, ValueError):
        return None


def _disc_segment(item, entered=None):
    """一个学科的直答段（确定性；换算值由本系统算，模型只引用不计算）。

    `entered`：本期是否已进入前 1%（权威来源 `wide/entered_1pct.parquet`；None＝缺表不猜）。
    2026-10-15 修（rick 实问暴露）：原句尾带「（＝总被引÷阈值；超过 100% 即已进入前 1%）」，
    模型把**条件**拼成了断言（"88.01%，已超过 100%，即已进入前 1%"）。改为给确定值——
    「阈值差」（table2 的 `thr_1pct_gap`：还差/高出 N 次被引）＋权威进入状态；
    不再出现「超过 100%」字样（模型再写就成游离数字，盾会拒）。
    """
    row = item["row"]
    parts = [f"{item['cn']}（{item['en']}）本期数据："]
    papers = _row_num(row, "papers", int)
    cites = _row_num(row, "total_cites", int)
    cnci = _row_num(row, "cnci", float)
    top = _row_num(row, "top_papers", int)
    thr = _row_num(row, "thr_1pct", int)
    thr_m = _row_num(row, "thr_1permille", int)
    if papers is not None:
        parts.append(f"论文数 {papers} 篇；")
    if cites is not None:
        parts.append(f"总被引频次 {cites}；")
    if cnci is not None:
        parts.append(f"CNCI {cnci:.2f}；")
    if top is not None:
        parts.append(f"顶尖论文 {top} 篇；")
    if cites is not None and thr:
        parts.append(f"前 1% 阈值 {thr}，前 1% 接近度 {cites / thr * 100:.2f}%（＝总被引÷阈值）；")
        gap = _row_num(row, "thr_1pct_gap", int)
        tail = ""
        if gap is not None:
            if gap < 0:
                tail = f"距前 1% 阈值还差 {abs(gap)} 次被引"
            elif gap > 0:
                tail = f"高出前 1% 阈值 {gap} 次被引"
            else:
                tail = "正好达到前 1% 阈值"
        if entered is not None:
            tail += ("（ESI 口径：本期已进入前 1%）" if entered
                     else "（ESI 口径：本期未进入前 1%）")
        if tail:
            parts.append(tail + "；")
    if cites is not None and thr_m:
        parts.append(f"前 1‰ 阈值 {thr_m}，前 1‰ 接近度 {cites / thr_m * 100:.2f}%；")
    if str(row.get("prox_change") or "").strip():
        parts.append(f"接近度较上期 {str(row['prox_change']).strip()}；")
    if str(row.get("rank_cn_change") or "").strip():
        parts.append(f"国内排名 {str(row['rank_cn_change']).strip()}。")
    return "".join(parts).rstrip("；。") + "。"


def _entered_for(d, discs):
    """本期进入状态（权威 `wide/entered_1pct.parquet`；缺表/缺列 → {}，不猜、不回落接近度）。"""
    p = pathlib.Path(d) / "wide" / "entered_1pct.parquet"
    if not p.is_file():
        return {}
    try:
        import pandas as pd                                        # noqa: PLC0415
        df = pd.read_parquet(p)
        col = str(pathlib.Path(d).name)
        if col not in df.columns:
            return {}
        return {en: (float(df.loc[en, col]) > 0) for en in discs if en in df.index}
    except Exception:                                              # noqa: BLE001
        return {}


def _disc_index(items):
    """(学科 en) → {值串: [字段, …]}：学科段里的数字按值回指 table2 的格。"""
    idx = {}
    for item in items:
        row = item["row"]
        per: dict = {}

        def add(value_str, key):
            bucket = per.setdefault(value_str, [])
            if key not in bucket:                                   # 同键同值去重（如阈值差的正负变体）
                bucket.append(key)

        for key in _FIELD_CN:
            raw = str(row.get(key) or "").strip()
            if not raw:
                continue
            try:
                val = float(raw)
            except ValueError:
                for m in _shield.NUM.finditer(raw):                 # "154/↓1" 这类串里的数字
                    add(m.group(0), key)
                continue
            for v in {f"{val:g}", f"{val:.2f}", f"{val:.1f}"}:
                add(v, key)
            if key == "thr_1pct_gap":                               # 直答段写「还差/高出 N」（无符号）
                for v in {f"{abs(val):g}", f"{abs(val):.2f}", f"{abs(val):.1f}"}:
                    add(v, key)
        cites, thr = _row_num(row, "total_cites"), _row_num(row, "thr_1pct")
        thr_m = _row_num(row, "thr_1permille")
        if cites and thr:
            add(f"{cites / thr * 100:.2f}", "derived_1pct")
        if cites and thr_m:
            add(f"{cites / thr_m * 100:.2f}", "derived_1permille")
        idx[item["en"]] = per
    return idx


def _manual_values(root, period) -> dict:
    """馆员已填的手工槽：`{"<段key>": {字段: 值}}`（键形如 `正文/p4::学科数`，存在状态库）。

    填写已入库（ADR-0012）：库在 `out/_state/`，由 `state_store.db_path` 唯一口径解出；
    库不存在 → 空（读口不建库，与旧文件缺失同口径）。
    """
    db = state_store.db_path(pathlib.Path(root) / str(period))
    mi = state_store.get_fills(db, str(period)) or {}
    out: dict = {}
    for key, item in mi.items():
        if "::" not in str(key):
            continue
        sec, field = str(key).split("::", 1)
        sec = sec.split("/")[-1]
        val = item.get("value") if isinstance(item, dict) else item
        if val not in (None, ""):
            out.setdefault(sec, {})[field] = str(val)
    return out


def _apply_manual(text: str, values: dict) -> str:
    """`【手工：X】` → 已填值；未填的槽位**所在分句丢掉**（不端裸占位符）。

    2026-10-11 修（rick：回答太死板）：由「整句丢」改「分句丢」——
    同一句里没槽位的分句照常保留。此前「本期我校共有 291 篇顶尖论文…覆盖【手工：学科数】个学科」
    整句被丢，问「多少篇」就答不出来了；现在只丢带槽的那一小句。
    """
    if "【手工：" not in text:
        return text
    out = []
    for sentence in re.split(r"(?<=[。；])", text):
        kept, dropped = [], False
        for piece in re.split(r"(?<=[，])", sentence):
            fields = re.findall(r"【手工：([^】]+)】", piece)
            if fields and any(f not in values for f in fields):
                dropped = True
                continue                                    # 未填槽位所在分句丢掉
            kept.append(re.sub(r"【手工：([^】]+)】",
                               lambda m: values.get(m.group(1), m.group(0)), piece))
        if not kept:
            continue
        piece_text = "".join(kept)
        if dropped and piece_text.rstrip().endswith(("，", "、", "；")):
            piece_text = piece_text.rstrip()[:-1] + "。"
        out.append(piece_text)
    return "".join(out)


def _fact_index(facts: dict) -> dict:
    """overview_facts.json → {数字串: [键路径, ...]}（按值匹配来源；字符串里的数字也索引）。

    值级指针只在**唯一命中**时使用；多个字段同值（或单字数字）时降段落级——
    宁可粗一点，不可指错（R-3：qa 数字到格后置）。
    """
    idx: dict = {}

    def add(value_str: str, path: str):
        idx.setdefault(value_str, []).append(path)

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, bool) or obj is None:
            return
        elif isinstance(obj, (int, float)):
            for variant in {str(obj), f"{obj:g}", f"{obj:.2f}", f"{obj:.1f}"}:
                add(variant, path)
        elif isinstance(obj, str):
            for m in _shield.NUM.finditer(obj):
                add(m.group(0), path)

    walk(facts, "")
    return idx


def _source_fields(facts_idx: dict, num: str, section_key: str) -> dict:
    """证据段数字的来源字段（编号/value 由 `NumberedText` 统一写入）。"""
    paths = facts_idx.get(num) or []
    if len(paths) == 1 and len(num) >= 2:
        path = paths[0]
        return {"kind": "product", "pointer": f"overview_facts.json#{path}",
                "label": f"本期事实 · {path}",
                "detail": "overview_facts.json（本期派生事实）"}
    return {"kind": "product", "pointer": f"overview_facts.json#{section_key}",
            "label": f"本期事实 · 段落 {section_key}",
            "detail": "数字属于该段正文；未唯一对应到 facts 字段（或由句骨架推导）"}


def build(root, period, payload) -> RuleDraft:
    """期次产物 + 问句 → RuleDraft。产物缺失/坏了 → 抛异常（核心按 unavailable 处理）。"""
    d = pathlib.Path(root) / str(period)
    facts = _load_json(d / "overview_facts.json")
    if not isinstance(facts, dict) or not facts:
        raise FileNotFoundError(f"该期没有可用的 overview_facts.json：{d}")
    meta = _load_json(d / "meta.json", default={}) or {}
    p_cur = str(meta.get("period_current") or period)
    p_prev = str(meta.get("period_prev") or "")
    if not p_prev:
        raise ValueError(f"meta.json 缺 period_prev（无法生成 {period} 对比句）：{d}")

    import sentences                                                # noqa: PLC0415

    # 预测章文字与报告同源：目标学科（report_subjects，改选优先）+ 模型说明句都读产物
    # （2026-10-16；缺文件回落「接近度前二 + 手工槽」，与老行为一致）
    fm = _load_json(d / "forecast_charts.json", default={}) or {}
    values = _manual_values(root, period)
    base_texts = {k: _apply_manual(v, values.get(k, {}))
                  for k, v in sentences.build(
                      facts, p_cur, p_prev,
                      forecast=fm.get("charts"),
                      targets=fm.get("report_subjects")).items()}

    question = str(payload.get("question") or "").strip()
    # 问句点名的那一期（P0-1，2026-10-14）：解析口径**复用对话前门**（唯一口径），
    # 只在证据与任务里明示；本轮产物基期仍由服务器路由决定（不换基）。
    from . import _dialog                                          # noqa: PLC0415
    _parsed = _dialog.parse(question,
                            today=_dialog.parse_today(payload.get("today")))
    focus_period = _parsed.period if _parsed.case == "period" else ""
    # 对话上文（2026-10-12 rick 实问「这是几月的」）：追问要靠它解指代——
    # 只用来理解（「那物理学呢」「这是几月的」），不引用其中数字
    # （上文的数字在盾里走「来自提问」的来源，不算本期事实）。
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    context_lines = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("text") or "").strip()[:180]
        if snippet:
            context_lines.append(("用户" if item.get("who") == "me" else "文衡") + "：" + snippet)
    matched = _match(base_texts, question)

    # ---- 学科问题直答段（2026-10-11）：问句点到哪个学科，就先给哪个学科的数据行 ----
    disc_items = _disc_hits(question, _disc_rows(d))
    entered_map = _entered_for(d, [it["en"] for it in disc_items])
    disc_texts = {f"学科数据·{it['cn']}": _disc_segment(it, entered=entered_map.get(it["en"]))
                  for it in disc_items}
    disc_idx = _disc_index(disc_items)

    # ---- 台账段（票 02/03 内核）：规划（规则→模型）→ 引擎取数 → 证据装配 ----
    # 视图取一次：台账段与工具面共用（工具面的学科白名单就是它的数据范围）。
    view = _view_for(root, period)
    ledger_texts, ledger_cells, ledger_plan = _ledger_evidence(
        root, period, question, disc_items, history=history,
        focus_period=focus_period, view=view)
    n_led = len(ledger_texts)

    texts_all = {**base_texts, **disc_texts, **ledger_texts}
    # 证据＝台账段 + 学科段 + 命中段优先 + 其余段（模型可自找）；
    # 规则版＝台账段（有则）+ 学科段（有则），否则命中段。
    ordered = list(ledger_texts) + list(disc_texts) + list(matched) + \
        [k for k in texts_all if k not in matched and k not in disc_texts
         and k not in ledger_texts]
    rule_keys = (list(ledger_texts) + list(disc_texts)) if (ledger_texts or disc_texts) \
        else list(matched)
    # 封面元数据（期号/月份/表题）是聊天噪音：从规则版剔掉；全被剔空则保留，避免空回答。
    _rk = [k for k in rule_keys if k not in _META_SKIP]
    if _rk:
        rule_keys = _rk
    rule_set = set(rule_keys)
    # 上文进**编号之前**的首个区块：它的数字必须过盾（否则模型一复述就被判「游离数字」）。
    # P0-1（2026-10-14）：问句点名了期次 → 任务首行**明示**（写手不必自己再解「5月」）。
    task_head = question
    if focus_period:
        task_head = f"本次问题指向期次 {focus_period}（已解析）。\n{question}"
    first_chunk = task_head
    if context_lines:
        first_chunk = ("对话上文（只用来理解指代，不要引用其中数字）：\n"
                       + "\n".join(context_lines) + "\n\n本次问题：" + task_head)
    chunks = [first_chunk] + [texts_all[k] for k in ordered]
    facts_idx = _fact_index(facts)

    def register(ti, _pos, value):
        """问句数字不是「本期事实」；证据段数字是（越题判定据此）。
        台账段（前 n_led 段）→ 指回台账的格；学科段 → table2 的格；其余 → facts 字段。"""
        if ti == 0:
            return {"kind": "fact", "pointer": "question", "label": "来自提问",
                    "detail": "提问中出现的数字", "fact": False}
        seg = ti - 1
        if seg < n_led:
            key = ordered[seg]
            cells = ledger_cells.get(key) or []
            hits = [(sheet, subj, period) for (v, sheet, subj, period) in cells if v == value]
            if len(hits) == 1:
                sheet, subj, period = hits[0]
                return {"kind": "ledger_cell",
                        "pointer": f"台账#{sheet}/{subj}/{period}",
                        "label": f"台账 · {sheet} · {subj} · {period}",
                        "detail": "云大监测表（台账，运行期只读；与逐格溯源同一读取面）",
                        "fact": True}
            if hits:
                sheet, subj, _p = hits[0]
                return {"kind": "ledger_cell", "pointer": f"台账#{sheet}/{subj}",
                        "label": f"台账 · {sheet} · {subj}",
                        "detail": "多期同值，未唯一到格", "fact": True}
            return {"kind": "ledger_cell", "pointer": f"台账#{key}",
                    "label": f"台账 · {key}",
                    "detail": "数字属于该台账序列", "fact": True}
        disc_seg = seg - n_led
        if disc_seg < len(disc_items):
            item = disc_items[disc_seg]
            keys = disc_idx.get(item["en"], {}).get(value) or []
            if len(keys) == 1 and len(value) >= 2:      # 单字数字（如「前 1%」的 1）不指格
                key = keys[0]
                if key.startswith("derived"):
                    label = "前 1% 接近度" if key.endswith("1pct") else "前 1‰ 接近度"
                    return {"kind": "product",
                            "pointer": f"table2.csv#{item['en']}（总被引÷阈值）",
                            "label": f"学科表 · {item['cn']} · {label}（系统换算）",
                            "detail": "table2.csv（接近度＝总被引 ÷ 阈值，系统换算）",
                            "fact": True}
                return {"kind": "product", "pointer": f"table2.csv#{item['en']}.{key}",
                        "label": f"学科表 · {item['cn']} · {_FIELD_CN.get(key, key)}",
                        "detail": "table2.csv（学科大表）", "fact": True}
            return {"kind": "product", "pointer": f"table2.csv#{item['en']}",
                    "label": f"学科表 · {item['cn']}",
                    "detail": "数字属于该学科行（未唯一对应到列）", "fact": True}
        fields = _source_fields(facts_idx, value, ordered[seg])
        fields["fact"] = True
        return fields

    # 编号与来源注册同一遍：手写 k 计数器与运行期 assert 就此删除。
    number = NumberedText.of(chunks, register)

    task = number.texts[0]
    if not task:                          # 无问句：给模型一个明确的概述任务
        task = "（未提供具体问题）请依据参考数据概述本期要点。"

    # ---- 原生工具环（2026-10-28）：视图在就挂四件只读工具，让模型自己拉证据 ----
    # 视图拿不到 → 不挂（现状路径逐字不变）；规则部署物理上没有工具环（RuleBrain 不看 tools）。
    tools = ()
    execute = None
    max_steps = 1
    if view is not None:
        try:
            tools = _qa_tools(view)
        except Exception:                                         # noqa: BLE001
            tools = ()
        if tools:
            execute = _qa_executor(view, period, number)
            # 4＝「取证 → 补证 → 再补 → 作答」的余量：真模型常要逐个学科拉数再对比，
            # 步数给少了会把正常的多步取证判成「连续请求工具未作答」而误回落（实测 2026-10-29）。
            max_steps = 4

    return RuleDraft(
        rule_text=_format_rule(rule_keys, texts_all),
        number=number,
        rule_protected="\n\n".join(number.texts[1 + i]
                                   for i, key in enumerate(ordered) if key in rule_set),
        parts=(),
        task=task,
        evidence=tuple(number.texts[1:]),
        plan=ledger_plan,
        tools=tools,
        execute=execute,
        max_steps=max_steps,
    )
