# -*- coding: utf-8 -*-
"""监测版 46 期趋势基建：逐期提取与 build_cache 同构的轻量快照，合并成单校跨期序列。

与 report.build_cache 的分工：缓存（_cache_<期次>.json）服务**当期渲染**（含 ±3 邻近窗、
cn_inst 等重件）；趋势件（_trend/<期次>.json）服务**跨期序列**，只留趋势需要的键，另加
`inst`（内置校在机构总表的行）供总排名序列。两者 schema 同构——渲染层可用同一形状读取
「当期缓存」与「历史期趋势件」。

入库纪律（brief 2026-10-31）：
- 每期先过 doctor.check(period, deep_d1=False) 门禁，不过 → 索引记 bad（含原因）跳过，
  绝不带病入库。D2/D3 以期次缓存为前提（doctor 文档化前提「缓存缺 = 先建」）：仅当失败项
  恰好全是「缓存不存在」时才补建缓存再重判；补建崩溃（老版式）如实记 bad，不放宽 doctor。
- 老期次全局件是老命名/老版式（全球机构.xlsx、THRESHOLD-ESI.xlsx、7 列榜单、无
  _下载信息.json），doctor 按现行包契约判 bad——这是 doctor 对老版式的判定，本模块不改判。
- 列按表头名识别（Cites 精确匹配，不吃 Cites to X / Cites/X Paper），9/7 列缺列值取 None，
  行位次（rank/cn_rank）不受版式影响；阈值表 INSTITUTION 列同样按表头名定位
  （202605/202607 式是 VLOOKUP 公式串，data_only=True 读 Excel 缓存计算值）。

cn_rank 口径（brief 定）：榜内 CHINA MAINLAND ∪ N/A 行计数推导——比 build_cache 的
纯 CHINA MAINLAND 计数多算属地未标注行（部属医院等），同榜同校两口径可差 1。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import openpyxl                                    # noqa: E402

from monitor import doctor as mdoc                 # noqa: E402
from monitor import report as mr                   # noqa: E402
from monitor import schools as sch                 # noqa: E402

TREND_ROOT = mr.MONITOR_ROOT / "_trend"
_EN_SET = {s["en"] for s in sch.SCHOOLS}


def _norm_head(cell) -> str:
    """表头单元格 → 规范名（大写、/ 归空格、压空白；与 mr._norm 同风格）。"""
    return " ".join(str(cell).upper().replace("/", " ").split()) if cell is not None else ""


def _load_table(path: pathlib.Path) -> tuple[tuple, list]:
    """→ (表头行, 数据行按排名升序)；表头行＝第 2 列文本为 Institutions 的行。"""
    wb = openpyxl.load_workbook(path)
    try:
        rows = [r for r in wb.active.iter_rows(values_only=True)
                if any(c is not None and str(c).strip() for c in r)]
    finally:
        wb.close()
    hdr = next((i for i, r in enumerate(rows) if str(r[1]).strip() == "Institutions"), None)
    if hdr is None:
        raise ValueError(f"{path.name}: 找不到 Institutions 表头行（版式不识别）")
    data = sorted((r for r in rows[hdr + 1:] if r[1]),
                  key=lambda r: int(float(str(r[0]).strip())))
    return rows[hdr], data


def _cols(header) -> dict:
    """表头名 → 列号；缺列（9/7 列老版式）→ None。Cites 必须精确匹配，
    避免吃掉 Cites to X / Cites/X Paper 系列列。"""
    heads = [_norm_head(c) for c in header]

    def exact(name: str) -> int | None:
        return heads.index(name) if name in heads else None

    country = next((i for i, h in enumerate(heads) if h.startswith("COUNTRIES")), None)
    return {"country": country, "papers": exact("WEB OF SCIENCE DOCUMENTS"),
            "cites": exact("CITES"), "cp": exact("CITES PAPER"),
            "hcp": exact("HIGHLY CITED PAPERS"), "hp": exact("HOT PAPERS")}


def _cell(row, idx: int | None):
    """按表头映射取数值；列缺失或空 → None（build_cache 行的缺列补位约定）。"""
    if idx is None or idx >= len(row) or row[idx] is None or not str(row[idx]).strip():
        return None
    return float(str(row[idx]).strip().replace(",", ""))


def _country(row, idx: int | None) -> str:
    v = row[idx] if idx is not None and idx < len(row) else None
    return str(v).strip() if v is not None else ""


def _thresholds(path: pathlib.Path) -> dict:
    """ThresholdESI.xlsx → {规范学科名: 机构阈值}。

    版式漂移：202609 式（THRESHOLD-ESI 杂行 + 表头 AUTHOR/INSTITUTION/JOURNAL，
    INSTITUTION 在第 4 列）与 202605/202607 式（表头仅 RESEARCH FIELDS/INSTITUTION，
    且 INSTITUTION 列是 VLOOKUP 公式串——须 data_only=True 读 Excel 缓存计算值）。
    统一按表头名定位 INSTITUTION 列（brief 规则：列按表头名识别，不按列序号硬编码）；
    表头行下出现空阈值＝真异常，报错不静默跳过。
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        rows = [r for r in wb.active.iter_rows(values_only=True)
                if any(c is not None and str(c).strip() for c in r)]
    finally:
        wb.close()
    hdr = next((i for i, r in enumerate(rows)
                if r and r[0] is not None and str(r[0]).strip() == "RESEARCH FIELDS"), None)
    if hdr is None:
        raise ValueError(f"{path.name}: 找不到 RESEARCH FIELDS 表头行（版式不识别）")
    heads = [_norm_head(c) for c in rows[hdr]]
    if "INSTITUTION" not in heads:
        raise ValueError(f"{path.name}: 阈值表头无 INSTITUTION 列")
    col = heads.index("INSTITUTION")
    expected = {mr._norm(s) for s in mr.STEMS}
    thr: dict[str, float] = {}
    for r in rows[hdr + 1:]:
        key = mr._norm(str(r[0]).strip()) if r and r[0] is not None else ""
        if key not in expected:
            continue                                   # 版权行等杂行——只认 22 学科行
        v = r[col] if col < len(r) else None
        if v is None or not str(v).strip():
            raise ValueError(f"{path.name}: 学科 {key} 的 INSTITUTION 阈值缺失")
        thr[key] = float(str(v).strip().replace(",", ""))
    missing = expected - set(thr)
    if missing:
        raise ValueError(f"{path.name}: 缺学科阈值 {sorted(missing)}")
    return thr


