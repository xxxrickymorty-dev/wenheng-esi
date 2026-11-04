# -*- coding: utf-8 -*-
"""monitor 分册：监测版（高校 ESI 报告，第三条产线）（20261101 C8 路由分册）。

ESI-only 全校站位报告，只读全局件，不碰台账与 out/。
契约：《监测版包契约-ESIonly（2026-10-31）》（工作区仓库① 设计文档）。
生成口幂等（20261101 C7）：同校/同校集合同期产物已存在 → 直接复用，不重跑 insight。
生成口供应商强制语义（rick 2026-11-04）：开启态下 insight 模型位失败
（`AIRequiredError`）→ 503 人话返回，不落半份产物。
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


def _ai_required_response(exc: Exception) -> JSONResponse:
    """供应商强制语义（rick 2026-11-04）：开启态下模型位失败
    （`AIRequiredError`）→ 人话错误返回，不落半份产物。
    文案本身已是人话（位置 + 原因码 + 重试指引），原样透传。"""
    return JSONResponse({"error": str(exc)}, status_code=503)


def _monitor_school_payload(period: str, field: str | None = None) -> dict:
    cache = monitor_report.load_cache(period)
    en_set_known = set()
    if cache:
        en_set_known = {row[0] for row in cache["cn_inst"]}
        en_set_known |= {en for v in cache["fields"].values() for en in v["schools"]}
    # 在榜查询（2026-11-04，P2 分析台契约）：带 field → items 增 in_field。
    # 数据源＝监测期次缓存 fields[field]["schools"]（键＝ESI 机构英文名，
    # 与 src/monitor/schools.py 的 en 名同源匹配）；不带 → 行为与从前逐字一致。
    field_stem = None
    in_field_set: set[str] = set()
    if field is not None and str(field).strip():
        field_stem = next(
            (s for s in monitor_report.STEMS
             if monitor_report.norm(s) == monitor_report.norm(str(field))),
            None)
        if field_stem is None:
            return JSONResponse(
                {"error": f"「{field}」不是 ESI 22 学科",
                 "hint": "学科英文名从 22 学科里选，如："
                         + "、".join(monitor_report.STEMS)},
                status_code=400)
        if not cache or field_stem not in cache["fields"]:
            return JSONResponse(
                {"error": f"本期（{period}）监测缓存里没有「{field_stem}」学科榜",
                 "hint": "先跑监测版缓存（monitor.build_cache），或换一个学科"},
                status_code=400)
        in_field_set = set(cache["fields"][field_stem]["schools"])
    items = []
    for s in monitor_schools.SCHOOLS:
        f = monitor_report.MONITOR_ROOT / s["cn"] / f"{period}.html"
        it = {
            "cn": s["cn"], "en": s["en"], "prov": s["prov"], "is985": s["is985"],
            "known": (not cache) or (s["en"] in en_set_known),
            "generated": f.exists(),
            "url": f"/monitor/report/{urllib.parse.quote(s['cn'])}/{period}.html" if f.exists() else None,
        }
        if field_stem is not None:
            it["in_field"] = s["en"] in in_field_set
        items.append(it)
    payload = {"period": period, "built": (cache or {}).get("built"), "schools": items}
    if field_stem is not None:
        payload["field"] = field_stem
    return payload


@router.get("/api/monitor/schools")
@user_route
async def api_monitor_schools(request: Request):
    """监测版内置院校清单：985/211 槽位 + 每校「ESI 是否在册 / 报告是否已生成」。

    可选查询参数 `field`（ESI 学科英文名，如 `Computer Science`，大小写不敏感）：
    带了 → items 每条加 `in_field`（该校该学科是否进入本期 ESI 前 1% 榜单），
    顶层回显 `field`（规范名）；不在 22 学科 / 本期缓存缺该学科 → 400 人话；
    不带 → 行为与从前完全一致（不加字段）。"""
    period = monitor_report.latest_period()
    if not period:
        return JSONResponse({"error": "没有可用的 ESI 期次数据",
                             "hint": "数据与复现/ESI数据/ 下需要有带 Institutions.xlsx 的期次目录"},
                            status_code=404)
    field = request.query_params.get("field")
    return _monitor_school_payload(period, field=field)


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
    except Exception as exc:                                    # noqa: BLE001
        from ai._attempt import AIRequiredError                 # noqa: PLC0415
        if isinstance(exc, AIRequiredError):
            # 供应商强制语义（rick 2026-11-04）：不落半份产物，人话报错。
            return _ai_required_response(exc)
        raise
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
    except Exception as exc:                                    # noqa: BLE001
        from ai._attempt import AIRequiredError                 # noqa: PLC0415
        if isinstance(exc, AIRequiredError):
            # 供应商强制语义（rick 2026-11-04）：不落半份产物，人话报错。
            return _ai_required_response(exc)
        raise
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
