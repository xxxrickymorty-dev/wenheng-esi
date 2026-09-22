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
    python tools/clarivate_esi_fetch.py toppapers        # Step 4 云大论文明细 ×3（文件名「数字在前」）
    python tools/clarivate_esi_fetch.py thresholds       # Step 5a 阈值 ×3
    python tools/clarivate_esi_fetch.py baselines        # Step 5b 基线 ×3
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import openpyxl
from playwright.sync_api import Page, sync_playwright

CDP = "http://127.0.0.1:9222"
ESI = "https://esi.clarivate.com"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tmp" / "clarivate_dl"

# 钩住 window.open（应用的导出全靠它，但会被浏览器弹窗拦截）
HOOK_JS = """() => {
    window.__esiExport = null;
    if (!window.__esiHooked) {
        const ow = window.open;
        window.open = function (u) { window.__esiExport = String(u); return null; };
        window.__esiHooked = true;
    }
    return true;
}"""


def get_esi_page(browser) -> Page:
    ctx = browser.contexts[0]
    for pg in ctx.pages:
        if "esi.clarivate.com" in pg.url:
            pg.bring_to_front()
            return pg
    pg = ctx.new_page()
    pg.goto(f"{ESI}/IndicatorsAction.action?app=esi&Init=Yes", wait_until="domcontentloaded")
    return pg


def export(page: Page, out_path: Path, fmt: str = "Excel") -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.evaluate(HOOK_JS)

    popup = page.locator(".popup-action-download")
    if popup.count() == 0 or not popup.first.is_visible():
        page.locator("a.action-download.icon").first.click(timeout=15000)
        page.wait_for_timeout(1000)

    clicked = page.evaluate(
        """(fmt) => {
            const pop = document.querySelector('.popup-action-download');
            if (!pop) return false;
            const a = [...pop.querySelectorAll('a')].find(x => x.innerText.trim().toUpperCase() === fmt.toUpperCase());
            if (!a) return false;
            a.click();
            return true;
        }""",
        fmt,
    )
    if not clicked:
        raise RuntimeError(f"下载弹层里没有 {fmt} 选项")

    deadline = time.time() + 15
    url = None
    while time.time() < deadline:
        time.sleep(0.5)
        url = page.evaluate("() => window.__esiExport")
        if url:
            break
    if not url:
        raise RuntimeError("没拿到导出 URL（window.open 未被调用）")

    resp = page.request.get(urljoin(page.url, url))
    if not resp.ok:
        raise RuntimeError(f"导出请求失败：{resp.status}")
    out_path.write_bytes(resp.body())
    print(f"[OK] {out_path.name}  ({out_path.stat().st_size} B)  [{fmt}]  {url.split('?')[0]}")
    return out_path


# 导出列：9 列＝默认（含 Highly Cited Papers + Hot Papers）；7 列＝历史版式
_SUBJECT_COLS9 = ("RowSeq,,Institutions,Countries/Regions,Web of Science Documents,Cites,Cites/Paper,"
                  "Top Papers,Highly Cited Papers,Hot Papers")
_SUBJECT_COLS7 = "RowSeq,,Institutions,Countries/Regions,Web of Science Documents,Cites,Cites/Paper,Top Papers"

# Step 1 全球机构总表（无筛选）的导出 URL（实测抄下：filterValue= 空、limit 给大值）
_INSTITUTIONS_URL = (
    ESI + "/IndicatorsExport.action?exportFile&_dc=1&groupBy=Institutions&start=0&limit=30000"
    "&filterBy=Institutions&filterValue=&show=Top"
    "&sort=%5B%7B%22property%22%3A%22cites%22%2C%22direction%22%3A%22DESC%22%7D%5D"
    "&colFilterVal=&exportType=indicators&colNames={cols}&fileType=Excel&f=Institutions.xlsx"
)


def cmd_institutions(page: Page, out: Path, fmt: str) -> None:
    """Step 1：全球机构总表（9 列，含 Highly Cited Papers / Hot Papers）。"""
    out.mkdir(parents=True, exist_ok=True)
    enc = _SUBJECT_COLS9.replace(",", "%2C").replace(" ", "+")
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
    """Step 2：22 个分学科机构排名表（默认 9 列，含 Highly Cited / Hot Papers）。"""
    _run_subjects(page, out, force, _SUBJECT_COLS9)


def cmd_subjects_7col(page: Page, out: Path, fmt: str, force: bool = False) -> None:
    """Step 2 历史版式：22 张学科表（7 列，末列 Top Papers）——用于复现旧期次。"""
    _run_subjects(page, out, force, _SUBJECT_COLS7)


