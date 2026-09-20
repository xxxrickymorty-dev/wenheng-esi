# -*- coding: utf-8 -*-
"""演示站 · 馆员工作台的数据装配（2026-09-19）。

设计前提（grill-me 定案，改这里前先读一遍）
------------------------------------------------------------------
1. **不判"对错"，只说"可溯源"**。系统里没有 ground truth（人工原件只有 1–4 期，
   且那 4 期自身还有笔误），所以顶部写的不是"已核对 N 格"，而是
   "N 个数字全部可溯源"—— 这句是真的，且当场能点开验证。
   注：多数来自台账，省域表 T19 的 110 格来自 ESI 原始包（extract_province.py）。
2. **待拍板只收"不处理报告就出不来或不该出"的那批**（约 20 条），不是全部 354 条。
   239 个大表格子 + 99 张图的正确状态是"已可溯源、要查随时能点开"，把它们塞进
   待办清单，等于把"已完成"和"待处理"混在一起——那正是"找不到重点"的根源。
3. 本模块**只读**。在线填的内容由别的模块写 `out/<期次>/manual_inputs.json`，
   **台账一个字节都不碰**（改了就破溯源）。
"""
from __future__ import annotations

import json
import pathlib
import re

#: 台账外的三张大表：**规格写死，状态不写死**。
#:
#: 🔴 别把它们当成固定的「待补三条」——2026-09-20 rick 拿人工原件问「这里明明有
#:    所有图表，为什么还有三个待补」，一查发现：T19/T20 在生成稿里确实只有表头
#:    （数据不在台账里），而 **T21 与原件逐格相同**（202607 就是第 4 期，母版恰好
#:    继承了它的清单）。写死常量会对着产物撒谎。
#:    → 状态一律**读生成稿实测**（`_pending_from_docx`），这里只留规格与说明。
#: 行×列 用来在 docx 里认出是哪张表（母版结构，逐期稳定）。
#: 行×列 用来在 docx 里认出是哪张表（母版结构，逐期稳定）；
#: `skip_head` 是**表头占几行** —— T19 是两级表头（第一行「排名」，第二行「国内/国际」），
#: 只跳 1 行会把第二级表头算成数据，于是空表被判成"已有内容 8.3%"（2026-09-20 实测）。
#: 这个数也得看实物定，不能照抄。
PENDING_SPECS = (
    {"id": "T19", "title": "云南省高校学科对比表", "rows": 13, "cols": 10, "skip_head": 2,
     "why": "各校 ESI 指标不在台账里，历期由馆员从 ESI 机构榜等外部来源补齐"},
    {"id": "T20", "title": "学科 × 高校矩阵表", "rows": 23, "cols": 12, "skip_head": 1,
     "why": "同上，数据源在台账外"},
    {"id": "T21", "title": "顶尖论文清单", "rows": 275, "cols": 7, "skip_head": 1,
     "why": "清单随期次更新；本期若与母版一致则无需处理"},
)

#: 数据区非空占比低于这个值，判为「只有表头、数据行是空的」
_EMPTY_RATIO = 0.02

#: 省域表的列名（除首列机构名）。**必须与 `src/fill_docx.py` 的 `PROVINCE_COLS`
#: 逐字一致** —— 这里只用于把 `T19/r5c3` 翻译成可读标签，真填表的是那边。
#: 有测试（test_province）钉住两边相等，防漂移。
PROVINCE_COLS = ("国内排名", "国际排名", "ESI前1%学科数", "发文量", "被引频次",
                 "篇均被引频次", "顶尖论文", "高被引论文", "热点论文")

#: 需要人工**确认**（不是填）的结构性项：这些填错整份报废
_CONFIRM_PREFIX = ("封面/",)
_CONFIRM_SOURCE = ("期次参数",)

_HAND = re.compile(r"【手工：([^】]*)】")

