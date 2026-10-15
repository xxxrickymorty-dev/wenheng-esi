# -*- coding: utf-8 -*-
"""观点分级（三级判断）—— 决定「机器能写到哪一步」。

| 类型 | 例 | 处理 |
|---|---|---|
| 描述性判断 | 「接近度从 62% 升至 78%，近 6 期持续上升」 | **规则 + 骨架自动生成，不经 LLM** |
| 解释性归因 | 「上升主要因为发文量增长」 | 可提出，但**必须**① 标「待验证假设」② 注明来源（规则引擎 / AI 推荐）③ 附可验证方式 |
| 专业判断 | 「建议加大该学科投入」 | **判断草稿**：机器可写；需馆员拍板的句子必须带「待审线」`==…==`，漏标由兜底词表报出并可确定性补标 |

为什么「注明来源」重要：不只标置信度，而是标**作者身份**。馆员引用时天然知道
「这是我的判断还是机器/AI 的建议」，责任归属不被模糊。

**2026-10-14 口径反转（ADR-0009）**：灵活报告是内部参考件、非报送件——专业判断由
写作位起草、馆员线下拍板。`guard` / `judgement_leaks` 不再「出现判断词即违规」，
改为**标记完备性检查**：兜底词表命中，凡不在成对 `==…==`（待审线）内、也不在
`【手工：…】`空位里的，即为**漏标**；`backfill_marks` 给漏标句确定性补标并计数。
复刻报告不动：它的专业判断仍由人工填写（`sentences.py` 的 `MANUAL` 机制）。
"""
from __future__ import annotations

import os
import re

from .datasource import cn_name, period_label

MANUAL = "【手工：{}】"

#: 假设的来源标记 —— 报告里必须原样出现，不许省略。
SRC_RULE = "规则引擎"
SRC_AI = "AI 推荐"

#: 待审线：成对 `==…==`（渲染成细下划线；用法只在报告头部说明一次）。
MARK_RE = re.compile(r"==([^=\n]+?)==")

#: 兜底词表 —— 判断句标记完备性检查用；env `WENHENG_FLEX_MARK_WORDS`（逗号分隔）可覆盖。
DEFAULT_MARK_WORDS = ("建议", "应当", "必须", "值得", "需要", "优先")

#: 空位与句子边界（补标以句为单位、不跨行，避免破坏列表/段落结构）。
_MANUAL_RE = re.compile(re.escape(MANUAL.split("：")[0]) + r"：[^】\n]*】")
_SENT_END = "。；！？\n"
_LIST_HEAD = re.compile(r"[ \t]*(?:[-*+>]+\s+|\d+[.)]\s+)?[，、]*")

#: 节标题豁免：标题是版式结构、不是判断句（拟定节名「建议事项（判断草稿）」自带词表词）；
#: 且给标题包 `==…==` 会破坏标题解析。扫描与补标都跳过整行标题。
_HEADING_RE = re.compile(r"(?m)^#{1,6}[ \t].*$")


def manual(what: str) -> str:
    """专业判断的空位（与复刻报告同构）。"""
    return MANUAL.format(what)


def _shape(vs: list[float]) -> tuple[str, int | None]:
    """按**数据形态**分类 —— 句式由形态决定，不再一律「自 A 上升至 B」。

    返回 `(形态, 关键期索引)`；关键期只在 `step` / `reversal` 两种形态下有值。

    判定顺序（从严到宽，别打乱）：
      单调 → 走平 → **反转**（峰/谷在区间内部，前后方向相反）→ **台阶**
      （变化压在一期上、其余各期都很小）→ 震荡。
    ⚠ 台阶的判据必须带「其余各期都很小」这一半：只看「最大步 ≥ 净变化的 55%」
      会把 `[1,3,2,4]` 这种明明是震荡上行的序列误判成台阶。
    """
    dl = [vs[i + 1] - vs[i] for i in range(len(vs) - 1)]
    if not dl:
        return "flat", None
    ups = sum(1 for x in dl if x > 0)
    downs = sum(1 for x in dl if x < 0)
    net = vs[-1] - vs[0]
    if ups and not downs:
        return "mono_up", None
    if downs and not ups:
        return "mono_down", None
    if not ups and not downs:
        return "flat", None

    # 台阶：单期变化占净变化的大头，且**其余各期都很小**
    #       （放在反转之前：`[2,2,8,7]` 这种"跳一下再小幅回落"更像台阶而不是反转）
    k = max(range(len(dl)), key=lambda i: abs(dl[i]))
    rest = max((abs(x) for i, x in enumerate(dl) if i != k), default=0.0)
    if net and abs(dl[k]) >= 0.55 * abs(net) and rest <= 0.25 * abs(net):
        return "step", k

    # 反转：极值点落在区间**内部**（不是首尾），且末值已从极值回落
    pk = max(range(len(vs)), key=lambda i: vs[i])
    tr = min(range(len(vs)), key=lambda i: vs[i])
    if 0 < pk < len(vs) - 1 and vs[-1] < vs[pk] and vs[pk] > vs[0]:
        return "reversal", pk
    if 0 < tr < len(vs) - 1 and vs[-1] > vs[tr] and vs[tr] < vs[0]:
        return "reversal", tr

    return ("volatile_up" if net > 0 else
            "volatile_down" if net < 0 else "flat"), None


