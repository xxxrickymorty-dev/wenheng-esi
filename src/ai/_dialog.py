# -*- coding: utf-8 -*-
"""dialog 构建器（对话前门：期次识别 [票 01] + 盘点 [票 02] + 核对门 [票 03] + 两意图路由 [票 07]）。

对话只做指挥（ADR-0006）：把馆员的一句话解析成「期次 / 意图」槽位，**先说出理解**，
再按「必需件清单」逐件盘点（动态监测表 / ESI 原始包 / 顶尖论文清单 / InCites 快照）：
缺就停 + 两条路（等发布 / 先做最新一期）、齐就给「去核对」。应答里出现的数字只有
解析与盘点的回显，逐条登记为 `fact` 来源——对话不产生任何台账数字。

**两意图（票 07，本能力只做路由）**：`kind ∈ {report, query, proceed, unclear, compare, qa}`——
- `report`：写报告（认期次 → 盘点 → 核对 → 出稿），现有链路不动；
- `query`：查数据——本能力**只判意图**，回答由服务器按意图调 `ai.run("qa", …)`
  （模型出口仍只有 `src/ai` 一处；这里不触网）；
- `proceed`：没带期次的「核完了，继续/出稿」——推进动作；
- `unclear`：认出了期次但没表态（「看看 9 月」「202607 怎么样」）——**不猜**，
  给两个明确出路（票 08 升级成单选卡）；都没中＝空（照旧反问期次）。
- `compare`（阶段 2，2026-10-30）：他校简报——「对比昆明理工大学和海南大学最新一期
  学科发展」。判据＝比较类字样 + 句中 ≥2 所校名 + 无指标词；命中即**直接调
  `flexible.panel`** 出数字（`panel` 三态：一所查不到其余照常），**不经模型、不经 qa**。
  形态选「规则命中直调」而不是「给内核加 panel 工具」：演示时不允许出现模型编数字的
  可能，且离线（无 key）也要能答；内核只出 `{period,intent}` 两个槽，加数字工具就得
  放宽 `parse_slots` 的零数字校验，等于拆掉唯一那条护栏。
- `qa`（2026-10-31）：问数并入——问数句式（指标词命中，见 `_METRIC`）且这轮**没有
  任何期次可依**（句里没有、槽位没有）时，不再反问「查哪一期」，**直接调问数引擎
  `aiqa_engine.plan/execute`**（白名单参数化 SQL、只读连接、零模型，照 compare 先例）；
  人话渲染＋逐行来源＋图型建议折进对话流，并照 `qa_log` 留痕。库缺席 → 讲人话空态。

**模型只在兜底位**（2026-10-13 票 03，ADR-0008）：规则 parse 与全部既有分支原样优先；
仅在「句内没有期次、有对话上文、规则未命中」的兜底点，若内核可用（qa 开关开 +
部署配好云模型），由 `_dialog_kernel`（pi 循环）补槽——只出 {period,intent} 槽位、
零数字、坏输出即拒；离线（无 key / `PROFILE=demo`）内核不启，纯规则可跑。

**槽位带过轮（2026-10-11，rick 实问暴露）**：句子里没带期次时，报告/推进意图与短应诺
（「对啊」）**沿用会话槽位里已确认的期次**——说过「9 月的报告」再问「怎么不做」不该被
反问期次。这不是猜期次，是接着聊（解析出的期次仍优先）。
**权限（2026-10-12 rick 定）**：操作员（评委）也有「出报告 + 审批」——报告/推进的路
两种角色都照常走（原先的「操作员只读」分支已删）；取数台等仍由工作区按角色裁剪。

盘点经**注入边缘**取：`ai.using(inventory=…)` 可替身注入（测试/脚本）；
生产走 `src/inventory.scan`（延迟导入——台账/pandas 不进 AI 层启动路径）。
盘点失败一律当「没有盘点」：回复退回只说理解，不猜发布状态、不拦住对话。

解析口径（GLOSSARY「期次」）：
- 期次只有一个含义＝**数据截止月**；「出稿月 / 发布月」不是期次说法——
  带这种说法就**停下纠正**，绝不换算、绝不猜；
- 显式六位期次（「再出 202605 的」）优先；其次「2026年9月」；再其次
  「9月 / 九月份」（年份取今天所在年）；都没有 → 反问，不静默。
- 「最新的 / 最近一期」（2026-10-13 rick 截图实问：复读死循环）——不猜数字：落
  `payload["periods"]`（服务端注入的有数据/产物期次，降序）里的**最近有效期次**；
  查数据反问不再裸复读（写明最近期次 + 给「查最新的」候选）。
- `payload["today"]` 可注入 ISO 日期（测试/脚本用）；HTTP 路由不传，
  生产走真实时钟（服务器时间即事实）。
"""
from __future__ import annotations

import datetime
import os
import pathlib
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, replace

from . import _dialog_kernel
from . import _runtime
from ._draft import RuleDraft
from ._numbered import NumberedText

#: 五种解析结局：period（认出来了）/ publication_month（出稿月说法，拒收）/
#: latest（「最新的」——落期次由 build 用 payload.periods 完成）/ no_period（没听出）。
CASES = ("period", "publication_month", "latest", "no_period")

#: 意图路由（票 07 + 阶段 2 + 问数并入）：一句话只归一类；认不准＝unclear（不猜，交给反问）。
KINDS = ("report", "query", "proceed", "unclear", "compare", "qa")

#: 一句里出现这些词 → 「继续/出稿」动作（核对回来后的推进；只在没带期次的句子上生效）。
_PROCEED = re.compile(r"继续|核完|核过|核对完了|出稿|开跑|开生成|开始生成|开始出稿|跑一遍")

#: 短应诺（对上一轮的确认）——带会话槽位期次时按「推进」走，不再反问期次。
#: 2026-10-11（rick 实问「对啊」被反问期次）：只认整句就是一句应诺的短句，不碰长句。
_AFFIRM = re.compile(r"^(对|嗯|是|好|行|可以|继续|对的|是的|对啊|对呀|好的|好嘞|ok|OK)"
                     r"[啊呀吧了呢。！!～~]*$")

#: 显式查数据（票 07）：「查 / 问」字样按查数据路由。
_ASK = re.compile(r"查|问")

#: 弱查数据信号（没有「查/问」字样也能认出是问数据）。
_QUERY_HINT = re.compile(
    r"多少|几门|几篇|几个|几条|哪些|接近度|排名|阈值|进\s*1|前\s*1|1‰|高被引|热点|论文|数据|发文|被引")

#: 盘点三种裁决：unpublished（未发布，停）/ missing（已发布但缺件，停）/ ready（齐，去核对）。
VERDICTS = ("", "unpublished", "missing", "ready")

#: 日期形态（payload.today 注入用；HTTP 路由不放行）。
DATE_FORMAT = "%Y-%m-%d"

_PERIOD = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)")
_YEAR_MONTH = re.compile(r"(20\d{2})\s*年\s*(0?[1-9]|1[0-2])\s*月")
_MONTH_CN = re.compile(r"([一二三四五六七八九十]{1,3})\s*月")
_MONTH_AR = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])\s*月")
_PUBLICATION = re.compile(r"出稿|发布")

#: 「最新的 / 最近一期」（2026-10-13）：只认「最新/最近 + 的/一期/那期」的形态——
#: **不碰**「最近六期 / 最近几期 / 最新的几期」（序列问法，走 qa 的多期口径）。
_LATEST = re.compile(r"(?:最新|最近)(?:的(?![几哪])|[一那]?期|的那?一?期)|最新(?![几哪的])")