# ================================================================== 逐格溯源
# 大表 11 列 → 数据从哪来。c0 是学科名，c1..c10 对应 table2 的列序。
# 直接格：值就在台账某张宽表里（sheet·学科·期次 三元组定位）；
# 派生格：值是算出来的 → 给出算式，并把**输入值**一并展示（不然"可溯源"对它不成立）。
_WIDE = ("papers", "cnci", "total_cites", "threshold_1pct", "proximity_1pct", "top_papers")


#: 大表列名（程序用）→ 报告表头里的中文。label 要给馆员看，不能出现 `papers`。
_COL_CN = {
    "discipline": "学科", "rank_cn_change": "国内排名/变化", "papers": "论文数",
    "cnci": "CNCI值", "total_cites": "总被引频次", "thr_1pct": "1%阈值",
    "thr_1pct_gap": "1%阈值差", "thr_1permille": "1‰阈值", "permille_rank": "千分位",
    "top_papers": "顶尖论文", "prox_change": "接近度变化",
}


def _cell(df, disc, period):
    """从宽表取标量；行或列不存在返回 None（别抛，逐格溯源不能一格挂全页）。"""
    try:
        v = df.loc[disc, period]
    except (KeyError, IndexError):
        return None
    return None if v != v else v          # NaN → None


def _series(df, disc, period, col="rank"):
    try:
        r = df[(df["discipline"] == disc) & (df["period"] == period)]
        v = r.iloc[0][col]
    except (IndexError, KeyError):
        return None
    return None if v != v else v


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if v % 1 else str(int(v))
    return str(v)


