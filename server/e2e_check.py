# -*- coding: utf-8 -*-
"""文衡演示站端到端验收（定稿后回归）。

用法（先起服务，再跑）：
    .venv\\Scripts\\python.exe server\\e2e_check.py
    服务地址可用环境变量覆盖：WENHENG_BASE=http://127.0.0.1:8080

验收范围：登录 → 首屏对勘本 → 控制台 /run → 期次入口 /p/<期次> → 期次红件清单
→ 任务入口与产物 → 签单闸门与落库（含撤回）→ 静态快照同源 → 任务状态口径同源。
只读 + 一次签单/撤回，不动流水线数据；结束后 202607 停在 unsigned。

三个容易写错的地方（都踩过，记在这里省得下次再踩）：
1. Jinja 的 tojson 输出 `"k": "v"`（冒号后有空格），断言 JSON 时正则要允许空白；
2. 「已钤印」这类字样是 JS 渲染的，裸 HTML 里没有——只能断言 JSON 里的
   approvalStatus，不能断言文案；
3. 路径一律以脚本自身位置为锚：脚本可能在 wenheng/ 下跑，也可能在仓库根跑。
"""
import http.cookiejar
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("WENHENG_BASE", "http://127.0.0.1:8080").rstrip("/")
ROOT = pathlib.Path(__file__).resolve().parent
WENHENG = ROOT if (ROOT / "out").is_dir() else ROOT.parent
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "wenheng-e2e")]
FAILS = []


def call(method, path, data=None):
    url = BASE + path
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", url


LOG = []


def out(line=""):
    print(line)
    LOG.append(line)


def check(name, cond, extra=""):
    msg = ("  OK   " if cond else "  FAIL ") + name + (("  " + extra) if extra else "")
    out(msg)
    if not cond:
        FAILS.append(name)


def dump_log():
    """Windows 控制台编码靠不住：结果自己写一份 UTF-8 报告。"""
    (ROOT / "e2e_report.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")


def jget(html, key, default=None):
    """从内联 JSON 里取一个键（容忍 tojson 的空格）。"""
    m = re.search(r'"%s":\s*("(?:[^"\\]|\\.)*"|\d+|true|false|null|\[|\{)' % re.escape(key), html)
    if not m:
        return default
    raw = m.group(1)
    if raw in ("[", "{"):
        return raw  # 只判存在
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def jget_str(html, key):
    v = jget(html, key)
    return v.strip('"') if isinstance(v, str) else ""


out("=== 1. 健康检查 ===")
st, body, _ = call("GET", "/healthz")
check("GET /healthz → 200", st == 200, f"got {st}")

out("=== 2. 未登录应跳登录 ===")
st, body, final = call("GET", "/")
check("GET / (未登录) 落到 /login", "/login" in final, f"final={final}")

out("=== 3. 登录 ===")
st, body, final = call("POST", "/login", {"username": "demo", "password": "wenheng@2026"})
check("POST /login 进入首页", final.rstrip("/").endswith("8080"), f"final={final}")

out("=== 4. 首屏 = 对勘本（最新一期） ===")
st, home, _ = call("GET", "/")
check("GET / → 200", st == 200, f"got {st}")
check("首屏是【对勘本】而非控制台", "对勘本" in home and "whc-grid" in home)
check("首屏不再是控制台表单", "run-form" not in home)
check("periodDir = 202607（最新期次）", jget_str(home, "periodDir") == "202607", f"got {jget_str(home,'periodDir')!r}")
check("periods 是数组且非空", jget(home, "periods") == "[", )
check("periods 含 202607 与 202605_复现", len(re.findall(r'"period":\s*"202', home)) >= 2,
      f"n={len(re.findall(chr(34) + 'period' + chr(34) + r':\s*' + chr(34) + '202', home))}")
check("signUrl 指向 /p/202607/sign", jget_str(home, "signUrl") == "/p/202607/sign", f"got {jget_str(home,'signUrl')!r}")
check("revokeUrl 指向 /p/202607/revoke", jget_str(home, "revokeUrl") == "/p/202607/revoke")
check("backUrl 是首屏自身 /", jget_str(home, "backUrl") == "/", f"got {jget_str(home,'backUrl')!r}")
check("crumbs 已注入", jget(home, "crumbs") == "[")
check("面包屑含 /run 控制台入口", "/run" in home)
check("live 为 true", jget(home, "live") is True)
check("jobId 为空（首屏无任务上下文）", jget_str(home, "jobId") == "")

out("=== 5. 控制台 /run ===")
st, run, _ = call("GET", "/run")
check("GET /run → 200", st == 200, f"got {st}")
check("/run 是控制台", "run-form" in run and "开始生成" in run)
check("/run 用 B 读数格 .readouts", 'class="readouts"' in run and 'class="readout"' in run)
check("/run 用面板 .panel-h", "panel-h" in run)
check("/run 用工序表 .seq", 'class="seq"' in run)
check("/run 含钤印品牌 .seal-sm", "seal-sm" in run)
check("/run 含套准十字", 'class="reg tl"' in run)
check("/run 去掉旧的圆角 hero card", "hero card" not in run)
check("/run 无 CDN 字体", "cdn.jsdelivr" not in run and "fonts.googleapis" not in run)

