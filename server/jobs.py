# -*- coding: utf-8 -*-
"""文衡演示站任务管理：创建任务 → 子进程跑流水线 → JSONL 进度 + 控制台日志。

约定：单机单任务（一次只跑一期，约 3 分钟）；uvicorn 单 worker。

状态口径（2026-09-15 接线）
--------------------------------------------------------------------------------
任务状态**不再由本文件自己定义**，一律取自 `src/agent/states.py`（10 态，权威）。
本文件此前用的是 `done / warn / failed / interrupted` 这套 4 态旧名，与
WH-DOC-03 §6.3 / WH-DOC-02 R-13 要求的 10 态对不上——`done` 不等于文档里的
`Completed`，`interrupted` 干脆是个文档里不存在的状态。

改动要点：
  · 写盘一律写新名；读盘经 `normalize()` 认旧名，历史任务记录无需迁移；
  · `TERMINAL` 只保留一个来源，`app.py` 判终态请用 `is_terminal()`（会先归一）。

存储口径（2026-10-21，ADR-0012 第二批）
--------------------------------------------------------------------------------
任务记录**不再落 `out/_jobs/<id>/job.json`**，唯一真相源是系统状态库
（`src/state_store.py` 的 `jobs` 表，`out/_state/wenheng.sqlite`）。
`out/_jobs/<id>/` 目录照旧创建——`progress.jsonl` / `console.log` / `forecast_choice.json`
还在里面（追加日志与 SSE 的字节偏移 tail 都靠它们），只是不再有 `job.json`。
对外签名与返回字典形状一个没动：`app.py`、前端、e2e 建在这些形状上。
"""
import asyncio
import datetime as dt
import json
import os
import pathlib
import secrets
import time
import urllib.parse

from . import config

#: config 导入时已把 src/ 放进 sys.path，这里可直接拿到 agent 层
from agent import states as agent_states
from src import atomic_io
from src import display_path
from src import forecast_choice
from src import state_store

#: 期次口径唯一来源（re-export，不另抄一份正则）
from src import period as _period

#: 任务终态集合（5 个）。判终态请用 `is_terminal()`，它兼容旧名。
TERMINAL = agent_states.TERMINAL

PERIOD_RE = _period.PERIOD_RE
PERIOD_DIR_RE = _period.PERIOD_DIR_RE    # out/ 下的期次目录（可能是 202605_复现）
_running: set = set()


def is_terminal(status):
    """终态判定。旧名（done/warn/interrupted）先归一，历史任务不会被判成"仍在跑"。"""
    return agent_states.is_terminal(agent_states.normalize(status))


def status_label(status):
    """状态中文名。前端 badge 与列表页都走这里，避免各处再写字典。"""
    return agent_states.label(status)


def status_from_exit_code(code):
    """流水线退出码 → 10 态任务状态。

    0 全绿 → completed；1 有断言未过 → warned（产物仍在，待馆员复核）；
    其它（含起不来进程的 -1）→ failed。抽成函数是为了可测：
    这段映射错了不会抛异常，只会把失败显示成完成。
    """
    if code == 0:
        return agent_states.COMPLETED
    if code == 1:
        return agent_states.WARNED
    return agent_states.FAILED


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def job_dir(job_id):
    return config.JOBS_DIR / job_id


def state_db_path():
    """任务记录所在的状态库：`out/_state/wenheng.sqlite`（与签单/复核同一个库）。

    口径跟 `JOBS_DIR` 走（`out/_jobs` 的同级 `_state/`）：测试把 `JOBS_DIR` 指到 tmp，
    库就落在 tmp，碰不到演示数据。`WENHENG_STATE_DB` 仍优先（e2e / 子进程靠它对齐）。
    """
    return state_store.db_path(config.JOBS_DIR)


