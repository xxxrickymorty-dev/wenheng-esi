# -*- coding: utf-8 -*-
"""监测版·AI 解读：确定性事实摘要 → 一段总体解读（章尾）。

红线姿势（与灵活产线同构）：
- 数字只来自 `facts_of()` 的确定性事实行（全部可回溯到缓存/全局件），模型只组织语言；
- 走 `ai._writer.compose`（内部过盾：模型只能引用题面+事实里出现的数字）；
  额外挂一道**调用侧数字白名单 veto**——输出里出现事实行没有的数字即拒收、回落骨架
  （fc 论证的教训：外发数字防线宁可两道）；
- **默认走模型**（rick 2026-10-31 裁：解读默认 LLM 而非规则模板）：直调 `_attempt.attempt`
  （anchored＝数字盾），不经写作位开关；无模型部署 / 调用失败 / 任一校验不过 →
  返回句骨架（`mode="rule"`），报告照常完整。
任何异常都不抛：解读是锦上添花，不是产出步骤。
"""
from __future__ import annotations

import re

from monitor import schools as sch


def _norm_num(x: str) -> str:
    return x.replace(",", "").replace("，", "").rstrip("%").rstrip(".")


def number_guard(output: str, sources: list[str]) -> bool:
    """True＝拒收：output 里出现了来源文本（题面+事实）中没有的数字。"""
    allow = {_norm_num(x) for src in sources for x in re.findall(r"\d[\d,，.]*", src)}
    for token in re.findall(r"\d[\d,，.]*", output):
        if _norm_num(token) not in allow:
            return True
    return False


def facts_of(cn: str, cache: dict) -> list[str]:
    """确定性事实行（一条一个关系，数字随行；渲染侧零换算）。"""
    s = sch.find(cn)
    if s is None:
        return []
    en = s["en"]
    tag = "985 工程" if s["is985"] else "211 工程"
    out: list[str] = []
    total = next((r for r in cache["cn_inst"] if r[0] == en), None)
    rows: dict[str, list] = {}
    for stem, d in cache["fields"].items():
        r = d["schools"].get(en)
        if r:
            rows[stem] = r
    if not rows:
        return [f"{cn}（{tag}）本期未进入 22 学科全球机构榜（低于收录线或未入册），报告如实呈现，不外推"]
    n = len(rows)
    thr1 = cache["thr1"]
    norm = lambda x: " ".join(str(x).upper().replace("/", " ").split())  # noqa: E731
    entered = [stem for stem, r in rows.items()
               if thr1.get(norm(stem)) and r[3] >= thr1[norm(stem)]]
    near = [(stem, r[3] / thr1[norm(stem)]) for stem, r in rows.items()
            if thr1.get(norm(stem)) and r[3] < thr1[norm(stem)]]
    pm = [stem for stem, r in rows.items() if r[0] <= cache["fields"][stem]["line"]]
    out.append(f"{cn}（{tag}）本期上榜 {n}/22 学科")
    if len(entered) == n:
        out.append(f"全部 {n} 个上榜学科已进入 ESI 前 1%")
    if near:
        stem, px = max(near, key=lambda kv: kv[1])
        out.append(f"离前 1% 最近的是{cn_name(stem)}（接近度 {px:.1f} 倍阈值）")
    if pm:
        best = min(pm, key=lambda stem: rows[stem][0])
        d = cache["fields"][best]
        out.append(f"{len(pm)} 个学科进入全球前 1‰：{'、'.join(cn_name(x) for x in sorted(pm, key=lambda x: rows[x][0]))}"
                   f"；其中{cn_name(best)}位次最靠前（全球第 {rows[best][0]}/{d['m']}）")
    top_cites = max(rows.items(), key=lambda kv: kv[1][3])
    top_papers = max(rows.items(), key=lambda kv: kv[1][2])
    out.append(f"被引最强学科是{cn_name(top_cites[0])}（被引 {top_cites[1][3]:,.0f}，篇均 {top_cites[1][4]:.2f}）")
    if top_papers[0] != top_cites[0]:
        out.append(f"论文体量最大的是{cn_name(top_papers[0])}（{top_papers[1][2]:,.0f} 篇）")
    if total:
        out.append(f"全球机构总排名 {total[1]}/{cache['n_inst']}（按总被引）")
    nb = cache["neighbors"].get(en) or []
    if nb:
        me = next((r for r in nb if r[0] == en), None)
        if me:
            k = sum(1 for r in nb if r[6] > me[6]) + 1
            out.append(f"总排名 ±3 的对标窗内，本校被引列第 {k}/7 位")
    miss = 22 - n
    if miss:
        out.append(f"未上榜 {miss} 学科无被引数据，报告不外推")
    return out


