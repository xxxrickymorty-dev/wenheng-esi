# -*- coding: utf-8 -*-
"""periods 分册：期次面 API（20261101 C8 路由分册，从 server/app.py 迁入）。

详情 / 产物 / 签单 / 对勘 / 溯源 / 水线 / 归档 / 大纲 / 图册 / 回滚，以及
`/p/{period}/chart|download` 两条文件口。三步条、签单闸门、操作员可见性等
语义逐字未动；`forecast-choice` 的 GET（读回）注册必须在 `api_route`
（GET+POST，写口）之前——FastAPI 按注册顺序匹配，顺序就是行为。
"""
import json
import pathlib
import re
import time
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               Response)
from starlette.concurrency import run_in_threadpool

from .. import (acquisition, approval, archive, artifacts, collation, config,
                forecasting, jobs, report_preview, visibility)
from ..guards import (_period_missing, admin_route, user_file_route,
                      user_route)
from ..web_common import (_job_missing, _operator_download_guard,
                          _role_of_request, _serve_artifact,
                          _visible_artifacts, current_user, find_ledger,
                          period_cards, resolve_period_dir)
from .acquisition import _acq_opened, _acq_touched
from esi_v1.data import display_name  # 学科名中文化（契约 #22）
from src import chart_data  # 图册 ECharts 同源数据（画了什么导什么；2026-10-28 前端全量 ECharts 化）
from src import forecast_choice  # 预测选模的唯一 implementation（读写/快照/留痕）
from src import parse_ledger  # 成品隔离/回滚的唯一口径（FINAL_PRODUCTS / SUPERSEDED_DIR）
from src import period as period_mod  # 期次口径唯一来源（ADR-0001：新工作区 API 也用它）
from src import period_facts  # 期次事实：目录/盘点/并入/产物/顺延的唯一 module
from src import state_store  # 系统状态库：/api/status 报「能不能写」；写失败话术（ADR-0012）
from src import ledger as ledger_mod  # 动态监测表（母本）路径唯一口径（2026-10-13：input/ 只放母本）

router = APIRouter()


def _period_label(period: str) -> str:
    """期次文案走 src/period.py（口径唯一来源）；算不出总期号时退回期次名，不编假期号。"""
    try:
        _idx, total = period_mod.issue_of(period)
        return f"第 {total} 期 · {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        return period


def _period_has_data(period: str) -> bool:
    """「期次认得出」的宽松口径：取数状态或当期核对副本已存在（还没出稿也算）。

    与 /api/periods 的补录、单期详情的宽松判定同一口径——取数台接手的期次，
    它的空产物 / 空回滚列表要回 200 空数组，而不是 404（404 会在页面控制台报错）。
    """
    m = re.match(r"^(\d{6})", period or "")
    if not m:
        return False
    pid = m.group(1)
    acq = acquisition.load(pid)
    return period_facts.has_data(period, out_root=config.OUT_DIR, acquisition=acq,
                                 copy_exists=acquisition.copy_path(pid).exists())


def _acquisition_only_periods(known: set[str]) -> list[dict]:
    """还没出稿、但取数已经有动静的期次：有取数状态，或当期核对副本已就位。

    取数台接手「未出稿的当期」——这些期次不在 period_cards（那靠 red_slots.json），
    列表里单独补进来（状态按「未签发」显示，出稿后由 period_cards 接管）。
    ⚠️ 「只是点过一次重新检查」的期次不算（那种状态里连文件都没有）：只在 `started`
    （确实取到过文件）或有核对副本时才进列表——否则列表会多出一个点进去就 404 的空期次。
    """
    extra = {p for p in acquisition.periods() if _acq_touched(p) or _acq_opened(p)}
    acq_root = config.OUT_DIR / "_acquisition"
    if acq_root.is_dir():
        for d in acq_root.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{6}", d.name) \
                    and acquisition.copy_path(d.name).exists():
                extra.add(d.name)
    return [{"period": p, "label": _period_label(p), "signed": False,
             "status": "unsigned", "generated": False,
             "url": "/p/" + urllib.parse.quote(p)}
            for p in sorted(extra - known, reverse=True)]


@router.get("/api/periods")
@user_route
async def api_periods(request: Request):
    """期次列表（新工作区系统 /app 的数据源）——与首屏印记链同源（period_cards）。

    期次文案走 src/period.py（口径唯一来源）；带后缀目录（如 202605_复现）算不出
    总期号时退回目录名，不编假期号。另补「未出稿但取数在途」的期次（见上）。
    """
    out = []
    seen = set()
    for c in period_cards():
        out.append({"period": c["period"], "label": _period_label(c["period"]),
                    "signed": c["status"] == "signed", "status": c["status"],
                    "generated": True, "url": c["url"]})
        seen.add(c["period"])
    out.extend(_acquisition_only_periods(seen))
    out.sort(key=lambda item: item["period"], reverse=True)
    return {"periods": out}


