# -*- coding: utf-8 -*-
"""监测版报告引擎（最简版）：只吃 ESI 全局件，产出单文件 HTML 站位报告。

设计对应《监测版包契约-ESIonly（2026-10-31）》：全局件对任何学校一字不差，
所以**按期次建一次缓存**（机构总表＋22 榜本校行＋阈值＋±3 邻近窗），渲染毫秒级。
缓存与产物都落在 `monitor_data/`（不在任何只读数据红线区内，源数据只读）。
本模块零 LLM、零网络：数字全部可回溯到包内原始表。
"""
from __future__ import annotations

import datetime
import html
import json
import pathlib
import re

import openpyxl

import ledger_contract
from parse_ledger import DISCIPLINES_CN

from monitor import charts
from monitor import facts as mfacts
from monitor import schools as sch
from monitor.appearance import (appearance_css, appearance_from_body,
                                head_meta, normalize, read_signature_from_file,
                                signature)

WENHENG_ROOT = pathlib.Path(__file__).resolve().parents[2]
ESI_ROOT = ledger_contract.esi_root()      # 路径口径唯一在 ledger_contract（20261101 C1）
MONITOR_ROOT = WENHENG_ROOT / "monitor_data"

STEMS = ["Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
         "Computer Science", "Economics & Business", "Engineering", "Environment Ecology",
         "Geosciences", "Immunology", "Materials Science", "Mathematics", "Microbiology",
         "Molecular Biology & Genetics", "Multidisciplinary", "Neuroscience & Behavior",
         "Pharmacology & Toxicology", "Physics", "Plant & Animal Science",
         "Psychiatry Psychology", "Social Sciences, General", "Space Science"]


def norm(s) -> str:
    """学科/表头名归一：大写、/ 归空格、压空白；None → 空串。

    monitor 包内唯一实现（20261101 C1 收敛，原 report/trend/insight/compare 四份各抄一遍；
    None 兜底沿表头空单元格语义——trend._cols 会喂 None 表头，其余调用点从不传 None）。
    """
    return " ".join(str(s).upper().replace("/", " ").split()) if s is not None else ""


#: 22 学科中文名——唯一来源＝parse_ledger.DISCIPLINES_CN（20261101 C1 收敛，原
#: report.CN / insight._CN 两份）。台账键为 slash 风格，经 norm 按 monitor STEM 键重排；
#: 台账与 monitor 两表的中文值经核对逐条一致，键对不上会在导入期 KeyError 暴露。
_CN_LEDGER = {norm(k): v for k, v in DISCIPLINES_CN.items()}
CN = {s: _CN_LEDGER[norm(s)] for s in STEMS}

_f = lambda x: float(x)


def latest_period() -> str | None:
    """最新一个带机构总表的 ESI 期次目录；没有返回 None。"""
    if not ESI_ROOT.is_dir():
        return None
    ds = sorted((d.name for d in ESI_ROOT.iterdir()
                 if re.fullmatch(r"20\d{4}", d.name) and (d / "Institutions.xlsx").exists()),
                reverse=True)
    return ds[0] if ds else None


def global_papers(base: pathlib.Path) -> dict[str, float]:
    """全球学科.xlsx → {学科 stem（规范大写）: WoS Documents}；文件缺失/不可解析 → {}。

    表头行＝「Research Fields」所在行，列序＝排名/Research Fields/WoS Documents/…；
    文件里学科名大写可带 /（如 ENVIRONMENT/ECOLOGY），经 norm 归一后必须落在 STEMS
    内（版权行等杂行跳过）。站位表「相对强度」的全球分母数据源。"""
    path = base / "全球学科.xlsx"
    if not path.exists():
        return {}
    try:
        wb = openpyxl.load_workbook(path)
        rows = [r for r in wb.active.iter_rows(values_only=True)
                if any(c is not None and str(c).strip() for c in r)]
        wb.close()
        hdr = next((i for i, r in enumerate(rows) if len(r) > 1 and r[1] is not None
                    and str(r[1]).strip() == "Research Fields"), None)
        if hdr is None:
            return {}
        stems = {norm(s) for s in STEMS}
        out: dict[str, float] = {}
        for r in rows[hdr + 1:]:
            if len(r) < 3 or r[1] is None or not str(r[1]).strip() or r[2] is None:
                continue
            key = norm(str(r[1]).strip())
            if key in stems:
                out[key] = _f(r[2])
        return out
    except (OSError, ValueError, TypeError):
        return {}


def cache_path(period: str) -> pathlib.Path:
    return MONITOR_ROOT / f"_cache_{period}.json"


