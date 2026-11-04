# -*- coding: utf-8 -*-
"""dialog 分册：对话前门、问文衡/问数、AI 能力开关与模型清单（20261101 C8 路由分册）。

对话（#33/#35/#36/#37）、qa/review 薄适配（#9/#27）、能力开关（#28/#29）、
调用留痕（#30）、模型管理（2026-10-29）、AI 问数（SQLite + 受控 NL2SQL，
2026-10-25）。会话库路径是装配壳的单例（`SESSION_DB_PATH`）：生产由 lifespan
装配，测试 monkeypatch `app_module.SESSION_DB_PATH` 注入 tmp——处理函数一律经
`web_common.session_db_path()` 在请求时现取（补丁锚点，见 web_common 模块 docstring）。
"""
import asyncio
import json
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .. import approval, config
from ..guards import _period_missing, admin_route, user_route
from ..web_common import (current_user, resolve_period_dir, session_db_path)
from src import session_store  # 会话库（票 11）——对话前门会话的服务端持久化

router = APIRouter()


def _answer_response(ans):
    """Answer → HTTP（#9/#27 共用）：无数据 404、权限 403、关闭 409、其余原样 JSON。"""
    if ans.mode == "unavailable":
        return JSONResponse({"error": ans.notice,
                             "hint": "请先跑一次生成流水线"}, status_code=404)
    if ans.mode == "denied":
        return JSONResponse({"error": ans.notice}, status_code=403)
    if ans.mode == "closed":
        return JSONResponse({"error": ans.notice}, status_code=409)
    return ans.as_dict()


@router.post("/api/analyze")
@user_route
async def api_analyze(request: Request):
    """问文衡（qa 能力）**薄适配**（SPEC §4 步骤 2）：调用方只认 Answer 字段面，
    不知道盾、回落、工具、留痕、开关任何一件。

    请求 `{period, question}`（旧版 `scope` 遗留字段被忽略——问句匹配在模块内）；
    响应＝`Answer.as_dict()`（`mode/backend/text/rule_text/notice/sources/shield/record_id`）。
    该期无产物 → 404（前端按「尚未出稿」处理）；能力被管理员关闭 → 409。
    """
    body = await request.json()
    period = str(body.get("period", "")).strip()
    question = str(body.get("question", "")).strip()
    d = resolve_period_dir(period) if period else None
    if d is None:
        return _period_missing()
    import ai                                                     # noqa: PLC0415
    ans = await run_in_threadpool(ai.run, "qa", period,
                                  payload={"question": question},
                                  actor=config.role_of(current_user(request) or ""))
    return _answer_response(ans)


@router.post("/api/periods/{period}/review-advice")
@admin_route
async def api_period_review_advice(request: Request, period: str):
    """复核参谋（review 能力；契约 #27）**薄适配**：调用方只认 Answer 字段面。

    只读红件清单/校验结果给核对建议（来源＝红件条目或校验记录）；
    **不代签、不改稿**——采纳/忽略只是界面指引，由前端自己存。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    import ai                                                     # noqa: PLC0415
    ans = await run_in_threadpool(ai.run, "review", period,
                                  actor=config.role_of(current_user(request) or ""))
    return _answer_response(ans)


@router.get("/api/ai/capabilities")
@user_route
async def api_ai_capabilities(request: Request):
    """能力开关表（契约 #28）：分析台「问文衡」的开关读它；纯读配置，无副作用。"""
    import ai                                                     # noqa: PLC0415
    rows = [c.as_dict() for c in
            ai.capabilities(config.role_of(current_user(request) or ""))]
    return {"capabilities": rows}