@router.get("/api/periods/{period}")
@user_route
async def api_period_detail(request: Request, period: str):
    """单期详情：三步条＝①取数 ②核对并并入 ③生成（ADR-0004）。

    未出稿但取数已有动静的期次（有取数状态、或当期核对副本已就位）也返回详情——
    「先取数、后生成」的工作流需要它们在台面上；三步的判定不出数字。
    """
    m = re.match(r"^(\d{6})", period or "")
    pid = m.group(1) if m else period
    acq = acquisition.load(pid)
    has_input = acquisition.copy_path(pid).exists()
    f = period_facts.facts(period, out_root=config.OUT_DIR, acquisition=acq,
                           copy_exists=has_input)
    if not f.has_data:
        return _period_missing()
    d = f.dir
    try:
        no, total = period_mod.issue_of(period)
        label = f"第 {total} 期 \u00b7 {period_mod.label(period)}"
    except (period_mod.PeriodUndetectable, period_mod.PeriodBeforeAnchor):
        no, total, label = None, None, period
    window = ""
    if d is not None:
        window = artifacts.read_facts(d).get("coverage_window", "")
    totals = (acq or {}).get("totals") or {}
    verified = totals.get("verified") if isinstance(totals.get("verified"), int) else None
    expected = totals.get("expected") if isinstance(totals.get("expected"), int) else None
    copy_state = ((acq or {}).get("copy") or {}).get("state") or "none"
    steps = {"fetch": f.acquire_ok, "merge": f.merge_ok, "generate": f.generate_ok}
    last = next(iter(jobs.list_jobs(limit=30, period=pid)), None)
    return {
        "period": pid, "label": label, "no": no, "total": total,
        "window": window, "palette": config.PALETTE, "steps": steps,
        "task": f.as_home(),
        "acquisition": {"started": acq is not None, "verified": verified,
                        "expected": expected, "copy": copy_state},
        "lastJob": {"id": last["id"], "status": last["status"],
                    "created_at": last.get("created_at")} if last else None,
    }


@router.get("/api/periods/{period}/artifacts")
@user_route
async def api_period_artifacts(request: Request, period: str):
    """按期次列运行产物；操作员看不到红件三件与运行日志（2026-10-11 角色分级）。"""
    d = resolve_period_dir(period)
    if d is None:
        if not _period_has_data(period):
            return _period_missing()
        return {"period": period, "artifacts": []}      # 还没出稿：产物为空，如实说
    return {"period": d.name,
            "artifacts": _visible_artifacts(jobs.collect_period_artifacts(d.name),
                                            _role_of_request(request))}


@router.get("/api/periods/{period}/download/{key}")
@user_route
async def api_period_download(request: Request, period: str, key: str):
    """期次产物下载；操作员只读，红件/日志包类键仅管理员可下载。"""
    guard = _operator_download_guard(_role_of_request(request), key)
    if guard:
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    return _serve_artifact(out_dir=d, key=key, pack_job=None,
                           resolve=lambda: jobs.resolve_period_artifact(d.name, key))


def _paginate(items, limit, offset):
    """统一分页：?limit=&offset= -> {rows, total, limit, offset, has_more}"""
    total = len(items)
    offset = max(0, offset)
    limit = min(max(1, limit), 500)
    rows = items[offset:offset + limit]
    return {"rows": rows, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + limit < total}


@router.post("/api/periods/{period}/sign")
@user_route
async def api_period_sign_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    note = str(body.get("note", ""))
    manual_ack = bool(body.get("known", body.get("manual_ack", False)))
    # 闸门加一道「已填未写入」：填了值但还没重出报告时，签的就是一份不含填值的稿。
    # 拦下来让馆员先重出——审核台会在签单前自动做这件事，这里兜直接调接口的手。
    from .. import workbench                                    # noqa: PLC0415
    pending = [f for f in workbench.build(d).get("fills_list", []) if f.get("state") == "pending"]
    if pending:
        return JSONResponse(
            {"error": f"还有 {len(pending)} 处填写没有写进报告，先重出再签单",
             "hint": "点「保存并重出报告」把填值写进报告，再签单"},
            status_code=409)
    ok, res = approval.sign(d, current_user(request), collation.build(d), note=note, manual_ack=manual_ack)
    if not ok:
        # 写库失败已经是给馆员的整句（含「这次没生效」），别再补「闸门」的提示误导人。
        hint = "" if state_store.is_write_failure_note(res) else "请先解决闸门拒绝的原因"
        return JSONResponse({"error": str(res), "hint": hint}, status_code=409)
    return {"status": approval.status(d, res), "fingerprint": approval.fingerprint(d)}


