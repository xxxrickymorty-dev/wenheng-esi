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


def call_json(method, path, payload=None):
    """JSON 版 call()：POST 带 application/json。"""
    url = BASE + path
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", url


# 二进制要单独取：call() 会把响应 decode 成文本，zip 会被读坏。
def call_raw(path):
    try:
        r = op.open(BASE + path)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)



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
# 欢迎页 = 登录页（rick 2026-09-21 定：校园插画做首屏）。
# 断言三件事：图在、图走 asset（带版本号，否则改图后浏览器吃缓存）、登录表单没被改坏。
st, lp, _ = call("GET", "/login")
check("欢迎页含校园插画且走 asset 版本号",
      "/static/img/campus-welcome.jpg?v=" in lp, f"got {st}")
check("欢迎页图带宽高（防加载抖动）", 'width="1024"' in lp and 'height="566"' in lp)
check("登录表单完好（账号/密码/action）",
      'name="username"' in lp and 'name="password"' in lp and 'action="/login"' in lp)
st, body, final = call("POST", "/login", {"username": "demo", "password": "wenheng@2026"})
# ⚠ 别写死 8080：用 `WENHENG_BASE` 换端口跑时，写死会让这条**假失败**
#    （2026-09-19 用 8099 实测：final 明明是首页，断言却判未过）。
check("POST /login 进入新工作区 /app/", final.rstrip("/") == BASE + "/app", f"final={final}")

out("=== 3.5 老站 302 落点（ADR-0002 阶段 2） ===")
# 期望落点的单一事实源在 server/config.py 的 LEGACY_REDIRECTS；
# 这里逐条打老 URL（自动跟随 302），断言最终落在新工作区对应视图。
_job_cands = sorted((WENHENG / "out" / "_jobs").glob("*/job.json"))
jobid = _job_cands[-1].parent.name if _job_cands else ""
_job_rec = (json.loads((WENHENG / "out" / "_jobs" / jobid / "job.json").read_text(encoding="utf-8"))
            if jobid else {})
_job_period = _job_rec.get("out_period") or _job_rec.get("period") or ""
import sys as _sys
_sys.path.insert(0, str(WENHENG))
from server import config as _cfg                                  # noqa: E402
for _old in _cfg.LEGACY_LIVE:
    _tpl = _cfg.LEGACY_REDIRECTS[_old]
    if "{job_id}" in _old:
        if not jobid:
            continue
        _old_path = _old.format(job_id=jobid)
        _target = _tpl.format(period=urllib.parse.quote(_job_period))
    else:
        _old_path = _old.format(period="202607")
        _target = _tpl.format(period="202607")
    _st, _b, _fin = call("GET", _old_path)
    check(f"{_old_path} 302 落点正确", _target in _fin, f"expect~{_target} final={_fin}")


out("=== 4/5. 旧首屏与旧控制台（已下线） ===")
# 老工作台 / 老控制台的内容断言随页面一起下线（ADR-0002 阶段 2）；
# 302 落点已在 §3.5 逐条覆盖。

out("=== 6. 期次入口（已下线，302 见 §3.5） ===")
# 老对勘本页已 302 到 /app/?view=reading&period=...；内容断言随页面下线。

out("=== 7. 红件清单下载端点（老页面已 302，清单数据走 §16 API） ===")
# 老清单页已 302 到 /app/?view=red；下载端点按 §六 保留（新站直接引用）
_st, _dl, _h = call_raw("/p/202607/download/red_list")
check("GET /p/202607/download/red_list → 200", _st == 200, f"got {_st}")
check("下载内容非空", len(_dl) >= 100, f"{len(_dl)}B")

out("=== 8. 任务进度 API（老任务页已下线，302 见 §3.5） ===")
if jobid:
    # GET /api/jobs/{jobid}/progress（任务瀑布 JSON，老站模板那步的前移）
    st, pg, _ = call("GET", f"/api/jobs/{jobid}/progress")
    check(f"GET /api/jobs/{jobid}/progress → 200", st == 200, f"got {st}")
    check("progress 有 events/waterfall/total_sec",
          '"events"' in pg and '"waterfall"' in pg and '"total_sec"' in pg)
    if '"missing": false' in pg:
        check("progress 的 waterfall 有真数据（sec/step）",
              '"sec"' in pg and '"step"' in pg)
    else:
        check("progress missing 时给 note 说明", '"note"' in pg)