@router.get("/api/periods/{period}/ai-calls")
@user_route
async def api_period_ai_calls(request: Request, period: str, limit: int = 100):
    """问答与模型调用记录（契约 #30；票 06 块）：只读 `out/<期次>/ai_calls.jsonl`。

    记录面照留痕纪律：只返回摘要（问题占位面、模式、后端、回落原因、盾计数、
    工具条数、耗时），**不返回回答正文与提示词**；坏行跳过，不猜。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    path = d / "ai_calls.jsonl"
    calls = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") != "call":
                continue
            calls.append({
                "record_id": r.get("record_id") or "",
                "ts": r.get("ts") or "",
                "capability": r.get("capability") or "",
                "mode": r.get("mode") or "",
                "backend": r.get("backend") or "",
                "fallback": r.get("fallback"),
                "shield": r.get("shield") or {"checked": 0, "passed": 0},
                "n_tools": len(r.get("tools") or []),
                "question": r.get("question") or "",
                "label": r.get("label") or "",
                "elapsed_ms": int(r.get("elapsed_ms") or 0),
            })
    limit = max(1, min(int(limit or 100), 500))
    calls = calls[-limit:][::-1]                                  # 新 → 旧
    n_fb = sum(1 for c in calls if c["fallback"])
    stats = {
        "n": len(calls),
        "model": sum(1 for c in calls if c["mode"] == "model"),
        "fallback": n_fb,
        "avg_sec": round(sum(c["elapsed_ms"] for c in calls) / len(calls) / 1000, 1) if calls else 0,
        "last_ts": calls[0]["ts"] if calls else "",
    }
    return {"period": period, "calls": calls, "stats": stats}


@router.get("/api/ai/call-stats")
@admin_route
async def api_ai_call_stats(request: Request):               # noqa: ARG001
    """模型调用统计口（契约 #40，2026-11-04）：聚合全部留痕记录。

    数据面＝`ai._record.aggregate_calls`：扫 `out/<期次>/ai_calls.jsonl`
    与 `out/_ai/ai_calls.jsonl`（kind=call 才算）。modes 口径——
    `model`＝模型轮成功、`failed`＝模型轮回落（原因码进 labels[].fallback）、
    `rule`＝其余（纯规则轮 / 关闭态）。label 缺失按 capability 归组。
    无任何记录 → 全零结构，不报错。
    """
    from ai import _record                                    # noqa: PLC0415
    return await run_in_threadpool(_record.aggregate_calls)


@router.post("/api/ai/switch")
@admin_route
async def api_ai_switch(request: Request):
    """能力开关唯一写口（契约 #29）：管理员一键关闭「问文衡」；数字与报告不受影响。"""
    body = await request.json()
    capability = str(body.get("capability") or "").strip()
    enabled = bool(body.get("enabled"))
    import ai                                                     # noqa: PLC0415
    try:
        await run_in_threadpool(ai.set_switch, capability, enabled,
                                actor=config.role_of(current_user(request) or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except PermissionError as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    return {"ok": True, "capability": capability, "enabled": enabled}


# ---------------------------------------------------------------- 模型清单（2026-10-29；2026-11-04 v2：供应商＋模型目录）
# 「对话框能切模型、设置里能配模型」的后端：清单落 `out/_ai/models.json`（不入库），
# 当前项即刻生效（`ai._config.cloud_config` 现读）。key 只出掩码，写口仅 admin。
@router.get("/api/models")
@user_route
async def api_models(request: Request):                          # noqa: ARG001
    """供应商清单（含各自模型目录）+ 当前用的是哪条哪个型号
    （读口对已登录用户开放，key 只给掩码）。"""
    from ai import _models                                        # noqa: PLC0415
    return await run_in_threadpool(_models.public)


@router.post("/api/models/save")
@admin_route
async def api_models_save(request: Request):
    """新增/改一条供应商（key 留空＝沿用旧 key；models＝整份模型目录）。"""
    body = await request.json()
    from ai import _models                                        # noqa: PLC0415
    actor = config.role_of(current_user(request) or "")
    try:
        row = await run_in_threadpool(_models.upsert, body, actor=actor)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except OSError as e:
        return JSONResponse({"error": f"写不进服务器上的配置文件：{e}"}, status_code=500)
    return {"ok": True, "provider": row, "models": (await run_in_threadpool(_models.public))}


@router.post("/api/models/remove")
@admin_route
async def api_models_remove(request: Request):
    body = await request.json()
    from ai import _models                                        # noqa: PLC0415
    actor = config.role_of(current_user(request) or "")
    try:
        await run_in_threadpool(_models.remove, str(body.get("id") or ""), actor=actor)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "models": await run_in_threadpool(_models.public)}


@router.post("/api/models/active")
@admin_route
async def api_models_active(request: Request):
    """切当前模型（`{provider, model}`；provider 空串＝用服务器 `.env` 的部署配置，
    model 省略＝该供应商目录里第一个）；下一句话即生效。"""
    body = await request.json()
    from ai import _models                                        # noqa: PLC0415
    actor = config.role_of(current_user(request) or "")
    try:
        await run_in_threadpool(_models.set_active, str(body.get("provider") or ""),
                                str(body.get("model") or ""), actor=actor)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "models": await run_in_threadpool(_models.public)}


