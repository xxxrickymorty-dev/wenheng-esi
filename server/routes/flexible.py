# -*- coding: utf-8 -*-
"""flexible 分册：灵活报告（第二条产线）与多校面板（20261101 C8 路由分册）。

口径见 `评审文档/19-双模式报告设计方案v1（权威口径）`。
🔴 复刻路径**完全不受影响**：这些路由只读 `out/<期次>/`、只写
   `out/<期次>/flexible/`，与复刻报告的产物（报告初稿 / red_slots / charts）互不重叠。
⚠ 2026-09-21 合入 V1 预测模块（PR #1）时这一整块曾被对方那份 app.py 覆盖掉，
   靠 `tests/test_stack_contract.py::test_状态变更都走表单POST而非AJAX` 抓回来。
   删任何一条路由前，先想清楚工作台首屏的入口会不会变成 404。
"""
import json
import pathlib
import re
import threading
import time
import urllib.parse
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               Response, StreamingResponse)
from starlette.concurrency import run_in_threadpool

from .. import jobs
from ..guards import (_period_missing, admin_route, user_file_route,
                      user_route)
from ..web_common import resolve_period_dir

router = APIRouter()


def _flex_ctx(d, intent=None, flash=None, variant=None):
    """灵活报告页上下文。`variant="rule"` 时正文取规则稿留底（report.rule.md）。"""
    import flexible.report as flex_report                           # noqa: PLC0415
    from flexible import mdview, planner, spec                     # noqa: PLC0415
    reports = flex_report.list_reports(d)
    cur = next((r for r in reports if r["intent"] == intent), None) or \
        (reports[0] if reports else None)
    body = None
    variant = (variant or "").strip()
    if cur:
        md_path = pathlib.Path(cur["path"])
        rule_path = md_path.parent / "report.rule.md"
        if variant == "rule" and rule_path.is_file():
            md_path = rule_path
        md = md_path.read_text(encoding="utf-8")
        imgmap = {n: f"/p/{d.name}/flexible/chart/{cur['intent']}/"
                     + urllib.parse.quote(n)
                  for n in (cur.get("meta", {}).get("charts") or [])}
        body = mdview.render(md, img_map=imgmap)
    return {"period_dir": d.name, "reports": reports, "cur": cur, "body": body,
            "variant": variant if (cur and variant == "rule"
                                   and (pathlib.Path(cur["path"]).parent
                                        / "report.rule.md").is_file()) else "",
            "has_rule": bool(cur and cur.get("has_rule")),
            "intents": [{"id": k, "cn": v} for k, v in planner.INTENTS.items()],
            "chart_catalog": spec.catalog(), "flash": flash,
            "disciplines": _flex_disciplines(d),
            "write": _flex_write_state()}


def _flex_disciplines(d) -> list[dict]:
    """监测学科清单（下拉用）：`[{en, cn}]`；数据缺时不报错、回空表。"""
    try:
        from flexible.datasource import DataSource, cn_name         # noqa: PLC0415
        src = DataSource(d)
        return [{"en": x, "cn": cn_name(x)} for x in src.disciplines]
    except Exception:                                                # noqa: BLE001
        return []


def _flex_write_state() -> dict:
    """写作位（AI 润色）的部署状态：开关开了且配了云才算可用（判据在 `ai._writing`）。"""
    try:
        from ai import _writing                                      # noqa: PLC0415
        return _writing.writing_state("write").as_dict()
    except Exception:                                                # noqa: BLE001
        return {"enabled": False, "available": False}


def _flex_appearance_from_meta(d, intent: str):
    """从 flex_meta.json 读回生成时的外观（下载 / 润色用）。

    meta 缺失、解析失败、旧稿没记外观、值不是 dict → None：
    调用方按「不带外观」走，回落行为与从前逐字节一致。
    """
    p = d / "flexible" / intent / "flex_meta.json"
    try:
        a = json.loads(p.read_text(encoding="utf-8")).get("appearance")
    except (OSError, ValueError):                                  # noqa: BLE001
        return None
    return a if isinstance(a, dict) else None