def build_cache(period: str) -> dict:
    """按期次建缓存：一次读盘，全名单受益。产物写入 monitor_data/。

    解析整体复用 trend 的强解析器（多版式候选名＋内容门禁＋重排拒收；20261101 C1
    收敛——原本地解析段是 trend 的严格子集）。本函数只做缓存形态组装：机构表衍生面
    （cn_inst/neighbors）、全球学科分母、下载元数据与落盘；fields/thr1/inst/n_inst
    与 trend.extract_period 逐键同构（tests/test_monitor_trend.py 钉）。"""
    from monitor import trend as mt                              # noqa: PLC0415
    # 函数级 import：trend 顶层 import report，模块级会成环
    base = ESI_ROOT / period
    if not base.is_dir():
        raise FileNotFoundError(f"期次目录不存在：{base}")
    en_names = [s["en"] for s in sch.SCHOOLS]
    en_set = set(en_names)

    t, raw = mt.extract_period_full(period)
    if not t["fields"] or t["n_inst"] is None:
        # 老版式/残表是趋势库的合法输入，但缓存直接喂渲染（分母、总排名窗），
        # 缺内容宁可炸在建造期也不落一份静默残缓存（与旧严格解析同失败面）。
        raise ValueError(f"{period}: 期次包解析不出机构总表/学科榜内容"
                         f"（trend._notes：{'；'.join(t['_notes'][:3])}）")
    inst_raw = raw["inst"]

    # ---- 机构总表衍生面：全量（±3 邻近需要全球行）＋ CHINA MAINLAND 子集（省内关键词） ----
    neighbors: dict[str, list] = {n: [] for n in en_names}
    cn_inst: list[list] = []
    if inst_raw and inst_raw["kind"] == "std":
        cols = inst_raw["cols"]
        ci = cols["country"] if cols["country"] is not None else 2
        data = inst_raw["data"]
        # N/A＝属地未标注（如部属医院），与 CHINA MAINLAND 一并按名关键词进省内
        cn_inst = [[str(r[1]).strip(), mt._rank_of(r[0]), mt._cell(r, cols["papers"]),
                    mt._cell(r, cols["cites"]), mt._cell(r, cols["cp"]), mt._cell(r, cols["hcp"])]
                   for r in data if mt._country(r, ci) in ("CHINA MAINLAND", "N/A")]
        for r in data:
            name = str(r[1]).strip()
            if name in en_set:
                k = mt._rank_of(r[0])
                neighbors[name] = [[str(x[1]).strip(), mt._country(x, ci), mt._rank_of(x[0]),
                                    mt._cell(x, cols["papers"]), mt._cell(x, cols["cites"]),
                                    mt._cell(x, cols["cp"]), mt._cell(x, cols["hcp"])]
                                   for x in data[max(0, k - 4):k + 3]]

    meta_path = base / "_下载信息.json"
    download = ""
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            download = f"{meta.get('首次下载', '')}/{meta.get('最近下载', '')}"
        except (json.JSONDecodeError, OSError):
            download = ""
    cache = {"period": period, "built": t["built"],
             "download": download, "n_inst": t["n_inst"],
             "fields": t["fields"], "thr1": t["thr1"],
             "global_papers": global_papers(base),
             "cn_inst": cn_inst, "neighbors": neighbors}
    MONITOR_ROOT.mkdir(parents=True, exist_ok=True)
    cache_path(period).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def load_cache(period: str) -> dict | None:
    p = cache_path(period)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 渲染
_e = html.escape
_fmt = lambda v: f"{v:,.0f}"


