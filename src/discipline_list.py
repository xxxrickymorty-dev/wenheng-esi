# -*- coding: utf-8 -*-
"""ESI 22 个学科：**文件名的单一事实源**。

为什么要有这个模块
------------------
同一批学科在仓里有三套名字，没有任何地方记录它们的对应关系：

1. **台账口径**（`parse_ledger.DISCIPLINES_CN` 的键）：`Environment/Ecology`、
   `Social Sciences, general`、`Psychiatry/Psychology`；
2. **ESI 导出文件名**（`数据与复现/ESI数据/<期>/<名>.xlsx` 的 stem）：
   `Environment Ecology`、`Social Sciences, General`、`Psychiatry Psychology`；
3. **中文显示名**（DISCIPLINES_CN 的值）：环境生态学、社会科学、精神病学与心理学。

`peers._raw_rows` 直接用 `f"{disc_en}.xlsx"` 拼路径，所以**只有第 2 套能用**。
传第 1 套不会报错——`Environment/Ecology.xlsx` 不存在，函数返回 None，
调用方静默回退到模板路径，结果看起来正常，数字可能来自别的口径。
2026-10-30 实测：按目录 glob + 黑名单数学科，202511 会数出 26 个、202607 数出 23 个，
多出来的是 `202511ESI总表模板`、`ThresholdESI` 这类非学科文件。

因此：**一律用 `DISCIPLINES` 里的 stem 做键**，需要中文走 `cn_of()`，
需要台账口径走 `LEDGER_KEY`。不要自己拼、不要 glob 目录。

与 `parse_ledger.DISCIPLINES_CN` 的关系
--------------------------------------
本模块**不重新定义中文名**，只在导入时从它派生映射并校验条数——
中文名改了，这里跟着变；两边条数不一致时导入即报错，不会静默漂移。
"""
from __future__ import annotations

#: 22 个学科，值为 ESI 导出文件的 stem（**不含 .xlsx**），按字母序。
DISCIPLINES: tuple[str, ...] = (
    "Agricultural Sciences",
    "Biology & Biochemistry",
    "Chemistry",
    "Clinical Medicine",
    "Computer Science",
    "Economics & Business",
    "Engineering",
    "Environment Ecology",
    "Geosciences",
    "Immunology",
    "Materials Science",
    "Mathematics",
    "Microbiology",
    "Molecular Biology & Genetics",
    "Multidisciplinary",
    "Neuroscience & Behavior",
    "Pharmacology & Toxicology",
    "Physics",
    "Plant & Animal Science",
    "Psychiatry Psychology",
    "Social Sciences, General",
    "Space Science",
)

#: 台账口径的键 → 文件 stem。三处差异是 ESI 导出与台账各自的历史写法，显式登记。
#: 新增差异时改这里，**不要加模糊匹配**（斜杠 / 大小写 / 下划线都不猜）。
LEDGER_KEY: dict[str, str] = {
    "Environment/Ecology": "Environment Ecology",
    "Psychiatry/Psychology": "Psychiatry Psychology",
    "Social Sciences, general": "Social Sciences, General",
}

_DISC_SET = frozenset(DISCIPLINES)


def _build_cn() -> dict[str, str]:
    try:
        from parse_ledger import DISCIPLINES_CN            # noqa: PLC0415
    except ImportError:                                    # 独立运行兜底
        return {}
    if len(DISCIPLINES_CN) != len(DISCIPLINES):
        raise RuntimeError(
            f"学科条数不一致：parse_ledger.DISCIPLINES_CN 有 {len(DISCIPLINES_CN)} 条，"
            f"discipline_list.DISCIPLINES 有 {len(DISCIPLINES)} 条。"
            f"改了一边就要改另一边，否则学科名会静默对不上。")
    out: dict[str, str] = {}
    for key, cn in DISCIPLINES_CN.items():
        stem = LEDGER_KEY.get(key, key)
        if stem not in _DISC_SET:
            raise RuntimeError(
                f"台账学科名 {key!r} 映射到 {stem!r}，但它不在 DISCIPLINES 里。"
                f"请补 LEDGER_KEY 或核对文件 stem。")
        out[stem] = cn
    missing = _DISC_SET - set(out)
    if missing:
        raise RuntimeError(f"这些学科没有中文名：{sorted(missing)}")
    return out


#: 文件 stem → 中文显示名
CN_OF: dict[str, str] = _build_cn()


def is_discipline(name: str) -> bool:
    """是否 22 个规范学科之一。**只做精确匹配**。"""
    return name in _DISC_SET


def cn_of(stem: str) -> str:
    """文件 stem → 中文名；不认识的原样返回（不猜）。"""
    return CN_OF.get(stem, stem)


def ledger_key_of(stem: str) -> str:
    """文件 stem → 台账口径的键；没有差异时返回自身。"""
    for key, mapped in LEDGER_KEY.items():
        if mapped == stem:
            return key
    return stem


def check_dir(names) -> dict:
    """核对一个目录里的文件名集合。

    返回 `{"present": [...], "missing": [...], "extra": [...]}`。
    `extra` 是**清单外的文件**——调用方应当报警而不是把它们当学科计数。
    """
    given = {str(n) for n in names}
    return {
        "present": [d for d in DISCIPLINES if d in given],
        "missing": [d for d in DISCIPLINES if d not in given],
        "extra": sorted(given - _DISC_SET),
    }
