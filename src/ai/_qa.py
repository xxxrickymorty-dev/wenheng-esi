# -*- coding: utf-8 -*-
"""qa 构建器（问文衡；SPEC §4 步骤 2 的构建器半边）。

规则版：报告同款句骨架 `sentences.build()` 出段 → 问句检索排序（命中段排前；
问句为空＝全部段；无命中＝前 3 段）→ 命中段文本即规则版正文。

三处口径（2026-09-29 修，rick 实问暴露）：
- **检索**：中文 2–4 字滑窗 + 报告别名（热点论文/高被引 → 顶尖论文），
  不再要求问句里带空格（旧版整句无空格＝零命中）；
- **手工槽**：`out/<期次>/manual_inputs.json` 里馆员已填的值回填 `【手工：X】`；
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

来源登记：问句里的数字 → `question`；事实段里的数字 → 按值匹配 `overview_facts.json`
的具体键（product 指针），匹配不到的（句骨架里算出来的期号等）降到段落级指针。
"""
from __future__ import annotations

import csv
import json
import pathlib
import re

from . import _shield
from ._draft import RuleDraft
from ._numbered import NumberedText

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
    """数据面视图装配（票 02 已定）：本期 parquet 优先 → 本期监测表回落 → None。

    - 本期 `out/<期次>/ledger_long.parquet` 在 → `DataSource`（该快照覆盖本期）；
    - 否则 `input/<期次>/监测表.xlsx` 在 → `WorkbookView`（现场只读解析，带 mtime 缓存）；
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
    path = out_root.parent / "input" / str(period) / "监测表.xlsx"
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


def _ledger_evidence(root, period, question, disc_items):
    """台账证据（票 02 内核）：规则规划 → 引擎取数 → 证据装配。

    返回 `(texts, cells)`：`{段key: 文本}` 与 `{段key: [(数字串, 表, 学科, 期次)]}`。
    台账缺/坏、单条 spec 失败 → 静默跳过（回落报告产物，与 v1 行为一致）。
    """
    from . import _evidence, _plan                               # noqa: PLC0415

    view = _view_for(root, period)
    if view is None:
        return {}, {}
    try:
        from flexible import queries                             # noqa: PLC0415
    except Exception:                                            # noqa: BLE001
        return {}, {}
    plan = _plan.plan(question, discs=[it["en"] for it in disc_items])
    results = []
    for spec in plan["specs"]:
        op = spec.get("op")
        args = {k: v for k, v in spec.items() if k != "op"}
        span = args.pop("span", None)
        if span == "recent":
            # 「最近六期」= 期次轴的最后六列（与 v1 台账段同口径；空列由引擎按缺数跳过）
            args["periods"] = [str(p) for p in view.periods[-6:]]
        try:
            results.append(queries.execute(view, op, **args))
        except Exception:                                        # noqa: BLE001
            continue
    ev = _evidence.assemble(results, question)
    texts = {key: text for key, text in ev["chunks"]}
    return texts, ev["cells"]


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


def _disc_segment(item):
    """一个学科的直答段（确定性；换算值由本系统算，模型只引用不计算）。"""
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
        parts.append(f"前 1% 阈值 {thr}，前 1% 接近度 {cites / thr * 100:.2f}%"
                     "（＝总被引÷阈值；超过 100% 即已进入前 1%）；")
    if cites is not None and thr_m:
        parts.append(f"前 1‰ 阈值 {thr_m}，前 1‰ 接近度 {cites / thr_m * 100:.2f}%；")
    if str(row.get("prox_change") or "").strip():
        parts.append(f"接近度较上期 {str(row['prox_change']).strip()}；")
    if str(row.get("rank_cn_change") or "").strip():
        parts.append(f"国内排名 {str(row['rank_cn_change']).strip()}。")
    return "".join(parts).rstrip("；。") + "。"


def _disc_index(items):
    """(学科 en) → {值串: [字段, …]}：学科段里的数字按值回指 table2 的格。"""
    idx = {}
    for item in items:
        row = item["row"]
        per: dict = {}

        def add(value_str, key):
            per.setdefault(value_str, []).append(key)

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
        cites, thr = _row_num(row, "total_cites"), _row_num(row, "thr_1pct")
        thr_m = _row_num(row, "thr_1permille")
        if cites and thr:
            add(f"{cites / thr * 100:.2f}", "derived_1pct")
        if cites and thr_m:
            add(f"{cites / thr_m * 100:.2f}", "derived_1permille")
        idx[item["en"]] = per
    return idx


def _manual_values(root, period) -> dict:
    """馆员已填的手工槽：`{"<段key>": {字段: 值}}`（文件键形如 `正文/p4::学科数`）。"""
    mi = _load_json(pathlib.Path(root) / str(period) / "manual_inputs.json",
                    default={}) or {}
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

    values = _manual_values(root, period)
    base_texts = {k: _apply_manual(v, values.get(k, {}))
                  for k, v in sentences.build(facts, p_cur, p_prev).items()}

    question = str(payload.get("question") or "").strip()
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
    disc_texts = {f"学科数据·{it['cn']}": _disc_segment(it) for it in disc_items}
    disc_idx = _disc_index(disc_items)

    # ---- 台账段（票 02 内核）：规则规划 → 引擎取数 → 证据装配 ----
    ledger_texts, ledger_cells = _ledger_evidence(root, period, question, disc_items)
    n_led = len(ledger_texts)

    texts_all = {**base_texts, **disc_texts, **ledger_texts}
    # 证据＝台账段 + 学科段 + 命中段优先 + 其余段（模型可自找）；
    # 规则版＝台账段（有则）+ 学科段（有则），否则命中段。
    ordered = list(ledger_texts) + list(disc_texts) + list(matched) + \
        [k for k in texts_all if k not in matched and k not in disc_texts
         and k not in ledger_texts]
    rule_keys = (list(ledger_texts) + list(disc_texts)) if (ledger_texts or disc_texts) \
        else list(matched)
    rule_set = set(rule_keys)
    # 上文进**编号之前**的首个区块：它的数字必须过盾（否则模型一复述就被判「游离数字」）。
    first_chunk = question
    if context_lines:
        first_chunk = ("对话上文（只用来理解指代，不要引用其中数字）：\n"
                       + "\n".join(context_lines) + "\n\n本次问题：" + question)
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
                            "detail": "table2.csv（总被引 ÷ 阈值；超过 100% 即已进入前 1%）",
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

    return RuleDraft(
        rule_text="\n\n".join(texts_all[k] for k in rule_keys),
        number=number,
        rule_protected="\n\n".join(number.texts[1 + i]
                                   for i, key in enumerate(ordered) if key in rule_set),
        parts=(),
        task=task,
        evidence=tuple(number.texts[1:]),
    )
