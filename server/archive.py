# -*- coding: utf-8 -*-
"""文衡演示站 · 运行档案（WH-DOC-02 R-21；WH-DOC-03 §8 审计与回放）。

R-21 要的四件事：**状态机回放 + 任务瀑布 + 产物渲染 + 日志包下载**，
且「任一期可完整回放」。本模块只做取数与汇总，**不碰 FastAPI**，
页面渲染留给 `app.py` + `templates/archive.html`。

三条设计约束（都是踩过或注定会踩的坑）
--------------------------------------------------------------------------------
1. **不造证据。** 演示站主入口走 `src/run_pipeline.py` 直跑，
   **不写** `agent_events/state_history/task_runs` 三件套（那是 `agent/flow.py`
   编排器才有的轨迹）。所以轨迹缺失时：
     · 状态机回放**合成最小链**并打 `synthesized=True`；
     · 任务瀑布改用 `progress.jsonl`（直跑路径确实会写）。
   合成≠伪造：页面上标注「合成」二字，且合成链只含**已知发生了**的迁移
   （created → running → 终态），不臆造 retrying/escalated。
   反过来，档案页不能因为缺文件就显示空白——那会被读成"这次运行没记录"。

2. **日志包 ≠ 归档包。** 4A 的 `out/_archive/<期次>` 是**全量产物**快照
   （含 docx/parquet/PNG，13MB+）。日志包只取**回放所需的最小集**
   （json/md/csv/jsonl），目标是邮件能发、评审能存。两者不重复造。

3. **瀑布的 elapsed 是累计值不是步长。** `run_pipeline._emit` 写的
   `elapsed` 是**从进程启动起的累计秒**，直接拿来画柱子会把后一步画成
   「包含前面所有步」。必须取 `终态时刻 − start 时刻` 才是本步耗时。

产物清单由调用方传入（`jobs.collect_*`），本模块不反向依赖 jobs，
这样档案视图可以脱离演示站单独测。
"""
from __future__ import annotations

import datetime as dt
import io
import json
import pathlib
import zipfile

#: 日志包里的回放最小集（相对 out/<期次>/ 或 out/<期次>/_jobs/<id>/）
LOGPACK_PERIOD_FILES = (
    "run_log.json",
    "meta.json",
    "audit_record.json",
    "env_snapshot.json",
    "审计记录.md",
    "审批记录.md",
    "红色件清单.md",
    "red_slots.json",
    "table2.csv",
    "overview_facts.json",
    # agent 编排器轨迹（直跑路径没有，有就带上）
    "agent_events.jsonl",
    "state_history.jsonl",
    "task_runs.jsonl",
)

#: 日志包额外带的任务上下文（相对 out/_jobs/<id>/）
LOGPACK_JOB_FILES = (
    "job.json",
    "progress.jsonl",
    "console.log",
)

#: 日志包的下载 key（走既有 `/…/download/{key}` 白名单，不新增路由）
LOGPACK_KEY = "logpack"

#: 审计结论 → 页面徽标语义
_VERDICT_LABEL = {
    "pass": "全部通过",
    "review": "待人工确认",
    "fail": "不通过",
}


def _read_json(path: pathlib.Path):
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: pathlib.Path):
    if not path or not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue          # 追加写可能被截断最后一行，跳过即可
    return out


def _read_text(path: pathlib.Path):
    if not path or not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------- 状态机回放
def _synthesize_states(job):
    """直跑路径没有轨迹文件时的最小链：只含**确定发生过**的迁移。

    不臆造 retrying / stalled / escalated——那些只有编排器才知道。
    """
    if not job:
        return [], "无任务上下文，无法合成状态链"
    term = job.get("status") or ""
    chain = [
        {"from": "pending", "to": "running", "trigger": "提交任务",
         "ts": job.get("created_at") or "", "attempt": 1, "synthetic": True},
        {"from": "running", "to": term, "trigger": "流水线退出码 %s" % (job.get("exit_code"),),
         "ts": job.get("finished_at") or "", "attempt": 1, "synthetic": True},
    ]
    return chain, "演示站直跑路径不产生 state_history.jsonl，此链由 job.json 合成"