def _relocate(j):
    """把 `progress` / `console` 重新指回 `out/_jobs/<id>/` 下的同名文件。

    为什么需要：历史记录里存的是**绝对路径**，而工作区被搬过
    （`首届高校图书馆“AI+管理服务”\\wenheng` → `首届高校图书馆\\wenheng`）。
    路径失效后进度事件与控制台输出全读不到，档案页会静默显示"没有进度事件"——
    读起来像"这次运行不是演示站发起的"，其实是**文件还在、指针过期**。

    2026-10-22 起新记录存**仓库相对**（`display_path.to_repo_relative`），
    `_restore_paths()` 已把它们拼回仓库下的绝对路径；这里的同名修补仍然要留：
    记录随部署包搬到另一台机器后，旧绝对路径照样失效，而文件就躺在
    `out/_jobs/<id>/` 里。只在本职目录里找同名文件；找不到就保持原值
    （让上层显示为缺失，而不是假装存在）。
    """
    for key in ("progress", "console"):
        old = j.get(key)
        if not old:
            continue
        # 先把 Windows 分隔符归一：部署机是 Linux，`Path("C:\\…\\progress.jsonl").name`
        # 在那边整串都算文件名，重定位会静默失效（记录随包跨平台走，必须两种写法都认）。
        name = pathlib.PurePath(str(old).replace("\\", "/")).name
        cand = job_dir(j["id"]) / name
        if cand.exists():
            j[key] = str(cand)
    return j


#: 任务记录里存**仓库相对写法**的字段（`display_path` 口径）：
#: `input` 是母本/当期核对副本，`progress` / `console` 是 `out/_jobs/<id>/` 下的两个文件。
#: 相对写法在部署包与换机后仍成立；绝对写法只可能是历史记录或仓库外的路径。
PATH_KEYS = ("input", "progress", "console")


def _restore_paths(j):
    """读侧还原：仓库相对 → 仓库下的**绝对路径**（`progress` / `console` 还要能直接打开）。

    为什么必须还原：`archive.build` / `/api/jobs/{id}/events` / 日志包 / 重跑
    都把 `job["progress"]`、`job["input"]` 当真实路径用（`pathlib.Path(...)`、
    `.parent`、`.exists()`）。留着相对写法在"服务不是从仓库根启动"时会解析错。

    绝对写法**原样不动**：历史记录里是旧工作区的绝对路径，改写成 `Path(...)`
    的字符串会把 `D://旧//…` 归一成 `D:\\旧\\…`，反而动了原文；交给 `_relocate`
    按同名文件修补。
    """
    for key in PATH_KEYS:
        old = j.get(key)
        if not isinstance(old, str) or not old.strip():
            continue
        if display_path.is_absolute(old):
            continue
        j[key] = str(display_path.from_repo_relative(old, config.ROOT))
    return j


def _prepare(j):
    """读出来的任务记录：状态旧名归一 + 路径还原/重定位（**唯一**的读侧加工点）。"""
    if isinstance(j, dict) and "status" in j:
        j["status"] = agent_states.normalize(j.get("status"))
        j = _restore_paths(j)
        j = _relocate(j)
    return j


def read_job(job_id):
    """读一条任务记录；没有 → None（不再看 `job.json`，磁盘上那份不再是读路径）。"""
    j = state_store.get_job(state_db_path(), job_id)
    return _prepare(j) if j is not None else None


def write_job(job):
    """落库（upsert）；目录照旧确保存在——`_run` 要往里写 console.log。"""
    job_dir(job["id"]).mkdir(parents=True, exist_ok=True)
    state_store.put_job(state_db_path(), job)


def _forecast_choice_snapshot(period):
    """按 forecast-choice GET 的读序冻结配置，不改写 legacy 文件（见 forecast_choice.snapshot）。"""
    return forecast_choice.snapshot(
        period, choices_dir=config.FORECAST_CHOICES_DIR,
        out_dir=config.OUT_DIR, snapshot_at=_now())


def list_jobs(limit=20, period=None):
    jobs = state_store.list_jobs(state_db_path(), period=period, limit=limit)
    return [_prepare(j) for j in jobs]


#: 「在跑」的库内状态：非终态里除 `waiting_approval` 之外的那几个。
#: 待签单的任务没有进程在跑，不该挡住新任务——与旧实现只看内存 `_running` 同义。
LIVE_STATUSES = (agent_states.PENDING, agent_states.RUNNING,
                 agent_states.RETRYING, agent_states.STALLED)


def active_job():
    """「一次只跑一期」的判据：库里第一条在跑的任务（一次查询，不扫目录）。"""
    for j in state_store.list_jobs(state_db_path(), statuses=LIVE_STATUSES, limit=20):
        j = _prepare(j)
        if j and not is_terminal(j.get("status")):
            return j
    return None