@router.post("/api/models/test")
@admin_route
async def api_models_test(request: Request):
    """探活：地址 + key（＋型号在不在网关上）。`id` 给了就测清单里那条供应商
    （用已存的 key 与 headers）；`headers`（票 4）＝表单/条目的自定义头，透传给探活
    ——测的就是要真发的那一套头。"""
    body = await request.json()
    from ai import _models                                        # noqa: PLC0415
    pid = str(body.get("id") or "")
    base_url = str(body.get("base_url") or "")
    key = str(body.get("key") or "")
    model = str(body.get("model") or "")
    headers = body.get("headers") if isinstance(body.get("headers"), dict) else None
    if pid:
        row = next((p for p in _models.read()["providers"] if p["id"] == pid), None)
        if row is None:
            return JSONResponse({"error": "没有这条供应商"}, status_code=404)
        base_url = row["base_url"]
        key = key or row["key"]
        if headers is None:
            headers = row.get("headers") or None
    try:
        result = await run_in_threadpool(
            _models.probe, base_url=base_url, key=key, model=model,
            headers=headers, timeout=15.0)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return result


@router.post("/api/models/list-remote")
@admin_route
async def api_models_list_remote(request: Request):
    """「获取可用模型」（图二按钮）：拉网关的型号清单给界面挑。
    `id` 给了就用清单里那条供应商的地址与已存 key；否则用表单这组。"""
    body = await request.json()
    from ai import _models                                        # noqa: PLC0415
    pid = str(body.get("id") or "")
    base_url = str(body.get("base_url") or "")
    key = str(body.get("key") or "")
    headers = body.get("headers") if isinstance(body.get("headers"), dict) else None
    if pid:
        row = next((p for p in _models.read()["providers"] if p["id"] == pid), None)
        if row is None:
            return JSONResponse({"error": "没有这条供应商"}, status_code=404)
        base_url = row["base_url"]
        key = key or row["key"]
        if headers is None:
            headers = row.get("headers") or None
    try:
        return await run_in_threadpool(
            _models.fetch_models, base_url=base_url, key=key,
            headers=headers, timeout=15.0)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/dialog/turn")
@user_route
async def api_dialog_turn(request: Request):
    """对话前门一轮（契约 #33，票 01–07）：一句话 → 路由（两意图）+ 应答 + 槽位 + 盘点。

    请求 `{text, slots:{period,intent}, history, session}`（slots/history/session 可省；
    期次形状非法按未设处理，不猜）。
    应答＝Answer 字段面 + `kind`（`report/query/proceed/unclear`/空：票 07 路由）
    + `slots`（本轮解析到的才覆盖，其余不变）+ 盘点三件：`verdict`（unpublished/missing/ready/空）、
    `inventory`（四件清单）、`actions`（改做/去取数台/去核对/覆盖重出/先等等）
    + `run`（出稿意图）+ `answer`（查数据：qa 能力的 Answer；其余为 null）
    + `session_id`（票 11：本回合的会话 id——续聊把它回传）。
    **会话（票 11）**：带 `session` → 校验归属、历史从会话库读（截断口径与现状一致）、
    回合追加进库；无 → 建新会话；他人会话 403、不存在 404。
    **两意图**：写报告与现有链路不变；查数据由**本路由**按意图调 `ai.run("qa", …)`
    ——对话能力只做路由，模型出口仍只有 `src/ai` 一处。
    解析与盘点走 `src/ai` 的 dialog 能力口（规则版离线可跑）；
    每轮对话的留痕复用 `ai_calls`（不新开账本）。空话 400；非 admin 401/403。
    """
    body = await request.json()
    payload, status = await _dialog_turn_impl(body, current_user(request) or "")
    if status == 200:
        return payload
    return JSONResponse(payload, status_code=status)