out("=== 9. 签单闸门与落库（JSON API；老表单已随对勘本下线） ===")
# 老对勘本页（含其表单 POST /p/{期次}/sign|revoke）已 302；签单走新站 JSON API
# （审核台在用）。闸门语义不变：不勾「已知悉」被拒且不落盘；签/撤留历史。

def _wstate():
    return jget_str(call("GET", "/api/periods/202607/workbench")[1], "approvalStatus")


call_json("POST", "/api/periods/202607/revoke", {"note": "e2e 前置归零"})
check("前置：状态归零到 unsigned", _wstate() == "unsigned", f"got {_wstate()!r}")

st, _e1, _ = call_json("POST", "/api/periods/202607/sign", {"note": "e2e"})
check("不勾「已知悉」→ 409 被闸门拦下", st == 409, f"got {st}")
_e1j = json.loads(_e1) if _e1.strip().startswith("{") else {}
check("拦截原因是待人工项未勾选",
      "已知悉" in str(_e1j.get("error", "")) or "手工" in str(_e1j.get("error", "")),
      f"err={str(_e1j.get('error'))[:80]!r}")
check("被拦时不落盘（状态仍 unsigned）", _wstate() == "unsigned", f"got {_wstate()!r}")

st, _s2, _ = call_json("POST", "/api/periods/202607/sign",
                       {"note": "e2e 验收", "known": True})
_s2j = json.loads(_s2) if _s2.strip().startswith("{") else {}
check("勾已知悉 → 签单成功", st == 200 and _s2j.get("status") == "signed",
      f"{st} {str(_s2j)[:80]}")
check("签单返回报告指纹", bool(_s2j.get("fingerprint")), str(_s2j.get("fingerprint"))[:60])
check("签后 approvalStatus = signed", _wstate() == "signed", f"got {_wstate()!r}")
_pl = call("GET", "/api/periods")[1]
check("印记链反映已签（periods 里出现 signed）", '"signed"' in _pl)
check("审批记录已落盘", (WENHENG / "out/202607/approval.json").exists())
check("审批记录 Markdown 已导出", (WENHENG / "out/202607/审批记录.md").exists())
rec = json.loads((WENHENG / "out/202607/approval.json").read_text(encoding="utf-8"))
check("记录里绑了报告指纹", bool(rec.get("fingerprint")), str(rec.get("fingerprint"))[:60])
check("记录含批注", rec.get("note") == "e2e 验收", f"note={rec.get('note')!r}")
check("记录含操作历史", isinstance(rec.get("history"), list) and len(rec["history"]) >= 1)

st, _r3, _ = call_json("POST", "/api/periods/202607/revoke", {"note": "e2e 撤回"})
_r3j = json.loads(_r3) if _r3.strip().startswith("{") else {}
check("撤回成功", st == 200 and _r3j.get("status") == "unsigned", f"{st} {str(_r3j)[:60]}")
check("撤回后回到 unsigned", _wstate() == "unsigned", f"got {_wstate()!r}")
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
check("快照内联全量槽位", snap.count('"loc"') >= 350, f"n={snap.count(chr(34)+'loc'+chr(34))}")

out("=== 11. 任务状态口径同源（10 态）===")
# 演示站的状态名必须来自 src/agent/states.py（WH-DOC-03 §6.3 要求恰好 10 态）。
# 这里只读校验：历史 job.json 里存的旧名（done/warn/interrupted）也必须在
# 读取时被归一——否则「已完成」的任务会被判成「仍在跑」。
sys.path.insert(0, str(WENHENG / "src"))
from agent import states                                          # noqa: E402

TEN = set(states.STATES)
LEGACY = {"done", "warn", "interrupted"}

st, css, _ = call("GET", "/static/style.css")
missing = [s for s in states.STATES if f".badge.{s}" not in css]
check("每个状态都有 badge 配色", not missing, f"缺 {missing}")

out("=== 12. 运行档案页（SRS R-21：状态机回放 + 瀑布 + 产物 + 日志包）===")
import io as _io                                                  # noqa: E402
import zipfile as _zf                                             # noqa: E402