def extract_period(period: str) -> dict:
    """单期提取：schema 与 build_cache 的 cache 同构
    （少 cn_inst/neighbors/download，多 inst）。不写盘。"""
    base = mr.ESI_ROOT / period
    header, inst_rows = _load_table(base / "Institutions.xlsx")
    ic = _cols(header)
    inst: dict[str, list] = {}
    for r in inst_rows:
        name = str(r[1]).strip()
        if name in _EN_SET:
            inst[name] = [int(float(str(r[0]).strip())), _cell(r, ic["papers"]),
                          _cell(r, ic["cites"]), _cell(r, ic["cp"])]

    fields: dict[str, dict] = {}
    for stem in mr.STEMS:
        fhdr, data = _load_table(base / f"{stem}.xlsx")
        fc = _cols(fhdr)
        m = len(data)
        line = (m + 1) // 10
        line_cites = _cell(data[line - 1], fc["cites"]) if 0 < line <= m else None
        ci = fc["country"] if fc["country"] is not None else 2
        rows: dict[str, list] = {}
        for i, r in enumerate(data):
            name = str(r[1]).strip()
            if name not in _EN_SET:
                continue
            # cn_rank（brief 口径）：榜内 CHINA MAINLAND ∪ N/A 行中排在本次之前的数量 + 1
            cn_rank = 1 + sum(1 for x in data[:i]
                              if _country(x, ci) in ("CHINA MAINLAND", "N/A"))
            rows[name] = [int(float(str(r[0]).strip())), cn_rank, _cell(r, fc["papers"]),
                          _cell(r, fc["cites"]), _cell(r, fc["cp"]),
                          _cell(r, fc["hcp"]), _cell(r, fc["hp"])]
        fields[stem] = {"m": m, "line": line, "line_cites": line_cites, "schools": rows}

    return {"period": period, "built": datetime.date.today().isoformat(),
            "n_inst": len(inst_rows), "fields": fields,
            "thr1": _thresholds(base / "ThresholdESI.xlsx"), "inst": inst}