def state_replay(out_dir, job=None):
    """状态机回放：优先读 `state_history.jsonl`，缺则合成最小链并标注。"""
    rows = _read_jsonl(pathlib.Path(out_dir) / "state_history.jsonl")
    if rows:
        for r in rows:
            r["synthetic"] = False
        return {"chain": rows, "synthetic": False, "note": "", "n": len(rows)}
    chain, note = _synthesize_states(job)
    return {"chain": chain, "synthetic": True, "note": note, "n": len(chain)}


# ---------------------------------------------------------------- 任务瀑布
#: progress.jsonl 的事件语义：start 是开工，done/warn/failed 是收工
_DONE_STATUS = ("done", "warn", "failed")


def waterfall(events):
    """`progress.jsonl` → 每步耗时（**不含**「完成」汇总事件，见 `waterfall_summary`）。

    `elapsed` 是**累计秒**（从进程启动算起），本步耗时 = 收工时刻 − 开工时刻。
    没有 start 的步（脚本中途插入的 warn）按 0 计并标 `orphan`。
    顺序：按**开工累计秒**排（真执行序）；同一秒开工的多步保持**事件出现序**——
    按名字排会把 compute 排到 parse 前（2026-09-24 前端实报）。
    """
    buckets: dict = {}
    for i, e in enumerate(events or []):
        step = e.get("step") or e.get("name") or "?"
        if step == "done":
            continue        # 「完成」是收束汇总（elapsed=全链路总时长），不是一步
        b = buckets.setdefault(step, {"step": step, "name": e.get("name") or step,
                                      "start": None, "end": None, "status": "",
                                      "detail": "", "ts": e.get("ts", ""), "order": i})
        st = (e.get("status") or "").lower()
        el = e.get("elapsed")
        el = float(el) if isinstance(el, (int, float)) else None
        if st == "start":
            if b["start"] is None:
                b["start"] = el
            b["ts"] = e.get("ts", b["ts"])
        elif st in _DONE_STATUS:
            if el is not None and (b["end"] is None or el >= b["end"]):
                b["end"] = el
            b["status"] = st
            if e.get("detail"):
                b["detail"] = e["detail"]
        elif not b["status"]:
            b["status"] = st or b["status"]

    pairs = []
    for b in buckets.values():
        s, e = b["start"], b["end"]
        if s is not None and e is not None:
            sec = round(max(0.0, e - s), 1)
            orphan = False
        elif s is not None:
            sec, orphan = 0.0, True          # 只有开工没有收工：多半中途失败
        elif e is not None:
            sec, orphan = round(e, 1), True  # 只有收工没有开工：中途插入的事件
        else:
            sec, orphan = 0.0, True
        # 排序键：开工累计秒优先；缺失退收工；再缺就靠事件序兜底。
        # 同值（同一秒开工）用事件出现序——执行序，不按名字排。
        key = s if s is not None else e
        pairs.append(((key, b["order"]), {"step": b["step"], "name": b["name"],
                                          "status": b["status"] or "done",
                                          "detail": b["detail"], "sec": sec,
                                          "at": b["ts"], "orphan": orphan}))

    def _key(item):
        k, order = item[0]
        return (float("inf") if k is None else k, order)

    pairs.sort(key=_key)
    return [r for _, r in pairs]