# Research Fields 视图的导出 URL（无筛选那张实测抄下；过滤拼在末尾，f= 必须 ASCII，中文名会被服务端按 Latin-1 处理而返回空表）
_FIELD_URL = (
    ESI + "/IndicatorsExport.action?exportFile&_dc=1&groupBy=ResearchFields&start=0&limit=22&show=Top"
    '&sort=%5B%7B%22property%22:%22cites%22%2C%22direction%22:%22DESC%22%7D%5D'
    "&colFilterVal=&exportType=indicators"
    "&colNames=RowSeq%2C%2CResearch+Fields%2CWeb+of+Science+Documents%2CCites%2CCites%2FPaper%2CTop+Papers"
    "&fileType=Excel&f={fname}&{filter_qs}"
)

# filter_qs 各自参数名不同（实测）：机构用 filterValue；国家用 filterBy=Countries-Territories（不是 Countries/Regions！）
_FIELD_FILTERS = [
    ("云大学科.xlsx", "ynu.xlsx", "filterBy=Institutions&filterValue=YUNNAN%20UNIVERSITY"),
    ("中国学科.xlsx", "cn.xlsx", "filterBy=Countries-Territories&filterValue=CHINA%20MAINLAND"),
]


def _looks_like_xlsx(body: bytes) -> bool:
    return body[:2] == b"PK"


# Step 4：云大论文明细（Documents Result List）。参数取自明细页 exportData() 拼的 URL。
_DOC_URL = (
    ESI + "/DocumentsExport.action?exportFile&_dc=1&groupBy=documentList&start=0&limit=5000"
    "&author=&institution=YUNNAN%20UNIVERSITY&territory=&journal=&researchFront=&year=&title="
    "&researchField=&show={show}"
    "&sort=%5B%7B%22property%22%3A%22citations%22%2C%22direction%22%3A%22DESC%22%7D%5D"
    "&colFilterVal=&exportType=documents"
    "&colNames=Accession+Number,DOI,PMID,Article+Name,Authors,Source,Research+Field,Times+Cited,"
    "Countries,Addresses,Institutions,Publication+Date&fileType=Excel&f=DocumentsExport.xls"
)
_TOPPAPERS = [("Top", "top"), ("highlyCited", "highly cited"), ("Hot", "hot papers")]


def _data_rows(path: Path) -> int:
    """明细导出的数据行数 = 总行数 − 8（前 5 行空/标题 + 表头 + 2 行页脚）。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    return max(ws.max_row - 8, 0)


def cmd_toppapers(page: Page, out: Path, fmt: str) -> None:
    """Step 4：云大 Top / Highly Cited / Hot 论文明细三张，文件名「数字在前」（如 274top.xlsx）。"""
    out.mkdir(parents=True, exist_ok=True)
    for show, suffix in _TOPPAPERS:
        resp = page.request.get(_DOC_URL.format(show=show))
        if not resp.ok or not _looks_like_xlsx(resp.body()):
            print(f"[FAIL] {suffix}: HTTP {resp.status}, {len(resp.body())} B（非 xlsx）")
            continue
        tmp = out / f"_tmp_{show}.xlsx"
        tmp.write_bytes(resp.body())
        n = _data_rows(tmp)
        target = out / f"{n}{suffix}.xlsx"
        if target.exists():
            target.unlink()
        tmp.replace(target)
        print(f"[OK] {target.name}  ({target.stat().st_size} B)  show={show}  篇数={n}")


def cmd_fields(page: Page, out: Path, fmt: str) -> None:
    """Step 3：Research Fields 汇总表三张 —— 全球学科（无筛选）+ 云大学科 + 中国学科。"""
    page.goto(f"{ESI}/IndicatorsAction.action?app=esi&Init=Yes", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.select_option("#groupBy", "Research Fields")
    page.wait_for_timeout(3500)
    export(page, out / "全球学科.xlsx", fmt)

    for fname, ascii_f, filter_qs in _FIELD_FILTERS:
        resp = page.request.get(_FIELD_URL.format(fname=ascii_f, filter_qs=filter_qs))
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
    "subjects-7col": cmd_subjects_7col,
    "fields": cmd_fields,
    "toppapers": cmd_toppapers,
    "thresholds": cmd_thresholds,
    "baselines": cmd_baselines,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--format", default="XLS", choices=["XLS", "CSV", "PDF"])
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件（subjects 用）")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        page = get_esi_page(browser)
        fn = COMMANDS[args.command]
        if args.command in ("subjects", "subjects-7col"):
            fn(page, Path(args.out), args.format, args.force)
        else:
            fn(page, Path(args.out), args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
