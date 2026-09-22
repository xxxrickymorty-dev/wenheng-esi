# -*- coding: utf-8 -*-
"""InCites 取数自动化（照《incites下载流程.txt》的 5 类，约 89 份）。

原理：Playwright 经 CDP 附着已登录 Chrome → 取 `x-1p-inc-sid`（/config 响应头）
→ 用会话 cookie 直接 POST 应用自己的导出端点
（`/route/export/explore/{datasetId}/{entity}/data/table/page/export/xlsx`）
→ 拿回 xlsx 字节落盘（绕开 UI 点击与 Chrome 下载通道；大文件服务端要算 1~2 分钟）。

前置：双击工作区根目录 `start-clarivate-chrome.bat`（CDP 9222，已登录 InCites）。

用法（在 `wenheng/` 下跑；**playwright 在系统 Python 里**，用系统 `python` 而不是 .venv）：
    python tools\\clarivate_incites_fetch.py institutions --out ..\\数据与复现\\incites\\<快照目录>
    python tools\\clarivate_incites_fetch.py fields       --out ..\\数据与复现\\incites\\<快照目录>
    python tools\\clarivate_incites_fetch.py subjects     --out ..\\数据与复现\\incites\\<快照目录>
    （默认跳过已存在文件；`--force` 覆盖。）

5 类对应命令：
    subjects     22 个「分学科全球机构排名表」（Organizations + Research Area=各学科）
    fields       全球 / 中国 / 云南大学 三张「22 学科汇总」（Research Areas 视图）
    institutions 全球机构排名表（Organizations，不分学科，按被引频次默认排序）

口径（与馆员流程一致，逐条实测抄自应用自己拼的请求）：
    时间 2016-2026 ｜ schema=Essential Science Indicators ｜ 文献类型 Article,Review
    ｜ Include ESCI documents 不勾（`queryDataCollection=undefined`）｜ Add indicator 全勾
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

CDP = "http://127.0.0.1:9222"
INCITES = "https://incites.clarivate.com"
DEFAULT_OUT_ROOT = Path(__file__).resolve().parents[2] / "数据与复现" / "incites"

#: 全球机构榜分块大小（整表一次拉会被网关 524；8000 行/块实测 ≤105 s）
_INSTITUTIONS_CHUNK = 8000

#: 两种实体的导出列（全指标；顺序照应用自己拼的请求，`key`/`seqNumber` 是隐藏列，导出时被丢弃）
_ORG_INDICATORS = [
    "key", "seqNumber", "hasProfile", "esibimonthlyhotpapers", "esibimonthlyhighlycitedpapers",
    "orgName", "wosDocuments", "timesCited", "cnorm", "percentCited", "rank", "norm",
    "allopenaccessdocs", "percfirstauthor", "prcntGlobalBaseDocs", "location", "esi",
    "doajgolddocuments", "perclastauthor", "prcntGlobalBaseCites", "nonselftimescited",
    "domAllDocuments", "prcntDocsIn99", "othergolddocuments", "perccorrespauthor",
    "prcntBaselineAllDocs", "intAllDocuments", "type", "prcntDocsIn90", "bronzedocuments",
    "firstauthor", "prcntBaselineAllCites", "percDomAllDocuments", "prcntHighlyCitedPapers",
    "lastauthor", "prcntBaselineForPinnedDocs", "greensubmitteddocs", "percInternationalDocs",
    "avrgCitations", "highlyCitedPapers", "stateProvice", "greenaccepteddocuments",
    "correspauthor", "prcntBaselineForPinnedCites", "collabCNCIDomAll", "avrgPrcnt",
    "prcntHotPapers", "greenpublisheddocuments", "collabCNCIIntAll", "jNCI", "jifdocs",
    "greenOnly", "domSingleDocuments", "impactRelToWorld", "jifdocsq1", "nonOaDocs",
    "domMultipleDocuments", "hindex", "jifdocsq2", "percallopenaccess", "intBilateralDocuments",
    "jifdocsq3", "percdoajgolddocuments", "nonselfhindex", "intTrilateralDocuments", "docsCited",
    "jifdocsq4", "percothergolddocuments", "intQuadrilateralDocuments", "percjifdocsq1",
    "yearCiting", "percbronzedocuments", "percDomSingleDocuments", "percjifdocsq2",
    "percgreensubmitteddocs", "citationsFromPatents", "percDomMutipleDocuments", "percjifdocsq3",
    "percgreenaccepteddocuments", "percInternationalBilatDocs", "percjifdocsq4",
    "percgreenpublisheddocuments", "percInternationalTrilatDocs", "docsIn99", "prcntGreenOnly",
    "percInternationalQuadlatDocs", "docsIn90", "prcntNonOaDocs", "collabCNCIDomSingle",
    "hotPapers", "collabCNCIDomMultiple", "collabCNCIIntBilateral", "collabCNCIIntTrilateral",
    "collabCNCIIntQuadrilateral", "indCollaborations", "prcntIndCollab", "organizationOnly",
    "prcntOrganizationOnly", "countryCollab", "intCollaborations", "prcntCountryCollab",
    "prcntIntCollab",
]
_SUBJ_INDICATORS = [
    "key", "seqNumber", "esibimonthlyhotpapers", "esibimonthlyhighlycitedpapers", "sbjName",
    "wosDocuments", "timesCited", "cnorm", "rank", "percentCited", "norm", "allopenaccessdocs",
    "prcntGlobalBaseDocs", "prcntDocsIn99", "doajgolddocuments", "prcntGlobalBaseCites",
    "domAllDocuments", "avrgCitations", "prcntDocsIn90", "othergolddocuments",
    "prcntBaselineAllDocs", "intAllDocuments", "avrgPrcnt", "prcntHighlyCitedPapers",
    "bronzedocuments", "prcntBaselineAllCites", "percDomAllDocuments", "jNCI",
    "highlyCitedPapers", "prcntBaselineForPinnedDocs", "greensubmitteddocs",
    "percInternationalDocs", "prcntHotPapers", "impactRelToWorld", "greenaccepteddocuments",
    "prcntBaselineForPinnedCites", "collabCNCIDomAll", "jifdocs", "greenpublisheddocuments",
    "collabCNCIIntAll", "jifdocsq1", "greenOnly", "domSingleDocuments", "jifdocsq2", "nonOaDocs",
    "domMultipleDocuments", "jifdocsq3", "percallopenaccess", "citationsFromPatents",
    "intBilateralDocuments", "jifdocsq4", "percdoajgolddocuments", "intTrilateralDocuments",
    "percjifdocsq1", "percothergolddocuments", "intQuadrilateralDocuments", "percjifdocsq2",
    "percbronzedocuments", "percDomSingleDocuments", "percjifdocsq3", "percgreensubmitteddocs",
    "percDomMutipleDocuments", "percjifdocsq4", "percgreenaccepteddocuments",
    "percInternationalBilatDocs", "percgreenpublisheddocuments", "docsIn99",
    "percInternationalTrilatDocs", "docsIn90", "prcntGreenOnly", "percInternationalQuadlatDocs",
    "hotPapers", "prcntNonOaDocs", "collabCNCIDomSingle", "collabCNCIDomMultiple",
    "collabCNCIIntBilateral", "collabCNCIIntTrilateral", "collabCNCIIntQuadrilateral",
    "indCollaborations", "prcntIndCollab", "countryCollab", "intCollaborations",
    "prcntCountryCollab", "prcntIntCollab",
]

#: 22 个 ESI 学科（InCites Research Area 视图里的原名；导出的机构表文件名把 `/` 换空格，随历史归档）
SUBJECTS = [
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
    "Computer Science", "Economics & Business", "Engineering", "Environment/Ecology",
    "Geosciences", "Immunology", "Materials Science", "Mathematics", "Microbiology",
    "Molecular Biology & Genetics", "Multidisciplinary", "Neuroscience & Behavior",
    "Pharmacology & Toxicology", "Physics", "Plant & Animal Science",
    "Psychiatry/Psychology", "Social Sciences, general", "Space Science",
]

_TAKE = 100_000                 # 服务端按「取到多少算多少」返回，超量无害（实测 15348 行榜返回全量）


def _window(dates: dict) -> list[int]:
    """10 年滚动窗口 [起, 止]（随 WoS 截止年推进：2026 年 = 2016-2026，与历史归档同规律）。"""
    end = int(str(dates["wosextractdate"])[:4])
    return [end - 10, end]


def _base_filters(period: list[int]) -> dict:
    return {
        "period": {"is": list(period)},
        "schema": {"is": "Essential Science Indicators"},
        "personIdTypeGroup": {"is": "authorRecord"},
        "geographicCollabType": {"is": "All"},
        "articletype": {"is": ["Article", "Review"]},
        "earlyAccess": {"is": [1]},
        "publisherType": {"is": "All"},
        "fundingAgencyType": {"is": "All"},
        "fundingDataSource": {"is": "All Sources"},
        "personIdType": {"is": "authorRecord"},
    }


def _subj_filters(period: list[int]) -> dict:
    f = _base_filters(period)
    f["assprsnIdTypeGroup"] = {"is": "authorRecord"}
    f["assprsnIdType"] = {"is": "authorRecord"}
    return f


def _get_incites_page(browser) -> Page:
    ctx = browser.contexts[0]
    for pg in ctx.pages:
        if "incites.clarivate.com" in pg.url:
            pg.bring_to_front()
            return pg
    pg = ctx.new_page()
    pg.goto(f"{INCITES}/#/analysis/0/organization", wait_until="domcontentloaded")
    return pg


def _session(page: Page) -> tuple[str, dict]:
    """取会话导出所需的 `x-1p-inc-sid`（/config 响应头）与数据集日期。"""
    cfg = page.request.get(f"{INCITES}/config", timeout=30_000)
    sid = cfg.headers.get("pssid")
    if not sid:
        raise SystemExit("[FAIL] /config 没返回 pssid —— 确认 Chrome 里 InCites 已登录")
    dep = page.request.get(
        f"{INCITES}/route/incites-app/about/data/display/wosanddeploydate",
        headers={"x-1p-inc-sid": sid}, timeout=30_000)
    if not dep.ok:
        raise SystemExit(f"[FAIL] wosanddeploydate HTTP {dep.status}")
    dates = dep.json()                       # {"deploydate": "2026-09-02", "wosextractdate": "2026-07-31"}
    return sid, dates


def _utc16(date_str: str) -> str:
    """`2026-07-31` → `2026-07-30T16:00:00.000Z`（应用按 UTC+8 零点算）。"""
    d = dt.datetime.strptime(date_str, "%Y-%m-%d") - dt.timedelta(hours=8)
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _export(page: Page, sid: str, dates: dict, *, entity: str, filters: dict,
            indicators: list[str], fname: str, take: int = _TAKE, skip: int = 0) -> bytes:
    """POST 应用自己的导出端点，返回 xlsx 字节（失败抛 RuntimeError）。"""
    body = {
        "dateInfo": {
            "deploydate": _utc16(dates["deploydate"]),
            "wosextractdate": _utc16(dates["wosextractdate"]),
            "exportDate": dt.date.today().isoformat(),
        },
        "filters": filters,
        "pinned": [],
        "skip": skip,
        "sortOrder": "desc",
        "take": take,
        "groupPinned": [],
        "sortBy": "timesCited",
        "indicators": indicators,
        "benchmarkNames": ["global", "all"],
    }
    url = (
        f"{INCITES}/route/export/explore/0/{entity}/data/table/page/export/xlsx"
        f"?sortBy=timesCited&sortOrder=desc&skip={skip}&take={take}&dataColumn=wosDocuments"
        f"&fileName={quote(fname)}&queryDataCollection=undefined"
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN",          # 中文表头，与历史归档同形
        "x-1p-inc-sid": sid,
    }
    resp = page.request.post(url, headers=headers, data=json.dumps(body, ensure_ascii=False),
                             timeout=600_000)
    data = resp.body()
    if resp.status not in (200, 201) or data[:2] != b"PK":
        raise RuntimeError(f"HTTP {resp.status}, {len(data)} B（非 xlsx）")
    return data


def _save(target: Path, data: bytes) -> tuple[int, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    import openpyxl
    wb = openpyxl.load_workbook(target, read_only=True)
    ws = wb[wb.sheetnames[0]]
    dims = (ws.max_row, ws.max_column)
    wb.close()
    return dims


def _run_item(page, sid, dates, *, entity, filters, indicators, fname, target: Path,
              force: bool, counters: dict) -> None:
    if target.exists() and not force:
        print(f"[skip] {target.name} 已存在")
        counters["skip"] += 1
        return
    t0 = dt.datetime.now()
    try:
        data = _export(page, sid, dates, entity=entity, filters=filters,
                       indicators=indicators, fname=fname)
    except Exception as e:                                   # noqa: BLE001
        print(f"[FAIL] {target.name}: {e}")
        counters["fail"] += 1
        return
    secs = (dt.datetime.now() - t0).total_seconds()
    try:
        rows, cols = _save(target, data)
    except Exception as e:                                   # noqa: BLE001
        print(f"[FAIL] {target.name}: 落盘/读取失败 {e}")
        counters["fail"] += 1
        return
    print(f"[OK] {target.name}  ({target.stat().st_size} B, {rows} 行 × {cols} 列, {secs:.0f}s)")
    counters["ok"] += 1


def cmd_subjects(page: Page, sid: str, dates: dict, period: list[int],
                 out: Path, force: bool) -> dict:
    """22 个「分学科全球机构排名表」（Organizations + Research Area=各学科）。"""
    counters = {"ok": 0, "skip": 0, "fail": 0}
    for s in SUBJECTS:
        f = _base_filters(period)
        f["sbjname"] = {"is": [s]}
        fname = s.replace("/", " ")
        target = out / f"{fname}.xlsx"
        _run_item(page, sid, dates, entity="organization", filters=f,
                  indicators=_ORG_INDICATORS, fname=fname, target=target,
                  force=force, counters=counters)
    return counters


_FIELD_ITEMS = [
    # （本地名=fileName=sheet 名, 附加筛选）
    ("全球 研究领域", {}),
    ("中国研究领域", {"location": {"is": ["CHINA MAINLAND"]}}),
    ("云南大学研究领域", {"orgname": {"is": ["Yunnan University"]}}),
]


def cmd_fields(page: Page, sid: str, dates: dict, period: list[int],
               out: Path, force: bool) -> dict:
    """全球 / 中国 / 云南大学 三张「22 学科汇总」（Research Areas 视图）。"""
    counters = {"ok": 0, "skip": 0, "fail": 0}
    for fname, extra in _FIELD_ITEMS:
        f = _subj_filters(period)
        f.update(extra)
        _run_item(page, sid, dates, entity="subject", filters=f,
                  indicators=_SUBJ_INDICATORS, fname=fname, target=out / f"{fname}.xlsx",
                  force=force, counters=counters)
    return counters


def cmd_institutions(page: Page, sid: str, dates: dict, period: list[int],
                     out: Path, force: bool) -> dict:
    """全球机构排名表（Organizations，不分学科，按被引频次默认排序）。

    ⚠ 整表一次导出（2 万余行 × 97 列）会被网关 **HTTP 524** —— 改**分块** skip/take 拉取后合并；
    每块 8000 行实测 ≤105 s（分块响应仍各带 2 行 baseline，合并时只保留第一份）。
    """
    counters = {"ok": 0, "skip": 0, "fail": 0}
    target = out / "全球机构排名.xlsx"
    if target.exists() and not force:
        print(f"[skip] {target.name} 已存在")
        counters["skip"] += 1
        return counters
    import io

    import openpyxl

    rows: list[tuple] = []
    skip = 0
    t0 = dt.datetime.now()
    try:
        while True:
            data = None
            last_err = None
            for _ in range(3):                      # 524 多为瞬时限流，重试 ≤3 次
                try:
                    data = _export(page, sid, dates, entity="organization",
                                   filters=_base_filters(period), indicators=_ORG_INDICATORS,
                                   fname="全球机构排名", take=_INSTITUTIONS_CHUNK, skip=skip)
                    last_err = None
                    break
                except Exception as e:              # noqa: BLE001
                    last_err = e
                    time.sleep(10)
            if data is None:
                raise RuntimeError(str(last_err))
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
            chunk = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
            wb.close()
            if skip == 0:
                rows.extend(chunk)                  # 表头 + 2 baseline + 第一块数据
            else:
                rows.extend(chunk[3:])              # 后块去掉表头 + 2 baseline
            n_data = len(chunk) - 3
            print(f"    [chunk] skip={skip} 取回 {n_data} 行（累计 {len(rows) - 3}）")
            if n_data < _INSTITUTIONS_CHUNK:
                break                               # 最后一块
            skip += _INSTITUTIONS_CHUNK
        wb2 = openpyxl.Workbook()
        ws = wb2.worksheets[0]
        ws.title = "全球机构排名"
        for r in rows:
            ws.append(list(r))
        target.parent.mkdir(parents=True, exist_ok=True)
        wb2.save(target)
    except Exception as e:                          # noqa: BLE001
        print(f"[FAIL] {target.name}: {e}")
        counters["fail"] += 1
        return counters
    secs = (dt.datetime.now() - t0).total_seconds()
    print(f"[OK] {target.name}  ({target.stat().st_size} B, {len(rows)} 行 × "
          f"{len(rows[0]) if rows else 0} 列, {secs:.0f}s)")
    counters["ok"] += 1
    return counters


COMMANDS = {
    "subjects": cmd_subjects,
    "fields": cmd_fields,
    "institutions": cmd_institutions,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--out", default=None,
                    help="产物目录（默认 ..\\数据与复现\\incites\\数据覆盖<起>-<止>.<WoS截止 MM.DD>）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件（默认跳过）")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        page = _get_incites_page(browser)
        sid, dates = _session(page)
        period = _window(dates)
        #: 快照目录名 = 数据覆盖<period起>-<period止>.<WoS 内容截止 MM.DD>（照历史归档）
        if args.out:
            out = Path(args.out)
        else:
            y, m, d = dates["wosextractdate"].split("-")
            out = DEFAULT_OUT_ROOT / f"数据覆盖{period[0]}-{period[1]}.{m}.{d}"
        print(f"[i] 数据集更新 {dates['deploydate']}，WoS 内容截止 {dates['wosextractdate']}"
              f"（窗口 {period[0]}-{period[1]}）")
        print(f"[i] 产出目录 {out}")
        counters = COMMANDS[args.command](page, sid, dates, period, out, args.force)
    print(f"[=] ok={counters['ok']} skip={counters['skip']} fail={counters['fail']}")
    return 1 if counters["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