def _variant(key: str, n: int) -> int:
    """按指标名稳定取一个句式变体 —— 同一份报告里不同指标不会撞成同一句。

    🔴 必须是**确定性**的：规则后端的产出要可复现，不能每次跑都不一样。
    """
    return sum(ord(c) for c in str(key)) % max(n, 1)


def descriptive_trend(points: list[dict], metric_cn: str, disc_cn: str,
                      better: str = "up", *, with_span: bool = True) -> str:
    """描述性判断：**纯规则**由上数点序列生成，不经 LLM。

    🔴 2026-09-21 重写（rick：「灵活报告并不灵活，语言还是很死板」）——
    原先三条指标一律「X月至X月（7 期），X 的 Y 自 A 上升至 B，累计变化 Z%，…」，
    同一个句式连写三遍，读起来就是模板。现在：
      ① 句式由**数据形态**决定（单调 / 波动 / 台阶 / 反转 / 走平）；
      ② 每种形态有 2–3 种说法，按指标名**确定性**取一种（同报告内不撞句）；
      ③ `with_span=False` 时不再重复区间（第二条起用「同期」「同一窗口」）。

    仍然只陈述「发生了什么」，不解释「为什么」。
    """
    if not points:
        return f"{disc_cn}的{metric_cn}在所选区间内无可用数据。"
    vs = [p["value"] for p in points]
    n = len(points)
    p0, p1 = points[0], points[-1]
    if n == 1:
        return f"{period_label(p0['period'])}，{disc_cn}的{metric_cn}为 {_fmt(vs[0])}。"

    shape, k = _shape(vs)
    a, b = _fmt(vs[0]), _fmt(vs[-1])
    net = vs[-1] - vs[0]
    pct = f"{abs(net) / abs(vs[0]) * 100:.2f}%" if vs[0] else None
    span = (f"{period_label(p0['period'])}至{period_label(p1['period'])}（{n} 期）"
            if with_span else None)
    opener = (f"{span}，" if span else _no_span_opener(metric_cn, n))
    subj = f"{disc_cn}的{metric_cn}"

    dl = [vs[i + 1] - vs[i] for i in range(n - 1)]
    ups = sum(1 for x in dl if x > 0)
    downs = sum(1 for x in dl if x < 0)

    if shape == "mono_up":
        body = [
            f"{subj}一路走高：由 {a} 抬到 {b}"
            + (f"，累计 {pct}" if pct else "")
            + f"，{n} 期里没有一期回落",
            f"{subj}保持单向上升 —— {a} → {b}"
            + (f"，累计 {pct}" if pct else "")
            + "，中途未掉头",
            f"{subj}从 {a} 稳步升到 {b}"
            + (f"（累计 {pct}）" if pct else "")
            + f"，逐期递增，{n} 期没有反抽",
        ][_variant(metric_cn, 3)]
    elif shape == "mono_down":
        body = [
            f"{subj}持续走低：由 {a} 降到 {b}"
            + (f"，累计 {pct}" if pct else "")
            + f"，{n} 期里没有一期回升",
            f"{subj}一路下滑 —— {a} → {b}"
            + (f"，累计 {pct}" if pct else "")
            + "，中途未反弹",
            f"{subj}从 {a} 逐级降到 {b}"
            + (f"（累计 {pct}）" if pct else "")
            + f"，{n} 期逐期递减",
        ][_variant(metric_cn, 3)]
    elif shape == "flat":
        body = (f"{subj}几乎走平，{n} 期都在 {a} 附近"
                + (f"（期末 {b}）" if a != b else ""))
    elif shape == "step":
        at = period_label(points[k + 1]["period"])
        step_d = vs[k + 1] - vs[k]
        body = (f"{subj}的变化集中在一期上：{at}单期"
                + ("跳增" if step_d > 0 else "回落")
                + f" {_fmt(abs(step_d))}，从 {a} 变为 {b}"
                + (f"，其余各期变动不超过 {_fmt(max((abs(x) for i2, x in enumerate(dl) if i2 != k), default=0))}"
                   if len(dl) > 1 else ""))
    elif shape == "reversal":
        mid = _fmt(vs[k])
        at = period_label(points[k]["period"])
        up_first = vs[k] - vs[0] > 0
        body = (f"{subj}先{'升' if up_first else '降'}后{'降' if up_first else '升'}："
                f"{a} → {mid}（{at}）→ {b}"
                + (f"，全区间净{'增' if net > 0 else '减'} {pct}" if pct else ""))
    else:                                                    # volatile_*
        word = "震荡上行" if shape == "volatile_up" else "震荡下行"
        body = [
            f"{subj}整体{word}但有反复：{a} → {b}"
            + (f"，累计 {pct}" if pct else "")
            + f"，其中 {ups} 期上行、{downs} 期下行",
            f"{subj}在波动中{word.replace('震荡', '')}：{a} 到 {b}"
            + (f"（累计 {pct}）" if pct else "")
            + f"，{ups} 期涨、{downs} 期跌，并非单边走势",
        ][_variant(metric_cn, 2)]

    # 好/坏只在方向明确时给结论词，避免在 threshold 这类「无方向」指标上瞎判
    taste = ""
    if better in ("up", "down") and net != 0:
        good = (net > 0) if better == "up" else (net < 0)
        taste = "，方向向好" if good else "，方向转差"
    return f"{opener}{body}{taste}。"