def _bigtable_trace(rows, led, period, prev):
    """大表 239 格逐格溯源。返回 [{loc, col, report, sheet, disc, src_ref, ledger, how}]"""
    import parse_ledger                                   # noqa: PLC0415

    wide = led.get("wide") or {}
    rev = {v: k for k, v in parse_ledger.WIDE_METRIC.items()}   # metric → 台账中文名
    cn = parse_ledger.DISCIPLINES_CN
    out = []
    for r in rows:
        loc = r.get("location") or ""
        if not loc.startswith("T01/r"):
            continue
        m = re.match(r"T01/r(\d+)c(\d+)", loc)
        if not m:
            continue
        ci = int(m.group(2))
        report = (r.get("new") or "").strip()
        if ci == 0:                                       # 学科名列
            disc_en = next((k for k, v in cn.items() if v == report), None)
            out.append({"loc": loc, "col": "学科", "report": report,
                        "label": f"{report}（学科列）",
                        "sheet": "（22 学科规范名单）", "src_ref": disc_en or "?",
                        "ledger": disc_en or "?", "how": "映射"})
            continue
        # 行号 → 学科：table2 行序 = 报告大表行序，但 LEDGER 的行序按学科名查，不依赖行号
        # 先用本行 c0 的中文名反查英文名（同一 red_slots 列表里 r{n}c0 一定在前面）
        cn_name = next((x.get("new") or "" for x in rows
                        if x.get("location") == f"T01/r{m.group(1)}c0"), "")
        disc_en = next((k for k, v in cn.items() if v == cn_name), cn_name)

        def W(metric):
            return _cell(wide.get(metric), disc_en, period)

        if ci == 1:      # 国内排名/变化
            a, b = _series(led["new_cn"], disc_en, period), _series(led["new_cn"], disc_en, prev)
            out.append({"loc": loc, "col": "国内排名/变化", "report": report,
                        "sheet": "新国内排名", "src_ref": f"{disc_en} · {period}/{prev} · rank",
                        "ledger": f"{_fmt(a)}（上期 {_fmt(b)}）",
                        "how": f"由两期排名算变化：{_fmt(a)} vs {_fmt(b)}"})
        elif ci == 6:    # 1%阈值差 = 总被引 − 1%阈值（列序与 table2 对齐：c6 是 gap）
            a, b = W("total_cites"), W("threshold_1pct")
            d_ = (a - b) if a is not None and b is not None else None
            out.append({"loc": loc, "col": "1%阈值差", "report": report,
                        "sheet": f"{rev['total_cites']} − {rev['threshold_1pct']}",
                        "src_ref": f"{disc_en} · {period}",
                        "ledger": f"{_fmt(a)} − {_fmt(b)} = {_fmt(d_)}",
                        "how": "派生：总被引 − 1%阈值"})
        elif ci == 7:    # 1‰阈值
            v = _cell(led.get("threshold_1permille"), disc_en, period)
            out.append({"loc": loc, "col": "1‰阈值", "report": report,
                        "sheet": "千分之一被引阈值", "src_ref": f"{disc_en} · {period}",
                        "ledger": _fmt(v), "how": "直接取值"})
        elif ci == 8:    # 千分位
            p_ = _series(led["rank_intl"], disc_en, period, col="rank_pct")
            d_ = p_ * 10 if p_ is not None else None
            out.append({"loc": loc, "col": "千分位", "report": report,
                        "sheet": "国际排名", "src_ref": f"{disc_en} · {period} · rank_pct",
                        "ledger": f"{_fmt(p_)} × 10 = {_fmt(d_)}",
                        "how": "派生：国际排名百分位 × 10"})
        elif ci == 10:   # 接近度变化
            a, b = W("proximity_1pct"), _cell(wide.get("proximity_1pct"), disc_en, prev)
            d_ = (a - b) * 100 if a is not None and b is not None else None
            out.append({"loc": loc, "col": "接近度变化", "report": report,
                        "sheet": rev["proximity_1pct"], "src_ref": f"{disc_en} · {period}/{prev}",
                        "ledger": f"{_fmt(a)} − {_fmt(b)} ×100 = {_fmt(d_)}",
                        "how": "派生：(本期接近度 − 上期) × 100"})
        elif ci == 9:    # 顶尖论文
            v = W("top_papers")
            out.append({"loc": loc, "col": "顶尖论文", "report": report,
                        "sheet": rev["top_papers"], "src_ref": f"{disc_en} · {period}",
                        "ledger": _fmt(v), "how": "直接取值"})
        else:
            metric = {2: "papers", 3: "cnci", 4: "total_cites", 5: "threshold_1pct"}.get(ci)
            if metric is None:
                out.append({"loc": loc, "col": f"c{ci}", "report": report,
                            "sheet": "?", "src_ref": "—", "ledger": "—",
                            "how": "未登记的列（别静默放过，来补映射）"})
            else:
                v = W(metric)
                out.append({"loc": loc, "col": metric, "report": report,
                            "sheet": rev[metric], "src_ref": f"{disc_en} · {period}",
                            "ledger": _fmt(v), "how": "直接取值"})
    # 统一补 label：`T01/r22c10` 这种位置码是给程序看的，馆员对不上 ——
    # 换成「学科名 · 列名」，位置码退到 title 里备查（不丢信息）。
    for rec in out:
        if rec.get("label"):
            continue
        m = re.match(r"T01/r(\d+)c", rec.get("loc") or "")
        cn_name = ""
        if m:
            cn_name = next((x.get("new") or "" for x in rows
                            if x.get("location") == f"T01/r{m.group(1)}c0"), "")
        col_cn = _COL_CN.get(rec.get("col"), rec.get("col"))
        rec["label"] = f"{cn_name} · {col_cn}" if cn_name else (col_cn or "?")
    return out