@router.get("/p/{period}/flexible/chart/{intent}/{name}")
@user_file_route
async def period_flexible_chart(request: Request, period: str,
                                intent: str, name: str):
    """灵活报告的图。**与复刻图分开解析** —— 归到 `flexible/<intent>/charts/` 下。"""
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    p = jobs.resolve_flex_chart(d, intent, name)
    if p is None:
        raise HTTPException(status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@router.get("/p/{period}/flexible/{intent}/report.html")
@user_file_route
async def period_flexible_report(request: Request, period: str, intent: str):
    """灵活报告整篇下载（rick 2026-09-29：出稿后「下载报告」）。

    返回的是**单文件**版：下载时把页内相对路径的图**即时内联**成 `data:` URI
    （`mdview.inline_images`）——离开 `charts/` 目录也带图；磁盘原件一个字节不动
    （旧稿也立刻生效，不必重出）。页内图在生成期已内联的新稿走同一函数，幂等。
    """
    if not re.fullmatch(r"[a-z0-9_]+", intent or ""):
        raise HTTPException(status_code=404)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    p = d / "flexible" / intent / "report.html"
    if not p.exists():
        raise HTTPException(status_code=404)
    import flexible.mdview as flex_mdview                            # noqa: PLC0415
    text = None
    # 2026-11-04：下载口即时 ECharts 升级——从 report.md + flex_sources.json
    # 现场重渲染（新稿幂等；旧稿也立刻拿到 ECharts 版，磁盘原件不动）。
    # 任一前置缺失/失败 → 回落原文件 + PNG 内联（绝不编数据）。
    try:
        md_p = p.parent / "report.md"
        srcs_p = p.parent / "flex_sources.json"
        if md_p.is_file() and srcs_p.is_file():
            from flexible import echart as fx_echart                 # noqa: PLC0415
            entries = json.loads(srcs_p.read_text(encoding="utf-8"))
            charts = [e for e in entries if e.get("kind") == "chart"]
            payloads = fx_echart.payloads_for(charts, d)
            md_text = md_p.read_text(encoding="utf-8")
            m = re.match(r"(?m)^#\s+(.+)$", md_text)
            title = m.group(1).strip() if m else "灵活分析稿"
            # 外观跟着生成件走：从 flex_meta.json 读回（旧稿没记 → None，
            # 与从前逐字节一致）；重渲染与磁盘原件无关，读不了也不编。
            text = flex_mdview.standalone(md_text, title,
                                           base_dir=p.parent,
                                           chart_payloads=payloads,
                                           appearance=_flex_appearance_from_meta(d, intent))
    except Exception:                                                # noqa: BLE001
        text = None
    if text is None:
        text = flex_mdview.inline_images(p.read_text(encoding="utf-8"),
                                          base_dir=p.parent)
    fn = urllib.parse.quote(f"灵活报告_{period}_{intent}.html")
    return Response(text, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-cache",
                             "Content-Disposition": f"attachment; filename*=utf-8''{fn}"})