def trend_path(period: str) -> pathlib.Path:
    return TREND_ROOT / f"{period}.json"


def write_period(period: str, data: dict) -> pathlib.Path:
    TREND_ROOT.mkdir(parents=True, exist_ok=True)
    p = trend_path(period)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _gate(period: str) -> tuple[bool, str]:
    """doctor 门禁：不过 → (False, 原因)。D2/D3 以期次缓存为前提——仅当失败项恰好
    全是「缓存不存在」时按 doctor 文档化前提（缓存缺 = 先建）补建缓存再重判；
    补建崩溃（老版式 build_cache 不支持）如实记 bad。不放宽 doctor。"""
    try:
        rep = mdoc.check(period, deep_d1=False)
    except Exception as exc:                                   # noqa: BLE001
        return False, f"doctor 崩溃 {type(exc).__name__}: {exc}"
    failing = [i for i in rep["items"] if not i["ok"]]
    if failing and all(i["id"] in ("D2", "D3") and "缓存不存在" in i["detail"] for i in failing):
        try:
            mr.build_cache(period)
        except Exception as exc:                               # noqa: BLE001
            return False, (f"D2/D3 前提（期次缓存）无法满足：build_cache 崩溃 "
                           f"{type(exc).__name__}: {exc}")
        rep = mdoc.check(period, deep_d1=False)
        failing = [i for i in rep["items"] if not i["ok"]]
    if failing:
        return False, "; ".join(f"{i['id']}: {i['detail']}" for i in failing)
    return True, ""


def build_all(force: bool = False, only: str | None = None) -> dict:
    """逐期 doctor 门禁 + 提取落盘，写 _trend/_index.json（断点续跑：已有件默认跳过）。"""
    latest = mr.latest_period()
    if not latest:
        raise FileNotFoundError("数据与复现/ESI数据/ 下没有可用的 ESI 期次目录")
    periods = sorted(d.name for d in mr.ESI_ROOT.iterdir()
                     if d.is_dir() and re.fullmatch(r"20\d{4}", d.name) and d.name <= latest)
    if only is not None:
        if only not in periods:
            raise FileNotFoundError(f"期次目录不存在或不在最新期内：{mr.ESI_ROOT / only}")
        periods = [only]

    index_path = TREND_ROOT / "_index.json"
    prev: dict = {}
    if index_path.exists():
        try:
            prev = json.loads(index_path.read_text(encoding="utf-8")).get("periods", {})
        except (json.JSONDecodeError, OSError):
            prev = {}

    results: dict[str, dict] = {}
    for p in periods:
        n_files = sum(1 for x in (mr.ESI_ROOT / p).iterdir() if x.is_file())
        if trend_path(p).exists() and not force and prev.get(p, {}).get("status") == "ok":
            results[p] = {"status": "ok", "n_files": n_files}  # 既有件必来自上次门禁通过
            print(f"[ok] {p} 已有趋势件，续跑跳过（--force 重建）")
            continue
        ok, reason = _gate(p)
        if not ok:
            results[p] = {"status": "bad", "reason": reason, "n_files": n_files}
            print(f"[bad] {p} {reason[:72]}")
            continue
        try:
            data = extract_period(p)
        except Exception as exc:                               # noqa: BLE001
            results[p] = {"status": "bad",
                          "reason": f"extract 崩溃 {type(exc).__name__}: {exc}",
                          "n_files": n_files}
            print(f"[bad] {p} extract 崩溃 {type(exc).__name__}")
            continue
        write_period(p, data)
        results[p] = {"status": "ok", "n_files": n_files}
        print(f"[ok] {p} n_inst={data['n_inst']}")

    built = {"built_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "periods": {**{k: v for k, v in prev.items() if k not in results}, **results}}
    TREND_ROOT.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(built, ensure_ascii=False, indent=1), encoding="utf-8")
    return built