def recover_stale():
    """服务重启后，把没有存活进程的 running 任务结掉。

    10 态里没有 `interrupted`（旧代码在这里造的词）。这里落 `failed`：
    进程随服务一起消失属"意外终止"，不是馆员主动 `cancelled`；
    也不落 `stalled`——停滞是**非终态**，留着会让任务永远挂在半途。
    """
    for j in state_store.list_jobs(state_db_path(), statuses=(agent_states.RUNNING,)):
        j = _prepare(j)
        if j and j.get("status") == agent_states.RUNNING:
            j["status"] = agent_states.FAILED
            j["finished_at"] = _now()
            j["recovered_from"] = "service_restart"
            write_job(j)


def _display(p):
    """真实路径 → 记录里存的写法（仓库相对；仓库外才绝对）。口径见 `src/display_path.py`。"""
    return display_path.to_repo_relative(p, config.ROOT)


def create_job(period, input_path, actor, backtest=False):
    if not PERIOD_RE.match(period):
        raise ValueError("期次格式应为 6 位数字，如 202609")
    if active_job():
        raise RuntimeError("已有任务正在运行")
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    d = job_dir(jid)
    d.mkdir(parents=True, exist_ok=True)
    snapshot_path = d / "forecast_choice.json"
    snapshot = _forecast_choice_snapshot(period)
    atomic_io.write_text_atomic(
        snapshot_path, json.dumps(snapshot, ensure_ascii=False, indent=1))
    job = {
        "id": jid, "period": period,
        # 路径一律存**仓库相对**（`display_path` 口径）：记录随部署包走，
        # 绝对路径换个用户名/换台机器就不成立，还会把本机路径打进包里。
        "input": _display(input_path),
        "actor": actor,
        "backtest": bool(backtest), "status": agent_states.RUNNING,
        "created_at": _now(), "started_at": _now(), "finished_at": None,
        "exit_code": None, "progress": _display(d / "progress.jsonl"),
        "console": _display(d / "console.log"),
    }
    write_job(job)
    _running.add(jid)
    asyncio.create_task(_run(job))
    return job


async def _run(job):
    jid = job["id"]
    d = job_dir(jid)
    console = d / "console.log"
    env = os.environ.copy()
    env["WENHENG_PROGRESS_FILE"] = str(d / "progress.jsonl")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["WENHENG_FORECAST_CHOICE_SNAPSHOT"] = str(d / "forecast_choice.json")
    if config.REFERENCE_DOCX:
        env["WENHENG_REFERENCE_DOCX"] = config.REFERENCE_DOCX
    # 期次显式传给流水线（2026-10-13 起输入是母本，台账最新期 ≠ 被跑期；
    # `--period` 让大表/图表/预测/报告全部按被跑期切窗——历史期补跑同一口径）。
    # 记录里是仓库相对写法，起进程前拼回真实路径（子进程 cwd 不必等于仓库根）。
    ledger = display_path.from_repo_relative(job["input"], config.ROOT)
    cmd = [config.PYTHON, str(config.PIPELINE), str(ledger), "--period", job["period"]]
    if job.get("backtest"):
        cmd.append("--backtest")

    code, err = None, None
    try:
        with open(console, "wb") as f:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(config.ROOT), env=env,
                stdout=f, stderr=asyncio.subprocess.STDOUT)
            code = await proc.wait()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        code = -1

    # 退出码 → 状态。语义与 `agent/flow.py` 的终态保持同一套词：
    #   0 → completed：全绿，可直接进人工审批门
    #   1 → warned   ：跑完了但断言未过，产物仍在，需馆员复核
    #   其它 → failed ：脚本异常退出，无可用产物
    # 注：`escalated`（自愈逾限）只在编排器 `agent/flow.py` 里产生，
    # 演示站走的是 `run_pipeline.py` 直跑路径，不会自己造这个状态。
    status = status_from_exit_code(code)

    job = read_job(jid) or job
    job.update({"status": status, "exit_code": code, "finished_at": _now()})
    if err:
        job["error"] = err

    # 流水线按期次自动检测输出目录（可能与上传目录名不同）
    try:
        t_start = dt.datetime.strptime(job["started_at"], "%Y-%m-%d %H:%M:%S").timestamp() - 10
    except (KeyError, ValueError):
        t_start = 0
    fresh_logs = [p for p in config.OUT_DIR.glob("*/run_log.json")
                  if p.stat().st_mtime >= t_start]
    if fresh_logs:
        newest = max(fresh_logs, key=lambda p: p.stat().st_mtime)
        job["out_period"] = newest.parent.name
        try:
            job["stats"] = json.loads(newest.read_text(encoding="utf-8"))
            if job["stats"].get("missing"):
                job["missing"] = job["stats"]["missing"]
        except (OSError, json.JSONDecodeError):
            pass
    write_job(job)
    _running.discard(jid)


