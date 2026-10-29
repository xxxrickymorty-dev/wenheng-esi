# -*- coding: utf-8 -*-
"""自动取数台路由组：`/api/periods/{period}/acquisition/*` 与 `/api/acquisition/browser`。

任务卡 01（2026-10-25）：整段从 `server/app.py:909-1386` 迁出。三条不变：
  · **接口路径与返回结构一律不动**——`server/e2e_check.py` 的 152 项断言、旧站模板、
    新前端都在依赖它们；
  · 函数体逐字搬运，含函数内 `import` 与既有 `# noqa` 注释；
  · 装饰器顺序不变：`@router.get/post` 在外、`@user_route` 在内（顺序反了守卫不执行）。

两个依赖已下沉到 `server/guards.py`：`current_user`、`_period_missing`。
它们原本在 `app.py`，若留在本模块顶层 `from ..app import ...` 会形成
`app → routes.acquisition → app` 的循环导入。

⚠️ 测试按 `app_module.<名字>` 直取这里的 handler 与 `_acq_*` helper
（`tests/test_acquire_preflight.py`、`test_acquisition_datapack.py`、
`test_api_acquisition_open.py`）。所以 `server/app.py` **必须**把它们 re-export 回去，
见 app.py import 区的注释——少一个测试就红，且卡片要求「不改测试」。
"""
import pathlib
import re
import subprocess
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .. import acquisition, config, datapack
from ..guards import _period_missing, current_user, user_route

router = APIRouter()


def _acq_expected_data(period: str) -> dict:
    """这一期**本该**对应哪一档数据：ESI 发布月＝期次当月；InCites 快照按 SNAP_MAP 解析。"""
    from src import acquisition_state as _st                          # noqa: PLC0415
    y, m = period[:4], int(period[4:6])
    try:
        snap = _st.resolve_snapshot(period, _st.INCITES_ROOT_DEFAULT) or ""
    except Exception:                                                # noqa: BLE001
        snap = ""
    return {"esi": f"{y} 年 {m} 月", "incites": str(snap)}


def _acq_reconcile(period: str, state: dict) -> dict:
    """要求期次 vs **实际下到哪一期**（票 03）。

    ESI/InCites 的导出接口没有期次参数——抓的是**当前发布**；所以对账是唯一能发现
    「拿当期数据冒充往期」的地方。状态里的 data_period/snapshot 是取数当时从网站页面读到的。
    还没取到任何文件时 `ok=true`（无可对账），免得开新一期就先弹「数据期对不上」。
    """
    exp = _acq_expected_data(period)
    act = state.get("data_period") or {}
    actual = {"esi": str(act.get("esi") or ""), "incites": str(state.get("snapshot") or "")}
    # 还没取到任何文件（开新一期/刚检查过）：无可对账，别报「对不上」吓人
    if not actual["esi"] and not actual["incites"]:
        return {"expected": exp, "actual": actual, "ok": True}
    ok = bool(actual["esi"]) and actual["esi"] == exp["esi"] \
        and (not exp["incites"] or actual["incites"] == exp["incites"])
    return {"expected": exp, "actual": actual, "ok": ok}


def _acq_touched(period: str) -> bool:
    """这一期有没有**取数动静**（不只是点过一次「重新检查」）。

    只检查过的状态里只有 `{period, preflight}`——没有 groups/totals/copy。
    用它把「点过一次检查的空期次」从期次列表和「往期」判据里排除掉。
    """
    st = acquisition.load(period) or {}
    return bool(st.get("groups") or st.get("totals") or st.get("copy"))


def _acq_opened(period: str) -> bool:
    """这一期是不是**开新一期**登记出来的空壳（票 05）。

    空壳只落了 preflight、没有取数动静，按 `_acq_touched` 本不算；但既已登记就该出现在
    期次列表里（否则 `?period=` 深链会被前端「列表没有就退回首期」冲掉）。用独立标记
    `opened` 区分于「只点过一次重新检查」的临时状态，且**不**计入 `_acq_touched`——
    否则「开一期新」会把当前期误判成「往期只读」。
    """
    return bool((acquisition.load(period) or {}).get("opened"))