def combine(en: str, root: str | pathlib.Path | None = None) -> dict:
    """汇总单校跨期序列：只吃 _index 里 status=ok 的期次文件，按期升序。"""
    root = pathlib.Path(root) if root is not None else TREND_ROOT
    statuses: dict = {}
    ip = root / "_index.json"
    if ip.exists():
        try:
            statuses = json.loads(ip.read_text(encoding="utf-8")).get("periods", {})
        except (json.JSONDecodeError, OSError):
            statuses = {}
    points: list[dict] = []
    fields: dict[str, list[dict]] = {}
    for name in sorted(x.name for x in root.glob("*.json")
                       if re.fullmatch(r"20\d{4}\.json", x.name)):
        if statuses.get(name[:-5], {}).get("status", "ok") != "ok":
            continue                                           # doctor 判 bad 的期次绝不进趋势
        try:
            t = json.loads((root / name).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        row = (t.get("inst") or {}).get(en)
        if row:
            points.append({"period": name[:-5], "total_rank": row[0],
                           "total_cites": row[2], "n_inst": t.get("n_inst")})
        for stem, fd in (t.get("fields") or {}).items():
            srow = (fd.get("schools") or {}).get(en)
            if not srow:
                continue
            fields.setdefault(stem, []).append(
                {"period": name[:-5], "rank": srow[0], "m": fd.get("m"),
                 "cites": srow[3], "line_cites": fd.get("line_cites"),
                 "thr1": (t.get("thr1") or {}).get(mr._norm(stem))})
    return {"en": en, "points": points, "fields": fields}


def _print_status() -> int:
    ip = TREND_ROOT / "_index.json"
    if not ip.exists():
        print("[trend] 索引不存在——先跑: uv run python -m src.monitor.trend")
        return 2
    try:
        idx = json.loads(ip.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[trend] 索引不可读: {exc}")
        return 2
    periods = idx.get("periods", {})
    ok = [p for p, v in sorted(periods.items()) if v.get("status") == "ok"]
    bad = {p: v.get("reason", "") for p, v in sorted(periods.items()) if v.get("status") != "ok"}
    print(f"[trend] built_at={idx.get('built_at')} ok={len(ok)} bad={len(bad)}")
    print("ok :", " ".join(ok) if ok else "-")
    for p, reason in bad.items():
        print(f"bad: {p} {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="监测版 46 期趋势基建（doctor 门禁，逐期提取/合并）")
    ap.add_argument("--period", default=None, help="只处理该期次（默认全量）")
    ap.add_argument("--force", action="store_true", help="已存在的趋势件也重建")
    ap.add_argument("--status", action="store_true", help="只打印索引摘要")
    args = ap.parse_args(argv)
    if args.status:
        return _print_status()
    if args.period and not (mr.ESI_ROOT / args.period).is_dir():
        print(f"[拒绝] 期次目录不存在：{mr.ESI_ROOT / args.period}")
        return 2
    idx = build_all(force=args.force, only=args.period)
    if args.period:
        v = idx["periods"].get(args.period, {})
        print(f"[trend] {args.period} · {v.get('status')} · 索引 {TREND_ROOT / '_index.json'}")
        return 0 if v.get("status") == "ok" else 1
    periods = idx["periods"]
    n_ok = sum(1 for v in periods.values() if v.get("status") == "ok")
    print(f"[trend] 全量 {len(periods)} 期 · ok {n_ok} · bad {len(periods) - n_ok}"
          f" · 索引 {TREND_ROOT / '_index.json'}")
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