#: 序列问法（「最近六期 / 最近几期 / 最新的几期」）：不落 qa 直调——这轮照旧反问
#: （2026-10-13 的既定话术钉着；引擎的多期序列以后再并，先不改这轮的路由面）。
_SERIES_SPAN = re.compile(r"(?:最近|最新)\s*的?\s*(?:[几六两三四五七八九十多]|\d+)\s*期")

#: 学科词（22 规范学科的中文面，抄 `parse_ledger.DISCIPLINES_CN` 的值）：问数槽要认
#: 「那材料科学呢」这类换学科追问；对话只认词，不产生任何台账数字。
_DISC_CN = ("农业科学", "生物学与生物化学", "化学", "临床医学", "计算机科学", "经济与商业",
            "工程学", "环境生态学", "地球科学", "免疫学", "材料科学", "数学", "微生物学",
            "分子生物学与遗传学", "多学科", "神经系统科学与行为学", "药理学与毒理学",
            "物理学", "植物与动物学", "精神病学与心理学", "社会科学", "空间科学")
_DISC_RE = re.compile("|".join(sorted(_DISC_CN, key=len, reverse=True)))
#: 上一期/上期/前一期：问数续聊的期次偏移词（引擎侧 `_periods_in` 同词表）。
_PREV_RE = re.compile(r"上一期|上期|前一期")

_REPORT_INTENT = re.compile(r"报告|出稿|生成|重出|再出|改做|做")

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}

#: 他校简报（阶段 2）：窗口期数（含末期）。双月一年＝六期，与 `panel` 默认一致。
PANEL_N = 6

#: 比较类字样。与「≥2 所校名」「无指标词」三条同时成立才归 `compare`。
_COMPARE = re.compile(r"对比|比较|比对|比一比|对照|各校|多校|他校|兄弟院校|横向")

#: 指标词：出现就**不**归简报——那是单学科问数（qa）的口径，交给既有路由，不改旧行为。
_METRIC = re.compile(r"接近度|被引|CNCI|阈值|顶尖|热点|发文|篇|排名|千分之一|1‰|前\s*1")

#: 校名候选：中文名 2–10 字 + 大学/学院/学校。
_SCHOOL = re.compile(r"[\u4e00-\u9fff]{2,10}?(?:大学|学院|学校)")

#: 句首套话：摘掉后才是校名。多字词摘完仍 ≥4 字就摘；单字连接词只在摘完仍是
#: 「≥2 字 + 大学/学院/学校」时摘——否则「同济大学」会被摘成「济大学」。
_CUES_MULTI = ("对比", "比较", "比对", "对照", "比一比", "以及", "还有", "一下",
               "分别", "各自", "看看", "帮我", "麻烦", "横向", "各校", "多校")
_CUES_ONE = ("和", "与", "跟", "及", "看", "查", "问", "请", "那", "这")

#: 他校简报（阶段 2 续，2026-10-30）：已知的「去『大学』二字」简称 → 全称。
#: 只在命中比较类字样时惰性构建（复用 `peers` 的缓存），用于识别「昆明理工 / 浙江工业」
#: 这类写法。唯一允许的简称＝`replace("大学", "")`，不猜任何其它缩写（云大/昆工之类不认）。
_SCHOOL_SHORT: dict[str, str] | None = None


def _short_forms() -> dict[str, str]:
    """所有校名的「去大学」简称 → 全称。惰性、缓存；建不出来（无数据）就返回空表。"""
    global _SCHOOL_SHORT
    if _SCHOOL_SHORT is not None:
        return _SCHOOL_SHORT
    forms: dict[str, str] = {}
    try:
        from flexible import peers as _peers                       # noqa: PLC0415
        tpl = _peers._latest_template()
        if tpl:
            nm = _peers._name_map(str(tpl))
            for _cn_norm, (_en, cn) in nm.items():
                short = (cn or "").replace("大学", "")
                if short and short != cn and short not in forms:
                    forms[short] = cn
    except Exception:                                             # noqa: BLE001
        pass
    _SCHOOL_SHORT = forms
    return forms


def parse_today(raw) -> datetime.date:
    """`payload.today` → date；缺省取真实今天；给了但不合法＝编程错误（抛）。"""
    if raw is None or raw == "":
        return datetime.date.today()
    try:
        return datetime.datetime.strptime(str(raw).strip(), DATE_FORMAT).date()
    except ValueError as e:
        raise ValueError(f"today 不是 ISO 日期（YYYY-MM-DD）：{raw!r}") from e


def _cn_month(text: str) -> int:
    """中文月份数字 → 1..12；不认识（如「二十」）返回 0。"""
    if text == "十":
        return 10
    if text == "十一":
        return 11
    if text == "十二":
        return 12
    return _CN_DIGITS.get(text, 0) if len(text) == 1 else 0


@dataclass(frozen=True)
class Parse:
    """一轮对话的解析结果（进 `Answer.data`，服务端照它合并槽位）。"""

    case: str                     # CASES 之一
    period: str = ""              # 数据截止月（case=period 时非空）
    year: int = 0
    month: int = 0
    intent: str = ""              # 「出报告」或空（意图槽）
    act: str = ""                 # 「proceed」或空（票 03：核完了/出稿——推进到出稿）
    kind: str = ""                # 票 07 路由：report/query/proceed/unclear/compare/空
    #: 他校简报：句子里认出的校名（≥2 所才归 compare；不进 `as_data()`，不上响应面）。
    schools: tuple = ()

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def as_data(self) -> dict:
        return {"case": self.case, "period": self.period,
                "intent": self.intent, "act": self.act, "kind": self.kind}


def _trim_name(raw: str) -> str:
    """候选串 → 校名：摘掉句首套话（「和海南大学」→「海南大学」）。

    单字连接词只在摘完仍 ≥4 字时摘，`同济大学` 因此不会被摘成 `济大学`。
    """
    name = raw
    for _ in range(3):                       # 最多三层（「帮我对比昆明理工大学」）
        before = name
        for cue in _CUES_MULTI:
            if name.startswith(cue) and len(name) - len(cue) >= 4:
                name = name[len(cue):]
        for cue in _CUES_ONE:
            if name.startswith(cue) and len(name) - 1 >= 4:
                name = name[1:]
        if name == before:
            break
    return name


def _compare_schools(norm: str) -> list[str]:
    """句子里能认出的校名；**≥2 所**才算他校简报（认不出＝交给既有路由，不改旧行为）。

    三条同时成立：比较类字样 + ≥2 所校名 + 无指标词。第三条是防抢：问
    「昆工和云大的化学接近度」是单学科问数，仍走 qa 的老路。

    校名抽取两路：① 带后缀的完整校名（昆明理工大学）；② 去「大学」二字的简称
    （昆明理工 / 浙江工业 / 上海交通 …），只认 `_short_forms()` 里的确切简称，
    并对完整校名已占用的字符区间做重叠保护，避免「理工」嵌在「昆明理工」里被重复认。
    """
    if not _COMPARE.search(norm) or _METRIC.search(norm):
        return []
    names: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _SCHOOL.finditer(norm):
        name = _trim_name(m.group(0))
        if name and name not in names:
            names.append(name)
            spans.append((m.start(), m.end()))
    for short, _full in sorted(_short_forms().items(), key=lambda kv: -len(kv[0])):
        if len(short) < 2:
            continue
        idx = norm.find(short)
        while idx != -1:
            if not any(s <= idx < e for s, e in spans) and short not in names:
                names.append(short)
                spans.append((idx, idx + len(short)))
                break
            idx = norm.find(short, idx + 1)
    return names if len(names) >= 2 else []


