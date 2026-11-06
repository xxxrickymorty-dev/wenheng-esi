# -*- coding: utf-8 -*-
"""历史档案库单测：archive_db 收口 + archive_import.read_csv_rows 编码/说明行。

纯函数 / 纯 SQLite（tmp_path 沙箱），不依赖 `数据与复现/` 原件，永远可跑（含 CI）。
覆盖要点（见 交接单 §4 阶段 1）：
  · `read_csv_rows` 编码优先级 utf-8-sig → gb18030 → cp1252（单字节西欧兜底）；
  · 首行 `Documents Result List: ...` 说明行必须跳过，否则 12 列表头错位；
  · 非法字节 / utf-16 BOM（三编码都解不开）→ 抛 ValueError，不许 `errors="replace"` 静默吞；
  · archive_db：ensure 幂等 / register / content_sha256 确定性 / reset 后重建同指纹。
"""
import io
import pathlib

import pytest

from src import archive_db as DB
import archive_import as AI


# ---------------------------------------------------------------- read_csv_rows
# 与目标文件一致的 12 列 ESI 论文清单表头。
_ESI_HEADER = ["Accession Number", "DOI", "PMID", "Article Name", "Authors", "Source",
               "Research Field", "Times Cited", "Countries", "Addresses", "Institutions",
               "Publication Date"]
_DESC_LINE = ("Documents Result List:  Institutions - 'YUNNAN UNIVERSITY' "
             "Show - Top Papers")
_DATA_ROW = ["WOS:0001", "10.x", "MED:1", "TITLE", "AUTH", "SRC", "CHEM", "5",
             "CN", "ADDR", "YUNNAN UNIVERSITY", "2024-01-01"]


def _write_csv(rows, enc: str, path: pathlib.Path) -> None:
    """把内存 str 行按指定编码写盘（标准 csv 格式）。"""
    buf = io.StringIO()
    w = __import__("csv").writer(buf)
    for r in rows:
        w.writerow(r)
    path.write_bytes(buf.getvalue().encode(enc))


@pytest.mark.parametrize("enc,has_desc", [
    ("utf-8-sig", False),
    ("utf-8-sig", True),
    ("gb18030", False),
    ("gb18030", True),
    ("cp1252", False),
    ("cp1252", True),
])
def test_read_csv_rows_ok(tmp_path, enc, has_desc):
    """三种编码（含 cp1252 兜底）都能正确读出 12 列表头；说明行被跳过。"""
    rows = []
    if has_desc:
        rows.append([_DESC_LINE])
    rows.append(_ESI_HEADER)
    rows.append(_DATA_ROW)
    p = tmp_path / "p.csv"
    _write_csv(rows, enc, p)

    got = AI.read_csv_rows(p)

    # 说明行必须被丢弃：首行就是 12 列表头
    assert got[0] == _ESI_HEADER, f"{enc} 首行应为表头，实为 {got[0][:1]}"
    assert len(got[0]) == 12
    # 数据行保留
    assert got[-1] == _DATA_ROW
    # 行数：表头 + 数据（+ 说明行被吃掉）
    assert len(got) == (2 if has_desc else 2)


def test_read_csv_rows_cp1252_real_bytes(tmp_path):
    """cp1252 字节（utf-8 / gb18030 都解码失败）必须靠兜底读出，不抛。

    0xE9 ('é')：utf-8 单字节非法；其后 0x0A 让 gb18030 不成双字节 → 二者皆失败，
    只有 cp1252 能完整解码。
    """
    content = "Name,Note\nYNU,Université\n"
    p = tmp_path / "c.csv"
    p.write_bytes(content.encode("cp1252"))

    got = AI.read_csv_rows(p)

    assert got[0] == ["Name", "Note"]
    assert got[1][1] == "Université"          # 0xE9 原样还原为 U+00E9


