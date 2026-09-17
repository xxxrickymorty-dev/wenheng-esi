# -*- coding: utf-8 -*-
"""运行档案页（M4-4B / SRS R-21）测试。

R-21 要求「任一期可完整回放：状态机回放 + 任务瀑布 + 产物渲染 + 日志包下载」。
本文件的重点不是"页面能打开"，而是**档案不许编故事**——三个最容易出错的地方：

1. **瀑布把累计值当步长。** `progress.jsonl` 的 `elapsed` 是从进程启动算起的
   累计秒，直接画柱子会让最后一步看起来"包含了前面所有步"。
2. **轨迹缺失时装作有轨迹。** 演示站直跑路径没有
   `state_history.jsonl`，合成链必须标 `synthetic=True` 且只含确定发生过的迁移，
   绝不能替编排器编出 retrying / escalated。
3. **日志包变成第二个归档包。** 日志包只取回放最小集（文本件），
   混入 docx/parquet/PNG 就会胖到发不出去，且与 `out/_archive/` 职责重叠。

数据驱动用例走 `tests/_guard_registry.skip_unless`（登记理由 + 探针）。
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import zipfile

import pytest

from _guard_registry import skip_unless

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import archive                                        # noqa: E402

OUT = ROOT / "out" / "202607"


def _progress(rows):
    """写一份临时 progress.jsonl，返回其路径。"""
    return rows


# ============================================================ 任务瀑布
def test_瀑布用步长而不是累计值():
    """`elapsed` 是累计秒：5→9 这一步的耗时是 4 秒，不是 9 秒。"""
    rows = [
        {"ts": "10:00:00", "step": "parse", "name": "解析台账", "status": "start", "elapsed": 0.0},
        {"ts": "10:00:05", "step": "parse", "name": "解析台账", "status": "done", "elapsed": 5.0},
        {"ts": "10:00:05", "step": "compute", "name": "计算大表", "status": "start", "elapsed": 5.0},
        {"ts": "10:00:09", "step": "compute", "name": "计算大表", "status": "done", "elapsed": 9.0},
    ]
    wf = {r["step"]: r for r in archive.waterfall(rows)}
    assert wf["parse"]["sec"] == 5.0
    assert wf["compute"]["sec"] == 4.0, "拿累计值当步长，最后一步会被画成包含前面所有步"


def test_瀑布按开工时刻排序():
    rows = [
        {"ts": "10:00:09", "step": "b", "name": "B", "status": "start", "elapsed": 5.0},
        {"ts": "10:00:10", "step": "b", "name": "B", "status": "done", "elapsed": 10.0},
        {"ts": "10:00:00", "step": "a", "name": "A", "status": "start", "elapsed": 0.0},
        {"ts": "10:00:05", "step": "a", "name": "A", "status": "done", "elapsed": 5.0},
    ]
    assert [r["step"] for r in archive.waterfall(rows)] == ["a", "b"]


def test_只有开工没有收工标orphan():
    """跑挂了的步只有 start。它耗时未知，标 orphan，不许填 0 冒充"很快"。"""
    rows = [{"ts": "10:00:00", "step": "docx", "name": "填充报告",
             "status": "start", "elapsed": 12.0}]
    r = archive.waterfall(rows)[0]
    assert r["orphan"] is True
    assert r["sec"] == 0.0
    assert r["step"] == "docx"


def test_中途插入的warn事件也被收纳():
    """只有收工没有开工的事件（如撤下上版成品的告警）不能整条丢掉。"""
    rows = [{"ts": "10:00:03", "step": "parse", "name": "解析台账",
             "status": "warn", "detail": "已撤下上版成品", "elapsed": 3.0}]
    r = archive.waterfall(rows)[0]
    assert r["step"] == "parse"
    assert r["status"] == "warn"
    assert r["detail"] == "已撤下上版成品"
    assert r["orphan"] is True


def test_空事件不炸():
    assert archive.waterfall([]) == []


# ============================================================ 状态机回放
def test_无轨迹文件时合成链且标注(tmp_path):
    job = {"id": "j1", "status": "warned", "exit_code": 1,
           "created_at": "2026-09-17 09:00:00", "finished_at": "2026-09-17 09:00:14"}
    rep = archive.state_replay(tmp_path, job=job)
    assert rep["synthetic"] is True
    assert rep["note"]
    assert [r["from"] for r in rep["chain"]] == ["pending", "running"]
    assert rep["chain"][-1]["to"] == "warned"
    # 合成的每一步都必须带标记，页面上才标得出"合成"二字
    assert all(r["synthetic"] for r in rep["chain"])


def test_合成链不许臆造自愈环节(tmp_path):
    """直跑路径知不知道 retrying/escalated？不知道。那就一个都不许出现。"""
    job = {"id": "j1", "status": "completed", "exit_code": 0,
           "created_at": "t0", "finished_at": "t1"}
    states = {s for r in archive.state_replay(tmp_path, job=job)["chain"]
              for s in (r["from"], r["to"])}
    assert not (states & {"retrying", "stalled", "escalated", "waiting_approval"}), \
        "合成链里出现了编排器才知道的状态——那是编故事，不是档案"


def test_无任务上下文时不合成(tmp_path):
    rep = archive.state_replay(tmp_path, job=None)
    assert rep["chain"] == []
    assert "无任务上下文" in rep["note"]


def test_有轨迹文件就读真迹(tmp_path):
    p = tmp_path / "state_history.jsonl"
    p.write_text(
        json.dumps({"ts": "t0", "from": "pending", "to": "running", "trigger": "start", "attempt": 1}) + "\n"
        + json.dumps({"ts": "t1", "from": "running", "to": "retrying", "trigger": "断言 FAIL", "attempt": 1}) + "\n",
        encoding="utf-8")
    rep = archive.state_replay(tmp_path, job={"status": "completed"})
    assert rep["synthetic"] is False
    assert [r["to"] for r in rep["chain"]] == ["running", "retrying"]
    assert not any(r["synthetic"] for r in rep["chain"])


def test_轨迹末行被截断也能读(tmp_path):
    """进程被杀时最后一行常是半截 JSON。跳掉即可，不能整份档案打不开。"""
    p = tmp_path / "state_history.jsonl"
    p.write_text(
        json.dumps({"ts": "t0", "from": "pending", "to": "running", "trigger": "start"}) + "\n"
        + '{"ts": "t1", "from": "run',
        encoding="utf-8")
    rep = archive.state_replay(tmp_path, job=None)
    assert rep["n"] == 1


# ============================================================ 审计视图
def test_缺审计记录时不编造():
    v = archive.audit_view(ROOT / "out" / "__不存在__")
    assert v["exists"] is False
    assert v["rows"] == []
    assert v["verdict"] == ""


def test_审计项给人话而不只是内部id(tmp_path):
    rec = {"verdict": "review", "generated_at": "t", "items": [
        {"id": "big_table", "status": "pass", "cells_total": 242, "cells_checked": 242, "n_diff": 0},
        {"id": "golden_bt", "status": "review", "pct": 100.0, "unit": "行级（22/22 行）",
         "reason": "行级 100% ≠ 格级达标"},
    ]}
    (tmp_path / "audit_record.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    v = archive.audit_view(tmp_path)
    assert v["verdict_label"] == "待人工确认"
    by_id = {i["id"]: i for i in v["rows"]}
    assert by_id["big_table"]["title"] == "大表全量回查"
    assert "242/242" in by_id["big_table"]["metric"]
    assert "100.0%" in by_id["golden_bt"]["metric"]
    assert "格级" in by_id["golden_bt"]["reason"]


# ============================================================ 日志包
def _make_out(tmp_path):
    d = tmp_path / "202607"
    d.mkdir()
    (d / "run_log.json").write_text('{"period":"202607"}', encoding="utf-8")
    (d / "audit_record.json").write_text('{"verdict":"pass","items":[]}', encoding="utf-8")
    (d / "table2.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (d / "报告初稿_202607.docx").write_bytes(b"PK" + b"\0" * 64)      # 大件，不该进包
    (d / "wide").mkdir()
    (d / "wide" / "ynd_rank.parquet").write_bytes(b"PAR1" + b"\0" * 64)
    return d


def test_日志包只收回放最小集(tmp_path):
    d = _make_out(tmp_path)
    data, name = archive.pack(d)
    assert name.startswith("wenheng-logpack-202607-") and name.endswith(".zip")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
    assert "README.txt" in names
    assert "period/run_log.json" in names
    assert "period/audit_record.json" in names
    assert "period/table2.csv" in names
    assert not any(n.endswith(".docx") for n in names), "docx 进了日志包——那就和归档包重复了"
    assert not any(n.endswith(".parquet") for n in names)


def test_日志包内README写清与归档包的分工(tmp_path):
    d = _make_out(tmp_path)
    data, _ = archive.pack(d)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        readme = z.read("README.txt").decode("utf-8")
    assert "202607" in readme
    assert "_archive" in readme, "README 要说清完整产物快照在归档目录，否则评审会以为包里缺东西"


def test_日志包带任务上下文(tmp_path):
    d = _make_out(tmp_path)
    jd = tmp_path / "_jobs" / "j1"
    jd.mkdir(parents=True)
    (jd / "job.json").write_text('{"id":"j1"}', encoding="utf-8")
    (jd / "progress.jsonl").write_text('{"step":"parse","status":"done"}\n', encoding="utf-8")
    (jd / "console.log").write_text("[1/5] 解析台账\n", encoding="utf-8")
    job = {"id": "j1", "progress": str(jd / "progress.jsonl")}
    data, _ = archive.pack(d, job=job)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
    assert "job/job.json" in names
    assert "job/progress.jsonl" in names
    assert "job/console.log" in names


def test_打包不落盘不污染out目录(tmp_path):
    """`pack` 是纯内存的：打完包 out/ 下不该多出任何文件。"""
    d = _make_out(tmp_path)
    before = {p.name for p in d.rglob("*")}
    archive.pack(d)
    assert {p.name for p in d.rglob("*")} == before


def test_缺文件也能打包(tmp_path):
    d = tmp_path / "空目录"
    d.mkdir()
    data, name = archive.pack(d)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "README.txt" in z.namelist()


# ============================================================ 汇总视图
def test_build在空目录上不炸(tmp_path):
    d = tmp_path / "209901"
    d.mkdir()
    v = archive.build(d)
    assert v["period"] == "209901"
    assert v["audit"]["exists"] is False
    assert v["waterfall"] == []
    assert v["replay"]["chain"] == []
    assert v["logpack"]["n_files"] == 0
    assert v["trace_files"] == []


def test_build认出轨迹文件(tmp_path):
    d = tmp_path / "202607"
    d.mkdir()
    for n in ("agent_events.jsonl", "state_history.jsonl"):
        (d / n).write_text("", encoding="utf-8")
    v = archive.build(d)
    assert v["trace_files"] == ["agent_events.jsonl", "state_history.jsonl"]


def test_build接得住job侧的进度事件(tmp_path):
    d = tmp_path / "202607"
    d.mkdir()
    jd = tmp_path / "_jobs" / "j1"
    jd.mkdir(parents=True)
    prog = jd / "progress.jsonl"
    prog.write_text(
        json.dumps({"ts": "10:00:00", "step": "parse", "name": "解析台账", "status": "start", "elapsed": 0}) + "\n"
        + json.dumps({"ts": "10:00:02", "step": "parse", "name": "解析台账", "status": "done", "elapsed": 2}) + "\n",
        encoding="utf-8")
    v = archive.build(d, job={"id": "j1", "status": "completed", "progress": str(prog)})
    assert [r["step"] for r in v["waterfall"]] == ["parse"]
    assert v["waterfall_total"] == 2.0


# ============================================================ 真实产物（数据驱动）
def _need_out():
    if not OUT.is_dir():
        skip_unless("out/202607 不存在（历史产物不入库，属正常）", lambda: OUT.is_dir())
    return OUT


def test_档案页在真实期次上完整可用():
    d = _need_out()
    v = archive.build(d, artifacts=[])
    assert v["period"] == "202607"
    assert v["run_log"].get("period") == "202607"
    assert v["logpack"]["n_files"] >= 3, "真实产物里至少应有 run_log / audit_record / env_snapshot"
    # 真实期次跑过 4A，审计记录必须在
    if (d / "audit_record.json").exists():
        rec = json.loads((d / "audit_record.json").read_text(encoding="utf-8"))
        assert v["audit"]["verdict"] == rec["verdict"]
        assert len(v["audit"]["rows"]) == len(rec["items"])


def test_真实期次的日志包能打开():
    d = _need_out()
    data, name = archive.pack(d)
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        assert "README.txt" in z.namelist()
        assert not any(n.endswith((".docx", ".parquet", ".png")) for n in z.namelist())
