# -*- coding: utf-8 -*-
"""监测版 46 期趋势基建：逐期提取与 build_cache 同构的轻量快照，合并成单校跨期序列。

(v2) 老版式可提取化：趋势门禁是**趋势自有检查**——候选名解析 + 内容二次确认 + 行数下限，
不再用 doctor 全量 D1-D6（缺 _下载信息.json、缺基线/全球学科等不构成 bad）；doctor.py 不改。

老期次归档实况（2026-10-31 逐期普查，证据钉在 tests/test_monitor_trend.py）：
- 机构总表等价物按候选名解析、按内容二次确认，共四种形态——
  a) 全量全球榜（7/9/15 列，有/无表头行）→ n_inst=行数；
  b) 中国子集（保 ESI 全局排名，名次有空洞，如 202107/202511）→ n_inst=None，行值仍为真值；
  c) [机构名, 排名, ...] 残表（202007/202009 四列）→ 只取总排名，论文/被引 None；
  d) 不可解析（如 202501 的中英文名映射表）→ inst 空、points 缺。
- 22 张学科榜：规范名（Windows 大小写不敏感）+ 个别别名（COMPUTER SCIENC / PSYCHIATRY
  SYCHOLOGY / AGRICULTURAL）+ 201905/201907 的「全球机构-<中文学科>.xlsx」。每张榜按内容
  分类：**全量全球榜**（前 50 行含非中国大陆行且 m≥100，m/line 如常）或**保排名子集**
  （纯中国大陆或截取件，名次非稠密＝保留全局排名，行值真实；m/line/line_cites 如实 None；
  cn_rank 公式自适应——全中国子集下行序即国内排名）。名次稠密且从 1 起（重排榜，语义假）
  → 拒收该榜。202011/Chemistry 一类手打名单不可解析 → 缺席。另有 201911-202007 的
  「全球机构-X/手工摘录」家族（[机构名, 全局排名, 中国序号, ...]，无表头、列序各异）按
  _HANDRANK_COLS 显式列位解析，只取全局排名（列位经 CAS 4→2→1 跨期互证）。
- 阈值表：ThresholdESI/THRESHOLD-ESI/ESI Thresholds/阈值ESI/ESI阈值 等命名、三种版式
  （宽表=杂行+RESEARCH FIELDS 表头、紧凑带表头、紧凑无表头），INSTITUTION 列一律按表头
  定位（无表头紧凑版按时代延续取第 2 列，已与 202403 宽表/202407 紧凑表互证）；
  VLOOKUP 公式串以 data_only=True 读 Excel 缓存值；无阈值表/个别学科缺值 → thr1 如实缺键。
- 202303 判 bad：其 22 榜与 institutions.xlsx 是 202603 期内容的拷贝（逐字一致；m 序列上
  202303 较 202301/202305 邻域 +30% 级跳变、202603 平滑）——证据见 _KNOWN_POISONED 与测试。

纪律：combine 出的序列不含任何推断值，缺失维度一律 None/缺键；运行期零 LLM、零网络。
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

from monitor import report as mr                   # noqa: E402
from monitor import schools as sch                 # noqa: E402

TREND_ROOT = mr.MONITOR_ROOT / "_trend"
_EN_SET = {s["en"] for s in sch.SCHOOLS}

# ---------------------------------------------------------------- 候选名表
#: 机构总表等价物（按序尝试，Windows 文件名大小写不敏感）。
_INST_CANDIDATES = ["Institutions.xlsx", "institutes.xlsx", "institute.xlsx",
                    "world Institutions.xlsx", "global institute.xlsx",
                    "all institutes.xlsx", "institutions all.xlsx",
                    "全球机构.xlsx", "全球机构排名.xlsx", "世界机构排名.xlsx",
                    "机构排名.xlsx", "ESI全球大学排名.xlsx", "ESI全球机构排名.xlsx"]

#: 学科榜个别别名（规范名缺失时的已核实替身）。
_STEM_FILE_ALIASES: dict[str, list[str]] = {
    "Computer Science": ["COMPUTER SCIENC.xlsx"],          # 202001
    "Psychiatry Psychology": ["PSYCHIATRY SYCHOLOGY.xlsx"],  # 202003
    "Agricultural Sciences": ["AGRICULTURAL.xlsx"],        # 202103
}

#: 201905/201907 时代的手工导出榜「全球机构-<中文学科>.xlsx」（内容二次确认兜底）。
_ZH_FIELD_FILES: dict[str, list[str]] = {
    "Agricultural Sciences": ["全球机构-农业科学.xlsx"],
    "Biology & Biochemistry": ["全球机构-生物与生物化学.xlsx"],
    "Chemistry": ["全球机构-化学.xlsx"],
    "Clinical Medicine": ["全球机构-临床医学.xlsx"],
    "Computer Science": ["全球机构-计算机.xlsx", "全球机构-计算机科学.xlsx"],
    "Economics & Business": ["全球机构-经济与商业.xlsx", "全球机构-经济商业.xlsx"],
    "Engineering": ["全球机构-工程.xlsx"],
    "Environment Ecology": ["全球机构-环境与生态.xlsx", "全球机构-环境生态.xlsx"],
    "Geosciences": ["全球机构-地球科学.xlsx"],
    "Immunology": ["全球机构-免疫.xlsx", "全球机构-免疫学.xlsx"],
    "Materials Science": ["全球机构-材料科学.xlsx"],
    "Mathematics": ["全球机构-数学.xlsx"],
    "Microbiology": ["全球机构-微生物.xlsx"],
    "Molecular Biology & Genetics": ["全球机构-分子生物与基因.xlsx"],
    "Multidisciplinary": ["全球机构-多学科.xlsx"],
    "Neuroscience & Behavior": ["全球机构-神经科学与行为.xlsx"],
    "Pharmacology & Toxicology": ["全球机构-药学与毒理学.xlsx"],
    "Physics": ["全球机构-物理.xlsx"],
    "Plant & Animal Science": ["全球机构-植物与动物学.xlsx", "全球机构-植物与动物科学.xlsx"],
    "Psychiatry Psychology": ["全球机构-精神病学与心理学.xlsx", "全球机构-生理学与心理学.xlsx"],
    "Social Sciences, General": ["全球机构-社会科学.xlsx"],
    "Space Science": ["全球机构-空间科学.xlsx"],
}

#: 阈值表候选名（按序尝试）。
_THR_CANDIDATES = ["ThresholdESI.xlsx", "THRESHOLD-ESI.xlsx", "ESI Thresholds.xlsx",
                   "阈值ESI.xlsx", "ESI阈值.xlsx", "ThresholdESI .xlsx",
                   "Citation Thresholds-Threshold ESI.xlsx", "ThresholdESI (1).xlsx"]

#: 手工摘录榜的列位（(期次, stem) → (机构名列, 全局排名列)）。这些文件是
#: [机构名, 全局排名, 中国序号, 云大注释, VLOOKUP...] 家族及其变体，无表头行、
#: 列序各异；全局排名列经内容互证核实（CAS 植物与动物学 201911=4 → 202111=2 →
#: 202609=1 单调；心理所/北师大行与 201907 CAS-233 连续）。只取排名，指标列 None。
_HANDRANK_COLS: dict[tuple[str, str], tuple[int, int]] = {
    ("201911", "Plant & Animal Science"): (0, 1),
    ("202001", "Plant & Animal Science"): (0, 1),
    ("202003", "Plant & Animal Science"): (0, 1),
    ("202005", "Plant & Animal Science"): (0, 1),
    ("202007", "Plant & Animal Science"): (0, 1),
    ("202007", "Psychiatry Psychology"): (2, 1),
    ("202007", "Multidisciplinary"): (3, 2),
}

#: 已核实的内容错乱期（整期拒绝入库），理由内联可审计。
_KNOWN_POISONED = {
    "202303": "22 张学科榜与 institutions.xlsx 为 202603 期内容的拷贝（CAS 化学行 "
              "118832/3668874 与 m=2275 逐字一致；m 序列上 202303 较 202301/202305 邻域 "
              "+30% 级跳变而 202603 平滑）——证据见 tests::test_202303_is_202603_copy",
}

_MIN_STEMS = 20            # 有效学科榜下限（缺/拒收超过 2 张 → 整期 bad）
_MIN_INST_ROWS_FULL = 1000   # 机构表「全量全球榜」行数下限
_MIN_FIELD_ROWS_FULL = 100   # 学科榜「全量全球榜」行数下限
_TOPN_CHECK = 50             # 中国/非中国行判定的抽查窗口


def _norm_head(cell) -> str:
    """表头单元格 → 规范名（大写、/ 归空格、压空白；与 mr._norm 同风格）。"""
    return " ".join(str(cell).upper().replace("/", " ").split()) if cell is not None else ""


def _is_num(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().replace(",", "")
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _rank_of(v) -> int:
    return int(float(str(v).strip().replace(",", "")))


def _load_rows(path: pathlib.Path, data_only: bool = False) -> list:
    wb = openpyxl.load_workbook(path, data_only=data_only)
    try:
        return [r for r in wb.active.iter_rows(values_only=True)
                if any(c is not None and str(c).strip() for c in r)]
    finally:
        wb.close()


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
    """按列映射取数值；列缺失或空 → None（老版式缺列补位约定）。"""
    if idx is None or idx >= len(row) or row[idx] is None or not str(row[idx]).strip():
        return None
    return float(str(row[idx]).strip().replace(",", ""))


def _country(row, idx: int | None) -> str:
    v = row[idx] if idx is not None and idx < len(row) else None
    return str(v).strip() if v is not None else ""


def _load_ranking(path: pathlib.Path,
                  handrank: tuple[int, int] | None = None) -> tuple[str, object, list]:
    """解析排名表 → (kind, cols, data)。

    kind='std'：首列排名（有表头行按表头映射；无表头按 7 列老导出位次 0-5）；
    kind='name_rank'：cols=(机构名列, 排名列)——手工摘录件按 _HANDRANK_COLS 的
    显式列位解析，未登记的手工件不猜列、直接拒收。
    排名非数字的杂行（版权行等）一律剔除。"""
    rows = _load_rows(path)
    hdr = next((i for i, r in enumerate(rows[:8])
                if len(r) > 1 and r[1] is not None and str(r[1]).strip() == "Institutions"), None)
    if hdr is not None:
        data = sorted((r for r in rows[hdr + 1:]
                       if len(r) > 1 and r[1] is not None and str(r[1]).strip() and _is_num(r[0])),
                      key=lambda r: _rank_of(r[0]))
        return "std", _cols(rows[hdr]), data
    if handrank is not None:                               # 手工摘录件：显式列位
        name_col, rank_col = handrank
        need = max(name_col, rank_col)
        data = sorted((r for r in rows
                       if len(r) > need and r[name_col] is not None
                       and str(r[name_col]).strip() and _is_num(r[rank_col])),
                      key=lambda r: _rank_of(r[rank_col]))
        if not data:
            raise ValueError(f"{path.name}: 手工摘录列位下无数据行")
        return "name_rank", (name_col, rank_col), data
    raw = [r for r in rows if len(r) > 1 and r[1] is not None and str(r[1]).strip()]
    if not raw:
        raise ValueError(f"{path.name}: 无数据行")
    if _is_num(raw[0][0]):                                 # 无表头：[排名, 机构名, ...]
        data = sorted((r for r in raw if _is_num(r[0])), key=lambda r: _rank_of(r[0]))
        cols = {"country": 2, "papers": 3, "cites": 4, "cp": 5, "hcp": None, "hp": None}
        return "std", cols, data
    if _is_num(raw[0][1]):                                 # 残表：[机构名, 排名, ...]
        data = sorted((r for r in raw if _is_num(r[1])), key=lambda r: _rank_of(r[1]))
        return "name_rank", (0, 1), data
    raise ValueError(f"{path.name}: 无 Institutions 表头行且首行不像数据行（版式不识别）")


def _is_dense_from_one(data) -> bool:
    """前 20 行名次是否从 1 起连续稠密——重排榜特征（保排名子集必有空洞）。"""
    ranks = []
    for r in data[:20]:
        if _is_num(r[0]):
            ranks.append(_rank_of(r[0]))
    return (len(ranks) >= 2 and ranks[0] == 1
            and all(ranks[i + 1] == ranks[i] + 1 for i in range(len(ranks) - 1)))


def _resolve(base: pathlib.Path, names: list[str]) -> pathlib.Path | None:
    for name in names:
        p = base / name
        if p.exists():
            return p
    return None


def _stem_candidates(stem: str) -> list[str]:
    return [f"{stem}.xlsx", *_STEM_FILE_ALIASES.get(stem, []), *_ZH_FIELD_FILES.get(stem, [])]


# ---------------------------------------------------------------- 单期提取
def _extract_inst(base: pathlib.Path) -> tuple[dict, int | None, str | None]:
    """机构总表等价物 → (inst, n_inst, note)。永不抛错：候选逐个试，全不可用 → 空表 + note。"""
    errs = []
    for name in _INST_CANDIDATES:
        path = base / name
        if not path.exists():
            continue
        try:
            kind, cols, data = _load_ranking(path)
        except ValueError as exc:
            errs.append(f"{name} 不可解析（{exc}）")
            continue
        if kind == "name_rank":                            # 残表：只取总排名
            name_col, rank_col = cols
            inst = {str(r[name_col]).strip(): [_rank_of(r[rank_col]), None, None, None]
                    for r in data if str(r[name_col]).strip() in _EN_SET}
            return inst, None, f"{name}: 排名残表，n_inst=None"
        top = data[:_TOPN_CHECK]
        has_non_china = any(_country(r, cols["country"]) not in ("CHINA MAINLAND", "N/A")
                            for r in top)
        full = has_non_china and len(data) >= _MIN_INST_ROWS_FULL
        if not full and _is_dense_from_one(data):
            errs.append(f"{name} 中国重排榜（排名稠密），拒收")
            continue
        inst = {}
        for r in data:
            nm = str(r[1]).strip()
            if nm in _EN_SET:
                inst[nm] = [_rank_of(r[0]), _cell(r, cols["papers"]),
                            _cell(r, cols["cites"]), _cell(r, cols["cp"])]
        if full:
            return inst, len(data), None
        return inst, None, f"{name}: 保排名子集，n_inst=None"
    if errs:
        return {}, None, "机构表候选均不可用：" + "；".join(errs)
    return {}, None, "机构总表等价物缺失"


def _extract_field(period: str, stem: str) -> tuple[dict | None, str | None]:
    """单张学科榜 → (fields[stem] 子典, note)；重排稠密榜/未登记手工件 → (None, note)。"""
    path = _resolve(mr.ESI_ROOT / period, _stem_candidates(stem))
    if path is None:
        return None, "榜文件缺失"
    try:
        kind, cols, data = _load_ranking(path, _HANDRANK_COLS.get((period, stem)))
    except ValueError as exc:
        return None, f"不可解析（{exc}）"
    if kind == "name_rank":
        name_col, rank_col = cols
        rows: dict[str, list] = {}
        for r in data:
            nm = str(r[name_col]).strip()
            if nm in _EN_SET:
                rows[nm] = [_rank_of(r[rank_col]), None, None, None, None, None, None]
        return {"m": None, "line": None, "line_cites": None, "schools": rows}, \
            f"{path.name}: 手工摘录榜，只取全局排名（m/line=None）"
    top = data[:_TOPN_CHECK]
    has_non_china = any(_country(r, cols["country"]) not in ("CHINA MAINLAND", "N/A")
                        for r in top)
    full = has_non_china and len(data) >= _MIN_FIELD_ROWS_FULL
    if not full and _is_dense_from_one(data):
        return None, "重排稠密榜，拒收"
    m = len(data)
    line = (m + 1) // 10
    line_cites = _cell(data[line - 1], cols["cites"]) if 0 < line <= m else None
    ci = cols["country"] if cols["country"] is not None else 2
    rows = {}
    for i, r in enumerate(data):
        name = str(r[1]).strip()
        if name not in _EN_SET:
            continue
        # cn_rank（brief 口径）：榜内 CHINA MAINLAND ∪ N/A 行中排在本次之前的数量 + 1；
        # 全中国子集下退化为行序＝国内排名，公式自适应。
        cn_rank = 1 + sum(1 for x in data[:i]
                          if _country(x, ci) in ("CHINA MAINLAND", "N/A"))
        rows[name] = [_rank_of(r[0]), cn_rank, _cell(r, cols["papers"]),
                      _cell(r, cols["cites"]), _cell(r, cols["cp"]),
                      _cell(r, cols["hcp"]), _cell(r, cols["hp"])]
    if full:
        return {"m": m, "line": line, "line_cites": line_cites, "schools": rows}, None
    return {"m": None, "line": None, "line_cites": None, "schools": rows}, \
        f"{path.name}: 保排名子集"


def _thresholds(path: pathlib.Path) -> dict:
    """阈值表 → {规范学科名: 机构阈值}。INSTITUTION 列按表头定位（无表头紧凑版取第 2 列，
    已与邻期宽表互证）；VLOOKUP 公式串以 data_only=True 读缓存值；缺值学科如实缺键。"""
    rows = _load_rows(path, data_only=True)
    expected = {mr._norm(s) for s in mr.STEMS}
    hdr = next((i for i, r in enumerate(rows)
                if r and r[0] is not None and str(r[0]).strip() == "RESEARCH FIELDS"), None)
    if hdr is not None:
        heads = [_norm_head(c) for c in rows[hdr]]
        col = heads.index("INSTITUTION") if "INSTITUTION" in heads else None
        body = rows[hdr + 1:]
    else:
        col = 1                                            # 无表头紧凑版（202405 式）
        body = rows
    if col is None:
        return {}
    thr: dict[str, float] = {}
    for r in body:
        if not r or r[0] is None:
            continue
        key = mr._norm(str(r[0]).strip())
        if key not in expected:
            continue                                       # 杂行/版权行——只认 22 学科行
        v = r[col] if col < len(r) else None
        if v is None or not str(v).strip():
            continue                                       # 缺值/公式无缓存 → 缺键
        try:
            thr[key] = float(str(v).strip().replace(",", ""))
        except ValueError:
            continue
    return thr


def extract_period(period: str) -> dict:
    """单期提取：schema 与 build_cache 的 cache 同构
    （少 cn_inst/neighbors/download，多 inst）。不写盘；老版式缺的维度如实 None。"""
    base = mr.ESI_ROOT / period
    inst, n_inst, inst_note = _extract_inst(base)
    fields: dict[str, dict] = {}
    notes: list[str] = []
    if inst_note:
        notes.append(inst_note)
    for stem in mr.STEMS:
        fd, note = _extract_field(period, stem)
        if fd is None:
            notes.append(f"{stem}: {note}")
            continue
        fields[stem] = fd
        if note:
            notes.append(f"{stem}: {note}")
    thr_path = _resolve(base, _THR_CANDIDATES)
    thr = _thresholds(thr_path) if thr_path else {}
    return {"period": period, "built": datetime.date.today().isoformat(),
            "n_inst": n_inst, "fields": fields, "thr1": thr, "inst": inst,
            "_notes": notes}


# ---------------------------------------------------------------- 落盘与门禁
def trend_path(period: str) -> pathlib.Path:
    return TREND_ROOT / f"{period}.json"


def write_period(period: str, data: dict) -> pathlib.Path:
    TREND_ROOT.mkdir(parents=True, exist_ok=True)
    p = trend_path(period)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _gate(period: str) -> tuple[bool, str, list[str]]:
    """趋势自有门禁（cheap 前置）：目录在、非已知错乱期、机构表候选命中、学科榜候选数达标。
    可解析性/行数下限/重排拒收在 extract 内按内容执行（build_all 兜底为 bad）。"""
    base = mr.ESI_ROOT / period
    if not base.is_dir():
        return False, "期次目录不存在", []
    if period in _KNOWN_POISONED:
        return False, _KNOWN_POISONED[period], []
    if _resolve(base, _INST_CANDIDATES) is None:
        return False, "机构总表等价物缺失（候选名全未命中）", []
    hits = [s for s in mr.STEMS if _resolve(base, _stem_candidates(s)) is not None]
    if len(hits) < _MIN_STEMS:
        miss = "、".join(s for s in mr.STEMS if s not in hits)
        return False, f"学科榜候选不足 {_MIN_STEMS}/22（缺：{miss}）", []
    notes = []
    if _resolve(base, _THR_CANDIDATES) is None:
        notes.append("无阈值表：thr1 整期省略")
    return True, "", notes


def build_all(force: bool = False, only: str | None = None) -> dict:
    """逐期门禁 + 提取落盘，写 _trend/_index.json（断点续跑：已有件默认跳过）。"""
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
        ok, reason, notes = _gate(p)
        data = None
        if ok:
            try:
                data = extract_period(p)
            except Exception as exc:                           # noqa: BLE001
                ok, reason = False, f"extract 崩溃 {type(exc).__name__}: {exc}"
        if ok:
            notes = [*notes, *(data.get("_notes") or [])]
            if len(data["fields"]) < _MIN_STEMS:
                ok = False
                reason = (f"有效学科榜不足 {_MIN_STEMS}/22："
                          + "；".join(data.get("_notes") or []))
        if not ok:
            results[p] = {"status": "bad", "reason": reason, "n_files": n_files}
            print(f"[bad] {p} {reason[:72]}")
            continue
        subset_n = sum(1 for fd in data["fields"].values() if fd["m"] is None)
        if subset_n:
            notes.append(f"保排名子集榜 {subset_n} 张（m/line=None，名次为真实全局值）")
        if data["n_inst"] is None:
            notes.append("机构表为子集/残表：n_inst=None、points 缺或仅总排名")
        write_period(p, {k: v for k, v in data.items() if k != "_notes"})
        entry = {"status": "ok", "n_files": n_files}
        if notes:
            entry["notes"] = "；".join(notes)
        results[p] = entry
        print(f"[ok] {p} fields={len(data['fields'])}/22 n_inst={data['n_inst']}")

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
            continue                                           # 判 bad 的期次绝不进趋势
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
    ap = argparse.ArgumentParser(description="监测版 46 期趋势基建（趋势自有门禁，逐期提取/合并）")
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
