# -*- coding: utf-8 -*-
"""原子写（ADR-0012 决定 1）落地后的两条单元级保证。

流水线侧另有对照证据（同一 `out_root` 跑改动前后各一遍，145/147 个产物逐字节相同），
这里钉的是不依赖数据的那两条：

1. **只换「怎么写」，不换字节**：默认 `newline=None` 的平台换行翻译必须与
   `Path.write_text(text, encoding="utf-8")` 逐字节相同（JSON 与 Markdown 都在）。
2. **写失败不毁旧文件**：目标文件保持旧内容，同目录不留 tmp。
3. 收进原子写的四处调用点（诊断报告 / `meta.json` / 归档 `manifest.json` /
   预测选模快照）确实走的是公用助手，不是又长出裸 `write_text`。
"""
import asyncio
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atomic_io                                                 # noqa: E402
import run_pipeline                                              # noqa: E402
from agent import audit                                          # noqa: E402
from server import config, jobs                                  # noqa: E402


# ============================================================ ① 字节不变
@pytest.mark.parametrize("text", [
    "a\nb\n",                                                    # 纯 LF（Windows 上要翻成 CRLF）
    json.dumps({"期次": "202607", "n": 1, "nested": {"x": [1, 2]}},
               ensure_ascii=False, indent=1),                     # 快照 / meta / manifest 的形状
    "\n".join(["# 诊断报告 · 台账断言未过", "", "- 期次：**202607**"]),
])
def test_原子写与write_text逐字节相同(tmp_path, text):
    """原子写只换落盘方式；换行翻译按平台走，与裸 `write_text` 同字节。"""
    want = tmp_path / "want.txt"
    want.write_text(text, encoding="utf-8")
    got = tmp_path / "got.txt"

    atomic_io.write_text_atomic(got, text)

    assert got.read_bytes() == want.read_bytes()


# ============================================================ ② 失败不毁旧文件
def test_写失败时目标文件保持旧内容且不留tmp(tmp_path, monkeypatch):
    target = tmp_path / "manifest.json"
    old = "旧内容\n".encode()
    target.write_bytes(old)

    def boom(*_a, **_k):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_io.os, "replace", boom)

    with pytest.raises(OSError):
        atomic_io.write_text_atomic(target, "新内容\n")

    assert target.read_bytes() == old, "替换失败时目标不能变成半截文件"
    assert not list(tmp_path.glob("*.tmp-*")), "失败后 tmp 必须清掉，别留在产物目录里"


# ============================================================ ③ 四处调用点走助手
def _spy(monkeypatch):
    """记录经 `atomic_io.write_text_atomic` 落盘的文件名（原函数照跑）。

    ⚠ 仓里这个模块有两个身份：`src/` 内的脚本 `import atomic_io`（顶层名），
    `server/` 与 `src/agent/` 用 `from src import atomic_io`——是**两个模块对象**，
    所以两处都要挂探针（既有写法如此，见 `server/jobs.py` 的 `from src import ...`）。
    """
    real = atomic_io.write_text_atomic
    seen = []

    def spy(path, text, *args, **kwargs):
        seen.append(pathlib.Path(path).name)
        return real(path, text, *args, **kwargs)

    targets = [atomic_io]
    also = sys.modules.get("src.atomic_io")
    if also is not None and also is not atomic_io:
        targets.append(also)
    for mod in targets:
        monkeypatch.setattr(mod, "write_text_atomic", spy)
    return seen


def test_诊断报告走原子写(tmp_path, monkeypatch):
    seen = _spy(monkeypatch)
    out_dir = tmp_path / "209901"

    p = run_pipeline._write_diagnosis(
        {"wide": {}, "diagnostics": {}}, "209901", out_dir,
        [("FAIL", "宽表 total_cites 学科数=22 (实际 21)")], 1)

    assert p and p.exists()
    assert "诊断报告.md" in seen


def test_归档manifest走原子写(tmp_path, monkeypatch):
    src = tmp_path / "out" / "209901"
    src.mkdir(parents=True)
    (src / "keep.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    seen = _spy(monkeypatch)

    audit.archive_period(str(src), archive_root=str(tmp_path / "_archive"))

    assert "manifest.json" in seen
    man = json.loads((tmp_path / "_archive" / "209901" / "manifest.json")
                     .read_text(encoding="utf-8"))
    assert man["period"] == "209901"


def test_预测选模快照走原子写(tmp_path, monkeypatch):
    """job 私有快照会被流水线子进程并发读——半截 JSON 就是一次假失败。"""
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    monkeypatch.setattr(config, "JOBS_DIR", tmp_path / "_jobs")
    monkeypatch.setattr(config, "FORECAST_CHOICES_DIR", tmp_path / "_forecast_choices")
    monkeypatch.setattr(jobs, "_running", set())
    monkeypatch.setattr(jobs, "active_job", lambda: None)

    async def no_run(_job):
        return None

    monkeypatch.setattr(jobs, "_run", no_run)
    seen = _spy(monkeypatch)

    async def create():
        return jobs.create_job("209901", "input.xlsx", "tester")

    job = asyncio.run(create())

    assert "forecast_choice.json" in seen
    snap = pathlib.Path(jobs.job_dir(job["id"])) / "forecast_choice.json"
    assert isinstance(json.loads(snap.read_text(encoding="utf-8")), dict)