def collect_artifacts(job):
    """可下载产物：key → 路径（全部位于 out/<period>/）。

    只列出本任务运行后新生成的产物（防止展示上一次运行的残留文件）。
    """
    out = config.OUT_DIR / (job.get("out_period") or job["period"])
    try:
        t_start = dt.datetime.strptime(job["started_at"], "%Y-%m-%d %H:%M:%S").timestamp() - 10
    except (KeyError, ValueError):
        t_start = 0

    def fresh(path):
        return bool(path) and path.exists() and path.stat().st_mtime >= t_start

    return _collect(out, f"/jobs/{job['id']}", f"/jobs/{job['id']}/download", fresh)


def collect_period_artifacts(period_dir):
    """按「期次」列产物（首屏对勘本用，没有任务上下文，也不做新鲜度过滤）。"""
    out = config.OUT_DIR / period_dir

    def fresh(path):
        return bool(path) and path.exists()

    q = urllib.parse.quote(str(period_dir))
    return _collect(out, f"/p/{q}", f"/p/{q}/download", fresh,
                    collation_url=f"/p/{q}")


# 产物表：key, 中文名, 路径（None = 在线查看型）, 是否主产物
def _artifact_table(out, fresh):
    report = next((p for p in out.glob("报告初稿_*.docx") if fresh(p)), None) if out.exists() else None
    diff = next((p for p in out.glob("对照差异报告*.md") if fresh(p)), None) if out.exists() else None
    return [
        ("report", "报告初稿（Word）", report, True),
        ("collation", "对勘本（正文级对照）", None, True),
        ("red_list", "红色件清单（Markdown）", out / "红色件清单.md", True),
        ("approval", "审批记录（签单后生成）", out / "审批记录.md", False),
        ("red_view", "红色件清单（逐格在线查看）", None, False),
        ("diff", "对照差异报告（金样回测）", diff, False),
        # 只在断言未过时产出（`run_pipeline.py` 带病出稿时附的核对指引）。
        # ⚠ 它与 `agent/flow.py` 那份《诊断报告》同名但不同源：那份是自愈逾限、
        #   拦停后的交接物，这份是报告照出时的"哪里脏、怎么核对"。
        ("diagnosis", "诊断报告（断言未过时的核对指引）", out / "诊断报告.md", False),
        ("forecast", "预测回测报告", out / "预测回测报告.md", False),
        ("table2", "大表数据（CSV）", out / "table2.csv", False),
        ("red_json", "红色件审计明细（JSON）", out / "red_slots.json", False),
        ("runlog", "运行日志（JSON）", out / "run_log.json", False),
    ]


def _collect(out, page_url, download_url, fresh, collation_url=None):
    items = []
    for key, label, path, primary in _artifact_table(out, fresh):
        if key in ("red_view", "collation"):
            if fresh(out / "red_slots.json"):
                if key == "red_view":
                    items.append({"key": key, "label": label,
                                  "name": "红色件清单",
                                  "size": None, "url": f"{page_url}/redslots",
                                  "primary": primary})
                else:
                    # 🔴 期次上下文没有 /p/{期次}/collation 这条路由（2026-09-24 修：
                    #    原来一律拼 {page_url}/collation，期次档案页的「对勘本」链接 404）。
                    #    期次的对勘本就是 /p/{期次} 本身（现 302 到新站阅读视图）。
                    items.append({"key": key, "label": label,
                                  "name": "在线查看",
                                  "size": None,
                                  "url": collation_url or f"{page_url}/collation",
                                  "primary": primary})
            continue
        if fresh(path):
            items.append({"key": key, "label": label, "name": path.name,
                          "size": path.stat().st_size,
                          "url": f"{download_url}/{key}",
                          "primary": primary})
    return items


