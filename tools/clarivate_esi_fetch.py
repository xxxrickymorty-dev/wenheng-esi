# -*- coding: utf-8 -*-
"""ESI 取数自动化（按《ESI数据下载流程.docx》）。

原理：Playwright 经 CDP 附着已登录 Chrome → 设置页面状态 → 点右上角下载图标 →
钩住 window.open 拿到应用的导出 URL（形如 `ThresholdESI.action?exportFile&…&fileType=Excel&f=…`）
→ 用当前会话 cookie 直接 GET，存到目标文件。
（不依赖 Chrome 下载：弹窗/自动下载权限都会拦，直接 GET 最稳。）

前置：双击 start-clarivate-chrome.bat（带 CDP 9222 的 Chrome，已登录 ESI/InCites）。

用法（命令名见下方 COMMANDS）：
    python tools/clarivate_esi_fetch.py institutions     # Step 1 全球机构总表（9 列）
    python tools/clarivate_esi_fetch.py subjects         # Step 2 22 学科机构表（9 列；--force 覆盖）
    python tools/clarivate_esi_fetch.py subjects-7col    # 同上，历史 7 列版式
    python tools/clarivate_esi_fetch.py fields           # Step 3 全球/云大/中国 学科汇总
    python tools/clarivate_esi_fetch.py toppapers        # Step 4 论文明细 ×3（--institution 换校）
    python tools/clarivate_esi_fetch.py thresholds       # Step 5a 阈值 ×3
    python tools/clarivate_esi_fetch.py baselines        # Step 5b 基线 ×3
    python tools/clarivate_esi_fetch.py login            # 检查/自动重登会话（不下载）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import openpyxl
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clarivate_login import ensure_login                    # noqa: E402  会话过期自动重登（同目录）

CDP = "http://127.0.0.1:9222"

def resolve_cdp() -> str:
    """CDP 地址：先试 127.0.0.1，再试 localhost（本机 IPv4 端口被占时 Chrome 可能只听 ::1）。

    只认**能解析出 CDP 版本 JSON** 的地址（别的服务占着 9222 也回 200 的坑踩过）；
    两个都不通就人话拒绝，别把连接错误糊成一段 traceback。
    """
    import json as _json
    import urllib.request

    for url in ("http://127.0.0.1:9222", "http://localhost:9222"):
        try:
            with urllib.request.urlopen(url + "/json/version", timeout=2) as r:
                if r.status == 200 and _json.loads(r.read()).get("Browser"):
                    return url
        except Exception:                                          # noqa: BLE001
            continue
    raise SystemExit("[拒绝] 取数浏览器没连上：先双击「取数专用浏览器」并确认窗口已打开，再重试。")

ESI = "https://esi.clarivate.com"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tmp" / "clarivate_dl"

def get_esi_page(browser) -> Page:
    ctx = browser.contexts[0]
    for pg in ctx.pages:
        if "esi.clarivate.com" in pg.url:
            pg.bring_to_front()
            return pg
    pg = ctx.new_page()
    pg.goto(f"{ESI}/IndicatorsAction.action?app=esi&Init=Yes", wait_until="domcontentloaded")
    return pg


# 导出列三档（机构表与学科表同一套）：
#   15 列＝默认：Base 6 列 + Top / Highly Cited / Hot 各 3 列（Papers、Cites to、Cites per）
#    9 列＝202607 那版（三组只保留 Papers 计数）；7 列＝更早的历史版式
_COLS15 = ("RowSeq,,Institutions,Countries/Regions,Web of Science Documents,Cites,Cites/Paper,"
           "Top Papers,Cites to Top Papers,Cites/Top Paper,"
           "Highly Cited Papers,Cites to Highly Cited Papers,Cites/Highly Cited Paper,"
           "Hot Papers,Cites to Hot Papers,Cites/Hot Paper")
_COLS9 = ("RowSeq,,Institutions,Countries/Regions,Web of Science Documents,Cites,Cites/Paper,"
          "Top Papers,Highly Cited Papers,Hot Papers")
_COLS7 = "RowSeq,,Institutions,Countries/Regions,Web of Science Documents,Cites,Cites/Paper,Top Papers"

# Step 1 全球机构总表（无筛选）的导出 URL（实测抄下：filterValue= 空、limit 给大值）
_INSTITUTIONS_URL = (
    ESI + "/IndicatorsExport.action?exportFile&_dc=1&groupBy=Institutions&start=0&limit=30000"
    "&filterBy=Institutions&filterValue=&show=Top"
    "&sort=%5B%7B%22property%22%3A%22cites%22%2C%22direction%22%3A%22DESC%22%7D%5D"
    "&colFilterVal=&exportType=indicators&colNames={cols}&fileType=Excel&f=Institutions.xlsx"
)


def cmd_institutions(page: Page, out: Path, fmt: str) -> None:
    """Step 1：全球机构总表（默认 15 列）。"""
    out.mkdir(parents=True, exist_ok=True)
    enc = _COLS15.replace(",", "%2C").replace(" ", "+")
    resp = page.request.get(_INSTITUTIONS_URL.format(cols=enc))
    if not resp.ok or not _looks_like_xlsx(resp.body()):
        print(f"[FAIL] Institutions.xlsx: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
        return
    target = out / "Institutions.xlsx"
    target.write_bytes(resp.body())
    print(f"[OK] {target.name}  ({target.stat().st_size} B)")


# Step 5a：三张阈值表（端点抄自 Thresholds 页 getThresholdsExport()）
# ⚠ HCP / Hot 的 sort 属性是 `FIELD`，ESI 那张是 `researchField`——用错返回 97 B 服务端报错。
_THRESHOLDS = [
    ("ThresholdESI", "thresholdsTop", "researchField", "ThresholdESI.xlsx"),
    ("ThresholdHighlyCited", "thresholdsHighlyCited", "FIELD", "ThresholdHighlyCited.xlsx"),
    ("ThresholdHot", "thresholdsHot", "FIELD", "ThresholdHot.xlsx"),
]


def cmd_thresholds(page: Page, out: Path, fmt: str) -> None:
    """Step 5a：三张阈值表（ESI / Highly Cited / Hot）。"""
    out.mkdir(parents=True, exist_ok=True)
    for action, fb, prop, fname in _THRESHOLDS:
        sort = f"%5B%7B%22property%22%3A%22{prop}%22%2C%22direction%22%3A%22ASC%22%7D%5D"
        url = (
            f"{ESI}/{action}.action?exportFile&_dc=1&sort={sort}"
            f"&groupBy=Thresholds&filterBy={fb}&exportType=Thresholds&fileType=Excel&f={action}.xlsx"
        )
        resp = page.request.get(url)
        if not resp.ok or not _looks_like_xlsx(resp.body()):
            print(f"[FAIL] {fname}: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
            continue
        target = out / fname
        target.write_bytes(resp.body())
        print(f"[OK] {fname}  ({target.stat().st_size} B)")


# Step 2：22 个 ESI 学科（顺序照《ESI数据下载流程.docx》）
SUBJECTS = [
    "Agricultural Sciences", "Biology & Biochemistry", "Chemistry", "Clinical Medicine",
    "Computer Science", "Economics & Business", "Engineering", "Environment/Ecology",
    "Geosciences", "Immunology", "Materials Science", "Mathematics", "Microbiology",
    "Molecular Biology & Genetics", "Multidisciplinary", "Neuroscience & Behavior",
    "Pharmacology & Toxicology", "Physics", "Plant & Animal Science",
    "Psychiatry/Psychology", "Social Sciences, General", "Space Science",
]

# 从「勾选 Chemistry 后应用自建的导出 URL」抄下来的模板（服务端认，直接 GET 即可）
_SUBJECT_URL = (
    ESI + "/IndicatorsExport.action?exportFile&_dc=1&groupBy=Institutions&start=0&limit=2268"
    "&filterBy=ResearchFields&filterValue={val}&show=Top"
    "&sort=%5B%7B%22property%22%3A%22cites%22%2C%22direction%22%3A%22DESC%22%7D%5D"
    "&colFilterVal=&exportType=indicators"
    "&colNames={cols}"
    "&fileType=Excel&f={fname}"
)


def _run_subjects(page: Page, out: Path, force: bool, cols: str) -> None:
    """Step 2：22 个分学科机构排名表；cols 决定导出里带哪些列。"""
    out.mkdir(parents=True, exist_ok=True)
    enc = cols.replace(",", "%2C").replace(" ", "+")
    for s in SUBJECTS:
        # 历史归档把 / 写成空格（Environment/Ecology → Environment Ecology.xlsx）
        fname = s.replace("/", " ")
        target = out / f"{fname}.xlsx"
        if target.exists() and not force:
            print(f"[skip] {target.name} 已存在")
            continue
        url = _SUBJECT_URL.format(val=quote(s.upper()), fname=quote(f"{fname}.xlsx"), cols=enc)
        resp = page.request.get(url)
        if not resp.ok or not _looks_like_xlsx(resp.body()):
            print(f"[FAIL] {s}: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
            continue
        target.write_bytes(resp.body())
        print(f"[OK] {target.name}  ({target.stat().st_size} B)")


def cmd_subjects(page: Page, out: Path, fmt: str, force: bool = False) -> None:
    """Step 2：22 个分学科机构排名表（默认 15 列）。"""
    _run_subjects(page, out, force, _COLS15)


def cmd_subjects_9col(page: Page, out: Path, fmt: str, force: bool = False) -> None:
    """Step 2 变体：9 列（202607 那版，Top/HCP/Hot 只保 Papers 计数）。"""
    _run_subjects(page, out, force, _COLS9)


def cmd_subjects_7col(page: Page, out: Path, fmt: str, force: bool = False) -> None:
    """Step 2 历史版式：7 列（末列 Top Papers）——用于复现旧期次。"""
    _run_subjects(page, out, force, _COLS7)


# Research Fields 视图的导出 URL（无筛选那张实测抄下；过滤拼在末尾，f= 必须 ASCII，中文名会被服务端按 Latin-1 处理而返回空表）
_FIELD_URL = (
    ESI + "/IndicatorsExport.action?exportFile&_dc=1&groupBy=ResearchFields&start=0&limit=22&show=Top"
    '&sort=%5B%7B%22property%22:%22cites%22%2C%22direction%22:%22DESC%22%7D%5D'
    "&colFilterVal=&exportType=indicators"
    "&colNames={cols}"
    "&fileType=Excel&f={fname}&{filter_qs}"
)

# Research Fields 视图的列：全球/中国 7 列；云大 14 列（再带 Top/HCP/Hot 各 Cites to / Cites-per）
_FIELD_COLS7 = "RowSeq,,Research Fields,Web of Science Documents,Cites,Cites/Paper,Top Papers"
_FIELD_COLS14 = ("RowSeq,,Research Fields,Web of Science Documents,Cites,Cites/Paper,"
                 "Top Papers,Cites to Top Papers,Cites/Top Paper,"
                 "Highly Cited Papers,Cites to Highly Cited Papers,Cites/Highly Cited Paper,"
                 "Hot Papers,Cites to Hot Papers,Cites/Hot Paper")

# filter_qs 各自参数名不同（实测）：机构用 filterValue；国家用 filterBy=Countries-Territories（不是 Countries/Regions！）
_FIELD_FILTERS = [
    ("全球学科.xlsx", "global.xlsx", "filterBy=ResearchFields&filterValue=", _FIELD_COLS7),
    ("云大学科.xlsx", "ynu.xlsx", "filterBy=Institutions&filterValue=YUNNAN%20UNIVERSITY", _FIELD_COLS14),
    ("中国学科.xlsx", "cn.xlsx", "filterBy=Countries-Territories&filterValue=CHINA%20MAINLAND", _FIELD_COLS7),
]


def _looks_like_xlsx(body: bytes) -> bool:
    return body[:2] == b"PK"


# Step 4：论文明细（Documents Result List）。参数取自明细页 exportData() 拼的 URL。
# 换校只改 institution 一个 URL 参数（2026-10-31 实测：HAINAN UNIVERSITY 直取成功），
# 无需界面过滤；失败多半是会话刚重登还没稳——先跑 `login` 再导出。
_DOC_URL = (
    ESI + "/DocumentsExport.action?exportFile&_dc=1&groupBy=documentList&start=0&limit=5000"
    "&author=&institution={inst}&territory=&journal=&researchFront=&year=&title="
    "&researchField=&show={show}"
    "&sort=%5B%7B%22property%22%3A%22citations%22%2C%22direction%22%3A%22DESC%22%7D%5D"
    "&colFilterVal=&exportType=documents"
    "&colNames=Accession+Number,DOI,PMID,Article+Name,Authors,Source,Research+Field,Times+Cited,"
    "Countries,Addresses,Institutions,Publication+Date&fileType=Excel&f=DocumentsExport.xls"
)
_TOPPAPERS = [("Top", "top"), ("highlyCited", "highly cited"), ("Hot", "hot papers")]


def _write_esi_csv(rows: list[tuple], path: Path) -> None:
    """按 ESI 导出的 CSV 观感写盘：标题行 + 表头 + 数据行（逐字段加引号）+ 页脚。

    这样产出的 CSV 与「学院顶尖论文清单.csv」（馆员手工另存的那份）同形，可替代人工贴入。
    """
    body = [r for r in rows if any(c is not None for c in r)]
    lines: list[str] = []
    for i, r in enumerate(body):
        cells = ["" if c is None else str(c) for c in r]
        head = cells[0]
        if i < 2 or head.startswith(("Copyright", "Export Date")):
            lines.append(",".join(cells).rstrip(","))
        else:
            lines.append(",".join('"' + c.replace('"', '""') + '"' for c in cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def cmd_toppapers(page: Page, out: Path, fmt: str, institution: str = "YUNNAN UNIVERSITY") -> None:
    """Step 4：论文明细 ×3（Top / Highly Cited / Hot），出 xlsx + 同形 CSV。

    文件名「数字在前」（如 274top.xlsx / 274top.csv）。换校＝--institution 改 URL 过滤参数
    （ESI 机构名写法照 Institutions 总表），其余流程不变。
    """
    out.mkdir(parents=True, exist_ok=True)
    inst = quote(institution)
    for show, suffix in _TOPPAPERS:
        resp = page.request.get(_DOC_URL.format(show=show, inst=inst))
        if not resp.ok or not _looks_like_xlsx(resp.body()):
            print(f"[FAIL] {suffix}: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
            continue
        tmp = out / f"_tmp_{show}.xlsx"
        tmp.write_bytes(resp.body())
        wb = openpyxl.load_workbook(tmp, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
        n = max(ws.max_row - 8, 0)
        target = out / f"{n}{suffix}.xlsx"
        if target.exists():
            target.unlink()
        tmp.replace(target)
        csv_path = out / f"{n}{suffix}.csv"
        _write_esi_csv(rows, csv_path)
        print(f"[OK] {target.name}  ({target.stat().st_size} B) + {csv_path.name}  篇数={n}")


def cmd_fields(page: Page, out: Path, fmt: str) -> None:
    """Step 3：Research Fields 汇总三张 —— 全球学科（7 列）+ 中国学科（7 列）+ 云大学科（14 列）。"""
    out.mkdir(parents=True, exist_ok=True)

    for fname, ascii_f, filter_qs, cols in _FIELD_FILTERS:
        enc = cols.replace(",", "%2C").replace(" ", "+")
        resp = page.request.get(_FIELD_URL.format(fname=ascii_f, filter_qs=filter_qs, cols=enc))
        if not resp.ok or not _looks_like_xlsx(resp.body()):
            print(f"[FAIL] {fname}: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
            continue
        target = out / fname
        target.write_bytes(resp.body())
        print(f"[OK] {fname}  ({target.stat().st_size} B)")


_BASELINES = [
    ("BaselineCitationRates", "citationRates", "researchField"),
    ("BaselinePercentiles", "percentiles", "percentile"),
    ("BaselineFieldRankings", "fieldRankings", "researchField"),
]


def cmd_baselines(page: Page, out: Path, fmt: str) -> None:
    """Step 5b：三张基线表（端点与参数抄自 Baseline 页的 getBaselinesExport()）。

    ⚠ `sort` 必须带，否则服务端返回 97 B 空响应。
    """
    out.mkdir(parents=True, exist_ok=True)
    for action, fb, prop in _BASELINES:
        sort = f"%5B%7B%22property%22%3A%22{prop}%22%2C%22direction%22%3A%22ASC%22%7D%5D"
        url = (
            f"{ESI}/{action}.action?exportFile&_dc=1&sort={sort}"
            f"&groupBy=Baselines&filterBy={fb}&exportType=Baselines&fileType=Excel&f={action}.xlsx"
        )
        resp = page.request.get(url)
        if not resp.ok or not _looks_like_xlsx(resp.body()):
            print(f"[FAIL] {action}: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
            continue
        target = out / f"{action}.xlsx"
        target.write_bytes(resp.body())
        print(f"[OK] {target.name}  ({target.stat().st_size} B)")


COMMANDS = {
    "institutions": cmd_institutions,
    "subjects": cmd_subjects,
    "subjects-9col": cmd_subjects_9col,
    "subjects-7col": cmd_subjects_7col,
    "fields": cmd_fields,
    "toppapers": cmd_toppapers,
    "thresholds": cmd_thresholds,
    "baselines": cmd_baselines,
}


def write_fetch_meta(out: Path, command: str) -> Path:
    """记下载信息：报告里「ESI 发布日期」槽位就用**下载日**（发布即下载），不再向馆员要。"""
    import datetime as dt
    import json

    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "_下载信息.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            meta = {}
    meta.setdefault("首次下载", dt.date.today().isoformat())
    meta["最近下载"] = dt.date.today().isoformat()
    meta["最近命令"] = command
    meta["说明"] = "报告里「ESI 发布日期」槽位取本文件首次/最近下载日（ESI 发布即下载）"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meta] {meta_path}  下载日 {meta['最近下载']}")
    return meta_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=sorted([*COMMANDS, "login"]))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--format", default="XLS", choices=["XLS", "CSV", "PDF"])
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件（subjects 用）")
    ap.add_argument("--institution", default="YUNNAN UNIVERSITY",
                    help="论文明细的机构过滤（ESI 机构名，换校改这里；toppapers 用）")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(resolve_cdp())
        page = get_esi_page(browser)
        ensure_login(page, "esi")            # 会话过期自动重登（Chrome 自动填表 + 点 Sign in）
        if args.command == "login":
            print("[OK] ESI 登录就绪")
            return 0
        fn = COMMANDS[args.command]
        if args.command in ("subjects", "subjects-9col", "subjects-7col"):
            fn(page, Path(args.out), args.format, args.force)
        elif args.command == "toppapers":
            fn(page, Path(args.out), args.format, args.institution)
        else:
            fn(page, Path(args.out), args.format)
    write_fetch_meta(Path(args.out), args.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
