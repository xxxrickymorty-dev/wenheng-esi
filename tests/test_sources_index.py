# -*- coding: utf-8 -*-
"""数据来源清单（`tools/sources_index.py` + `sources` 表，迁移 004）。

判据：清单是**磁盘的镜子**——扫描入库、重跑幂等、`size+mtime` 没变时 `--hash` 不重算、
变了要重算、`check` 三类判得准、`export-md` 内容可读、**库不存在时 check 不建库不删东西**。
全部用 tmp 合成目录，**不碰真实的 `../数据与复现/`（9 GB）**。
"""
import json
import sqlite3

import pytest

import sources_index
from src import state_store


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


@pytest.fixture
def data(tmp_path):
    """合成数据根：ESI 两期 + 一根散件 + 嵌套子目录；InCites 一个快照 + 一根 zip。"""
    root = tmp_path / "数据与复现"
    _write(root / "ESI数据" / "202607" / "Institutions.xlsx", "a" * 100)
    _write(root / "ESI数据" / "202607" / "云大学科.xlsx", "b" * 200)
    _write(root / "ESI数据" / "202609" / "Institutions.xlsx", "c" * 300)
    _write(root / "ESI数据" / "ESI总表模板.xlsx", "t" * 10)          # scope = _root
    _write(root / "ESI数据" / "_归档统一命名" / "202607" / "x.json", "{}")
    _write(root / "incites" / "数据覆盖2016-2026.08.31" / "全球机构排名.xlsx", "d" * 400)
    _write(root / "incites" / "数据覆盖2016-2026.08.31" / "全球 研究领域.xlsx", "e" * 50)
    _write(root / "incites" / "数据覆盖2016-2026.08.31.zip", "z" * 20)
    return root


def _db(tmp_path):
    return tmp_path / "out" / "_state" / "wenheng.sqlite"


def _rows(db, **kw):
    return state_store.sources_rows(db, **kw)


# ---------------------------------------------------------------- 扫描入库
def test_扫描入库_记元数据且默认不算指纹(data, tmp_path):
    db = _db(tmp_path)
    assert not db.exists()

    summary = sources_index.scan(db, kind="all", data_root=data, emit=lambda *_: None)

    assert summary["esi"]["files"] == 5 and summary["incites"]["files"] == 3
    assert summary["esi"]["bytes"] == 100 + 200 + 300 + 10 + 2
    rows = _rows(db)
    assert len(rows) == 8
    assert {r["kind"] for r in rows} == {"esi", "incites"}
    assert {r["sha256"] for r in rows} == {""}, "默认只元数据，指纹留空"
    assert {(r["kind"], r["scope"]) for r in rows} >= {
        ("esi", "202607"), ("esi", "202609"), ("esi", "_root"),
        ("esi", "_归档统一命名"), ("incites", "数据覆盖2016-2026.08.31"),
        ("incites", "_root")}
    one = next(r for r in rows if r["rel_path"].endswith("202607/云大学科.xlsx"))
    assert one["rel_path"] == "ESI数据/202607/云大学科.xlsx", "rel_path 相对数据根"
    assert one["size"] == 200 and one["mtime_ns"] > 0
    assert one["payload"] == {}


def test_裸目录之外的子目录也记全(data, tmp_path):
    """`_归档统一命名/202607/` 这类嵌套目录：scope 取第一层，路径记全。"""
    db = _db(tmp_path)
    sources_index.scan(db, kind="esi", data_root=data, emit=lambda *_: None)
    paths = [r["rel_path"] for r in _rows(db, kind="esi", scope="_归档统一命名")]
    assert paths == ["ESI数据/_归档统一命名/202607/x.json"]


def test_重复扫描幂等_库内容逐行不变(data, tmp_path):
    db = _db(tmp_path)
    sources_index.scan(db, kind="all", data_root=data, emit=lambda *_: None)
    first = _rows(db)

    summary = sources_index.scan(db, kind="all", data_root=data, emit=lambda *_: None)

    assert summary["esi"]["added"] == 0 and summary["esi"]["updated"] == 0
    assert summary["esi"]["kept"] == 5
    assert _rows(db) == first, "重跑同样的目录：行、大小、时间、scanned_at 都不该变"


def test_scan按kind与scope过滤(data, tmp_path):
    db = _db(tmp_path)
    sources_index.scan(db, kind="esi", scope="202609", data_root=data, emit=lambda *_: None)

    rows = _rows(db)
    assert [(r["kind"], r["scope"]) for r in rows] == [("esi", "202609")]