def _no_span_opener(metric_cn: str, n: int) -> str:
    """第二条起不再重复区间（原来三条开头一字不差，就是这么来的）。"""
    return ["同一窗口内，", f"同区间（{n} 期）看，", "同期"][_variant(metric_cn, 3)]


def gap_lead(period_cn: str, disc_cn: str, gap) -> str:
    """「一、当期概况」的引导句 —— 原来一律「…的核心指标如下」，也是模板腔。

    `gap` = 总被引 − 1% 阈值（负=还差，正=已超，None=算不出来）。
    """
    if gap is None:
        return f"{period_cn}，{disc_cn}本期核心指标如下，逐项附来源。"
    if gap < 0:
        return (f"{period_cn}，{disc_cn}距 ESI 前 1% 阈值还差 **{_fmt(abs(gap))}** 次被引；"
                f"本期核心指标如下。")
    return (f"{period_cn}，{disc_cn}的总被引已高出 1% 阈值 **{_fmt(gap)}**；"
            f"本期核心指标如下。")


def rank_sentence(n: int, prox_pos, paper_pos, disc_cn: str) -> str:
    """「三、相对位次」—— 原来「在本期 22 个学科中…排第 X 位（共 22 个学科）」
    把 22 说了两遍。改成一次说清，并补一个「处在哪个三分段」的纯算术定位。"""

    def third(pos):
        if not pos:
            return ""
        if pos <= n / 3:
            return "前 1/3"
        if pos <= 2 * n / 3:
            return "中间 1/3"
        return "后 1/3"

    t = third(prox_pos)
    where = f"（{t}）" if t else ""
    a = f"接近度在 {n} 个学科里排第 **{prox_pos}** 位{where}" if prox_pos else "接近度未取到位次"
    b = f"，论文数排第 **{paper_pos}** 位" if paper_pos else ""
    return f"横过来看，{disc_cn}的{a}{b}。"


def _fmt(v) -> str:
    if isinstance(v, (int, float)) and abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.4g}" if isinstance(v, (int, float)) else str(v)


def hypothesis(text: str, verify: str, source: str = SRC_RULE) -> dict:
    """构造一条**待验证假设**。三件套缺一不可，缺了就是违规输出。

    Args:
        text:   假设内容（「上升主要因为…」）
        verify: 可验证方式（查哪个指标、哪几期）——**必填**
        source: `规则引擎` 或 `AI 推荐`
    """
    if not text or not verify:
        raise ValueError("待验证假设必须同时给出内容与可验证方式")
    if source not in (SRC_RULE, SRC_AI):
        raise ValueError(f"来源标记必须是 {SRC_RULE} 或 {SRC_AI}，实为 {source!r}")
    return {"kind": "hypothesis", "text": text, "verify": verify, "source": source}


def render_hypothesis(h: dict) -> str:
    """渲染成报告里的固定句式。"""
    return (f"- **待验证假设**（来源：{h['source']}）：{h['text']}\n"
            f"  - 可验证方式：{h['verify']}")


def mark_words() -> tuple[str, ...]:
    """兜底词表：env `WENHENG_FLEX_MARK_WORDS`（逗号分隔）非空即覆盖内置六词。"""
    raw = os.environ.get("WENHENG_FLEX_MARK_WORDS", "")
    words = tuple(w.strip() for w in raw.split(",") if w.strip())
    return words or DEFAULT_MARK_WORDS


