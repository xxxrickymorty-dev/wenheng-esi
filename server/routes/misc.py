# -*- coding: utf-8 -*-
"""misc 分册：杂项端点（20261101 C8 路由分册，从 server/app.py 迁入）。

探活、工作区状态（含状态库只读降级告警，ADR-0012 决定 7）、当前用户、
沙盘故事卡、台账表页盘点、二维码。
"""
import io
import json
import pathlib

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config, jobs, visibility
from ..guards import admin_route, current_user, user_route
from datetime import datetime
from src import ledger as ledger_mod  # 动态监测表（母本）路径唯一口径（2026-10-13：input/ 只放母本）
from src import state_store      # 系统状态库：/api/status 报「能不能写」（ADR-0012 决定 7）

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"ok": True}


#: 状态库只读降级时给馆员看的话（页面原文）。技术细节只进服务端日志：
#: 这两句里不出现库名、版本号、迁移之类的字眼，只说「现在怎么样 + 找谁」。
STATE_DB_TOO_NEW = "本机数据存储版本比程序新，已进入只读模式，请联系管理员。"
STATE_DB_UNREADABLE = "本机数据存储打不开，保存类操作已暂停，请联系管理员。"


def _state_db_status() -> dict:
    """`/api/status` 的 `state_db`：本机状态库现在能不能写（ADR-0012 决定 7 的告警数据源）。

    库不存在＝正常（还没签过单），**这里绝不建库**——`state_store.health()` 只连已存在的文件。
    降级分两种：版本比程序新（能读、不能写）与库打不开；两种都给一句人话，页面据此挂横幅。
    """
    try:
        h = state_store.health(jobs.state_db_path())
    except OSError:                      # 路径本身读不了（权限/被占）：如实报，不装作健康
        return {"ok": False, "schema_version": 0,
                "code_schema_version": state_store.SCHEMA_VERSION,
                "degraded": True, "message": STATE_DB_UNREADABLE}
    degraded = bool(h.get("degraded"))
    too_new = degraded and (h.get("schema_version") or 0) > (h.get("code_version") or 0)
    return {
        "ok": not degraded,
        "schema_version": h.get("schema_version") or 0,
        "code_schema_version": h.get("code_version") or 0,
        "degraded": degraded,
        "message": (STATE_DB_TOO_NEW if too_new else STATE_DB_UNREADABLE) if degraded else "",
    }


@router.get("/api/status")
@user_route
async def api_status(request: Request):
    """工作区任务入口：只提供前端跳转所需的任务标识，不暴露落盘记录。

    `state_db`（2026-10-22 加）：本机数据存储能不能写——库版本比程序新时只能只读，
    页面据此挂一条常驻告警（写入会失败，得先让馆员知道为什么）。既有字段一个不动。
    """
    active = jobs.active_job()
    last = next((j for j in jobs.list_jobs(20) if j.get("stats")), None)
    return {
        "active": (active or {}).get("id"),
        "last": ({"id": last.get("id"), "period": last.get("period")}
                 if last else None),
        "state_db": _state_db_status(),
    }


@router.post("/api/feedback")
async def api_feedback(request: Request):
    """意见反馈（2026-11-07 用户菜单收编件）：登录用户写一句，落 _feedback/feedback.jsonl。
    目录在 ROOT/_feedback——刻意不放 out/（数据红线：out/ 只读）。"""
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录", "hint": "请先登录"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "无法解析", "hint": "请重试"}, status_code=400)
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "内容为空", "hint": "写一句再提交"}, status_code=400)
    fb_dir = config.ROOT / "_feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    rec = {"at": datetime.now().isoformat(timespec="seconds"), "user": user, "text": text[:2000]}
    with (fb_dir / "feedback.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    return {"ok": True}


@router.get("/api/me")
async def api_me(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "未登录", "hint": "请先登录"}, status_code=401)
    role = config.role_of(user)
    return {"name": user, "role": role,
            "capabilities": visibility.capabilities(role)}


@router.get("/api/sandbox/heal")
@user_route
async def api_sandbox_heal(request: Request):                      # noqa: ARG001
    """自愈沙盘故事卡（只读）：读 tmp/_heal_sandbox/story.json。

    沙盘只碰副本；原件与脏件哈希由 tools/heal_sandbox.py 记录。没跑过就
    返回 available=false，界面给一条「先跑哪条命令」，不编故事。
    """
    path = pathlib.Path(__file__).resolve().parent.parent / "tmp" / "_heal_sandbox" / "story.json"
    if not path.exists():
        return {"available": False, "hint": "先跑一次自愈沙盘工具，刷新本页"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "hint": "沙盘故事卡读不出来，重跑一次自愈沙盘工具"}
    return {"available": True, **data}


@router.get("/api/sandbox/migrate")
@user_route
async def api_sandbox_migrate(request: Request):                    # noqa: ARG001
    """换馆沙盘故事卡（只读）：读 tmp/_migration_sandbox/readiness.json。"""
    path = pathlib.Path(__file__).resolve().parent.parent / "tmp" / "_migration_sandbox" / "readiness.json"
    if not path.exists():
        return {"available": False, "hint": "先跑一次换馆沙盘工具，刷新本页"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "hint": "换馆故事卡读不出来，重跑一次换馆沙盘工具"}
    return {"available": True, **data}


@router.get("/api/ledger/sheets")
@admin_route
async def api_ledger_sheets(request: Request, period: str = ""):
    import openpyxl                                        # noqa: PLC0415
    # 2026-10-13 起只有一份动态监测表（母本，含全部期次）；period 参数保留仅为 API 兼容。
    lp = ledger_mod.runtime_path(config.ROOT)
    if not lp.exists():
        return JSONResponse({"error": "动态监测表不在",
                             "hint": f"请把母本放到 input/{ledger_mod.LEDGER_NAME}"},
                            status_code=404)
    try:
        wb = openpyxl.load_workbook(str(lp), read_only=True, data_only=True)
    except Exception as exc:                               # noqa: BLE001
        return JSONResponse({"error": f"台账读取失败：{exc}"}, status_code=500)
    sheets = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(max_row=2, values_only=True)
        header = next(rows, ()) or ()
        cols = [str(c).strip() if c is not None else "" for c in header]
        periods = [c for c in cols[1:] if c and c[0].isdigit() and len(c) == 6]
        sheets.append({
            "name": ws.title,
            "columns": cols,
            "n_columns": len(cols),
            "periods": periods,
            "n_periods": len(periods),
        })
    wb.close()
    return {"file": lp.name, "sheets": sheets, "n_sheets": len(sheets)}


@router.get("/qr.png")
async def qr(request: Request):
    url = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    try:
        import qrcode
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="image/png")
    except Exception:  # noqa: BLE001
        return JSONResponse({"url": url}, status_code=200)