# ---------------------------------------------------------------- 增量指纹
def test_hash在元数据未变时不重算(data, tmp_path, monkeypatch):
    db = _db(tmp_path)
    calls = []
    real = sources_index.sha256_file

    def probe(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(sources_index, "sha256_file", probe)
    sources_index.scan(db, kind="esi", do_hash=True, data_root=data, emit=lambda *_: None)
    assert len(calls) == 5                        # 第一次：全算

    calls.clear()
    summary = sources_index.scan(db, kind="esi", do_hash=True, data_root=data,
                                 emit=lambda *_: None)
    assert calls == [], "size + mtime_ns 都没变 → 一次都不该重算"
    assert summary["esi"]["hash_skipped"] == 5 and summary["esi"]["hashed"] == 0
    assert all(r["sha256"] for r in _rows(db, kind="esi"))


def test_hash缺指纹的行照算(data, tmp_path):
    db = _db(tmp_path)
    sources_index.scan(db, kind="esi", data_root=data, emit=lambda *_: None)   # 只有元数据
    assert all(r["sha256"] == "" for r in _rows(db))

    summary = sources_index.scan(db, kind="esi", do_hash=True, data_root=data,
                                 emit=lambda *_: None)
    assert summary["esi"]["hashed"] == 5 and summary["esi"]["hash_skipped"] == 0
    assert all(len(r["sha256"]) == 64 for r in _rows(db, kind="esi"))


def test_改了文件要重算指纹(data, tmp_path, monkeypatch):
    db = _db(tmp_path)
    sources_index.scan(db, kind="esi", do_hash=True, data_root=data, emit=lambda *_: None)
    before = {r["rel_path"]: r["sha256"] for r in _rows(db, kind="esi")}

    target = data / "ESI数据" / "202607" / "Institutions.xlsx"
    target.write_bytes(b"changed" * 5)            # 大小也变了
    calls = []
    real = sources_index.sha256_file
    monkeypatch.setattr(sources_index, "sha256_file",
                        lambda p: (calls.append(str(p)), real(p))[1])

    summary = sources_index.scan(db, kind="esi", do_hash=True, data_root=data,
                                 emit=lambda *_: None)

    assert calls == [str(target)], "只重算变了的那一个"
    assert summary["esi"]["updated"] == 1 and summary["esi"]["kept"] == 4
    after = {r["rel_path"]: r["sha256"] for r in _rows(db, kind="esi")}
    assert after["ESI数据/202607/Institutions.xlsx"] != before["ESI数据/202607/Institutions.xlsx"]
    assert {k: v for k, v in after.items() if "Institutions" not in k} == \
        {k: v for k, v in before.items() if "Institutions" not in k}


def test_扫描发现文件没了会移除该行(data, tmp_path, capsys):
    db = _db(tmp_path)
    sources_index.scan(db, kind="esi", scope="202607", data_root=data, emit=print)
    (data / "ESI数据" / "202607" / "云大学科.xlsx").unlink()

    summary = sources_index.scan(db, kind="esi", scope="202607", data_root=data, emit=print)

    assert summary["esi"]["removed"] == 1
    assert [r["rel_path"] for r in _rows(db)] == ["ESI数据/202607/Institutions.xlsx"]
    assert "移除" in capsys.readouterr().out


# ---------------------------------------------------------------- check
def test_check三类判定(data, tmp_path, capsys):
    db = _db(tmp_path)
    sources_index.scan(db, kind="all", do_hash=True, data_root=data, emit=lambda *_: None)
    capsys.readouterr()

    _write(data / "ESI数据" / "202609" / "新增.xlsx", "new" * 10)     # 新增
    (data / "ESI数据" / "202607" / "云大学科.xlsx").write_bytes(b"b" * 999)  # 变了
    (data / "incites" / "数据覆盖2016-2026.08.31" / "全球 研究领域.xlsx").unlink()  # 没了

    result = sources_index.check(db, kind="all", data_root=data)

    assert result["added"] == ["esi · 202609 · ESI数据/202609/新增.xlsx（30 B）"]
    assert len(result["changed"]) == 1 and "大小 200 → 999" in result["changed"][0]
    assert result["removed"] == ["incites · 数据覆盖2016-2026.08.31 · incites/数据覆盖2016-2026.08.31/全球 研究领域.xlsx"]

    out = capsys.readouterr().out
    assert "新增 1" in out and "变了 1" in out and "没了 1" in out


def test_check无变化时明确说无变化(data, tmp_path):
    db = _db(tmp_path)
    sources_index.scan(db, kind="all", do_hash=True, data_root=data, emit=lambda *_: None)
    lines = []
    result = sources_index.check(db, kind="all", data_root=data, emit=lines.append)

    assert result["added"] == [] and result["changed"] == [] and result["removed"] == []
    assert any("结论：无变化" in line for line in lines)


def test_check_hash能发现同尺寸同时间的篡改(data, tmp_path):
    """元数据没变、内容被换：只有 `--hash` 看得见（这也是它默认不算的理由）。"""
    db = _db(tmp_path)
    sources_index.scan(db, kind="esi", do_hash=True, data_root=data, emit=lambda *_: None)
    target = data / "ESI数据" / "202607" / "Institutions.xlsx"
    st = target.stat()
    target.write_bytes(b"y" * 100)                # 同尺寸
    import os
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))   # 时间也复原

    assert sources_index.check(db, kind="esi", data_root=data,
                               emit=lambda *_: None)["changed"] == []
    lines = sources_index.check(db, kind="esi", do_hash=True, data_root=data,
                                emit=lambda *_: None)["changed"]
    assert len(lines) == 1 and "指纹" in lines[0]