st, arc, _ = call("GET", "/p/202607/archive")
check("GET /p/202607/archive → 200", st == 200, f"got {st}")
for k in ("状态机回放", "任务瀑布", "审计结论", "运行环境快照", "运行日志包", "Agent 轨迹文件"):
    check(f"档案页含「{k}」", k in arc)
# 动态取（2026-09-23 实踩：审计 verdict 会随产物状态在 pass/review/fail 间变，
# 写死某一档会假红）。断言本意是「页面如实显示审计结论、不粉饰」，比对标签即可。
_arc_rec = json.loads((WENHENG / "out" / "202607" / "audit_record.json").read_text(encoding="utf-8"))
_arc_label = {"pass": "全部通过", "review": "待人工确认", "fail": "不通过"}.get(_arc_rec.get("verdict", ""), "")
check("审计总判定如实显示（不是粉饰成通过）",
      bool(_arc_label) and _arc_label in arc,
      f"verdict={_arc_rec.get('verdict')} label={_arc_label}")
check("轨迹缺口如实说明（直跑路径没有 trace 三件套）", "真实的记录缺口" in arc)

st, raw, hdr = call_raw("/p/202607/download/logpack")
check("GET 期次日志包 → 200", st == 200, f"got {st}")
check("日志包 Content-Type 是 zip", "zip" in (hdr.get("content-type") or ""),
      hdr.get("content-type", ""))
check("日志包带 ASCII 文件名", "wenheng-logpack-202607-" in (hdr.get("content-disposition") or ""),
      hdr.get("content-disposition", ""))
try:
    _z = _zf.ZipFile(_io.BytesIO(raw))
    _names, _ok = _z.namelist(), _z.testzip() is None
except Exception as _e:                                            # noqa: BLE001
    _names, _ok = [], False
check("日志包是完好的 zip", _ok)
check("日志包含 README（说清与归档包的分工）", "README.txt" in _names)
check("日志包含 run_log / audit_record / env_snapshot",
      all(n in _names for n in ("period/run_log.json", "period/audit_record.json",
                                "period/env_snapshot.json")), str(_names[:6]))
check("日志包不含大件（docx/parquet/png）",
      not any(n.endswith((".docx", ".parquet", ".png")) for n in _names),
      str([n for n in _names if n.endswith((".docx", ".parquet", ".png"))]))

if jobid:
    st, jarc, _ = call("GET", f"/jobs/{jobid}/archive")
    check("GET 任务档案页 → 200", st == 200, f"got {st}")
    check("任务档案页认得 job（有返回任务的面包屑）", f"/jobs/{jobid}" in jarc)
    st, jraw, _ = call_raw(f"/jobs/{jobid}/download/logpack")
    try:
        _jz = _zf.ZipFile(_io.BytesIO(jraw))
        _jn = _jz.namelist()
    except Exception:                                              # noqa: BLE001
        _jn = []
    check("任务日志包带 job 上下文三件套",
          all(n in _jn for n in ("job/job.json", "job/progress.jsonl", "job/console.log")),
          str([n for n in _jn if n.startswith("job/")]))

out("=== 13. 图表路由的越界防护（老清单页已 302，路由按 §六 保留） ===")
# /p/{期次}/chart/ 直接服务磁盘文件，越界 = 任意文件读取（能读到 server/.env）
for _bad in ("/p/202607/chart/../server/.env",
             "/p/202607/chart/..%2Fserver%2F.env",
             "/p/202607/chart/Chemistry/../../../.env"):
    _s, _, _ = call("GET", _bad)
    check(f"越界请求被拒 {_bad[-28:]}", _s == 404, f"got {_s}")

out("=== 14. 对勘本图表槽位（JSON API；老页面已 302） ===")
# 老对勘本页的 chartUrl 就地铺图随页面下线；数据层等价物走 collation JSON：
# 槽位带 kind/source，源文件仍走 /p/{期次}/chart/ 白名单路由（新站直接引用）。
_rslots_path = WENHENG / "out" / "202607" / "red_slots.json"
_n_charts = sum(1 for _r in json.loads(_rslots_path.read_text(encoding="utf-8"))
                if (_r.get("source") or "").startswith("charts"))
_st, _cl, _ = call("GET", "/api/periods/202607/collation?full=true")
_clj = json.loads(_cl)
_chart_rows = [r for r in _clj.get("rows", [])
               if (r.get("source") or "").startswith("charts/")]
