"""8080 临时预览壳：把 /app 从 web/dist 摘下，反代到 frontend/ 的 Vite dev（5180）。

rick 2026-10-27 口谕：5180 工作区接入 8080，8080 的工作区先下架，看切换效果。
不动 server/app.py（旧站冻结，树上还有别的会话的未提交改动）——import 原 app 后
在内存里换路由。回滚：停掉本进程，照旧 `uvicorn server.app:app` 重启即恢复原样。

起法（两步，cwd 均为 wenheng/）：
  1) cd frontend && npm run dev -- --base=/app/      # Vite dev，5180
  2) uv run python -m uvicorn preview_5180:app --host 127.0.0.1 --port 8080

注意：旧 /app 挂载的 require_login 不在代理上（Vite 本来就无鉴权、仅 127.0.0.1 可达），
数据权限仍由 /api/* 的登录态把关；未登录看到的是新壳的未登录视图。
代理只走 HTTP，不带 WebSocket——HMR 已在 frontend/vite.config.ts 指向直连 5180。
"""
import urllib.error
import urllib.request

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse, Response

from server.app import app

VITE = "http://127.0.0.1:5180"

# 摘下旧工作区挂载（web/dist → /app，name="web"）
app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/app"]

# 逐跳头不转发；accept-encoding 也掐掉，让 Vite 回明文，免得解压对不上
_HOP_HEADERS = {
    "host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
    "content-length", "accept-encoding",
}
_DROP_RESP_HEADERS = {"connection", "transfer-encoding", "content-length", "content-encoding"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 3xx 原样透传，浏览器带着正确 Origin 自己再发


# 强制直连：urllib 默认读系统代理（梯子一开注册表 ProxyEnable 就翻true），
# 会把 127.0.0.1:5180 也发给代理 —— 代理端口活着就绕路、死了就 10061 拒连。
# localhost 永远不该走代理，ProxyHandler({}) = 一律直连。
_opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _fetch_vite(method, url, headers, body):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener.open(req, timeout=30) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:  # 4xx/5xx 同样透传
        return e.code, e.headers, e.read()


async def _proxy(request: Request) -> Response:
    target = VITE + request.url.path + ("?" + request.url.query if request.url.query else "")
    fwd = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
    body = await request.body()
    try:
        status, raw_headers, content = await run_in_threadpool(
            _fetch_vite, request.method, target, fwd, body or None)
    except urllib.error.URLError as e:
        return PlainTextResponse(
            f"[preview_5180] Vite dev 不可达（{e.reason}）。"
            "先在 frontend/ 下跑：npm run dev -- --base=/app/", status_code=502)
    out = {}
    for k, v in raw_headers.items():
        if k.lower() in _DROP_RESP_HEADERS:
            continue
        if k.lower() == "location" and v.startswith(VITE):
            v = v[len(VITE):] or "/"
        out[k] = v
    return Response(content, status_code=status, headers=out)


@app.api_route("/app", methods=["GET", "HEAD"], include_in_schema=False)
async def _proxy_app_root(request: Request):
    return await _proxy(request)


@app.api_route("/app/{p:path}",
               methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
               include_in_schema=False)
async def _proxy_app(request: Request, p: str):
    return await _proxy(request)