@router.get("/p/{period}/flexible/{intent}/report.docx")
@user_file_route
async def period_flexible_report_docx(request: Request, period: str, intent: str):
    """灵活报告 DOCX 下载（2026-10-15，rick：给 docx 方便馆员修改）。

    磁盘上有且不比 `report.md` 旧 → 直接发；否则**现场转换**（不落盘）——
    旧稿即刻可用，不必重出。页脚标注「内部参考 · 非报送件」（doc19 导出规格）。
    """
    if not re.fullmatch(r"[a-z0-9_]+", intent or ""):
        raise HTTPException(status_code=404)
    d = resolve_period_dir(period)
    if d is None:
        return RedirectResponse("/", status_code=303)
    md_p = d / "flexible" / intent / "report.md"
    dx_p = d / "flexible" / intent / "report.docx"
    if not md_p.exists():
        raise HTTPException(status_code=404)
    if dx_p.exists() and dx_p.stat().st_mtime >= md_p.stat().st_mtime:
        data = dx_p.read_bytes()
    else:
        def _convert():
            import flexible.docxview as flex_docx                    # noqa: PLC0415
            return flex_docx.build(md_p.read_text(encoding="utf-8"), base_dir=md_p.parent)
        data = await run_in_threadpool(_convert)
    fn = urllib.parse.quote(f"灵活报告_{period}_{intent}.docx")
    return Response(data, media_type=(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers={"Cache-Control": "no-cache",
                 "Content-Disposition": f"attachment; filename*=utf-8''{fn}"})


@router.get("/api/periods/{period}/flexible")
@user_route
async def api_period_flexible(request: Request, period: str, intent: str = "",
                              variant: str = ""):
    """灵活报告 JSON（契约 #21①）：列已生成 + 当前稿的 body_html + 下拉清单。

    body_html 用**后端同一个 mdview.render**（图已指向
    `/p/<期次>/flexible/chart/<intent>/<name>`）——前端不引 md 渲染器。
    `variant=rule`：看写作位留底的规则稿（`report.rule.md`）。
    未生成过的期次返回空列表 + cur=null + body_html=""，不 500。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    ctx = _flex_ctx(d, intent or None, variant=variant or None)
    return {
        "period": ctx["period_dir"],
        "intents": ctx["intents"],
        "reports": [{"intent": r["intent"], "title": r["title"], "meta": r["meta"],
                     "has_rule": bool(r.get("has_rule"))}
                    for r in ctx["reports"]],
        "cur": (ctx["cur"] or {}).get("intent") or None,
        "variant": ctx.get("variant") or "",
        "has_rule": bool(ctx.get("has_rule")),
        "disciplines": ctx.get("disciplines") or [],
        "write": ctx.get("write") or {"enabled": False, "available": False},
        "body_html": ctx["body"] or "",
    }


@router.post("/api/periods/{period}/flexible")
@admin_route
async def api_period_flexible_generate(request: Request, period: str):
    """生成一份灵活报告（契约 #21②）—— 同步几秒。

    只写 `out/<期次>/flexible/`（产物目录），台账一字节不碰。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    intent = str(body.get("intent") or "").strip()
    disc = str(body.get("disc") or "").strip() or None
    peers = body.get("peers")
    if isinstance(peers, str):
        peers = peers.split(",")
    peers = [str(x).strip() for x in (peers or []) if str(x).strip()]
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}",
                             "hint": "可选：" + "、".join(flex_planner.INTENTS)}, status_code=400)
    import flexible.report as flex_report                           # noqa: PLC0415
    # 报告外观三轴：请求带了才抽（不认识的值静默回落，绝不 400）。
    from monitor.appearance import appearance_from_body             # noqa: PLC0415
    appearance = appearance_from_body(body) or None
    t0 = time.time()
    try:
        if appearance is None:
            r = flex_report.generate(d, intent, disc=disc, peers=peers)
        else:
            r = flex_report.generate(d, intent, disc=disc, peers=peers,
                                     appearance=appearance)
    except ValueError as e:
        return JSONResponse({"error": str(e)[:200],
                             "hint": "学科请从名单中选择（支持中文名）"}, status_code=400)
    except Exception as e:                                          # noqa: BLE001
        return JSONResponse({"error": f"生成失败：{type(e).__name__}", "hint": str(e)[:200]}, status_code=500)
    return {"ok": True, "intent": intent, "elapsed": round(time.time() - t0, 1),
            "n_charts": r.get("n_charts"), "backend": (r.get("plan") or {}).get("backend", "")}