def _acq_mode(period: str) -> str:
    """`collect`＝当期可取；`readonly`＝往期档案只读（票 03）。

    判据是**真取过**：比它更新的期次里只要有一期有取数动静（`_acq_touched`），它就是往期
    （ESI/InCites 不提供历史数据，对往期重取只会把当期数据写进往期目录）。
    ⚠️ 只看"有没有状态文件"不够——**点一次「重新检查」也会落个状态文件**，那不算取过。
    """
    try:
        if any(p > period and _acq_touched(p) for p in acquisition.periods()):
            return "readonly"
    except Exception:                                                # noqa: BLE001
        pass
    return "collect"


@router.get("/api/periods/{period}/acquisition")
@user_route
async def api_period_acquisition(request: Request, period: str):
    """自动取数台状态（只读）。没有取数记录时 started=false——界面显示「还没开始」，不编数据。

    状态由取数流程写入 `out/_acquisition/<期次>.json`（人触发；见 ADR-0004）。
    另附 `mode`（当期可取 / 往期只读）与 `reconcile`（要求期次 vs 实际数据期，票 03）。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    mode = _acq_mode(period)
    state = acquisition.load(period)
    if state is None:
        return {"period": period, "started": False, "mode": mode}
    lv = _acq_op_liveness(period, state)          # 只读判断：前端据此显示「疑似中断」
    if lv is not None:
        state = {**state, "op": {**(state.get("op") or {}), "liveness": lv}}
    return {"period": period, "started": True, "mode": mode,
            "reconcile": _acq_reconcile(period, state), **state}


# ------------------------------------------------------------------ 自动取数台 · 写动作（X3）
# 全部由**人按键**触发（R-1）：这里是拉起 `tools/acquire.py` 的**非交互执行口**，
# 进度由取数流程写回 `out/_acquisition/<期次>.json`，前端轮询读取。不做任何数据加工。
def _acq_acquire_py():
    return config.ROOT / "tools" / "acquire.py"


def _acq_op_liveness(period: str, st: dict) -> str | None:
    """正在跑的任务现在算不算活着（**只读判断，不改状态**）：

    - `alive`：有 pid 且进程在；或没有 pid 但状态文件 15 分钟内动过（启动窗口/旧状态）；
    - `dead`：有 pid 但进程没了（暴死/被强杀）；
    - `stale`：没有 pid 且超过 15 分钟没动静（ADR-0010 之前留下的旧僵尸）；
    - 非 running → None。

    GET 只把它算出来展示（`op.liveness`）；**自动结清**发生在写动作路径（`_acq_op_running`）。
    """
    op = st.get("op") or {}
    if op.get("state") != "running":
        return None
    pid = op.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        return "alive" if acquisition.pid_alive(pid) else "dead"
    try:
        age = time.time() - acquisition.state_path(period).stat().st_mtime
    except OSError:
        age = 0
    return "alive" if age <= acquisition.OP_STALE_SECONDS else "stale"


def _acq_op_running(period: str):
    """正在跑的取数任务；**判活＝进程在不在**（`op.pid`），无 pid 的旧状态回退 15 分钟时间口径。

    ADR-0010（2026-10-19）：此前只看「状态文件 1 小时内有改动」——进程暴死后要干等
    1 小时才放行（2026-10-17 实测）。现在判活落在 `_acq_op_liveness`；`dead`/`stale` 时
    **在这里（写动作路径；GET 不改状态）**把 `op` 落 `failed` 并放行新任务。
    """
    st = acquisition.load(period) or {}
    lv = _acq_op_liveness(period, st)
    if lv is None:
        return None
    if lv == "alive":
        return st.get("op") or {}
    why = "任务进程已退出" if lv == "dead" else "太久没有动静"
    st["op"] = {**(st.get("op") or {}), "state": "failed",
                "note": f"上次运行中断：{why}",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        acquisition.write_state(period, st)
    except OSError:
        pass
    return None


def _acq_kill_tree(pid: int) -> bool:
    """把取数任务**连它的子进程**一起停掉（Windows `taskkill /T /F`；POSIX 杀进程组）。"""
    import os
    import signal
    if os.name == "nt":
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S603
                               capture_output=True, text=True, timeout=30)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False


def _acq_spawn(period: str, action: str, extra: list | None = None):
    """拉起一个取数任务（detached）——先占位写「正在跑」，再起进程。"""
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    running = _acq_op_running(period)
    if running:
        return JSONResponse({"error": "有一项下载数据任务还在跑，等它完成再试。",
                             "hint": running.get("note", "")}, status_code=409)
    st = acquisition.load(period) or {}
    st["op"] = {"kind": action if action != "fetch" else "fetch", "state": "running",
                "note": "刚排上队，正在开始", "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    acquisition.write_state(period, st)
    log = config.OUT_DIR / "_acquisition" / f"{period}-{action}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    import os
    with open(log, "a", encoding="utf-8") as fh:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8",
               "PYTHONUNBUFFERED": "1"}
        subprocess.Popen(  # noqa: S603 — 固定脚本路径 + 期次已校验，无注入面
            [str(config.PYTHON), str(_acq_acquire_py()), action, period, *(extra or [])],
            cwd=str(config.ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env,
            # POSIX：自成进程组，「停止下载」才能连子进程一起停（Windows 用 taskkill /T）
            start_new_session=(os.name != "nt"))
    return {"ok": True, "started": True, "log": log.name}


#: 「取数专用浏览器」＝独立 profile + CDP 9222 的 Chrome；取数脚本靠附着它工作。
#: **凭证靠 Chrome 自己记住，系统从不碰账号密码**（`src`/`tools` 侧红线；首次需人工登录一次）。
def _acq_chrome_exe():
    """找本机 Chrome（装在哪都行）；找不到返回 None。"""
    import os
    cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(str(pathlib.Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    for p in cands:
        if pathlib.Path(p).exists():
            return p
    return None


def _acq_cdp_responds() -> bool:
    """9222 有没有**能应答 CDP 版本 JSON**的浏览器（不管是谁的）。"""
    import json as _json
    import urllib.request as _urlreq
    for url in ("http://127.0.0.1:9222", "http://localhost:9222"):
        try:
            with _urlreq.urlopen(url + "/json/version", timeout=2) as r:
                if r.status == 200 and _json.loads(r.read()).get("Browser"):
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _acq_cdp_alive() -> bool:
    """「下载数据专用浏览器」在跑：①9222 应答 CDP 版本 JSON **且** ②端口占用者命令行带专用 profile。

    只看①会被任意占 9222 的进程骗过（2026-10-17 实测：opencode 会话遗留的无头 Edge 也开 9222，
    `/json/version` 照样 200 → 曾被当成「已经在跑」→ 永远不开登录窗口）。认主口径见
    `src/acquisition_state.cdp_browser_ours`。
    """
    return _acq_cdp_responds() and acquisition.cdp_browser_ours()


def _acq_kill_profile_chrome(profile: pathlib.Path) -> int:
    """关掉占着这个 profile 的 Chrome 进程。

    同一个 profile 只能有一个浏览器实例：**先跑起来的那个没带调试端口时，后起的进程会
    把 URL 转交给它、自己不开端口**——那样 9222 永远起不来（2026-10-15 实测）。
    只关"命令行里带这个 profile"的进程，不碰用户其它 Chrome 窗口；登录态存在 profile 里，重开还在。
    """
    ps = ("$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\"; "
          "$hit = $p | Where-Object { $_.CommandLine -like '*" + str(profile) + "*' }; "
          "$n = @($hit).Count; "
          "$hit | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
          "$n")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=40)
        return int((r.stdout or "0").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


@router.post("/api/acquisition/browser")
@user_route
async def api_acq_browser(request: Request):
    """把「下载数据专用浏览器」拉起来（独立 profile `~/.chrome-clarivate` + CDP 9222）。

    已经在跑就不重复起。**只负责开窗**——登录仍由人（或 Chrome 记住的凭据）完成。
    9222 被**别的**程序占着时明确报错、不硬开（新开的 Chrome 抢不到端口，白弹窗还误导）。
    """
    if _acq_cdp_alive():
        return {"ok": True, "started": False, "already": True,
                "note": "下载数据专用浏览器已经在跑。"}
    if _acq_cdp_responds():
        owner = acquisition.cdp_listener_cmdline()[:120]
        return {"ok": False, "started": False, "already": False,
                "note": "9222 端口被别的程序占着（不是下载数据专用浏览器），"
                        f"先关掉占用它的浏览器/程序再试。占用者命令行：{owner}"}
    exe = _acq_chrome_exe()
    if not exe:
        return {"ok": False, "started": False, "already": False,
                "note": "没找到 Chrome（装一个，或把 chrome.exe 的路径告诉我）。"}
    profile = acquisition.CDP_PROFILE_DIR
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "started": False, "already": False, "note": f"准备 profile 目录失败：{e}"}
    # 同一 profile 只能一个实例：先把"没带调试端口"的那个收掉，否则新进程只转交 URL、不开 9222
    closed = _acq_kill_profile_chrome(profile)
    if closed:
        time.sleep(1.5)
    try:
        subprocess.Popen(  # noqa: S603 —— 固定路径 + 固定参数，无外部输入
            [exe, "--remote-debugging-port=9222", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check",
             # 入口与取数脚本一致（不是站点根）：ESI 走 legacy Indicators；InCites 走
             # `/#/analysis/0/organization`（NG InCites SPA）——站点根会落到别的产品入口，
             # 实测会显示 No Subscription Found（2026-10-16）
             "https://esi.clarivate.com/IndicatorsAction.action?app=esi&Init=Yes",
             "https://incites.clarivate.com/#/analysis/0/organization"],
            cwd=str(config.ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"ok": False, "started": False, "already": False, "note": f"浏览器没起来：{e}"}
    return {"ok": True, "started": True, "already": False, "closed": closed,
            "note": "已打开下载数据专用浏览器；首次使用需要在这个窗口里登录 ESI / InCites 一次。"}


def _acq_data_block(period: str):
    """取数前「数据期」校验（票 04）：**明确判定未更新**时拦下，读不到就放行。

    判据来自最近一次 preflight（`state.preflight.data`）：要求期次 vs 网站数据集更新日。
    宁可放行也不要因网络/登录抖动把取数锁死——真正的不发车由前端「开始前检查」先挡一遍。
    """
    st = acquisition.load(period) or {}
    data = (st.get("preflight") or {}).get("data") or {}
    if data.get("ok") is False:
        return JSONResponse({"error": data.get("note") or "这一期的数据还没更新。",
                             "hint": "等网站更新后再取。"}, status_code=409)
    return None


@router.post("/api/periods/{period}/acquisition/start")
@user_route
async def api_acq_start(request: Request, period: str):
    """开始取数（按 9 组下载；完成后自动建当期核对副本）。"""
    blocked = _acq_data_block(period)
    if blocked:
        return blocked
    return _acq_spawn(period, "fetch")


@router.post("/api/periods/{period}/acquisition/open")
@user_route
async def api_acq_open(request: Request, period: str):
    """开新一期（票 05）：登记期次、落一个只含 preflight 的空状态——**不 scan、不取数**。

    期次须是六位 `YYYYMM` 且月份是双月（1/3/5/7/9/11，见 `forecast_select.next_periods`）。
    空壳只占位（`preflight` 全 waiting + `opened` 痕迹），进期次列表；真正的取数仍要点
    「开始取数」走开始前检查（票 04 的数据期校验在那时把关）。**不碰** `out/<期次>/`、台账。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return JSONResponse({"error": "期次要六位数字（如 202611）。",
                             "hint": "格式 YYYYMM。"}, status_code=400)
    if int(period[4:6]) not in (1, 3, 5, 7, 9, 11):
        return JSONResponse({"error": f"{period} 不是双月期次。",
                             "hint": "期次是每年的 1 / 3 / 5 / 7 / 9 / 11 月。"}, status_code=400)
    st = acquisition.load(period) or {}
    st.setdefault("preflight", {"browser": "waiting", "esi": "waiting", "incites": "waiting"})
    st["opened"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": current_user(request) or ""}
    acquisition.write_state(period, st)
    return {"ok": True, "period": period, "opened": st["opened"]}


@router.post("/api/periods/{period}/acquisition/retry")
@user_route
async def api_acq_retry(request: Request, period: str):
    """断组重试：只重下指定的组（body: {"group": "esi-papers"}）。"""
    blocked = _acq_data_block(period)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:                                                # noqa: BLE001
        body = {}
    group = str((body or {}).get("group", "")).strip()
    return _acq_spawn(period, "fetch", ["--groups", group] if group else [])


@router.post("/api/periods/{period}/acquisition/copy")
@user_route
async def api_acq_copy(request: Request, period: str):
    """重建当期核对副本（`out/_acquisition/<期次>/监测表.xlsx`）；主台账不碰。"""
    return _acq_spawn(period, "copy")


@router.post("/api/periods/{period}/acquisition/merge")
@user_route
async def api_acq_merge(request: Request, period: str):
    """把已核对副本并入主台账（写前备份 + 写后五查）。

    并入是**全系统唯一会改台账的动作**，守卫用**数据条件**、不靠界面在哪个视图（2026-10-16 票 02）：
    副本状态不是「待核对」就直接 409 说清原因（已并入 → "无需再并"），不再起一个注定被拒的任务。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    st = acquisition.load(period) or {}
    copy_state = (st.get("copy") or {}).get("state")
    if copy_state != "review":
        if copy_state == "merged":
            merged_at = (st.get("copy") or {}).get("merged_at") or "时间未记"
            msg = f"本期已并入台账（{merged_at}），无需再并。"
        else:
            msg = "还没有本期核对副本——先在下载数据台下载并核对，再并入。"
        return JSONResponse({"error": msg, "state": copy_state}, status_code=409)
    return _acq_spawn(period, "merge", ["--by", current_user(request) or ""])


@router.post("/api/periods/{period}/acquisition/preflight")
@user_route
async def api_acq_preflight(request: Request, period: str):
    """开始前检查：取数专用浏览器是否开着、两家网站是否已登录。同步跑（几秒）。"""
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    r = subprocess.run(  # noqa: S603 — 同上
        [str(config.PYTHON), str(_acq_acquire_py()), "preflight", period],
        cwd=str(config.ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)
    st = acquisition.load(period) or {}
    pf = st.get("preflight") or {}
    return {"ok": r.returncode == 0, "preflight": pf}


@router.post("/api/periods/{period}/acquisition/stop")
@user_route
async def api_acq_stop(request: Request, period: str):
    """停止正在跑的下载数据任务（2026-10-19 晚，ADR-0010「落地补记」；静态稿已过审）。

    语义是**停止（可续）**、不是终止：已下载的文件保留，「继续下载」只补缺的。
    正在跑 → 连子进程一起停掉后落 `failed`（note 前缀「已停止」）；
    本来就是中断的僵尸 → 如实结清（「上次运行中断：…」）；没有在跑的任务 → 409、不写状态。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    st = acquisition.load(period)
    if st is None:
        return _period_missing()
    lv = _acq_op_liveness(period, st)
    if lv is None:
        return JSONResponse({"error": "现在没有在跑的下载任务。",
                             "hint": "要下载请回到取数核验页点「继续下载」。"}, status_code=409)
    stopped = False
    pid = (st.get("op") or {}).get("pid")
    if lv == "alive" and isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        stopped = _acq_kill_tree(pid)
        time.sleep(0.6)                      # 等进程树退干净，免得它再回写一次状态
    st["op"] = {**(st.get("op") or {}), "state": "failed",
                "note": "已停止（人工）——已下载的文件保留，可继续下载补缺的",
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    acquisition.write_state(period, st)
    return {"ok": True, "stopped": stopped, "liveness": lv, "op": st["op"]}


@router.get("/api/periods/{period}/acquisition/datapack")
@user_route
async def api_acq_datapack(request: Request, period: str, source: str = ""):
    """已下载数据打包下载（2026-10-19 馆员需求；rick 定「拆两个包、两个按钮」）。

    `source=esi`    → `数据与复现/ESI数据/<期次>/`（十余 MB）
    `source=incites` → 当期 `incites/<快照>/`（150–300 MB，包里最大头）
    只读打包：不写 out/、不碰台账；zip 落**系统临时目录**、响应结束即删（见 `server/datapack.py`）。
    该来源没下载过 → 404；`source` 非法 → 400。
    """
    if not re.fullmatch(r"\d{6}", period or ""):
        return _period_missing()
    if source not in ("esi", "incites"):
        return JSONResponse({"error": "要下哪一路数据？这个包分两路：ESI 和 InCites。",
                             "hint": "地址上带 ?source=esi 或 ?source=incites。"}, status_code=400)
    st = acquisition.load(period) or {}
    snapshot = (st.get("snapshot")
                or acquisition.resolve_snapshot(period, acquisition.INCITES_ROOT_DEFAULT))
    esi_dir = acquisition.ESI_ROOT_DEFAULT / period
    inc_dir = (acquisition.INCITES_ROOT_DEFAULT / snapshot) if snapshot else None
    if source == "esi":
        if not esi_dir.is_dir():
            return JSONResponse({"error": "这一期还没有下载过 ESI 数据。",
                                 "hint": "先在取数核验里下载好，再来打包。"}, status_code=404)
    elif not (inc_dir and inc_dir.is_dir()):
        return JSONResponse({"error": "这一期还没有下载过 InCites 数据。",
                             "hint": "先在取数核验里下载好，再来打包。"}, status_code=404)
    totals = st.get("totals") or {}
    readme = datapack.build_readme(period=period, snapshot=snapshot,
                                   verified=totals.get("verified"),
                                   expected=totals.get("expected"),
                                   esi_dir=esi_dir if source == "esi" else None,
                                   incites_dir=inc_dir if source == "incites" else None)
    import os
    import tempfile
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"wenheng-{source}-data-{period}-{stamp}.zip"   # ASCII 包名（个别浏览器中文名乱码）
    tmp = pathlib.Path(tempfile.gettempdir()) / f".wenheng-datapack-{source}-{period}-{os.getpid()}-{stamp}"
    try:
        await run_in_threadpool(datapack.pack, tmp, period=period,
                                esi_dir=esi_dir if source == "esi" else None,
                                incites_dir=inc_dir if source == "incites" else None,
                                readme=readme)
    except datapack.EmptyPack:
        return JSONResponse({"error": "这一路还没有下载过数据。",
                             "hint": "先在取数核验里下载好，再来打包。"}, status_code=404)
    return FileResponse(tmp, filename=name, media_type="application/zip",
                        background=BackgroundTask(tmp.unlink, missing_ok=True))
