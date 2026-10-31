# -*- coding: utf-8 -*-
"""监测版·AI 解读：确定性事实摘要 → 500 字以上的总体解读（篇尾，可分段）。

红线姿势（与灵活产线同构）：
- 数字只来自 `facts_of()` 的确定性事实行（全部可回溯到缓存/趋势库/全局件），模型只组织语言；
- **默认走模型**（rick 2026-10-31 裁：解读默认 LLM 而非规则模板）：直调 `_attempt.attempt`
  （anchored＝数字盾：输出数字必须来自题面+事实摘要），不经写作位开关；
  额外挂一道**调用侧数字白名单 veto**——输出里出现事实行没有的数字即拒收、回落骨架
  （fc 论证的教训：外发数字防线宁可两道）；
- 无模型部署 / 调用失败 / 任一校验不过 → 返回句骨架（`mode="rule"`），报告照常完整。
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


def facts_of(cn: str, cache: dict, tr: dict | None = None) -> list[str]:
    """确定性事实行（一条一个关系，数字随行；渲染侧零换算）。

    tr＝`trend.combine(en)` 的跨期序列（可缺）：给了才出趋势/进位/增幅类事实。
    """
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
    top_cp = max(rows.items(), key=lambda kv: kv[1][4])
    out.append(f"被引最强学科是{cn_name(top_cites[0])}（被引 {top_cites[1][3]:,.0f}，篇均 {top_cites[1][4]:.2f}）")
    if top_papers[0] != top_cites[0]:
        out.append(f"论文体量最大的是{cn_name(top_papers[0])}（{top_papers[1][2]:,.0f} 篇）")
    if top_cp[0] not in (top_cites[0], top_papers[0]):
        out.append(f"篇均最高的是{cn_name(top_cp[0])}（{top_cp[1][4]:.2f}）")
    if total:
        out.append(f"全球机构总排名 {total[1]}/{cache['n_inst']}（按总被引）")
    # ---- 结构（top3 份额，与环图同口径）----
    psum = sum(r[2] for r in rows.values())
    if psum > 0:
        tops = sorted(rows.items(), key=lambda kv: -kv[1][2])[:3]
        shares = "、".join(f"{cn_name(st)} {r[2] / psum * 100:.1f}%" for st, r in tops)
        out.append(f"论文结构前三位：{shares}")
    # ---- 趋势/进位（tr 给了才有）----
    if tr:
        pts = tr.get("points") or []
        if len(pts) >= 2:
            first, last = pts[0], pts[-1]
            if first.get("total_cites") and last.get("total_cites"):
                growth = last["total_cites"] / first["total_cites"]
                out.append(f"总被引自 {first['period']} 的 {first['total_cites']:,.0f} 增至 "
                           f"{last['period']} 的 {last['total_cites']:,.0f}（约 {growth:.1f} 倍）")
            if first.get("total_rank") and last.get("total_rank"):
                out.append(f"全球总排名同期自第 {first['total_rank']} 位进至第 {last['total_rank']} 位"
                           f"（{len(pts)} 期在档）")
        tl: list[tuple[str, str]] = []
        for stem, seq in (tr.get("fields") or {}).items():
            if stem not in rows or not seq:
                continue
            first1 = next((f["period"] for f in seq if f.get("thr1") is not None
                           and f.get("cites") is not None and f["cites"] >= f["thr1"]), None)
            firstpm = next((f["period"] for f in seq
                            if f.get("m") and f.get("rank") is not None
                            and f["rank"] <= (f["m"] + 1) // 10), None)
            if first1:
                tl.append((first1, f"{cn_name(stem)} {first1} 起进入前 1%"))
            if firstpm:
                tl.append((firstpm, f"{cn_name(stem)} {firstpm} 起进入前 1‰"))
        if tl:
            tl.sort()
            out.append("进位时间线上最早的是" + tl[0][1] + "；最近的一次是" + tl[-1][1])
            pm_recent = [x for _, x in tl if "1‰" in x]
            if len(pm_recent) >= 2:
                out.append(f"前 1‰ 事件共 {len(pm_recent)} 次，近一次为{pm_recent[-1].split(' ', 1)[-1]}")
    nb = cache["neighbors"].get(en) or []
    if nb:
        me = next((r for r in nb if r[0] == en), None)
        if me:
            k = sum(1 for r in nb if r[6] > me[6]) + 1
            out.append(f"总排名 ±3 的对标窗内，本校被引列第 {k}/7 位")
    miss = 22 - n
    if miss:
        out.append(f"未上榜 {miss} 学科（低于收录线或未入册）无被引数据，报告不外推")
    return out


def _skeleton(facts: list[str]) -> str:
    """句骨架兜底：事实行直接成句（model 不可用时解读者就是它）。"""
    return "；".join(facts) + "。各章数字与派生算法见上文。"


_SYS = (
    "你是 ESI 学科监测报告的解读撰写者，面向图书馆员与学科办。"
    "写一篇 500 字以上的中文总体解读，分 2-4 个自然段（段间空行），"
    "按「学科格局总评 → 头部学科与前 1‰ 阵营 → 结构与相对强度 → 趋势与进位 → 短板与下程看点」"
    "的组织方式行文（可按数据取舍侧重），有观点、有比较、有侧重，语气克制，不写空话套话。"
    "任务里的所有数字都已替换为 [[n]] 占位标记：写进正文的数字必须以 [[n]] 形式出现"
    "（按行文需要自由选取，可重复引用），严禁新增、删除或改写任何数字与标记，"
    "严禁输出 [[n]] 之外的任何数字。只输出正文，不要解释、不要标题、不要分点符号。"
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


def insight(cn: str, period: str, cache: dict) -> dict | None:
    """→ {"text", "mode"}（mode=model|rule）| None（名单外/无事实）。不抛。"""
    try:
        s = sch.find(cn)
        if s is None or not cache:
            return None
        facts = facts_of(cn, cache)
        if not facts:
            return None
        tr = None
        try:
            from monitor import trend as mtrend                 # noqa: PLC0415
            tr = mtrend.combine(s["en"])
        except Exception:                                       # noqa: BLE001
            tr = None
        facts = [f"数据期次 {period}（Clarivate ESI）"] + facts_of(cn, cache, tr)
        safe = _skeleton(facts)
        topic = (f"为 {cn} 的 {period} 期 ESI 学科站位监测报告写一篇 500 字以上的总体解读；"
                 "数字只准用事实摘要里出现过的。")
        return compose_text(topic, facts, safe, label="monitor/insight",
                            veto=lambda t: number_guard(t, [topic, *facts]))
    except Exception:                                           # noqa: BLE001
        return {"text": _skeleton(facts_of(cn, cache)), "mode": "rule"}