def report_data(cn: str, period: str, cache: dict, insight: dict | None = None) -> dict:
    """数据装配层：HTML 渲染与 Word 导出（monitor/docx.py）共用的唯一数据源。

    站位事实（上榜/前 1%/前 1‰/排名/接近度）统一取自 facts 层（monitor/facts.py，
    20261101 C6 唯一派生），本函数只做显示值换算与章节装配：千分位、×1.83、
    前 16.9%，两个消费者都不做第二套换算；趋势 combine 的装配同样收在这里。
    零 LLM、零网络。
    """
    s = sch.find(cn)
    if s is None:
        raise KeyError(cn)
    en = s["en"]
    tag = "985 工程" if s["is985"] else "211 工程"

    sf = mfacts.school_facts(cache, en)
    present = sf["present"]
    total = sf["total"]
    entered, near = [], []
    for stem in STEMS:
        px = sf["prox"].get(stem)
        if px is None:
            continue
        item = {"stem": stem, "cn": CN[stem], "r": present[stem], "prox": px}
        (entered if px >= 1 else near).append(item)
    pairs = sf["pairs"]
    pm_set = set(sf["pm"])
    # 相对强度（RCA）分母：缓存无 global_papers（老缓存/缺全球学科.xlsx）→ 显示 —
    gp = cache.get("global_papers") or {}
    g_sum = sum(gp.values())
    mine_sum = sf["mine_sum"]
    miss_list = [CN[stem] for stem in sf["miss"]]
    nb = sf["neighbors"]
    download = cache.get("download") or "—"

    def field_cells(kv):
        stem, r = kv
        m = cache["fields"][stem]["m"]
        pct = f"前 {r[0] / m * 100:.1f}%" if m else "—"
        gf = gp.get(norm(stem))
        rca = (f"×{(r[2] / mine_sum) / (gf / g_sum):.2f}"
               if g_sum and mine_sum and gf and r[2] is not None else "—")
        return [CN[stem], f"{r[0]} / {m}", pct, str(r[1]), _fmt(r[2]), _fmt(r[3]),
                f"{r[4]:.2f}", f"{r[5]:.0f}", f"{r[6]:.0f}", rca,
                "前 1‰" if r[0] <= cache["fields"][stem]["line"] else "前 1%"]

    out: dict = {
        "cn": cn, "en": en, "tag": tag, "period": period, "built": cache["built"],
        "download": download, "n_present": len(present),
        "meta": (f"数据源：Clarivate ESI {period} 期（下载 {download}）· "
                 f"{cn}上榜 {len(present)} / {len(STEMS)} 学科 · ESI 名 {en}"),
        "nums": [], "absent_note": None, "sections": [], "insight": insight,
        "algorithms": ["国内排名＝榜内 CHINA MAINLAND ∪ N/A（属地）行计数",
                       "1‰ 线＝第 ⌊(m+1)/10⌋ 位被引",
                       "接近度＝被引 ÷ 前 1% 机构阈值"],
        "footer": {
            "source": (f"数据来源：Clarivate ESI（Essential Science Indicators）{period} 期全局件，"
                       f"云南大学图书馆订阅账号下载（{download}）；本报告是监测版包契约的验证件，"
                       "不是对外报告，数字未经该校核对。"),
            "trend": "期 1 无历史台账，趋势章由历史全球档案回填生成；预测章随期次积累后解锁。",
            "engine": f"生成：文衡监测版引擎 src/monitor/（{cache['built']}）。"},
    }
    if total:
        out["nums"] = [
            {"label": "入围 ESI 前 1% 学科", "value": str(len(entered)), "suffix": " / 22",
             "note": "被引 ≥ 该学科机构阈值"},
            {"label": "全球机构总排名", "value": f"{total[1]:,}", "suffix": f" / {cache['n_inst']:,}",
             "note": "按总被引"},
            {"label": "总被引", "value": _fmt(total[3]), "suffix": "",
             "note": f"论文 {_fmt(total[2])} · 篇均 {total[4]:.2f}"},
            {"label": "进入全球前 1‰ 的学科", "value": str(len(pm_set)), "suffix": "",
             "note": "、".join(CN[stem] for stem, _r in pairs if stem in pm_set) or "—"},
        ]
    else:
        out["absent_note"] = (f"本期全球机构总表未收录该校（ESI 名 {en}）——可能低于收录线"
                              "或名称待人工核对。下方表格只呈现 22 学科榜里搜得到的学科行。")

    sec1 = {"num": "一", "title": f"学科站位（上榜 {len(present)} 学科，按被引降序）",
            "flow": True,
            "table": {"head": ["学科", "全球排名", "分位", "国内排名*", "论文", "被引", "篇均",
                               "高被引", "热点", "相对强度", "档位"],
                      "colclasses": ["", "n", "n", "n", "n", "n", "n", "n", "n", "n", ""],
                      "pill_cols": [10],
                      "rows": [field_cells(kv) for kv in pairs],
                      "subs": [stem for stem, _r in pairs]},
            "notes": ["* 国内排名＝榜内 CHINA MAINLAND ∪ N/A（属地）行计数推导，非 ESI 原生指标。"
                      "排名写法「全球第 N / 榜内 M 所」。分位＝rank ÷ m；"
                      "相对强度＝(本校该学科论文 ÷ 本校上榜学科论文合计) ÷ (全球该学科论文 ÷ 全球 22 学科论文合计)，"
                      "分母为本校上榜学科合计，部分覆盖下指数偏高，仅作结构参考。"]}
    if not pairs:
        sec1["table"]["placeholder"] = "22 学科榜内未搜到该校——低于收录线或未入册，本期不出学科行。"
    else:
        sec1["charts"] = [{"cap": "在榜学科论文结构",
                           "svg": charts.donut([(CN[stem], r[2] or 0) for stem, r in
                                                sorted(pairs, key=lambda kv: -(kv[1][2] or 0))],
                                               title=f"在榜论文合计\n{mine_sum:,.0f}")}]

    pm_cells = [[CN[stem], f"{r[0]} / {cache['fields'][stem]['m']}",
                 f"第 {cache['fields'][stem]['line']} 位",
                 _fmt(cache["fields"][stem]["line_cites"])]
                for stem, r in pairs if r[0] <= cache["fields"][stem]["line"]]
    sec2 = {"num": "二", "title": f"前 1‰ 俱乐部（{len(pm_cells)} 学科）"}
    if pm_cells:
        sec2["table"] = {"head": ["学科", "全球排名", "1‰ 线", "线上被引"],
                         "colclasses": ["", "n", "n", "n"], "rows": pm_cells}
        sec2["charts"] = [{"svg": charts.permille_strip(
            [(CN[stem], r[0], cache["fields"][stem]["m"], cache["fields"][stem]["line"])
             for stem, r in pairs if r[0] <= cache["fields"][stem]["line"]])}]
    sec2["notes"] = ([] if pm_cells else ["本期无学科进入前 1‰。"])
    sec2["notes"].append("1‰ 线＝榜内第 ⌊(m+1)/10⌋ 位机构的被引（m＝榜内机构数），与 extract_1permille 同法。")

    # ---- 三 趋势：trend.combine 跨期序列 → 总被引轨迹 + 最强学科排名轨迹 + 进位时间线 ----
    # 排名轨迹取当前在榜学科中 rank/m 分位最好、且趋势里有 ≥2 点序列的一个（y 轴反转）；
    # 时间线逐在榜学科找首次「被引 ≥ 前 1% 阈值」与「排名 ≤ 1‰ 线」的期次（thr1/m 缺的期
    # 跳过），按期升序。点数 <3 或读取异常 → 整章替换为一句 note，不报错。
    try:
        from monitor import trend as mt                              # noqa: PLC0415
        t = mt.combine(en)
    except Exception:                                                   # noqa: BLE001
        t = {"en": en, "points": [], "fields": {}}
    pts = t.get("points") or []
    flds = t.get("fields") or {}
    if len(pts) < 3:
        sec3 = {"num": "三", "title": "趋势", "notes": ["趋势数据不足，随期次积累解锁。"]}
    else:
        figs = [{"cap": "总被引轨迹",
                 "svg": charts.line_chart([("总被引",
                                            [(p["period"], p.get("total_cites")) for p in pts])])}]
        best = sorted((r[0] / cache["fields"][stem]["m"], stem) for stem, r in present.items()
                      if cache["fields"][stem].get("m"))
        for _pct, stem in best:
            seq = [(f["period"], f.get("rank")) for f in flds.get(stem) or []]
            if len(seq) >= 2:
                figs.append({"cap": f"{CN[stem]} · 全球排名轨迹",
                             "svg": charts.line_chart([(_e(CN[stem]), seq)], y_invert=True)})
                break
        # ---- 入榜与进位时间轴：文字清单换甘特轴。事件判定唯一在 facts.entry_events
        # （20261101 C6）：每在榜学科 first_seen＝序列首个有 rank 的期次，first1＝首次
        # cites≥thr1，firstpm＝首次 rank≤(m+1)//10（m/thr1 缺的期跳过）。本函数只做
        # pre 判定与装配：pre（档案起点前已入围）＝首个可判定观测点即满足 1% 且
        # first_seen 在档案首期——状态与档案同起、无法定位跨越点：有窗内 1‰ 事件的
        # pre 行照画（起点实心圆＋浅色延伸），无任何事件的归并成一句 note；中途入榜
        # 后达标＝真实事件行，按 entry1 升序。
        sec3 = {"num": "三", "title": "趋势", "flow": True,
                "notes": [_trend_note()], "charts": figs}
        periods = _trend_periods() or sorted({p["period"] for p in pts}
                                             | {f["period"] for seq in flds.values() for f in seq})
        p0 = periods[0] if periods else ""
        evf = mfacts.entry_events(t, present)
        ev: list[dict] = []
        pre_names: list[str] = []
        items: list[str] = []
        for stem in STEMS:
            ef = evf.get(stem)
            if not ef:
                continue
            fs, f1, fpm = ef["first_seen"], ef["first1"], ef["firstpm"]
            if f1:
                items.append(f"{CN[stem]}：{f1} 起进入前 1%（{ef['n_seq']} 期在榜）")
            if fpm:
                items.append(f"{CN[stem]}：{fpm} 起进入前 1‰（{ef['n_seq']} 期在榜）")
            pre = bool(ef["judge0"]) and f1 == ef["judge0"] and fs == p0
            entry1 = None if pre else f1
            if pre and (fpm is None or fpm == fs):
                pre_names.append(CN[stem])                       # 无窗内事件 → 归并不逐行画
                continue
            if entry1 or fpm:
                ev.append({"label": CN[stem], "first_seen": fs,
                           "entry1": entry1, "entrypm": fpm, "pre": pre})
            # 其余（从未进 1% 也无 1‰ 事件）＝窗内无动作可画，不外推
        if ev or pre_names:
            periods = sorted(set(periods) | {r0[k] for r0 in ev
                                             for k in ("first_seen", "entry1", "entrypm") if r0[k]})
            ev.sort(key=lambda r0: (r0["entry1"] or r0["entrypm"] or "9999", r0["label"]))
            sec3["timeline"] = {
                "cap": "入榜与进位时间轴",
                "svg": charts.entry_timeline(ev, periods=periods) if ev else "",
                "pre_note": (f"档案起点前已入围 {len(pre_names)} 学科：{'、'.join(pre_names)}。"
                             if pre_names else ""),
                "items": items}

    sec4 = {"num": "四", "title": "进位预警"}
    near_cells = [[x["cn"], _fmt(x["r"][3]), _fmt(cache["thr1"].get(norm(x["stem"]), 0)),
                   f"{x['prox']:.2f}"]
                  for x in sorted(near, key=lambda x0: -(x0["prox"] or 0))]
    notes4 = []
    if near_cells:
        sec4["table"] = {"head": ["学科", "本校被引", "前 1% 阈值", "接近度"],
                         "colclasses": ["", "n", "n", "n"], "rows": near_cells}
    elif entered:
        notes4.append(f"上榜学科全部已在前 1% 内（最小接近度 "
                      f"{min(x['prox'] for x in entered):.1f}×阈值），无临阈学科。")
    else:
        notes4.append("本期全球机构总表未收录该校，无法计算接近度。")
    # 接近度条形（log 轴，ref=1× 阈值线）：ESI 学科榜收录线≈1% 阈值，真实数据下 near
    # 恒空（在榜即入围），所以 entered 的入围余量与 near 的临阈距离画同一张图——
    # 余量最小（最临阈）的学科排最前，预警章从此有图。
    bars = sorted((x["cn"], x["prox"]) for x in (*entered, *near) if x["prox"])
    if bars:
        sec4["charts"] = [{"svg": charts.hbar_log(bars, lo=0.5, ref=1.0, ref_label="1× 阈值",
                                                  fmt=lambda v: f"{v:.2f}",
                                                  tick_fmt=lambda v: f"{v:g}×")} ]
    if miss_list:
        notes4.append(f"未上榜 {len(miss_list)} 学科（{'、'.join(miss_list)}）低于榜内收录线或未导出，"
                      "无被引数据，接近度不可算，不外推。")
    sec4["notes"] = notes4

    sec5 = {"num": "五", "title": "对标 · 总排名邻近（±3 名）",
            "table": {"head": ["机构", "总排名", "论文", "被引", "篇均", "高被引"],
                      "colclasses": ["", "n", "n", "n", "n", "n"],
                      "rows": [[str(r[0]).title(), str(r[2]), _fmt(r[3]), _fmt(r[4]),
                                f"{r[5]:.2f}", f"{r[6]:.0f}"] for r in nb]},
            "notes": ["自动邻近窗；跨省自由对比用插件页右上角「＋」进队列，一键出对比件（不限数量）。"]}
    out["sections"] = [sec1, sec2, sec3, sec4, sec5]
    return out


