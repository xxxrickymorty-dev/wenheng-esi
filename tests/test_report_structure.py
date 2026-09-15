# -*- coding: utf-8 -*-
"""报告初稿排版结构校验：96 个图表槽位 + 22 行大表。

对应 `tools/verify_report_docx.py`（原先散落在 Agent 技能目录里，现收编进仓库）。
这层闸挡的是「图表挤出页」「槽位漏插图」「大表没填满」这类
**数字全对但成品不能用**的问题——纯靠肉眼很难发现，必须机器验。
"""
import verify_report_docx


def _check_one(path, capsys):
    rc = verify_report_docx.main(str(path))
    out = capsys.readouterr().out
    problems = []
    if rc != 0:
        problems.append(f"返回码 {rc}")
    if "槽位格通过: 96/96" not in out:
        problems.append("槽位未满 96 格")
    if "大表数据行: 22/22" not in out:
        problems.append("大表未满 22 行")
    if problems:
        return f"{path.name}：{'；'.join(problems)}\n{out}"
    return None


def test_报告初稿结构全绿(reports, capsys):
    bad = [x for x in (_check_one(r, capsys) for r in reports) if x]
    assert not bad, "\n\n".join(bad)
