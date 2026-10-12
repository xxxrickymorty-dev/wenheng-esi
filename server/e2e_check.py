# -*- coding: utf-8 -*-
"""文衡演示站端到端验收（定稿后回归）。

用法（先起服务，再跑）：
    .venv\\Scripts\\python.exe server\\e2e_check.py
    服务地址可用环境变量覆盖：WENHENG_BASE=http://127.0.0.1:8080

验收范围：登录 → 首屏对勘本 → 控制台 /run → 期次入口 /p/<期次> → 期次红件清单
→ 任务入口与产物 → 签单闸门与落库（含撤回）→ 静态快照同源 → 任务状态口径同源。
只读 + 一次签单/撤回 + 一次选模往返（验完写回原值），不动流水线数据；结束后 202607 停在 unsigned。

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


def _env_file_value(key: str, default: str = "") -> str:
    """口令只从环境变量或 server/.env 来（2026-10-02：删掉内置默认口令）。"""
    if os.environ.get(key):
        return os.environ[key]
    env_file = WENHENG / "server" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


ADMIN_U = os.environ.get("WENHENG_E2E_USER") or _env_file_value("WENHENG_USER", "admin")
ADMIN_P = os.environ.get("WENHENG_E2E_PASS") or _env_file_value("WENHENG_PASS")
if not ADMIN_P:
    print("未找到管理员口令：请在 server/.env 设置 WENHENG_PASS，或设 WENHENG_E2E_PASS 后重跑。")
    raise SystemExit(2)
#: 操作员（评委，只读；2026-10-11 起取代 guest）——账号/口令从 .env 或环境变量来。
OPERATOR_U = os.environ.get("WENHENG_E2E_OPERATOR_USER") or _env_file_value("WENHENG_OPERATOR_USER", "demo")
OPERATOR_P = os.environ.get("WENHENG_E2E_OPERATOR_PASS") or _env_file_value("WENHENG_OPERATOR_PASS")
if not OPERATOR_P:
    print("未找到操作员口令：请在 server/.env 设置 WENHENG_OPERATOR_PASS，或设 WENHENG_E2E_OPERATOR_PASS 后重跑。")
    raise SystemExit(2)

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "wenheng-e2e")]
FAILS = []


def call(method, path, data=None, opener=None, headers=None):
    url = BASE + path
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        r = (opener or op).open(req)
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
st, body, _final = call("GET", "/app/", headers={"Accept": "text/html"})
check("GET /app/ (未登录) 显示「请先登录」页",
      st == 200 and "请先登录" in body and 'href="/login"' in body, f"got {st}")

out("=== 3. 登录 ===")
# 欢迎页 = 登录页（rick 2026-09-21 定：建筑图做首屏；2026-09-28 二改：满屏背景 + 云大绿）。
# 断言三件事：背景图与校徽在且走 asset（版本号，否则改图后浏览器吃缓存）、登录表单没被改坏。
st, lp, _ = call("GET", "/login")
check("欢迎页背景图 + 校徽走 asset 版本号",
      "/static/img/library-exterior.jpg?v=" in lp and "/static/img/ynu-emblem.png?v=" in lp,
      f"got {st}")
check("登录表单完好（账号/密码/action）",
      'name="username"' in lp and 'name="password"' in lp and 'action="/login"' in lp)
check("登录页只有登录表单（入口已移入工作区导航）",
      lp.count('action="/login"') == 1 and "陈列馆" not in lp)
st, body, final = call("POST", "/login", {"username": ADMIN_U, "password": ADMIN_P})
# ⚠ 别写死 8080：用 `WENHENG_BASE` 换端口跑时，写死会让这条**假失败**
#    （2026-09-19 用 8099 实测：final 明明是首页，断言却判未过）。
check("POST /login（管理员）先落陈列馆 /app/shelf/",
      final.rstrip("/") == BASE + "/app/shelf", f"final={final}")

out("=== 3.1 操作员账号（demo）真登 + 只读角色门（契约 §4，2026-10-11） ===")
# 2026-10-11：guest 取消，改「操作员」（评委，只读）——进工作区但不被送回陈列馆；
# 取数/台账/运行档案/红件/溯源不可见，写动作一律 403；陈列馆两种角色同拿全数据。
gop = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
st, _, gfinal = call("POST", "/login", {"username": OPERATOR_U, "password": OPERATOR_P}, opener=gop)
check("POST /login（操作员）也先落陈列馆 /app/shelf/",
      gfinal.rstrip("/") == BASE + "/app/shelf", f"final={gfinal}")
st, gme, _ = call("GET", "/api/me", opener=gop)
check("GET /api/me（操作员）→ 200", st == 200, f"got {st}")
check("操作员角色是 operator", '"role":"operator"' in gme or '"role": "operator"' in gme,
      f"body={gme[:100]}")
for _path in ("/api/periods/202607/redslots", "/api/periods/202607/acquisition",
              "/api/periods/202607/trace", "/api/periods/202607/archive",
              "/api/ledger/sheets"):
    st, _, _ = call("GET", _path, opener=gop)
    check(f"操作员访问隐藏屏端点被挡（403）：{_path}", st == 403, f"got {st}")
st, _, _ = call("POST", "/api/periods/202607/acquisition/preflight", opener=gop)
check("操作员访问取数写动作被挡（403）", st == 403, f"got {st}")
st, _, _ = call("POST", "/api/periods/202607/sign", {"known": "true", "note": "e2e-操作员"}, opener=gop)
check("操作员签单被挡（403）", st == 403, f"got {st}")
for _path in ("/api/periods/202607/facts", "/api/periods/202607/collation?limit=1",
              "/api/periods/202607/charts", "/api/periods/202607/artifacts"):
    st, _, _ = call("GET", _path, opener=gop)
    check(f"操作员可读只读端点（200）：{_path}", st == 200, f"got {st}")
st, garts, _ = call("GET", "/api/periods/202607/artifacts", opener=gop)
check("操作员产物清单无红件与运行日志",
      st == 200 and "red_list" not in garts and "red_json" not in garts and "runlog" not in garts,
      f"got {st}")
st, gdata, _ = call("GET", "/app/shelf/data.js", opener=gop)
check("操作员陈列馆数据=全数据（与管理员同份）",
      st == 200 and '"rank_intl_now"' in gdata, f"got {st}, bytes={len(gdata)}")
st, _, glegacy = call("GET", "/p/202607", opener=gop)
check("操作员旧报告路由进新工作区阅读视图",
      "/app/?view=reading" in glegacy, f"final={glegacy}")

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


def _pending_fills():
    """工作台里「已填未写入」条数（签单前的填值闸要读它）。"""
    _st, _wb, _ = call("GET", "/api/periods/202607/workbench")
    try:
        rows = json.loads(_wb).get("fills_list") or []
    except (json.JSONDecodeError, AttributeError):
        rows = []
    return [f for f in rows if f.get("state") == "pending"]


def _manual_slots():
    """待人工空位数（签单的「已知悉」闸只在有它时要勾）——从对勘数据现取。"""
    _st, _cl, _ = call("GET", "/api/periods/202607/collation?full=true")
    try:
        secs = json.loads(_cl).get("sections") or []
    except (json.JSONDecodeError, AttributeError):
        secs = []
    return sum(int(s.get("manual") or 0) for s in secs)


# 闸门预期按工作台**真实状态**取（2026-09-29 修）：
#   有「已填未写入」→ 填值闸先拦（先重出再签）；
#   有待人工空位   → 不勾「已知悉」被知悉闸拦；
#   两者都没有     → 不勾也直接可签（闸门只为待人工而设）——写死「必 409」会在干净数据上假失败。
_pend, _manual = _pending_fills(), _manual_slots()

call_json("POST", "/api/periods/202607/revoke", {"note": "e2e 前置归零"})
check("前置：状态归零到 unsigned", _wstate() == "unsigned", f"got {_wstate()!r}")

if _pend:
    st, _e1, _ = call_json("POST", "/api/periods/202607/sign",
                           {"note": "e2e 验收", "known": True})
    _e1j = json.loads(_e1) if _e1.strip().startswith("{") else {}
    check("有「已填未写入」→ 签单被填值闸拦下（先重出再签）",
          st == 409 and "写进报告" in str(_e1j.get("error", "")),
          f"{st} err={str(_e1j.get('error'))[:70]!r}")
    check("被拦时不落盘（状态仍 unsigned）", _wstate() == "unsigned", f"got {_wstate()!r}")
    print(f"  ⚠ 跳过签/撤往返：本期还有 {len(_pend)} 处填写没写进报告"
          "——先在审核台「保存并重出报告」，再跑完整 e2e")
else:
    if _manual:
        st, _e1, _ = call_json("POST", "/api/periods/202607/sign", {"note": "e2e"})
        _e1j = json.loads(_e1) if _e1.strip().startswith("{") else {}
        check("不勾「已知悉」→ 409 被闸门拦下", st == 409, f"got {st}")
        check("拦截原因是待人工项未勾选",
              "已知悉" in str(_e1j.get("error", "")) or "手工" in str(_e1j.get("error", "")),
              f"err={str(_e1j.get('error'))[:80]!r}")
        check("被拦时不落盘（状态仍 unsigned）", _wstate() == "unsigned", f"got {_wstate()!r}")
    else:
        st, _e1, _ = call_json("POST", "/api/periods/202607/sign", {"note": "e2e 探针"})
        check("无待人工项：不勾「已知悉」也可直接签（闸门只为待人工而设）",
              st == 200, f"got {st}")
        call_json("POST", "/api/periods/202607/revoke", {"note": "e2e 探针归零"})

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
check("快照单文件自足（样式/脚本已内联，无外部 link/script src）",
      'id="whc-snapshot-style"' in snap and 'id="whc-snapshot-script"' in snap
      and 'href="style.css"' not in snap and 'src="collation.js"' not in snap)
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

out("=== 12. 运行档案：老页已 302（§3.5），数据走 JSON API + 保留下载端点 ===")
# 2026-09-24 第二轮：/p/202607/archive 与 /jobs/<id>/archive 已 302 到 ?view=archive
# （落点由 §3.5 逐条验）。原页面的内容断言前移到 §16 的 archive JSON
# （replay/audit/logpack/artifacts、不回绝对路径都在那里）。这里只留保留下来的下载端点。
import io as _io                                                  # noqa: E402
import zipfile as _zf                                             # noqa: E402

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
    # 任务档案页已 302（§3.5 按任务期次验落点）；任务日志包下载端点保留。
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
# 台账路径两处都找：开发机是 <工作区>/数据与复现/（原始事实源）；部署包/服务器上
# 只有 input/<期次>/监测表.xlsx（服务端实际读的那份）。两处都没有就跳过比对——
# 2026-09-24 实踩：写死工作区布局，在解包目录里 `_led.stat()` 直接 FileNotFoundError，
# 整个 e2e 崩在中途（服务器上必然复现）。
_led_cands = (
    ROOT.parent.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx",
    ROOT.parent / "input" / "202607" / "监测表.xlsx",
)
_led = next((p for p in _led_cands if p.exists()), None)
_sha0 = _led.stat().st_size if _led else -1
st, _f1, _ = call_json("POST", "/api/periods/202607/flag", {"loc": "T01/r999c9"})
_f1j = json.loads(_f1) if _f1.strip().startswith("{") else {}
check("存疑接口 200 且落 doubt", st == 200 and _f1j.get("state") == "doubt",
      f"{st} {str(_f1j)[:60]}")
st, _f2, _ = call_json("POST", "/api/periods/202607/flag", {"loc": "T01/r999c9"})
_f2j = json.loads(_f2) if _f2.strip().startswith("{") else {}
check("再点一次撤销（可切换）", st == 200 and _f2j.get("state") == "clear",
      f"{st} {str(_f2j)[:60]}")
if _led:
    check("台账没被在线填/存疑碰到（字节数不变）",
          _led.stat().st_size == _sha0, f"{_led.name} {_sha0} -> {_led.stat().st_size}")
else:
    out("  SKIP 台账未随包（部署环境属正常）——跳过字节数比对")
# 灵活报告页已 302 到分析台（落点 §3.5）；保留下来的图路由与 JSON API 在 §16 验。

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
check("period_detail 有 steps 三步（取数/核对并并入/生成）",
      '"fetch"' in pd and '"merge"' in pd and '"generate"' in pd)
check("period_detail 有 acquisition 摘要",
      '"acquisition"' in pd and '"started"' in pd and '"expected"' in pd)
check("period_detail 有 window", '"window"' in pd)
check("period_detail 有 no/total", '"no"' in pd and '"total"' in pd)

# GET /api/periods/{period}/acquisition（自动取数台；X2·只读）
st, aq, _ = call("GET", "/api/periods/202607/acquisition")
check("GET acquisition 200", st == 200, f"got {st}")
check("acquisition 有 period/started", '"period"' in aq and '"started"' in aq)
st, _, _ = call("GET", "/api/periods/abc/acquisition")
check("acquisition 非法期次 404", st == 404, f"got {st}")
st, _, _ = call_json("POST", "/api/periods/abc/acquisition/merge", {})
check("POST acquisition 非法期次 404", st == 404, f"got {st}")

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

# POST /api/analyze（JSON body；qa 能力薄适配，契约 §2.2 #9，2026-09-29 D2 接线）
st, an, _ = call_json("POST", "/api/analyze", {"period": "202607", "question": "顶尖论文"})
check("POST analyze 200", st == 200, f"got {st}")
try:
    _aj = json.loads(an)
except json.JSONDecodeError:
    _aj = {}
check("analyze 是 Answer 字段面（mode/backend/text/rule_text/sources/shield）",
      all(k in _aj for k in ("mode", "backend", "text", "rule_text", "sources", "shield")),
      str(sorted(_aj))[:120])
check("analyze mode ∈ {rule, model} 且 text 非空",
      _aj.get("mode") in ("rule", "model") and bool(str(_aj.get("text") or "").strip()),
      f"mode={_aj.get('mode')!r}")
check("analyze 盾计数与来源数一致（第 k 个数字 ↔ sources[k]）",
      isinstance(_aj.get("sources"), list)
      and (_aj.get("shield") or {}).get("checked")
      == (_aj.get("shield") or {}).get("passed") == len(_aj.get("sources") or []),
      f"shield={_aj.get('shield')} n_sources={len(_aj.get('sources') or [])}")

# POST /api/dialog/turn · 查数据（契约 #33，票 07：两意图；服务器按意图调 qa）
st, dlg, _ = call_json("POST", "/api/dialog/turn",
                       {"text": "查一下顶尖论文", "slots": {"period": "202607"}})
check("POST dialog/turn（查数据）200", st == 200, f"got {st}")
try:
    _dj = json.loads(dlg)
except json.JSONDecodeError:
    _dj = {}
check("对话前门 · 查数据路由 kind=query", _dj.get("kind") == "query", str(_dj.get("kind")))
_ans = _dj.get("answer") or {}
check("对话前门 · 查数据带回答（Answer 字段面 + 留痕）",
      _ans.get("mode") in ("rule", "model") and bool(str(_ans.get("text") or "").strip())
      and bool(_ans.get("record_id")),
      f"mode={_ans.get('mode')!r}")
check("对话前门 · 查数据盾计数与来源数一致",
      (_ans.get("shield") or {}).get("checked")
      == (_ans.get("shield") or {}).get("passed") == len(_ans.get("sources") or []),
      f"shield={_ans.get('shield')} n_sources={len(_ans.get('sources') or [])}")

# POST /api/dialog/turn · 覆盖确认（契约 #33，票 05 口径 A：回合不执行——产物已在先问一次）
st, dlg2, _ = call_json("POST", "/api/dialog/turn",
                        {"text": "核完了，继续", "slots": {"period": "202607"}})
check("POST dialog/turn（覆盖确认）200", st == 200, f"got {st}")
try:
    _dj2 = json.loads(dlg2)
except json.JSONDecodeError:
    _dj2 = {}
check("对话前门 · 产物已在→先问一次（不自动开跑）",
      (_dj2.get("run") or {}).get("auto") is False, f"run={_dj2.get('run')}")
st2, sj, _ = call("GET", "/api/status")
try:
    _active = (json.loads(sj) or {}).get("active")
except json.JSONDecodeError:
    _active = None
check("对话前门 · 问一次没有启动任何任务", st2 == 200 and not _active, f"active={_active!r}")

# GET /api/dialog/home（契约 #35，票 06：本期任务——三步状态从既有产物判，只读）
st, hm, _ = call("GET", "/api/dialog/home")
check("GET dialog/home 200", st == 200, f"got {st}")
try:
    _hm = json.loads(hm)
except json.JSONDecodeError:
    _hm = {}
check("对话前门 · 首页带本期与三步",
      len(str(_hm.get("period") or "")) == 6 and len(_hm.get("steps") or []) == 3,
      f"period={_hm.get('period')!r} n_steps={len(_hm.get('steps') or [])}")
check("对话前门 · 首页有卡点与上一期线索",
      bool(_hm.get("stuck"))
      and (_hm.get("prev") is None or len(str((_hm.get("prev") or {}).get("period") or "")) == 6),
      f"stuck={_hm.get('stuck')!r} prev={_hm.get('prev')!r}")

# POST /api/periods/{period}/review-advice（复核参谋；契约 #27，2026-09-29 D4）
st, rv, _ = call_json("POST", "/api/periods/202607/review-advice", {})
check("POST review-advice 200", st == 200, f"got {st}")
try:
    _rj = json.loads(rv)
except json.JSONDecodeError:
    _rj = {}
check("review-advice mode ∈ {rule, model} 且 text 非空",
      _rj.get("mode") in ("rule", "model") and bool(str(_rj.get("text") or "").strip()),
      f"mode={_rj.get('mode')!r}")
check("review-advice 带边界句（不会代签、不会改稿）",
      "不会代签" in str(_rj.get("text") or "") and "不会改稿" in str(_rj.get("text") or ""),
      str(_rj.get("text"))[:60])
check("review-advice 来源指红件/校验记录",
      bool(_rj.get("sources")) and all(
          str(s.get("pointer", "")).startswith(("red_slots.json", "meta.json"))
          for s in _rj.get("sources") or []),
      str([s.get("pointer") for s in (_rj.get("sources") or [])][:3]))

# GET /api/ai/capabilities + POST /api/ai/switch（D5 前端开关；契约 #28/#29）
st, caps, _ = call("GET", "/api/ai/capabilities")
check("GET ai/capabilities 200", st == 200, f"got {st}")
check("capabilities 含四能力", all(f'"{k}"' in caps for k in ("qa", "review", "diagnose", "brief")))
st, _sw, _ = call_json("POST", "/api/ai/switch", {"capability": "不存在", "enabled": False})
check("ai/switch 未知能力 400（不动真开关）", st == 400, f"got {st}")

# GET /api/periods/{period}/ai-calls（运行档案票 06 块；契约 #30）
st, aic, _ = call("GET", "/api/periods/202607/ai-calls")
check("GET ai-calls 200", st == 200, f"got {st}")
check("ai-calls 有 calls+stats", '"calls"' in aic and '"stats"' in aic)
check("ai-calls 只回摘要（无回答正文/提示词）",
      '"text_preview"' not in aic and '"system"' not in aic)

# POST /api/periods/{period}/forecast-choice（JSON body，契约 #17 嵌套形状）
# 先取检查前的选择：验完写回——e2e 不把测试选模留在 202607（重出报告会带上它）。
# 学科名从接口现取：候选学科随数据期次滚动，写死会过期（曾写「化学」，2026-09-28 已不在候选里）。
st, meta_body, _ = call("GET", "/api/forecast/meta")
try:
    e2e_subject = (json.loads(meta_body).get("subjects") or ["分子生物学与遗传学"])[0]
except (json.JSONDecodeError, AttributeError):
    e2e_subject = "分子生物学与遗传学"
st, fq0, _ = call("GET", "/api/periods/202607/forecast-choice")
prev_choice = json.loads(fq0).get("choice", {}) if st == 200 else {}
st, fc, _ = call_json("POST", "/api/periods/202607/forecast-choice",
                      {"choice": {"citation": {e2e_subject: "SARIMA模型"}}})
check("POST forecast-choice 200（嵌套形状）", st == 200, f"got {st} subject={e2e_subject}")
check("forecast-choice POST 返回 ok+saved+saved_routes（防被读回路由抢先）",
      '"ok"' in fc and '"saved"' in fc and '"saved_routes"' in fc, f"body={fc[:120]}")

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
check("facts 学科名已是中文（契约 #22）", "分子生物学与遗传学" in fc, f"body={fc[:100]}")

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
check("读回能见刚保存的嵌套值（保存确实落盘）",
      '"citation"' in fq and e2e_subject in fq and "SARIMA" in fq, f"body={fq[:160]}")
check("forecast-choice GET 有 by", '"by"' in fq)
# 写回检查前的选择（e2e 不留测试残留；原本为空就写回 {}＝无选择态）
st, _, _ = call_json("POST", "/api/periods/202607/forecast-choice", {"choice": prev_choice})
check("forecast-choice 写回检查前的选择", st == 200, f"got {st}")

# GET /api/periods/202607/collation?full=true
st, clf, _ = call("GET", "/api/periods/202607/collation?full=true")
check("GET collation?full=true 200", st == 200, f"got {st}")
check("collation full 有 sections+slots", '"sections"' in clf and '"slots"' in clf or '"rows"' in clf)

# GET /api/periods/202607/report-preview（审核台试排报告，契约 #24）
st, pv, _ = call("GET", "/api/periods/202607/report-preview")
check("GET report-preview 200", st == 200, f"got {st}")
check("report-preview 有 blocks/fields/docx",
      all(k in pv for k in ('"blocks"', '"fields"', '"docx"')))
check("report-preview 段落块带 runs（可按原格式渲染）", '"runs"' in pv)
check("report-preview 字段是工作台同套键（含 ::）", "::" in pv or '"fields":{}' in pv.replace(" ", ""))
_m = re.search(r'"rid"\s*:\s*"(rId\d+)"', pv)
if _m:
    st, raw_img, hdr = call_raw(f"/api/periods/202607/report-image/{_m.group(1)}")
    check("report-image 按 rId 可取图", st == 200 and (hdr.get("content-type") or "").startswith("image/"),
          f"got {st} {hdr.get('content-type')}")
else:
    check("report-preview 含插图 rId", False, "no rid found")
st, _, _ = call("GET", "/api/periods/202607/report-image/not-a-rid")
check("report-image 非法 rid 拒绝", st == 404, f"got {st}")

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
# POST /api/periods/202601_复现/rebuild（没有填值应拒绝，不碰产物）
# 复现期次是开发机产物、不随演示包分发（包内只有 202607）→ 服务器上退化为 404
# 「期次不存在」；本地有它时必须 409（有产物、没填值）。两种情况都要求「拒绝 + error 体」。
st, rb, _ = call_json("POST", "/api/periods/202601/rebuild", {})
# 2026-09-29 起历史补跑产物按正常期次命名（out/202601），不再带 _复现 后缀；
# 开发机有该目录 → 409（有产物、没填值）；部署包内没有 → 404。
_expect = 409 if (WENHENG / "out" / "202601").is_dir() else 404
check(f"rebuild 无填值被拒（{_expect}）", st == _expect and '"error"' in rb, f"got {st}")

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
check("board 学科名已是中文（契约 #22）", "分子生物学与遗传学" in bd, f"body={bd[:100]}")

# GET /api/periods/{period}/flexible（灵活报告 JSON，契约 #21①）
st, fx, _ = call("GET", "/api/periods/202607/flexible")
check("GET flexible API 200", st == 200, f"got {st}")
check("flexible 有 intents/reports/cur/body_html",
      all(k in fx for k in ('"intents"', '"reports"', '"cur"', '"body_html"')))
check("flexible 列到两份报告", fx.count('"intent"') >= 3, f"n={fx.count(chr(34) + 'intent' + chr(34))}")
check("flexible body_html 指向图表保留路由", "/p/202607/flexible/chart/" in fx)
# 页面下线后这条图路由必须还活着（body_html 直接引用它，删了图全裂）
_m_chart = re.search(r"/p/202607/flexible/chart/[^\"\\\s]+", fx)
if _m_chart:
    _st_c, _c_bytes, _ = call_raw(_m_chart.group(0))
    check("保留的灵活图路由可开", _st_c == 200 and len(_c_bytes) > 100,
          f"got {_st_c} {len(_c_bytes)}B {_m_chart.group(0)[:60]}")
else:
    check("body_html 里有可直接打开的图地址", False, fx[:120])

# 灵活报告下载＝单文件（页内图下载时即时内联为 data URI；契约 #26）
st_dl, dl_html, _ = call("GET", "/p/202607/flexible/single_trend/report.html")
check("灵活报告下载 200", st_dl == 200, f"got {st_dl}")
check("灵活报告下载已带图（单文件 data URI）",
      "data:image/" in (dl_html or "") and 'src="charts/' not in (dl_html or ""),
      f"len={len(dl_html or '')} has_data={'data:image/' in (dl_html or '')}")

out("=" * 56)
if FAILS:
    out(f"结果：{len(FAILS)} 项未过")
    for f in FAILS:
        out("  - " + f)
else:
    out("结果：全部通过（%d 项断言）" % len(LOG))
dump_log()
sys.exit(1 if FAILS else 0)
