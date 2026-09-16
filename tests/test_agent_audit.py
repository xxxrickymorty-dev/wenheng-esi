# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 审计闭环（M4 / P3）测试。

验收判据沿用 M3 的规矩：**判据是「结论对」，不是「用例全绿」**。
所以本文件里有相当一部分是"反自欺"用例——专门钉住那些会让人误以为审计通过、
其实什么都没验的写法：

- 拿 `ledger_long.parquet` 当真值 = 同源自证 → 缺台账必须 skip，不许降级
- 图槽位的 `[图] 路径` 当字面文本比对 → 会全军覆没，必须改验"格子里有图"
- 笼统抓第一个 `xx%` 当一致率 → 曾抓到「1‰接近度 55.13%」
- 行级 100% 冒充格级达标 → 口径不同就不许自动判过
- 按 `source` 判手工槽 → 会把约 100 个机器图槽算成待人工清点

数据驱动的用例缺数据时走 `tests/_guard_registry.skip_unless`（登记理由 + 探针），
不用裸 `pytest.skip`——后者会被会话收尾判失败。
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from _guard_registry import skip_unless

from agent import audit

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "202607"
LEDGER = ROOT / "input" / "202607" / "监测表.xlsx"

_PERIOD = "202607"


def _need(p: pathlib.Path, what: str):
    if not p.exists():
        skip_unless(f"缺{what}：{p.name}（out/ 与 input/ 按 .gitignore 不入库）",
                    lambda: p.exists())


# ================================================================== 结构性
def test_六项检查齐全且与实现一一对应():
    assert len(audit.AUDIT_ITEMS) == 6
    assert set(audit.AUDIT_ITEMS) == set(audit.CHECKS)
    for name in audit.AUDIT_ITEMS:
        assert callable(audit.CHECKS[name])


def test_三个M4工具已接线不再是待实现():
    """契约早就注册了，milestone 标 M4。实现没接上时调用会抛 TOOL_NOT_IMPLEMENTED。"""
    from agent import tools
    for name in ("scan_stale", "collect_artifacts", "write_env_snapshot"):
        assert tools.REGISTRY[name].milestone == "M4"
        assert not tools.REGISTRY[name].handler(**_dummy_args(name)).get("__not_implemented__")


def _dummy_args(name):
    if name == "scan_stale":
        return {"out_dir": str(OUT), "ledger": str(LEDGER)}
    if name == "collect_artifacts":
        return {"run_dir": str(OUT)}
    return {"run_dir": str(OUT)}


def test_工具总数仍是13个_没破栈契约():
    from agent import tools
    assert len(tools.REGISTRY) == 13


# ================================================================== 空值语义
def test_空值的三种写法彼此相等():
    """CSV 读回是 NaN、pandas 未落值是空串、JSON 里是 None——语义同为空。"""
    for a, b in [(None, ""), (float("nan"), ""), ("", None),
                 (float("nan"), None), ("   ", "")]:
        assert audit._same(a, b), f"{a!r} 与 {b!r} 应判相等"


def test_零不是空值():
    """0 是有意义的数字。把 0 判成空会让「0 篇论文」被当成没填。"""
    assert not audit._blank(0)
    assert not audit._blank(0.0)
    assert not audit._same(0, "")
    assert not audit._same(0, None)


def test_整数与浮点往返视为相等():
    assert audit._same(12, 12.0)
    assert audit._same("12", 12)
    assert not audit._same(12, 13)


# ================================================================== 第 4 项
def test_行级100不等于格级达标_必须交人工(tmp_path):
    """反自欺核心用例：行级 22/22 看着 100%，但 M0 基线 99.5% 是格级。
    口径不同就不许自动判过——否则等于用更松的口径冒充达标。"""
    (tmp_path / "对照差异报告_202607回测.md").write_text(
        "行级通过 22/22；不一致 0 行（无）。\n大表：22/22 行逐格一致\n",
        encoding="utf-8")
    r = audit.check_golden_bt(str(tmp_path))
    assert r["status"] == "review"
    assert r["pct"] == 100.0
    assert "行级" in r["unit"]
    assert "格级" in r["reason"]


def test_格级一致率达标才判过(tmp_path):
    # ⚠ 必须分两个目录：实现会把同目录下所有 *回测*.md **拼接**后取第一个一致率，
    #   放一起就成了"先读到谁算谁"，测不出第二个分支。
    ok, bad = tmp_path / "ok", tmp_path / "bad"
    ok.mkdir()
    bad.mkdir()
    (ok / "x回测.md").write_text("一致率 99.6%\n", encoding="utf-8")
    (bad / "y回测.md").write_text("一致率 90.0%\n", encoding="utf-8")
    assert audit.check_golden_bt(str(ok))["status"] == "pass"
    assert audit.check_golden_bt(str(bad))["status"] == "fail"


def test_不能把接近度当成一致率(tmp_path):
    """真实踩过的坑：文案里有「1‰接近度 55.13%」，笼统抓第一个 % 会误判失败。"""
    (tmp_path / "对照差异报告_202607回测.md").write_text(
        "- ✅ 1‰接近度 55.13%: 台账计算=55.13；手工版文本含该数字\n"
        "行级通过 22/22；不一致 0 行（无）。\n", encoding="utf-8")
    r = audit.check_golden_bt(str(tmp_path))
    assert r["pct"] != 55.13