def _exempt_spans(text: str) -> list[tuple[int, int]]:
    """豁免区间：成对 `==…==`（待审线）＋ `【手工：…】`空位 ＋ 整行标题。"""
    spans = [(m.start(), m.end()) for m in MARK_RE.finditer(text)]
    spans += [(m.start(), m.end()) for m in _MANUAL_RE.finditer(text)]
    spans += [(m.start(), m.end()) for m in _HEADING_RE.finditer(text)]
    return sorted(spans)


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= pos < e for s, e in spans)


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """命中处所属句子 [起, 止)：按 `。；！？` 与换行切，不跨行。"""
    a = max(text.rfind(b, 0, pos) for b in _SENT_END) + 1
    z = min((i for i in (text.find(b, pos) for b in _SENT_END) if i >= 0),
            default=len(text))
    return a, z


def _segments(a: int, z: int, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """[a, z) 去掉豁免段后的连续段（供补标只包非豁免部分）。"""
    segs, cur = [], a
    for s, e in spans:
        if e <= cur:
            continue
        if s >= z:
            break
        if s > cur:
            segs.append((cur, s))
        cur = max(cur, e)
    if cur < z:
        segs.append((cur, z))
    return segs


def judgement_leaks(text: str) -> list[str]:
    """标记完备性检查（旧 `guard` 的语义反转）：判断句**未带标记即失败**。

    扫描兜底词表（`mark_words()`）命中，凡不在成对 `==…==`（待审线）内、
    也不在 `【手工：…】`空位里的，即为**漏标**——返回漏标片段（按句去重，原文顺序）。
    """
    words = mark_words()
    if not text or not words:
        return []
    spans = _exempt_spans(text)
    pat = re.compile("|".join(re.escape(w) for w in words))
    out: list[str] = []
    seen: set[tuple[int, int]] = set()
    for m in pat.finditer(text):
        if _inside(m.start(), spans):
            continue
        bounds = _sentence_bounds(text, m.start())
        if bounds in seen:
            continue
        seen.add(bounds)
        snippet = text[bounds[0]:bounds[1]].strip()
        if snippet:
            out.append(snippet)
    return out


def backfill_marks(text: str) -> tuple[str, int]:
    """兜底补标：给漏标句包上 `==…==`（确定性、可复现）→ 返回（新文本, 补标句数）。

    只包非豁免部分（与既有标记/空位贴边时宁可不包——留给自检报漏标、由调用侧回退）；
    计数＝实际补到标的**句子数**（同句多处漏标只算一句）。同输入同输出。
    """
    words = mark_words()
    if not text or not words:
        return text, 0
    spans = _exempt_spans(text)
    pat = re.compile("|".join(re.escape(w) for w in words))
    leak_pos = [m.start() for m in pat.finditer(text) if not _inside(m.start(), spans)]
    if not leak_pos:
        return text, 0

    pairs: list[tuple[tuple[int, int], list[tuple[int, int]]]] = []
    seen: set[tuple[int, int]] = set()
    for pos in leak_pos:
        sent = _sentence_bounds(text, pos)
        if sent in seen:
            continue
        seen.add(sent)
        a, z = sent
        segs = [se for se in _segments(a, z, spans)
                if any(se[0] <= p < se[1] for p in leak_pos)]
        if segs:
            pairs.append((sent, segs))

    out, n = text, 0
    for _sent, segs in reversed(pairs):          # 右到左插入，坐标不漂
        applied = False
        for s, e in reversed(segs):
            head = _LIST_HEAD.match(out[s:e])
            lead = head.group(0) if head else ""
            core = out[s:e][len(lead):].rstrip()
            if not core or "==" in core:
                continue                          # 标记语法已损坏：不硬包，留给自检
            if out[max(0, s - 2):s] == "==" or out[e:e + 2] == "==":
                continue                          # 与既有标记贴边会撞出 `====`：同上
            out = (out[:s] + lead + "==" + core + "==" + out[s + len(lead) + len(core):])
            applied = True
        if applied:
            n += 1
    return out, n


def guard(text: str) -> list[str]:
    """旧名保留（写作位 veto / 既有调用方仍用）：语义＝`judgement_leaks`。"""
    return judgement_leaks(text)


def sections_of_discipline(disc: str, name_cn: str) -> dict:
    """单学科诊断的**章节骨架**（AI 只选科/选指/选期，骨架固定）。"""
    return {
        "title": f"{name_cn}发展态势诊断",
        "lead": f"本节围绕{name_cn}的关键指标展开，数据均来自台账，逐项附来源链。",
    }