def waterfall_summary(events):
    """「完成」汇总事件 → `{name, detail, at, sec}`（**不进步骤数组**；无则 None）。

    sec 是全链路总时长（累计 elapsed）。它混进步骤数组会让合计翻倍
    （96.5→193.0，2026-09-24 前端实报）——单列出来给展示用。
    """
    done = next((e for e in reversed(events or [])
                 if (e.get("step") or "") == "done"), None)
    if not done:
        return None
    sec = done.get("elapsed")
    return {"name": done.get("name") or "完成",
            "detail": done.get("detail") or "",
            "at": done.get("ts") or "",
            "sec": round(float(sec), 1) if isinstance(sec, (int, float)) else None}


# ---------------------------------------------------------------- 审计摘要
_AUDIT_TITLE = {
    "big_table": "大表全量回查",
    "slot_sample": "槽位抽样回查",
    "stale_scan": "陈旧期次残留扫描",
    "golden_bt": "金样回测",
    "manual_slots": "手工槽清点",
    # 🔴 键名要跟 CHECKS 注册的 id 一致（旧表写的是 charts，注册的是 figures——
    #    查不到就原样吐英文 id，2026-09-24 前端实报）。
    "figures": "图表抽查",
}


def _audit_summary(item):
    """单条审计项 → 一行人话 + 关键数字。字段缺失一律显示 `—`，不猜。"""
    iid = item.get("id", "?")
    row = {"id": iid, "title": _AUDIT_TITLE.get(iid, iid),
           "status": item.get("status", ""), "metric": "—", "reason": item.get("reason", "")}
    if iid == "big_table":
        row["metric"] = f"{item.get('cells_checked', '—')}/{item.get('cells_total', '—')} 格，差异 {item.get('n_diff', '—')}"
    elif iid == "slot_sample":
        row["metric"] = f"抽 {item.get('sample_size', '—')}/{item.get('slots_total', '—')} 处，差异 {item.get('n_diff', '—')}"
    elif iid == "stale_scan":
        row["metric"] = f"扫 {item.get('files_scanned', '—')} 个文件，高危 {item.get('n_high', '—')} 处"
    elif iid == "golden_bt":
        pct = item.get("pct")
        row["metric"] = (f"{pct}%（{item.get('unit', '')}）" if pct is not None
                         else f"阈值 {item.get('threshold', '—')}%（无结果）")
    elif iid == "manual_slots":
        row["metric"] = f"待签 {item.get('n_pending', '—')} 处 / 共 {item.get('slots_total', '—')} 槽"
    elif iid == "charts":
        row["metric"] = f"{item.get('n_ok', '—')}/{item.get('n_total', '—')} 通过"
    else:
        row["metric"] = item.get("metric", "—")
    return row


def audit_view(out_dir):
    rec = _read_json(pathlib.Path(out_dir) / "audit_record.json")
    if not rec:
        return {"exists": False, "verdict": "", "verdict_label": "",
                "rows": [], "generated_at": "", "truth_chain": ""}
    items = [_audit_summary(it) for it in rec.get("items", [])]
    verdict = rec.get("verdict", "")
    return {
        "exists": True,
        "verdict": verdict,
        "verdict_label": _VERDICT_LABEL.get(verdict, verdict or "—"),
        # 键名**不能叫 items**：Jinja 的 `audit.items` 会先命中 dict.items 方法，
        # 渲染时抛 "builtin_function_or_method is not iterable"（实测踩到）。
        "rows": items,
        "generated_at": rec.get("generated_at", ""),
        "truth_chain": rec.get("truth_chain", ""),
        "elapsed_s": round(sum(it.get("elapsed_s", 0) or 0
                               for it in rec.get("items", [])), 2),
    }