async def _dialog_turn_impl(body: dict, user: str, progress=None) -> tuple:
    """对话前门一轮的**共享内核**（同步口 #33 / 流口 #37 共用；2026-10-14 票 12）。

    返回 `(payload, status)`；`progress`（可选）在真实编排点收阶段码：
    「理解」（进对话能力前）/「查数」（进问答能力前）——规则模式如实少事件，不演。
    """
    def _prog(code):
        if progress is not None:
            try:
                progress(code)
            except Exception:                                     # noqa: BLE001
                pass

    t0 = time.monotonic()
    text = str(body.get("text") or "").strip()
    if not text:
        return {"error": "请先说一句话"}, 400
    slots = body.get("slots") if isinstance(body.get("slots"), dict) else {}
    period = str(slots.get("period") or "").strip()
    if period and not re.fullmatch(r"\d{6}", period):
        period = ""                                   # 形状不合法就丢弃，不猜
    intent = str(slots.get("intent") or "").strip()[:20]
    # 问数槽（2026-10-31 二步）：上一轮认出的指标/学科随对话流动——引擎拿它解
    # 「上一期呢」「那材料科学呢」这类追问；形状不合法的值丢弃。
    qmetric = str(slots.get("qmetric") or "").strip()[:12]
    qdisc = str(slots.get("qdisc") or "").strip()[:16]
    # 问数直答开关（ai 能力 qa_direct，settings.json 即时生效）：关＝问数句式回落
    # 既有路由（模型作答）——rick 2026-10-31 要 A/B 两条路径。
    from ai import _settings as _ai_settings                     # noqa: PLC0415
    qa_direct = bool(_ai_settings.store_for(config.OUT_DIR)
                     .read().get("caps", {}).get("qa_direct", True))
    # 会话（票 11）：有 session → 归属校验 + 历史从库读；无 → 本回合结束时建新会话。
    session_id = str(body.get("session") or "").strip()
    stored_turns = None
    if session_id:
        if session_db_path() is None:
            return {"error": "会话不存在"}, 404
        try:
            stored = await run_in_threadpool(session_store.load,
                                             session_db_path(), session_id, user)
        except (ValueError, KeyError):
            return {"error": "会话不存在"}, 404
        except PermissionError:
            return {"error": "会话不属于当前用户"}, 403
        stored_turns = stored["turns"]
    # 对话上文（2026-10-12 rick 实问「这是几月的」）：追问要靠上文解指代——
    # 只收 me/wh 的文本，条数与长度都截断（外发面另有字符上限兜底，默认 20000、env 可调）。
    # 带会话时改从库读（票 11），口径同上：最近 8 条、每条 200 字。
    history = []
    if stored_turns is not None:
        for t in stored_turns[-8:]:
            snippet = str(t.get("text") or "").strip()[:200]
            if snippet:
                history.append({"who": t["who"], "text": snippet})
    else:
        for item in (body.get("history") if isinstance(body.get("history"), list) else [])[-8:]:
            if not isinstance(item, dict):
                continue
            who = "me" if item.get("who") == "me" else "wh"
            snippet = str(item.get("text") or "").strip()[:200]
            if snippet:
                history.append({"who": who, "text": snippet})
    # 「最新的」解析（2026-10-13，票 10）：注入已知期次（降序）——「最近有效期次」
    # 与「本期」同源口径（taskview.known_periods：母本有效期次 ∪ out ∪ 取数在途）。
    import taskview                                               # noqa: PLC0415
    periods = await run_in_threadpool(taskview.known_periods)
    import ai                                                     # noqa: PLC0415
    actor = config.role_of(user)
    # 2026-10-12：操作员也有出报告/审批——报告流程两种角色一致（readonly 注入已取消）。
    _prog("理解")                                                 # 票 12：进对话能力前
    ans = await run_in_threadpool(ai.run, "dialog", period,
                                  payload={"text": text, "history": history,
                                           "periods": periods,
                                           "qmetric": qmetric, "qdisc": qdisc,
                                           "qa_direct": qa_direct}, actor=actor)
    if ans.mode in ("closed", "denied", "unavailable"):
        r = _answer_response(ans)
        return json.loads(r.body), r.status_code
    turn = ans.data or {}
    resp = ans.as_dict()
    resp["kind"] = str(turn.get("kind") or "")
    resp["slots"] = {"period": str(turn.get("period") or period),
                     "intent": str(turn.get("intent") or intent),
                     "qmetric": str(turn.get("qmetric") or qmetric),
                     "qdisc": str(turn.get("qdisc") or qdisc)}
    resp["verdict"] = str(turn.get("verdict") or "")
    resp["inventory"] = turn.get("inventory") if isinstance(turn.get("inventory"), dict) else None
    resp["actions"] = turn.get("actions") if isinstance(turn.get("actions"), list) else []
    # 出稿意图（票 03）：{period, auto}——auto=False 表示产物已在、先问一次；
    # 真正的开跑由前端拿它调既有开跑口（对话只做指挥，不替人按按钮）。
    resp["run"] = turn.get("run") if isinstance(turn.get("run"), dict) else None
    # 查数据（票 07）：dialog 只判意图；回答由**服务器**按意图调 qa 能力。
    # 没产物先提示出稿；qa 关闭照旧说「已关闭」——都在聊天里说清楚，不 404/409 摔出去。
    # 问数（aiqa，2026-10-31）：问数句式命中时构建器已直调问数引擎出好回答与图块
    # （白名单参数化 SQL、零模型，照他校简报先例）——这里只折进响应面：正文走
    # answer（带角标来源，query 同款），图块走 qa；顶层 text 清空防整段重显
    # （流式 delta 的 _visible_body 优先 answer.text，落库回读也优先 answer）。
    resp["answer"] = None
    resp["qa"] = None
    qa_block = turn.get("qa") if isinstance(turn.get("qa"), dict) else None
    if qa_block is not None:
        resp["qa"] = qa_block
        resp["answer"] = {k: resp[k] for k in ("mode", "backend", "text", "rule_text",
                                               "notice", "sources", "shield", "record_id")}
        resp["text"] = ""
    elif resp["kind"] == "query":
        target = resp["slots"]["period"]
        if target:
            if resolve_period_dir(target) is None:
                resp["text"] = "这一期还没有可用产物——先出稿，才有得查。"
            else:
                _prog("查数")                                     # 票 12：进问答能力前
                qa_ans = await run_in_threadpool(
                    ai.run, "qa", target,
                    payload={"question": text, "history": history}, actor=actor)
                resp["answer"] = qa_ans.as_dict()
    # 会话落库（票 11）：回合完成后追加「用户话＋文衡回复文本」，槽位整存；
    # 无 session 时此刻建新会话。落库失败不挡这一轮（聊天照常，只是这轮不持久化）。
    if session_db_path() is not None:
        try:
            if not session_id:
                session_id = await run_in_threadpool(
                    session_store.create, session_db_path(), user)
            await run_in_threadpool(session_store.append, session_db_path(),
                                    session_id, "me", text, user=user)
            reply = str(resp.get("text") or "").strip()
            if not reply and isinstance(resp.get("answer"), dict):
                reply = str(resp["answer"].get("text") or "").strip()
            if reply:
                await run_in_threadpool(session_store.append, session_db_path(),
                                        session_id, "wh", reply, user=user)
            await run_in_threadpool(session_store.save_slots, session_db_path(),
                                    session_id, resp["slots"], user=user)
        except Exception:                                     # noqa: BLE001
            session_id = ""
    resp["session_id"] = session_id
    resp["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    resp["ts"] = time.strftime("%H:%M")
    return resp, 200


#: 阶段文案（票 12）：阶段码 → 人话。规则模式如实少事件（不演）。
_STAGE_TEXT = {
    "理解": "正在理解这句话…",
    "查数": "正在查台账…",
    "model:dialog": "正在理解这句话…（模型兜底）",
    "model:qa-plan": "正在规划查哪些数…",
    "model:qa": "正在写答案…",
    "model:polish": "正在润色…",
    "model:qa-polish": "正在润色…",
}


#: 流式正文（契约 #37 扩展，2026-10-30）：答案整段到后（数字盾已还原）分块回传，
#: 让界面渐进显示、不再卡在「正在写答案…」。delta 排在 done 之前，仍满足首 stage / 末 done。
def _visible_body(payload: dict) -> str:
    """本轮要显示的正文：优先 qa 的 answer.text，兜底用顶层 text。"""
    if not isinstance(payload, dict):
        return ""
    ans = payload.get("answer")
    if isinstance(ans, dict) and str(ans.get("text") or "").strip():
        return str(ans.get("text") or "")
    return str(payload.get("text") or "")


def _chunk_text(s: str, size: int = 6):
    """按字符（非字节）切片，避免把多字节中文截断；空串不产出。"""
    s = s or ""
    for i in range(0, len(s), size):
        yield s[i:i + size]


@router.post("/api/dialog/turn/stream")
@user_route
async def api_dialog_turn_stream(request: Request):
    """对话前门一轮·**阶段进度流**（契约 #37，2026-10-14 票 12）：NDJSON 一行一事件。

    `stage×N → done(payload)`（payload 与 #33 响应同形状）；失败 → `error`（不断流）。
    **不流正文**——数字必须先过「数字盾」；阶段发生在真实节点（不造假进度）。
    请求体与 #33 完全一致。"""
    body = await request.json()
    user = current_user(request) or ""

    async def gen():
        q: asyncio.Queue = asyncio.Queue()
        result: dict = {}
        loop = asyncio.get_running_loop()

        def _put(code):
            # 进度可能来自线程池线程（_attempt 在 run_in_threadpool 里跑）——必须跨线程投递
            loop.call_soon_threadsafe(q.put_nowait, ("stage", code))

        def _trace(ev):
            # 工具调用轨迹（2026-10-29）：同样跨线程投递；坏了不影响这一轮。
            try:
                loop.call_soon_threadsafe(q.put_nowait, ("tool", dict(ev)))
            except Exception:                                     # noqa: BLE001
                pass

        async def _worker():
            try:
                import ai                                         # noqa: PLC0415
                with ai.using(progress=_put, trace=_trace):
                    result["payload"], result["status"] = await _dialog_turn_impl(
                        body, user, progress=_put)
            except Exception as e:                                # noqa: BLE001
                result["error"] = f"{type(e).__name__}: {e}"
            finally:
                q.put_nowait(("end", None))

        task = asyncio.create_task(_worker())
        try:
            while True:
                kind, item = await q.get()
                if kind == "end":
                    break
                if kind == "tool":
                    yield json.dumps({"event": "tool", **item},
                                     ensure_ascii=False) + "\n"
                    continue
                yield json.dumps({"event": "stage", "stage": item,
                                  "text": _STAGE_TEXT.get(item, "处理中…")},
                                 ensure_ascii=False) + "\n"
        finally:
            await task
        if result.get("status", 200) != 200 or "payload" not in result:
            payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
            yield json.dumps({"event": "error",
                              "error": payload.get("error") or result.get("error") or "未知错误",
                              "status": int(result.get("status") or 500)},
                             ensure_ascii=False) + "\n"
        else:
            payload = result["payload"]
            # 流式正文（#37 扩展）：数字盾已在 _attempt 内还原，此处正文是最终安全文本，
            # 分块回传让界面渐进显示；delta 在 done 之前，首 stage / 末 done 契约不变。
            for chunk in _chunk_text(_visible_body(payload), 6):
                yield json.dumps({"event": "delta", "text": chunk},
                                 ensure_ascii=False) + "\n"
            yield json.dumps({"event": "done", "payload": payload},
                             ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/api/dialog/session/{session_id}")
@user_route
async def api_dialog_session(request: Request, session_id: str):
    """会话回读（契约 #36，票 11）：刷新/换设备带 URL `?s=<id>` 即恢复。

    仅 owner：不存在 404、他人会话 403（与既有口径一致）；形状非法按不存在处理。
    """
    if session_db_path() is None:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    user = current_user(request) or ""
    try:
        data = await run_in_threadpool(session_store.load, session_db_path(), session_id, user)
    except (ValueError, KeyError):
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "会话不属于当前用户"}, status_code=403)
    return {"id": data["id"], "slots": data["slots"], "turns": data["turns"]}


