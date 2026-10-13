# -*- coding: utf-8 -*-
"""dialog 构建器（对话前门：期次识别 [票 01] + 盘点 [票 02] + 核对门 [票 03] + 两意图路由 [票 07]）。

对话只做指挥（ADR-0006）：把馆员的一句话解析成「期次 / 意图」槽位，**先说出理解**，
再按「必需件清单」逐件盘点（动态监测表 / ESI 原始包 / 顶尖论文清单 / InCites 快照）：
缺就停 + 两条路（等发布 / 先做最新一期）、齐就给「去核对」。应答里出现的数字只有
解析与盘点的回显，逐条登记为 `fact` 来源——对话不产生任何台账数字。

**两意图（票 07，本能力只做路由）**：`kind ∈ {report, query, proceed, unclear}`——
- `report`：写报告（认期次 → 盘点 → 核对 → 出稿），现有链路不动；
- `query`：查数据——本能力**只判意图**，回答由服务器按意图调 `ai.run("qa", …)`
  （模型出口仍只有 `src/ai` 一处；这里不触网）；
- `proceed`：没带期次的「核完了，继续/出稿」——推进动作；
- `unclear`：认出了期次但没表态（「看看 9 月」「202607 怎么样」）——**不猜**，
  给两个明确出路（票 08 升级成单选卡）；都没中＝空（照旧反问期次）。

**不做模型轮**（`_specs` 里 `modeled=False`）：期次猜错就是整期返工，解析因此
是确定性的；模型在结构上不参与，也不新增第二个模型出口（不触网可跑）。

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
import pathlib
import re
import unicodedata
from dataclasses import dataclass, replace

from . import _runtime
from ._draft import RuleDraft
from ._numbered import NumberedText

#: 四种解析结局：period（认出来了）/ publication_month（出稿月说法，拒收）/
#: latest（「最新的」——落期次由 build 用 payload.periods 完成）/ no_period（没听出）。
CASES = ("period", "publication_month", "latest", "no_period")

#: 两意图路由（票 07）：一句话只归一类；认不准＝unclear（不猜，交给反问）。
KINDS = ("report", "query", "proceed", "unclear")

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

_REPORT_INTENT = re.compile(r"报告|出稿|生成|重出|再出|改做|做")

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


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
    kind: str = ""                # 票 07 路由：report/query/proceed/unclear/空

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def as_data(self) -> dict:
        return {"case": self.case, "period": self.period,
                "intent": self.intent, "act": self.act, "kind": self.kind}


def _kind_for(case: str, *, ask: bool, intent: str, hint: bool, act: str) -> str:
    """路由（票 07，纯规则、确定性）：始终只有一个类别。

    顺序即优先级：出稿月纠正（问句除外）→ 显式查（查/问）→ 推进 → 写报告 →
    弱查（多少/接近度/进了没…）→ 认出了期次但没表态＝含糊（不猜、给反问）；
    都没中＝空（照旧反问期次，不硬塞进四类）。
    """
    if case == "publication_month":
        return "query" if ask else "report"
    if ask:
        return "query"
    if act == "proceed":
        return "proceed"
    if intent:
        return "report"
    if hint:
        return "query"
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

    m_period = _PERIOD.search(norm)
    if m_period:
        year, month = int(m_period.group(1)), int(m_period.group(2))
        return Parse("period", period=f"{year:04d}{month:02d}",
                     year=year, month=month, intent=intent,
                     kind=_kind_for("period", ask=ask, intent=intent, hint=hint, act=""))

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
                     kind=_kind_for("publication_month", ask=ask, intent=intent,
                                    hint=hint, act=""))
    if month:
        return Parse("period", period=f"{year:04d}{month:02d}",
                     year=year, month=month, intent=intent,
                     kind=_kind_for("period", ask=ask, intent=intent, hint=hint, act=""))
    if _LATEST.search(norm):
        # 「最新的 / 最近一期」（2026-10-13 rick 截图实问）：不猜数字；落期次在
        # build()——用 payload.periods（服务端注入，降序）的最近有效期次。
        return Parse("latest", intent=intent,
                     kind=_kind_for("latest", ask=ask, intent=intent, hint=hint, act=""))
    # 没带期次的「继续 / 出稿」＝推进动作（目标期次用槽位里的）；带期次的句子不算。
    act = "proceed" if _PROCEED.search(norm) else ""
    return Parse("no_period", intent=intent, act=act,
                 kind=_kind_for("no_period", ask=ask, intent=intent, hint=hint, act=act))


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
            actions = [{"kind": "run", "period": target, "text": "覆盖重出"},
                       {"kind": "dismiss", "text": "保留，我先看看旧的"}]
            return ("核对通过、已并入台账。不过这一期已经有产物（上次出过）——"
                    "直接重出会覆盖旧的。要覆盖重出吗？",
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


def _latest_from(payload) -> str:
    """`payload["periods"]`（服务端注入的已知期次，降序）→ 最近有效期次；没有/形状不合法 → ""。"""
    raw = payload.get("periods") if isinstance(payload.get("periods"), list) else []
    for item in raw:
        s = str(item or "").strip()
        if re.fullmatch(r"\d{6}", s):
            return s
    return ""


# ---------------------------------------------------------------- 构建器
def build(root, period, payload):                                  # noqa: ARG001
    """构建器入口：一句话 → RuleDraft（应答 + 来源 + 槽位/盘点数据 + 记账期次）。

    `root` 对解析与盘点无意义；`period`＝会话槽位里已有的期次（这轮对话谈的就是它）：
    - 句子里带期次 → 用句子里的（解析优先）；
    - **报告/推进意图没带期次 → 沿用槽位期次**（2026-10-11 rick 实问：说过「9 月的报告」
      再问「怎么不做」被反问期次——这不是猜，是接着聊）；短应诺（「对啊」）同此。
    - **「最新的」→ `payload.periods[0]`**（最近有效期次；2026-10-13 票 10，不猜数字）。
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

    run = None
    if kind == "query":
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
    elif kind == "proceed":
        reply, verdict, actions, run, inv = _proceed(root, period, p)
    else:
        if p.case == "period" and p.period and _products_exist(root, p.period):
            # 这期已出过稿（2026-10-11 rick 实问「帮我做 9 月的报告」）——
            # 先问一次覆盖，不静默重出、也不再报「还差几件」。
            reply = "这一期已经出过稿了（成品还在）——直接重出会覆盖旧的。要覆盖重出吗？"
            actions = [{"kind": "run", "period": p.period, "text": "覆盖重出"},
                       {"kind": "dismiss", "text": "保留，我先看看旧的"}]
            run = {"period": p.period, "auto": False, "intent": "single_trend"}
            verdict, inv = "ready", None
        else:
            inv = _scan_inventory(p.period) if (p.case == "period" and p.period) else None
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
    number = NumberedText.of([reply], _register(p, inv, latest=latest))
    data = {**p.as_data(), "verdict": verdict, "actions": actions,
            "inventory": inv, "run": run}
    if kind in ("query", "unclear"):
        data["intent"] = ""            # 查数据/含糊轮不动意图槽
    return RuleDraft(
        rule_text=reply,
        number=number,
        rule_protected=number.texts[0],
        parts=(),
        task="",                       # modeled=False：task 不参与模型轮
        evidence=(),
        data=data,
        record_period=p.period,
    )
