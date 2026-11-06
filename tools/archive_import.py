# -*- coding: utf-8 -*-
"""历史档案库导入器：`../数据与复现/` 的 ESI / InCites 历史原始包 → 档案库（ADR-0015）。

🔴 **对数据目录只读**：只 `stat` + 读字节算指纹 + openpyxl/csv 读内容，
   不改名、不移动、不删除、不写回（同 `sources_index.py` 纪律）。

设计要点（ADR-0015 / `src/archive_db.py`）：
- **全部登记**：每个文件先入 `files` 清单（指纹增量：size+mtime 没变沿用库里指纹），
  再按角色解析；锁文件 / 孪生件 / 派生件 / 文档类登记不解析，永不漏账。
- **主键是「期次+角色」不是文件名**：文件名跨 4 个命名时代漂移（大写残留、
  拼写错误 `178hilycited`、`COMPUTER SCIENC`、别名 6 种…），角色按文件名语义归类，
  学科按规范名归一（EN 精确 → 中文 → 前缀兜底治 `COMPUTER SCIENC`/`xxxlsx.xlsx`）。
- **InCites 列漂移**：表头字典并集（`incites_metrics` slug ↔ 原样表头）动态建列；
  最老 8 快照 219 件表头乱码按 `数据说明.txt` 老版列序**位置恢复**（`OLD_LAYOUT_*`，
  列数对得上才走，对不上整件进 `misc_rows` 兜底）。
- **孪生件只解析一份**：`excel/` 子目录 xlsx 孪生、202609 起 xlsx+csv 同形对——
  解析主件，孪生标 `skipped_duplicate`（原件在盘上，清单有指纹，不丢数据）。
- **确定性**：文件按 rel_path 排序处理 → files.id / slug 分配顺序 / 行序全部确定，
  同输入 → 同 `content_sha256`。

用法（wenheng/ 下）：
    uv run python tools\\archive_import.py --kind esi --scope 202607      # 小样（追加）
    uv run python tools\\archive_import.py --kind incites --scope 数据覆盖2016-2026.08.31
    uv run python tools\\archive_import.py --kind all --reset             # 全量重建
    uv run python tools\\archive_import.py --verify                       # 对账（纯读）
    uv run python tools\\archive_import.py --report                       # 覆盖报告（纯读）
"""
from __future__ import annotations

import argparse
import codecs
import csv
import datetime
import json
import pathlib
import re
import sys

# CSV 字段上限：Clarivate 导出里 Addresses / Authors 这类字段可达 130KB+，
# 超过 csv 模块默认 131072 上限会抛 `field larger than field limit`。
# 一次性抬高到系统上限（解析前无需逐文件判断；影响本进程内所有 csv 读取，符合预期）。
_csv_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_csv_limit)
        break
    except OverflowError:
        _csv_limit = int(_csv_limit // 10)

import openpyxl

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from src import archive_db as DB  # noqa: E402
import parse_ledger as PL  # noqa: E402  22 学科规范名唯一口径
import sources_index as SI  # noqa: E402  iter_files / sha256_file 复用

DATA_ROOT = REPO.parent / "数据与复现"
ESI_ROOT = DATA_ROOT / "ESI数据"
CORRUPT_MD = DATA_ROOT / "incites损坏文件清单_20260919.md"

SUBJECTS = list(PL.DISCIPLINES_EN)
#: EN 规范名 → 归一化键（小写、压空白；规范名里的 `/` 在文件名里写作空格，两种键都收）。
_SUBJ_NORM: dict[str, str] = {}
for _s_name in SUBJECTS:
    _n = DB.norm_label(_s_name).lower()
    _SUBJ_NORM[_n] = _s_name
    _SUBJ_NORM[_n.replace("/", " ")] = _s_name
#: 中文名 → EN（治 `云大化学.xlsx` 这类中文名学科件）。
_SUBJ_CN_NORM: dict[str, str] = {}
for _en, _cn in PL.DISCIPLINES_CN.items():
    _n = DB.norm_label(_cn).lower()
    _SUBJ_CN_NORM[_n] = _en
    _SUBJ_CN_NORM[_n.replace("/", " ")] = _en

PERIOD_RE = re.compile(r"^\d{6}$")

#: 角色（受控词表，进 files.role）。
R_SUBJECT = "学科表"
R_YNU_SUBJECT = "云大学科表"
R_INST = "机构榜"
R_INST_G = "全球机构榜"
R_ORG_TYPE = "机构属性"
R_THRESHOLD = "阈值"
R_BASELINE = "基线"
R_PAPERS = "论文清单"
R_RESEARCH = "研究领域"
R_META = "元数据"
R_RENAME = "改名记录"
R_MASTER = "总表模板"
R_DERIVED = "派生件"
R_LOCK = "锁文件"
R_DOC = "文档"
R_ZIP = "档案zip"
R_MISC = "散件"
R_LEDGER = "监测表母本"

#: 解析状态（受控词表，进 files.parse_status）。
ST_PARSED = "parsed"                  # 专属表已解析
ST_RECOVERED = "recovered"            # 乱码表头按老版列序位置恢复（专属表）
ST_STASHED = "stashed"                # 无专属解析器 / 表头未识别，整件 misc_rows 原样
ST_CORRUPTED = "corrupted"            # 表头乱码且列序对不上，misc_rows 兜底
ST_EMPTY = "empty"                    # 无内容（锁文件 / 纯元数据）
ST_DUP = "skipped_duplicate"          # 孪生件 / zip 重复件（原件在盘、清单有指纹）
ST_DERIVED = "derived_no_parse"       # 派生件 / 母本 / 文档，只登记
ST_FAILED = "failed"


# ------------------------------------------------------------------ 老版列序（位置恢复）
# 依据（小样阶段已实测核对，2026-11-04）：
# · `数据说明.txt` §1/§3/§4 的列目顺序，经 `云南高校发文概况.xlsx`（59 列，表头 mojibake
#   可完全反转）与 `云大esi22学科总体.xlsx`（39 列）逐列核对一致；
# · 「名称,排名」在最前（不是「排名,名称」）；59 列里「ESI 引文影响力排名」在该世代
#   实为 YES/NO 在榜标记——标签照存、数值保真，语义备注进 incites_metrics.note。
_OLD_GLOBAL_METRICS = [
    "Web of Science 论文数", "学科规范化的引文影响力", "被引频次", "论文被引百分比",
    "ESI 引文影响力排名", "JIF 期刊中的论文",
    "Q1 期刊中的论文", "Q1 期刊中论文的百分比", "Q2 期刊中的论文", "Q2 期刊中论文的百分比",
    "Q3 期刊中的论文", "Q3 期刊中论文的百分比", "Q4 期刊中的论文", "Q4 期刊中论文的百分比",
    "热门论文百分比", "被引次数排名前 1% 的论文百分比", "被引次数排名前 10% 的论文百分比",
    "高被引论文", "高被引论文百分比", "h 指数", "平均百分位", "引文影响力",
    "期刊规范化的引文影响力", "某年发表文献对发表前所有年份的累计施引频次",
    "相对于全球平均水平的影响力", "被引用过的论文数",
    "国际合作论文", "国际合作论文百分比", "横向合作论文百分比", "国际合作论文/论文",
    "% DOAJ 金色文档", "% 其他金色文档", "% 所有开放存取文档", "% 绿色已出版文档",
    "% 绿色已录用文档", "% 铜色文档",
    "论文/教学和科研人员 - 规范化", "科研声誉 - 全球", "研究收入/教学人员 - 规范化",
    "横向研究收入/教学人员", "机构收入/教学人员", "教学声誉 - 全球", "教学人员/学生",
    "学科规范化的引文影响力-国家规范化", "国际教学人员/教学人员", "国际学生/学生",
    "博士学位/教学人员 - 规范化", "博士学位/本科学位",
    "DOAJ 金色文档", "其他金色文档", "所有开放存取文档", "绿色已出版文档",
    "绿色已录用文档", "铜色文档",
    "国家/地区", "机构类型", "省/直辖市/自治区",
]
_OLD_YNU_METRICS = [
    "Web of Science 论文数", "学科规范化的引文影响力", "被引频次", "论文被引百分比",
    "JIF 期刊中的论文",
    "Q1 期刊中的论文", "Q1 期刊中论文的百分比", "Q2 期刊中的论文", "Q2 期刊中论文的百分比",
    "Q3 期刊中的论文", "Q3 期刊中论文的百分比", "Q4 期刊中的论文", "Q4 期刊中论文的百分比",
    "热门论文百分比", "被引次数排名前 1% 的论文百分比", "被引次数排名前 10% 的论文百分比",
    "高被引论文", "高被引论文百分比", "平均百分位", "引文影响力", "期刊规范化的引文影响力",
    "相对于全球平均水平的影响力",
    "国际合作论文", "国际合作论文百分比", "横向合作论文百分比",
    "% DOAJ 金色文档", "% 其他金色文档", "% 所有开放存取文档", "% 绿色已出版文档",
    "% 绿色已录用文档", "% 铜色文档",
    "DOAJ 金色文档", "其他金色文档", "所有开放存取文档", "绿色已出版文档",
    "绿色已录用文档", "铜色文档",
]
#: 完整列序（名称 + 排名 + 指标列；已按实盘核对）。
OLD_LAYOUT_GLOBAL = ["名称", "排名"] + _OLD_GLOBAL_METRICS
OLD_LAYOUT_YNU = ["名称", "排名"] + _OLD_YNU_METRICS
#: 云大论文清单 20 列（2009-2019 世代 `云大<学科>.xlsx` 实测）：3 个检索号列 + 数据说明 §4 的 17 列。
OLD_LAYOUT_PAPERS = ["WOS收录号", "DOI", "MEDLINE收录号"] + [
    "论文标题", "作者", "来源", "学科领域", "文献类型", "卷", "期", "页", "出版年",
    "被引频次", "网址", "期刊预期被引频次", "类别预期被引频次", "期刊规范化的引文影响力",
    "学科规范化的引文影响力", "学科领域百分位", "期刊影响因子",
]


# ------------------------------------------------------------------ 基础读
def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _int(n):
    return int(n) if n is not None else None


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def read_xlsx_rows(path: pathlib.Path, *, read_only: bool) -> list[list]:
    """首个 sheet 全行（ESI 导出 dimension 常坏 → ESI 侧用普通模式；InCites 大表用 read_only）。"""
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=read_only)
    try:
        ws = wb[wb.sheetnames[0]]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def read_xlsx_all_sheets(path: pathlib.Path) -> dict[str, list[list]]:
    """全部 sheet 全行（misc 兜底用）。"""
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    try:
        return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)]
                for ws in wb.worksheets}
    finally:
        wb.close()