@router.get("/api/dialog/sessions")
@user_route
async def api_dialog_sessions(request: Request):
    """会话清单（契约 #36 增补，2026-10-24 rick：要能看到之前的对话）：
    当前用户的保存对话，最近在前；库还没建过 → 空清单（空态不编）。"""
    if session_db_path() is None:
        return {"sessions": []}
    user = current_user(request) or ""
    rows = await run_in_threadpool(session_store.list_sessions, session_db_path(), user)
    return {"sessions": [{"id": r["id"], "title": r["title"],
                          "n_turns": r["n_turns"], "updated": r["updated"]} for r in rows]}


@router.post("/api/dialog/session/{session_id}/drop")
@user_route
async def api_dialog_session_drop(request: Request, session_id: str):
    """删一段保存的对话（仅本人；删除不可恢复，界面走行内确认）。"""
    if session_db_path() is None:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    user = current_user(request) or ""
    try:
        ok = await run_in_threadpool(session_store.drop, session_db_path(), session_id, user)
    except ValueError:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "会话不属于当前用户"}, status_code=403)
    if not ok:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    return {"ok": True}


@router.get("/api/dialog/home")
@user_route
async def api_dialog_home(request: Request):                      # noqa: ARG001
    """对话前门·空态「本期任务」（契约 #35，票 06）：三步状态从既有产物判，只读不新算。

    本期＝最新一个有内容的期次（台账有效期次 ∪ 出过稿的产物 ∪ 取数四件已齐）；三步全成且已签发 → 顺延下一期。
    签发状态在 server 层核实（`src/taskview` 不 import server）；扫描拿不到 → 空形状
    （界面退回普通问候，不编）。
    """
    import taskview                                               # noqa: PLC0415

    def _status(period: str) -> str:
        return approval.status(config.OUT_DIR / period)

    data = await run_in_threadpool(taskview.scan, status=_status)
    if data is None:
        return {"period": "", "released": False, "n_missing": 0,
                "steps": [], "stuck": "", "prev": None}
    return data