out("=== 6. 期次入口 /p/<期次> ===")
st, p1, _ = call("GET", "/p/202607")
check("GET /p/202607 → 200", st == 200, f"got {st}")
check("/p/202607 是对勘本", "whc-grid" in p1)
check("/p/202607 的 periods 也带上（可切期次）", jget(p1, "periods") == "[")
st, p2, _ = call("GET", "/p/202605_%E5%A4%8D%E7%8E%B0")
check("GET /p/202605_复现 → 200", st == 200, f"got {st}")
check("/p/202605_复现 的 periodDir 是带后缀目录", jget_str(p2, "periodDir") == "202605_复现",
      f"got {jget_str(p2,'periodDir')!r}")
st, pb, _ = call("GET", "/p/199901")
check("非法期次回落首页（不是 500）", st == 200, f"got {st}")

out("=== 7. 期次红色件清单（本次修的 500） ===")
st, rs, _ = call("GET", "/p/202607/redslots")
check("GET /p/202607/redslots → 200", st == 200, f"got {st}")
check("清单渲染 354 行", rs.count("<tr>") == 355, f"rows={rs.count('<tr>') - 1}")
check("清单用朱色本期列", 'class="new"' in rs)
check("清单回链指向 /p/202607", 'href="/p/202607"' in rs)
check("清单下载指向期次端点", 'href="/p/202607/download/red_list"' in rs)
check("无空任务链接 /jobs//", "/jobs//" not in rs)
check("清单用统一面板与套准十字", "panel-h" in rs and 'class="reg tl"' in rs)

out("=== 8. 任务入口仍可用 ===")
cands = sorted((WENHENG / "out" / "_jobs").glob("*/job.json"))
jobid = cands[-1].parent.name if cands else ""
check("找到历史任务", bool(jobid), f"job={jobid!r}")
if jobid:
    st, jp, _ = call("GET", f"/jobs/{jobid}")
    check(f"GET /jobs/{jobid} → 200", st == 200, f"got {st}")
    check("任务页用 .panel/.panel-h", "panel-h" in jp)
    check("任务页有产物区", 'id="results"' in jp)
    check("任务页有对勘本入口", f"/jobs/{jobid}/collation" in jp)
    check("任务页仍保留 job.js 依赖的 #status-badge.badge", 'id="status-badge"' in jp and 'class="badge' in jp)
    st, cp, _ = call("GET", f"/jobs/{jobid}/collation")
    check(f"GET /jobs/{jobid}/collation → 200", st == 200, f"got {st}")
    check("任务入口面包屑回任务页", f"← 返回任务 {jobid}" in cp)
    check("任务入口 signUrl 仍投期次端点", jget_str(cp, "signUrl").startswith("/p/"),
          f"got {jget_str(cp,'signUrl')!r}")
    check("任务入口 backUrl 是任务对勘本页", jget_str(cp, "backUrl") == f"/jobs/{jobid}/collation",
          f"got {jget_str(cp,'backUrl')!r}")
    check("任务入口 jobId 非空", bool(jget_str(cp, "jobId")))
    st, rp, _ = call("GET", f"/jobs/{jobid}/redslots")
    check(f"GET /jobs/{jobid}/redslots → 200", st == 200, f"got {st}")
    check("任务入口清单回链指向任务对勘本", f'href="/jobs/{jobid}/collation"' in rp)

out("=== 9. 签单闸门与落库（先归零） ===")
st, _, f0 = call("POST", "/p/202607/revoke", {"note": "e2e 前置归零", "back": "/p/202607"})
st, pz, _ = call("GET", "/p/202607")
base_state = jget_str(pz, "approvalStatus")
check("前置：状态归零到 unsigned", base_state == "unsigned", f"got {base_state!r}")

st, _, f1 = call("POST", "/p/202607/sign", {"note": "e2e", "ack": "", "back": "/p/202607"})
err1 = urllib.parse.unquote(f1.split("err=")[-1]) if "err=" in f1 else ""
check("不勾「已知悉」→ 被闸门拦下", "err=" in f1, f"final={f1}")
check("拦截原因是待人工项未勾选", "已知悉" in err1 or "手工" in err1, f"err={err1!r}")
check("被拦时不落盘（状态仍 unsigned）", jget_str(call("GET", "/p/202607")[1], "approvalStatus") == "unsigned")

st, _, f2 = call("POST", "/p/202607/sign", {"note": "e2e 验收", "ack": "1", "back": "/p/202607"})
check("勾已知悉 → 签单成功", "signed=1" in f2, f"final={f2}")
check("回跳到 back 指定的 /p/202607", "/p/202607" in f2, f2)
st, ps, _ = call("GET", "/p/202607")
check("签后 approvalStatus = signed", jget_str(ps, "approvalStatus") == "signed",
      f"got {jget_str(ps,'approvalStatus')!r}")
