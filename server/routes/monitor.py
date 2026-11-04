# -*- coding: utf-8 -*-
"""monitor 分册：监测版（高校 ESI 报告，第三条产线）（20261101 C8 路由分册）。

ESI-only 全校站位报告，只读全局件，不碰台账与 out/。
契约：《监测版包契约-ESIonly（2026-10-31）》（工作区仓库① 设计文档）。
生成口幂等（20261101 C7）：同校/同校集合同期产物已存在 → 直接复用，不重跑 insight。
docx 缺件兜底走 `monitor.docx.ensure`（当期缺失现算、老期次不补）。
"""
import re
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from ..guards import user_file_route, user_route
from src.monitor import compare as monitor_compare
from src.monitor import docx as monitor_docx
from src.monitor import report as monitor_report
from src.monitor import schools as monitor_schools

router = APIRouter()


def _monitor_school_payload(period: str) -> dict:
    cache = monitor_report.load_cache(period)
    en_set_known = set()
    if cache:
        en_set_known = {row[0] for row in cache["cn_inst"]}
        en_set_known |= {en for v in cache["fields"].values() for en in v["schools"]}
    items = []
    for s in monitor_schools.SCHOOLS:
        f = monitor_report.MONITOR_ROOT / s["cn"] / f"{period}.html"
        items.append({
            "cn": s["cn"], "en": s["en"], "prov": s["prov"], "is985": s["is985"],
            "known": (not cache) or (s["en"] in en_set_known),
            "generated": f.exists(),
            "url": f"/monitor/report/{urllib.parse.quote(s['cn'])}/{period}.html" if f.exists() else None,
        })
    return {"period": period, "built": (cache or {}).get("built"), "schools": items}


@router.get("/api/monitor/schools")
@user_route
async def api_monitor_schools(request: Request):
    """监测版内置院校清单：985/211 槽位 + 每校「ESI 是否在册 / 报告是否已生成」。"""
    period = monitor_report.latest_period()
    if not period:
        return JSONResponse({"error": "没有可用的 ESI 期次数据",
                             "hint": "数据与复现/ESI数据/ 下需要有带 Institutions.xlsx 的期次目录"},
                            status_code=404)
    return _monitor_school_payload(period)


@router.post("/api/monitor/report")
@user_route
async def api_monitor_report(request: Request):
    """生成一所学校的站位报告（同校同期已生成则直接复用，不重复算）。"""
    try:
        body = await request.json()
    except Exception:                                          # noqa: BLE001
        body = {}
    cn = str(body.get("school") or "").strip()
    s = monitor_schools.find(cn)
    if s is None:
        return JSONResponse({"error": f"名单里没有「{cn}」这所学校",
                             "hint": "从清单里选，或先在 src/monitor/schools.py 里补录"},
                            status_code=404)
    period = monitor_report.latest_period()
    if not period:
        return JSONResponse({"error": "没有可用的 ESI 期次数据",
                             "hint": "数据与复现/ESI数据/ 下需要有带 Institutions.xlsx 的期次目录"},
                            status_code=404)
    def _gen():
        return monitor_report.generate(cn, period)
    try:
        path = await run_in_threadpool(_gen)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    url = f"/monitor/report/{urllib.parse.quote(cn)}/{period}.html"
    return {"period": period, "url": url, "cached": path.exists() and path.stat().st_size > 0}


@router.post("/api/monitor/compare")
@user_route
async def api_monitor_compare(request: Request):
    """对比队列一键生成：体 {schools: [中文名...]}，去重保序、不限数量（≥2）。
    幂等（20261101 C7）：同校集合同期产物已存在 → 直接复用，不重跑 insight（LLM 不重复调用）。
    """
    try:
        body = await request.json()
    except Exception:                                          # noqa: BLE001
        body = {}
    cns = [str(x).strip() for x in (body.get("schools") or []) if str(x).strip()]
    if len(cns) < 2:
        return JSONResponse({"error": "对比至少选 2 所学校",
                             "hint": "点卡片右上角「＋」把学校放进对比队列"}, status_code=400)
    unknown = [cn for cn in cns if monitor_schools.find(cn) is None]
    if unknown:
        return JSONResponse({"error": f"名单里没有：{'、'.join(unknown)}",
                             "hint": "从清单里选，或先在 src/monitor/schools.py 里补录"}, status_code=404)
    period = monitor_report.latest_period()
    if not period:
        return JSONResponse({"error": "没有可用的 ESI 期次数据"}, status_code=404)

    def _gen():
        return monitor_compare.generate(cns, period)
    try:
        path = await run_in_threadpool(_gen)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    url = f"/monitor/compare/{period}/{path.name}"
    return {"period": period, "url": url, "n": len(cns)}