def insight_how(mode: str | None) -> str:
    """解读来源标注（HTML 与 docx 共用同一句文案）。"""
    return "模型解读（数字已过盾校验）" if mode == "model" else "规则拼装（模型不可用或校验未过的兜底）"


def _table_html(t: dict) -> str:
    """table 规格 → <table>：首列加粗＋可选英文名 subline；pill_cols 列出档位徽标；
    空表落 placeholder 合并行。"""
    ths = "".join(f'<th class="n">{_e(h)}</th>' if c == "n" else f"<th>{_e(h)}</th>"
                  for h, c in zip(t["head"], t["colclasses"]))
    pills = set(t.get("pill_cols") or ())
    trs: list[str] = []
    for i, row in enumerate(t["rows"]):
        tds = []
        for j, (cell, c) in enumerate(zip(row, t["colclasses"])):
            if j == 0:
                sub = f'<span class="en">{_e(t["subs"][i])}</span>' if t.get("subs") else ""
                tds.append(f"<td><b>{_e(cell)}</b>{sub}</td>")
            elif j in pills:
                pill = "pill pm" if "‰" in str(cell) else "pill ok"
                tds.append(f'<td><span class="{pill}">{_e(cell)}</span></td>')
            else:
                cls = ' class="n"' if c == "n" else ""
                tds.append(f"<td{cls}>{_e(cell)}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    if not trs and t.get("placeholder"):
        trs.append(f'<tr><td colspan="{len(t["head"])}" class="note">{_e(t["placeholder"])}</td></tr>')
    return f'<table>\n<thead><tr>{ths}</tr></thead>\n<tbody>{"".join(trs)}</tbody>\n</table>'


def _section_html(sec: dict) -> str:
    """section 规格 → <section>：标题＋表格＋notes＋图表＋时间线，顺序固定。"""
    parts = [f'<h2><span class="num">{sec["num"]}</span>{_e(sec["title"])}</h2>']
    if sec.get("table"):
        parts.append(_table_html(sec["table"]))
    for note in sec.get("notes", []):
        parts.append(f'<p class="note">{_e(note)}</p>')
    for fig in sec.get("charts", []):
        if fig.get("cap"):
            parts.append(f'<p class="cap">{_e(fig["cap"])}</p>')
        parts.append(fig["svg"])
    tl = sec.get("timeline")
    if tl:
        if tl.get("svg"):                                        # 图（HTML）；全 pre 场景整图省略
            parts.append(f'<p class="cap">{_e(tl["cap"])}</p>')
            parts.append(tl["svg"])
        if tl.get("pre_note"):
            parts.append(f'<p class="note">{_e(tl["pre_note"])}</p>')
        # tl["items"]（文字清单）只供 Word 导出（docx v1 不内联 svg），HTML 不再复读
    attr = ' class="flow"' if sec.get("flow") else ""
    return f"<section{attr}>\n" + "\n".join(parts) + "\n</section>"


_CSS = """
:root{--bg:#faf9f6;--card:#fff;--ink:#17181a;--ink-2:#3a3c40;--muted:#6f7278;--line:#e4e1da;
--line-2:#efede7;--ok:#2f6f5e;--ok-bg:#e8f1ed;--warn:#9a6b14;--warn-bg:#f6efdf;--radius:5px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
font-size:15.5px;line-height:1.6;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
.wrap{max-width:1000px;margin:0 auto;padding:0 clamp(18px,4vw,40px)}
header.top{padding:24px 0 0;display:flex;justify-content:space-between;gap:14px;font-size:12.5px;color:var(--muted);flex-wrap:wrap}
h1{font-size:clamp(1.6rem,1.3rem+1.6vw,2.2rem);font-weight:600;letter-spacing:-.02em;margin-top:clamp(34px,5vh,54px)}
.lead{margin-top:12px;max-width:66ch;color:var(--ink-2)}.lead b{background:#f0ece1;padding:0 .18em;font-weight:600}
.meta{margin-top:14px;font-size:12.5px;color:var(--muted)}
.nums{margin-top:22px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.nm{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:13px 15px}
.nm .nl{font-size:11.5px;color:var(--muted)}.nm .nv{font-size:clamp(1.2rem,1.1rem+.6vw,1.5rem);font-weight:600;margin-top:2px}
.nm .nx{font-size:11.5px;color:var(--muted)}
section{margin-top:clamp(40px,6vh,60px)}
h2{font-size:1.28rem;font-weight:600;display:flex;gap:10px;align-items:baseline}
h2 .num{font-size:12.5px;color:var(--muted);font-family:ui-monospace,Consolas,monospace}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:16px}
th{font-weight:600;text-align:left;padding:8px 10px 8px 0;border-bottom:1px solid var(--line);font-size:12.5px;color:var(--ink-2)}
th.n,td.n{text-align:right;padding-right:12px}
td{padding:9px 10px 9px 0;border-bottom:1px solid var(--line-2);vertical-align:top;color:var(--ink-2)}
td b{font-weight:600;color:var(--ink)}
td .en{display:block;font-size:11px;color:var(--muted);font-family:ui-monospace,Consolas,monospace}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{font-size:11px;padding:2px 8px;border-radius:99px;white-space:nowrap}
.pill.ok{background:var(--ok-bg);color:var(--ok)}
.pill.pm{background:var(--warn-bg);color:var(--warn);font-weight:600}
.note{font-size:12.5px;color:var(--muted);margin-top:10px}
.cap{font-size:12.5px;color:var(--muted);margin-top:16px}
footer{margin-top:clamp(48px,8vh,76px);padding:22px 0 46px;border-top:1px solid var(--line);font-size:12.5px;color:var(--muted);line-height:1.8}
@media (max-width:760px){.nums{grid-template-columns:repeat(2,1fr)}}
@media print{
@page{size:A4;margin:14mm}
body{background:#fff}
.nm{box-shadow:none;border-color:#ccc}
th{border-color:#bbb}td{border-color:#ccc}
section{break-inside:avoid}
section.flow{break-inside:auto}
h2{break-after:avoid}
table{break-inside:auto}
thead{display:table-header-group}
a{color:inherit}
}
"""


def render(cn: str, period: str, cache: dict, insight: dict | None = None,
           *, appearance: dict | None = None) -> str:
    """最简版站位报告：report_data() 的 HTML 消费者（Word 导出与其共用同一份数据装配）。

    appearance 为 None（不带外观参数）→ 逐字节保持现有输出：不挂 data-*、不追加 CSS，
    现有取数链与回归全靠这条。非 None → 在 <html> 上挂三轴属性，并在 _CSS 之后
    追加皮肤/字体/图表换色/模板 CSS；内容部分（数字、表格、章节）原样不动。
    """
    d = report_data(cn, period, cache, insight)
    nums_html = "".join(
        f'<div class="nm"><div class="nl">{_e(n["label"])}</div>'
        + (f'<div class="nv">{_e(n["value"])}<small>{_e(n["suffix"])}</small></div>'
           if n.get("suffix") else f'<div class="nv">{_e(n["value"])}</div>')
        + f'<div class="nx">{_e(n["note"])}</div></div>'
        for n in d["nums"])
    absent_html = (f'<p class="note" style="margin-top:18px">{_e(d["absent_note"])}</p>'
                   if d["absent_note"] else "")
    sh = {sec["num"]: _section_html(sec) for sec in d["sections"]}
    # 不带外观时，三个占位都留成空串——<html> / <head> / <style> 因此与改造前逐字节一致。
    if appearance is None:
        head_attrs = ""
        extra_css = ""
        appearance_meta = ""
    else:
        a = normalize(appearance)
        head_attrs = (f' data-template="{a["template"]}"'
                      f' data-skin-rpt="{a["skin_rpt"]}"'
                      f' data-font="{a["font"]}"')
        extra_css = appearance_css(appearance)
        appearance_meta = head_meta(appearance)   # <head> 里那枚可核对的签名标记

    return f"""<!DOCTYPE html>
<html lang="zh-CN"{head_attrs}>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{appearance_meta}<title>{_e(d["cn"])} · 学科监测报告 · {d["period"]}</title>
<style>{_CSS}{extra_css}</style>
</head>
<body>
<header class="top wrap"><span>监测版 · 包契约验证件 · {_e(d["tag"])}</span><span>生成 {_e(d["built"])} · <a href="{d["period"]}.docx" style="color:inherit;text-decoration:underline">导出 Word</a></span></header>
<div class="wrap">
<h1>{_e(d["cn"])} · 学科监测报告</h1>
<p class="lead">期 1 · 站位报告。数据面＝<b>{_e(d["period"])} 期 ESI 全局件</b>（机构总表、22 学科全球榜、阈值表）——
未取论文清单，论文层分析不在本版。所有数字可回溯到包内原始表。</p>
<p class="meta">{_e(d["meta"])}</p>
<div class="nums">{nums_html}</div>
{absent_html}

{sh["一"]}

{sh["二"]}

{sh["三"]}

{sh["四"]}

{sh["五"]}

{_insight_section(d["insight"])}

<footer>
{_e(d["footer"]["source"])}<br>
{_e(d["footer"]["trend"])}
派生算法：{" · ".join(d["algorithms"])}。<br>
{_e(d["footer"]["engine"])}
</footer>
</div>
</body>
</html>
"""


def _insight_section(insight: dict | None, num: str = "六") -> str:
    """篇尾解读段：AI 模型文本或句骨架（mode 如实标注；缺省＝无此段）。
    num＝章号（单校报告六章制的「六」；对比件按自身章数显式传）。"""
    if not insight or not (insight.get("text") or "").strip():
        return ""
    how = insight_how(insight.get("mode"))
    paras = [x for x in (_e(pp) for pp in insight["text"].split("\n\n")) if x.strip()]
    body = "".join('<p style="margin-top:10px;max-width:70ch;color:var(--ink-2)">' + pp + "</p>" for pp in paras)
    return f"""
<section>
<h2><span class="num">{num}</span>解读</h2>
{body}
<p class="note">{_e(how)}。</p>
</section>"""


def _trend_periods() -> list[str]:
    """趋势档案的 ok 期次列表（_index 现读，作时间轴 x 轴）；索引缺席 → []。"""
    try:
        from monitor import trend as mt                              # noqa: PLC0415
        idx = json.loads((mt.TREND_ROOT / "_index.json").read_text(encoding="utf-8"))
        return sorted(p for p, v in (idx.get("periods") or {}).items() if v.get("status") == "ok")
    except (OSError, json.JSONDecodeError, ImportError, AttributeError):
        return []


def _trend_note() -> str:
    """趋势章首注：期次范围与期数从 _trend/_index.json 读，不写死；索引缺席退化为定性句。"""
    try:
        from monitor import trend as mt                              # noqa: PLC0415
        idx = json.loads((mt.TREND_ROOT / "_index.json").read_text(encoding="utf-8"))
        ok = sorted(p for p, v in (idx.get("periods") or {}).items() if v.get("status") == "ok")
        n_bad = sum(1 for v in (idx.get("periods") or {}).values() if v.get("status") != "ok")
        if ok:
            return (f"趋势由 {ok[0]}–{ok[-1]} 共 {len(ok)} 期全球档案回填"
                    f"（{n_bad} 期坏档已剔除）；ESI 每期为滚动十年窗的当期快照。")
    except (OSError, json.JSONDecodeError, ImportError, AttributeError):
        pass
    return "趋势由历史全球档案回填；ESI 每期为滚动十年窗的当期快照。"


def generate(cn: str, period: str | None = None, *, force: bool = False,
             appearance: dict | None = None) -> pathlib.Path:
    """生成（或复用）一所学校的站位报告，返回文件路径。

    幂等（20261101 C7）：同校同期产物已存在 → 直接返回该路径，不再重跑 insight
    （LLM 不重复调用）。
    **外观变了也要重出（2026-11-05 修）**：带 appearance 时，产物 <head> 里留一枚
    签名标记；文件已存在但标记与本次不同、或旧件压根没标记（legacy）→ 覆盖重出，
    否则「换模板/皮肤/字体再点生成」会直接返回旧文件、控件等于死的。不带 appearance
    时完全照旧（文件在就返回，连读都不读）。
    **`force=True`＝界面上的「重新生成」**：无论同不同都覆盖重出。此前只有幂等，
    旧件若是规则兜底（模型当时不可用），按钮点了也原样返回，AI 解读永远出不来。
    重出写在临时件上再替换，失败不留半份（解读算在写盘之前，异常直接上抛）。
    **例外（供应商强制语义，rick 2026-11-04）**：开启态下 insight 的
    模型位失败抛 `AIRequiredError`，原样穿透——上抛即整单失败，不落半份产物。
    """
    period = period or latest_period()
    if not period:
        raise FileNotFoundError("数据与复现/ESI数据/ 下没有可用的 ESI 期次目录")
    out = MONITOR_ROOT / cn / f"{period}.html"
    if out.exists() and not force:
        if appearance is None:
            return out                       # 不带外观：完全照旧（不读、不改）
        # 带外观：只读文件头部核对标记——同外观幂等；外观变了 / 旧件没标记（legacy）→ 往下重出
        if read_signature_from_file(out) == signature(appearance):
            return out
    cache = load_cache(period) or build_cache(period)
    _AIRequiredError = None
    try:
        from ai._attempt import AIRequiredError as _e           # noqa: PLC0415
        _AIRequiredError = _e
    except Exception:                                           # noqa: BLE001
        pass
    ins: dict | None = None
    try:
        from monitor import insight as _ins                              # noqa: PLC0415
        ins = _ins.insight(cn, period, cache)
    except Exception as e:                                               # noqa: BLE001
        if _AIRequiredError is not None and isinstance(e, _AIRequiredError):
            raise   # 供应商强制语义：不落半份产物（rick 2026-11-04）
        ins = None
    out.parent.mkdir(parents=True, exist_ok=True)
    from ai import _record                                            # noqa: PLC0415
    _record.atomic_write_text(out, render(cn, period, cache, insight=ins,
                                          appearance=appearance))
    return out
