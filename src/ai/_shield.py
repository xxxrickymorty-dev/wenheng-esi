# -*- coding: utf-8 -*-
"""数字盾：唯一出口（SPEC §2.1 出网零值、C1/B 复核条件）。

- 保护：文本里的数字全部 → `[[n]]` 占位（顺序编号，可复现）；
- 校验：占位符**一个不少、一个不多**、无游离数字、无未知标记；
- 还原：只由模块内部完成，模型永远拿不到映射表。
- 逐字复用 `shield_primitives` 的正则口径（NUM / MARK）——盾不许长出第二份正则；
  D6 收编后 `shield_primitives` 只剩这份盾原语。
"""
from __future__ import annotations

import shield_primitives

NUM = shield_primitives.NUM
MARK = shield_primitives.MARK


def numberize(texts, start: int = 0) -> tuple[list[str], dict, list]:
    """编号的**唯一实现**：多段文本共用一套连续编号。

    返回 `(受保护各段, mapping, hits)`；`hits = [(段号, 段内位置, k, 原值), ...]`
    按扫描序——调用方在同一遍里同时拿到「哪一段哪一个数」与「它是第几号」，
    来源注册不再需要第二次扫描、也不再靠顺序约定对齐。
    `start`＝编号起点偏移（默认 0＝从 1 起）：续接场景（`NumberedText.append`，
    qa 原生工具环）从既有最大 k 续号——既有签名向后兼容。
    `protect` / `protect_chunks` 都是它的薄委托。
    """
    mapping: dict = {}
    pieces: list[str] = []
    hits: list = []

    def repl(m, ti):
        k = str(start + len(mapping) + 1)
        mapping[k] = m.group(0)
        hits.append((ti, m.start(), k, m.group(0)))
        return f"[[{k}]]"

    for ti, text in enumerate(texts):
        pieces.append(NUM.sub(lambda m, ti=ti: repl(m, ti), str(text)))
    return pieces, mapping, hits


def protect(text: str) -> tuple[str, dict]:
    """数字 → [[n]]；返回 (受保护文本, 映射 {k: 原值})。"""
    pieces, mapping, _hits = numberize([text])
    return pieces[0], mapping


def protect_chunks(chunks) -> tuple[list[str], dict]:
    """多段文本共用**一套连续编号**（qa：问句＋各段证据/规则文本）。

    与逐段 protect 的区别：编号跨段连续、共用一张 mapping——「第 k 个数字 ↔
    sources[k]」在多段场景下依然成立；分段只影响外发面拼装，不影响还原。
    """
    pieces, mapping, _hits = numberize(chunks)
    return pieces, mapping


def restore(text: str, mapping: dict) -> str:
    return shield_primitives.restore(text, mapping)


def strip_marks(text: str) -> str:
    return MARK.sub("", text)


def visible_digits(text: str) -> list[str]:
    """去掉占位标记后仍可见的数字串（应为空 = 零值达标）。"""
    return NUM.findall(strip_marks(text))


def validate(out_text: str | None, mapping: dict) -> tuple[bool, dict]:
    """占位符完备 + 无游离数字 + 无未知标记。返回 (ok, 详情)。

    比 `shield_primitives.validate` 多一条：**未知标记**（模型自造 `[[9]]`）也要拒——
    旧校验会先把它当标记删掉，于是漂过去了。
    """
    text = out_text or ""
    marks = MARK.findall(text)
    missing = sorted(k for k in mapping if marks.count(str(k)) != 1)
    unknown = sorted({k for k in marks if k not in mapping})
    stray = visible_digits(text)
    detail = {"missing": missing, "unknown": unknown, "stray": stray}
    return (not missing and not unknown and not stray), detail


def validate_free(out_text: str | None, mapping: dict) -> tuple[bool, dict]:
    """自由作答型（qa/review）校验：用到必有 ref、无游离数字。

    与锚定型 `validate` 的区别：**允许相关子集**（不要求 mapping 全部出现）；
    **允许重复引用同一来源**（2026-09-29 放宽——真实模型写「前 [[1]]%…前 [[1]]%」很自然，
    重复引用不产生新事实；位置映射按出现次序重复登记即可）。
    未登记/自造标记、照写照算的数字 —— 一律拒（SPEC §2.1 二分）。
    """
    text = out_text or ""
    marks = MARK.findall(text)
    unknown = sorted({k for k in marks if k not in mapping})
    stray = visible_digits(text)
    detail = {"unknown": unknown, "stray": stray}
    return (not unknown and not stray), detail