def _is_desc_line(row) -> bool:
    """说明行识别：Clarivate 导出首行 `Documents Result List: ...`（单格说明，非表头）。

    与 ESI 包「表头前 5 个空行」是两套形态——空行 `_find_header` 会自动跳过，
    但这条是**非空**说明行，必须按字符串单独识别、显式跳过，不能再复用表头查找逻辑。
    """
    text = " ".join(_s(c) for c in row).strip()
    return text.lower().startswith("documents result list")


#: CSV 解码兜底 handler：UTF-8 文件里偶有孤立的 cp1252/latin-1 控制字节（0x80–0x9F，
#: UTF-8 与 cp1252 均无法 strict 解），把每个坏字节按 latin-1 逐字节映射。
#: 确定性、无损（字节↔码点 1:1），**不是** `errors="replace"`（后者会把坏字节吞成 U+FFFD、
#: 污染 content_sha256 指纹且不可逆）。仅作用于 UTF-8 解不开的单字节，主体中文仍是 UTF-8。
def _utf8_latin1(exc):
    if isinstance(exc, UnicodeDecodeError):
        return "".join(bytes([b]).decode("latin-1") for b in exc.object[exc.start:exc.end]), exc.end
    raise exc


codecs.register_error("utf8_latin1", _utf8_latin1)


def read_csv_rows(path: pathlib.Path) -> list[list[str]]:
    """CSV 全行（utf-8-sig → gb18030 → cp1252 兜底；首行是说明行则跳过）。

    🔴 识别失败即抛，**不许** `errors="replace"` 静默吞坏字节——
    坏字节会污染 `files.content_sha256` 指纹，让确定性对账失效。

    编码顺序（实测优先级）：
      · utf-8-sig          —— 现代导出默认；
      · gb18030            —— 老中文导出；
      · cp1252（＝ latin-1 单字节西欧）—— 部分老导出是单字节西欧编码，
        实测 `原始导出_学院顶尖论文清单.csv` utf-8-sig 在 pos 2886、gb18030 在 pos 5193
        失败，cp1252 / latin-1 才可完整解码。

    首行说明行（`Documents Result List: ...`）非表头，解析前丢弃，
    第 2 行才是真正的 12 列表头（交给 `_find_header` 校验）。

    字段上限已在模块载入时抬高（`csv.field_size_limit` 系统上限）：
    Clarivate 导出的 Addresses / Authors 字段可达 130KB+，超过默认 131072 会抛错。
    """
    rows: list[list[str]] | None = None
    for enc in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            with open(path, newline="", encoding=enc) as fh:
                rows = [list(r) for r in csv.reader(fh)]
            break
        except UnicodeDecodeError:
            continue
    if rows is None:
        # 最后兜底：主体 UTF-8、偶有孤立 cp1252/latin-1 控制字节（实测
        # `201905/Web Of Science 论文数植物动物学2009-2019.csv`：UTF-8 中文 + 0x8d/0x8f/0x90/0x9d
        # 这类字节 UTF-8/cp1252 都 strict 解不开）→ 用 utf8_latin1 handler 逐字节保真，不丢字节。
        try:
            with open(path, newline="", encoding="utf-8", errors="utf8_latin1") as fh:
                rows = [list(r) for r in csv.reader(fh)]
        except UnicodeDecodeError:
            raise ValueError(
                f"CSV 编码识别失败（utf-8-sig/gb18030/cp1252/utf-8-latin1 均失败）：{path.name}")
    # 跳过首行说明行（"Documents Result List: ..."），第 2 行才是真正表头。
    if rows and _is_desc_line(rows[0]):
        rows = rows[1:]
    return rows


def read_rows_any(path: pathlib.Path, *, read_only: bool) -> list[list]:
    if path.suffix.lower() == ".csv":
        return [list(r) for r in read_csv_rows(path)]
    return read_xlsx_rows(path, read_only=read_only)


def _raw_json(row) -> str:
    return json.dumps([_s(c) for c in row], ensure_ascii=False)


def _is_garbled(cells) -> bool:
    """表头乱码检测：0x3F 顶字节在单元格里表现为问号（mojibake 反转后仍残留 '?'）。"""
    return any("?" in _fix_mojibake(c) for c in cells)


def _fix_mojibake(v) -> str:
    """老世代表头是 UTF-8 字节被按 GBK 误读的 mojibake（`名称`→`鍚嶇О`）。

    能往返的（字节未丢）反转回中文；丢过字节（0x3F）的反转不了，原样返回——
    剩余 '?' 由 `_is_garbled` 捕获，走位置恢复。数据行是干净的，不受影响。
    """
    s = _s(v)
    if not s:
        return s
    for attempt in (s, s.replace("?", "")):
        try:
            fixed = attempt.encode("gbk").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed:
            return fixed
    return s


# ------------------------------------------------------------------ 学科名归一
def match_subject(stem: str) -> str | None:
    """文件名 stem → 22 学科规范名（EN 精确 → 中文 → 前缀兜底治脏写法）。"""
    n = DB.norm_label(stem).lower()
    if n in _SUBJ_NORM:
        return _SUBJ_NORM[n]
    if n in _SUBJ_CN_NORM:
        return _SUBJ_CN_NORM[n]
    for key, en in _SUBJ_NORM.items():
        if key.startswith(n) or n.startswith(key):
            return en
    return None


def _parse_period(text: str) -> str:
    """从文件名/目录名里提期次（202609论文清单.xlsx → 202609）；提不到给空串。"""
    m = re.search(r"\b(20\d{4})\b", text)
    return m.group(1) if m else ""


# ------------------------------------------------------------------ 角色分类
def _kind_by_name(stem_l: str) -> str | None:
    """阈值/基线/论文清单三族的 kind 值（按文件名语义，不按精确名）。"""
    if "threshold" in stem_l:
        if "highly" in stem_l:
            return "highly_cited"
        if "hot" in stem_l:
            return "hot"
        return "esi_1pct"
    if "baseline" in stem_l or "citation rate" in stem_l or "field ranking" in stem_l \
            or "percentile" in stem_l:
        if "field" in stem_l:
            return "field_rankings"
        if "percentile" in stem_l:
            return "percentiles"
        return "citation_rates"
    if "highly" in stem_l or "hily" in stem_l:
        return "highly_cited"
    if "hot" in stem_l:
        return "hot"
    if "top" in stem_l:
        return "top"
    return None


def _research_scope(stem_l: str, name: str) -> str | None:
    """研究领域件 → scope（global/china/ynu）；非研究领域件返回 None。

    ⚠ 排除总体/概况类（`云大esi22学科总体` 也含「学科」二字，但不是研究领域表）。
    """
    if "总体" in name or "概况" in name:
        return None
    if "研究领域" not in name and "research field" not in stem_l \
            and "research area" not in stem_l \
            and "researchfields" not in stem_l.replace(" ", "") and "学科" not in name:
        return None
    if "云大" in name or "yunnan" in stem_l or stem_l.startswith("ynu"):
        return "ynu"
    if "中国" in name or "china" in stem_l:
        return "china"
    if "全球" in name or "global" in stem_l or "国际" in name:
        return "global"
    return None


