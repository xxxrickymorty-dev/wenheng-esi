# -*- coding: utf-8 -*-
"""从 ESI 原始下载包抽取「前 1% / 前 0.1%（千分之一）」被引阈值，并可写回台账。

背景与口径（2026-09-15 反推确立，用 202605 全 23 项验证 23/23 命中）
--------------------------------------------------------------------
ESI 每个学科的「机构榜」（文件如 `Chemistry.xlsx`）只收录**全球前 1%** 的机构，
按 Cites 降序排列。由此：

  · 1%  阈值 = 榜单**末位**机构的 Cites
                （恒等于 `ThresholdESI.xlsx` 的 INSTITUTION 列，可作交叉校验）
  · 1‰  阈值 = 榜单第 **floor((m+1)/10)** 位机构的 Cites
                榜单前 10% 即全局前 0.1% = 千分之一
                m = 榜单有效数据行数；+1 是因为馆员的百分比区间**含表头行**

榜单结构（三种期次导出一致）：
    行4 = 说明行、行5 = 表头、行6 起为数据
    列 A 序号 │ B Institutions │ C Countries/Regions │ D WoS Docs │ E Cites │ F Cites/Paper │ G Top Papers
注意：**这些导出文件的单元格是文本**（'111691' 而非 111691），必须自行转数。

用法
----
    # 只看（dry-run，默认）
    .venv\\Scripts\\python.exe src\\extract_1permille.py 202601

    # 写回台账（先自动备份，再只改目标 sheet 的 XML，其余 zip 成员字节不变）
    .venv\\Scripts\\python.exe src\\extract_1permille.py 202601 --write

    # 手工指定数据根目录 / 目标台账
    ... --data-root "..\\数据与复现\\ESI数据" --ledger "<台账.xlsx>" --ledger "<另一份.xlsx>"

写回是**按列追加、绝不覆盖历史**：新期次与现有期次合并后按时间序重排，已存在的值若与
新算值冲突会**拒绝写入**并报错（口径变化必须先人工确认）。
"""
import argparse
import html
import pathlib
import re
import shutil
import sys
import zipfile

import openpyxl

REPO = pathlib.Path(__file__).resolve().parent.parent          # wenheng/
SHEET = "千分之一被引阈值"

# 台账学科名（与 parse_ledger.DISCIPLINES_EN 对齐） → ESI 原始文件名
DISC_FILES = {
    "Agricultural Sciences": "Agricultural Sciences.xlsx",
    "Biology & Biochemistry": "Biology & Biochemistry.xlsx",
    "Chemistry": "Chemistry.xlsx",
    "Clinical Medicine": "Clinical Medicine.xlsx",
    "Computer Science": "Computer Science.xlsx",
    "Economics & Business": "Economics & Business.xlsx",
    "Engineering": "Engineering.xlsx",
    "Environment/Ecology": "Environment Ecology.xlsx",
    "Geosciences": "Geosciences.xlsx",
    "Immunology": "Immunology.xlsx",
    "Materials Science": "Materials Science.xlsx",
    "Mathematics": "Mathematics.xlsx",
    "Microbiology": "Microbiology.xlsx",
    "Molecular Biology & Genetics": "Molecular Biology & Genetics.xlsx",
    "Multidisciplinary": "Multidisciplinary.xlsx",
    "Neuroscience & Behavior": "Neuroscience & Behavior.xlsx",
    "Pharmacology & Toxicology": "Pharmacology & Toxicology.xlsx",
    "Physics": "Physics.xlsx",
    "Plant & Animal Science": "Plant & Animal Science.xlsx",
    "Psychiatry/Psychology": "Psychiatry Psychology.xlsx",
    "Social Sciences, general": "Social Sciences, General.xlsx",
    "Space Science": "Space Science.xlsx",
}
OVERALL_FILE = "Institutions.xlsx"          # 全校整体（台账不存，仅供信息）