def trace(out_dir, ledger_path, period=None, prev=None):
    """逐格溯源装配。**现场真读台账**（load_ledger），不拿宽表 parquet 自证——
    同源自证差异恒为 0，看起来严谨实际什么都没验（评审文档里的老教训）。"""
    import parse_ledger                                   # noqa: PLC0415
    rows = _slots(out_dir)
    period = period or pathlib.Path(out_dir).name
    try:
        led = parse_ledger.load_ledger(pathlib.Path(ledger_path))
        # 上期不由调用方猜 —— 用解析器自己的口径（脏期次归一、占位列剔除都在它里面）
        if not prev:
            _, prev = parse_ledger._latest_periods(led)
        big = _bigtable_trace(rows, led, period, prev)
    except Exception as e:                                # noqa: BLE001
        big = [{"loc": "—", "col": "台账读取失败", "report": "—",
                "sheet": str(pathlib.Path(ledger_path).name),
                "src_ref": "—", "ledger": f"{type(e).__name__}: {e}", "how": "—"}]

    charts = [{"loc": r.get("location"), "report": (r.get("new") or "").strip(),
               "src": r.get("source") or ""}
              for r in rows if (r.get("source") or "").startswith("charts")]
    # 省域表 T19：**数据源不是台账**（是 ESI 原始包），单独一类，
    # 否则这 110 格在溯源页上看不到 —— 与"全部可溯源"自相矛盾。
    province = [{"loc": r.get("location"), "report": (r.get("new") or "").strip(),
                 "src": r.get("source") or ""}
                for r in rows if (r.get("location") or "").startswith("T19/")]
    # 省域表同样把位置码换成可读标签：`T19/r5c3` → `云南农业大学 · ESI前1%学科数`
    for rec in province:
        m = re.match(r"T19/r(\d+)c(\d+)", rec["loc"] or "")
        if not m:
            continue
        ri, ci = int(m.group(1)), int(m.group(2))
        uname = next((x.get("new") or "" for x in rows
                      if x.get("location") == f"T19/r{ri}c0"), "")
        rec["label"] = uname if ci == 0 else (
            f"{uname} · {PROVINCE_COLS[ci - 1]}" if ci <= len(PROVINCE_COLS) else uname)
    texts = [{"loc": r.get("location"), "report": (r.get("new") or "").strip()[:60],
              "src": r.get("source") or ""}
             for r in rows if (r.get("source") or "").startswith(("sentences", "期次参数", "母版"))]
    # 筛选下拉的选项：按数据里真实出现的列/学科生成，不写死
    seen_c, cols = set(), []
    for rec in big:
        k = rec.get("col")
        if k and k not in seen_c and k != "学科":
            seen_c.add(k)
            cols.append({"key": k, "label": _COL_CN.get(k, k)})
    discs = sorted({(x.get("new") or "") for x in rows
                    if (x.get("location") or "").endswith("c0")
                    and (x.get("location") or "").startswith("T01/r")})
    return {"bigtable": big, "charts": charts, "province": province, "texts": texts,
            "cols": cols, "discs": discs,
            "n": len(rows), "ledger": str(ledger_path)}


def _slots(out_dir):
    p = pathlib.Path(out_dir) / "red_slots.json"
    if not p.exists():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def _todo_from_slot(row, idx):
    """把一个槽位里的【手工：…】标记拆成若干条待办（按**处**不是按槽位）。

    id 用 `位置::标记文字`（如 `正文/p2::去年同期升幅%`）而**不是序号**：
    序号在重跑流水线后会错位（red_slots 行序变了），人工填的值就挂到别人身上了。
    这个 id 同时是 `fill_docx` 回填时的查找键，两边必须一致。
    """
    # ⚠ 必须在**全文**上探测：red_slots 的 new 被截断到 50 字，只扫 new 会漏判
    text = row.get("new_full") or row.get("new") or ""
    where = row.get("location") or "?"
    out = []
    for i, m in enumerate(_HAND.finditer(text), 1):
        hint = (m.group(1) or "").strip()
        out.append({
            "id": f"{where}::{hint}",
            "kind": "fill",                 # 可以且应该在线填
            "title": hint or "待人工填写",
            "where": where,
            "source": row.get("source") or "",
        })
    return out


# ================================================================== 在线填 / 存疑
# 两个状态文件都落在 out/<期次>/（产物目录），**台账一个字节不碰**。
# 破坏了这条，"354 个数字可溯源"就变成一句空话 —— 修改必须发生在报告侧。