def classify_esi(scope: str, rel_under: str, name: str) -> tuple[str, str]:
    """ESI 件 → (role, kind_or_note)。`rel_under` 是 scope 下的相对路径。"""
    p = pathlib.Path(rel_under)
    stem_l = DB.norm_label(p.stem).lower()
    suffix = p.suffix.lower()
    if name.startswith("~$"):
        return R_LOCK, ""
    if suffix in (".pdf", ".doc", ".docx", ".md", ".txt"):
        return R_DOC, ""
    if suffix == ".json":
        return (R_META, "") if "下载信息" in name else (R_RENAME, "")
    if scope == "_归档统一命名":
        return R_DERIVED, ""
    if suffix not in (".xlsx", ".xls", ".csv"):
        return R_DERIVED, suffix  # 非数据件（压缩包/配置等），只登记、不解析也不 stash
    if "总表" in name:
        return R_MASTER, ""
    if p.parent != pathlib.Path("."):
        if suffix not in (".xlsx", ".xls", ".csv"):
            return R_DERIVED, f"非数据子目录件（{suffix}）"
        return R_MISC, "子目录件（他校数据/杂件）"
    if stem_l == "institutions":
        return R_INST, ""
    if stem_l in ("world institutions", "全球机构"):
        return R_INST_G, ""
    if "机构类型" in name or "organization type" in stem_l:
        return R_ORG_TYPE, ""
    if match_subject(p.stem):
        return R_SUBJECT, match_subject(p.stem) or ""
    kind = _kind_by_name(stem_l)
    if kind in ("esi_1pct", "highly_cited", "hot") and "threshold" in stem_l:
        return R_THRESHOLD, kind
    if kind in ("citation_rates", "field_rankings", "percentiles"):
        return R_BASELINE, kind
    if kind in ("top", "highly_cited", "hot"):
        return R_PAPERS, kind
    if "yunnan university" in stem_l:      # 机构档案（云大列后备源，与云大学科同形）
        return R_RESEARCH, "ynu"
    scope_f = _research_scope(stem_l, name)
    if scope_f:
        return R_RESEARCH, scope_f
    return R_MISC, ""


def classify_incites(scope: str, rel_under: str, name: str) -> tuple[str, str]:
    """InCites 快照件 → (role, kind_or_note)。

    ⚠ `云大<学科>.xlsx`（2009-2019 世代）实测是**云大该学科论文清单**（20 列，
    数据说明 §4），不是学科机构榜——归论文清单；`云大esi22学科总体` 才是 39 列学科总表。
    """
    p = pathlib.Path(rel_under)
    stem_l = DB.norm_label(p.stem).lower()
    suffix = p.suffix.lower()
    if name.startswith("~$"):
        return R_LOCK, ""
    if suffix == ".zip":
        return R_ZIP, ""
    if suffix in (".pdf", ".doc", ".docx", ".md", ".txt"):
        return R_DOC, ""
    if suffix == ".json":
        return R_RENAME, ""
    if suffix not in (".xlsx", ".xls", ".csv"):
        return R_DERIVED, suffix  # 非数据件（压缩包/配置等），只登记、不解析也不 stash
    scope_f = _research_scope(stem_l, name)
    if scope_f:
        return R_RESEARCH, scope_f
    if "机构排名" in name or "组织机构" in name or "global 机构" in stem_l:
        return R_INST_G, ""
    if "论文" in name or re.fullmatch(r"wos\d+", stem_l):
        return R_PAPERS, "云大论文"
    if stem_l.startswith("云大") or "yunnan university" in stem_l:
        if "总体" in name or "esi22" in stem_l:
            return R_YNU_SUBJECT, "云大22学科总体"
        subj = match_subject(stem_l.replace("云大", "", 1))
        if subj:
            return R_PAPERS, subj          # 云大<学科>.xlsx = 该学科论文清单
    subj = match_subject(p.stem)
    if subj:
        return R_SUBJECT, subj
    return R_MISC, ""


def classify_misc(scope: str, rel_under: str, name: str) -> tuple[str, str]:
    """`数据与复现/` 根散件与 论文清单/ → (role, kind_or_note)。"""
    p = pathlib.Path(rel_under)
    suffix = p.suffix.lower()
    if suffix in (".md", ".txt", ".docx", ".pdf"):
        return R_DOC, ""
    if "动态检测表" in name:
        return R_LEDGER, ""
    if p.parts[0] == "论文清单" and suffix in (".xlsx", ".csv"):
        return R_PAPERS, "school_list"
    return R_MISC, ""


# ------------------------------------------------------------------ 解析：ESI 侧
def _find_header(rows, *keys, max_scan: int = 12, mode: str = "all"):
    """前 max_scan 行里找表头行：返回 (行号, 标签列表)。

    mode="all"：keys 全部命中才算；mode="any"：任一命中即算（论文清单表头
    各世代叫法不同——Article Name / 论文标题 / Times Cited / 被引频次…）。

    🔴 防静默失效：候选行必须 **≥ 2 个非空单元格**才可能是多列表头。Clarivate 导出
    常在表头前塞一行「Documents / Indicators Results List: …」段落说明——只有一个超长
    单元格、里面嵌着 'Institutions' 等词，子串匹配会误命中它 → h 坐标系错位、整表废数据
    被标 parsed（202607 Chemistry 实测：这段说明行仅 1 个非空单元格，真实表头有 ≥5）。
    """
    for i, r in enumerate(rows[:max_scan]):
        h = [_s(c) for c in r]
        if sum(1 for x in h if x) < 2:          # 段落说明行 / 空行：不可能是多列表头
            continue
        if mode == "any":
            if any(k.lower() in x.lower() for k in keys for x in h if x):
                return i, h
            continue
        for k in keys:
            if not any(k.lower() in x.lower() for x in h if x):
                break
        else:
            return i, h
    return None, None


def _esi_cols(h):
    """ESI 榜表头 → 各 canonical 列号（找不到给 None；旧 9/7 列版式天然缺列）。

    🔴 修复静默失效：
      · 'inst' / 'cites' 用**精确单元格匹配优先**，修掉 `or` 对下标 0 的 falsy 陷阱——
        'Indicators Results List: Institutions …' 段落行里 'institutions' 子串命中列 0，
        原 `idx(..., exact=True) or idx(...)` 在精确命中列 0 时会因 `0 or …` 丢掉列 0；
      · 'rank' 当第 0 列为空表头时显式认作排名列（202607 英文版式：第 0 列空表头存排名）。
    """
    def idx(*keys, exact=False):
        for j, x in enumerate(h):
            if exact and x == keys[0]:
                return j
            if not exact and any(k.lower() in x.lower() for k in keys):
                return j
        return None

    def idx_cell(*keys):
        """精确单元格匹配（大小写不敏感）：'Institutions' 必须是独立单元格，
        不被 'Indicators Results List: Institutions' 段落行吞掉。"""
        for j, x in enumerate(h):
            xl = x.lower()
            if xl and any(k.lower() == xl for k in keys):
                return j
        return None

    def group(*keys):
        """同族多列（Top Papers / Top Papers % …）：无 % 的第一个=计数，含 %=百分比。"""
        cnt = pct = None
        for j, x in enumerate(h):
            if all(k.lower() in x.lower() for k in keys):
                if "%" in x or "percent" in x.lower():
                    pct = pct if pct is not None else j
                else:
                    cnt = cnt if cnt is not None else j
        return cnt, pct

    top_c, top_p = group("Top Papers")
    hc_c, hc_p = group("Highly Cited")
    hot_c, hot_p = group("Hot Papers")
    # 排名列：中文/英文精确优先；否则「第 0 列空表头」视为排名（202607 英文版式）。
    rank = idx_cell("序号", "Rank", "排名")
    if rank is None and h and not h[0].strip():
        rank = 0
    # 机构列：精确单元格优先（修掉 `or` 对下标 0 的 falsy 陷阱），再退回原单键子串匹配。
    inst_cell = idx_cell("Institutions", "机构", "Institution")
    inst = inst_cell if inst_cell is not None else idx("Institutions")
    # 引文数：同理修 trap。
    cites_cell = idx_cell("Cites", "Citations", "被引")
    cites = cites_cell if cites_cell is not None else idx("Cites")
    return {
        "rank": rank,
        "inst": inst,
        "country": idx("Countr", "国家", "Country"),
        "documents": idx("Document", "文献", "Docum"),
        "cites": cites,
        "cpp": idx("Cites/Paper", "篇均", "Cites per Paper"),
        "top": top_c, "top_pct": top_p, "hc": hc_c, "hc_pct": hc_p,
        "hot": hot_c, "hot_pct": hot_p,
    }


def _data_rows(rows, hi: int, start: int | None = None):
    """数据行：从 start（默认表头下一行）起，跳过 copyright / InCites footer 行与全空行。"""
    begin = hi + 1 if start is None else start
    for i, r in enumerate(rows[begin:], start=begin):
        head = " ".join(str(c).lower() for c in r[:3] if c is not None)
        if "copyright" in head or "incites dataset" in head:
            break
        if r and any(_s(c) for c in r):
            yield i, r