# ---------------------------------------------------------------- 汇总视图
def build(out_dir, job=None, artifacts=None):
    """一次运行的完整档案视图。缺什么标什么，绝不拿空值充数。"""
    out_dir = pathlib.Path(out_dir)
    run_log = _read_json(out_dir / "run_log.json") or {}
    prog = pathlib.Path(job["progress"]) if job and job.get("progress") else None
    events = _read_jsonl(prog) if prog else []
    # 「没读到」有两种：压根没有任务上下文（正常），或文件指针过期（异常）。
    # 混成一句"无进度事件"会让后者被当成前者——页面必须区分。
    progress_missing = bool(job) and bool(prog) and not prog.exists()

    wf = waterfall(events)
    replay = state_replay(out_dir, job=job)
    audit = audit_view(out_dir)
    env = _read_json(out_dir / "env_snapshot.json") or {}

    packs = logpack_files(out_dir, job=job)
    return {
        "period": out_dir.name,
        "out_dir": str(out_dir),
        "job": job or {},
        "job_id": (job or {}).get("id", ""),
        "run_log": run_log,
        "stats": (job or {}).get("stats") or run_log,
        "waterfall": wf,
        "waterfall_summary": waterfall_summary(events),
        "waterfall_total": round(sum(r["sec"] for r in wf), 1),
        "progress_path": str(prog) if prog else "",
        "progress_missing": progress_missing,
        "replay": replay,
        "audit": audit,
        "env": env,
        "artifacts": artifacts or [],
        "logpack": {"key": LOGPACK_KEY, "files": packs,
                    "n_files": len(packs),
                    "bytes": sum(p["size"] for p in packs)},
        "trace_files": [n for n in ("agent_events.jsonl", "state_history.jsonl",
                                    "task_runs.jsonl") if (out_dir / n).exists()],
    }


def _job_dir_hint(out_dir):
    """out/<期次>/_jobs/ 不一定存在，仅作兜底探测路径（不创建）。"""
    return pathlib.Path(out_dir) / "_jobs"


# ---------------------------------------------------------------- 日志包
def logpack_files(out_dir, job=None):
    """日志包内文件清单（供页面展示与打包共用，避免两处各列一遍）。"""
    out_dir = pathlib.Path(out_dir)
    out = []
    for name in LOGPACK_PERIOD_FILES:
        p = out_dir / name
        if p.exists():
            out.append({"name": name, "scope": "期次", "size": p.stat().st_size})
    if job:
        jd = pathlib.Path(job.get("progress", "")).parent if job.get("progress") else None
        if jd and jd.is_dir():
            for name in LOGPACK_JOB_FILES:
                p = jd / name
                if p.exists():
                    out.append({"name": name, "scope": "任务", "size": p.stat().st_size})
    return out


def _readme(out_dir, job, files):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "文衡 · 运行日志包",
        "=" * 40,
        f"期次      ：{out_dir.name}",
        f"任务 ID   ：{(job or {}).get('id', '（无任务上下文）')}",
        f"打包时间  ：{now}",
        f"文件数    ：{len(files)}",
        "",
        "本包 = 回放所需的最小集（json / md / csv / jsonl）。",
        "完整产物快照（含 docx、parquet、图表 PNG）请看归档目录 out/_archive/<期次>/。",
        "",
        "文件清单：",
    ]
    for f in files:
        lines.append(f"  [{f['scope']}] {f['name']}  ({f['size']} B)")
    lines += [
        "",
        "数字口径：全部来自台账单元格，运行期大模型不进入数据路径。",
    ]
    return "\n".join(lines) + "\n"


def pack(out_dir, job=None):
    """打日志包 → `(bytes, 文件名)`。纯内存，不落盘、不污染 out/。"""
    out_dir = pathlib.Path(out_dir)
    files = logpack_files(out_dir, job=job)
    period = out_dir.name
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"wenheng-logpack-{period}-{stamp}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", _readme(out_dir, job, files))
        for f in files:
            if f["scope"] == "任务" and job and job.get("progress"):
                src = pathlib.Path(job["progress"]).parent / f["name"]
                arc = f"job/{f['name']}"
            else:
                src = out_dir / f["name"]
                arc = f"period/{f['name']}"
            try:
                z.write(src, arc)
            except OSError:
                continue          # 打包失败不该让下载整套崩掉
    return buf.getvalue(), name
