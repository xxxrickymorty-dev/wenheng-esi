# -*- coding: utf-8 -*-
"""数字防护盾**原语**（唯一一份正则）——数字 → `[[n]]` 占位 / 还原 / 校验。

D6 收编（2026-09-29）：本模块只剩盾原语。
- 模型出口已统一到 `src/ai`（`ai.run` 的能力调用与 `ai._llm` 的内部口），
  **不再有 Ollama 直连、polish/draft 入口**；
- 盾的语义实现（拒未知标记、自由型子集校验）在 `src/ai/_shield.py`，
  这里保留的是最底层、无依赖的占位/还原/校验函数，供 AI 层与测试复用。
"""
import re

NUM = re.compile(r"\d+(?:\.\d+)?")
MARK = re.compile(r"\[\[(\d+)\]\]")


def protect(text):
    """数字 → [[n]]，返回 (受保护文本, 映射表)。"""
    mapping = {}

    def repl(m):
        k = str(len(mapping) + 1)
        mapping[k] = m.group(0)
        return f"[[{k}]]"

    return NUM.sub(repl, text), mapping


def restore(text, mapping):
    return re.sub(r"\[\[(\d+)\]\]", lambda m: mapping.get(m.group(1), m.group(0)), text)


def validate(out_text, mapping):
    """占位符完备 + 无新增数字。返回 (ok, 详情)。"""
    missing = [k for k in mapping if out_text.count(f"[[{k}]]") != 1]
    stray = NUM.findall(MARK.sub("", out_text))
    ok = (not missing) and (not stray)
    return ok, {"missing": missing, "stray": stray}
