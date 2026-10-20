# -*- coding: utf-8 -*-
"""往期 ESI 包统一命名（tools/normalize_esi_names.py）：按内容认、改名、归档、可重复跑。

只用 tmp 合成目录，**绝不碰真 数据与复现/**（工具默认 dry-run；这里连 --write 都指向 tmp）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import openpyxl
import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src"), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import normalize_esi_names as N                                # noqa: E402


def _xlsx(path: pathlib.Path, rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)


def _fields_rows(n: int = 22) -> list[list]:
    rows: list[list] = [["Indicators Results List: Research Fields"],
                        ["Research Fields", "Web of Science Documents", "Cites", "Cites/Paper",
                         "Top Papers"]]
    rows += [[f"FIELD {i}", i, i * 2, 2.0, 1] for i in range(n)]
    return rows


def _papers_rows(n: int = 18) -> list[list]:
    rows: list[list] = [["Documents Result List: Institutions"],
                        ["Accession Number", "DOI", "Article Name", "Authors"]]
    rows += [[f"WOS:{i:015d}", f"10.1/x{i}", f"TITLE {i}", "AUTHOR, A"] for i in range(n)]
    return rows


def _institutions_rows(n: int = 600) -> list[list]:
    rows: list[list] = [["Indicators Results List: Institutions"],
                        ["Institutions", "Countries/Regions", "Web of Science Documents"]]
    rows += [[f"INST {i}", "CHINA MAINLAND", 1000 + i] for i in range(n)]
    return rows


def _mk_period(tmp_path: pathlib.Path) -> pathlib.Path:
    d = tmp_path / "202601"
    d.mkdir(parents=True)
    _xlsx(d / "Institutions.xlsx", _institutions_rows())
    _xlsx(d / "Environment Ecology.xlsx", _institutions_rows(50))     # 学科表（名字带空格的坑）
    _xlsx(d / "ResearchFields.xlsx", _fields_rows(25))
    _xlsx(d / "CHINA MAINLAND.xlsx", _fields_rows(28))
    _xlsx(d / "YUNNAN UNIVERSITY.xlsx", _fields_rows(20))
    _xlsx(d / "top paper12.xlsx", _papers_rows(18))                   # 20 行 − 8 = 12
    _xlsx(d / "top12按发文量排序.xlsx", _papers_rows(18))              # 派生视图 → 归档
    _xlsx(d / "243Highly Cited Papers.xlsx", _papers_rows(19))         # 21 行 − 8 = 13
    _xlsx(d / "202601ESI总表模板.xlsx", [["英文单位", "中国单位", "省份", "机构类型"]] * 3)
    (d / "_下载信息.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_计划_按内容认_不误伤学科表(tmp_path):
    root = _mk_period(tmp_path)
    plan = N.plan_period("202601", root)
    ren = {src.name: dst for src, dst, _ in plan["rename"]}
    assert ren == {
        "ResearchFields.xlsx": "全球学科.xlsx",
        "CHINA MAINLAND.xlsx": "中国学科.xlsx",
        "YUNNAN UNIVERSITY.xlsx": "云大学科.xlsx",
        "top paper12.xlsx": "12top.xlsx",
        "243Highly Cited Papers.xlsx": "13highly cited.xlsx",
    }
    arch = {src.name for src, _ in plan["archive"]}
    assert arch == {"202601ESI总表模板.xlsx", "top12按发文量排序.xlsx"}
    assert "Environment Ecology.xlsx" not in arch, "学科表（名字里的 / 换空格）不能被当归档"
    assert "_下载信息.json" not in arch


def test_执行_改名归档并留痕_重复跑无动作(tmp_path):
    root = _mk_period(tmp_path)
    plan = N.plan_period("202601", root)
    rec = N.apply_plan(plan, root, write=True)
    d = root / "202601"
    assert (d / "全球学科.xlsx").exists() and not (d / "ResearchFields.xlsx").exists()
    assert (d / "12top.xlsx").exists()
    assert (d / "Environment Ecology.xlsx").exists()
    arch = root / N.ARCHIVE_DIRNAME / "202601"
    assert (arch / "202601ESI总表模板.xlsx").exists()
    manifest = json.loads((arch / "_改名记录.json").read_text(encoding="utf-8"))
    assert len(manifest["renamed"]) == 5 and len(manifest["archived"]) == 2
    assert rec["period"] == "202601"

    again = N.plan_period("202601", root)
    assert again["rename"] == [] and again["archive"] == [], "第二次跑应无事可做"


def test_目标已存在_不覆盖_源进归档(tmp_path):
    root = _mk_period(tmp_path)
    (root / "202601" / "全球学科.xlsx").write_bytes(b"already-here")
    plan = N.plan_period("202601", root)
    ren = {src.name: dst for src, dst, _ in plan["rename"]}
    assert "ResearchFields.xlsx" not in ren, "目标已存在时不得改名覆盖"
    arch = {src.name for src, _ in plan["archive"]}
    assert "ResearchFields.xlsx" in arch, "重复件应进归档"


def test_拒绝_目标存在时apply不覆盖(tmp_path):
    root = _mk_period(tmp_path)
    (root / "202601" / "全球学科.xlsx").write_bytes(b"already-here")
    plan = N.plan_period("202601", root)
    # 手工塞一个会被改名且目标存在的冲突pair，确认 apply 直接拒绝
    src = root / "202601" / "CHINA MAINLAND.xlsx"
    plan["rename"].append((src, "全球学科.xlsx", "test"))
    with pytest.raises(SystemExit):
        N.apply_plan(plan, root, write=True)
