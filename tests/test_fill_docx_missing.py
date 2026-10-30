# -*- coding: utf-8 -*-
"""R2-3【S1】缺省域表 / 矩阵时不许静默返回：槽位里必须留一条哨兵。

红队第二轮（`docs/reviews/2026-10-28-ADR0014-对抗性审查-第二轮.md` R2-3）：
`fill_matrix` / `fill_province` 在缺 `matrix.json` / `province.json` / 找不到 T19 时
直接 `return 0`，表格整片空白、`red_slots.json` 一条不记、状态照旧 `completed` ——
「缺一步」被读成「这一步本来就没内容」。

本文件钉住：三处（连同 JSON 损坏）都在返回前往 `slots` 里留哨兵，且在控制台喊一声。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                   # noqa: E402
from docx import Document                                       # noqa: E402

import fill_docx                                                # noqa: E402


def _empty_doc():
    """没有 T19/T20 的空白文档：fill_* 只会在「缺表」分支返回。"""
    return Document()


def _sentinels(slots):
    return [s for s in slots if str(s.get("new", "")).startswith("[缺]")]


class Test缺文件:
    def test_缺matrix_json_留哨兵(self, tmp_path, capsys):
        slots = []
        assert fill_docx.fill_matrix(_empty_doc(), tmp_path, slots) == 0
        sent = _sentinels(slots)
        assert len(sent) == 1, slots
        assert sent[0]["location"] == "T20/整表"
        assert sent[0]["source"] == "fill_matrix"
        assert "matrix.json" in sent[0]["new"]
        assert "T20" in capsys.readouterr().out, "缺数据必须在控制台喊一声"

    def test_缺province_json_留哨兵(self, tmp_path, capsys):
        slots = []
        assert fill_docx.fill_province(_empty_doc(), tmp_path, slots) == 0
        sent = _sentinels(slots)
        assert len(sent) == 1, slots
        assert sent[0]["location"] == "T19/整表"
        assert sent[0]["source"] == "fill_province"
        assert "province.json" in sent[0]["new"]
        assert "T19" in capsys.readouterr().out

    def test_空目录两条哨兵都留(self, tmp_path):
        """产线最常见的现场：整个省域/矩阵两步没跑，两个 json 都不在。"""
        slots = []
        fill_docx.fill_province(_empty_doc(), tmp_path, slots)
        fill_docx.fill_matrix(_empty_doc(), tmp_path, slots)
        assert {s["location"] for s in _sentinels(slots)} == {"T19/整表", "T20/整表"}


class Test文件在但用不了:
    def test_province_json损坏_留哨兵(self, tmp_path):
        (tmp_path / "province.json").write_text("{不是 JSON", encoding="utf-8")
        slots = []
        assert fill_docx.fill_province(_empty_doc(), tmp_path, slots) == 0
        assert len(_sentinels(slots)) == 1
        assert "损坏" in _sentinels(slots)[0]["new"]

    def test_matrix_json损坏_留哨兵(self, tmp_path):
        (tmp_path / "matrix.json").write_text("[1, 2,", encoding="utf-8")
        slots = []
        assert fill_docx.fill_matrix(_empty_doc(), tmp_path, slots) == 0
        assert len(_sentinels(slots)) == 1
        assert "损坏" in _sentinels(slots)[0]["new"]

    def test_有数据但母版没有T19_留哨兵(self, tmp_path):
        (tmp_path / "province.json").write_text(
            json.dumps({"universities": {"云南大学": {}}}, ensure_ascii=False), encoding="utf-8")
        slots = []
        assert fill_docx.fill_province(_empty_doc(), tmp_path, slots) == 0
        sent = _sentinels(slots)
        assert len(sent) == 1 and sent[0]["location"] == "T19/整表"
        assert "13×10" in sent[0]["new"]


class Test哨兵进红件清单:
    def test_哨兵计入文字槽位(self):
        """`main()` 的统计口径：非 T01/r、非 [图] 的槽算文字槽 —— 哨兵必须落在这一类。"""
        slots = []
        fill_docx.fill_province(_empty_doc(), pathlib.Path("不存在"), slots)
        sent = _sentinels(slots)[0]
        assert not sent["location"].startswith("T01/r")
        assert not sent["new"].startswith("[图]")


@pytest.mark.parametrize("fn, ledger", [(fill_docx.fill_province, "province.json"),
                                        (fill_docx.fill_matrix, "matrix.json")])
def test_哨兵不会因为缺文件而重复(fn, ledger, tmp_path):
    """返回 0 但槽位非空：调用方若按 `if n:` 打印，仍能从红件清单看到缺什么。"""
    slots = []
    n = fn(_empty_doc(), tmp_path, slots)
    assert n == 0 and len(slots) == 1
    assert not (tmp_path / ledger).exists()