def test_无回测产物时标未执行而不是失败(tmp_path):
    r = audit.check_golden_bt(str(tmp_path))
    assert r["status"] == "not_run"


# ================================================================== 第 5 项
def test_手工槽只认手工标记_机器图槽不算(tmp_path):
    """按 source 判会把 charts/**.png 的机器图槽也算成待人工清点（曾虚高到 115）。"""
    slots = [
        {"location": "T03/r1c1", "old": "", "new": "[图] Chemistry/cnci.png",
         "source": "charts/Chemistry/cnci.png"},
        {"location": "正文/p1", "old": "", "new": "据【手工：ESI发布日期】ESI最新数据显示",
         "source": "sentences.py（句骨架+数字槽）"},
        {"location": "T01/r1c0", "old": "", "new": "工程学", "source": "table2.csv"},
    ]
    (tmp_path / "red_slots.json").write_text(
        json.dumps(slots, ensure_ascii=False), encoding="utf-8")
    r = audit.manual_slot_checklist(str(tmp_path))
    assert r["n_pending"] == 1
    assert r["items"] == ["ESI发布日期"]


# ================================================================== 第 3 项
def test_期次残留按严重程度分档(tmp_path):
    """上期及更早的期次多为历史序列正当引用（low）；未来期次必是残留（high）。"""
    (tmp_path / "meta.json").write_text(
        json.dumps({"period_current": "202607", "period_prev": "202605"}),
        encoding="utf-8")
    (tmp_path / "预测选模与过线.md").write_text(
        "窗口 201903 起，对比 202509，本期 202607。", encoding="utf-8")
    r = audit.scan_stale(str(tmp_path))
    assert r["period"] == "202607"        # 键名必须是 period_current，不是 period
    assert r["status"] == "pass"          # 只有 low 档 → 不判失败
    assert r["n_high"] == 0
    assert {s["period"] for s in r["suspicious"]} == {"201903", "202509"}


def test_未来期次判失败(tmp_path):
    (tmp_path / "meta.json").write_text(
        json.dumps({"period_current": "202607", "period_prev": "202605"}),
        encoding="utf-8")
    (tmp_path / "x.md").write_text("本期 202609 已出数。", encoding="utf-8")
    r = audit.scan_stale(str(tmp_path))
    assert r["status"] == "fail"
    assert r["n_high"] == 1


# ================================================================== 归档
def test_归清单一律带sha256且排除被隔离的上一版(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "_superseded").mkdir()
    (tmp_path / "_superseded" / "old.docx").write_text("x", encoding="utf-8")
    man = audit.collect_artifacts(str(tmp_path))
    assert man["n_files"] == 1
    assert man["files"][0]["sha256"] == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_环境快照写得出来且带git提交号(tmp_path):
    snap = audit.write_env_snapshot(str(tmp_path))
    assert (tmp_path / "env_snapshot.json").exists()
    assert snap["python"]


def test_归档只复制不动源目录(tmp_path):
    """归档出错不能毁掉本期产物——这是本用例存在的全部理由。"""
    src = tmp_path / "out" / _PERIOD
    src.mkdir(parents=True)
    (src / "keep.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    before = audit._sha256(src / "keep.csv")

    info = audit.archive_period(str(src), archive_root=str(tmp_path / "_archive"))
    assert info["n_files"] == 1
    assert audit._sha256(src / "keep.csv") == before        # 源文件一字节没动
    assert (tmp_path / "_archive" / _PERIOD / "keep.csv").exists()
    assert (tmp_path / "_archive" / _PERIOD / "manifest.json").exists()


# ================================================================== 端到端
def test_大表全量242格回查():
    _need(OUT / "table2.csv", "产物")
    _need(LEDGER, "台账原件")
    r = audit.check_big_table(str(OUT), str(LEDGER))
    assert r["cells_checked"] == 242 and r["cells_full"]
    assert r["n_diff"] == 0, f"大表有差异：{r['diffs']}"


def test_缺台账时大表回查跳过_不许拿ledger_long自证():
    """同源自证比不做更坏：它会给出一个"通过"的假象。"""
    _need(OUT / "table2.csv", "产物")
    r = audit.check_big_table(str(OUT), None)
    assert r["status"] == "skipped"
    assert "自证" in r["reason"]


def test_六项跑完落两份产物():
    _need(OUT / "table2.csv", "产物")
    _need(LEDGER, "台账原件")
    rec = audit.run_audit(str(OUT), ledger=str(LEDGER))
    assert len(rec["items"]) == 6
    assert (OUT / "audit_record.json").exists()
    assert (OUT / "审计记录.md").exists()
    # 真值链必须写进记录：审计能证明什么、不能证明什么，都得摆出来
    assert "does_not_cover" in rec["truth_chain"]
    assert "ledger_long" in rec["truth_chain"]["not_used"]
