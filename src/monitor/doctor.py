# -*- coding: utf-8 -*-
"""监测版 doctor——包契约 D1/D2/D3/D6 的机器核验（D4 对拍见 tools/monitor_derive_backtest.py，
D5 台账自建检查待多期台账出现后补）。

独立可跑（自举 src/ 进 sys.path，不依赖 server.config 的副作用）：
    uv run python src/monitor/doctor.py [--period 202609] [--json]

判据出自《评审文档/38-监测版包契约-ESIonly（20261031）.md》§5：
- D1 全局件核验：31 张源文件在位、tag/表头/行数下限；
- D2 校本绑定：缓存里的机构行全部来自内置名单的 ESI 写法（名字绑定有断言）；
- D3 本校行存在性三级判定：榜内=入围；总表在而榜不在=未入围（正常）；两边无=写法错（fail）；
- D6 元数据：_下载信息.json 在位且下载日可解析。
产出 `monitor_data/_doctor_<期次>.json`；有 fail 时退出码 1。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import openpyxl                                    # noqa: E402

from monitor import report as mr                   # noqa: E402
from monitor import schools as sch                 # noqa: E402

#: 已核实的「ESI 未入册」校（低于收录线，名单保留、报告如实呈现）——D3 里不算写法错。
EXPECTED_UNREGISTERED = {"中国政法大学"}


def _load_names_and_header(path: pathlib.Path, name_col: str) -> tuple[list[str], int, int]:
    """→ (机构名列表, 数据行数, 表头行号)；供 D1 行数与表头检查复用。"""
    wb = openpyxl.load_workbook(path)
    rows = [r for r in wb.active.iter_rows(values_only=True)
            if any(c is not None and str(c).strip() for c in r)]
    wb.close()
    hdr = next((i for i, r in enumerate(rows) if str(r[1]).strip() == name_col), None)
    if hdr is None:
        return [], 0, -1
    data = [str(r[1]).strip() for r in rows[hdr + 1:] if r[1]]
    return data, len(data), hdr


def check(period: str, *, deep_d1: bool = True) -> dict:
    """跑 D1/D2/D3/D6，返回报告 dict（含 items 与 fail 数）。"""
    base = mr.ESI_ROOT / period
    items: list[dict] = []

    def add(check_id: str, ok: bool, detail: str) -> None:
        items.append({"id": check_id, "ok": ok, "detail": detail})

    # ---- D1 全局件核验（源文件在位 + tag/行数） ----
    inst_names, inst_n, _ = (["-"], 0, -1)
    if not base.is_dir():
        add("D1", False, f"期次目录不存在：{base}")
    else:
        miss = [f for f in ("Institutions.xlsx", "ThresholdESI.xlsx", "ThresholdHighlyCited.xlsx",
                            "ThresholdHot.xlsx", "全球学科.xlsx", "中国学科.xlsx",
                            "BaselineCitationRates.xlsx", "BaselinePercentiles.xlsx",
                            "BaselineFieldRankings.xlsx") if not (base / f).exists()]
        stem_miss = [s for s in mr.STEMS if not (base / f"{s}.xlsx").exists()]
        if miss or stem_miss:
            add("D1", False, f"缺文件：{miss + [s + '.xlsx' for s in stem_miss]}")
        elif deep_d1:
            inst_names, inst_n, _ = _load_names_and_header(base / "Institutions.xlsx", "Institutions")
            if inst_n < 10_000:
                add("D1", False, f"机构总表仅 {inst_n} 行（期望 ≥ 10,000）——导出可能被截断")
            else:
                small = []
                for s in mr.STEMS:
                    _, m, _ = _load_names_and_header(base / f"{s}.xlsx", "Institutions")
                    if m < 100:
                        small.append(f"{s}({m})")
                if small:
                    add("D1", False, "分学科榜行数异常： " + "、".join(small))
                else:
                    add("D1", True, f"31 张全局件在位；机构总表 {inst_n:,} 行；22 榜行数正常")
        else:
            add("D1", True, "31 张全局件在位（浅检：未逐榜开文件）")

    # ---- D2 校本绑定 + D3 三级判定（基于缓存；缓存缺 = 先建） ----
    cache = mr.load_cache(period)
    if cache is None:
        add("D2", False, "期次缓存不存在——先跑 build_cache（服务端首次生成会自动建）")
        add("D3", False, "期次缓存不存在，无法做三级判定")
    else:
        en_set = {s["en"] for s in sch.SCHOOLS}
        bound = {en for v in cache["fields"].values() for en in v["schools"]}
        stray = sorted(bound - en_set)
        add("D2", not stray,
            "缓存机构行全部来自内置名单" if not stray else f"缓存出现名单外机构名：{stray}")

        total_names = {row[0] for row in cache["cn_inst"]}
        entered, near, unreg = [], [], []
        for s in sch.SCHOOLS:
            en = s["en"]
            in_total = en in total_names
            in_field = any(en in v["schools"] for v in cache["fields"].values())
            if in_field:
                entered.append(s["cn"])
            elif in_total:
                near.append(s["cn"])
            else:
                unreg.append(s["cn"])
        wrong = [c for c in unreg if c not in EXPECTED_UNREGISTERED]
        add("D3", not wrong,
            f"入围 {len(entered)} · 未入围 {len(near)} · 未入册 {len(unreg)}"
            + ("" if not wrong else f" · 写法错待核：{wrong}（名单与总表都搜不到）"))

    # ---- D6 元数据 ----
    meta = base / "_下载信息.json"
    if not meta.exists():
        add("D6", False, "_下载信息.json 缺失——报告「ESI 发布日期」槽位无来源")
    else:
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            ok = bool(m.get("首次下载")) and bool(m.get("最近下载"))
            add("D6", ok, f"下载日 {m.get('首次下载')}/{m.get('最近下载')}" if ok
                else "_下载信息.json 缺首次/最近下载字段")
        except (json.JSONDecodeError, OSError) as exc:
            add("D6", False, f"_下载信息.json 不可解析：{exc}")

    return {"period": period, "built": cache["built"] if cache else None,
            "items": items, "fails": sum(1 for i in items if not i["ok"])}


def main() -> int:
    ap = argparse.ArgumentParser(description="监测版包契约核验（D1/D2/D3/D6）")
    ap.add_argument("--period", default=None, help="期次（默认取最新可用）")
    ap.add_argument("--json", action="store_true", help="只打印 JSON")
    args = ap.parse_args()
    period = args.period or mr.latest_period()
    if not period:
        print("[拒绝] 数据与复现/ESI数据/ 下没有可用的期次目录")
        return 2
    rep = check(period)
    out = mr.MONITOR_ROOT / f"_doctor_{period}.json"
    mr.MONITOR_ROOT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for i in rep["items"]:
            mark = "✓" if i["ok"] else "✗"
            print(f"[{i['id']}] {mark} {i['detail']}")
        print(f"[doctor] {period} · fail {rep['fails']} · 报告 {out.name}")
    return 1 if rep["fails"] else 0


if __name__ == "__main__":
    sys.exit(main())