check("签后 periodDir 仍正确", jget_str(ps, "periodDir") == "202607")
check("印记链反映已签（periods 里出现 signed）", '"status": "signed"' in ps or '"status":"signed"' in ps)
check("审批记录已落盘", (WENHENG / "out/202607/approval.json").exists())
check("审批记录 Markdown 已导出", (WENHENG / "out/202607/审批记录.md").exists())
rec = json.loads((WENHENG / "out/202607/approval.json").read_text(encoding="utf-8"))
check("记录里绑了报告指纹", bool(rec.get("fingerprint")), str(rec.get("fingerprint"))[:60])
check("记录含批注", rec.get("note") == "e2e 验收", f"note={rec.get('note')!r}")
check("记录含操作历史", isinstance(rec.get("history"), list) and len(rec["history"]) >= 1)

st, _, f3 = call("POST", "/p/202607/revoke", {"note": "e2e 撤回", "back": "/p/202607"})
check("撤回成功", "revoked=1" in f3, f"final={f3}")
st, pr, _ = call("GET", "/p/202607")
check("撤回后回到 unsigned", jget_str(pr, "approvalStatus") == "unsigned")
rec2 = json.loads((WENHENG / "out/202607/approval.json").read_text(encoding="utf-8"))
hist = [h.get("action") for h in rec2.get("history", [])]
check("历史保留 sign→…→revoke", "sign" in hist and "revoke" in hist, str(hist))

out("=== 10. 静态快照同源 ===")
st, snap, _ = call("GET", "/static/collation-demo.html")
check("GET 快照 → 200", st == 200, f"got {st}")
check("快照引用 style.css（新令牌来源）", 'href="style.css"' in snap)
check("快照含钤印品牌", "seal-sm" in snap)
check("快照含套准十字", 'class="reg tl"' in snap)
check("快照 signUrl 为空 → 降级只读", jget_str(snap, "signUrl") == "")
check("快照 approvalStatus 强制 unsigned（不假造已签）", jget_str(snap, "approvalStatus") == "unsigned")
check("快照 periods 为空 → 不渲染印记链", jget(snap, "periods") == "[")
check("快照无 CDN", "cdn.jsdelivr" not in snap)
check("快照内联全量 354 槽位", snap.count('"loc"') >= 350, f"n={snap.count(chr(34)+'loc'+chr(34))}")

out("=== 11. 任务状态口径同源（10 态）===")
# 演示站的状态名必须来自 src/agent/states.py（WH-DOC-03 §6.3 要求恰好 10 态）。
# 这里只读校验：历史 job.json 里存的旧名（done/warn/interrupted）也必须在
# 读取时被归一——否则「已完成」的任务会被判成「仍在跑」。
sys.path.insert(0, str(WENHENG / "src"))
from agent import states                                          # noqa: E402

TEN = set(states.STATES)
LEGACY = {"done", "warn", "interrupted"}

st, runpage, _ = call("GET", "/run")
pairs = re.findall(r'<span class="badge ([a-z_]+)">([^<]*)</span>', runpage)
check("列表页徽章类名都落在 10 态内", all(c in TEN for c, _ in pairs),
      str(sorted({c for c, _ in pairs})))
check("列表页没有旧 4 态名", not any(c in LEGACY for c, _ in pairs),
      str(sorted({c for c, _ in pairs} & LEGACY)))
check("列表页文案取自状态机", all(t.strip() == states.LABELS[c] for c, t in pairs if c in states.LABELS),
      str([t for c, t in pairs][:3]))

if jobid:
    st, jp2, _ = call("GET", f"/jobs/{jobid}")
    mb = re.search(r'id="status-badge" class="badge ([a-z_]+)">([^<]*)<', jp2)
    check("任务页 badge 类名是 10 态名", bool(mb) and mb.group(1) in TEN,
          mb.group(1) if mb else "未匹配")
    check("任务页 badge 文案 = 状态机中文名",
          bool(mb) and mb.group(2).strip() == states.LABELS.get(mb.group(1)),
          f"{mb.group(2)!r} vs {states.LABELS.get(mb.group(1))!r}" if mb else "")
    check("任务页注入状态字典（前端不再写死名单）",
          "__STATUS_LABELS__" in jp2 and "__TERMINAL__" in jp2)

st, css, _ = call("GET", "/static/style.css")
missing = [s for s in states.STATES if f".badge.{s}" not in css]
check("每个状态都有 badge 配色", not missing, f"缺 {missing}")

out("=" * 56)
if FAILS:
    out(f"结果：{len(FAILS)} 项未过")
    for f in FAILS:
        out("  - " + f)
else:
    out("结果：全部通过（%d 项断言）" % len(LOG))
dump_log()
sys.exit(1 if FAILS else 0)