def test_check在库不存在时不建库不删东西(data, tmp_path, capsys):
    db = _db(tmp_path)
    before = sorted(p.as_posix() for p in data.rglob("*"))

    result = sources_index.check(db, kind="all", data_root=data)

    assert result["db_exists"] is False
    assert not db.exists(), "读口不建库"
    assert not db.parent.exists()
    assert sorted(p.as_posix() for p in data.rglob("*")) == before
    assert "状态库不存在" in capsys.readouterr().out


# ---------------------------------------------------------------- export-md
def test_export_md产物含汇总与明细(data, tmp_path):
    db = _db(tmp_path)
    sources_index.scan(db, kind="all", do_hash=True, data_root=data, emit=lambda *_: None)
    out = tmp_path / "out" / "_state" / "sources.md"

    sources_index.export_md(db, out, emit=lambda *_: None)
    text = out.read_text(encoding="utf-8")

    assert text.startswith("# 数据来源清单")
    assert "原始文件不入库" in text and "inventory.py" in text
    assert "## ESI数据（`kind=esi`）" in text and "## incites（`kind=incites`）" in text
    assert "| `202607` | 2 |" in text
    assert "### ESI数据 · `202607`（2 文件" in text
    assert "`ESI数据/202607/云大学科.xlsx`" in text
    assert "—" not in text.split("### ESI数据 · `202607`")[1].split("###")[0], "算过指纹就不该出现 —"


def test_export_md空库给说明而不是假清单(tmp_path):
    db = _db(tmp_path)
    out = tmp_path / "sources.md"
    sources_index.export_md(db, out, emit=lambda *_: None)
    text = out.read_text(encoding="utf-8")
    assert "还没有清单" in text and not db.exists()


def test_export_md不写数据目录(data, tmp_path):
    db = _db(tmp_path)
    sources_index.scan(db, kind="all", data_root=data, emit=lambda *_: None)
    before = sorted(p.as_posix() for p in data.rglob("*"))

    sources_index.export_md(db, emit=lambda *_: None,
                            out_path=data / ".." / "out" / "sources.md")

    assert sorted(p.as_posix() for p in data.rglob("*")) == before, "数据目录一个文件都不该多"


# ---------------------------------------------------------------- 命令入口
def test_命令入口scan_check_export(data, tmp_path, capsys):
    db = tmp_path / "out" / "_state" / "wenheng.sqlite"
    base = ["--db", str(db), "--data-root", str(data)]

    assert sources_index.main(base + ["scan", "--kind", "esi", "--hash"]) == 0
    out = capsys.readouterr().out
    assert "esi 合计：5 文件" in out

    assert sources_index.main(base + ["check", "--kind", "esi"]) == 0
    assert "结论：无变化" in capsys.readouterr().out

    md = tmp_path / "out" / "_state" / "sources.md"
    assert sources_index.main(base + ["export-md", "--out", str(md)]) == 0
    assert md.is_file()


# ---------------------------------------------------------------- 表与迁移
def test_003库升级到004不丢数据且补上sources表(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    con = sqlite3.connect(str(db))
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL,"
                    " note TEXT NOT NULL DEFAULT '')")
        for fn in (state_store._migrate_001, state_store._migrate_002,
                   state_store._migrate_003):
            fn(con)
        con.execute("INSERT INTO approvals (period, actor, signed_at, payload)"
                    " VALUES (?, ?, ?, ?)",
                    ("202607", "rick", "t", json.dumps({"signed": True})))
        con.execute("INSERT INTO manual_inputs (period, slot, payload)"
                    " VALUES (?, ?, ?)", ("202607", "正文/p4::学科数", json.dumps({"value": "19"})))
        for mid in ("001-approvals-reviews", "002-jobs", "003-manual-inputs"):
            con.execute("INSERT INTO migrations (id, applied_at, note) VALUES (?, 't', '')", (mid,))
        con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")
        con.commit()
    finally:
        con.close()

    assert state_store.get_approval(db, "202607")["signed"] is True
    assert state_store.get_fills(db, "202607")["正文/p4::学科数"]["value"] == "19"
    assert state_store.sources_rows(db) == []                    # 打开即补 004
    assert state_store.health(db)["schema_version"] == state_store.SCHEMA_VERSION
    with sqlite3.connect(str(db)) as con:
        ids = {r[0] for r in con.execute("SELECT id FROM migrations")}
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert ids == {m["id"] for m in state_store.MIGRATIONS}
    assert "sources" in tables


def test_来源词条非法不落行(tmp_path):
    db = tmp_path / "wenheng.sqlite"
    bad = [
        {"kind": "ftp", "scope": "x", "rel_path": "a"},
        {"kind": "esi", "scope": "", "rel_path": "a"},
        {"kind": "esi", "scope": "202607", "rel_path": ""},
        {"kind": "esi", "scope": "202607", "rel_path": "a", "payload": "x"},
    ]
    for entry in bad:
        with pytest.raises(state_store.StoreError):
            state_store.put_sources(db, [entry])
    assert state_store.sources_rows(db) == []