@pytest.mark.parametrize("kind", ["invalid_bytes", "utf16_bom"])
def test_read_csv_rows_bad_bytes_never_replaced(tmp_path, kind):
    """坏字节不再抛、也不许 U+FFFD：阶段 3b 起走 utf8_latin1 逐字节保真兜底。

    阶段 1 的旧语义是「三编码都解不开 → 抛 ValueError」；阶段 3b 为保真历史散件补了
    utf8_latin1（不是 errors="replace"），坏字节按 latin-1 1:1 映射读回。
    🔴 不许改回抛错（会重新 failed），更不许出现 U+FFFD（会污染 content_sha256 指纹）。
    """
    p = tmp_path / "bad.csv"
    if kind == "invalid_bytes":
        # 0x81 在 cp1252 未定义、0x81 0x00 不成 gb18030 双字节、孤立 0x81 不是合法 UTF-8
        # → 前三种编码全失败，落 utf8_latin1 逐字节保真。
        p.write_bytes(b"Name,Note\nYNU,\x81\x00x\n")
    else:  # utf-16 BOM：含 U+0081（UTF-16LE = 0x81 0x00）同样三编码失败 → 逐字节保真
        text = "Name,Note\nYNU,\x81\n"
        p.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))

    got = AI.read_csv_rows(p)
    flat = "\x00".join(cell for row in got for cell in row)
    assert "\ufffd" not in flat               # 关键：绝不出现替换字符
    if kind == "invalid_bytes":
        assert got[1][1] == "\u0081\x00x"      # 0x81 / 0x00 各自 1:1 保真，不丢字节


def test_read_csv_rows_large_field(tmp_path):
    """超长字段（> csv 默认 131072 上限）必须正常读出，不抛 field limit 错。

    复现真实阻塞：目标文件某行 Addresses 字段约 132KB。
    """
    big = "X" * 200_000
    rows = [_ESI_HEADER, ["WOS:1", "d", "p", "t", "a", "s", "CHEM", "1", "CN", big,
                          "YUNNAN UNIVERSITY", "2024"]]
    p = tmp_path / "big.csv"
    _write_csv(rows, "utf-8-sig", p)

    got = AI.read_csv_rows(p)

    assert got[0] == _ESI_HEADER
    assert got[1][9] == big
    assert len(got[1][9]) == 200_000


def test_is_desc_line():
    """说明行识别：仅首格为 'Documents Result List: ...' 的非空说明行命中。"""
    assert AI._is_desc_line([_DESC_LINE])
    assert AI._is_desc_line([_DESC_LINE, "extra"])          # 多格也只认首格
    assert not AI._is_desc_line(_ESI_HEADER)                # 真表头不命中
    assert not AI._is_desc_line([])                         # 空行不命中
    assert not AI._is_desc_line(["Documents", "Result"])    # 断词不命中


# ---------------------------------------------------------------- ESI 榜映射（阶段 1b 修复）
def _esi_rows_202607_like():
    """模拟 202607 Chemistry.xlsx 的版式：4 空行 + 1 段落实说明行 + 真表头 + 数据。"""
    blank = [None] * 7
    para = ["Documents Result List: Institutions - 'YUNNAN UNIVERSITY' Show - Top Papers",
            None, None, None, None, None, None]     # 仅 1 个非空单元格（段落行）
    header = ["", "Institutions", "Countries/Regions", "Web of Science Documents",
              "Cites", "Cites/Paper", "Top Papers"]
    data = ["1", "CHINESE ACADEMY OF SCIENCES", "CHINA MAINLAND", "113595",
            "3433820", "30.23", "3095"]
    return [blank, blank, blank, blank, para, header, data]


def test_find_header_skips_paragraph_row():
    """表头前的段落说明行（仅 1 个非空单元格、嵌 'Institutions'）必须被跳过。

    这是阶段 1b 的真实 bug：段落行里 'institutions' 子串命中 → hi 错位 → 整表废数据。
    `_find_header` 现在要求候选行 ≥ 2 个非空单元格，段落行被排除。
    """
    rows = _esi_rows_202607_like()
    hi, h = AI._find_header(rows, "Institutions")
    assert hi == 5, hi
    assert h[1] == "Institutions"
    c = AI._esi_cols(h)
    assert c["inst"] == 1                       # 真实机构列
    assert c["rank"] == 0                        # 第 0 列空表头 = 排名列
    assert c["documents"] == 3
    assert c["cites"] == 4


def test_esi_cols_inst_column_zero_not_trapped():
    """机构列在 0 号位时，精确匹配 0 必须被认作机构列，不被 `or` 当 falsy 丢掉。"""
    h = ["Institutions", "Country", "Documents", "Cites"]
    c = AI._esi_cols(h)
    assert c["inst"] == 0                        # 精确单元格命中列 0，修复 `or` 陷阱


