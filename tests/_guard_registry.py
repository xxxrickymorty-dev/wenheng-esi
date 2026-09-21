# -*- coding: utf-8 -*-
"""跳过登记簿（测试基础设施，不是测试用例，pytest 不会收集它）。

为什么需要它
────────────────────────────────────────────────────────────────
`input/`（馆员台账）与 `out/`（历史产物）按 `.gitignore` 不入库，所以数据驱动的
用例在缺数据时 `skip` 是对的 —— 否则"没数据"会被读成"代码坏了"，红灯反而误导人。

代价是：**数据整片丢失时 pytest 依然一路全绿**，只是少跑了几十条。2026-09-16
已经吃过一次同类的亏：1‰ 守卫的数据根常量指向了一层被搬走的旧目录，四条测试
静默 skip，全绿，谁都没发现。

所以每一次跳过都要**登记理由，并留一个复核探针**。会话收尾时
`conftest.pytest_sessionfinish` 逐条复核：

    探针说"资源其实在" → 这次跳过站不住脚 → 会话判失败

这样"跳过"就从"没人看见的静默降级"变成"有据可查、且被机器复核过的缺席"。
"""
from __future__ import annotations

import pytest

#: [(跳过理由, 复核探针)]。探针返回 True ＝ 该资源其实在仓库里。
SKIPS: list[tuple[str, object]] = []


def skip_unless(reason, probe):
    """资源确实缺席才跳过；同时登记理由与探针，供会话收尾复核。

    `probe` 必须已经在前面调用过（也就是 `skip_unless` 只在真的要走跳过分支时调用），
    所以探针本身只需表达"那个资源在不在"。

    🔴 `probe` 必须是**可调用对象**（通常是 `lambda: ...`），不能是已求值的 bool：
    后者在会话收尾复核时会 `TypeError` 崩掉整个会话，而且只有"数据缺席"的环境
    （新 clone / CI）才会踩到 —— 本地有数据时永远发现不了。
    """
    if not callable(probe):
        raise TypeError(
            f"skip_unless 的探针必须可调用（如 lambda: p.exists()），收到 {probe!r}；"
            f"理由：{reason}")
    SKIPS.append((reason, probe))
    pytest.skip(reason)


def outstanding() -> list[str]:
    """站不住脚的跳过理由：探针说资源还在，却跳过了。"""
    seen, bad = set(), []
    for reason, probe in SKIPS:
        if reason in seen:
            continue
        seen.add(reason)
        try:
            present = bool(probe())
        except OSError:
            present = False
        if present:
            bad.append(reason)
    return bad


def stats() -> tuple[int, int]:
    """(登记过的不同理由数, 其中站不住脚的条数)。"""
    return len({r for r, _ in SKIPS}), len(outstanding())