def parse_esi_subject(conn, path, file_id, period, discipline):
    """ESI 学科机构榜 → esi_discipline_rank（15 列 canonical；旧 9/7 列版式缺列 NULL）。"""
    rows = read_rows_any(path, read_only=False)
    hi, h = _find_header(rows, "Institutions")
    if hi is None:
        raise ValueError("未识别 ESI 学科表表头（没有 Institutions 列）")
    c = _esi_cols(h)
    out = []
    seq = 0
    for i, r in _data_rows(rows, hi):
        inst = _s(r[c["inst"]]) if c["inst"] is not None and c["inst"] < len(r) else ""
        if not inst:
            continue
        rank = None
        if c["rank"] is not None and c["rank"] < len(r):
            rank = _int(_num(r[c["rank"]]))
        if rank is None and len(r) > 0:
            rank = _int(_num(r[0]))
        if rank is None:
            seq += 1
            rank = seq
        else:
            seq = rank
        out.append((period, discipline, rank, inst.upper(),
                    _s(r[c["country"]]).upper() if c["country"] is not None and c["country"] < len(r) else "",
                    _int(_num(r[c["documents"]])) if c["documents"] is not None and c["documents"] < len(r) else None,
                    _int(_num(r[c["cites"]])) if c["cites"] is not None and c["cites"] < len(r) else None,
                    _num(r[c["cpp"]]) if c["cpp"] is not None and c["cpp"] < len(r) else None,
                    _int(_num(r[c["top"]])) if c["top"] is not None and c["top"] < len(r) else None,
                    _num(r[c["top_pct"]]) if c["top_pct"] is not None and c["top_pct"] < len(r) else None,
                    _int(_num(r[c["hc"]])) if c["hc"] is not None and c["hc"] < len(r) else None,
                    _num(r[c["hc_pct"]]) if c["hc_pct"] is not None and c["hc_pct"] < len(r) else None,
                    _int(_num(r[c["hot"]])) if c["hot"] is not None and c["hot"] < len(r) else None,
                    _num(r[c["hot_pct"]]) if c["hot_pct"] is not None and c["hot_pct"] < len(r) else None,
                    file_id, i))
    cols = ["period", "discipline", "rank_no", "institution", "country", "documents",
            "cites", "cites_per_paper", "top_papers", "top_pct", "highly_cited",
            "highly_cited_pct", "hot_papers", "hot_pct", "file_id", "row_no"]
    DB.insert_rows(conn, "esi_discipline_rank", cols, out)
    return len(out)


def parse_esi_institutions(conn, path, file_id, period):
    """机构榜（EN 或中文表头都行）→ esi_institutions 全行。"""
    rows = read_rows_any(path, read_only=False)
    hi, h = _find_header(rows, "Institutions")
    if hi is not None:
        c = _esi_cols(h)
        ic, cc, nc = c["rank"], c["country"], c["inst"]
    else:
        hi, h = _find_header(rows, "名称", "Name", max_scan=15)
        if hi is None:
            raise ValueError("未识别机构榜表头")
        ic = next((j for j, x in enumerate(h) if x == "排名"), None)
        nc = next((j for j, x in enumerate(h) if x in ("名称", "Name")), None)
        cc = next((j for j, x in enumerate(h) if "国家" in x or "Countr" in x), None)
    out = []
    seq = 0
    for i, r in _data_rows(rows, hi):
        name = _s(r[nc]) if nc is not None and nc < len(r) else ""
        if not name:
            continue
        n = _num(r[ic]) if ic is not None and ic < len(r) else None
        seq = int(n) if n and n > 0 else seq + 1
        out.append((period, seq, name.upper(),
                    _s(r[cc]).upper() if cc is not None and cc < len(r) else "", file_id, i))
    DB.insert_rows(conn, "esi_institutions",
                   ["period", "seq", "institution", "country", "file_id", "row_no"], out)
    return len(out)


def parse_thresholds(conn, path, file_id, period, kind):
    """阈值表（RESEARCH FIELDS / 值 两列）→ esi_thresholds。"""
    rows = read_rows_any(path, read_only=False)
    hi, _h = _find_header(rows, "RESEARCH FIELDS", max_scan=6)
    start = hi + 1 if hi is not None else 0
    out = []
    for i, r in enumerate(rows[start:], start=start):
        if not r or not _s(r[0]) or "copyright" in str(r[0]).lower():
            continue
        v = _num(r[1]) if len(r) > 1 else None
        if v is None:
            continue
        out.append((period, kind, DB.norm_label(r[0]), v, file_id, i))
    if not out:
        raise ValueError("阈值表没有可解析行")
    DB.insert_rows(conn, "esi_thresholds",
                   ["period", "kind", "discipline", "value", "file_id", "row_no"], out)
    return len(out)


def parse_baselines(conn, path, file_id, period, kind):
    """基线表（宽表 → 长）：discipline × col_label × value。"""
    rows = read_rows_any(path, read_only=False)
    hi, h = _find_header(rows, "RESEARCH FIELDS", max_scan=8)
    if hi is None:
        raise ValueError("基线表未识别表头（RESEARCH FIELDS）")
    labels = [DB.norm_label(x) for x in h]
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 1):
        if not r or not _s(r[0]) or "copyright" in str(r[0]).lower():
            continue
        disc = DB.norm_label(r[0])
        for j in range(1, min(len(r), len(labels))):
            if not labels[j]:
                continue
            v = _num(r[j])
            if v is not None:
                out.append((period, kind, disc, labels[j], v, file_id, i))
    DB.insert_rows(conn, "esi_baselines",
                   ["period", "kind", "discipline", "col_label", "value", "file_id", "row_no"],
                   out)
    return len(out)


def parse_papers(conn, path, file_id, period, kind):
    """论文清单（中英列头都行）→ esi_papers canonical + raw_json 兜底。"""
    rows = read_rows_any(path, read_only=path.suffix.lower() != ".csv")
    hi, h = _find_header(rows, "Publication Date", "论文标题", "Times Cited", "被引频次",
                         "Article Name", max_scan=14, mode="any")
    if hi is None:
        raise ValueError("论文清单未识别表头")
    low = [x.lower() for x in h]

    def col(*keys):
        for j, x in enumerate(low):
            if all(k.lower() in x for k in keys):
                return j
        return None

    ti = col("article name") or col("title") or col("论文标题")
    ai = col("author") or col("作者")
    si = col("source") or col("来源")
    yi = col("publication year") or col("出版年")
    di = col("publication date") or col("出版日期")
    ci = col("times cited") or col("被引频次")
    di_f = col("research field") or col("学科")
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 1):
        if not r or not any(_s(c) for c in r):
            continue
        if any(c and "copyright" in str(c).lower() for c in r[:2]):
            break
        pub = _s(r[di]) if di is not None and di < len(r) else ""
        year = _int(_num(r[yi])) if yi is not None and yi < len(r) else None
        if year is None and pub:
            m = re.match(r"(\d{4})", pub)
            year = int(m.group(1)) if m else None
        out.append((period, kind,
                    _s(r[ti]) if ti is not None and ti < len(r) else "",
                    _s(r[ai]) if ai is not None and ai < len(r) else "",
                    _s(r[si]) if si is not None and si < len(r) else "",
                    year, pub,
                    _int(_num(r[ci])) if ci is not None and ci < len(r) else None,
                    _s(r[di_f]) if di_f is not None and di_f < len(r) else "",
                    _raw_json(r), file_id, i))
    DB.insert_rows(conn, "esi_papers",
                   ["period", "kind", "title", "authors", "source", "pub_year", "pub_date",
                    "times_cited", "discipline", "raw_json", "file_id", "row_no"], out)
    return len(out)


def parse_research_fields(conn, path, file_id, period, scope):
    """研究领域表（Research Fields + Cites/Paper + Q1–Q4%）→ esi_research_fields。"""
    rows = read_rows_any(path, read_only=path.suffix.lower() != ".csv")
    hi, h = _find_header(rows, "Research Fields", max_scan=8)
    if hi is None:
        raise ValueError("研究领域表未识别表头")
    di = next(j for j, x in enumerate(h) if "research field" in x.lower())
    cpp = next((j for j, x in enumerate(h) if "cites/paper" in x.lower()), None)
    q = {}
    for j, x in enumerate(h):
        m = re.match(r"Q([1-4])\b", x.strip().upper())
        if m:
            q.setdefault(int(m.group(1)), j)
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 1):
        if not r or not _s(r[di]) or "copyright" in str(r[0]).lower():
            continue

        def qv(n):
            j = q.get(n)
            return _num(r[j]) if j is not None and j < len(r) else None

        out.append((period, scope, _s(r[di]),
                    _num(r[cpp]) if cpp is not None and cpp < len(r) else None,
                    qv(1), qv(2), qv(3), qv(4), _raw_json(r), file_id, i))
    DB.insert_rows(conn, "esi_research_fields",
                   ["period", "scope", "discipline", "cites_per_paper", "q1", "q2", "q3", "q4",
                    "raw_json", "file_id", "row_no"], out)
    return len(out)