def test_esi_cols_202607_resolves_real_values():
    """给定 202607 表头，能正确解析出首条数据行的机构/国家/文档数/引文。"""
    rows = _esi_rows_202607_like()
    hi, h = AI._find_header(rows, "Institutions")
    c = AI._esi_cols(h)
    r = rows[6]
    inst = AI._s(r[c["inst"]]) if c["inst"] is not None and c["inst"] < len(r) else ""
    country = AI._s(r[c["country"]]) if c["country"] is not None and c["country"] < len(r) else ""
    docs = AI._int(AI._num(r[c["documents"]])) if c["documents"] is not None and c["documents"] < len(r) else None
    cites = AI._int(AI._num(r[c["cites"]])) if c["cites"] is not None and c["cites"] < len(r) else None
    assert inst == "CHINESE ACADEMY OF SCIENCES"
    assert country == "CHINA MAINLAND"
    assert docs == 113595 and cites == 3433820   # 不再是排名字符串


def _seed_discipline_rank(c, rows):
    DB.insert_rows(c, "esi_discipline_rank",
                   ["period", "discipline", "rank_no", "institution", "country", "documents",
                    "cites", "cites_per_paper", "top_papers", "top_pct", "highly_cited",
                    "highly_cited_pct", "hot_papers", "hot_pct", "file_id", "row_no"],
                   rows)


def test_value_health_rejects_broken(conn):
    """反例：整表错位（institution 存成排名、指标全 NULL）→ 必须报 FAIL。"""
    broken = [( "202607", "Chemistry", i, str(i), "", None, None,
                None, None, None, None, None, None, None, 1, i)
              for i in range(1, 101)]
    _seed_discipline_rank(conn, broken)
    assert AI._value_health(conn, emit=lambda *_: None) is False


def test_value_health_passes_good(conn):
    """正例：机构名非数字、指标非 NULL → 通过。"""
    good = [("202607", "Chemistry", i, f"INST{i}", "CHINA", 100 + i, 1000 + i,
             None, None, None, None, None, None, None, 1, i)
            for i in range(1, 101)]
    _seed_discipline_rank(conn, good)
    assert AI._value_health(conn, emit=lambda *_: None) is True


# ---------------------------------------------------------------- archive_db 收口
@pytest.fixture
def conn(tmp_path, monkeypatch):
    db = tmp_path / "archive.sqlite"
    monkeypatch.setenv("WENHENG_ARCHIVE_DB", str(db))
    c = DB.connect(db)
    DB.ensure(c)
    yield c
    c.close()


def _seed(c) -> int:
    """往一个空库塞确定性数据：files + misc_rows + esi_papers + 动态表占位。"""
    DB.ensure_subject_columns(c, [])          # 动态表 incites_subject_rows 必须先建
    fid = DB.register_file(c, kind="misc", scope="_root", rel_path="x.csv",
                           size=10, mtime_ns=1, sha256="abc", role="论文清单")
    DB.insert_rows(c, "misc_rows",
                   ["file_id", "sheet", "row_no", "raw_json"],
                   [(fid, "", 1, '["a","b"]'), (fid, "", 2, '["c","d"]')])
    DB.insert_rows(c, "esi_papers",
                   ["period", "kind", "title", "authors", "source", "pub_year",
                    "pub_date", "times_cited", "discipline", "raw_json",
                    "file_id", "row_no"],
                   [("202607", "school_list", "T", "A", "S", 2024, "2024", 5,
                     "CHEM", '["x"]', fid, 1)])
    c.commit()
    return fid


def test_ensure_idempotent(conn):
    """ensure 幂等：连跑两次不报错，静态表都在。"""
    DB.ensure(conn)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("files", "esi_papers", "misc_rows", "incites_metrics"):
        assert t in names


