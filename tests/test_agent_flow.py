# -*- coding: utf-8 -*-
"""Agent 层（P1 / M2）测试。

核心是把 2026-09-15 的裁决**变成可执行的证明**：

    首轮拦停 → 一次自愈重试 → 再败即升级

这条语义此前在三份文档里互相冲突（HLD §6.1 / 架构设计 §4.2·§4.7 / 决策方案 §3），
现在用三个断言分别钉住它的三个要素：拦停、重试恰好一次、升级。
"""
import pathlib
import sys

import pytest

from agent import flow, states, tools, trace

ALL_10 = {
    "pending", "running", "retrying", "stalled", "waiting_approval",
    "completed", "warned", "escalated", "failed", "cancelled",
}


# ============================================================ 状态机
def test_恰好十个状态且与文档一致():
    assert len(states.STATES) == 10
    assert set(states.STATES) == ALL_10


def test_终态不可再迁移():
    for s in states.TERMINAL:
        assert states.TRANSITIONS[s] == frozenset(), f"{s} 不应再有出边"


def test_终态集合符合文档():
    assert states.TERMINAL == frozenset(
        {"completed", "warned", "escalated", "failed", "cancelled"})


@pytest.mark.parametrize("src,dst", [
    ("completed", "running"),      # 终态不可复活（重跑=新建运行）
    ("pending", "completed"),      # 不能跳过 running
    ("escalated", "running"),
])
def test_非法迁移被拒绝(src, dst):
    with pytest.raises(states.IllegalTransition):
        states.check_transition(src, dst)


@pytest.mark.parametrize("src,dst", [
    ("pending", "running"),
    ("running", "retrying"),
    ("retrying", "running"),
    ("retrying", "escalated"),
    ("running", "completed"),
    ("running", "warned"),
])
def test_合法迁移放行(src, dst):
    states.check_transition(src, dst)


def test_未知状态名被拒():
    with pytest.raises(states.IllegalTransition):
        states.check_transition("pending", "不存在的状态")


# ============================================================ 步骤表
def test_主干五步且顺序固定():
    assert [s["id"] for s in flow.STEPS] == ["parse", "compute", "forecast", "charts", "docx"]


def test_步骤表与演示站一致_防两份漂移():
    """server/config.py 也有一份 STEPS，前端五步进度靠它。两边必须一致。"""
    server = pathlib.Path(__file__).resolve().parent.parent / "server"
    sys.path.insert(0, str(server))
    try:
        import config                                        # noqa: PLC0415
    finally:
        sys.path.remove(str(server))
    assert [s["id"] for s in config.STEPS] == [s["id"] for s in flow.STEPS], \
        "server/config.STEPS 与 agent/flow.STEPS 已漂移，前端进度会与编排脱节"


# ============================================================ 工具契约
def test_契约共十三个工具():
    assert len(tools.REGISTRY) == 13


def test_未注册工具被拒绝():
    """主干不可被模型扩展：注册表外的名字一律拒绝。"""
    with pytest.raises(tools.ToolError) as e:
        tools.call("shell_exec", cmd="rm -rf /")
    assert e.value.code == "TOOL_NOT_IMPLEMENTED"


def _pending_tools():
    """探测出「契约已定、实现待补」的工具：调用它会抛 TOOL_NOT_IMPLEMENTED。

    用探测而不是维护一张清单，是因为清单一定会忘更新——M4 三工具落地时就是靠
    写死 `scan_stale` 的旧用例才暴露出来的。探测的代价是要真的调一次，
    所以**跳过无必填参数的工具**（调它们会真跑、有副作用）。
    """
    found = []
    for t in tools.REGISTRY.values():
        kwargs = {k: "x" for k, (_typ, req, _d) in t.args.items() if req}
        if not kwargs:
            continue
        try:
            tools.call(t.name, **kwargs)
        except tools.ToolError as e:
            if e.code == "TOOL_NOT_IMPLEMENTED":
                found.append(t)
        except Exception:                                     # noqa: BLE001
            pass
    return found


def test_未实现工具报明确错误而非静默成功():
    """契约已定、实现待补的工具，调用必须抛 TOOL_NOT_IMPLEMENTED 并指明归属里程碑。

    ⚠ **不要写死工具名**。这条原本写死 `scan_stale`；M4 三工具 2026-09-16 落地后
    它就成了"等着实现接上"的反用例——实现一接上反而红。改为遍历探测出来的待补工具，
    并在一个都不剩时明确失败（否则"没东西可测"会伪造成全绿）。
    """
    todos = _pending_tools()
    assert todos, "所有工具都已实现——本用例的遍历前提没了，需改用别的方式验证契约"
    for t in todos:
        kwargs = {k: "x" for k, (_typ, req, _d) in t.args.items() if req}
        with pytest.raises(tools.ToolError) as e:
            tools.call(t.name, **kwargs)
        assert e.value.code == "TOOL_NOT_IMPLEMENTED", t.name
        assert t.milestone in e.value.message, f"{t.name} 应指出实现归属的里程碑"


def test_缺少必填参数被拒():
    with pytest.raises(tools.ToolError) as e:
        tools.call("run_parse", ledger="a.xlsx")           # 缺 out_dir
    assert "out_dir" in e.value.message


def test_参数类型不符被拒():
    with pytest.raises(tools.ToolError):
        tools.call("run_parse", ledger=123, out_dir="x")


def test_未声明参数被拒():
    with pytest.raises(tools.ToolError) as e:
        tools.call("write_env_snapshot", surprise=1)
    assert "未声明参数" in e.value.message