#: ESI 原始包根目录：其**子目录名即期次**（如 `<root>/202601/Chemistry.xlsx`）。
#: 2026-09-16 原始包由 `数据与复现/202601-03ESI数据/<期次>/` 改为
#: `数据与复现/<期次>/`；2026-09-18 去冗余 + 命名归一后再改为
#: `数据与复现/ESI数据/<期次>/`（45 期齐 201903→202607，目录名统一 `YYYYMM`）。
#: 常量过期不会报错，只会让 1‰ 取位守卫**静默跳过**（`tests/test_permille_rule.py`
#: 四例全 skip），故一并把断言写进 tests。
DEFAULT_DATA_ROOT = REPO.parent / "数据与复现" / "ESI数据"
DEFAULT_LEDGERS = [
    REPO.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx",
    REPO / "input" / "202607" / "监测表.xlsx",
]
BACKUP_DIR = REPO.parent / "归档" / "台账备份"


def _num(v):
    """ESI 导出为文本，统一转 float。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def find_ranking_header(rows, limit=12):
    """→ (表头 0 基行号, {列名: 列号})，找不到返回 (None, {})。

    2026-09-18 起不再写死 `rows[5]`：说明行
    `Indicators Results List: Institutions   Filter Results By: … Filter Value(s): CHEMISTRY`
    也含 "Institutions" 字样且排在真表头之前，所以判据取严——
    要求**某一整格等于** "Institutions"（真表头第 2 列）。
    """
    for hi, hrow in enumerate(rows[:limit]):
        if not any(str(c).strip() == "Institutions" for c in (hrow or []) if c is not None):
            continue
        cols = {}
        for ci, c in enumerate(hrow or []):
            nm = str(c).strip() if c is not None else ""
            if nm:
                cols.setdefault(nm, ci)
        return hi, cols
    return None, {}


def pick_cites_col(cols):
    """从表头列名里挑「Cites」列。

    必须按名字挑，不能写死列号：202309/Physics 这类文件的列布局整体右移一格
    （Countries/Regions 列空、国家挪到下一列），写死第 5 列会读到 **WoS Documents**，
    于是整份榜单按发文量排序 → 取位值崩到 1/30 且非降序。
    """
    for nm, ci in cols.items():
        if nm.lower() == "cites":
            return ci
    for nm, ci in cols.items():               # 变体兜底：Cites 但排除 Cites/Paper
        k = nm.lower()
        if k.startswith("cite") and "paper" not in k:
            return ci
    return None


def _is_footer(row):
    """页脚行（`Copyright © 20xx Clarivate…`）。"""
    return any(c and "copyright" in str(c).lower() for c in (row or [])[:3])


def parse_ranking(path):
    """返回 (cites 列表 降序, m)。找不到机构榜时返回 (None, 0)。

    终止判据是 **Cites 列非数字** 或**页脚行**，不是「序号列非数字」：
    202501/Biology & Biochemistry.xlsx 的**首行序号是空的**
    （`['', 'UNIVERSITY OF CALIFORNIA', …]`），拿序号当判据会一行都读不到。
    """
    wb = openpyxl.load_workbook(path, data_only=True)  # ESI 新导出 dimension 常坏，普通模式才读得全
    best = None
    try:
        for sn in wb.sheetnames:
            ws = wb[sn]
            rows = list(ws.iter_rows(min_row=1, max_row=None if ws.max_row else 4096,
                                    values_only=True))
            if len(rows) < 8:
                continue
            hi, cols = find_ranking_header(rows)
            if hi is None:
                continue
            ci = pick_cites_col(cols)
            if ci is None:
                continue
            cites = []
            for r in rows[hi + 1:]:
                if not r or _is_footer(r):
                    break
                if len(r) <= ci:
                    continue
                v = _num(r[ci])
                if v is None:
                    continue                    # 缺序号的首行等，不当作数据终止
                cites.append(v)
            if len(cites) >= 10 and (best is None or len(cites) > len(best)):
                best = cites
    finally:
        wb.close()
    if not best:
        return None, 0
    # 🔴 必须自己降序排：部分期次（202003/202005 等）的导出是**按国名字母序**排列的
    #    （202003/Engineering 首行 ALGERIA、末行 WALES），行序不反映 Cites 高低。
    #    而 1‰ 阈值只取决于「集合」——取第 ⌊(m+1)/10⌋ 大的 Cites 即可，
    #    与行序无关。对本来就降序的文件，排序是无操作（202607 上对馆员成品 22/22 不变）。
    return sorted(best, reverse=True), len(best)


#: 2019 年老格式包的中文文件名 → 台账学科名。
#: 201905/201907 用「全球机构-<中文>」；201903 用「全球<中文>入选情况」（只 8 科）。
#: 键都经 `_norm_name` 归一，比对时也归一。
#: 🔴 必须显式成表，不能用「包含中文名」的模糊包含匹配——
#:    「化学」是「生物与生物化学」的子串，包含匹配会把 B&B 错配给 Chemistry。
CN_FILE_ALIAS = {
    # ── 201905 / 201907
    "全球机构化学": "Chemistry",
    "全球机构临床医学": "Clinical Medicine",
    "全球机构免疫": "Immunology",
    "全球机构免疫学": "Immunology",
    "全球机构农业科学": "Agricultural Sciences",
    "全球机构分子生物与基因": "Molecular Biology & Genetics",
    "全球机构地球科学": "Geosciences",
    "全球机构多学科": "Multidisciplinary",
    "全球机构工程": "Engineering",
    "全球机构微生物": "Microbiology",
    "全球机构数学": "Mathematics",
    "全球机构材料科学": "Materials Science",
    "全球机构植物与动物学": "Plant & Animal Science",
    "全球机构植物与动物科学": "Plant & Animal Science",
    "全球机构物理": "Physics",
    "全球机构环境与生态": "Environment/Ecology",
    "全球机构环境生态": "Environment/Ecology",
    "全球机构生物与生物化学": "Biology & Biochemistry",
    "全球机构社会科学": "Social Sciences, general",
    "全球机构神经科学与行为": "Neuroscience & Behavior",
    "全球机构空间科学": "Space Science",
    "全球机构经济与商业": "Economics & Business",
    "全球机构经济商业": "Economics & Business",
    "全球机构药学与毒理学": "Pharmacology & Toxicology",
    "全球机构计算机": "Computer Science",
    "全球机构计算机科学": "Computer Science",
    "全球机构精神病学与心理学": "Psychiatry/Psychology",
    "全球机构生理学与心理学": "Psychiatry/Psychology",     # 201907 原件笔误
    # ── 201903（只这 8 科有）
    "全球化学学科入选情况": "Chemistry",
    "全球临床医学入选情况": "Clinical Medicine",
    "全球工程学入选情况": "Engineering",
    "全球微生物学入选情况": "Microbiology",
    "全球数学学科入选情况": "Mathematics",
    "全球材料科学入选情况": "Materials Science",
    "全球植物与动物学科入选情况": "Plant & Animal Science",
    "全球物理学入选情况": "Physics",
}
_CANON = "".join(chr(ord("A") + i) for i in range(26)) + "0123456789"


def _norm_name(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s or ""))
    for ch in " \t_-/,\u3000.()（）":
        s = s.replace(ch, "")
    return s.lower()


def _index_dir(d, depth=2):
    """目录 → {归一化名: 路径}，含**至多 depth 层**子目录。

    201909 的机构榜在 `201909/ESI/<学科>.xlsx`（比别的期深一层），
    所以必须递归；浅层优先，避免深层同名文件抢位。
    """
    idx = {}
    stack = [(d, 0)]
    while stack:
        cur, lv = stack.pop(0)
        try:
            entries = sorted(cur.iterdir())
        except OSError:
            continue
        for q in entries:
            if q.is_dir():
                if lv + 1 < depth:
                    stack.append((q, lv + 1))
                continue
            if q.name.startswith("~$") or q.suffix.lower() not in (".xlsx", ".xls"):
                continue
            idx.setdefault(_norm_name(q.name), q)
            idx.setdefault(_norm_name(q.stem), q)
    return idx


def resolve_file(d, fn, disc=None, idx=None):
    """在目录 d（含浅层子目录）里宽松定位学科文件。

    历史期次的文件名不干净（2026-09-18 实测）：
      · 大写：`CHEMISTRY.xlsx`（2019–2020 各期）—— Windows 不区分大小写，天然可开
      · 截断：`COMPUTER SCIENC.xlsx`（202001）、`AGRICULTURAL.xlsx`（202103）
      · 拼错：`PSYCHIATRY SYCHOLOGY.xlsx`（202003）
      · 中文：`全球机构-化学.xlsx`（201905/201907）、`全球化学学科入选情况.xlsx`（201903）
      · 深一层：`ESI/Chemistry.xlsx`（201909）
    """
    import difflib
    p = d / fn
    if p.exists():
        return p
    idx = _index_dir(d) if idx is None else idx
    want = _norm_name(pathlib.Path(fn).stem)
    if want in idx:
        return idx[want]
    key = disc or pathlib.Path(fn).stem
    for cn, tgt in CN_FILE_ALIAS.items():           # 中文别名（显式表，不做包含匹配）
        if tgt == key and cn in idx:
            return idx[cn]
    for k, q in sorted(idx.items()):                # 前缀截断（按 stem 比，不能带扩展名）
        if len(k) >= 8 and (k.startswith(want) or want.startswith(k)):
            return q
    close = difflib.get_close_matches(want, list(idx), n=1, cutoff=0.85)
    return idx[close[0]] if close else None


def resolve_overall(d, idx=None):
    """定位「整体机构榜」（全校不分学科的机构被引榜，**台账不存、仅供信息**）。

    2026-09-18 全量清点：这份文件在各期的名字有 **8 种写法**，且一半期次干脆没下：
        Institutions.xlsx / institutions.xlsx / institutions all.xlsx /
        institutes.xlsx / all institutes.xlsx / institute.xlsx /
        global institute.xlsx / world Institutions.xlsx

    共同点是都含拉丁词干 `institut`，所以这里**按词干筛**（与学科文件的显式别名表
    相反：这份每期至多一份，不存在歧义）。规范名 `institutions` 优先，其次浅层优先
    （202603/202605/202607 有嵌套 `测试/institutions.xlsx`，别让深层的抢位）。
    🔴 不能用中文「机构」当判据——`中国机构属性.xlsx` 是属性表、不是榜单。
    """
    idx = _index_dir(d) if idx is None else idx
    if "institutions" in idx:                      # 规范名优先
        return idx["institutions"]
    hits = [(len(q.relative_to(d).parts), k, q)
            for k, q in idx.items() if "institut" in k]
    if not hits:
        return None
    hits.sort(key=lambda t: (t[0], len(t[1])))     # 浅层优先、再取短名
    return hits[0][2]


def extract_period(data_root, period):
    """→ {学科: {'m','t1pct','t1pm','rank_1pm','src'}} + '__OVERALL__'"""
    d = pathlib.Path(data_root) / str(period)
    if not d.is_dir():
        raise SystemExit(f"数据目录不存在：{d}")
    idx = _index_dir(d)                 # 每期只扫一次目录树（22 科共用）
    out = {}
    for disc, fn in DISC_FILES.items():
        p = resolve_file(d, fn, disc=disc, idx=idx)
        if p is None:
            out[disc] = {"error": f"缺文件 {fn}"}
            continue
        cites, m = parse_ranking(p)
        if not cites:
            out[disc] = {"error": "未识别机构榜 sheet"}
            continue
        rank = (m + 1) // 10
        out[disc] = {"m": m, "t1pct": int(cites[-1]),
                     "t1pm": int(cites[rank - 1]), "rank_1pm": rank,
                     "src": p.name}
    p = resolve_overall(d, idx)
    if p is not None:
        cites, m = parse_ranking(p)
        if cites:
            rank = (m + 1) // 10
            out["__OVERALL__"] = {"m": m, "t1pct": int(cites[-1]),
                                  "t1pm": int(cites[rank - 1]), "rank_1pm": rank,
                                  "src": p.name}
    return out


def crosscheck_t1pct(data_root, period, res):
    """1% 阈值 与 ThresholdESI.xlsx 的 INSTITUTION 列比对，作口径体检。

    迭代必须给上界：202103/ThresholdESI.xlsx 的 `dimension` 是坏的
    （openpyxl 报 max_row=1），无界 `iter_rows()` 只会吐 1 行 → 全期一个学科都匹配不上。
    """
    p = pathlib.Path(data_root) / str(period) / "ThresholdESI.xlsx"
    if not p.exists():
        return None
    wb = openpyxl.load_workbook(p, data_only=True)  # ESI 新导出 dimension 常坏，普通模式才读得全
    try:
        ws = wb[wb.sheetnames[0]]
        try:
            ws.reset_dimensions()               # 官方修法；老版本没有就靠下面的 max_row
        except Exception:
            pass
        thr = {}
        for r in ws.iter_rows(min_row=1, max_row=128, values_only=True):
            if r and len(r) > 3 and r[0] and _num(r[3]) is not None \
                    and str(r[0]).strip().isupper():
                thr[str(r[0]).strip()] = int(_num(r[3]))
    finally:
        wb.close()
    hit = miss = 0
    detail = []
    for disc, rec in res.items():
        if disc.startswith("__") or "error" in rec:
            continue
        key = [k for k in thr
               if k.replace(" ", "").upper() == disc.replace(" ", "").upper()
               or k.upper().startswith(disc.split("/")[0].upper()[:8])]
        if not key:
            continue
        if thr[key[0]] == rec["t1pct"]:
            hit += 1
        else:
            miss += 1
            detail.append((disc, rec["t1pct"], thr[key[0]]))
    return hit, miss, detail


# ---------------------------------------------------------------- 写回台账
CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
ROW_RE = re.compile(r'<row r="(\d+)"([^>]*?)>(.*?)</row>', re.S)

PERIOD_RE = re.compile(r"^\d{6}$")


def col_letter(idx):
    """1 基列号 → 列字母（1→A, 26→Z, 27→AA…）。45 期要写到 AU，`chr(ord('B')+i)` 不够用。"""
    s = ""
    while idx > 0:
        idx, r = divmod(idx - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n


def read_sheet_table(ledger, sheetname=SHEET):
    """→ (periods:list[str], {学科: {期次: 值}})

    periods = 表头行中**所有 6 位数字期次**，按列序排列（不再写死 B–F 五列）。
    """
    import xlsx_io                                                # noqa: PLC0415

    zf = zipfile.ZipFile(ledger)
    try:
        shared = xlsx_io.read_shared_strings(zf)
        member = xlsx_io.member_of(zf, sheetname)
        xml = zf.read(member).decode("utf-8")
    finally:
        zf.close()
    rows = {}
    for mrow in ROW_RE.finditer(xml):
        rn = int(mrow.group(1))
        cells = {}
        for col, _r, attrs, inner in CELL_RE.findall(mrow.group(3)):
            if 't="s"' in attrs and inner:
                cells[col] = html.unescape(shared[int(re.search(r"<v>(\d+)</v>", inner).group(1))])
            else:
                v = re.search(r"<v>([^<]*)</v>", inner) if inner else None
                cells[col] = v.group(1) if v else None
        rows[rn] = cells
    pairs = sorted((col_index(c), str(v).strip())
                   for c, v in rows.get(1, {}).items()
                   if c != "A" and v is not None and PERIOD_RE.match(str(v).strip()))
    periods = [p for _, p in pairs]
    cols = [col_letter(i) for i, _ in pairs]
    table = {}
    for rn in sorted(rows):
        if rn == 1:
            continue
        name = rows[rn].get("A")
        if not name:
            continue
        table[name] = {p: rows[rn].get(c) for c, p in zip(cols, periods)}
    return periods, table


def rewrite_sheet(ledger, periods, order, table, sheetname=SHEET):
    """按 periods 顺序重写该 sheet。

    只改目标 sheet 的 XML，其余 zip 成员原样复制（保住图表/条件格式/打印设置）。
    order = [学科名...]（保持原行序）；table = {学科: {期次: 值}}
    值单元格沿用该行原 B 列样式，斑马纹与边框不变。
    """
    import xlsx_io                                                # noqa: PLC0415

    with zipfile.ZipFile(ledger) as zf:
        member = xlsx_io.member_of(zf, sheetname)
        xml = zf.read(member).decode("utf-8")

    cols = [col_letter(2 + i) for i in range(len(periods))]

    def fix(mrow):
        rn = int(mrow.group(1))
        attrs_row = mrow.group(2)
        cells = {c: (a, i) for c, _r, a, i in CELL_RE.findall(mrow.group(3))}
        a_attr, a_inner = cells["A"]
        b_attr = cells["B"][0]                       # 该行值列样式（斑马纹）
        if a_inner is not None:
            head = f'<c r="A{rn}"{a_attr}>{a_inner}</c>'
        else:
            head = f'<c r="A{rn}"{a_attr}/>'
        if rn == 1:                                  # 表头行 → 期次号
            vals = list(periods)
        elif rn - 2 < len(order):                    # 数据行 → 按学科取值
            vals = [table[order[rn - 2]].get(p, "") for p in periods]
        else:
            return mrow.group(0)                     # 结构外的行，原样保留
        body = "".join(
            (f'<c r="{c}{rn}"{b_attr}><v>{v}</v></c>' if v not in (None, "")
             else f'<c r="{c}{rn}"{b_attr}/>')
            for c, v in zip(cols, vals))
        spans = re.sub(r'spans="1:\d+"', f'spans="1:{len(periods) + 1}"', attrs_row)
        return f'<row r="{rn}"{spans}>{head}{body}</row>'

    new_xml = ROW_RE.sub(fix, xml)
    last_col = col_letter(1 + len(periods))
    last_row = len(order) + 1
    new_xml = re.sub(r'<dimension ref="A1:[A-Z]+\d+"/>',
                     f'<dimension ref="A1:{last_col}{last_row}"/>', new_xml)
    if new_xml == xml:
        return False
    # 🔴 写盘前良构自检 + 其余成员逐字节，都在 `xlsx_io.rewrite`（2026-09-18 事故后加）。
    import xlsx_io                                                # noqa: PLC0415

    xlsx_io.rewrite(ledger, {member: new_xml})
    return True


def update_ledger(ledger, period, values):
    """把某期次的 22 学科 1‰ 值按时间序写回台账。→ (periods, is_new)"""
    periods, table = read_sheet_table(ledger)
    order = list(table.keys())
    for disc, v in values.items():                   # 冲突即拒绝，绝不悄悄覆盖
        old = table.get(disc, {}).get(str(period))
        if old not in (None, "") and _num(old) is not None and int(_num(old)) != int(v):
            raise SystemExit(f"[拒绝写入] {ledger.name} 中 {disc} @{period} 已有 {old}，"
                             f"与新算 {v} 不符；口径变化需人工确认后再改。")
    is_new = str(period) not in periods
    if is_new:
        periods = sorted(set(periods) | {str(period)})
    for disc, v in values.items():
        if disc in table:
            table[disc][str(period)] = int(v)
    rewrite_sheet(ledger, periods, order, table)
    return periods, is_new


def update_ledger_bulk(ledger, by_period, sheetname=SHEET):
    """一次写入**多期**：`by_period = {期次: {学科: 值}}`。

    与 `update_ledger` 同一道闸门：任何一处与台账现有值冲突即**整批拒写**并逐条列出，
    绝不悄悄改历史。返回 (新期次列表, 新增期次列表)。
    """
    periods, table = read_sheet_table(ledger, sheetname)
    order = list(table.keys())
    conflicts = []
    for per, values in by_period.items():
        for disc, v in values.items():
            old = table.get(disc, {}).get(str(per))
            if old not in (None, "") and _num(old) is not None and int(_num(old)) != int(v):
                conflicts.append((disc, str(per), int(_num(old)), int(v)))
    if conflicts:
        lines = "\n".join(f"    {d} @{p}: 台账 {o}  ≠  新算 {n}" for d, p, o, n in conflicts)
        raise SystemExit(f"[拒绝写入] {ledger.name} 有 {len(conflicts)} 处与现有值不符：\n{lines}")
    new_pers = sorted(set(periods) | {str(p) for p in by_period})
    for per, values in by_period.items():
        for disc, v in values.items():
            if disc in table:
                table[disc][str(per)] = int(v)
    rewrite_sheet(ledger, new_pers, order, table, sheetname)
    return new_pers, [p for p in new_pers if p not in periods]


def main():
    ap = argparse.ArgumentParser(description="抽取 ESI 1‰/1% 被引阈值（可写回台账）")
    ap.add_argument("period", help="期次，如 202601")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    ap.add_argument("--ledger", action="append", default=None,
                    help="要写回的台账（可多次）；默认两份已知台账")
    ap.add_argument("--write", action="store_true", help="写回台账（默认只打印）")
    args = ap.parse_args()

    res = extract_period(args.data_root, args.period)
    print(f"### {args.period} 1‰ / 1% 阈值（数据根：{pathlib.Path(args.data_root).name}）")
    print(f"{'学科':30s} {'m':>7s} {'rank':>6s} {'1‰阈值':>10s} {'1%阈值':>9s}")
    values = {}
    for disc, rec in res.items():
        if disc.startswith("__"):
            continue
        if "error" in rec:
            print(f"{disc:30s}  !! {rec['error']}")
            continue
        values[disc] = rec["t1pm"]
        print(f"{disc:30s} {rec['m']:>7d} {rec['rank_1pm']:>6d} {rec['t1pm']:>10,d} {rec['t1pct']:>9,d}")
    ov = res.get("__OVERALL__")
    if ov:
        print(f"{'[整体 Institutions]':30s} {ov['m']:>7d} {ov['rank_1pm']:>6d} "
              f"{ov['t1pm']:>10,d} {ov['t1pct']:>9,d}   ← 台账不存，仅参考")

    cc = crosscheck_t1pct(args.data_root, args.period, res)
    if cc:
        hit, miss, detail = cc
        print(f"\n口径体检：1% 阈值 vs ThresholdESI.INSTITUTION → 相符 {hit} / 不符 {miss}")
        for d in detail:
            print(f"   ✗ {d[0]}: 末位 {d[1]} vs {d[2]}")

    if not args.write:
        print("\n（dry-run。加 --write 写回台账）")
        return

    ledgers = [pathlib.Path(x) for x in (args.ledger or DEFAULT_LEDGERS)]
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for lg in ledgers:
        if not lg.exists():
            print(f"[跳过] 不存在：{lg}")
            continue
        bak = BACKUP_DIR / f"{lg.stem}.{args.period}.bak.xlsx"
        shutil.copy2(lg, bak)
        periods, n_new = update_ledger(lg, args.period, values)
        print(f"\n已写回 {lg}\n  备份 → {bak}\n  期次列现为 {periods}")
    print("完成。请重新运行 rerun_history.py 复现目标期次。")


if __name__ == "__main__":
    sys.exit(main())