def _resolve(items, out, key):
    for a in items:
        if a["key"] == key and key not in ("red_view", "collation"):
            p = out / a["name"]
            if p.exists():
                return p
    return None


def resolve_artifact(job, key):
    out = config.OUT_DIR / (job.get("out_period") or job["period"])
    return _resolve(collect_artifacts(job), out, key)


def resolve_period_artifact(period_dir, key):
    return _resolve(collect_period_artifacts(period_dir),
                    config.OUT_DIR / period_dir, key)


CHART_EXT = frozenset({".png"})


def _resolve_under(base, rel):
    """把 `rel` 安全解析到 `base` 之下；越界/非图一律 None。

    三道闸（与 `resolve_chart` 同口径，抽出来给灵活报告复用）：
      1. 拒绝对路径与盘符（`(base / "/etc/passwd")` 在 pathlib 下会**整体替换**
         成绝对路径——不先挡住的话后面全白搭）；
      2. 拒 `.` / `..` / 空段；
      3. 解析后必须**真的落在** base 里，且后缀是允许的图片类型。
    """
    if not rel:
        return None
    rel = str(rel).replace("\\", "/")
    pp = pathlib.PurePosixPath(rel)
    if pp.is_absolute() or ":" in (pp.parts[0] if pp.parts else ""):
        return None
    parts = [p for p in pp.parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None

    base = pathlib.Path(base).resolve()
    try:
        p = (base / pathlib.Path(*parts)).resolve()
    except (OSError, ValueError):
        return None
    if p.suffix.lower() not in CHART_EXT:
        return None
    if p == base or os.path.commonpath([str(base), str(p)]) != str(base):
        return None
    return p if p.is_file() else None


def resolve_chart(out_dir, rel):
    """把 `charts/<学科>/<图名>.png` 解析成磁盘路径；越界一律 None。

    这个函数只有一件事：**拒绝一切越界请求**。`rel` 直接来自 URL，
    放过一个 `..` 或绝对路径就是任意文件读取（能读到 `/opt/wenheng/server/.env`）。
    三道闸见 `_resolve_under`。
    """
    return _resolve_under(pathlib.Path(out_dir) / "charts", rel)


def resolve_flex_chart(out_dir, intent, name):
    """灵活报告的图：`flexible/<intent>/charts/<name>.png`。

    与复刻报告**分开**：灵活图若混进 `out/<期次>/charts/`，
    会破坏「99 张图 99 个唯一哈希」这条验收判据。
    路径段仍逐层校验（intent 也必须无 `..` / 无分隔符）。
    """
    if not intent or not name:
        return None
    if any(sep in str(intent) for sep in ("/", "\\", "..")):
        return None
    base = pathlib.Path(out_dir) / "flexible" / intent / "charts"
    return _resolve_under(base, name)


def list_charts(out_dir):
    """枚举 `out_dir/charts/` 下的全部期次图，按子目录分组。

    为什么要有这个：红件清单页共 354 条，图只占其中 99 条，而且位置字段写的是
    「正文」、排在全部表数值（240 条）之后 —— 用户打开页面看到的是一屏 csv 来源的
    数值行，**看不出哪里有图**，得先搜「png」才筛得出来。图册页给的是
    「打开就能看全」的入口。

    路径由服务端枚举而非来自 URL，但仍走 `resolve_chart` 复核一遍：
    防的是符号链接、以及未来有人把这里改成接收外部输入。
    返回 `[{group, name, rel}]`，`rel` 是相对 `charts/` 的 posix 路径。
    """
    root = pathlib.Path(out_dir) / "charts"
    if not root.is_dir():
        return []
    items = []
    for p in sorted(root.rglob("*")):
        try:
            if not p.is_file() or p.suffix.lower() not in CHART_EXT:
                continue
            rel = p.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if resolve_chart(out_dir, rel) is None:
            continue
        head = pathlib.PurePosixPath(rel)
        items.append({
            "group": head.parts[0] if len(head.parts) > 1 else "（根目录）",
            "name": p.name,
            "rel": rel,
        })
    return items


def read_progress(job):
    p = pathlib.Path(job.get("progress", ""))
    if not p or not p.exists():
        return []
    events = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
