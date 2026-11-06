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
def test_read_csv_rows_rejects(tmp_path, kind):
    """非法字节 / utf-16 BOM（三编码都解不开）→ 抛 ValueError，不静默吞坏字节。"""
    p = tmp_path / "bad.csv"
    if kind == "invalid_bytes":
        # 0x81 在 cp1252 未定义（cp1252 仅 5 个码位无映射），且 0x81 0x00 不成 gb18030
        # 双字节序列（尾字节须 0x40-0xFE）→ 三编码全部失败。
        p.write_bytes(b"Name,Note\nYNU,\x81\x00x\n")
    else:  # utf-16 BOM：含 U+0081（UTF-16LE = 0x81 0x00）→ cp1252 解不开 → 抛
        text = "Name,Note\nYNU,\x81\n"
        p.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))

    with pytest.raises(ValueError):
        AI.read_csv_rows(p)


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