@router.get("/api/periods/{period}/forecast-choice")
@user_route
async def api_forecast_choice_get(request: Request, period: str):
    """读回请求期次的预测模型选择，仅管理员可读。

    `applied`＝**上次出稿实际用的选择**（当期产物的出稿快照，只读）——前端拿它和已保存的
    `choice` 比值：不一致＝改选还没进报告（2026-10-16 加，rick 要求说清「报告还是旧的」）；
    没有该文件（没出过稿的老期次）→ null，前端不显示提示。

    ⚠️ 这条是 **GET**（2026-09-24 修）：此前被误挂成 `@app.post`，又注册在下面的
    `api_route(methods=["GET","POST"])` 之前——FastAPI 按注册顺序匹配，POST 会被这条
    抢先接走，导致「保存选择」永远只读回、不落盘。改装饰器前先想一遍注册顺序。"""
    if not _forecast_choice_period_is_safe(period):
        return JSONResponse({"error": "期次格式无效"}, status_code=400)
    entry = forecast_choice.read_entry(
        period, choices_dir=config.FORECAST_CHOICES_DIR, out_dir=config.OUT_DIR)
    return {"period": period, "choice": entry["choice"],
            "by": entry["by"], "at": entry["at"],
            "applied": forecast_choice.read_applied(period, out_dir=config.OUT_DIR)}


def _forecast_choice_period_is_safe(period):
    """允许 YYYYMM 及带原样后缀的期次名，不让请求值拼出子路径。"""
    return bool(re.fullmatch(r"\d{6}(?:_[\w-]+)?", period or ""))


#: 兼容别名：形状统计的唯一实现在 `forecast_choice.count`（tests 仍从本 module 取用）。
_count_forecast_choice = forecast_choice.count


@router.api_route("/api/periods/{period}/forecast-choice", methods=["GET", "POST"])
@admin_route
async def api_forecast_choice(request: Request, period: str):
    if request.method == "GET":
        return await api_forecast_choice_get(request, period)
    if not _forecast_choice_period_is_safe(period):
        return JSONResponse({"error": "期次格式无效"}, status_code=400)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "请求必须是合法 JSON 对象"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "请求必须是合法 JSON 对象"}, status_code=400)
    choice = body.get("choice")
    if not isinstance(choice, dict):
        return JSONResponse(
            {"error": "choice 必须是 {路线: {学科: 模型名}}",
             "hint": '例：{"citation": {"物理学": "SARIMA模型"}}'}, status_code=400)
    candidate_subjects = (set(forecasting.page_context().get("subjects") or [])
                          if choice else set())
    ok, error = forecast_choice.validate(choice, subjects=candidate_subjects)
    if not ok:
        return JSONResponse({"error": error}, status_code=400)
    forecast_choice.write_entry(period, choice, by=current_user(request), at=forecast_choice.now(),
                                choices_dir=config.FORECAST_CHOICES_DIR)
    n_subjects, n_routes = forecast_choice.count(choice)
    resp = {"ok": True, "saved": n_subjects,
            "path": f"_forecast_choices/{period}.json"}
    if n_routes is not None:
        resp["saved_routes"] = n_routes
    return resp


@router.post("/api/periods/{period}/revoke")
@user_route
async def api_period_revoke_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    note = str(body.get("note", ""))
    ok, res = approval.revoke(d, current_user(request), note=note)
    if not ok:
        hint = "" if state_store.is_write_failure_note(res) else "请先解决闸门拒绝的原因"
        return JSONResponse({"error": str(res), "hint": hint}, status_code=409)
    return {"status": approval.status(d, res)}


@router.post("/api/periods/{period}/fill")
@admin_route
async def api_period_fill_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    items = body.get("items") or {}
    if not isinstance(items, dict):
        return JSONResponse({"error": "items 必须是 {todo_id: value}", "hint": "例：{'T01_r9c3': '33.87'}"}, status_code=400)
    from .. import workbench                                     # noqa: PLC0415
    n = 0
    try:
        for todo_id, value in items.items():
            if str(todo_id).strip():
                workbench.save_fill(d, str(todo_id), str(value), by=current_user(request))
                n += 1
    except state_store.WRITE_ERRORS as exc:
        # 存储写不进去：回馆员人话（技术原文进日志）。多处以「这次没生效」为准——
        # 已经存进去的那几处仍然有效，如实说出来，别让人以为全白填。
        note = state_store.write_error_note(exc, action="填写")
        if n:
            note += f"（此前已保存的 {n} 处仍然有效）"
        return JSONResponse({"error": note}, status_code=409)
    return {"ok": True, "saved": n}


@router.post("/api/periods/{period}/flag")
@admin_route
async def api_period_flag_json(request: Request, period: str):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    loc = str(body.get("loc", "")).strip()
    if not loc:
        return JSONResponse({"error": "loc 不能为空", "hint": "例：T01/r9c3"}, status_code=400)
    from .. import workbench                                     # noqa: PLC0415
    try:
        r = workbench.toggle_flag(d, loc, by=current_user(request))
    except state_store.WRITE_ERRORS as exc:
        return JSONResponse({"error": state_store.write_error_note(exc, action="标记存疑")},
                            status_code=409)
    return {"ok": True, "loc": r["loc"], "state": r["state"], "n_doubt": r["n_doubt"]}


