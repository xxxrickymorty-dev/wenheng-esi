# -*- coding: utf-8 -*-
"""守卫体检：**跳过必须在数据真的缺席时才发生**。

背景见 `_guard_registry.py`。这里只做两件事：

  1. 登记簿自己的逻辑要能被验证（探针说资源还在 → 该跳过算数）；
  2. 结构上禁止出现裸 `pytest.skip` —— 那会绕过登记，也就绕过了复核。

第 2 条是这份文件存在的真正理由：只要有人图省事直接写一句跳过，静默降级的口子就又开了。
"""
import pathlib
import re

import pytest

import _guard_registry as G


def test_探针说资源还在时跳过就站不住脚():
    G.SKIPS.append(("资源其实还在", lambda: True))
    try:
        assert "资源其实还在" in G.outstanding()
    finally:
        G.SKIPS.pop()


def test_探针说资源不在时跳过成立():
    G.SKIPS.append(("资源真缺席", lambda: False))
    try:
        assert "资源真缺席" not in G.outstanding()
    finally:
        G.SKIPS.pop()


def test_没有绕过登记簿的裸pytest_skip():
    """`tests/` 下所有跳过都必须经由 `skip_unless`。

    允许列表只有登记簿自己（它就住在那句 `pytest.skip` 里）。
    """
    here = pathlib.Path(__file__).resolve().parent
    offenders = []
    for p in sorted(here.rglob("*.py")):
        if p.name == "_guard_registry.py" or "__pycache__" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bpytest\.skip\s*\(", line):
                offenders.append(f"{p.relative_to(here)}:{i}")
    assert not offenders, (
        f"这些地方绕过了跳过登记，会重新打开『静默跳过』的口子：{offenders} —— "
        f"改用 tests/_guard_registry.py 的 skip_unless(理由, 探针)")


def test_探针传成bool必须当场报错():
    """已求值的 bool 探针只有"数据缺席"的环境（新 clone / CI）才会爆——
    2026-09-21 CI 空克隆模拟实测：会话收尾 `outstanding()` 直接 TypeError。
    所以必须当场拦住，不能等收尾。"""
    with pytest.raises(TypeError, match="可调用"):
        G.skip_unless("测试用：探针写成了 bool", True)