def _load_json(path):
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_fills(out_dir):
    return _load_json(pathlib.Path(out_dir) / "manual_inputs.json")


def save_fill(out_dir, todo_id, value, by="?", at=None):
    """保存一处人工填写。返回记录。**只写产物侧**，永不写台账。"""
    import datetime as dt
    p = pathlib.Path(out_dir) / "manual_inputs.json"
    data = _load_json(p)
    rec = {"value": value, "by": by,
           "at": at or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    data[todo_id] = rec
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "id": todo_id, **rec, "n_filled": len(data)}


def load_review(out_dir):
    return _load_json(pathlib.Path(out_dir) / "review.json")


def toggle_flag(out_dir, loc, by="?", at=None):
    """存疑/取消存疑（切换）。返回 {loc, state}。"""
    import datetime as dt
    p = pathlib.Path(out_dir) / "review.json"
    data = _load_json(p)
    cur = data.get(loc) or {}
    if cur.get("state") == "doubt":
        del data[loc]                       # 再点一次 = 撤销存疑
        state = "clear"
    else:
        data[loc] = {"state": "doubt", "by": by,
                     "at": at or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        state = "doubt"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "loc": loc, "state": state, "n_doubt": len(data)}


def _fill_state(key, pending_ids, slot_locs):
    """一条填写记录的三种状态。

    🔴 **别用「已填数 − 待办里还挂着的」去推「已写入报告」**：键对不上的历史残留
    （旧版格式、测试写入）也会落进那个差额里，于是页面上出现"已填 2 处、2 处已写入"
    而实际上一条都没进报告（2026-09-20 rick 实踩）。逐个判，判据要能自证。

    - `pending`：对应位置的 `【手工：x】` 还在 → 填了，但**还没重出报告**
    - `applied`：位置真实存在、标记已不在 → 值已经写进报告初稿
    - `orphan` ：位置在当前产物里根本找不到 → 旧版残留或测试垃圾，**要能看出来**
    """
    if key in pending_ids:
        return "pending"
    loc = key.split("::", 1)[0]
    return "applied" if loc in slot_locs else "orphan"


def _fill_rows(fills, todo, rows):
    order = {"pending": 0, "applied": 1, "orphan": 2}
    pending_ids = {t["id"] for t in todo}
    locs = {(r.get("location") or "") for r in rows}
    out = []
    for k, v in (fills or {}).items():
        v = v or {}
        out.append({"key": k, "value": v.get("value") or "",
                    "by": v.get("by") or "", "at": v.get("at") or "",
                    "state": _fill_state(k, pending_ids, locs)})
    out.sort(key=lambda x: (order[x["state"]], x["key"]))
    return out


def _table_fill(t, skip_head=1, skip_left=1):
    """表格「数据区」的非空占比。表头行与首列（标签列）不算数据。"""
    rows, cols = len(t.rows), len(t.columns)
    total = 0
    filled = 0
    for r in t.rows[skip_head:]:
        for c in r.cells[skip_left:]:
            total += 1
            if c.text.strip():
                filled += 1
    return (filled / total) if total else 0.0


