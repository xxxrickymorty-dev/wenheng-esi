# -*- coding: utf-8 -*-
"""观点分级（三级判断）—— 决定「机器能写到哪一步」。

| 类型 | 例 | 处理 |
|---|---|---|
| 描述性判断 | 「接近度从 62% 升至 78%，近 6 期持续上升」 | **规则 + 骨架自动生成，不经 LLM** |
| 解释性归因 | 「上升主要因为发文量增长」 | 可提出，但**必须**① 标「待验证假设」② 注明来源（规则引擎 / AI 推荐）③ 附可验证方式 |
| 专业判断 | 「建议加大该学科投入」 | 🔴 **绝不生成**，只留 `【手工：…】` |

为什么「注明来源」重要：不只标置信度，而是标**作者身份**。馆员引用时天然知道
「这是我的判断还是机器/AI 的建议」，责任归属不被模糊。

支撑事实：复刻报告**连定性判断都是人工填的**（`sentences.py` 的 `MANUAL` 机制）。
文衡从来没有让机器生成过「观点」，这是它「可签发」的根基之一。
灵活报告**不改变这条根基** —— 它把机器能说的严格限制在「描述」与「带标注的假设」，
专业判断依旧留空位。
"""
from __future__ import annotations

from .datasource import cn_name, period_label

MANUAL = "【手工：{}】"

#: 假设的来源标记 —— 报告里必须原样出现，不许省略。
SRC_RULE = "规则引擎"
SRC_AI = "AI 推荐"


def manual(what: str) -> str:
    """专业判断的空位（与复刻报告同构）。"""
    return MANUAL.format(what)


def descriptive_trend(points: list[dict], metric_cn: str, disc_cn: str,
                      better: str = "up") -> str:
    """描述性判断：**纯规则**由上数点序列生成，不经 LLM。

    只陈述「发生了什么」（取值、区间、单调性），不解释「为什么」。
    """
    if not points:
        return f"{disc_cn}的{metric_cn}在所选区间内无可用数据。"
    vs = [p["value"] for p in points]
    p0, p1 = points[0], points[-1]
    n = len(points)
    if n == 1:
        return (f"{period_label(p0['period'])}，{disc_cn}的{metric_cn}为 {_fmt(vs[0])}。")

    d = vs[-1] - vs[0]
    word = "上升" if d > 0 else ("下降" if d < 0 else "持平")
    pct = f"，累计变化 {abs(d) / abs(vs[0]) * 100:.2f}%" if vs[0] else ""
    mono = _monotonic(vs)
    span = f"{period_label(p0['period'])}至{period_label(p1['period'])}（{n} 期）"
    # 好/坏只在方向明确时给结论词，避免在 threshold 这类「无方向」指标上瞎判
    taste = ""
    if better in ("up", "down") and d != 0:
        good = (d > 0) if better == "up" else (d < 0)
        taste = "，为改善方向" if good else "，为不利方向"
    return (f"{span}，{disc_cn}的{metric_cn}自 {_fmt(vs[0])} {word}至 {_fmt(vs[-1])}"
            f"{pct}{mono}{taste}。")


def _monotonic(vs: list[float]) -> str:
    if len(vs) < 3:
        return ""
    dl = [vs[i + 1] - vs[i] for i in range(len(vs) - 1)]
    if all(x >= 0 for x in dl):
        return "，区间内逐期未出现回落"
    if all(x <= 0 for x in dl):
        return "，区间内逐期未出现回升"
    up = sum(1 for x in dl if x > 0)
    return f"，区间内有 {up} 期上升、{len(dl) - up} 期下降"


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


def guard(text: str) -> list[str]:
    """自检：报告文本里凡出现「建议 / 应当 / 必须」这类**专业判断措辞**即报警。

    这是"专业判断一律不生成"的守门人 —— 规则后端和模型后端都过这道检查。
    """
    import re
    hits = []
    for m in re.finditer(r"[^。；\n]{0,24}(建议|应当|必须|亟需|应加大|宜加强)[^。；\n]{0,24}", text):
        s = m.group(0).strip()
        if MANUAL.split("：")[0] in s:            # 【手工：…】空位里允许出现
            continue
        hits.append(s)
    return hits


def sections_of_discipline(disc: str, name_cn: str) -> dict:
    """单学科诊断的**章节骨架**（AI 只选科/选指/选期，骨架固定）。"""
    return {
        "title": f"{name_cn}发展态势诊断",
        "lead": f"本节围绕{name_cn}的关键指标展开，数据均来自台账，逐项附来源链。",
    }