@router.post("/api/periods/{period}/rebuild")
@admin_route
async def api_period_rebuild_json(request: Request, period: str):
    """填完重出（JSON 版）——与表单版同一套三步。

    ① 先存 body.items 里的填值（可空，用已落盘的）
    ② 旧成品撤到 _superseded/（覆盖前留机器稿，能回滚）
    ③ fill_docx 用已解析宽表重出，不重新解析台账
    转 2-15 秒（重插 96 张图），同步阻塞 —— uvicorn 单 worker 是项目既定约束。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    items = body.get("items") or {}
    if not isinstance(items, dict):
        return JSONResponse({"error": "items 必须是 {todo_id: value}", "hint": "可省略，用已落盘的填值"}, status_code=400)
    import fill_docx                                        # noqa: PLC0415
    import parse_ledger                                     # noqa: PLC0415
    from .. import workbench                                 # noqa: PLC0415
    try:                                                    # ① 先存
        for todo_id, value in items.items():
            if str(todo_id).strip():
                workbench.save_fill(d, str(todo_id), str(value), by=current_user(request))
    except state_store.WRITE_ERRORS as exc:
        # 存不进去就别往下走：重出只会把「没存上的填值」当没有，白跑一遍还撤掉旧成品。
        return JSONResponse({"error": state_store.write_error_note(exc, action="填写")},
                            status_code=409)
    fills = workbench.load_fills(d)
    if not fills:                                           # ② 没内容就不动产物
        return JSONResponse({"error": "还没有填写内容", "hint": "先在工作台填值再重出"}, status_code=409)
    t0 = time.time()
    parse_ledger.quarantine_final_products(d, None)
    try:
        fill_docx.main(ledger_dir=str(d), manual_inputs=fills)  # ③ 重出
    except Exception as e:                                  # noqa: BLE001
        return JSONResponse({"error": f"重出失败：{type(e).__name__}", "hint": str(e)[:200]}, status_code=500)
    n = sum(1 for v in fills.values() if str(v.get("value") or "").strip())
    docx = next((p.name for p in d.glob("报告初稿_*.docx")), "")
    return {"ok": True, "rebuilt": n, "period": d.name, "docx": docx,
            "elapsed": round(time.time() - t0, 1)}


def _discipline_cn(name):
    """学科英文名 → 中文展示名（契约 #22）；未知名字原样返回（不猜、不丢）。"""
    return display_name(name) if isinstance(name, str) else name


def _localize_facts(facts: dict) -> dict:
    """契约 #22：facts 里展示用的学科名就地换中文。

    只动接口响应——磁盘产物 `overview_facts.json` 保持英文，逐格溯源链不断。
    换的是五处展示位（前端据此删掉自己的名字桥）：
    `best_1permille` / `worst_cn_rank` / `top2_not_entered[].discipline`，以及并列组
    `top3_by_top_papers[][0]`、`top3_groups[][1][]`（名字在固定位置，只能就地换）；
    顺带 `top2_prox_change[][0]`（同类展示位，避免下一个用它的页面再踩英文）。
    """
    for key in ("best_1permille", "worst_cn_rank"):
        item = facts.get(key)
        if isinstance(item, dict) and "discipline" in item:
            item["discipline"] = _discipline_cn(item["discipline"])
    for key in ("top2_not_entered", "not_entered"):
        for item in facts.get(key) or []:
            if isinstance(item, dict) and "discipline" in item:
                item["discipline"] = _discipline_cn(item["discipline"])
    for key in ("top3_by_top_papers", "top2_prox_change"):
        rows = facts.get(key)
        if isinstance(rows, list):
            facts[key] = [[_discipline_cn(r[0]), *r[1:]]
                          if isinstance(r, (list, tuple)) and r else r for r in rows]
    groups = facts.get("top3_groups")
    if isinstance(groups, list):
        facts["top3_groups"] = [
            [r[0], [_discipline_cn(d) for d in r[1]]]
            if isinstance(r, (list, tuple)) and len(r) >= 2 and isinstance(r[1], (list, tuple))
            else r
            for r in groups]
    return facts


@router.get("/api/periods/{period}/facts")
@user_route
async def api_period_facts(request: Request, period: str):
    """读数带数据：overview_facts.json + meta.json 摘要，仅管理员可读。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    if not (d / "overview_facts.json").exists():
        return JSONResponse({"error": "该期次尚无 overview_facts.json", "hint": "请先跑一次生成流水线"}, status_code=404)
    facts = artifacts.read_facts(d)
    meta = artifacts.read_meta(d)
    facts = _localize_facts(facts)
    # 顶尖论文历期序列（纯序列化 meta；空值＝未来期空列，滤掉）——契约 #19
    trend = {k: v for k, v in (meta.get("top_total_by_period") or {}).items()
             if isinstance(v, (int, float))}
    return {
        "period": meta.get("period_current", ""),
        "period_prev": meta.get("period_prev", ""),
        "facts": facts,
        "trend": trend,
        "assertions": artifacts.assertion_counts(meta),
        "missing": meta.get("missing", []),
    }


@router.get("/api/periods/{period}/water")
@user_route
async def api_period_water(request: Request, period: str):
    """学科水位（只读）：从 matrix.json 的「云大」列取接近度，给首屏水尺。

    `prox`＝被引 ÷ 1% 阈值的百分数点值（100＝刚好到线）；`state`：
    `in`＝已在 ESI 前 1% 榜内、`near`≥80%、`far`<80%。只读产物，不重算口径。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    return {"period": period, **period_facts.water_rows(d / "matrix.json")}


