# -*- coding: utf-8 -*-
"""period_facts「出过稿凭证」口径回归：半途 run 不再让整期从 API 消失。

2026-10-17 实案：run 在撤下上版成品后死在 red_slots 落盘之前 → out/202609
有报告初稿与 meta.json、无 red_slots.json → `resolve()` 判整期不存在 →
工作台 / 报告预览 / 大纲全线 404（rick 2026-10-24 报「下架后后续都无法使用」）。

口径（2026-10-24 定）：凭证放宽为「red_slots.json 或（报告初稿 docx＋meta.json）」；
`facts.generate_ok` **不**放宽——三步条的「生成」仍只认 red_slots，
半途期次诚实显示「卡在生成」，指回生成台或「回滚到上一版」（票 07 入口）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import period_facts  # noqa: E402


def _mk(root, name, *, red=False, docx=False, meta=False):
    d = root / name
    d.mkdir(parents=True)
    if red:
        (d / "red_slots.json").write_text("[]", encoding="utf-8")
    if docx:
        (d / "报告初稿_202609（试排）.docx").write_bytes(b"x")
    if meta:
        (d / "meta.json").write_text("{}", encoding="utf-8")
    return d


def test_全凭证期次照旧可认(tmp_path):
    _mk(tmp_path, "202609", red=True)
    assert period_facts.resolve("202609", out_root=tmp_path) is not None


def test_半途期次_docx加meta可认(tmp_path):
    """本修的主场景：red_slots 没出，但报告初稿在——期次必须可见。"""
    _mk(tmp_path, "202609", docx=True, meta=True)
    d = period_facts.resolve("202609", out_root=tmp_path)
    assert d is not None and d.name == "202609"


def test_只有meta或只有docx都不认(tmp_path):
    _mk(tmp_path, "202601", meta=True)
    _mk(tmp_path, "202603", docx=True)
    assert period_facts.resolve("202601", out_root=tmp_path) is None
    assert period_facts.resolve("202603", out_root=tmp_path) is None


def test_空目录与不存在的期次不认(tmp_path):
    (tmp_path / "202605").mkdir()
    assert period_facts.resolve("202605", out_root=tmp_path) is None
    assert period_facts.resolve("209901", out_root=tmp_path) is None


def test_产品期次列表包含半途期次(tmp_path):
    _mk(tmp_path, "202607", red=True)
    _mk(tmp_path, "202609", docx=True, meta=True)
    (tmp_path / "_superseded").mkdir()          # 留档目录不是期次
    assert period_facts.product_periods(out_root=tmp_path) == {"202607", "202609"}


def test_generate_ok仍只认red_slots(tmp_path):
    """半途期次**可见**（resolve 放宽）但三步条**诚实**（生成未完成）。"""
    _mk(tmp_path, "202609", docx=True, meta=True)
    f = period_facts.facts("202609", repo_root=tmp_path, out_root=tmp_path, filled=[])
    assert f.dir is not None
    assert f.generate_ok is False


def test_has_data对半途期次为真(tmp_path):
    _mk(tmp_path, "202609", docx=True, meta=True)
    assert period_facts.has_data("202609", out_root=tmp_path) is True
