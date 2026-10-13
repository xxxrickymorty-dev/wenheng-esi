# -*- coding: utf-8 -*-
"""演示站**写路径**验收：真跑一次任务，验状态机是否接线成功。

用法（先起服务，再跑）：
    .venv\\Scripts\\python.exe tools\\verify_demo_run.py 202607

验的是 `server/e2e_check.py` **不覆盖**的那一段——那个只读验收不发起任务，
因此「发起 → running → 终态落盘 → 前端 badge 跟着变」这条链一直没有守卫。
本脚本补这条链：

  1. 新建任务初始状态是非终态（running）；
  2. 跑完落 `completed`（断言全绿）或 `warned`（有告警），**不是**旧的 done/warn；
  3. 终态被 `agent.states.is_terminal` 认出（页面才会停轮询、放出重跑按钮）；
  4. 任务页 badge 的类名与文案与 `agent.states` 逐字一致。

⚠️ 会真跑一遍流水线（约 15–30 秒）并覆盖 `out/<期次>/` 下的产物——
   这正是演示站「一键生成」按钮的行为，不要在需要保留当期产物时跑。
"""
import http.cookiejar
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8080"
WENHENG = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WENHENG / "src"))
from agent import states                                          # noqa: E402

PERIOD = sys.argv[1] if len(sys.argv) > 1 else "202607"

env = {}
p = WENHENG / "server" / ".env"
if p.exists():
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

fails = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with op.open(req) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get(path):
    try:
        with op.open(BASE + path) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


ADMIN_PASS = env.get("WENHENG_PASS") or os.environ.get("WENHENG_PASS", "")
if not ADMIN_PASS:
    print("未找到管理员口令：请在 server/.env 设置 WENHENG_PASS，或设环境变量后重跑。")
    raise SystemExit(2)
post("/login", {
    "username": env.get("WENHENG_USER") or os.environ.get("WENHENG_USER", "demo"),
    "password": ADMIN_PASS,
})

print(f"=== 1. 发起任务（{PERIOD}）===")
code, body = post("/api/jobs", {"period": PERIOD})
check("POST /api/jobs → 200", code == 200, f"got {code} {body[:120]}")
if code != 200:
    print("=" * 56)
    print(f"结果：{len(fails)} 项未过 → {fails}")
    raise SystemExit(1)
job_id = json.loads(body)["job_id"]
print(f"  任务号 {job_id}")

print("=== 2. 轮询到终态 ===")
statuses = []
final = None
t0 = time.time()
while time.time() - t0 < 180:
    time.sleep(1.0)
    c, b = get(f"/api/jobs/{job_id}")
    if c != 200:
        check("GET /api/jobs/<id> → 200", False, f"got {c}")
        break
    final = json.loads(b)
    s = final.get("status")
    if not statuses or statuses[-1] != s:
        statuses.append(s)
        print(f"  [{time.time() - t0:5.1f}s] 状态 = {s}（{states.label(s)}）")
    if states.is_terminal(s):
        break

print(f"  状态轨迹：{statuses}")
check("观察到非终态（说明先 running 再收尾）",
      any(not states.is_terminal(s) for s in statuses[:-1]) or statuses[0] != statuses[-1],
      f"{statuses}")
check("终态是 10 态里的合法状态名",
      bool(final) and final["status"] in states.STATES, str(final and final["status"]))
check("终态是 completed 或 warned（不是旧名 done/warn）",
      bool(final) and final["status"] in (states.COMPLETED, states.WARNED),
      str(final and final["status"]))
check("终态被 is_terminal 认出（页面会停轮询、放重跑按钮）",
      bool(final) and states.is_terminal(final["status"]))

print("=== 3. 新工作区在线（老站任务页已随 ADR-0002 下线）===")
# 旧站 /jobs/<id> 与 /run 已 302 到 React /app/，服务端渲染的 badge / 状态字典不复存在。
# 「状态话术与状态机同源」这条保证改由**跨栈 parity 测试**守：
#   tests/test_demo_station_states.py::test_前端话术与后端中文名逐字一致
#   （还有 前端十态/终态集合两条）
# 这里只验新工作区确实在线；任务数据链（发起→running→终态）由 1/2 段覆盖。
c, page = get("/app/")
check("GET /app/ → 200（新工作区在线）", c == 200, f"got {c}")

print("=" * 56)
print("结果：" + ("全部通过" if not fails else f"{len(fails)} 项未过 → {fails}"))
raise SystemExit(1 if fails else 0)
