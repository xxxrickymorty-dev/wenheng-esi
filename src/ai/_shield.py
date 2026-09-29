# -*- coding: utf-8 -*-
"""数字盾：唯一出口（SPEC §2.1 出网零值、C1/B 复核条件）。

- 保护：文本里的数字全部 → `[[n]]` 占位（顺序编号，可复现）；
- 校验：占位符**一个不少、一个不多**、无游离数字、无未知标记；
- 还原：只由模块内部完成，模型永远拿不到映射表。
- 逐字复用 `local_llm` 的正则口径（NUM / MARK）——盾不许长出第二份正则；
  D6 收编后 `local_llm` 只剩这份盾原语。
"""
from __future__ import annotations

import local_llm

NUM = local_llm.NUM
MARK = local_llm.MARK


def protect(text: str) -> tuple[str, dict]:
    """数字 → [[n]]；返回 (受保护文本, 映射 {k: 原值})。"""
    return local_llm.protect(text)


def protect_chunks(chunks) -> tuple[list[str], dict]:
    """多段文本共用**一套连续编号**（qa：问句＋各段证据/规则文本）。

    与逐段 protect 的区别：编号跨段连续、共用一张 mapping——「第 k 个数字 ↔
    sources[k]」在多段场景下依然成立；分段只影响外发面拼装，不影响还原。
    """
    mapping: dict = {}
    out = []

    def repl(m):
        k = str(len(mapping) + 1)
        mapping[k] = m.group(0)
        return f"[[{k}]]"

    for chunk in chunks:
        out.append(NUM.sub(repl, str(chunk)))
    return out, mapping


def restore(text: str, mapping: dict) -> str:
    return local_llm.restore(text, mapping)


def strip_marks(text: str) -> str:
    return MARK.sub("", text)


def visible_digits(text: str) -> list[str]:
    """去掉占位标记后仍可见的数字串（应为空 = 零值达标）。"""
    return NUM.findall(strip_marks(text))


def validate(out_text: str | None, mapping: dict) -> tuple[bool, dict]:
    """占位符完备 + 无游离数字 + 无未知标记。返回 (ok, 详情)。

    比 `local_llm.validate` 多一条：**未知标记**（模型自造 `[[9]]`）也要拒——
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
    """自由作答型（qa/review）校验：用到必有 ref、每个引用至多一次、无游离数字。

    与锚定型 `validate` 的区别：**允许相关子集**（不要求 mapping 全部出现）。
    未登记/自造标记、重复引用、照写照算的数字 —— 一律拒（SPEC §2.1 二分）。
    """
    text = out_text or ""
    marks = MARK.findall(text)
    unknown = sorted({k for k in marks if k not in mapping})
    duplicate = sorted({k for k in set(marks) if marks.count(k) > 1})
    stray = visible_digits(text)
    detail = {"unknown": unknown, "duplicate": duplicate, "stray": stray}
    return (not unknown and not duplicate and not stray), detail