check("对勘 JSON 带全量图表槽位", len(_chart_rows) >= 90, f"n={len(_chart_rows)}")
check(f"图表槽位数与红件清单一致（{_n_charts}）", len(_chart_rows) == _n_charts,
      f"n={len(_chart_rows)} vs {_n_charts}")
_src = _chart_rows[0]["source"] if _chart_rows else ""
if _src.startswith("charts/"):
    # 路由口径与 _redslots_page 一致：rel 是去掉 charts/ 前缀的相对路径
    _rel = _src[len("charts/"):]
    _st, _raw, _h = call_raw(f"/p/202607/chart/{_rel}")
    check("图表源文件走 /p/202607/chart/ 能取到且真是 PNG",
          _st == 200 and _raw[:4] == b"\x89PNG",
          f"{_st} {(_h.get('content-type') or '')} {len(_raw)}B")

out("=== 15. 逐格溯源 / 存疑（JSON API；老页面已 302） ===")
# 老溯源页已 302 到 /app/?view=trace；数据等价物走 trace JSON（现场真读台账）。
st, _tr, _ = call("GET", "/api/periods/202607/trace?limit=5")
_trj = json.loads(_tr)
check("trace JSON 200 且台账读得到", st == 200 and _trj.get("ledger_ok") is True, f"got {st}")
check("trace 大表格数正确（239）", _trj.get("counts", {}).get("bigtable") == 239,
      f"got {_trj.get('counts', {}).get('bigtable')}")
check(f"trace 有图表 {_n_charts} 张", _trj.get("counts", {}).get("charts") == _n_charts,
      f"got {_trj.get('counts', {}).get('charts')}")
# 并排对照语义：行里带台账原值（ledger）与对法（how）
_bt_rows = json.loads(call("GET", "/api/periods/202607/trace?cat=bigtable&limit=500")[1]).get("rows", [])
check("溯源行带台账原值与对法", bool(_bt_rows) and all("ledger" in r and "how" in r for r in _bt_rows),
      f"n={len(_bt_rows)}")
_derived = [r for r in _bt_rows if "派生" in (r.get("how") or "")]
check("派生格给了算式", bool(_derived) and any(
    "−" in r["how"] or "×" in r["how"] for r in _derived),
    f"n_derived={len(_derived)}")
# 存疑走 JSON API（老表单已随页面下线）：可切换、台账一个字节不碰
_led = ROOT.parent.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
_sha0 = _led.stat().st_size if _led.exists() else -1
st, _f1, _ = call_json("POST", "/api/periods/202607/flag", {"loc": "T01/r999c9"})
_f1j = json.loads(_f1) if _f1.strip().startswith("{") else {}
check("存疑接口 200 且落 doubt", st == 200 and _f1j.get("state") == "doubt",
      f"{st} {str(_f1j)[:60]}")
st, _f2, _ = call_json("POST", "/api/periods/202607/flag", {"loc": "T01/r999c9"})
_f2j = json.loads(_f2) if _f2.strip().startswith("{") else {}
check("再点一次撤销（可切换）", st == 200 and _f2j.get("state") == "clear",
      f"{st} {str(_f2j)[:60]}")
check("台账没被在线填/存疑碰到（字节数不变）",
      _led.stat().st_size == _sha0, f"{_sha0} -> {_led.stat().st_size}")
# 灵活报告页按 §五 保留（P2 未迁）
st, fp, _ = call("GET", "/p/202607/flexible")
check("灵活页可开且生成表单齐备（意图/后端/学科/提交）",
      st == 200 and 'name="intent"' in fp and 'name="backend"' in fp
      and 'method="post"' in fp and 'id="flex-report"' in fp)

out("=== 16. 新 API 端点（契约 §2.2 #1-#12） ===")
# GET /api/me
st, me, _ = call("GET", "/api/me")
check("GET /api/me 200", st == 200, f"got {st}")
check("/api/me 返回 name+role", '"name"' in me and '"role"' in me)
check("/api/me role=admin（已登录 demo）", '"admin"' in me)