def _kind_for(case: str, *, ask: bool, intent: str, hint: bool, act: str,
              compare: bool = False, metric: bool = False) -> str:
    """路由（票 07 + 阶段 2 + 问数并入，纯规则、确定性）：始终只有一个类别。

    顺序即优先级：他校简报 → 出稿月纠正（问句除外）→ 显式查（查/问）→ 推进 →
    写报告 → 弱查（多少/接近度/进了没…）→ 问数句式（指标词，弱查没盖住的
    CNCI/顶尖等）→ 认出了期次但没表态＝含糊（不猜、给反问）；
    都没中＝空（照旧反问期次，不硬塞进几类）。

    指标词**不落给写报告**（2026-10-31）：出稿月纠正里没带「查/问」的指标句归
    `qa`（问数），不再给出稿链路；其余分支的既有优先级原样保留。
    """
    if compare:
        return "compare"
    if case == "publication_month":
        if ask:
            return "query"
        return "qa" if metric else "report"
    if ask:
        return "query"
    if act == "proceed":
        return "proceed"
    if intent:
        return "report"
    if hint:
        return "query"
    if metric:
        return "qa"
    if case == "period":
        return "unclear"
    return ""


def parse(text, *, today: datetime.date | None = None) -> Parse:
    """一句话 → 期次/意图（纯逻辑、确定性、零网络）。"""
    norm = unicodedata.normalize("NFKC", str(text or ""))
    today = today or datetime.date.today()
    intent = "出报告" if _REPORT_INTENT.search(norm) else ""
    ask = bool(_ASK.search(norm))
    hint = bool(_QUERY_HINT.search(norm))
    metric = bool(_METRIC.search(norm))
    schools = tuple(_compare_schools(norm))
    compare = bool(schools)

    def route(case: str, **kw) -> str:
        return _kind_for(case, ask=ask, intent=intent, hint=hint,
                         compare=compare, metric=metric, **kw)

    m_period = _PERIOD.search(norm)
    if m_period:
        year, month = int(m_period.group(1)), int(m_period.group(2))
        return Parse("period", period=f"{year:04d}{month:02d}",
                     year=year, month=month, intent=intent,
                     kind=route("period", act=""), schools=schools)

    m_ym = _YEAR_MONTH.search(norm)
    m_cn = _MONTH_CN.search(norm)
    m_ar = _MONTH_AR.search(norm)
    year = int(m_ym.group(1)) if m_ym else today.year
    month = int(m_ym.group(2)) if m_ym else 0
    if not month and m_cn:
        month = _cn_month(m_cn.group(1))
    if not month and m_ar:
        month = int(m_ar.group(1))

    if month and _PUBLICATION.search(norm):
        # 「9 月出稿 / 出稿月」＝把出稿月当期次——不支持，停下纠正（不换算）。
        return Parse("publication_month", year=year, month=month, intent=intent,
                     kind=route("publication_month", act=""), schools=schools)
    if month:
        return Parse("period", period=f"{year:04d}{month:02d}",
                     year=year, month=month, intent=intent,
                     kind=route("period", act=""), schools=schools)
    if _LATEST.search(norm):
        # 「最新的 / 最近一期」（2026-10-13 rick 截图实问）：不猜数字；落期次在
        # build()——用 payload.periods（服务端注入，降序）的最近有效期次。
        return Parse("latest", intent=intent,
                     kind=route("latest", act=""), schools=schools)
    # 没带期次的「继续 / 出稿」＝推进动作（目标期次用槽位里的）；带期次的句子不算。
    act = "proceed" if _PROCEED.search(norm) else ""
    return Parse("no_period", intent=intent, act=act,
                 kind=route("no_period", act=act), schools=schools)


def reply_for(p: Parse) -> str:
    """解析结果 → 应答（票 01 面：只说理解与纠正；盘点在 `_compose`）。"""
    if p.case == "period":
        return f"我按「数据截至 {p.label}」理解 → 期次 {p.period}。"
    if p.case == "publication_month":
        period = f"{p.year:04d}{p.month:02d}"
        return (f"期次只按「数据截止月」理解——「出稿月 / 发布月」不是期次说法。"
                f"要说数据截至 {p.label} 那期（期次 {period}），"
                f"请说「做 {p.month} 月的报告」。")
    if p.case == "latest":
        return ("「最新的」是哪一期，我这边一时看不到可用的期次列表——不猜。"
                "说一句带期次的吧，比如「查 202609 的化学接近度」。")
    return ("我还没听出是哪一期。说一句话，比如「帮我做 9 月的报告」"
            "——期次＝数据截止月份。")


# ---------------------------------------------------------------- 盘点（票 02）
def _real_scan(period: str):
    from inventory import scan                                    # noqa: PLC0415

    return scan(period)


def _normalize_inventory(raw) -> dict | None:
    """替身/真实盘点 → 规范形状（服务端原样透出；形状只此一份）。"""
    data = raw.as_data() if hasattr(raw, "as_data") else dict(raw or {})
    pieces = []
    for piece in data.get("pieces") or []:
        if not isinstance(piece, dict):
            continue
        pieces.append({"key": str(piece.get("key") or ""),
                       "label": str(piece.get("label") or ""),
                       "state": "ok" if piece.get("state") == "ok" else "missing",
                       "note": str(piece.get("note") or "")})
    if not pieces:
        return None
    return {"period": str(data.get("period") or ""),
            "released": bool(data.get("released")),
            "pieces": pieces,
            "n_pieces": len(pieces),
            "n_missing": sum(1 for x in pieces if x["state"] != "ok"),
            "fallback": str(data.get("fallback") or "")}


def _scan_inventory(period: str) -> dict | None:
    """盘点（可替身注入）；任何失败 → None（回复退回只说理解，不拦住对话）。"""
    ov = _runtime.overrides().get("inventory")
    try:
        raw = ov(period) if ov is not None else _real_scan(period)
    except Exception:                                              # noqa: BLE001
        return None
    if raw is None:
        return None
    return _normalize_inventory(raw)


def _pieces_block(inv: dict) -> str:
    lines = [f"盘点 · {inv['period']}（必需件 {inv['n_pieces']} 件）"]
    for piece in inv["pieces"]:
        mark = "✓" if piece["state"] == "ok" else "✗"
        tail = "已有" if piece["state"] == "ok" else "缺"
        lines.append(f"{mark} {piece['label']} · {tail}")
    return "\n".join(lines)


def _fallback_phrase(fb: str) -> str:
    return f"{fb}（数据截至 {fb[:4]}-{fb[4:6]}）"


def _compose(p: Parse, inv: dict) -> tuple[str, str, list]:
    """理解 + 盘点 + 裁决 → (应答, verdict, 动作)。

    2026-10-13 rick 定：**已并入期次直接放行**——原始件（ESI/InCites）缺不缺都不再卡
    「补件」（部署演示环境没有 数据与复现/，评委流程不能被堵住）；缺件照旧在盘点块里
    如实显示，出稿时省域/矩阵步降级跳过、沿用旧件。「缺件停」只对**未发布**期次保留。
    """
    fb = inv["fallback"]

    if not inv["released"]:
        verdict = "unpublished"
        head = f"做不了——这一期数据还没到（{inv['n_missing']} 件没到）。"
        if fb:
            tail = (f"两条路：\n① 先等发布：ESI 发布后这两件才拿得到（双月节奏）。\n"
                    f"② 先做最新一期：现在能做的完整一期是 {_fallback_phrase(fb)}。")
            actions = [{"kind": "send", "text": f"改做 {fb} 的"},
                       {"kind": "dismiss", "text": "先等等"}]
        else:
            tail = ("先等发布：ESI 发布后这两件才拿得到（双月节奏）。")
            actions = [{"kind": "dismiss", "text": "先等等"}]
    else:
        verdict = "ready"
        if inv["n_missing"]:
            head = (f"已并入台账——可以出稿（原始件缺 {inv['n_missing']} 件："
                    f"省域/矩阵表沿用旧件，出稿不受阻）。")
            tail = "去核对 ▸，或直接说「核完了，继续」。"
            actions = [{"kind": "goto", "view": "acquire", "period": p.period,
                        "text": "去核对 ▸"},
                       {"kind": "send", "text": "核完了，继续"}]
        else:
            head = "数据齐，走生成台三步条：①取数 ✓ → ②核对并并入 → ③一键生成。"
            tail = "去核对：跳到核对表格页逐件核，签过才并入。"
            actions = [{"kind": "goto", "view": "acquire", "period": p.period,
                        "text": "去核对 ▸"}]

    text = "\n".join([reply_for(p), "", _pieces_block(inv), "", head + (f"\n{tail}" if tail else "")])
    return text, verdict, actions