def parse_download_meta(conn, path, period):
    """`_下载信息.json` → periods.download_meta（原文）。"""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    conn.execute("INSERT INTO periods(period, download_meta) VALUES(?,?)"
                 " ON CONFLICT(period) DO UPDATE SET download_meta=excluded.download_meta",
                 (period, text))
    return 1


# ------------------------------------------------------------------ 解析：InCites 侧
def _incites_header(rows):
    """快照机构榜表头：返回 (行号, 标签, 是否乱码)。

    判据：前 15 行里第一行「≥4 个非空文本列 且 含 名称/Name/论文数/被引频次」。
    老世代表头是 GBK mojibake——先反转再判（能反转全的不算乱码，直接用反转后的标签）。
    """
    for i, r in enumerate(rows[:15]):
        h = [_fix_mojibake(c) for c in r]
        nonempty = [x for x in h if x]
        if len(nonempty) < 4:
            continue
        texty = sum(1 for x in nonempty if _num(x) is None)
        if texty >= 3 and any(x in ("名称", "Name") or "论文数" in x or "被引频次" in x
                              for x in nonempty):
            return i, h, _is_garbled(r)
    return None, None, False


_IDENTITY = (
    ("rank_no", ("排名", "Rank")),
    ("institution", ("名称", "Name", "Institutions")),
    ("country", ("国家/地区", "国家或地区", "Countries")),
    ("org_type", ("机构类型", "Organization Type")),
    ("province", ("省/直辖市/自治区", "Province")),
)


def _identity_cols(labels):
    """标签列表 → 身份列号（rank 只认全等，其余子串）。"""
    out = {}
    for name, keys in _IDENTITY:
        for j, x in enumerate(labels):
            nx = DB.norm_label(x)
            if name == "rank_no":
                if nx.lower() in ("排名", "rank"):
                    out[name] = j
                    break
            elif any(k == nx or k in nx for k in keys):
                out[name] = j
                break
    return out


def _first_data_row(rows) -> int:
    """位置恢复时的数据起始行：首个含数字单元格的行（表头行全文本）。"""
    for i, r in enumerate(rows[:20]):
        if any(_num(c) is not None for c in r if _s(c)):
            return i
    return 1


def parse_subject_rows(conn, path, file_id, snapshot, discipline, *, ynu: bool):
    """快照学科机构榜 → incites_subject_rows（表头字典并集；乱码走位置恢复）。

    返回 (行数, status, note)。
    """
    rows = read_rows_any(path, read_only=path.suffix.lower() != ".csv")
    hi, labels, garbled = _incites_header(rows)
    layout = OLD_LAYOUT_YNU if ynu else OLD_LAYOUT_GLOBAL
    note = ""
    start = None
    if hi is None or garbled:
        # 表头不可信（mojibake 反转不全 / 合并损毁）：列数对得上老版列序 → 位置恢复；
        # 对不上 → 整件 misc 兜底
        width = max((len(r) for r in rows if r), default=0)
        if width == len(layout):
            labels = layout
            hi = _first_data_row(rows)
            start = hi
            note = "表头乱码，按数据说明.txt 老版列序位置恢复（列序经云南高校发文概况.xlsx 实测核对）"
        else:
            n = stash_misc(conn, path, file_id)
            return n, ST_CORRUPTED, f"表头乱码且列数 {width}≠{len(layout)}，整件 misc_rows"
    idc = _identity_cols(labels)
    slug_by_col: dict[int, str] = {}
    for j, x in enumerate(labels):
        if not x or j in idc.values():
            continue
        slug_by_col[j] = DB.metric_slug(conn, x)
    base = ["snapshot", "discipline", "rank_no", "institution", "country", "org_type",
            "province", "file_id", "row_no"]
    slugs = sorted(set(slug_by_col.values()))
    cols = base + slugs
    out = []
    for i, r in _data_rows(rows, hi, start=start):
        get = {}
        for name, _keys in _IDENTITY:
            j = idc.get(name)
            v = _s(r[j]) if j is not None and j < len(r) else ""
            if name == "rank_no":
                get[name] = _int(_num(v))
            else:
                get[name] = v.upper()
        mvals = {s: None for s in slugs}
        for j, slug in slug_by_col.items():
            if j < len(r):
                mvals[slug] = _num(r[j])
        # 数据块结束护栏：Filter Summary / Exported Date 等脚注行——无排名、全无数值、
        # 非空格 ≤2（全 n/a 的数据行有大量非空格，不会误杀）
        if get["rank_no"] is None and all(v is None for v in mvals.values()) \
                and sum(1 for c in r if _s(c)) <= 2:
            break
        out.append((snapshot, discipline, get["rank_no"], get["institution"],
                    get["country"], get["org_type"], get["province"], file_id, i)
                   + tuple(mvals[s] for s in slugs))
    DB.ensure_subject_columns(conn, slugs)
    DB.insert_rows(conn, "incites_subject_rows", cols, out)
    return len(out), (ST_RECOVERED if note else ST_PARSED), note


def parse_incites_research(conn, path, file_id, snapshot, scope):
    """研究领域/趋势表（Q1–Q4% 列）→ incites_research_fields；表头不识 → misc 兜底。"""
    rows = read_rows_any(path, read_only=path.suffix.lower() != ".csv")
    hi = None
    for i, r in enumerate(rows[:10]):
        cells = [_s(c) for c in r]
        if sum(1 for x in cells if re.match(r"Q[1-4]", x.strip().upper())) >= 2:
            hi = i
            break
    if hi is None:
        n = stash_misc(conn, path, file_id)
        return n, ST_STASHED, "研究领域表头未识别，整件 misc_rows"
    h = [_s(c) for c in rows[hi]]
    q = {}
    for j, x in enumerate(h):
        m = re.match(r"Q([1-4])", x.strip().upper())
        if m:
            q.setdefault(int(m.group(1)), j)
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 1):
        if not r or not _s(r[0]):
            continue

        def qv(n):
            j = q.get(n)
            return _num(r[j]) if j is not None and j < len(r) else None

        out.append((snapshot, scope, _s(r[0]), qv(1), qv(2), qv(3), qv(4),
                    _raw_json(r), file_id, i))
    DB.insert_rows(conn, "incites_research_fields",
                   ["snapshot", "scope", "discipline", "q1", "q2", "q3", "q4",
                    "raw_json", "file_id", "row_no"], out)
    return len(out), ST_PARSED, ""


def parse_ynu_papers(conn, path, file_id, snapshot, discipline=""):
    """云大 WOS 论文清单 → incites_ynu_papers（canonical + raw_json）。

    2009-2019 世代表头 mojibake 且合并损毁：宽 20 时按 `OLD_LAYOUT_PAPERS`
    位置恢复（标题=3 作者=4 来源=5 出版年=11 被引频次=12，经 云大Chemistry.xlsx 实测核对）。
    """
    rows = read_rows_any(path, read_only=path.suffix.lower() != ".csv")
    hi, h, garbled = None, None, False
    if path.suffix.lower() != ".csv":
        hi, h, garbled = _incites_header(rows)
    note = ""
    ti = ai = si = yi = ci = None
    if hi is not None and not garbled and h:
        low = [x.lower() for x in h]
        ti = next((j for j, x in enumerate(low) if "title" in x or "论文标题" in x), None)
        ai = next((j for j, x in enumerate(low) if "author" in x or "作者" in x), None)
        si = next((j for j, x in enumerate(low) if "source" in x or "来源" in x), None)
        yi = next((j for j, x in enumerate(low) if "publication year" in x or "出版年" in x), None)
        ci = next((j for j, x in enumerate(low) if "times cited" in x or "被引频次" in x), None)
        start = hi + 1
    else:
        width = max((len(r) for r in rows if r), default=0)
        if width != len(OLD_LAYOUT_PAPERS):
            n = stash_misc(conn, path, file_id)
            return n, ST_STASHED, f"论文表头未识别且列数 {width}≠{len(OLD_LAYOUT_PAPERS)}，整件 misc_rows"
        ti, ai, si, yi, ci = 3, 4, 5, 11, 12
        start = _first_data_row(rows)
        note = "表头乱码，按数据说明.txt §4 老版列序位置恢复"
    out = []
    for i, r in enumerate(rows[start:], start=start):
        if not r or not any(_s(c) for c in r):
            continue
        head = " ".join(str(c).lower() for c in r[:3] if c is not None)
        if "incites dataset" in head:
            break
        title = _s(r[ti]) if ti is not None and ti < len(r) else ""
        tc = _int(_num(r[ci])) if ci is not None and ci < len(r) else None
        # 数据块结束护栏：Filter Summary 等脚注行（无标题无被引）一律终止
        if not title and tc is None and not any(_num(c) is not None for c in r[ti or 0:]):
            break
        out.append((snapshot, discipline, title, tc, _raw_json(r), file_id, i))
    DB.insert_rows(conn, "incites_ynu_papers",
                   ["snapshot", "discipline", "title", "times_cited", "raw_json",
                    "file_id", "row_no"], out)
    return len(out), (ST_RECOVERED if note else ST_PARSED), note