# ---------------- AI 问数（SQLite + 受控 NL2SQL；2026-10-25）----------------
# 数据层：src/aiqa_db.py（out/_aidata/aiqa.sqlite，单向 ETL、运行期只读 + qa_log 留痕）；
# 引擎：src/aiqa_engine.py（规则规划器 → 白名单参数化 SQL → 人话渲染 + 图型建议）。
# 红线：模型的输出类型里没有数值——规划只产白名单规格，SQL 由引擎拼装执行。


def _aiqa_con():
    """问数库只读连接；缺库 503 人话（提示管理员先构建）。"""
    try:
        from src import aiqa_db                                   # noqa: PLC0415
        return aiqa_db.connect_ro(config.ROOT), None
    except FileNotFoundError:
        return None, JSONResponse(
            {"error": "问数数据库还没建好",
             "hint": "请在服务器上运行 tools/build_aiqa_db.py 后重试"},
            status_code=503)


@router.get("/api/aiqa/meta")
@user_route
async def api_aiqa_meta(request: Request):
    """问数库元信息（期次 / 指标白名单 / 学科名单 / 期次轴）。已登录即可。"""
    con, err = _aiqa_con()
    if err:
        return err
    try:
        from src import aiqa_db                                   # noqa: PLC0415
        m = aiqa_db.meta(config.ROOT)
        return {
            "period": m.get("period", ""),
            "built_at": m.get("built_at", ""),
            "n_facts": int(m.get("n_facts", "0") or 0),
            "disciplines": aiqa_db.view_disciplines(con),
            "metrics": aiqa_db.view_metrics(con),
            "periods": aiqa_db.view_periods(con),
        }
    finally:
        con.close()