def _pending_from_docx(out_dir):
    """**读生成稿实测**这三张大表是空的还是有内容 —— 别写死「待补三条」。

    返回 `[{id,title,why,state,filled}]`，只有 `state == "empty"` 的才是真待补。
    `state == "has_data"` 的也要返回（页面显示「母版已带内容，本期无需处理」），
    否则人工会以为它不存在 —— rick 的疑问正是这么来的。
    """
    out = pathlib.Path(out_dir)
    docx = next(iter(sorted(out.glob("报告初稿_*.docx"))), None)
    rows = []
    for spec in PENDING_SPECS:
        rec = dict(spec)
        rec.update({"state": "unknown", "filled": None})
        rows.append(rec)
    if docx is None:
        for r in rows:
            r["state"] = "no_docx"          # 还没出稿，无从判断
        return rows, False
    try:
        from docx import Document                              # noqa: PLC0415
        doc = Document(str(docx))
    except Exception:                                          # noqa: BLE001
        return rows, False
    by_shape = {(len(t.rows), len(t.columns)): t for t in doc.tables}
    for rec in rows:
        t = by_shape.get((rec["rows"], rec["cols"]))
        if t is None:
            rec["state"] = "not_found"
            continue
        ratio = _table_fill(t, skip_head=rec.get("skip_head", 1), skip_left=1)
        rec["filled"] = round(ratio, 4)
        rec["state"] = "empty" if ratio < _EMPTY_RATIO else "has_data"
        if rec["state"] == "has_data" and rec["id"] == "T21":
            # 清单是从母版继承的：本期与母版一致 ≠ 下期也对（下期要换新清单）
            rec["why"] = "清单继承自母版（本期与原件一致）；**换到下一期时需替换为新清单**"
    return rows, True


def build(out_dir, period=None, approval=None):
    """装配一屏所需的一切。返回 dict（纯读，不写任何文件）。"""
    rows = _slots(out_dir)
    period = period or pathlib.Path(out_dir).name

    traced = sum(1 for r in rows if (r.get("source") or "").strip())

    todo = []
    for i, r in enumerate(rows):
        todo += _todo_from_slot(r, i)

    # 结构性项：期次 / 封面年月 —— 不填错就行，但要人看一眼
    for i, r in enumerate(rows):
        loc = r.get("location") or ""
        src = r.get("source") or ""
        if loc.startswith(_CONFIRM_PREFIX) or any(k in src for k in _CONFIRM_SOURCE):
            value = (r.get("new") or "").strip()
            # 标题带上位置与现值，而不是笼统的"期次/封面"——
            # 三条确认项长得不一样（封面期数 / 封面年月 / 大表列名），
            # 写笼统了人不知道要看哪个。
            todo.append({
                "id": f"confirm-{i}",
                "kind": "confirm",
                "title": f"{loc}：{value}" if value else f"{loc}（空）",
                "where": loc or "封面",
                "value": value,
                "source": src,
            })

    pending_all, has_docx = _pending_from_docx(out_dir)
    pending = [r for r in pending_all if r["state"] == "empty"]
    pending_ok = [r for r in pending_all if r["state"] == "has_data"]

    fills = load_fills(out_dir)
    for t in todo:
        f = fills.get(t["id"])
        t["filled"] = (f or {}).get("value")
        t["filled_by"] = (f or {}).get("by")
        t["filled_at"] = (f or {}).get("at")
    fills_list = _fill_rows(fills, todo, rows)
    n_filled = sum(1 for f in fills_list if f["state"] != "orphan")
    n_applied = sum(1 for f in fills_list if f["state"] == "applied")
    n_orphan = sum(1 for f in fills_list if f["state"] == "orphan")

    return {
        "period": period,
        "period_dir": pathlib.Path(out_dir).name,
        "traceable": {"n": len(rows), "with_source": traced},
        "todo": todo,
        "todo_fill": [t for t in todo if t["kind"] == "fill"],
        "todo_confirm": [t for t in todo if t["kind"] == "confirm"],
        "pending": pending,
        "pending_ok": pending_ok,
        "pending_all": pending_all,
        "fills_list": fills_list,
        "n_filled": n_filled,
        "n_applied": n_applied,
        "n_orphan": n_orphan,
        "n_doubt": len(load_review(out_dir)),
        "approval": approval or {},
        # 二级入口（审计视图）：给工程/评委深挖用，不占首屏
        "audit_links": [
            {"label": "对勘本（正文级对照）", "href": f"/p/{period}"},
            {"label": "红色件清单", "href": f"/p/{period}/redslots"},
            {"label": "图表图册", "href": f"/p/{period}/charts"},
            {"label": "运行档案", "href": f"/p/{period}/archive"},
        ],
    }