# ---------------------------------------------------------------- 核对门（票 03）
def _products_exist(root, period: str) -> bool:
    """该期已有产物？（红件清单是「出过稿」的标记；有它就要先问一次，绝不自动覆盖）"""
    return bool(period) and (pathlib.Path(root) / period / "red_slots.json").exists()


def _proceed(root, slot_period: str, p: Parse):
    """「核完了，继续 / 出稿」→ 核对门：通过＝开始出稿；没过＝拦住指回核对。

    返回 (应答, verdict, actions, run, inventory)。run＝「可以让前端开跑」的意图
    （auto=False 表示先问一次——产物已在，覆盖要人点）。

    2026-10-13 rick 定：**已并入期次直接放行**——原始件缺不缺不再拦（部署演示环境
    没有 数据与复现/，评委流程不能被堵）；「先别出稿」只留给未发布期次。
    """
    target = slot_period or ""
    if not target:
        return "还差一个期次——先说做哪期，比如「做 9 月的报告」。", "", [], None, None
    inv = _scan_inventory(target)
    if inv is None:
        actions = [{"kind": "goto", "view": "acquire", "period": target, "text": "去核对 ▸"}]
        return ("先停一下——这一期数据状态我一时看不到，先不出稿；"
                "去核对表格页确认一下。", "", actions, None, None)
    if inv["released"]:
        if _products_exist(root, target):
            # 已出过稿：先给「看这一期怎么做的 / 打开报告」两条安全出口，
            # 再给「覆盖重出」；评委演示不必为了看流程而覆盖金标成品。
            actions = [{"kind": "goto", "view": "archive", "period": target,
                        "text": "看这一期怎么做的"},
                       {"kind": "goto", "view": "report", "period": target,
                        "text": "打开报告"},
                       {"kind": "run", "period": target, "text": "覆盖重出"},
                       {"kind": "dismiss", "text": "保留，我先看看旧的"}]
            return ("核对通过、已并入台账。这一期已经有产物（上次出过）——"
                    "可以先看这一期怎么做出来的，或直接覆盖重出。",
                    "ready", actions,
                    {"period": target, "auto": False, "intent": "single_trend"}, inv)
        return ("核对通过、已并入台账。开始出稿——",
                "ready", [], {"period": target, "auto": True, "intent": "single_trend"}, inv)
    fb = inv["fallback"]
    tail = ("两条路：①去核对表格页（逐件核、签过才并入）"
            + (f"；②先做最新完整一期 {_fallback_phrase(fb)}。" if fb else "。"))
    actions = [{"kind": "goto", "view": "acquire", "period": target, "text": "去核对 ▸"}] \
        + ([{"kind": "send", "text": f"改做 {fb} 的"}] if fb else [])
    return f"先别出稿——这一期还没核对并并入。{tail}", "unpublished", actions, None, inv


# ---------------------------------------------------------------- 两意图（票 07）
def _query_reply(p: Parse, slot_period: str, *, latest: str = "") -> str:
    """查数据路由话术：有期次就放行（正文由服务器调 qa 能力给）；没有就先要期次。

    2026-10-13（rick 截图实问）：反问不再裸复读——知道最近有效期次就写明，
    并给「查最新的」候选（点一下＝发回一句话，走正常一轮；复用既有 `send` 动作）。
    """
    target = p.period or slot_period
    if not target:
        if latest:
            return (f"查哪一期？最近有效期次是 {latest}（数据截至 {latest[:4]}-{latest[4:6]}）。"
                    f"点下面「查最新的」，或说「查 {latest} 的化学接近度」——期次＝数据截止月份。")
        return ("查哪一期？说一句带期次的，比如「查 202609 的化学接近度」"
                "——期次＝数据截止月份。")
    return ""


def _unclear_reply(target: str) -> tuple[str, list]:
    """含糊不猜（票 07；票 08 升级成单选卡）：给两个明确出路。

    选项文本＝**要发回去的那句话**（点选即当下一句话发回，走正常一轮）。
    """
    text = f"这句我拿不准——是想做 {target} 的报告，还是查 {target} 的数据？"
    actions = [{"kind": "send", "text": f"做 {target} 的报告"},
               {"kind": "send", "text": f"查 {target} 的数据"},
               {"kind": "dismiss", "text": "先等等"}]
    return text, actions


# ---------------------------------------------------------------- 来源登记
def _register(p: Parse, inv: dict | None, *, latest: str = ""):
    """应答里每个数字的来源（解析与盘点的回显；全是 fact）。"""
    known: dict = {}
    if p.period:
        known[p.period] = {"kind": "fact", "pointer": "dialog/period", "label": "期次",
                           "detail": "期次只有一个含义：数据截止月", "fact": True}
    if p.year:
        known[str(p.year)] = {"kind": "fact", "pointer": "dialog/period.year",
                              "label": "期次年份", "detail": "由这句话里的月份与年份解析",
                              "fact": True}
    if p.month:
        known[f"{p.month:02d}"] = {"kind": "fact", "pointer": "dialog/period.month",
                                   "label": "期次月份", "detail": "从这句话里读出的月份（数据截止月）",
                                   "fact": True}
    if latest:
        # 「最新的」反问里写明的最近有效期次（服务端注入的 payload.periods[0]）。
        known.setdefault(latest, {"kind": "fact", "pointer": "dialog/latest",
                                  "label": "最近有效期次",
                                  "detail": "有数据/产物的期次（母本有效期次 ∪ 出过稿的产物目录）里的最新一期",
                                  "fact": True})
        known.setdefault(latest[:4], {"kind": "fact", "pointer": "dialog/latest.year",
                                      "label": "期次年份", "detail": "最近有效期次的年份",
                                      "fact": True})
        known.setdefault(latest[4:6], {"kind": "fact", "pointer": "dialog/latest.month",
                                       "label": "期次月份", "detail": "最近有效期次的月份",
                                       "fact": True})
    if inv:
        known.setdefault(str(inv["n_pieces"]),
                         {"kind": "fact", "pointer": "dialog/inventory",
                          "label": "必需件件数", "detail": "盘点按必需件清单逐件判",
                          "fact": True})
        if inv["n_missing"]:
            known.setdefault(str(inv["n_missing"]),
                             {"kind": "fact", "pointer": "dialog/inventory.missing",
                              "label": "没到的件数", "detail": "盘点结果：缺哪件说哪件",
                              "fact": True})
        fb = inv["fallback"]
        if fb:
            known.setdefault(fb, {"kind": "fact", "pointer": "dialog/fallback",
                                  "label": "现在能做的完整一期",
                                  "detail": "四件齐的最近一个有效期次", "fact": True})
            known.setdefault(fb[:4], {"kind": "fact", "pointer": "dialog/fallback.year",
                                      "label": "可做期次年份", "detail": "盘点选出的替代期次",
                                      "fact": True})
            known.setdefault(fb[4:6], {"kind": "fact", "pointer": "dialog/fallback.month",
                                       "label": "可做期次月份", "detail": "盘点选出的替代期次",
                                       "fact": True})

    def register(ti, pos, value):                                  # noqa: ARG001
        hit = known.get(value)
        if hit is not None:
            return dict(hit)
        return {"kind": "fact", "pointer": "dialog/example", "label": "示例",
                "detail": "应答里的举例（不是本期数据）", "fact": True}

    return register