def test_未知错误码直接拒绝():
    with pytest.raises(ValueError):
        tools.ToolError("TOTALLY_MADE_UP", "x")


def test_错误码在文档全集内():
    used = {c for t in tools.REGISTRY.values() for c in t.errors}
    assert used <= set(tools.ERROR_CODES)


def test_契约可导出schema():
    s = tools.schema()
    names = {t["name"] for t in s}
    assert "run_parse" in names and "run_college_stats" in names
    assert all("milestone" in t for t in s)


# ============================================================ 编排裁决
def _stub(monkeypatch, behaviour):
    """把 `_invoke` 换成桩：behaviour(step_id) 返回 dict 或抛 ToolError。"""
    calls = []

    def fake(step, ctx, result):
        calls.append(step["id"])
        r = behaviour(step["id"])
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(flow, "_invoke", fake)
    return calls


def _ok(step_id):
    return {"ok": True, "period": "202607", "out_dir": "x"}


def test_首轮拦停_一次重试_再败升级(monkeypatch, tmp_path):
    """裁决的三要素一次验完。"""
    calls = _stub(monkeypatch, lambda sid: tools.ToolError("MISSING_PERIOD", "模拟缺期次")
                  if sid == "compute" else _ok(sid))
    r = flow.run("fake.xlsx", out_root=tmp_path / "out", run_dir=tmp_path / "run")

    # ① 升级：重试仍失败 → escalated（不是 failed，也不是"未过仍出稿"）
    assert r.status == states.ESCALATED
    # ② 一次重试：失败步恰好被调用两次（首轮 + 自愈后一次）
    assert calls.count("compute") == 2, f"重试次数不对：{calls}"
    # ③ 拦停：失败步之后的步骤一次都没跑
    assert "forecast" not in calls and "charts" not in calls and "docx" not in calls


def test_升级时产出诊断报告(monkeypatch, tmp_path):
    _stub(monkeypatch, lambda sid: tools.ToolError("ASSERT_FAIL", "断言未过")
          if sid == "parse" else _ok(sid))
    r = flow.run("fake.xlsx", out_root=tmp_path / "out", run_dir=tmp_path / "run")
    assert r.status == states.ESCALATED
    diag = pathlib.Path(r.run_dir) / "诊断报告.md"
    assert diag.exists(), "升级场景必须产出《诊断报告》（SRS R-26）"
    assert "自愈逾限" in diag.read_text(encoding="utf-8")


def test_自愈成功则继续走完全程(monkeypatch, tmp_path):
    """首轮失败、重试成功 → 不升级，后续步骤照常。"""
    seen = {"n": 0}

    def behaviour(sid):
        if sid == "compute":
            seen["n"] += 1
            if seen["n"] == 1:
                return tools.ToolError("MISSING_PERIOD", "首次失败")
        return _ok(sid)

    calls = _stub(monkeypatch, behaviour)
    r = flow.run("fake.xlsx", out_root=tmp_path / "out", run_dir=tmp_path / "run")
    assert r.status == states.COMPLETED
    assert calls[-1] == "docx", "重试成功后应继续跑完剩余步骤"


def test_可降级错误码不拦停且终态为warned(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, lambda sid: tools.ToolError("REF_MISSING", "无原件")
                  if sid == "forecast" else _ok(sid))
    r = flow.run("fake.xlsx", out_root=tmp_path / "out", run_dir=tmp_path / "run")
    assert r.status == states.WARNED
    assert "charts" in calls and "docx" in calls, "可降级错误不应拦停"
    assert r.warnings, "应有告警记录"


def test_全绿走完成(monkeypatch, tmp_path):
    _stub(monkeypatch, _ok)
    r = flow.run("fake.xlsx", out_root=tmp_path / "out", run_dir=tmp_path / "run")
    assert r.status == states.COMPLETED
    assert r.failure is None


def test_每次运行都落run_result(monkeypatch, tmp_path):
    _stub(monkeypatch, _ok)
    r = flow.run("fake.xlsx", out_root=tmp_path / "out", run_dir=tmp_path / "run")
    assert (pathlib.Path(r.run_dir) / "run_result.json").exists()


# ============================================================ 轨迹
def test_轨迹三文件落盘(tmp_path):
    tr = trace.Trace(tmp_path)
    tr.event("plan", tool="run_parse", args={"ledger": "秘密路径.xlsx"})
    tr.transition(states.PENDING, states.RUNNING, trigger="start")
    tr.task_run("parse", 1, 1.0, 2.5, "done")

    for name in ("agent_events.jsonl", "state_history.jsonl", "task_runs.jsonl"):
        assert (tmp_path / name).exists(), f"缺轨迹文件 {name}"


def test_轨迹只存摘要不存原值(tmp_path):
    """台账明细不得出内网：轨迹里只留 digest。"""
    tr = trace.Trace(tmp_path)
    tr.event("act", tool="read_cell", args={"cell": "C12", "secret": "云南大学"})
    text = (tmp_path / "agent_events.jsonl").read_text(encoding="utf-8")
    assert "args_digest" in text
    assert "云南大学" not in text
    assert "C12" not in text


def test_轨迹拒绝非法phase(tmp_path):
    tr = trace.Trace(tmp_path)
    with pytest.raises(ValueError):
        tr.event("made_up_phase")


def test_轨迹迁移同样校验合法性(tmp_path):
    tr = trace.Trace(tmp_path)
    with pytest.raises(states.IllegalTransition):
        tr.transition(states.COMPLETED, states.RUNNING, trigger="x")