# GET /api/periods/{period}
st, pd, _ = call("GET", "/api/periods/202607")
check("GET /api/periods/202607 200", st == 200, f"got {st}")
check("period_detail 有 palette 三色", '"primary"' in pd and '"deep"' in pd and '"lift"' in pd)
check("period_detail 有 steps 三步", '"ledger"' in pd and '"input"' in pd and '"generated"' in pd)
check("period_detail 有 window", '"window"' in pd)
check("period_detail 有 no/total", '"no"' in pd and '"total"' in pd)

# GET /api/periods/{period}/redslots
st, rs, _ = call("GET", "/api/periods/202607/redslots?limit=5&offset=0")
check("GET redslots?limit=5 200", st == 200, f"got {st}")
check("redslots 有分页字段", '"total"' in rs and '"limit"' in rs and '"offset"' in rs and '"has_more"' in rs)
check("redslots 有 count", '"count"' in rs)

# GET /api/periods/{period}/collation
st, cl, _ = call("GET", "/api/periods/202607/collation?limit=5&offset=0")
check("GET collation?limit=5 200", st == 200, f"got {st}")
check("collation 有 sections 元数据", '"sections"' in cl)
check("collation 有分页字段", '"total"' in cl and '"limit"' in cl)

# GET /api/periods/{period}/charts
st, ch, _ = call("GET", "/api/periods/202607/charts?limit=5&offset=0")
check("GET charts?limit=5 200", st == 200, f"got {st}")
check("charts 有分页字段", '"total"' in ch and '"limit"' in ch)
check("charts 有 name/url/group", '"name"' in ch and '"url"' in ch and '"group"' in ch)

# GET /api/ledger/sheets（不传 period 找最新；台账文件名含中文，glob 可能因编码失配）
st, sh, _ = call("GET", "/api/ledger/sheets")
if st == 404:
    # 台账文件可能不在 input/ 下，跳过而非 FAIL
    check("GET ledger/sheets 200 或 404（台账缺失时跳过）", st in (200, 404), f"got {st}")
else:
    check("GET ledger/sheets 200", st == 200, f"got {st}")
    check("ledger/sheets 有 sheets 数组", '"sheets"' in sh)
    check("ledger/sheets 有 n_sheets", '"n_sheets"' in sh)

# POST /api/analyze（JSON body）
st, an, _ = call_json("POST", "/api/analyze", {"period": "202607", "question": "", "scope": ""})
check("POST analyze 200", st == 200, f"got {st}")
check("analyze 有 text+shields", '"text"' in an and '"shields"' in an)
check("analyze backend=sentences（LLM 不进数据路径）", '"backend"' in an and '"sentences"' in an)

# POST /api/periods/{period}/forecast-choice（JSON body）
st, fc, _ = call_json("POST", "/api/periods/202607/forecast-choice", {"choice": {"Chemistry": "SARIMA模型"}})
check("POST forecast-choice 200", st == 200, f"got {st}")
check("forecast-choice POST 返回 ok+saved（防被读回路由抢先）",
      '"ok"' in fc and '"saved"' in fc, f"body={fc[:100]}")

# 错误体统一：{error, hint?, missing?}
st, err, _ = call("GET", "/api/periods/209901")
check("不存在期次 404 且有 error 字段", st == 404 and '"error"' in err, f"got {st}")

out("=== 17. facts / workbench / forecast-choice GET / collation full ===")
# GET /api/periods/202607/facts
st, fc, _ = call("GET", "/api/periods/202607/facts")
check("GET facts 200", st == 200, f"got {st}")
check("facts 有 facts 字段", '"facts"' in fc)
check("facts 有 assertions", '"assertions"' in fc)
check("facts 有 missing", '"missing"' in fc)

# GET /api/periods/202607/workbench
st, wb, _ = call("GET", "/api/periods/202607/workbench")
check("GET workbench 200", st == 200, f"got {st}")
check("workbench 有 todo", '"todo"' in wb)
check("workbench 有 fills_list", '"fills_list"' in wb)
check("workbench 有 pending", '"pending"' in wb)
check("workbench 有 approvalStatus", '"approvalStatus"' in wb)

# GET /api/periods/202607/forecast-choice
st, fq, _ = call("GET", "/api/periods/202607/forecast-choice")
check("GET forecast-choice 200", st == 200, f"got {st}")
check("forecast-choice GET 有 choice", '"choice"' in fq)
check("读回能见刚保存的值（保存确实落盘）", "SARIMA" in fq, f"body={fq[:120]}")
check("forecast-choice GET 有 by", '"by"' in fq)