def _period_in_text(norm: str, periods_desc) -> str:
    """句内出现的已知期次（取最新提到的一个）；没有 → 空。"""
    for x in periods_desc:
        if x and x in norm:
            return x
    return ""


def _periods_from(payload) -> list:
    """`payload["periods"]`（服务端注入的已知期次，降序）→ 六位期次列表；坏形状丢弃。"""
    raw = payload.get("periods") if isinstance(payload.get("periods"), list) else []
    out = []
    for item in raw:
        s = str(item or "").strip()
        if re.fullmatch(r"\d{6}", s) and s not in out:
            out.append(s)
    return out


def _latest_from(payload) -> str:
    """「最近有效期次」＝`payload["periods"]` 的第一个六位期次；没有/形状不合法 → ""。"""
    periods = _periods_from(payload)
    return periods[0] if periods else ""


# ---------------------------------------------------------------- 他校简报（阶段 2）
#: 预热只做一次（进程内）；失败不重试——它只影响首问快慢，不影响任何数字。
_WARM = {"started": False}
_WARM_LOCK = threading.Lock()


def _warm_panel_cache() -> None:
    """把 `panel()` 的读表缓存焐热（只读、不产数字、不改任何回答）。

    走**公共 API**（`panel(["云南大学"])`）而不是 `panel._rows`：六期 × 二十二学科的
    读表被 `lru_cache` 记住后，后面的对比问句从 20 多秒降到 1 秒内。云大是本项目
    锚点校，拿它预热与「谁问」无关——缓存键是（期次, 学科），与校名无关。
    """
    try:
        from flexible.panel import panel as _panel           # noqa: PLC0415
    except Exception:                                        # noqa: BLE001
        return
    try:
        _panel(["云南大学"], n=PANEL_N)
    except Exception:                                        # noqa: BLE001
        return


def _warm_async() -> bool:
    """后台预热（守护线程，进程内一次）。返回是否真的起了线程。

    两个关断位：`WENHENG_PANEL_PREWARM=0`（运维）、pytest（用例会与预热线程抢同一份
    `lru_cache`，同键重复计算，把断言拖成竞态）。**只在非 compare 轮触发**——否则
    首问就是对比题时，预热会和 panel 自己抢同一批读表。
    """
    if os.environ.get("WENHENG_PANEL_PREWARM", "1") == "0":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    with _WARM_LOCK:
        if _WARM["started"]:
            return False
        _WARM["started"] = True
    threading.Thread(target=_warm_panel_cache, name="wenheng-panel-prewarm",
                     daemon=True).start()
    return True


def _short(period: str) -> str:
    """`202609` → `2026-09`（对话里比「2026年9月」省地方，且逐位可核）。"""
    p = str(period)
    return f"{p[:4]}-{p[4:6]}"


def _panel_of(schools, period_end):
    """调 `flexible.panel`（只读、零模型）。返回 `(panel, 中文错误)`。

    延迟导入：openpyxl 不进 AI 层启动路径（与 `_real_scan` 同一姿势）。
    面板自己三态不抛（absent/error 在校内表达），这里只兜**整批**失败
    （期次不在数据目录、模块没装），照实回一句中文，不把异常甩给上层。
    """
    try:
        from flexible.panel import panel as _panel           # noqa: PLC0415
    except Exception as e:                                   # noqa: BLE001
        return None, f"灵活产线模块没装上（{type(e).__name__}）"
    try:
        return _panel(list(schools), period_end=period_end or None, n=PANEL_N), ""
    except Exception as e:                                   # noqa: BLE001
        return None, str(e).strip() or type(e).__name__


def _event_line(e: dict) -> str:
    """事件 → 一行话。口径同 `flexible/brief.py::_event_text`（那边出产物件，这里不反向
    依赖它的私有函数）：`overtake` 的 `school` 是**被追上的那方**，直接套 `text` 会读成
    「昆明理工大学 6 期追平昆明理工」——主语宾语同一校。
    """
    if e.get("kind") == "overtake":
        m = e.get("meta") or {}
        verb = "追平" if m.get("gap") == 0 else "反超"
        return f"被{m.get('with', '对手')}{verb}"
    return str(e.get("text") or "")


def _compare_reply(schools, period_end):
    """他校简报 → `(lines, line_sources, data, ok)`。

    **全文只由 `panel()` 的数字 + 固定句式拼出来**：这里不做任何算术
    （「共同上榜 N 个」是 panel 的 `len(common)`），也没有模型参与——回答里的每个
    数字都能在 `panel()` 的返回里逐字找到，也能回 ESI 学科表逐格核。

    `lines` 与 `line_sources` 一一对应（同下标），交给 `_register_panel` 逐行登记
    来源——这样「第 k 个数字 ↔ 来源」在长回答里仍按行对齐，而不是靠值猜。
    """
    from discipline_list import cn_of                        # noqa: PLC0415

    _runtime.trace({"step": 1, "tool": "panel", "label": "他校取数",
                    "summary": "正在读各期学科表", "ok": True, "refused": False, "ms": 0})
    p, err = _panel_of(schools, period_end)
    if p is None:
        lines = [f"这次没取到数：{err}",
                 "没有改动任何数据。换个期次，或核对一下校名在 ESI 里的写法再问一次。"]
        srcs = [{"pointer": "panel/error", "label": "取数失败"}] * len(lines)
        return lines, srcs, {"error": err}, False

    end = p["period_end"]
    periods = p["periods"]
    discs = p["disciplines"]
    span = f"{_short(periods[0])}–{_short(periods[-1])}"
    lines: list[str] = []
    srcs: list[dict] = []

    def add(text, pointer, label):
        lines.append(text)
        srcs.append({"pointer": pointer, "label": label})

    add(f"按 {_short(end)} 那期对比（窗口 {span}，{len(periods)} 期，{len(discs)} 个学科）：",
        f"panel/{end}/window", "期次窗口与学科口径")
    add("", f"panel/{end}/window", "期次窗口与学科口径")
    add("各期上榜学科数（期次由左到右）：", f"panel/{end}/periods", "期次序列")
    add("期次　" + " · ".join(_short(x) for x in periods),
        f"panel/{end}/periods", "期次序列")
    for s in p["schools"]:
        if s["status"] != "ok":
            continue                                 # 查不到的学校不画计数行（None≠0）
        cells = " · ".join("—" if v is None else str(v) for v in s["counts"])
        add(f"{s['cn']}　{cells}", f"panel/{end}/schools/{s['cn']}/counts",
            f"{s['cn']} 各期上榜学科数")

    ok = [s for s in p["schools"] if s["status"] == "ok"]
    add("", f"panel/{end}/common", "末期满血交集")
    if len(ok) >= 2 and p["common"]:
        add(f"共同上榜 {len(p['common'])} 个学科：" + "、".join(cn_of(x) for x in p["common"]) + "。",
            f"panel/{end}/common", "末期满血交集")
        add("共同之外另有（本校末期满血 − 共同交集，不是全校独有）：",
            f"panel/{end}/only", "各校另有")
        for cn, stems in p["only"].items():
            got = "、".join(cn_of(x) for x in stems) if stems else "—"
            add(f"· {cn}：{got}", f"panel/{end}/only/{cn}", f"{cn} 共同之外另有")
    elif len(ok) >= 2:
        add(f"{_short(end)} 这期没有共同上榜的学科。", f"panel/{end}/common", "末期满血交集")
    elif ok:
        add(f"只纳入了 {len(ok)} 所学校——共同/差异要两所以上才算。",
            f"panel/{end}/schools", "纳入的学校")

    add("", f"panel/{end}/events", "值得标注的变化")
    events = list(p["events"])
    if events:
        add("值得标注的变化：", f"panel/{end}/events", "值得标注的变化")
        for e in events[:10]:
            add(f"· {e['school']} · {_short(e['period'])}：{_event_line(e)}",
                f"panel/{end}/events/{e['school']}/{e['period']}", "值得标注的变化")
        if len(events) > 10:
            add("· ……（其余未列，可在简报里看全）", f"panel/{end}/events", "值得标注的变化")
    else:
        why = str((getattr(p["events"], "meta", None) or {}).get("error") or "")
        add("这一窗没有值得标注的变化。" + (f"（{why}）" if why else ""),
            f"panel/{end}/events", "值得标注的变化")

    if p["missing"]:
        add("", f"panel/{end}/missing", "缺数据的期次")
        add("下列期次没有学科表，表里记「—」，没有拿别的期次顶替："
            + "、".join(_short(x) for x in p["missing"]),
            f"panel/{end}/missing", "缺数据的期次")

    bad = [s for s in p["schools"] if s["status"] != "ok"]
    if bad:
        add("", f"panel/{end}/schools", "未能纳入的学校")
        for s in bad:
            what = "整校未在 ESI 中出现" if s["status"] == "absent" else "校名对不上"
            add(f"未能纳入：{s['query']}（{what}）——{s['note']}",
                f"panel/{end}/schools/{s['query']}/note", f"{s['query']} 未能纳入的原因")

    add("", f"panel/{end}/source", "数据源")
    add(f"数据源：{p['source']['dataset']}（{len(discs)} 个学科表，只读）。"
        f"上榜＝该校出现在该学科的 ESI 机构表；每个数字都能回原表逐格核对。",
        f"panel/{end}/source", "数据源")

    data = {"period_end": end, "periods": periods,
            "schools": [{"query": s["query"], "cn": s["cn"], "status": s["status"],
                         "counts": s["counts"]} for s in p["schools"]],
            "common": list(p["common"]), "only": dict(p["only"]),
            "events": [f"{e['school']} · {_short(e['period'])}：{_event_line(e)}"
                       for e in events],
            "missing": list(p["missing"]), "source": dict(p["source"])}
    return lines, srcs, data, True


