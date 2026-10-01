# -*- coding: utf-8 -*-
"""期次（period）：台账**期次轴**的唯一口径。

为什么要有这个模块
------------------
「当期是哪一期」原先散在 15 处、4 套算法：`parse_ledger._latest_periods` 与
`compute.detect_periods` 是逐行相同的两份拷贝；`charts._infer_end_period` 与
`fill_docx` 各自 `re.search(r"(\\d{6})")`；`backtest` 用 `(20\\d{4})`；
`server/jobs.PERIOD_RE` 用 `^\\d{6}`。2026-09-18 已经因此产出过
「文件名是第 3 期、内容是第 4 期」的错稿（是回测抓到的，不是测试抓到的）。

口径（写在这里，别再各写一份）
------------------------------
1. **有效期次 = 列名是六位 YYYYMM 且该列有数据**。两条都要：
   - 不看列名形态（旧行为）会让脏表头 `2023.3` 成为一期，于是 `out/2023.3/`
     建得出来、而看板不认这个目录；
   - 只看形态不看数据会让台账里先建好的末期占位列（如未发布的 `202609`）
     挤进窗口，图与文对不上（差分图多算一格）。
2. **上期 = 严格早于当期的最近一个有效期次**（`prev_before`）。不是「日历上一期」：
   台账允许有缺口，复现历史期次时当期可能不是最后一期。
3. **期次只有一个规范形态**：六位字符串 `YYYYMM`。它是 DataFrame 列标签、也是
   `out/<期次>/` 的目录名前缀，但**目录名可以带后缀**（`202605_复现`）。
   两者之间的转换只走 `from_dir`，**禁止把目录名直接当列标签用**
   （`server/workbench.trace` 曾因此在逐格溯源页静默显示 `—`）。
4. **两个事实、一个值**：`Issue(period, prev)` 是一次报告对「这一期」的完整指代；
   `resolve()` 是定位它的唯一入口（override > 目录名 > 台账最新两期）。
   封面期号、中文年月都是派生 property——别再自己拼。

本模块**零第三方依赖**（不 import pandas）：`filled` 只读 `.columns` / `.notna()`，
所以 `server/` 侧可以放心地 import 它来取正则与校验，不会把 pandas 拖进启动路径。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

#: 规范形态：恰好六位数字。
PERIOD_RE = re.compile(r"^\d{6}$")

#: 目录名形态：以六位数字**开头**，后面允许后缀（`202605_复现`、`202607_备份`）。
#: 与 `PERIOD_RE` 的差别是刻意的：`out/` 下允许人工加的说明性后缀。
PERIOD_DIR_RE = re.compile(r"^\d{6}")

#: 脏期次的归一（`2026.5` / `2023-03` / `2023年7月` / `20233`）。
#: ⚠ 默认口径**不启用**——只在自愈 overlay 打开时由 `parse_ledger` 调用；
#:    `tests/test_agent_heal.py` 用「默认逐字不变」钉着这条。
_RAW_RE = re.compile(r"(20\d{2})\D*(\d{1,2})\D*$")

#: 「总第 N 期」的锚点。目前只有一句口头/文档作证：2026 年第 1 期 = 总第 35 期
#: （与仓库记录一致：commit 64ab634 收入 2026 年第 1-3 期人工原件，标注总第 35/36/37 期）。
#: ⏳ 锚点本身待馆员（卜彤）书面确认；见 CONTEXT.md 待办。
ISSUE_ANCHOR = "202601"
ISSUE_ANCHOR_TOTAL = 35

#: 一年 6 期（双月）。改这个数等于改期号口径。
ISSUES_PER_YEAR = 6


class PeriodUndetectable(ValueError):
    """台账里定位不出当期。继承 ValueError：旧调用方按 ValueError 捕获仍然成立。"""


class PeriodBeforeAnchor(ValueError):
    """期次早于期号锚点，总期号不可推。宁可报错也不给一个算出来的假期号。"""


def valid(s) -> bool:
    """是否规范期次（六位 YYYYMM）。前端表单、URL 期次、上传目录名都用这一条。"""
    return bool(PERIOD_RE.match(str(s or "")))


def parse(raw):
    """脏期次 → 规范 YYYYMM；认不出来**原样返回**（调用方按需报错，不由本函数决定）。

    只处理同一件事：年月之间/尾部的非数字噪声。`2026.5`→`202605`、
    `2023年11月`→`202311`、`20233`→`202303`；`20231231`、`202605_复现` 原样返回。
    `None` / 空 → `""`（保持旧实现的行为，便于 `if s` 判断）。
    """
    t = "" if raw is None else str(raw).strip()
    m = _RAW_RE.fullmatch(t)
    return f"{m.group(1)}{int(m.group(2)):02d}" if m else t


def from_dir(path):
    """目录名 / 路径 → 期次；不是期次目录返回 None。

    认的是 `202605_复现` 这类**带后缀**的期次目录；`out/_jobs`、`out/对样包_202607`
    一律 None（后者含六位数字但不在开头，刻意不认——它不是流水线产物目录）。
    """
    m = PERIOD_DIR_RE.match(pathlib.Path(path).name)
    return m.group(0) if m else None


def filled(wide):
    """**有效期次**的完整有序序列（升序＝台账列序）。这是本模块唯一的原始事实。

    `wide` 是 `parse_ledger` 落盘后由 `compute.load_wide` 装出来的宽表字典。
    """
    tc = wide["total_cites"]
    return [str(c) for c in tc.columns if PERIOD_RE.match(str(c)) and tc[c].notna().any()]


def detect(wide):
    """当期、上期。`detect(wide) == (filled(wide)[-1], filled(wide)[-2])`。"""
    got = filled(wide)
    if len(got) < 2:
        raise PeriodUndetectable("台账被引表有效期次不足 2 期，无法定位当期")
    return got[-1], got[-2]


def prev_before(periods, period):
    """序列里**严格早于** `period` 的最近一期；没有更早的期次则报错。

    复现历史期次时当期不是最后一期，所以不能取 `periods[-2]`。
    """
    earlier = [p for p in periods if p < str(period)]
    if not earlier:
        raise PeriodUndetectable(f"台账中没有早于 {period} 的有效期次")
    return earlier[-1]


def month(period) -> int:
    """期次的月份数（`202607` → 7）。报告正文里「较 12 月」这类表述用它。"""
    return int(str(period)[4:])


def label(period) -> str:
    """期次的中文年月（`202607` → `2026年7月`）。封面、表题、趋势标签共用一份。"""
    p = str(period)
    return f"{p[:4]}年{month(p)}月"


def _issue_index(period) -> int:
    """年内第几期：202601→1、202603→2、…、202611→6。"""
    return (int(str(period)[:4]) - 2026) * ISSUES_PER_YEAR + (month(period) + 1) // 2


def issue_of(period):
    """→ `(年内序号, 总期号)`。封面写「2026年第4期（总第38期）」用这两个数。

    早于锚点（`ISSUE_ANCHOR`）的期次直接报错：锚点之前的总期号没有任何依据，
    宁可失败也不要在封面上写一个算出来的假期号。
    """
    p = str(period)
    if not valid(p):
        raise PeriodUndetectable(f"不是规范期次（六位 YYYYMM）：{p!r}")
    if p < ISSUE_ANCHOR:
        raise PeriodBeforeAnchor(
            f"{p} 早于期号锚点 {ISSUE_ANCHOR}（＝总第 {ISSUE_ANCHOR_TOTAL} 期），"
            f"总期号不可推 —— 请先让馆员确认锚点（CONTEXT.md 待办）。")
    return _issue_index(p), ISSUE_ANCHOR_TOTAL + _issue_index(p) - _issue_index(ISSUE_ANCHOR)


# ------------------------------------------------------------------ 一期 = 两个事实
@dataclass(frozen=True)
class Issue:
    """一次报告对「这一期」的完整指代：当期 + 上期。

    上期口径＝`prev_before`（严格早于的最近一期，台账允许缺口），不是 `filled[-2]`。
    其余全部派生：中文年月、期号、封面串。早于锚点的期号**报错不给假期号**。
    """

    period: str
    prev: str

    @property
    def year(self) -> str:
        return str(self.period)[:4]

    @property
    def month(self) -> int:
        return month(self.period)

    @property
    def prev_month(self) -> int:
        return month(self.prev)

    @property
    def label(self) -> str:
        return label(self.period)

    @property
    def prev_label(self) -> str:
        return label(self.prev)

    @property
    def numbers(self) -> tuple[int, int]:
        """`(年内序号, 总期号)`；早于锚点抛 `PeriodBeforeAnchor`。"""
        return issue_of(self.period)

    @property
    def cover_issue(self) -> str:
        """封面期号串（`2026年第4期（总第38期）`）——`fill_docx` 按这个形态匹配。"""
        idx, total = self.numbers
        return f"{self.year}年第{idx}期（总第{total}期）"


def resolve(wide, out_dir=None, period_override=None) -> Issue:
    """定位一期：`period_override` > 目录名（且须是有效期次）> 台账最新两期。

    目录名带后缀（`202605_复现`）只在这里归一。override 不在台账有效期内
    直接报错——总不能拿别期数据填当期封面。
    """
    periods = filled(wide)
    if period_override:
        p = str(period_override)
        if p not in periods:
            span = f"{periods[0]}..{periods[-1]}" if periods else "（无）"
            raise PeriodUndetectable(f"台账无 {p} 期数据（有效期次：{span}）")
        return Issue(period=p, prev=prev_before(periods, p))
    d = from_dir(out_dir) if out_dir is not None else None
    if d and d in periods:
        return Issue(period=d, prev=prev_before(periods, d))
    p, _ = detect(wide)
    return Issue(period=p, prev=prev_before(periods, p))