def parse_global_institutions(conn, path, file_id, snapshot):
    """InCites 全球机构榜 → incites_global_institutions（canonical + raw_json）。"""
    rows = read_rows_any(path, read_only=path.suffix.lower() != ".csv")
    hi, labels, _g = _incites_header(rows)
    if hi is None:
        n = stash_misc(conn, path, file_id)
        return n, ST_STASHED, "机构榜表头未识别，整件 misc_rows"
    idc = _identity_cols(labels)
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 1):
        if not r or not any(_s(c) for c in r):
            continue
        if any(c and "copyright" in str(c).lower() for c in r[:2]):
            break
        j = idc.get("rank_no")
        n = _num(r[j]) if j is not None and j < len(r) else None
        j = idc.get("institution")
        name = _s(r[j]).upper() if j is not None and j < len(r) else ""
        j = idc.get("country")
        ctry = _s(r[j]).upper() if j is not None and j < len(r) else ""
        out.append((snapshot, _int(n), name, ctry, _raw_json(r), file_id, i))
    DB.insert_rows(conn, "incites_global_institutions",
                   ["snapshot", "rank_no", "institution", "country", "raw_json",
                    "file_id", "row_no"], out)
    return len(out), ST_PARSED, ""


# ------------------------------------------------------------------ 兜底
def stash_misc(conn, path, file_id) -> int:
    """整件逐行原样进 misc_rows（无专属解析器 / 损坏救不回的件）。"""
    sheets = ({"": read_rows_any(path, read_only=True)}
              if path.suffix.lower() == ".csv" else read_xlsx_all_sheets(path))
    out = []
    for sheet, rows in sheets.items():
        for i, r in enumerate(rows, start=1):
            if not r or not any(_s(c) for c in r):
                continue
            out.append((file_id, sheet, i, _raw_json(r)))
    DB.insert_rows(conn, "misc_rows", ["file_id", "sheet", "row_no", "raw_json"], out)
    return len(out)


# ------------------------------------------------------------------ 维度与清单
#: 期次 → InCites 快照（仅 `src/extract_matrix.py::SNAP_MAP` 逐期验证过的 5 期；未知不猜）。
from extract_matrix import SNAP_MAP as SNAP_SOURCE  # noqa: E402


def put_dims(conn, kind: str, scope: str) -> None:
    if kind == "esi" and PERIOD_RE.fullmatch(scope):
        conn.execute("INSERT INTO periods(period) VALUES(?)"
                     " ON CONFLICT(period) DO NOTHING", (scope,))
    if kind == "incites" and scope.startswith("数据覆盖"):
        body = scope[len("数据覆盖"):]
        start, _, end = body.partition("-")
        conn.execute(
            "INSERT INTO snapshots(snapshot, window_start, window_end) VALUES(?,?,?)"
            " ON CONFLICT(snapshot) DO NOTHING", (scope, start.strip(), end.strip()))
    if kind == "esi" and scope in SNAP_SOURCE:
        conn.execute(
            "INSERT INTO period_snapshot(period, snapshot, source) VALUES(?,?,?)"
            " ON CONFLICT(period) DO UPDATE SET snapshot=excluded.snapshot,"
            " source=excluded.source", (scope, SNAP_SOURCE[scope], "snap_map"))


def load_corrupt_relpaths() -> set[str]:
    """损坏清单 md → 相对 `数据与复现/` 的路径集合（真损坏段；附注段不算）。"""
    if not CORRUPT_MD.is_file():
        return set()
    text = CORRUPT_MD.read_text(encoding="utf-8", errors="replace").split("附注")[0]
    out = set()
    for m in re.finditer(r"`([^`]+)`", text):
        raw = pathlib.Path(m.group(1))
        if "数据与复现" not in str(raw):
            continue
        try:
            out.add(raw.relative_to(DATA_ROOT).as_posix())
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ 主流程
def _walk_misc():
    """数据与复现/ 根散件 + 论文清单/（排除 ESI数据/ 与 incites/，那两块归各自 kind）。"""
    for path in sorted(DATA_ROOT.iterdir()):
        if path.is_file():
            yield "_root", path.name, path
    sub = DATA_ROOT / "论文清单"
    if sub.is_dir():
        for path in sorted(sub.rglob("*")):
            if path.is_file():
                yield "论文清单", f"论文清单/{path.name}", path


def _cached_sha(conn, kind, scope, rel_path, path) -> str:
    """指纹增量：库里已有同键指纹就沿用（9 GB 不重算），否则现算。"""
    row = conn.execute(
        "SELECT sha256 FROM files WHERE kind=? AND scope=? AND rel_path=?",
        (kind, scope, rel_path)).fetchone()
    if row and row["sha256"]:
        return str(row["sha256"])
    return SI.sha256_file(path)


def _clear_file_rows(conn, file_id: int) -> None:
    """重解析前清掉该文件的旧数据行（幂等；清单行保留）。动态表可能尚未建，先查再删。"""
    have = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("esi_discipline_rank", "esi_institutions", "esi_thresholds",
                  "esi_baselines", "esi_papers", "esi_research_fields",
                  "incites_subject_rows", "incites_research_fields",
                  "incites_ynu_papers", "incites_global_institutions", "misc_rows"):
        if table in have:
            conn.execute(f"DELETE FROM {table} WHERE file_id=?", (file_id,))


def _parse_one(conn, kind, scope, fid, path, role, extra, root_stems, rel_under):
    """单文件解析分发。返回 (行数, status, note)。"""
    p = pathlib.Path(rel_under)
    period = scope if PERIOD_RE.fullmatch(scope) else _parse_period(p.stem)
    # 孪生件：excel/ 子目录 xlsx、根目录 csv 的 xlsx 同形对——主件已解析就跳过
    if len(p.parts) >= 2 and p.parts[1] == "excel":
        if DB.norm_label(p.stem).lower() in root_stems:
            return 0, ST_DUP, "excel/ 孪生件，与根目录主件同数据"
    if p.suffix.lower() == ".csv" and p.parent == pathlib.Path(".") \
            and path.with_suffix(".xlsx").is_file():
        return 0, ST_DUP, "xlsx 同形对，主件 xlsx 已解析"

    if role in (R_LOCK, R_DOC, R_DERIVED, R_MASTER, R_LEDGER):
        return 0, (ST_EMPTY if role == R_LOCK else ST_DERIVED), \
            ("Office 锁文件" if role == R_LOCK else "文档/派生/母本件，只登记")
    if role == R_ZIP:
        return 0, ST_DUP, "与同名快照目录疑似重复，不解析"
    if role == R_META:
        return parse_download_meta(conn, path, period), ST_PARSED, ""
    if role == R_RENAME:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if kind == "incites" and scope.startswith("数据覆盖"):
            conn.execute("UPDATE snapshots SET note=? WHERE snapshot=?", (text, scope))
        return 0, ST_EMPTY, "改名记录 JSON，存维度表"

    if kind == "esi":
        if role == R_SUBJECT:
            return parse_esi_subject(conn, path, fid, period, extra), ST_PARSED, ""
        if role in (R_INST, R_INST_G):
            return parse_esi_institutions(conn, path, fid, period), ST_PARSED, ""
        if role == R_ORG_TYPE:
            n = stash_misc(conn, path, fid)
            return n, ST_STASHED, "机构属性（misc 原样）"
        if role == R_THRESHOLD:
            return parse_thresholds(conn, path, fid, period, extra), ST_PARSED, ""
        if role == R_BASELINE:
            return parse_baselines(conn, path, fid, period, extra), ST_PARSED, ""
        if role == R_PAPERS:
            return parse_papers(conn, path, fid, period, extra), ST_PARSED, ""
        if role == R_RESEARCH:
            return parse_research_fields(conn, path, fid, period, extra), ST_PARSED, ""
        if role == R_MISC:
            return stash_misc(conn, path, fid), ST_STASHED, "散件原样"
    elif kind == "incites":
        if role == R_SUBJECT:
            return parse_subject_rows(conn, path, fid, scope, extra, ynu=False)
        if role == R_YNU_SUBJECT:
            return parse_subject_rows(conn, path, fid, scope, extra, ynu=True)
        if role == R_RESEARCH:
            return parse_incites_research(conn, path, fid, scope, extra)
        if role == R_PAPERS:
            return parse_ynu_papers(conn, path, fid, scope,
                                    discipline=extra if extra != "云大论文" else "云大论文")
        if role == R_INST_G:
            return parse_global_institutions(conn, path, fid, scope)
        if role == R_MISC:
            return stash_misc(conn, path, fid), ST_STASHED, "散件原样"
    elif kind == "misc" and role == R_PAPERS:
        return parse_papers(conn, path, fid, period, extra), ST_PARSED, ""
    return 0, ST_DERIVED, f"未接解析器的角色：{role}"