_CN = {"Agricultural Sciences": "农业科学", "Biology & Biochemistry": "生物学与生物化学",
       "Chemistry": "化学", "Clinical Medicine": "临床医学", "Computer Science": "计算机科学",
       "Economics & Business": "经济与商业", "Engineering": "工程学",
       "Environment Ecology": "环境生态学", "Geosciences": "地球科学", "Immunology": "免疫学",
       "Materials Science": "材料科学", "Mathematics": "数学", "Microbiology": "微生物学",
       "Molecular Biology & Genetics": "分子生物学与遗传学", "Multidisciplinary": "多学科",
       "Neuroscience & Behavior": "神经系统科学与行为学",
       "Pharmacology & Toxicology": "药理学与毒理学", "Physics": "物理学",
       "Plant & Animal Science": "植物与动物学", "Psychiatry Psychology": "精神病学与心理学",
       "Social Sciences, General": "社会科学", "Space Science": "空间科学"}
cn_name = lambda stem: _CN.get(stem, stem)  # noqa: E731


_SYS = (
    "你是 ESI 学科监测报告的解读撰写者，面向图书馆员与学科办。"
    "写中文解读：2-4 句、一段成文、不分点、不写建议与套话；"
    "有观点、有侧重，点出学科格局、位次关系与最值得注意的一两个事实，语气克制。"
    "任务里的所有数字都已替换为 [[n]] 占位标记：写进正文的数字必须以 [[n]] 形式出现"
    "（按解读需要自由选取，可重复引用），严禁新增、删除或改写任何数字与标记，"
    "严禁输出 [[n]] 之外的任何数字。只输出整段正文，不要解释、不要标题。"
)


def compose_text(topic: str, facts: list[str], safe: str, *, label: str, veto=None) -> dict:
    """默认走模型的解读生成：模型文本过盾 + veto，失败回落 safe。→ {"text", "mode"}。"""
    try:
        from ai import _attempt, _writer as _w
        fl = [str(x).strip() for x in facts if str(x).strip()]
        task = f"【节主题】\n{topic}\n\n【事实摘要】\n" + "\n".join(f"- {x}" for x in fl)
        res = _attempt.attempt(task, system=_SYS, ability="polish", anchored=True)
        fallback, result = None, safe
        if res.attempted and res.text is not None:
            result = res.text
            if veto is not None and veto(result):
                fallback, result = "guard_reject", safe
        mode = "model" if (res.attempted and res.text is not None and fallback is None) else "rule"
        backend = res.backend if res.attempted else "rule"
        try:
            _w._record_call(res, period="", label=label, fallback=fallback,
                            mode=mode, backend=backend)
        except Exception:                                       # noqa: BLE001
            pass
        return {"text": result, "mode": mode}
    except Exception:                                           # noqa: BLE001
        return {"text": safe, "mode": "rule"}


def _skeleton(facts: list[str]) -> str:
    """句骨架兜底：事实行直接成句（model 不可用时解读者就是它）。"""
    return "；".join(facts) + "。各章数字与派生算法见上文。"


def insight(cn: str, period: str, cache: dict) -> dict | None:
    """→ {"text", "mode"}（mode=model|rule）| None（名单外/无事实）。不抛。"""
    try:
        s = sch.find(cn)
        if s is None or not cache:
            return None
        facts = facts_of(cn, cache)
        if not facts:
            return None
        facts = [f"数据期次 {period}（Clarivate ESI）"] + facts
        safe = _skeleton(facts)
        topic = (f"为 {cn} 的 {period} 期 ESI 学科站位监测报告写一段总体解读；"
                 "数字只准用事实摘要里出现过的。")
        return compose_text(topic, facts, safe, label="monitor/insight",
                            veto=lambda t: number_guard(t, [topic, *facts]))
    except Exception:                                                   # noqa: BLE001
        return {"text": _skeleton(facts_of(cn, cache)), "mode": "rule"}