@router.get("/api/periods/{period}/workbench")
@user_route
async def api_period_workbench(request: Request, period: str):
    """工作台全量数据：todo/fills/pending/approval。admin 可读。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    from .. import workbench, approval as _appr               # noqa: PLC0415
    rec = _appr.read(d)
    data = workbench.build(d, approval=rec)
    data["approvalStatus"] = _appr.status(d, rec)
    return data


@router.get("/api/periods/{period}/report-preview")
@user_route
async def api_period_report_preview(request: Request, period: str):
    """审核台用：把这一期的试排报告（docx）拆成可渲染的块 + 在线填空字段。

    只读产物；不重算任何数字。没出稿时 404，让前端给出「去生成」的下一步。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    data = await run_in_threadpool(report_preview.build, d)
    if not data.get("docx"):
        return JSONResponse(
            {"error": "这一期还没有出稿", "hint": "先在生成台生成这一期，再回来审核"},
            status_code=404)
    return data


@router.get("/api/periods/{period}/report-image/{rid}")
@user_route
async def api_period_report_image(request: Request, period: str, rid: str):
    """报告预览里的插图（按 docx 内部 rId 取，只读、不落盘）。"""
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    hit = await run_in_threadpool(report_preview.image, d, rid)
    if hit is None:
        return JSONResponse({"error": "图片不存在"}, status_code=404)
    blob, ctype = hit
    return Response(content=blob, media_type=ctype,
                    headers={"Cache-Control": "no-cache"})


_TRACE_CATS = ("bigtable", "charts", "province", "matrix", "texts")


def _rel_path(p):
    """绝对路径 -> 仓库相对（跨机器可读；API 不回服务器目录结构）。

    转不了（不在仓库内 / 跨平台遗留的 Windows 路径）就只回文件名。
    2026-10-13 实踩：Linux 上读到历史任务记录里的 `C:\\...` 时，`Path.resolve()`
    把它当**相对名**解析，`relative_to(ROOT)` 反而"成功"，绝对路径就漏进了 archive
    响应（e2e「archive 不回绝对路径」在服务器上 FAIL）——带盘符且不在本仓下的一律
    只回文件名。
    """
    s = str(p)
    if pathlib.PureWindowsPath(s).drive and not s.startswith(str(config.ROOT)):
        return s.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        return str(pathlib.Path(s).resolve().relative_to(config.ROOT)).replace("\\", "/")
    except (ValueError, OSError, TypeError):
        return s.replace("\\", "/").rsplit("/", 1)[-1]


def _sanitize_paths(obj, keys):
    """把 dict 里指定键的路径值换成仓库相对形式（原对象不改）。"""
    if not isinstance(obj, dict):
        return obj
    out = dict(obj)
    for k in keys:
        if out.get(k):
            out[k] = _rel_path(out[k])
    if isinstance(out.get("stats"), dict):          # 嵌套的 stats 里也有 input
        out["stats"] = _sanitize_paths(out["stats"], keys)
    return out