#: (kind, role) → 专属数据表（verify 行数对账用）。
_ROLE_TABLE = {
    ("esi", R_SUBJECT): "esi_discipline_rank",
    ("esi", R_INST): "esi_institutions",
    ("esi", R_INST_G): "esi_institutions",
    ("esi", R_THRESHOLD): "esi_thresholds",
    ("esi", R_BASELINE): "esi_baselines",
    ("esi", R_PAPERS): "esi_papers",
    ("esi", R_RESEARCH): "esi_research_fields",
    ("incites", R_SUBJECT): "incites_subject_rows",
    ("incites", R_YNU_SUBJECT): "incites_subject_rows",
    ("incites", R_RESEARCH): "incites_research_fields",
    ("incites", R_PAPERS): "incites_ynu_papers",
    ("incites", R_INST_G): "incites_global_institutions",
}


def import_kind(conn, kind: str, scopes=None, *, force: bool = False, emit=print) -> dict:
    """一个 kind 的清单登记 + 解析。返回统计。"""
    if kind == "esi":
        raw_iter = SI.iter_files("esi")
        classify = classify_esi
        prefix = "ESI数据"
    elif kind == "incites":
        raw_iter = SI.iter_files("incites")
        classify = classify_incites
        prefix = "incites"
    else:
        raw_iter = _walk_misc()
        classify = classify_misc
        prefix = ""

    stats = {"files": 0, "parsed": 0, "recovered": 0, "skipped": 0, "rows": 0, "failed": 0}
    per_scope: dict[str, list] = {}
    for scope, rel_path, path in raw_iter:
        if scopes and scope not in scopes:
            continue
        # rel_under = 相对 scope 目录的路径（scope 直下的文件没有子路径成分）
        root_dir = SI.kind_root(kind) if prefix else DATA_ROOT
        base = root_dir / scope if prefix and scope != "_root" else root_dir
        rel_under = path.relative_to(base).as_posix()
        per_scope.setdefault(scope, []).append((rel_under, path))

    for scope in sorted(per_scope):
        items = per_scope[scope]
        put_dims(conn, kind, scope)
        # 第一遍：登记清单（指纹增量）
        reg = []
        for rel_under, path in items:
            st = path.stat()
            sha = _cached_sha(conn, kind, scope, rel_under, path)
            role, extra = classify(scope, rel_under, path.name)
            fid = DB.register_file(conn, kind=kind, scope=scope, rel_path=rel_under,
                                   size=st.st_size, mtime_ns=st.st_mtime_ns,
                                   sha256=sha, role=role)
            reg.append((fid, rel_under, path, role, extra))
        conn.commit()
        # excel/ 孪生判定：根目录（scope 直下）同名 stem 的主件存在 → 子目录件跳过
        root_stems = {DB.norm_label(pathlib.Path(rel).stem).lower()
                      for rel, _p in items if pathlib.Path(rel).parent == pathlib.Path(".")}
        scope_stat = {"parsed": 0, "recovered": 0, "skipped": 0, "failed": 0, "rows": 0}
        # 第二遍：按角色解析
        for fid, rel_under, path, role, extra in sorted(reg, key=lambda t: t[1]):
            row = conn.execute("SELECT parse_status FROM files WHERE id=?", (fid,)).fetchone()
            if not force and row and row["parse_status"] in (ST_PARSED, ST_RECOVERED):
                stats["files"] += 1
                continue
            _clear_file_rows(conn, fid)
            try:
                n, status, note = _parse_one(conn, kind, scope, fid, path, role, extra,
                                             root_stems, rel_under)
            except Exception as exc:  # 解析失败不炸全局：记账继续
                # 表头未识别的件（64 件研究领域/论文清单）→ 按 §3「散件 stash 保真是预期行为」
                # 转 stash 而非 failed：这些是解析器确实认不出的表头，设计上就该整件 misc_rows
                # 保真，不是真损坏。其它一切错误仍 failed——**不洗白真失败**。
                if isinstance(exc, ValueError) and (
                        "未识别表头" in str(exc) or "没有可解析行" in str(exc)):
                    conn.rollback()
                    try:
                        n = stash_misc(conn, path, fid)
                        status, note = (ST_STASHED,
                                        f"表头未识别，整件 misc_rows 保真（原报错：{exc}）")
                    except Exception as exc2:
                        n, status, note = 0, ST_FAILED, f"{type(exc2).__name__}: {exc2}"
                else:
                    conn.rollback()
                    n, status, note = 0, ST_FAILED, f"{type(exc).__name__}: {exc}"
            DB.set_file_parse(conn, fid, status=status, rows=n,
                              error=note if status in (ST_FAILED, ST_CORRUPTED) else "",
                              note=note if status in (ST_RECOVERED, ST_DUP, ST_STASHED) else "")
            conn.commit()
            stats["files"] += 1
            stats["rows"] += n
            scope_stat["rows"] += n
            if status == ST_PARSED:
                stats["parsed"] += 1
                scope_stat["parsed"] += 1
            elif status == ST_RECOVERED:
                stats["recovered"] += 1
                scope_stat["recovered"] += 1
            elif status == ST_FAILED:
                stats["failed"] += 1
                scope_stat["failed"] += 1
                emit(f"  !! 失败 {kind}·{scope}·{rel_under}: {note}")
            elif status in (ST_DUP, ST_EMPTY, ST_DERIVED):
                stats["skipped"] += 1
                scope_stat["skipped"] += 1
            if status in (ST_PARSED, ST_RECOVERED, ST_STASHED, ST_CORRUPTED):
                emit(f"  [{kind}·{scope}] {rel_under} → {status} {n} 行"
                     + (f"（{note}）" if note else ""))
        emit(f"[{kind}·{scope}] 共 {len(items)} 件 · 解析 {scope_stat['parsed']}"
             f" · 恢复 {scope_stat['recovered']} · 跳过 {scope_stat['skipped']}"
             f" · 失败 {scope_stat['failed']} · 行数 {scope_stat['rows']}")
        del per_scope[scope]
    return stats


# ------------------------------------------------------------------ verify / report
def _value_health(conn, emit) -> bool:
    """值域防复发：机构榜 `esi_discipline_rank` 的「行数假绿但列全空／错位」当场报 FAIL。

    🔴 血泪教训：按名称匹配填表会**静默失效、不抛异常**（202607 Chemistry 整张 35810 行
    institution 错存成排名字符串、指标全 NULL 却标 parsed、行数对账「不符 0」）。
    仅依赖行数对账发现不了，必须把列值域也纳入对账：
      · `institution` 不得大面积纯数字（错位时存成排名 '1'/'2'…，真机构名永不纯数字）；
      · `documents`/`cites` 不得大面积双空（该表确有指标列落库时才考核非空率，
        兼容旧版缺列 NULL）。
    """
    total = conn.execute("SELECT COUNT(*) n FROM esi_discipline_rank").fetchone()["n"]
    ok = True
    if total:
        # 纯数字机构名 = 非空、且不含任何非数字字符（GLOB '*[^0-9]*' 命中即含非数字）。
        num_inst = conn.execute(
            "SELECT COUNT(*) n FROM esi_discipline_rank"
            " WHERE institution IS NOT NULL AND institution <> ''"
            " AND institution NOT GLOB '*[^0-9]*'"
        ).fetchone()["n"]
        any_metric = conn.execute(
            "SELECT COUNT(*) n FROM esi_discipline_rank"
            " WHERE documents IS NOT NULL OR cites IS NOT NULL"
        ).fetchone()["n"]
        null_metrics = total - any_metric
        num_ratio = num_inst / total
        emit("值域体检：institution 纯数字 %d/%d（%.1f%%）"
             % (num_inst, total, num_ratio * 100)
             + (f" · documents/cites 双空 {null_metrics}/{total}（{null_metrics / total * 100:.1f}%）"
                if total else ""))
        if num_ratio > 0.01:
            emit(f"  值域异常：institution 纯数字占比 {num_ratio:.1%}"
                 f"（≥1% 视为机构榜错位废数据，列全错位）")
            ok = False
        elif any_metric:                      # 该表确有指标列落库时才考核双空率
            null_ratio = null_metrics / total
            if null_ratio > 0.5:
                emit(f"  值域异常：documents/cites 双空占比 {null_ratio:.1%}"
                     f"（>50% 视为列全空失效）")
                ok = False
    return ok