@router.post("/api/aiqa/ask")
@user_route
async def api_aiqa_ask(request: Request):
    """问数主口（契约 #38）：{question} → 规格化查询 + 人话回答 + 图表数据。

    规划＝规则适配器（离线可跑）；执行＝白名单参数化 SQL（只读连接）；
    每问落 `qa_log` 留痕（写失败不阻塞查询）。
    """
    con, err = _aiqa_con()
    if err:
        return err
    t0 = time.time()
    try:
        from src import aiqa_db, aiqa_engine                      # noqa: PLC0415
        try:
            body = await request.json()
        except Exception:                                          # noqa: BLE001
            return JSONResponse({"error": "请求不是合法 JSON"},
                                status_code=400)
        question = str((body or {}).get("question") or "").strip()
        if not question:
            return JSONResponse({"error": "问题不能为空",
                                 "hint": "试试「化学的总被引趋势」"},
                                status_code=400)
        plan = aiqa_engine.plan(question, con)
        result = aiqa_engine.execute(con, plan["specs"])
        text = aiqa_engine.render_text(con, question, result)
        chart = aiqa_engine.suggest_chart(con, plan["specs"], result)
        chart_data = aiqa_engine.to_chart_data(con, chart, result)
        elapsed = int((time.time() - t0) * 1000)
        user = current_user(request) or ""
        n_rows = sum(len(r.get("points") or r.get("items") or
                         r.get("rows") or []) for r in result.get("rows") or [])
        record_id = aiqa_db.log_qa(
            config.ROOT, user=user, question=question, specs=plan["specs"],
            plan_origin=plan["origin"], n_rows=n_rows, elapsed_ms=elapsed,
            answer_text=text, chart_kind=chart.get("kind", ""))
        return {
            "question": question,
            "plan": {"specs": plan["specs"], "origin": plan["origin"],
                     "note": plan.get("note", "")},
            "answer": text,
            "chart": chart,
            "chart_data": chart_data,
            "record_id": record_id,
            "elapsed_ms": elapsed,
        }
    finally:
        con.close()


@router.get("/api/aiqa/log")
@admin_route
async def api_aiqa_log(request: Request, limit: int = 50):
    """问数留痕（仅管理员）：最近 N 条（新→旧）。"""
    con, err = _aiqa_con()
    if err:
        return err
    try:
        limit = max(1, min(int(limit or 50), 500))
        rows = [dict(r) for r in con.execute(
            "SELECT id, ts, user, question, specs, plan_origin, n_rows,"
            " elapsed_ms, answer_text, chart_kind FROM qa_log "
            "ORDER BY id DESC LIMIT ?", (limit,))]
        for r in rows:
            try:
                r["specs"] = json.loads(r.get("specs") or "[]")
            except Exception:                                      # noqa: BLE001
                r["specs"] = []
        return {"log": rows, "n": len(rows)}
    finally:
        con.close()