@router.get("/api/periods/{period}/archive")
@user_route
async def api_period_archive(request: Request, period: str, job: str = ""):
    """期次运行档案 JSON（契约 §2.2 #18）—— 状态机回放 + 瀑布 + 审计 + 日志包清单。

    与档案页同源（`archive.build`）。**自动挂该期最近一次任务**
    （否则 replay 只能是空链、waterfall 无事件）；`?job=<id>` 可指定某次运行。
    安全：**不回服务器绝对路径**；日志包下载走保留的 `/p/{period}/download/logpack`。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    if job:
        target = jobs.read_job(job)
        if target is None:
            return _job_missing()
    else:
        target = next((j for j in jobs.list_jobs(50)
                       if d.name in (j.get("period"), j.get("out_period"))), None)
    q = urllib.parse.quote(d.name)
    role = _role_of_request(request)
    artifacts = jobs.collect_period_artifacts(d.name)
    if role != "admin":
        artifacts = _visible_artifacts(artifacts, role)
    view = archive.build(d, job=target, artifacts=artifacts)
    view.pop("out_dir", None)                                  # 不回绝对路径
    view.pop("progress_path", None)
    # job/stats/run_log 里还有 input/progress/console 等本机路径：转仓库相对
    _path_keys = ("input", "progress", "console", "run_dir", "out_dir")
    view["job"] = _sanitize_paths(view.get("job"), _path_keys)
    view["stats"] = _sanitize_paths(view.get("stats"), _path_keys)
    view["run_log"] = _sanitize_paths(view.get("run_log"), _path_keys)
    view["download_base"] = f"/p/{q}"
    # 操作员只读证据面，但红件/运行日志/日志包仍按 2026-10-11 政策只给管理员。
    # 不给链接，避免页面上出现一点就 403 的按钮；决定走 visibility。
    view["logpack_url"] = (f"/p/{q}/download/{view['logpack']['key']}"
                           if visibility.allowed(role, "logpack", "download") else "")
    return view


@router.get("/api/periods/{period}/trace")
@user_route
async def api_period_trace(request: Request, period: str, cat: str = "bigtable",
                           limit: int = 60, offset: int = 0):
    """逐格溯源 JSON。现场真读台账（与老站同源）。

    cat 选类别：bigtable/charts/province/matrix/texts；
    limit/offset 分页（大件不一次性塞满，契约 §3）。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    if cat not in _TRACE_CATS:
        cat = "bigtable"
    ledger = find_ledger()
    if ledger is None:
        empty = {k: 0 for k in _TRACE_CATS}
        return {"period": d.name, "ledger": "", "ledger_ok": False,
                "ledger_error": f"本地未找到动态监测表 input/{ledger_mod.LEDGER_NAME}",
                "n": 0, "cat": cat, "counts": empty,
                "rows": [], "total": 0, "limit": limit, "offset": offset,
                "has_more": False, "cols": [], "discs": [], "review": {}}
    from .. import workbench                                  # noqa: PLC0415
    data = workbench.trace(d, ledger, prev=None)
    counts = {k: len(data.get(k) or []) for k in _TRACE_CATS}
    page = _paginate(data.get(cat) or [], limit, offset)
    return {
        "period": d.name,
        "ledger": pathlib.Path(ledger).name,
        "ledger_ok": True,
        "n": data.get("n", 0),
        "cat": cat,
        "counts": counts,
        "rows": page["rows"],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
        "has_more": page["has_more"],
        "cols": data.get("cols", []),
        "discs": data.get("discs", []),
        "review": workbench.load_review(d),
    }


@router.get("/api/periods/{period}/redslots")
@user_route
async def api_period_redslots(request: Request, period: str,
                              limit: int = 50, offset: int = 0):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    rows = []
    for s in artifacts.read_slots(d):
        loc = str(s.get("location", ""))
        src = str(s.get("source", ""))
        group = loc.split("/")[0] if "/" in loc else loc
        if loc.startswith("T01/r"):
            group = "大表数值"
        elif loc.startswith("T0") or loc.startswith("T1"):
            group = loc.split("/")[0]
        rows.append({"group": group, "label": loc,
                     "old": artifacts.slot_text(s, "old"),
                     "new": artifacts.slot_text(s, "new"),
                     "src": src, "kind": artifacts.slot_kind(s)})
    page = _paginate(rows, limit, offset)
    page["count"] = page["total"]
    return page