def _flex_stream_line(ev: dict, d, intent: str) -> str:
    """流式事件 → 一行 NDJSON。section 的正文 md 在此渲成 html（图指服务端路由）。"""
    if ev.get("event") == "section":
        import re                                                    # noqa: PLC0415
        from flexible import mdview                                  # noqa: PLC0415
        names = [p.split("/")[-1]
                 for p in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", ev.get("body") or "")]
        imgmap = {n: f"/p/{d.name}/flexible/chart/{intent}/"
                     + urllib.parse.quote(n) for n in names}
        html = mdview.render(ev["body"], img_map=imgmap)
        return json.dumps({"event": "section", "title": ev["title"], "html": html},
                          ensure_ascii=False) + "\n"
    body = {k: v for k, v in ev.items() if k != "event"}
    return json.dumps({"event": ev.get("event"), **body},
                      ensure_ascii=False, default=str) + "\n"


#: 正在跑的流式出稿（run 令牌 → 停止事件）。停止键（契约 #21⑤）用；
#: 跑完/出错/停掉即从表里摘除——不在的令牌＝没有可停的。
_flex_stops: dict[str, threading.Event] = {}


@router.post("/api/periods/{period}/flexible/stream")
@user_route
async def api_period_flexible_stream(request: Request, period: str):
    """流式生成（契约 #21③）：一行一个事件 `status → plan → section×N → done/error/stopped`。

    事件发生在**真实节点**（规划完成、每节完成），不做假进度；
    前端用 `fetch` 逐行读取（后端不引 SSE 库，NDJSON 更省）。
    首行（status）带 `run` 令牌——停止键（#21⑤）拿它喊停。

    2026-10-12（rick 定案）：出报告对操作员开放——本口与 `/stop` 从 admin 放开
    （对话前门两段式的第一段；取数/回滚/润色等仍 admin）。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    intent = str(body.get("intent") or "").strip()
    disc = str(body.get("disc") or "").strip() or None
    peers = body.get("peers")
    if isinstance(peers, str):
        peers = peers.split(",")
    peers = [str(x).strip() for x in (peers or []) if str(x).strip()]
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}",
                             "hint": "可选：" + "、".join(flex_planner.INTENTS)}, status_code=400)
    import flexible.report as flex_report                           # noqa: PLC0415
    # 报告外观三轴：同同步口——带了才传，不认识的值静默回落，绝不 400。
    from monitor.appearance import appearance_from_body             # noqa: PLC0415
    appearance = appearance_from_body(body) or None

    token = uuid.uuid4().hex[:12]
    stop = threading.Event()
    _flex_stops[token] = stop

    def gen():
        try:
            first = True
            if appearance is None:
                evs = flex_report.generate_stream(d, intent, disc=disc,
                                                  should_stop=stop.is_set,
                                                  peers=peers)
            else:
                evs = flex_report.generate_stream(d, intent, disc=disc,
                                                  should_stop=stop.is_set,
                                                  peers=peers,
                                                  appearance=appearance)
            for ev in evs:
                line = _flex_stream_line(ev, d, intent)
                if first:                                # 首行带令牌（停止键要用）
                    rec = json.loads(line)
                    rec["run"] = token
                    line = json.dumps(rec, ensure_ascii=False) + "\n"
                    first = False
                yield line
        finally:
            _flex_stops.pop(token, None)

    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/api/periods/{period}/flexible/stop")
@user_route
async def api_period_flexible_stop(request: Request, period: str):   # noqa: ARG001
    """停止出稿（契约 #21⑤）：对正在流式生成的那一次喊停。

    下一次事件点收手，终态事件 `stopped` 从**原流**里送出（不落产物）；
    流已结束/令牌不在 → `{ok: false}` + 人话（不是错误）。
    2026-10-12：与 `/stream` 同档——操作员出报告要能停（rick 定案）。
    """
    body = await request.json()
    token = str(body.get("run") or "")
    ev = _flex_stops.get(token)
    if ev is None:
        return {"ok": False, "error": "这次出稿已经结束（或找不到），没有可停的。"}
    ev.set()
    return {"ok": True}


@router.post("/api/periods/{period}/flexible/polish")
@admin_route
async def api_period_flexible_polish(request: Request, period: str):
    """AI 润色（写作位，契约 #21④）：按已出稿的规划重出稿，只重写叙述段。

    数字、图表、来源链一律不变；任何段失败都保留规则稿。首次润色时把当前
    规则稿留底为 `report.rule.md`（界面可对照）。写作位没开或没配云 → 409。
    """
    d = resolve_period_dir(period)
    if d is None:
        return _period_missing()
    body = await request.json()
    intent = str(body.get("intent") or "").strip()
    import flexible.planner as flex_planner                         # noqa: PLC0415
    if intent not in flex_planner.INTENTS:
        return JSONResponse({"error": f"未知意图：{intent}"}, status_code=400)
    plan_path = d / "flexible" / intent / "flex_plan.json"
    if not plan_path.is_file():
        return JSONResponse({"error": "还没有这份稿，先「生成分析稿」再来润色。"},
                            status_code=400)
    from ai import _writing                                         # noqa: PLC0415
    if not _writing.writing_state("write").available:
        return JSONResponse({"error": "写作位未开启（部署开关未设或未配云端模型）。"},
                            status_code=409)
    import flexible.report as flex_report                           # noqa: PLC0415
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        plan = None
    t0 = time.time()
    # 润色只重写叙述段，外观要原样保留：从 flex_meta.json 读回生成时的
    # 三轴传下去（旧稿没记 → None，行为不变），免得润色把外观洗掉。
    appearance = _flex_appearance_from_meta(d, intent)
    try:
        if appearance is None:
            r = flex_report.generate(d, intent, plan=plan, write=True)
        else:
            r = flex_report.generate(d, intent, plan=plan, write=True,
                                     appearance=appearance)
    except Exception as e:                                           # noqa: BLE001
        return JSONResponse({"error": f"润色失败：{type(e).__name__}",
                             "hint": str(e)[:200]}, status_code=500)
    return {"ok": True, "intent": intent, "elapsed": round(time.time() - t0, 1),
            "mode": r.get("mode"), "write": r.get("write"),
            "backend": (r.get("plan") or {}).get("backend", "")}


def _panel_payload(period_end, schools, disciplines, n: int, with_grid: bool) -> dict:
    """跑 `flexible.panel()`，并按需摘掉 `grid`。

    `panel()` 返回的是**同一进程内**的结果（`_rows` 有 lru_cache），所以这里只做浅拷贝，
    绝不原地 pop——那会把缓存里的矩阵也削掉，下一次调用就少一块。
    """
    import flexible.panel as flex_panel                              # noqa: PLC0415
    result = flex_panel.panel(schools, disciplines=disciplines or None,
                              period_end=period_end, n=n)
    payload = dict(result)
    if not with_grid:
        payload.pop("grid", None)
    return payload


@router.get("/api/periods/{period}/panel-data")
@user_route
async def api_period_panel_data(request: Request, period: str, schools: str = "",   # noqa: ARG001
                                n: int = 6, disciplines: str = "", grid: bool = False):
    """多校面板（他校简报）的数据：`flexible.panel()` 的结果，**默认不带 `grid`**。

    `schools` 逗号分隔（顿号、分号、「和」也认——与 `peers._split_queries` 同一套）；
    `disciplines` 不传＝22 个学科全要；`period` 传 `latest` 取 ESI 目录里最新一期。
    `?grid=1` 才返回全量矩阵（期次 × 学校 × 学科）：它只给前端画图，不进模型上下文
    （`panel` 模块 docstring 的两层返回）。

    冷启动约 24 秒（132 次读表）；同一进程内后续调用走 `panel._rows` 的 lru_cache，
    实测 1 秒内。路由层**不**再叠一层缓存——两处缓存就有两处失效逻辑，收益不值。
    校名对不上时 `panel` 给的是 `status=absent/error` 的整校记录，不是异常；
    参数本身不合法（n<1、不认识的学科）才 400。
    """
    if period != "latest":
        d = resolve_period_dir(period)
        if d is None:
            return _period_missing()
    try:
        return await run_in_threadpool(
            _panel_payload, None if period == "latest" else period,
            schools, disciplines, n, grid)
    except ValueError as e:
        return JSONResponse({"error": str(e)[:300],
                             "hint": "校名/学科名请用 ESI 表里的写法，期次用 6 位月份"}, status_code=400)
