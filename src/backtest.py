# -*- coding: utf-8 -*-
"""逐格回测：流水线计算值 vs 人工原件《学科信息参考》大表 / 概述 / 省表。

2026-09-18 改造（原件从 1 期扩到 4 期：第 1–4 期）。三处结构性改动：

① 大表**按表头语义对齐**，不再用写死的列索引。
   人工原件的列结构逐期在变，写死索引必然错位：
     第 1/2 期：阈值 / 与ESI前1%阈值差 / 篇均被引 / 顶尖论文 / 高被引论文 / 热点论文
                （**无** 1‰阈值、**无** 千分位；表头写「阈值」不写「1%阈值」）
     第 3 期：  1%阈值 / 1%阈值差 / 1‰阈值 / **引文影响力** / 顶尖论文
                （无千分位；「引文影响力」实测＝篇均被引＝总被引÷论文数）
     第 4 期：  1%阈值 / 1%阈值差 / 1‰阈值 / **千分位** / 顶尖论文
   只比两边**都有的语义列**；对方独有的列（高被引/热点论文）记作「口径演进」而非差异。
   接近度变化列的表头逐期不同（较11月 / 较1月 / 较3月 / 较5月），按「以『接近度』开头」识别。

② **期次与上期可自动推断**：期次取自 out_dir 目录名（`out/202601_复现` → 202601），
   上期取台账中该期之前最近的有效期次。所以 `agent/tools.py` 只传两个参数
   （`backtest.main(reference, out_dir)`）也能测对期次，不再恒定回测 202607。

③ 概述段数字改「**语义锚点 + 正则**」抽取（原件句式逐期稳定），
   不再写死 202607 的具体数字（旧版把「国际排名 995」「顶尖论文 274 篇」写进 checks，
   换期次必假报）。

用法：
    .venv\\Scripts\\python.exe src\\backtest.py "<人工原件.docx>" out/<期次> [期次] [上期]
回测只覆盖**数字**。图表去向 / T19 T20 空白 / 占位 / 清单 → 用 tools/compare_reports.py（模式 E）。
"""
import pathlib
import re
import sys

import pandas as pd
from docx import Document

import compute
from parse_ledger import DISCIPLINES_CN


# ---------------------------------------------------------------- 工具

def _norm_header(s):
    """表头归一化：去空白/换行，全角括号与符号拉平。"""
    return (s or "").strip().replace("\n", "").replace(" ", "").replace("　", "")