@router.get("/api/periods/{period}/outline")
@user_route
async def api_period_outline(request: Request, period: str):
    """②选材 · 报告大纲（**只读**，最省版）。

    只由产物推导：章节 + 每节的就绪态 / 数据来源 / 槽位数（按 `red_slots.json` 的 location 分组）。
    **不写任何文件、不改出稿**——这一屏只记"本轮办哪些节"，出稿一律全出、母版不动。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    locs = [str(s.get("location", "")) for s in artifacts.read_slots(d)]

    def has(name: str) -> bool:
        return (d / name).exists()

    def n_tables(*tids: str) -> int:
        pfx = tuple(f"{t}/" for t in tids)
        return sum(1 for x in locs if x.startswith(pfx))

    def n_body(*keys: str) -> int:
        want = {"正文/" + k for k in keys}
        return sum(1 for x in locs if x in want)

    pred = [f"T{i:02d}" for i in range(3, 19)]          # T03–T18：预测章 16 张学科表
    # 正文槽位按章归位（图/表也算，唯「图片行距」是版式、不归章）
    s1 = n_body("p1", "p2", "p3", "p4", "1%接近度图（新）", "1‰潜力图", "排名情况图（第4期格式·带数据表）")
    s2 = n_tables("T01", "T20") + n_body(
        "trend", "situation_head", "situation", "table2_title", "发展趋势图（第4期格式·带数据表）")
    s3 = n_tables(*pred, "T17") + n_body("forecast_p1", "forecast_p2")
    s4 = n_tables("T19") + n_body("province_p")
    s5 = n_body("top_section", "顶尖论文·学科分布", "顶尖论文·年代分布",
                "学院贡献度饼图（被引频次）", "学院贡献度饼图（发文量）",
                "学院顶尖论文发文量与被引频次统计表")
    # 附录《我校顶尖论文清单》：由馆员清单另填（不进红件槽位）——看清单在不在
    inv = []
    for base in (d.parent / "_acquisition" / d.name, config.ROOT / "数据与复现"):
        try:
            inv += [p.name for p in base.glob(f"*{d.name}*清单*")]
        except OSError:
            pass
    return {
        "period": d.name,
        # 版式类槽位（如「图片行距」）不归章——单列出来，别让各节相加对不上总数
        "slotsTotal": len(locs),
        "slotsUnassigned": len(locs) - (s1 + s2 + s3 + s4 + s5),
        "sections": [
            {"id": "s0", "label": "封面 · 名词解释", "ready": True,
             "source": "母版固定（名词解释不填）", "slots": 0},
            {"id": "s1", "label": "一 概述", "ready": has("overview_facts.json"),
             "source": "overview_facts.json · sentences.py 句骨架", "slots": s1},
            {"id": "s2", "label": "二 我校学科发展情况", "ready": has("table2.csv"),
             "source": "table2.csv · matrix.json", "slots": s2,
             "subs": [{"id": "s2.t1", "label": "大表数值", "ready": has("table2.csv"),
                       "slots": n_tables("T01")},
                      {"id": "s2.t20", "label": "学科×高校矩阵", "ready": has("matrix.json"),
                       "slots": n_tables("T20")},
                      {"id": "s2.trend", "label": "发展趋势 · 态势统计", "ready": has("matrix.json"),
                       "slots": n_body("trend", "situation_head", "situation")}]},
            {"id": "s3", "label": "三 我校潜力学科趋势预测", "ready": has("forecast_charts.json"),
             "source": "forecast_charts.json · 预测选模", "slots": s3,
             "subs": [{"id": "s3.tabs", "label": "学科表 ×16", "ready": has("forecast_charts.json"),
                       "slots": n_tables(*pred, "T17")},
                      {"id": "s3.charts", "label": "模型预测图 ×4 · 说明句", "ready": has("forecast_charts.json"),
                       "slots": n_body("forecast_p1", "forecast_p2")}]},
            {"id": "s4", "label": "四 云南省主要高校学科发展基本情况", "ready": has("province.json"),
             "source": "college_stats.json · province.json", "slots": s4},
            {"id": "s5", "label": "五 我校顶尖论文清单（附录）", "ready": bool(inv),
             "source": "馆员清单（本科目另填）", "slots": s5},
        ],
    }


@router.get("/api/periods/{period}/collation")
@user_route
async def api_period_collation(request: Request, period: str,
                               limit: int = 50, offset: int = 0,
                               full: bool = False):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    data = collation.build(d)
    sections = [{"id": s["id"], "name": s["name"], "note": s.get("note", ""),
                 "count": s.get("count", 0), "text": s.get("text", 0),
                 "cell": s.get("cell", 0), "chart": s.get("chart", 0),
                 "manual": s.get("manual", 0),
                 "slots": s.get("slots", [])}
                for s in data.get("sections", [])]
    all_slots = []
    for s in data.get("sections", []):
        for it in s.get("slots", []):
            all_slots.append({"section": s["id"], **it})
    if full:
        return {"sections": sections, "rows": all_slots,
                "total": len(all_slots), "period": data.get("period", ""),
                "assertions": data.get("assertions", {})}
    page = _paginate(all_slots, limit, offset)
    page["sections"] = [{k: v for k, v in s.items() if k != "slots"} for s in sections]
    page["period"] = data.get("period", "")
    page["assertions"] = data.get("assertions", {})
    return page


@router.get("/api/periods/{period}/charts-data")
@user_route
async def api_period_charts_data(request: Request, period: str):      # noqa: ARG001
    """图册 ECharts 交互图的数据（契约 #38）：现读台账宽表，与报告 PNG 同一批数字。

    「画了什么导什么」——窗口/交集/×100/差分都照抄画图函数口径，前端零换算。
    台账没并入的期次回 404：前端拿到 404/无数据一律回退 PNG 原图。

    另附 `report_map`（2026-10-28 rick 裁决：审核台正文全换 ECharts）：
    docx 插图 rId → 图册图位（组, 文件名），逐字节比对得出——
    前端据此把正文里的图换成同源交互图；对不上就保留原图。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    try:
        payload = await run_in_threadpool(chart_data.build, d)
    except FileNotFoundError:
        return _period_missing()
    try:
        payload["report_map"] = await run_in_threadpool(report_preview.chart_map, d)
    except Exception:                     # noqa: BLE001  映射缺席不该拖垮图册数据本身
        payload["report_map"] = {}
    return payload