def test_ensure_subject_columns_creates_dynamic(conn):
    """动态表 `incites_subject_rows` 由 ensure_subject_columns 建（ensure 不建），且幂等。"""
    assert "incites_subject_rows" not in {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    DB.ensure_subject_columns(conn, [])
    DB.ensure_subject_columns(conn, [])
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "incites_subject_rows" in names


def test_register_and_set_parse(conn):
    """register_file 幂等键 + set_file_parse 回写解析结果。"""
    fid = DB.register_file(conn, kind="misc", scope="_root", rel_path="x.csv",
                           size=10, mtime_ns=1, sha256="abc", role="论文清单")
    assert fid >= 1
    DB.set_file_parse(conn, fid, status="parsed", rows=3)
    row = conn.execute("SELECT parse_status, parse_rows FROM files WHERE id=?",
                       (fid,)).fetchone()
    assert row["parse_status"] == "parsed" and row["parse_rows"] == 3


def test_content_sha256_deterministic(conn):
    """同输入 → 同指纹（逐表按主键序扫行，不依赖 meta）。"""
    _seed(conn)
    h1 = DB.content_sha256(conn)
    h2 = DB.content_sha256(conn)
    assert len(h1) == 64
    assert h1 == h2


def test_reset_rebuild_deterministic(conn):
    """reset() 清空重建后，重放相同数据 → 指纹与重建前一致（派生物可确定性重建）。"""
    _seed(conn)
    h_before = DB.content_sha256(conn)
    DB.reset(conn)
    _seed(conn)
    h_after = DB.content_sha256(conn)
    assert h_after == h_before


def test_content_sha256_ignores_meta(conn):
    """meta 不参与指纹：写 meta 不应改变 content_sha256。"""
    _seed(conn)
    h1 = DB.content_sha256(conn)
    DB.put_meta(conn, "built_at", "2026-11-06T00:00:00")
    DB.put_meta(conn, "content_sha256", "deadbeef")
    h2 = DB.content_sha256(conn)
    assert h1 == h2


# ---------------------------------------------------------------- 阶段 3b：年份窗口归一 / 护栏 / 编码 / 退出码 / stash 分流
def test_norm_label_year_window_collapses():
    """同概念、不同年份/时间窗口 → 同一 label_norm（归一成 (WINDOW)）。

    阶段 3 全量导入实测：45 快照表头字典并集 326 > 护栏 200 → 1108 件 InCites failed；
    根因就是窗口片段跨期漂移各占一个 slug。阶段 3b 归一后并集降到 290。
    """
    groups = [
        ("% First Author (2008-Present)", "% First Author (2008-2020)",
         "% First Author （2008-2024）"),
        ("Cites (2008-Present)", "Cites (2008-2021)", "Cites (2016-2026.08.31)"),
    ]
    for variants in groups:
        norms = {DB.norm_label(v) for v in variants}
        assert len(norms) == 1, f"同概念不同窗口应归一到同一 label_norm：{variants} → {norms}"
        assert "(WINDOW)" in norms.pop()
    # 不同概念不得被误合并（窗口归一只替换窗口片段，前缀仍在）
    assert DB.norm_label("Cites (2008-Present)") != DB.norm_label("Cites/Paper (2008-Present)")
    # 不含窗口的普通表头不受影响
    assert DB.norm_label("Web of Science 论文数") == "Web of Science 论文数"


def test_norm_label_deterministic():
    """确定性：同输入多次调用同一结果（content_sha256 依赖重放顺序）。"""
    s = "% First Author （2008-2020）"
    assert len({DB.norm_label(s) for _ in range(20)}) == 1
    assert DB.norm_label(s) == DB.norm_label(s)


def test_year_window_reuses_metric_slug(conn):
    """同概念不同窗口 → 复用同一 slug；不同概念仍分配不同 slug。"""
    s1 = DB.metric_slug(conn, "% First Author (2008-Present)")
    s2 = DB.metric_slug(conn, "% First Author (2008-2020)")
    s3 = DB.metric_slug(conn, "% First Author （2008-2024）")
    assert s1 == s2 == s3
    s4 = DB.metric_slug(conn, "Cites (2008-Present)")
    assert s4 != s1
    # incites_metrics 只记了 2 个 slug（不是每个窗口一个）
    n = conn.execute("SELECT COUNT(*) AS n FROM incites_metrics").fetchone()["n"]
    assert n == 2


def test_metric_slug_guardrail_still_enforced(conn, monkeypatch):
    """护栏仍在：调到 400 不等于删护栏——并集触顶仍抛 RuntimeError，不许静默写坏。"""
    assert DB.MAX_METRIC_COLUMNS == 400        # 阶段 3b 实测值（原 200 触发 1108 件 failed）
    assert DB.MAX_METRIC_COLUMNS < 2000        # 远低于 SQLite 默认 2000 列上限
    monkeypatch.setattr(DB, "MAX_METRIC_COLUMNS", 3)
    for i in range(3):
        DB.metric_slug(conn, f"指标{i}")
    with pytest.raises(RuntimeError, match="列上限"):
        DB.metric_slug(conn, "指标超阈值")


@pytest.mark.parametrize("bad_byte", [0x81, 0x8D, 0x8F, 0x90, 0x9D])
def test_read_csv_rows_utf8_latin1_preserves_bytes(tmp_path, bad_byte):
    """utf8_latin1 兜底：主体 UTF-8 中文 + 孤立 cp1252 未定义字节 → 逐字节保真、无 U+FFFD、不丢列。

    坏字节紧跟逗号（0x2C < 0x40，gb18030 不成双字节）→ utf-8-sig/gb18030/cp1252 全失败，
    落 utf8_latin1；这 5 个是 cp1252 仅有的未定义码位。
    """
    raw = ("名称,备注,数值\n云南大学,A".encode("utf-8")
           + bytes([bad_byte]) + b",42\n")
    p = tmp_path / "enc.csv"
    p.write_bytes(raw)

    got = AI.read_csv_rows(p)

    assert got[0] == ["名称", "备注", "数值"]     # 主体中文按 UTF-8 正确还原
    assert len(got[1]) == 3                       # 不丢列
    assert got[1][0] == "云南大学"
    assert got[1][1] == "A" + chr(bad_byte)       # 坏字节 1:1 映射成同码点，不丢字节
    assert got[1][2] == "42"
    assert "\ufffd" not in "\x00".join(c for r in got for c in r)   # 不是 errors="replace"


@pytest.mark.parametrize("has_failed,expected_rc", [(False, 0), (True, 1)])
def test_main_exit_code_on_failed(tmp_path, monkeypatch, has_failed, expected_rc):
    """退出码语义（§8.3 根治「EXIT 0 但 1177 失败」）：库里有 failed → main 返回 1，无 → 0。

    用 monkeypatch 替换 import_kind，只往临时库塞一条指定状态的文件行，不碰真实数据目录。
    """
    db = tmp_path / "exit.sqlite"

    def fake_import_kind(conn, kind, scopes=None, *, force=False, emit=print):
        DB.register_file(conn, kind="misc", scope="_root", rel_path="x.csv",
                         size=1, mtime_ns=1, sha256="x")
        conn.execute("UPDATE files SET parse_status=? WHERE rel_path='x.csv'",
                     ("failed" if has_failed else "parsed",))
        conn.commit()
        return {"files": 1, "parsed": 1, "recovered": 0, "skipped": 0,
                "rows": 0, "failed": 0}

    monkeypatch.setattr(AI, "import_kind", fake_import_kind)
    rc = AI.main(["--kind", "misc", "--db", str(db)])
    assert rc == expected_rc


@pytest.mark.parametrize("exc,expect_status,expect_err", [
    (ValueError("未识别表头：研究领域"), "stashed", ""),
    (ValueError("没有可解析行"), "stashed", ""),
    (RuntimeError("磁盘读失败"), "failed", "RuntimeError"),
    (ValueError("其它真错误"), "failed", "ValueError"),
])
def test_import_kind_stash_routing(conn, tmp_path, monkeypatch, exc, expect_status, expect_err):
    """stash 分流：仅「未识别表头／没有可解析行」转 stashed，其它异常仍 failed（不洗白真失败）。

    monkeypatch SI.iter_files / kind_root / _parse_one 到 tmp_path 沙箱，不碰 数据与复现/。
    """
    scope = "s1"
    fake = tmp_path / scope / "data.csv"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_bytes(b"a,b\n1,2\n")

    monkeypatch.setattr(AI.SI, "kind_root", lambda kind, data_root=None: tmp_path)
    monkeypatch.setattr(AI.SI, "iter_files",
                        lambda kind, data_root=None: iter([(scope, "data.csv", fake)]))

    def boom(*_a, **_kw):
        raise exc
    monkeypatch.setattr(AI, "_parse_one", boom)

    AI.import_kind(conn, "esi", None, emit=lambda *_: None)

    row = conn.execute(
        "SELECT parse_status, parse_error, note, parse_rows FROM files"
        " WHERE kind='esi' AND scope=? AND rel_path='data.csv'", (scope,)).fetchone()
    assert row is not None
    assert row["parse_status"] == expect_status, row["parse_error"]
    if expect_status == "stashed":
        assert "表头未识别" in row["note"]
        assert row["parse_rows"] >= 1           # 整件 misc_rows 保真确实落了行
        assert not row["parse_error"]
        n = conn.execute("SELECT COUNT(*) AS n FROM misc_rows").fetchone()["n"]
        assert n >= 1
    else:
        assert expect_err in row["parse_error"]