def _register_panel(srcs):
    """逐行来源登记器（`NumberedText.of` 的 register）：第 ti 行的数字归该行来源。"""
    def register(ti, pos, value):                                  # noqa: ARG001
        info = srcs[ti] if 0 <= ti < len(srcs) else None
        if info is None:
            return {"kind": "fact", "pointer": "panel/unknown", "label": "他校简报",
                    "detail": "", "fact": True}
        return {"kind": "fact", "pointer": info["pointer"], "label": info["label"],
                "detail": "", "fact": True}

    return register


# ---------------------------------------------------------------- 问数（aiqa）
#: 底表缺席的空态（UX §十：一句 + 下一步；不讲技术术语）。
_QA_ABSENT = ("问数的底表还没生成，这一轮答不了数。",
              "下一步：让管理员先把台账汇总成问数库，再回来问一次。")


def _qa_pointer(row: dict) -> tuple[str, str]:
    """执行行 → (来源指针, 标签)：回答里的数字能回 aiqa.sqlite 的对应表逐格核。"""
    t = row.get("type")
    if t == "compare":
        return f"aiqa/facts/{row.get('period', '')}/{row.get('metric', '')}", "台账事实（问数库）"
    if t == "at":
        return (f"aiqa/facts/{row.get('disc', '')}/{row.get('metric', '')}"
                f"/{row.get('period', '')}", "台账事实（问数库）")
    if t == "overview":
        return f"aiqa/report_overview/{row.get('period', '')}", "报告概述（问数库）"
    if t == "table2":
        return f"aiqa/report_table2/{row.get('period', '')}", "报告大表（问数库）"
    if t == "province_compare":
        return (f"aiqa/province_fact/{row.get('period', '')}/{row.get('metric', '')}",
                "省域高校快照（问数库）")
    if t == "ynd_rank":
        return "aiqa/ynd_rank_series", "云大排名序列（问数库）"
    return f"aiqa/facts/{row.get('disc', '')}/{row.get('metric', '')}", "台账事实（问数库）"


def _aiqa_reply(question: str, root):
    """问数直调（2026-10-31）：一句话 → 问数引擎的数字＋图型建议。

    **照他校简报的先例**：不经模型、不经既有 qa 能力——`plan/execute` 是白名单
    参数化 SQL 于只读连接，回答里的每个数字都能回问数库逐格核。行与来源一一对应
    （同 `_compare_reply` 的形状，登记直接复用 `_register_panel`）。

    `root` 是数据根（out/ 一层）；库在 `<root>/../out/_aidata/aiqa.sqlite`
    （`aiqa_db.db_path` 唯一口径）。缺席 → 讲人话空态（ok=False），不把
    FileNotFoundError 甩给对话。留痕走 `qa_log` 既有 API，写失败只返回 -1 不阻断。
    返回 `(lines, line_sources, data, ok)`；`data` 携带图块与留痕号，服务端照它折进响应面。
    """
    try:
        import aiqa_db as _aiqa_db                           # noqa: PLC0415
        import aiqa_engine as _aiqa_engine                   # noqa: PLC0415
    except Exception as e:                                   # noqa: BLE001
        lines = [f"问数引擎这一轮没接上（{type(e).__name__}），换个问法或稍后再试。"]
        return lines, [{"pointer": "aiqa/error", "label": "问数引擎"}], None, False
    repo_root = pathlib.Path(root).parent
    try:
        con = _aiqa_db.connect_ro(repo_root)
    except FileNotFoundError:
        return (list(_QA_ABSENT),
                [{"pointer": "aiqa/absent", "label": "问数底表"}] * len(_QA_ABSENT),
                None, False)
    t0 = time.perf_counter()
    try:
        qp = _aiqa_engine.plan(question, con)
        result = _aiqa_engine.execute(con, qp["specs"])
        chart = _aiqa_engine.suggest_chart(con, qp["specs"], result)
        chart_data = _aiqa_engine.to_chart_data(con, chart, result)
        lines: list[str] = []
        srcs: list[dict] = []
        for row in result.get("rows") or []:
            # 整行空结果的两种类型不产行，逐行渲染会把引擎的兜底句误带进来——跳过。
            if row.get("type") == "table2" and not (row.get("rows") or []):
                continue
            if row.get("type") == "overview" and not (row.get("facts") or {}):
                continue
            ptr, label = _qa_pointer(row)
            for ln in _aiqa_engine.render_text(con, question, {"rows": [row]}).split("\n"):
                if ln.strip():
                    lines.append(ln)
                    srcs.append({"pointer": ptr, "label": label})
        if not lines:
            # 没认出指标/学科等：用引擎自己的人话兜底（「可问…」），不另写一套。
            lines = _aiqa_engine.render_text(con, question, {"rows": []}).split("\n")
            srcs = [{"pointer": "aiqa/plan", "label": "问数口径"}] * len(lines)
        if result.get("note"):
            lines.append(result["note"])
            srcs.append({"pointer": "aiqa/plan", "label": "问数口径"})
        elapsed = int((time.perf_counter() - t0) * 1000)
        n_rows = sum(len(r.get("points") or r.get("items") or r.get("rows") or [])
                     for r in result.get("rows") or [])
        record_id = _aiqa_db.log_qa(
            repo_root, user="", question=question, specs=qp["specs"],
            plan_origin=qp["origin"], n_rows=n_rows, elapsed_ms=elapsed,
            answer_text="\n".join(lines), chart_kind=str(chart.get("kind") or ""))
        data = {"chart": chart, "chart_data": chart_data, "record_id": record_id,
                "elapsed_ms": elapsed, "answered": bool(result.get("rows"))}
        return lines, srcs, data, True
    except Exception as e:                                   # noqa: BLE001
        lines = [f"这一轮没查成（{type(e).__name__}）。换个问法，或稍后再问一次。"]
        return lines, [{"pointer": "aiqa/error", "label": "问数引擎"}], None, False
    finally:
        con.close()