@router.get("/api/monitor/compare-status")
@user_route
async def api_monitor_compare_status(request: Request):
    """对比件落盘探测（前端轮询兜底，20261104）：`?schools=A,B&period=YYYYMM`。

    文件名确定性同 `compare.compare_path`；已落盘 → 200 + {exists,url}，
    未落盘 → 404 + {exists:false,url}（前端只认 r.ok，落盘即跳）。"""
    qp = request.query_params
    cns = [x.strip() for x in (qp.get("schools") or "").split(",") if x.strip()]
    if len(cns) < 2:
        return JSONResponse({"error": "对比至少选 2 所学校",
                             "hint": "点卡片右上角「＋」把学校放进对比队列"}, status_code=400)
    unknown = [cn for cn in cns if monitor_schools.find(cn) is None]
    if unknown:
        return JSONResponse({"error": f"名单里没有：{'、'.join(unknown)}",
                             "hint": "从清单里选，或先在 src/monitor/schools.py 里补录"}, status_code=404)
    period = qp.get("period") or monitor_report.latest_period()
    if not period or not re.fullmatch(r"20\d{4}", period):
        return JSONResponse({"error": "没有可用的 ESI 期次数据"}, status_code=404)
    path = monitor_compare.compare_path(cns, period)
    url = f"/monitor/compare/{period}/{path.name}"
    if path.exists():
        return {"exists": True, "url": url}
    return JSONResponse({"exists": False, "url": url}, status_code=404)


@router.get("/monitor/compare/{period}/{fname}")
@user_file_route
def monitor_compare_page(request: Request, period: str, fname: str):
    """对比报告页（登录后可看）。文件名确定性（校名集合哈希）；同校集合同期已生成即复用，
    要重出先删旧件（compare.generate 幂等，20261101 C7）。"""
    if not re.fullmatch(r"20\d{4}", period or "") or             not re.fullmatch(r"cmp_[0-9a-f]{12}\.html", fname or ""):
        raise HTTPException(status_code=404)
    p = monitor_report.MONITOR_ROOT / "_compare" / period / fname
    if not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(p, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


@router.get("/monitor/report/{cn}/{fname}")
@user_file_route
def monitor_report_page(request: Request, cn: str, fname: str):
    """监测版报告页（登录后可看；admin 与操作员同权——只读验证件）。docx 缺文件时现生成。"""
    m = re.fullmatch(r"(20\d{4})\.(html|docx)", fname or "")
    if not m:
        raise HTTPException(status_code=404)
    p = monitor_report.MONITOR_ROOT / cn / fname
    if not p.is_relative_to(monitor_report.MONITOR_ROOT):
        raise HTTPException(status_code=404)
    if not p.exists():
        if m.group(2) != "docx":
            raise HTTPException(status_code=404)    # html 只随当期落盘，缺失不补
        # 缺件兜底收口到 monitor.docx.ensure（20261101 C7）：名单外校／老期次不补
        # （None → 404）；期次包坏时 build_cache 的 FileNotFoundError 照抛（→ 404 带原因），
        # 语义与原内联段逐字一致。
        try:
            generated = monitor_docx.ensure(cn, m.group(1))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if generated is None:
            raise HTTPException(status_code=404)
        p = generated
    if fname.endswith(".docx"):
        return FileResponse(p, media_type="application/vnd.openxmlformats-officedocument"
                                     ".wordprocessingml.document",
                            headers={"Cache-Control": "no-cache"})
    return FileResponse(p, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})
