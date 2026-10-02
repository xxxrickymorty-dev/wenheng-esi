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


def _synth_ledger(path):
    """手写最小台账：rels 是 Type/Target/Id 序、sheet 元素 r:id 在 name 前——
    正是旧 `_sheet_member` 顺序敏感正则必失配的形态（openpyxl 不再产 sharedStrings）。"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml",
                    '<workbook><sheets><sheet r:id="rId1" name="千分之一被引阈值"/>'
                    "</sheets></workbook>")
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<Relationships><Relationship Type="t" '
                    'Target="worksheets/sheet1.xml" Id="rId1"/></Relationships>')
        zf.writestr("xl/sharedStrings.xml",
                    "<sst><si><t>学科</t></si><si><t>化学</t></si></sst>")
        zf.writestr("xl/worksheets/sheet1.xml",
                    "<worksheet><sheetData>"
                    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>202601</v></c></row>'
                    '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>42</v></c></row>'
                    "</sheetData></worksheet>")
    return pathlib.Path(path)


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


class Test写手回归:
    def test_read_sheet_table吃属性乱序的文件(self, tmp_path):
        """旧 `_sheet_member` 的 `Id→Target` 顺序敏感正则在这份文件上必失配；
        改走 xlsx_io 后两种属性序都能读。"""
        import extract_1permille as e1
        p = _synth_ledger(tmp_path / "ledger.xlsx")
        periods, table = e1.read_sheet_table(p)
        assert periods == ["202601"]
        assert table["化学"]["202601"] == "42"

    def test_update_ledger在乱序文件上可写且值落位(self, tmp_path):
        import extract_1permille as e1
        p = _synth_ledger(tmp_path / "ledger.xlsx")
        periods, is_new = e1.update_ledger(p, "202601", {"化学": 42})   # 同值不冲突
        assert is_new is False
        _, table = e1.read_sheet_table(p)
        assert table["化学"]["202601"] == "42"


class TestSha256:
    def test_与一次性哈希一致_跨分块(self, tmp_path):
        p = tmp_path / "big.bin"
        blob = b"wenheng" * (200_000)          # ~1.4 MiB，跨 1 MiB 分块
        p.write_bytes(blob)
        assert xlsx_io.sha256_file(p) == hashlib.sha256(blob).hexdigest()

    def test_缺文件抛(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            xlsx_io.sha256_file(tmp_path / "nope.xlsx")