# ---------------------------------------------------------------- 构建器
def build(root, period, payload):                                  # noqa: ARG001
    """构建器入口：一句话 → RuleDraft（应答 + 来源 + 槽位/盘点数据 + 记账期次）。

    `root` 对解析与盘点无意义；`period`＝会话槽位里已有的期次（这轮对话谈的就是它）：
    - 句子里带期次 → 用句子里的（解析优先）；
    - **报告/推进意图没带期次 → 沿用槽位期次**（2026-10-11 rick 实问：说过「9 月的报告」
      再问「怎么不做」被反问期次——这不是猜，是接着聊）；短应诺（「对啊」）同此。
    - **「最新的」→ `payload.periods[0]`**（最近有效期次；2026-10-13 票 10，不猜数字）。
    - **他校简报（阶段 2）**：比较类问句 → 直接调 `flexible.panel` 出六期计数/共同差异/
      关键变化，逐行登记来源；期次缺了按台账最近一期，模型不参与（也不问内核）。
    - **指代兜底（票 03）**：句内没有期次、有对话上文、规则未命中 → 内核可用时问
      `_dialog_kernel`（只补 {period,intent} 槽位，零数字）；内核失败/坏输出/离线 →
      一切按原规则（含「查最新的」候选）。规则命中路径与内核缺席时逐字不变。
    - `payload.readonly`（服务端按角色注入）：操作员只读出稿/核对直接说明白，不演流程。
    """
    text = str(payload.get("text") or "")
    p = parse(text, today=parse_today(payload.get("today")))
    slot = str(period or "")
    kind = p.kind
    carried = False
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    latest = _latest_from(payload)
    was_latest = p.case == "latest"

    if was_latest and latest:
        # 「最新的」→ 最近有效期次（服务端注入 payload.periods，降序）——不猜数字；
        # 落成显式期次后走既有两条意图路（2026-10-13 rick 截图实问：不再复读）。
        p = replace(p, case="period", period=latest,
                    year=int(latest[:4]), month=int(latest[4:6]))

    # ---- 内核兜底（票 03，ADR-0008）：句内没有期次、有上文、规则未命中 → 模型补槽 ----
    # 规则 parse/既有分支全部原样优先；只有这个兜底点会问内核，且它只出 {period,intent}
    # 槽位（零数字、坏输出即拒）。内核不可用（无 key / demo / qa 关）＝零外发、不触发；
    # 内核失败/超时/坏输出 → 不改任何东西，一切按原规则（含「查最新的」候选）。
    # 短应诺（「对啊」）是规则确定性命中（槽位带过轮），不问内核。
    # 他校简报（compare）**不问内核**：它的期次缺了按台账最近一期出，模型不必碰这一轮。
    kernel_record = None
    kernel_filled = False
    kernel_receipts: tuple = ()
    norm_text = unicodedata.normalize("NFKC", text)
    metric_hit = bool(_METRIC.search(norm_text))
    rel_hit = bool(_PREV_RE.search(norm_text))
    m_disc_now = _DISC_RE.search(norm_text)
    slot_qm = str(payload.get("qmetric") or "")
    slot_qd = str(payload.get("qdisc") or "")
    qctx = bool(slot_qm or slot_qd)
    # 问数槽在场且这轮是问数续聊（上一期/指标词）→ 内核让路：这类句子由问数引擎
    # 直答（下面 qa 门），内核的期次兜底只服务报告/推进那些轮。
    if (p.case == "no_period" and history and kind != "compare"
            and not (qctx and (rel_hit or metric_hit))
            and not _AFFIRM.fullmatch(text.strip())):
        kr = _dialog_kernel.assist(
            text, history=history, periods=_periods_from(payload), slot=slot,
            tools={"scan_inventory": _scan_inventory,
                   "product_status": lambda per: _products_exist(root, per)})
        if kr.status != "off":
            kernel_record = kr.record()
        kernel_receipts = tuple(kr.receipts)
        if kr.status == "ok":
            if kr.period:
                p = replace(p, case="period", period=kr.period,
                            year=int(kr.period[:4]), month=int(kr.period[4:6]))
                kernel_filled = True
            if kr.intent and not p.intent:
                p = replace(p, intent=kr.intent)

    if kind in ("report", "proceed") and not p.period and slot and not was_latest:
        p = replace(p, case="period", period=slot,
                    year=int(slot[:4]), month=int(slot[4:6]))
        carried = True
    elif not kind and slot and _AFFIRM.fullmatch(text.strip()):
        p = replace(p, act="proceed", kind="proceed")
        kind = "proceed"
        carried = True
    elif not kind and history:
        # 追问（2026-10-12 rick 实问「这是几月的」）：解析不出意图但**有对话上文**时，
        # 当追问走 qa——上文随请求带过去解指代，不再回「我还没听出是哪一期」。
        p = replace(p, kind="query")
        kind = "query"
    if was_latest and not kind and p.period:
        # 认到「最新」但没表态（没上文）——与显式期次同款：含糊不猜，给两个出路。
        p = replace(p, kind="unclear")
        kind = "unclear"

    # 问数（2026-10-31 二步）：**凡问数句式或带问数槽的追问都直调引擎**——不再按
    # 「有没有期次」分家：槽位期次喂给引擎当入参，模型转述退为引擎认不出时的兜底。
    # 槽继承三形态：上一期（rel）/ 换学科（disc）/ 裸期次续问；比较类、报告与推进
    # 意图优先级更高（上面已路由）；多期序列问法照旧反问。
    if (payload.get("qa_direct", True)
            and kind in ("query", "unclear", "")
            and not _SERIES_SPAN.search(norm_text)
            and (metric_hit or (qctx and (rel_hit or m_disc_now or p.period)))):
        p = replace(p, kind="qa")
        kind = "qa"
    if kind == "unclear" and qctx and (p.period or rel_hit or m_disc_now):
        # 直答关着也必须模型作答（rick 2026-10-31）：带问数槽的追问解析出了期次/
        # 学科/指标，就不落含糊卡——交给既有 query 路由（服务器按意图调 qa 能力）。
        p = replace(p, kind="query")
        kind = "query"

    run = None
    actions: list = []
    rcpts: list = []                     # 规则轮回执（receipts-lite：只登记下面真调用的工具）
    lines: list | None = None            # 他校简报按行出（逐行登记来源）；其余仍是单段
    register = None
    compare_data = None
    qa_data = None
    if kind != "compare":
        # 冷启动 20 多秒不能让人干等（阶段 2）：在这一轮就把 panel 的读表缓存焐热，
        # 后台线程、进程内一次；对比轮自己不预热（免得与 panel 抢同一批读表）。
        _warm_async()
    if kind == "qa":
        # 问数直调（2026-10-31，照他校简报先例）：不经模型、不经既有 qa 能力；
        # 规划问句把**问数槽**折进去：上一轮认出的指标/学科、槽位期次都算数
        # （「上一期呢」「那材料科学呢」由此活）；句里已带的不重复。留痕记折完的问句。
        eff = text
        if not metric_hit and slot_qm:
            eff += f"（{slot_qm}）"
        if slot_qd and (not m_disc_now or m_disc_now.group(0) != slot_qd):
            eff += f"（{slot_qd}）"
        if rel_hit and not _PERIOD.search(norm_text):
            # 上一期锚点：句内期次 > 槽位期次 > 最近有效期次；取「有数据期」降序列的下一位
            # （答过 202607 再问上一期＝202605——锚着对话走，不是全局倒数第二）。
            periods_desc = _periods_from(payload)
            anchor = next((x for x in (_period_in_text(norm_text, periods_desc),
                                       slot, periods_desc[0] if periods_desc else "") if x), "")
            prev = ""
            if anchor and anchor in periods_desc:
                i = periods_desc.index(anchor)
                prev = periods_desc[i + 1] if i + 1 < len(periods_desc) else ""
            if prev:
                eff += f" {prev}"
        elif slot and not _PERIOD.search(norm_text):
            eff += f" {slot}"
        tc0 = time.perf_counter()
        lines, srcs, qa_data, qa_ok = _aiqa_reply(eff, root)
        reply = "\n".join(lines)
        register = _register_panel(srcs)
        rcpts.append(_dialog_kernel.tool_receipt(
            "aiqa", "问数", {"question": eff},
            "问数引擎按台账答了这一句" if qa_ok else "问数底表还没生成",
            ok=qa_ok, t0=tc0))
        verdict, inv = "", None
    elif kind == "query":
        # 查数据（票 07）：不盘点、不出稿；正文本地只在「没期次」时出声，
        # 有期次时的回答由服务器调 qa 能力给出（本能力只做路由）。
        reply = _query_reply(p, slot, latest=latest)
        actions = ([{"kind": "send", "text": "查最新的"},
                    {"kind": "dismiss", "text": "先等等"}]
                   if (not p.period and not slot and latest) else [])
        verdict, inv = "", None
    elif kind == "unclear":
        reply, actions = _unclear_reply(p.period or period)
        verdict, inv = "", None
    elif kind == "compare":
        # 他校简报（阶段 2）：期次优先句子里的，其次会话槽位，再次台账最近一期；
        # 都没有就交给 panel 自己取数据目录最新一期（它会在回答里写明是哪一期）。
        target = p.period or slot or latest
        tc0 = time.perf_counter()
        lines, srcs, compare_data, cmp_ok = _compare_reply(p.schools, target)
        reply = "\n".join(lines)
        register = _register_panel(srcs)
        rcpts.append(_dialog_kernel.tool_receipt(
            "panel", "他校取数",
            {"schools": list(p.schools), "period": target},
            (f"他校简报 · {compare_data.get('period_end') or target or '—'}"
             f"（{len(p.schools)} 所）") if cmp_ok else "这一轮没取到数",
            ok=cmp_ok, t0=tc0))
        verdict, inv = "", None
    elif kind == "proceed":
        # 内核补槽轮：目标期次用补出来的（规则轮原样用槽位，逐字不变）。
        reply, verdict, actions, run, inv = _proceed(
            root, p.period if kernel_filled else period, p)
    else:
        has_products = False
        if p.case == "period" and p.period:
            # 产物核对（确定性工具，receipts-lite）：True/False 都照实出回执。
            tc0 = time.perf_counter()
            has_products = _products_exist(root, p.period)
            rcpts.append(_dialog_kernel.tool_receipt(
                "product_status", "产物核对", {"period": p.period},
                "该期已有成品" if has_products else "该期暂无成品", ok=True, t0=tc0))
        if has_products:
            # 这期已出过稿（2026-10-11 rick 实问「帮我做 9 月的报告」）——
            # 先问一次覆盖，不静默重出、也不再报「还差几件」。
            # 安全出口优先：看运行档案 / 打开报告；覆盖重出放第三位。
            reply = ("这一期已经出过稿了（成品还在）——要看这一期怎么做出来的，"
                     "还是覆盖重出？")
            actions = [{"kind": "goto", "view": "archive", "period": p.period,
                        "text": "看这一期怎么做的"},
                       {"kind": "goto", "view": "report", "period": p.period,
                        "text": "打开报告"},
                       {"kind": "run", "period": p.period, "text": "覆盖重出"},
                       {"kind": "dismiss", "text": "保留，我先看看旧的"}]
            run = {"period": p.period, "auto": False, "intent": "single_trend"}
            verdict, inv = "ready", None
        else:
            inv = None
            if p.case == "period" and p.period:
                # 盘点（确定性工具，receipts-lite）：盘到与否都照实出回执。
                tc0 = time.perf_counter()
                inv = _scan_inventory(p.period)
                if inv is None:
                    rcpts.append(_dialog_kernel.tool_receipt(
                        "scan_inventory", "盘点", {"period": p.period},
                        "该期数据状态在这里看不到", ok=False, t0=tc0))
                else:
                    missing = f"，缺 {inv['n_missing']} 件" if inv["n_missing"] else ""
                    rcpts.append(_dialog_kernel.tool_receipt(
                        "scan_inventory", "盘点", {"period": p.period},
                        f"盘点 · {inv['period']}（必需件 {inv['n_pieces']} 件{missing}）",
                        ok=True, t0=tc0))
            if inv is None:
                if p.case == "period" and p.period:
                    # 有期次但盘点不到（如演示站没有台账/数据与复现）——如实说，别演。
                    lead = f"接着 {p.period} 那期——" if carried else reply_for(p) + "\n\n"
                    reply = (lead + "这一期的数据状态我在这里看不到（要本机带台账才盘得了）；"
                             "出稿去生成台看三步条，查数据可以直接问我（比如「查一下化学的接近度」）。")
                    actions = [{"kind": "goto", "view": "workbench", "period": p.period,
                                "text": "去生成台 ▸"}]
                    verdict = ""
                else:
                    reply, verdict, actions = reply_for(p), "", []
            else:
                reply, verdict, actions = _compose(p, inv)
    if lines is None:
        lines = [reply]
        register = _register(p, inv, latest=latest)
    number = NumberedText.of(lines, register)
    data = {**p.as_data(), "verdict": verdict, "actions": actions,
            "inventory": inv, "run": run}
    if kind in ("query", "unclear", "compare", "qa"):
        data["intent"] = ""            # 查数据/含糊/简报/问数轮不动意图槽
    if kind in ("report", "proceed", "compare"):
        data["qmetric"] = ""           # 切去写报告/推进/简报＝问数上下文到头了
        data["qdisc"] = ""
    if compare_data is not None:
        data["compare"] = compare_data
    if qa_data is not None:
        data["qa"] = qa_data
        _m_hits = [m.group(0) for m in _METRIC.finditer(norm_text)]
        data["qmetric"] = slot_qm or (max(_m_hits, key=len) if _m_hits else "")
        # 答的是哪期就锚哪期（写回 period 槽）：「上一期呢」的锚点跟着对话走
        data["period"] = _period_in_text(unicodedata.normalize("NFKC", eff),
                                         _periods_from(payload))
        data["qdisc"] = slot_qd or (m_disc_now.group(0) if m_disc_now else "")
    if kernel_record is not None:
        # 内核轮记录面（票 03）：核心据此把该轮 ai_calls 的 mode/backend/fallback/
        # egress/elapsed 记成 model|fallback 如实；不进 as_dict()（Answer 字段面冻结）。
        data["kernel"] = kernel_record
    return RuleDraft(
        rule_text=reply,
        number=number,
        rule_protected=number.protected,
        parts=(),
        task="",                       # modeled=False：task 不参与模型轮
        evidence=(),
        data=data,
        record_period=(compare_data or {}).get("period_end") or p.period,
        receipts=kernel_receipts + tuple(rcpts),   # 内核轮在前、规则轮在后（receipts-lite）
    )