def _forecast_chart_labels(period_dir):
    """预测图的读得懂的名字：`forecast_3_cites.png` → 「免疫学 · 被引频次与阈值（预测图）」。

    源＝本期 `forecast_charts.json`（出图时写定）；缺文件/字段就留空，不猜（前端回落文件名）。
    2026-10-16 加：未进 1% 的全部学科都出图后，图册里再显示裸文件名就太难认了。
    """
    mp = pathlib.Path(period_dir) / "forecast_charts.json"
    try:
        charts = json.loads(mp.read_text(encoding="utf-8")).get("charts", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    labels = {}
    for c in charts:
        if not isinstance(c, dict):
            continue
        png, subject, kind = c.get("png"), c.get("subject"), c.get("kind")
        if isinstance(png, str) and isinstance(subject, str) and kind in ("cites", "rank"):
            metric = "被引频次与阈值" if kind == "cites" else "国内排名与机构数"
            labels[png] = f"{subject} · {metric}（预测图）"
    return labels


@router.get("/api/periods/{period}/charts")
@user_route
async def api_period_charts_json(request: Request, period: str,
                                 limit: int = 50, offset: int = 0):
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    q = urllib.parse.quote(d.name)
    labels = _forecast_chart_labels(d)
    items = []
    for it in jobs.list_charts(d):
        items.append({"name": it["name"], "group": it["group"],
                      "label": labels.get(it["name"], ""),
                      "url": f"/p/{q}/chart/" + urllib.parse.quote(it["rel"])})
    return _paginate(items, limit, offset)


# ---------------- 回滚到上一版（票 07） ----------------

def _rollback_dir(period: str):
    """回滚只认两件事：期次名合法 + 期次目录里有 _superseded/。

    与 resolve_period_dir 不同：**允许当前没有成品**——重跑失败之后回来回滚，正是主场景。
    """
    if not jobs.PERIOD_DIR_RE.match(period or ""):
        return None
    d = config.OUT_DIR / period
    if d.is_dir() and (d / parse_ledger.SUPERSEDED_DIR).is_dir():
        return d
    return None


def _rollback_points(out_dir: pathlib.Path):
    """列回滚点（新→旧）：只列真带成品的留档目录（下划线开头的是标记文件）。"""
    sup = out_dir / parse_ledger.SUPERSEDED_DIR
    points = []
    for d in sorted((p for p in sup.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        files = sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.startswith("_"))
        if files:
            points.append({"id": d.name, "files": files})
    return points


@router.get("/api/periods/{period}/rollback-points")
@admin_route
async def api_rollback_points(request: Request, period: str):
    out_dir = _rollback_dir(period)
    if not out_dir:
        if not _period_has_data(period):
            return JSONResponse({"error": "这一期没有可回滚的留档"}, status_code=404)
        return {"period": period, "points": []}         # 还没出稿：没有留档可回滚
    return {"period": period, "points": _rollback_points(out_dir)}


@router.post("/api/periods/{period}/rollback")
@admin_route
async def api_rollback(request: Request, period: str):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    point = str((body or {}).get("point") or "")
    out_dir = _rollback_dir(period)
    if not out_dir:
        return JSONResponse({"error": "这一期没有可回滚的留档"}, status_code=404)
    busy = jobs.active_job()
    if busy:
        return JSONResponse({"error": f"已有任务运行中（{busy['period']}），回滚会跟它打架，请稍候"},
                            status_code=409)
    points = _rollback_points(out_dir)
    if not points:
        return JSONResponse({"error": "没有可回滚的版本（每次重跑/重出都会把旧版留档）"}, status_code=404)
    target = next((p for p in points if p["id"] == point), None) if point else points[0]
    if not target:
        return JSONResponse({"error": "指定的回滚点不存在"}, status_code=404)
    src = out_dir / parse_ledger.SUPERSEDED_DIR / target["id"]
    # 先把当前成品撤进新的留档目录——让「回滚」本身也能再回滚
    quarantined = parse_ledger.quarantine_final_products(out_dir)
    restored = []
    for name in target["files"]:
        p = src / name
        if p.is_file():
            p.replace(out_dir / name)
            restored.append(name)
    try:
        (src / "_已回滚.txt").write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}：这一版成品已回滚到 {period} 期目录；"
            f"回滚前的成品另存了新留档目录。\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return {"ok": True, "period": period, "point": target["id"],
            "restored": restored, "pre_rollback_quarantined": quarantined}


# ---------------- 文件口（老站保留的图表 / 产物下载） ----------------

@router.get("/p/{period}/chart/{rel:path}")
@user_file_route
async def period_chart(request: Request, period: str, rel: str):
    """图表原图（只读）。`rel` 是 `red_slots.json` 里 `source` 去掉 `charts/` 的部分。

    越界请求由 `jobs.resolve_chart` 挡住——这条路由直接服务磁盘文件，
    少一道检查就能读到 `server/.env`，别在这里省事。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    p = jobs.resolve_chart(d, rel)
    if not p:
        return JSONResponse({"error": "图表不存在"}, status_code=404)
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.get("/p/{period}/download/{key}")
@user_file_route
async def period_download(request: Request, period: str, key: str):
    guard = _operator_download_guard(_role_of_request(request), key)
    if guard:
        return guard
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    return _serve_artifact(out_dir=d, key=key, pack_job=None,
                           resolve=lambda: jobs.resolve_period_artifact(period, key))
