# -*- coding: utf-8 -*-
"""`src/xlsx_io.py`：zip 级原语的机械保证（属性序 / 逐字节 / 良构闸 / 指纹）。"""
import hashlib
import pathlib
import zipfile

import openpyxl
import pytest

import xlsx_io


def _make_xlsx(path, sheets=("数据", "千分之一被引阈值")):
    """openpyxl 生成——它的 rels 是 Type/Target/Id 序，正是旧正则的失配场景。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheets[0]
    ws["A1"], ws["B1"] = "指标", "值"
    ws["A2"], ws["B2"] = "论文", 3
    if len(sheets) > 1:
        ws2 = wb.create_sheet(sheets[1])
        ws2["A1"], ws2["B1"] = "学科", "202601"
        ws2["A2"], ws2["B2"] = "化学", 42
    wb.save(path)
    return pathlib.Path(path)


def _members(path):
    with zipfile.ZipFile(path) as zf:
        return {i.filename: zf.read(i.filename) for i in zf.infolist()}


class TestMemberOf:
    def test_openpyxl属性序也能认(self, tmp_path):
        p = _make_xlsx(tmp_path / "t.xlsx")
        with zipfile.ZipFile(p) as zf:
            m = xlsx_io.member_of(zf, "千分之一被引阈值")
        assert "worksheets/sheet" in m
        assert m in _members(p)

    def test_没有的sheet报KeyError(self, tmp_path):
        p = _make_xlsx(tmp_path / "t.xlsx")
        with zipfile.ZipFile(p) as zf, pytest.raises(KeyError):
            xlsx_io.member_of(zf, "不存在的表")

    def test_共享串表缺成员给空表(self, tmp_path):
        p = tmp_path / "min.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("xl/workbook.xml", "<workbook/>")
        with zipfile.ZipFile(p) as zf:
            assert xlsx_io.read_shared_strings(zf) == []


class TestRewrite:
    def test_只换目标成员_其余逐字节相同(self, tmp_path):
        p = _make_xlsx(tmp_path / "t.xlsx")
        before = _members(p)
        with zipfile.ZipFile(p) as zf:
            target = xlsx_io.member_of(zf, "数据")
        patched = before[target].decode("utf-8").replace(
            "</worksheet>", "<!-- patched --></worksheet>")
        xlsx_io.rewrite(p, {target: patched})
        after = _members(p)
        assert set(after) == set(before)
        for name in before:
            if name == target:
                assert after[name] != before[name]
            else:
                assert after[name] == before[name], f"非目标成员被动过：{name}"
        openpyxl.load_workbook(p)          # 改写后仍能被 Excel 读

    def test_坏XML被良构闸拦住_文件一字节不动(self, tmp_path):
        p = _make_xlsx(tmp_path / "t.xlsx")
        before = p.read_bytes()
        with zipfile.ZipFile(p) as zf:
            target = xlsx_io.member_of(zf, "数据")
        with pytest.raises(SystemExit):
            xlsx_io.rewrite(p, {target: "<worksheet>"})
        assert p.read_bytes() == before

    def test_dry只过闸不落盘(self, tmp_path):
        p = _make_xlsx(tmp_path / "t.xlsx")
        before = p.read_bytes()
        with zipfile.ZipFile(p) as zf:
            target = xlsx_io.member_of(zf, "数据")
        xlsx_io.rewrite(p, {target: "<worksheet/>"}, dry=True)
        assert p.read_bytes() == before


class TestSha256:
    def test_与一次性哈希一致_跨分块(self, tmp_path):
        p = tmp_path / "big.bin"
        blob = b"wenheng" * (200_000)          # ~1.4 MiB，跨 1 MiB 分块
        p.write_bytes(blob)
        assert xlsx_io.sha256_file(p) == hashlib.sha256(blob).hexdigest()

    def test_缺文件抛(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            xlsx_io.sha256_file(tmp_path / "nope.xlsx")