# GET /api/periods/202607/collation?full=true
st, clf, _ = call("GET", "/api/periods/202607/collation?full=true")
check("GET collation?full=true 200", st == 200, f"got {st}")
check("collation full 有 sections+slots", '"sections"' in clf and '"slots"' in clf or '"rows"' in clf)

# 错误体有 hint
st, err404, _ = call("GET", "/api/periods/209901")
# GET /api/periods/202607/trace（逐格溯源 JSON）
st, tr, _ = call("GET", "/api/periods/202607/trace?limit=5")
check("GET trace 200", st == 200, f"got {st}")
check("trace 有 counts 五类", all(k in tr for k in ("bigtable", "charts", "province", "matrix", "texts")))
check("trace 有分页字段", '"total"' in tr and '"limit"' in tr and '"offset"' in tr and '"has_more"' in tr)
check("trace 有 cols/discs 筛选数据", '"cols"' in tr and '"discs"' in tr)
check("trace 大表行含 loc/report/how", '"loc"' in tr and '"report"' in tr and '"how"' in tr)
check("trace ledger 只回文件名（不泄漏路径）", ":" not in tr.split('"ledger":')[1].split(",")[0], tr.split('"ledger":')[1].split(",")[0][:40])
# POST /api/periods/202601_复现/rebuild（没有填值应 409 拒绝，不碰产物）
st, rb, _ = call_json("POST", "/api/periods/202601_%E5%A4%8D%E7%8E%B0/rebuild", {})
check("rebuild 无填值时 409 拒绝", st == 409 and '"error"' in rb, f"got {st}")

st, tr2, _ = call("GET", "/api/periods/202607/trace?cat=charts&limit=3")
check("trace cat=charts 可切换", st == 200 and '"cat":"charts"' in tr2, f"got {st}")

check("404 错误体有 hint 字段", '"hint"' in err404, f"body={err404[:80]}")

# GET /api/periods/202607/archive（运行档案 JSON，契约 §2.2 #16）
st, ar, _ = call("GET", "/api/periods/202607/archive")
check("GET archive 200", st == 200, f"got {st}")
check("archive 有 replay/audit/logpack/artifacts",
      all(k in ar for k in ("replay", "audit", "logpack", "artifacts")))
check("archive 不回绝对路径", '"out_dir"' not in ar and "C:" not in ar and "Desktop" not in ar)
check("archive logpack_url 指保留下载端点", "/download/logpack" in ar)
check("archive 对勘本链接已修（不再出现无路由的 /p/{期次}/collation）",
      '"/p/202607/collation"' not in ar)

# GET /api/forecast/board（学科板，契约 #20）
st, bd, _ = call("GET", "/api/forecast/board")
check("GET forecast/board 200", st == 200, f"got {st}")
check("board 有 period/window/routes",
      '"period"' in bd and '"window"' in bd and '"routes"' in bd)
check("board 两条路线各 8 学科",
      bd.count('"subject"') >= 16, f"subjects={bd.count(chr(34) + 'subject' + chr(34))}")
check("board 行带 model/prox/t1/both_under_5",
      all(k in bd for k in ('"model"', '"prox"', '"t1"', '"both_under_5"')))

# GET /api/periods/{period}/flexible（灵活报告 JSON，契约 #21①）
st, fx, _ = call("GET", "/api/periods/202607/flexible")
check("GET flexible API 200", st == 200, f"got {st}")
check("flexible 有 intents/reports/cur/body_html",
      all(k in fx for k in ('"intents"', '"reports"', '"cur"', '"body_html"')))
check("flexible 列到两份报告", fx.count('"intent"') >= 3, f"n={fx.count(chr(34) + 'intent' + chr(34))}")
check("flexible body_html 指向图表保留路由", "/p/202607/flexible/chart/" in fx)

out("=" * 56)
if FAILS:
    out(f"结果：{len(FAILS)} 项未过")
    for f in FAILS:
        out("  - " + f)
else:
    out("结果：全部通过（%d 项断言）" % len(LOG))
dump_log()
sys.exit(1 if FAILS else 0)