def _num(s):
    """把手册里的数字串转 float；空 / 短横 / 破折号 → None（表示"原件没填"）。

    ⚠️ 方向符号必须转成真正的正负号：机器稿的 `fmt_pct_change` 输出 `↑2.49%` / `↓2.49%`，
    而原件写 `+2.49%` / `-2.49%`。早先只把 ↑↓ 删掉 → 负号丢失，**符号相反的格子会被报成差异**
    （2026-09-18 在 202603/202605 各误报 3 行）。
    """
    t = (s or "").strip()
    t = t.replace("↑", "+").replace("↓", "-").replace("%", "")
    t = t.replace(" ", "").replace(",", "").replace("，", "")
    if t in ("", "-", "—", "–", "－", "/", "\\"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------- 列语义
# (机器字段, 判表头函数, 容差)  —— 容差 0 = 整数必须完全相等
_COL_RULES = [
    ("rank_cn_change", lambda h: h.startswith("国内排名"), None),
    ("papers", lambda h: h == "论文数", 0.0),
    ("cnci", lambda h: h.upper() == "CNCI" or h.upper() == "CNCI值", 0.006),
    ("total_cites", lambda h: h == "总被引频次", 0.0),
    ("thr_1pct", lambda h: h in ("阈值", "1%阈值"), 0.0),
    ("thr_1pct_gap", lambda h: h in ("1%阈值差", "与ESI前1%阈值差"), 0.0),
    ("thr_1permille", lambda h: h == "1‰阈值", 0.0),
    ("permille_rank", lambda h: h == "千分位", 0.0006),
    ("cites_per_paper", lambda h: h in ("篇均被引", "引文影响力"), 0.006),
    ("top_papers", lambda h: h == "顶尖论文", 0.0),
    ("prox_change", lambda h: h.startswith("接近度"), 0.006),
]

FIELD_CN = {
    "rank_cn_change": "国内排名/变化", "papers": "论文数", "cnci": "CNCI值",
    "total_cites": "总被引频次", "thr_1pct": "1%阈值", "thr_1pct_gap": "1%阈值差",
    "thr_1permille": "1‰阈值", "permille_rank": "千分位(引文影响力)",
    "cites_per_paper": "篇均被引", "top_papers": "顶尖论文", "prox_change": "接近度变化",
}


def _map_headers(header_cells):
    """表头 → {机器字段: 列下标}；返回 (映射, 未识别的表头名)。"""
    mapping, unknown = {}, []
    for i, h in enumerate(header_cells):
        hn = _norm_header(h)
        if not hn or hn in ("ESI学科", "学科", "学科/高校"):
            continue
        for field, pred, _tol in _COL_RULES:
            if field in mapping:          # 一个字段只认第一个命中的列
                continue
            if pred(hn):
                mapping[field] = i
                break
        else:
            unknown.append((i, hn))
    return mapping, unknown


def _norm_rank(s):
    """国内排名/变化：抹平空格与箭头写法差异。"""
    t = (s or "").strip().replace(" ", "").replace("　", "")
    t = t.replace("上升", "↑").replace("下降", "↓")
    return t


def _mine_fmt(field, row):
    # 派生列：台账不直接存「篇均被引」，由 总被引÷论文数 现算
    # （原件第 1–3 期该列叫「篇均被引」/「引文影响力」，实测同义）
    if field == "cites_per_paper":
        return round(float(row["total_cites"]) / float(row["papers"]), 6)
    v = row[field]
    if field == "rank_cn_change":
        return _norm_rank(str(v))
    if field == "prox_change":
        return _num(str(v))
    if field in ("cnci",):
        return round(float(v), 6)
    if field == "permille_rank":
        return round(float(v), 6)
    if field == "top_papers":
        return None if (isinstance(v, str) and v.strip() == "") else float(v)
    if v is None or v != v:          # None / NaN
        return None
    return float(v)


def _cmp(field, mine, doc_s, tol):
    """返回 (ok, note)。ok=None 表示不可判（原件空 / 机器也空）。"""
    if field == "rank_cn_change":
        d = _norm_rank(doc_s)
        if d == "":
            return None, "原件空"
        return (_norm_rank(str(mine)) == d), f"计算={mine} 手工={doc_s}"
    dv = _num(doc_s)
    if dv is None and mine is None:
        return None, "两边皆空"
    if dv is None:
        return None, f"原件未填（计算={mine:g}）"
    if mine is None:
        return False, f"计算=空 手工={doc_s}"
    return (abs(mine - dv) <= tol + 1e-12), f"计算={mine:g} 手工={doc_s}"


# ---------------------------------------------------------------- 期次

def _filled_periods(wide):
    df = wide["total_cites"]
    return [str(c) for c in df.columns if str(c).isdigit() and df[c].notna().any()]


def detect_period_from_dir(out_dir):
    m = re.search(r"(20\d{4})", pathlib.Path(out_dir).name)
    return m.group(1) if m else None


def prev_period(wide, period):
    earlier = [p for p in _filled_periods(wide) if p < period]
    if not earlier:
        raise SystemExit(f"台账中没有早于 {period} 的有效期次")
    return earlier[-1]


# ---------------------------------------------------------------- 原件读取

def load_doc_tables(docx_path):
    d = Document(docx_path)

    def pick(pred):
        for tb in d.tables:
            if tb.rows and pred(_norm_header(tb.rows[0].cells[0].text)):
                return tb
        return None

    big = pick(lambda h: h.startswith("ESI学科"))
    prov = pick(lambda h: h.startswith("机构名称"))
    if big is None:
        # 兜底：取第一个 ≥10 列的表（旧行为）
        big = [tb for tb in d.tables if len(tb.columns) >= 10][0]
    if prov is None:
        cands = [tb for tb in d.tables if len(tb.columns) >= 10]
        prov = cands[1] if len(cands) > 1 else None
    return d, big, prov


# ---------------------------------------------------------------- 概述锚点

# (标签, 取机器值的函数, 正则, 类型)   —— 类型 int/signed/float
_OV_ANCHORS = [
    ("国际排名（当期）", lambda f: f["rank_intl_now"], r"我校位于第(\d+)位", "int"),
    ("国际排名较上期上升", lambda f: f["rank_intl_delta"],
     r"我校位于第\d+位[，,]\s*较上期上升(\d+)位", "int"),
    ("ESI前1%学科数", lambda f: f["n_disc_1pct"], r"我校目前有ESI前1%学科(\d+)个", "int"),
    ("顶尖论文（当期）", lambda f: f["top_papers_now"], r"本期我校共有(\d+)篇顶尖论文", "int"),
    ("顶尖论文较上期变化", lambda f: f["top_papers_delta"],
     r"较上期总数(增加|减少)(\d+)篇", "signed"),
    ("国内排名上升学科数", lambda f: f["rank_up"], r"有(\d+)个学科排名上升", "int"),
    ("国内排名下降学科数", lambda f: f["rank_down"], r"(\d+)个学科排名下降", "int"),
    ("国内排名持平学科数", lambda f: f["rank_flat"], r"(\d+)个学科排名与\S+持平", "int"),
    # 国内机构 / 国内高校排名升降是**两个独立 delta**，原件第 2/3 期并不相等（+2/+1、+3/+2）。
    # 2026-09-18 回测发现 sentences.py 曾用 inst_delta 套两句并写「均」→ 加这两个锚点守住。
    # 原件句式逐期不同（「较上期不变」无升降词 → 自动落 ⚠️ 未抽到，安全）。
    ("国内机构排名较上期升降", lambda f: f["rank_cn_inst_delta"],
     r"国内机构排名[^，。；;]*?(上升|下降)(\d+)位", "signed"),
    ("国内高校排名较上期升降", lambda f: f["rank_cn_uni_delta"],
     r"国内高校排名[^，。；;]*?(上升|下降)(\d+)位", "signed"),
    # ⚠️ 锚点必须带「前1‰」语境：第 1 期单学科段落里有「…ESI前1%接近度为66.96%」，
    #    只用 `接近度为([\d.]+)%` 会抓到它（1% 接近度 ≠ 1‰ 接近度），曾误报。
    ("1‰接近度最高学科（数值）", lambda f: f["best_1permille"]["prox_pct"],
     r"前1‰接近度较高的学科为\S+?，接近度为([\d.]+)%", "float"),
]


def _grab(pat, text):
    m = re.search(pat, text)
    return m.groups() if m else None


# ---------------------------------------------------------------- 主流程

def main(docx_path, out_dir="out/202607", ledger_dir=None, period=None, prev=None):
    ledger_dir = ledger_dir or out_dir
    wide, ni, nc, thr = compute.load_wide(ledger_dir)
    P = period or detect_period_from_dir(out_dir) or "202607"
    Q = prev or prev_period(wide, P)
    t2 = compute.build_table2(wide, ni, nc, thr, period=P, prev=Q)
    ynd = pd.read_parquet(f"{ledger_dir}/wide/ynd_rank.parquet").set_index("period")
    top_total = (pd.read_parquet(f"{ledger_dir}/wide/top_total.parquet")
                 .set_index("period")["total"].to_dict())

    d, big, prov = load_doc_tables(docx_path)

    lines = [f"# 对照差异报告 · 回测期次 {P}（上期 {Q}）", "",
             f"- 人工原件：`{pathlib.Path(docx_path).name}`",
             f"- 机器稿目录：`{out_dir}`", ""]
    n_pass = n_fail = n_skip = 0

    # ---------- 1. 大表 ----------
    header = [_norm_header(c.text) for c in big.rows[0].cells]
    mapping, unknown = _map_headers(header)
    machine_fields = [f for f, *_ in _COL_RULES]
    missing_in_doc = [f for f in machine_fields if f not in mapping]

    lines += ["## 1. 大表（22 学科 × N 列）", ""]
    lines.append(f"- 原件表头：{' | '.join(h for h in header if h)}")
    lines.append(f"- 对齐上的语义列 {len(mapping)} 个："
                 + "、".join(FIELD_CN[f] for f in machine_fields if f in mapping))
    if missing_in_doc:
        lines.append("- ⚠️ **机器稿有、本原件无**（口径演进，不计入差异）："
                     + "、".join(FIELD_CN[f] for f in missing_in_doc))
    if unknown:
        lines.append("- ⚠️ **原件有、机器稿不产出**（台账外/人工列，不计入差异）："
                     + "、".join(f"第{i+1}列「{h}」" for i, h in unknown))
    lines.append("")

    doc_rows = {}
    for r in big.rows[1:]:
        cells = [c.text.strip() for c in r.cells]
        if cells[0] and cells[0] != "ESI学科":
            doc_rows[cells[0]] = cells
    fail_rows = []
    for _, row in t2.iterrows():
        cn_name = DISCIPLINES_CN[row["discipline"]]
        cells = doc_rows.get(cn_name)
        if cells is None:
            n_fail += 1
            fail_rows.append(cn_name)
            lines.append(f"- ❌ {cn_name}: 原件大表缺该行")
            continue
        bad = []
        for field, _pred, tol in _COL_RULES:
            if field not in mapping:
                continue
            mine = _mine_fmt(field, row)
            doc_s = cells[mapping[field]] if mapping[field] < len(cells) else ""
            ok, note = _cmp(field, mine, doc_s, tol)
            if ok is None:
                n_skip += 1
                continue
            if not ok:
                bad.append((field, note))
        if bad:
            n_fail += 1
            fail_rows.append(cn_name)
            for field, note in bad:
                lines.append(f"- ❌ {cn_name} · {FIELD_CN[field]}: {note}")
        else:
            n_pass += 1
    lines.append("")
    lines.append(f"**行级通过 {n_pass}/22**；不一致 {n_fail} 行"
                 f"（{', '.join(fail_rows) or '无'}）；不可判 {n_skip} 格。")
    lines.append("")

    # ---------- 2. 概述 ----------
    lines += ["## 2. 概述与学校发展段数字事实", ""]
    paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    ov = "\n".join(paras)
    facts = compute.build_overview(wide, ni, nc, thr, ynd, top_total, period=P, prev=Q)

    for label, getter, pat, kind in _OV_ANCHORS:
        g = _grab(pat, ov)
        mine = getter(facts)
        if g is None:
            lines.append(f"- ⚠️ {label}: 原件未出现该句式（计算={mine}）")
            continue
        if kind == "signed":
            # 增加/减少（顶尖论文）与 上升/下降（排名）两种措辞共用同一套进位规则
            doc_v = int(g[1]) * (1 if g[0] in ("增加", "上升") else -1)
        elif kind == "int":
            doc_v = int(g[0])
        else:
            doc_v = float(g[0])
        ok = abs(float(mine) - doc_v) < (0.006 if kind == "float" else 1e-9)
        lines.append(f"- {'✅' if ok else '❌'} {label}: 台账计算={mine} 原件={doc_v}")
    # 1‰ 最高学科的**学科名**也要核（第 3/4 期有「前1‰接近度较高的学科为X」句式）
    g_name = _grab(r"前1‰接近度较高的学科为(\S+?)，接近度", ov)
    if g_name:
        want = DISCIPLINES_CN[facts["best_1permille"]["discipline"]]
        lines.append(f"- {'✅' if g_name[0] == want else '❌'} 1‰接近度最高学科（名称）: "
                     f"台账={want} 原件={g_name[0]}")
    lines.append("")
    lines.append("> **已知口径风险（2026-09-18 回测发现，尚未修）**：`n_disc_1pct` 用「接近度≥1」"
                 "推「是否在前1%」，而**未进前1%的学科的接近度来自 InCites**（原件脚注写明），"
                 "两套口径在阈值附近打架。实测（`tmp/pct1_blast.py`，以 ESI 学科榜为真值）："
                 "**仅 202511 / 202601 两期多算 1 个（数学）**，因数学在 2025-05 退出前1%、"
                 "2026-03 才重新进入（见台账 `学科进入时间` 表），而台账里它的接近度 202601＝1.027。"
                 "202603 起数值正确。**历史复现期次的「前1%学科数」暂不可信，需馆员确认。**")
    lines += ["## 3. 云南省高校表（仅云大自身行可推导格）", ""]
    if prov is not None:
        prov_doc = {}
        for r in prov.rows[2:]:
            cells = [c.text.strip().replace("\n", "") for c in r.cells]
            if cells[0]:
                prov_doc[cells[0]] = cells
        yndu = prov_doc.get("云南大学", [])
        if yndu:
            ck = [
                ("排名·国内", str(facts["rank_cn_inst_now"]), yndu[1] if len(yndu) > 1 else ""),
                ("排名·国际", str(facts["rank_intl_now"]), yndu[2] if len(yndu) > 2 else ""),
                ("ESI前1%学科数", str(facts["n_disc_1pct"]), yndu[3] if len(yndu) > 3 else ""),
                ("顶尖论文", str(facts["top_papers_now"]), yndu[7] if len(yndu) > 7 else ""),
            ]
            for label, mine, docv in ck:
                dv = _num(docv)
                ok = dv is not None and abs(float(mine) - dv) < 1e-9
                lines.append(f"- {'✅' if ok else '❌'} 云大·{label}: 台账={mine} 原件={docv}")
        else:
            lines.append("- ⚠️ 省表未找到云南大学行")
    else:
        lines.append("- ⚠️ 未定位到省高校表")
    lines.append("")
    lines.append("省表其余列（发文量/被引/篇均/高被引/热点）= ESI 官网**各机构页全领域口径**，")
    lines.append("台账只存云大 22 学科口径（例：台账学科合计发文 ≠ 机构页全领域发文），v1.0 由馆员贴入。")
    lines.append("")

    # ---------- 4. 台账外 ----------
    lines += ["## 4. 台账外（馆员手工查数项，v1.0 不自动化）", ""]
    for e in ["本期 ESI 全球机构总数（官网当期数字）",
              "学院贡献度 / 学科 × 学院分布（清单口径，M4b 未实现）",
              "云南省高校 ESI 前1%学科总数与新增项（省域汇总，台账无）",
              "高被引论文 / 热点论文列（第 1–3 期大表有，台账未收录）"]:
        lines.append(f"- {e}")
    lines.append("")

    # ---------- 结论 ----------
    lines += ["## 结论", ""]
    lines.append(f"- 大表：**{n_pass}/22 行逐格一致**（只比两边都有的语义列；不一致行见上）。")
    lines.append("- 概述：台账可推数字已按语义锚点核对；标 ⚠️ 者＝原件句式不同、未抽到（需人工看一眼）。")
    lines.append("- 报告形态（图表去向 / T19 T20 / 占位 / 清单）**不在本报告范围**，"
                 "用 `tools/compare_reports.py`（模式 E）。")

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    report = pathlib.Path(out_dir) / f"对照差异报告_{P}回测.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return n_fail == 0


if __name__ == "__main__":
    docx_path = sys.argv[1] if len(sys.argv) > 1 else \
        r"..\云南大学原报告\云南大学学科信息参考2026年第4期.docx"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "out/202607"
    period = sys.argv[3] if len(sys.argv) > 3 else None
    prev = sys.argv[4] if len(sys.argv) > 4 else None
    ok = main(docx_path, out_dir=out_dir, period=period, prev=prev)
    sys.exit(0 if ok else 2)