def verify(conn, *, emit=print, fingerprint: bool = False) -> bool:
    """对账：解析状态分布 / 行数对账 / 损坏 219 件核对 / 抽样值对拍。纯读。"""
    ok = True
    counts = DB.table_counts(conn)
    emit("表行数：" + json.dumps(counts, ensure_ascii=False))
    # ① 解析状态分布与失败清单
    rows = conn.execute("SELECT parse_status, COUNT(*) AS n FROM files GROUP BY parse_status"
                        ).fetchall()
    emit("解析状态：" + " · ".join(f"{r['parse_status']}={r['n']}" for r in rows))
    for r in conn.execute("SELECT kind, scope, rel_path, parse_error FROM files"
                          " WHERE parse_status='failed' LIMIT 30"):
        emit(f"  失败：{r['kind']}·{r['scope']}·{r['rel_path']}（{r['parse_error'][:120]}）")
        ok = False
    # ② 行数对账：parsed/recovered → 专属表；stashed/corrupted → misc_rows
    bad = 0
    for r in conn.execute("SELECT id, kind, role, parse_rows, parse_status FROM files"
                          " WHERE parse_status IN ('parsed','recovered','stashed','corrupted')"):
        if r["parse_status"] in (ST_PARSED, ST_RECOVERED):
            table = _ROLE_TABLE.get((r["kind"], r["role"]))
        else:
            table = "misc_rows"
        if table is None:      # 元数据等无行角色
            continue
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE file_id=?",
                         (r["id"],)).fetchone()["n"]
        if n != r["parse_rows"]:
            emit(f"  行数不符：file {r['id']} {r['kind']}·{r['role']}"
                 f" 记 {r['parse_rows']} 实 {n}")
            bad += 1
    if bad:
        ok = False
    emit(f"行数对账：不符 {bad}")
    # ③.5 值域防复发：机构榜「行数假绿但列全空／错位」当场报 FAIL
    if not _value_health(conn, emit):
        ok = False
    # ③ 损坏 219 件核对：清单里的每件都必须 recovered / corrupted / skipped_duplicate
    corrupt = load_corrupt_relpaths()
    if corrupt:
        by_rel = {r["rel_path"]: r["parse_status"]
                  for r in conn.execute(
                      "SELECT rel_path, parse_status FROM files WHERE kind='incites'")}
        unaccounted = [rel for rel in corrupt
                       if by_rel.get(rel) not in (ST_RECOVERED, ST_CORRUPTED, ST_DUP)]
        emit(f"损坏清单核对：{len(corrupt)} 件，未对上 {len(unaccounted)}")
        for rel in unaccounted[:20]:
            emit(f"  未对上：{rel}")
        if unaccounted:
            ok = False
    # ④ 抽样值：202607 Chemistry 榜与 extract_incites.read_esi_list 逐值对拍
    if not _spot_check(conn, emit):
        ok = False
    # ⑤ 指纹
    if fingerprint:
        emit("计算全库指纹（大库可能要几分钟）…")
        sha = DB.content_sha256(conn, emit=emit)
        old = DB.get_meta(conn, "content_sha256")
        DB.put_meta(conn, "content_sha256", sha)
        conn.commit()
        emit(f"content_sha256={sha}"
             + (f"（上次 {old}，{'一致' if old == sha else '**不一致**'}）" if old else "（首次）"))
        if old is not None and old != sha:
            ok = False
    emit("verify 结论：" + ("通过" if ok else "**未通过（见上）**"))
    return ok


def _spot_check(conn, emit) -> bool:
    """抽样：202607 Chemistry 榜与 extract_incites.read_esi_list（口径同源工具）对拍。"""
    import extract_incites as T
    esi_dir = SI.kind_root("esi") / "202607"
    p = T._resolve_file(esi_dir, "Chemistry")
    if p is None:
        emit("  抽样跳过：202607 无 Chemistry 原件")
        return True
    ref = T.read_esi_list(p)
    n = conn.execute("SELECT COUNT(*) AS n FROM esi_discipline_rank WHERE period='202607'"
                     " AND discipline='Chemistry'").fetchone()["n"]
    if n != ref["m"]:
        emit(f"  抽样不符：202607 Chemistry 行数 库{n} ≠ 工具{ref['m']}")
        return False
    yrow = conn.execute(
        "SELECT rank_no, documents, cites FROM esi_discipline_rank"
        " WHERE period='202607' AND discipline='Chemistry'"
        " AND institution LIKE 'YUNNAN UNIVERSITY%'").fetchone()
    if yrow is None:
        emit("  抽样不符：202607 Chemistry 没有云大行")
        return False
    if yrow["rank_no"] != ref["ypos"] or yrow["documents"] != ref["y_docs"] \
            or yrow["cites"] != ref["y_cites"]:
        emit(f"  抽样不符：云大行 库={dict(yrow)} 工具 ypos={ref['ypos']}"
             f" y_docs={ref['y_docs']} y_cites={ref['y_cites']}")
        return False
    emit(f"  抽样通过：202607 Chemistry {n} 行，云大 rank={yrow['rank_no']}"
         f" documents={yrow['documents']} cites={yrow['cites']}")
    return True


def report(conn, *, emit=print) -> None:
    """覆盖报告：清单/解析/行数按 kind·scope 汇总 + 快照学科覆盖。纯读。"""
    rows = conn.execute(
        "SELECT kind, scope, COUNT(*) AS n,"
        " SUM(parse_status IN ('parsed','recovered')) AS done,"
        " SUM(parse_status='corrupted') AS corrupt,"
        " SUM(parse_status='skipped_duplicate') AS skip,"
        " SUM(parse_status='failed') AS fail, SUM(parse_rows) AS rows"
        " FROM files GROUP BY kind, scope ORDER BY kind, scope").fetchall()
    emit("| kind | scope | 文件 | 已解析 | 损坏 | 跳过 | 失败 | 解析行数 |")
    emit("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        emit(f"| {r['kind']} | {r['scope']} | {r['n']} | {r['done']} | {r['corrupt']}"
             f" | {r['skip']} | {r['fail']} | {r['rows']} |")
    for snap in conn.execute("SELECT snapshot FROM snapshots ORDER BY snapshot"):
        n = conn.execute("SELECT COUNT(DISTINCT discipline) AS n FROM incites_subject_rows"
                         " WHERE snapshot=?", (snap["snapshot"],)).fetchone()["n"]
        if n:
            emit(f"  快照 {snap['snapshot']}：{n} 学科")


# ------------------------------------------------------------------ 入口
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="历史档案库导入器（对数据目录只读，ADR-0015）")
    ap.add_argument("--kind", default="all", choices=["esi", "incites", "misc", "all"])
    ap.add_argument("--scope", action="append", default=None,
                    help="只处理这一期/快照（目录名），可多次")
    ap.add_argument("--reset", action="store_true", help="清空重建（全量重导前用）")
    ap.add_argument("--force", action="store_true", help="已解析的件也重解析")
    ap.add_argument("--verify", action="store_true", help="对账（纯读）")
    ap.add_argument("--fingerprint", action="store_true", help="verify 附带全库内容指纹")
    ap.add_argument("--report", action="store_true", help="覆盖报告（纯读）")
    ap.add_argument("--db", default=None, help="库路径（默认 档案库/wenheng_archive.sqlite）")
    args = ap.parse_args(argv)

    db = pathlib.Path(args.db) if args.db else DB.db_path()
    emit = print
    if args.verify or args.report:
        if not db.is_file():
            emit(f"档案库不存在：{db}（先跑导入）")
            return 2
        conn = DB.connect(db)
        try:
            if args.report:
                report(conn, emit=emit)
            if args.verify:
                return 0 if verify(conn, emit=emit, fingerprint=args.fingerprint) else 1
        finally:
            conn.close()
        return 0

    emit(f"档案库：{db}")
    emit(f"数据根：{DATA_ROOT}（只读）")
    conn = DB.connect(db)
    if args.reset:
        DB.reset(conn)
        emit("已清空重建 schema")
    DB.ensure(conn)
    kinds = ["esi", "incites", "misc"] if args.kind == "all" else [args.kind]
    emit(f"开始导入 kind={kinds} scope={args.scope or '全部'}"
         f"（{datetime.datetime.now().strftime('%H:%M:%S')}）")
    for k in kinds:
        stats = import_kind(conn, k, args.scope, force=args.force, emit=emit)
        emit(f"== {k} 完成：文件 {stats['files']} · parsed {stats['parsed']}"
             f" · recovered {stats['recovered']} · skipped {stats['skipped']}"
             f" · failed {stats['failed']} · 行数 {stats['rows']}")
    DB.put_meta(conn, "built_at", datetime.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    # 退出码语义（根治「软失败被绿码掩盖」，与 §7 行数假绿同类）：
    # 任何非预期 failed（解析抛错 / 编码失败）一律 EXIT 1，不再静默 0。
    failed_total = conn.execute(
        "SELECT COUNT(*) AS n FROM files WHERE parse_status='failed'").fetchone()["n"]
    if failed_total:
        emit(f"!! 导入结束但有 {failed_total} 件 failed（非预期失败），EXIT 1")
        conn.close()
        return 1
    emit(f"结束（{datetime.datetime.now().strftime('%H:%M:%S')}）；"
         f"后续：--verify 对账 / --report 覆盖报告")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
