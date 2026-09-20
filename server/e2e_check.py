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
# ⚠ 别写死 8080：用 `WENHENG_BASE` 换端口跑时，写死会让这条**假失败**
#    （2026-09-19 用 8099 实测：final 明明是首页，断言却判未过）。
check("POST /login 进入首页", final.rstrip("/") == BASE, f"final={final}")

out("=== 4. 首屏 = 馆员工作台（最新一期） ===")
# 2026-09-19 改：首屏原是「对勘本」（生产视角：报告怎么拼出来的），
# 换成「工作台」（馆员视角：这次要我做什么决定）。对勘本没删，挪到 /p/<期次>，
# 下面第 6 段照旧守它 —— 别把断言删了，那等于把回归覆盖一起扔掉。
st, home, _ = call("GET", "/")
check("GET / → 200", st == 200, f"got {st}")
check("首屏是【工作台】而非控制台", "本次出稿体检" in home and "run-form" not in home)
check("首屏给可溯源总数（不是「已核对」）", "全部可溯源" in home)
# ⚠ 只看**读数区**：页面正文里有一句「我们不写『已核对 N 格』」的说明，
#   全文搜「已核对」会被这句自己命中（否定式断言的经典自伤）。
_readouts = home.split('class="readouts"')[-1].split("panel-foot")[0]
check("读数区不写「已核对」（没有 ground truth 就不能这么标）",
      "已核对" not in _readouts)
check("有待拍板清单", "需要你填" in home and "需要你确认" in home)
check("有待补数据段（台账外）", "待补数据" in home)
# 待补那三张大表**必须读生成稿实测**，不能写死"待补三条"：
# 2026-09-20 rick 拿人工原件问「明明有图表为什么说待补」——一查 T21 与原件逐格相同，
# 写死的常量在对着产物撒谎。现在 T19/T20 空（0.0%）、T21 有内容（90.6%）。
check("待补判定走实测而非写死（T21 显示已有内容）",
      "共 3 处" in home and "已有内容" in home, "应显示「N 处待补 / 共 3 处」且 T21 标已有内容")
check("其余可溯源项不混进待办", "不进待办" in home)
check("审计视图入口齐全", all(x in home for x in
      ("/p/202607/redslots", "/p/202607/charts", "/p/202607/archive", "/run")))

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
# 首屏改成工作台后，这批对勘本上下文断言挪到这儿守（原在 / 上）
check("periodDir = 202607", jget_str(p1, "periodDir") == "202607", f"got {jget_str(p1,'periodDir')!r}")
check("periods 是数组且非空", jget(p1, "periods") == "[")
check("signUrl 指向 /p/202607/sign", jget_str(p1, "signUrl") == "/p/202607/sign")
check("revokeUrl 指向 /p/202607/revoke", jget_str(p1, "revokeUrl") == "/p/202607/revoke")
check("crumbs 已注入", jget(p1, "crumbs") == "[")
check("live 为 true", jget(p1, "live") is True)
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
check("清单行数与 red_slots.json 一致",
      rs.count("<tr>") == len(json.loads((ROOT.parent / "out" / "202607" / "red_slots.json").read_text(encoding="utf-8"))) + 1,
      f"rows={rs.count(chr(60) + chr(116) + chr(114) + chr(62)) - 1}")
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
check("快照内联全量槽位", snap.count('"loc"') >= 350, f"n={snap.count(chr(34)+'loc'+chr(34))}")

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

out("=== 12. 运行档案页（SRS R-21：状态机回放 + 瀑布 + 产物 + 日志包）===")
# 二进制要单独取：call() 会把响应 decode 成文本，zip 会被读坏。
def call_raw(path):
    try:
        r = op.open(BASE + path)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


import io as _io                                                  # noqa: E402
import zipfile as _zf                                             # noqa: E402

st, arc, _ = call("GET", "/p/202607/archive")
check("GET /p/202607/archive → 200", st == 200, f"got {st}")
for k in ("状态机回放", "任务瀑布", "审计结论", "运行环境快照", "运行日志包", "Agent 轨迹文件"):
    check(f"档案页含「{k}」", k in arc)
check("审计总判定如实显示（不是粉饰成通过）", "待人工确认" in arc)
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

out("=== 13. 红件清单的图表预览与安全 ===")
st, rs, _ = call("GET", "/p/202607/redslots")
_imgs = re.findall(r'<img src="([^"]+)"', rs)
check("图槽位渲染成图片（不再只是路径文本）", len(_imgs) >= 90, f"n={len(_imgs)}")
if _imgs:
    _st, _raw, _h = call_raw(_imgs[0])
    check("图能取到且真是 PNG", _st == 200 and _raw[:4] == b"\x89PNG",
          f"{_st} {(_h.get('content-type') or '')} {len(_raw)}B")
    check("图响应带 PNG 的 Content-Type", "image/png" in (_h.get("content-type") or ""))
# 这条路由直接服务磁盘文件，越界 = 任意文件读取（能读到 server/.env）
for _bad in ("/p/202607/chart/../server/.env",
             "/p/202607/chart/..%2Fserver%2F.env",
             "/p/202607/chart/Chemistry/../../../.env"):
    _s, _, _ = call("GET", _bad)
    check(f"越界请求被拒 {_bad[-28:]}", _s == 404, f"got {_s}")

out("=== 14. 对勘本图表槽位就地铺图 ===")
# 缩略图是 collation.js 渲染的，裸 HTML 里没有 <img>——只能断言内联 JSON 里的
# `chartUrl`（与第 13 节的坑同源），再抽一张验证它真能取到。
# 数字记死：学科图表槽位 96 张 + 概览图槽位 3 张 = 99，与 charts/ 下的 png 数一致。
_st, _rs, _ = call("GET", "/p/202607")
_cu = re.findall(r'"chartUrl":\s*"([^"]+)"', _rs)
check("图表槽位带上了图地址（前端据此就地铺图）", len(_cu) >= 90, f"n={len(_cu)}")
check("合计 99 张（学科 96 + 概览 3）", len(_cu) == 99, f"n={len(_cu)}")
check("都走 /p/202607/chart/ 这一条白名单路由",
      bool(_cu) and all(u.startswith("/p/202607/chart/") for u in _cu))
if _cu:
    _st, _raw, _h = call_raw(_cu[0])
    check("对勘本里的图能取到且真是 PNG", _st == 200 and _raw[:4] == b"\x89PNG",
          f"{_st} {(_h.get('content-type') or '')} {len(_raw)}B")
# 前端两个分支都要在：有地址给缩略图，没地址给兜底文案（离线快照则整块不渲染）
_cjs = (ROOT / "static" / "collation.js").read_text(encoding="utf-8")
check("collation.js 渲染缩略图", 'class="thumb"' in _cjs and "<img src=" in _cjs)
check("collation.js 有缺图兜底（不显示裂图）", "图未落盘" in _cjs)

out("=== 15. 工作台：逐格溯源 / 在线填 / 存疑 ===")
# 2026-09-19 新增。三个数字的落点：354→trace，19→在线填，3→待补说明。
st, tr, _ = call("GET", "/p/202607/trace")
check("GET /p/202607/trace → 200", st == 200, f"got {st}")
check("trace 大表格数正确（239）", 'id="f-shown">239<' in tr,
      "标题里的计数被筛选用的 span 包住了，断言要查元素内容而不是纯文本")
check("trace 有图表 99 张", "图表 · 99" in tr)
check("trace 是并排对照不是单列值", "台账（现场重读）" in tr and "派生" in tr)
check("派生格给了算式", "总被引 − ESI被引阈值" in tr and "× 10" in tr)
check("台账缺失时降级说明而不是空白", "本地未找到台账" in tr or "全部可回查" not in tr)
# 在线填：写产物侧 manual_inputs.json，**台账不碰**（字节数前后必须一致）。
# fill/flag 走真实表单 POST + 303 回跳（栈契约：状态变更不依赖 JS），不是 AJAX。
_led = ROOT.parent.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"
_sha0 = _led.stat().st_size if _led.exists() else -1
st, fr, fin = call("POST", "/p/202607/fill",
                   {"id": "e2e-fill-test", "value": "e2e 测试值",
                    "back": "/#todo-panel"})
check("POST fill 走表单 303 回跳", st == 200 and fin.endswith("#todo-panel"),
      f"{st} final={fin}")
_mi = ROOT.parent / "out" / "202607" / "manual_inputs.json"
_mi_ok = _mi.exists() and "e2e-fill-test" in _mi.read_text(encoding="utf-8")
check("manual_inputs.json 落在产物目录", _mi_ok)
# 🔴 用完必须自己打扫：这条测试键会显示在馆员工作台的「已填」区里（2026-09-20
#    rick 就看到了"已填 2 处"却哪也没填 —— 一条是这个，一条是更早的测试残留）。
if _mi.exists():
    _d = json.loads(_mi.read_text(encoding="utf-8"))
    _d.pop("e2e-fill-test", None)
    _mi.write_text(json.dumps(_d, ensure_ascii=False, indent=1), encoding="utf-8") if _d \
        else _mi.unlink()
check("e2e 写完自己清理掉测试键", not _mi.exists()
      or "e2e-fill-test" not in _mi.read_text(encoding="utf-8"))
st, fr2, _ = call("POST", "/p/202607/flag", {"loc": "T01/r999c9",
                                             "back": "/p/202607/trace"})
_rv = ROOT.parent / "out" / "202607" / "review.json"
_d1 = (json.loads(_rv.read_text(encoding="utf-8")).get("T01/r999c9") or {}
       if _rv.exists() else {})
st, fr3, _ = call("POST", "/p/202607/flag", {"loc": "T01/r999c9",
                                             "back": "/p/202607/trace"})
_d2 = (json.loads(_rv.read_text(encoding="utf-8")) if _rv.exists() else {})
check("存疑可切换（点两次=撤销）",
      _d1.get("state") == "doubt" and "T01/r999c9" not in _d2, f"{_d1} | {_d2}")
check("台账没被在线填/存疑碰到（字节数不变）",
      _led.stat().st_size == _sha0, f"{_sha0} -> {_led.stat().st_size}")
# 首页的三个数字都是可点的。
# 🔴 断言要写**完整路径**：之前写成 href="202607/trace"（少了 /p/ 前缀），
#    断言照着 bug 写 → 点击 404 但 e2e 全绿（rick 2026-09-19 实踩）。
st, home2, _ = call("GET", "/")
check("工作台三个数字可点（trace 链接完整）", 'href="/p/202607/trace"' in home2)
check("待办区是一个批量表单（一次提交取代逐条刷新）",
      'name="v:' in home2 and "保存全部" in home2)
check("输入框有 aria-label（16 个同名框否则无法区分）",
      home2.count('aria-label="正文') >= 5)
check("发起新任务在顶栏（页面最上方）",
      home2.split("</header>")[0].count("发起新任务") == 1)
check("待补数据说明诚实标注交互未定", "交互还没定" in home2)
# 🔴 链接/表单 action 必须是**绝对路径**：写成 202607/trace 会从 / 解析成
#    /202607/trace → 404，而 e2e 直接打绝对 URL 是抓不到的（2026-09-19 rick 实踩，
#    2026-09-20 表单 action 又犯一次）。这条断言专治这个。
check("表单 action 是绝对路径（不是相对路径）",
      'action="/p/202607/fill"' in home2 and 'action="202607/fill"' not in home2
      and 'action="/p/202607/rebuild"' in home2)
# 产线入口必须**在第一屏**（rick 2026-09-20：原来只塞在第六格审计链接堆里，
# 一般用户根本不知道入口在哪）。断言两件事：产线条里真的有灵活报告链接、
# 且第六格的审计链接段落里**没有**「灵活报告」字样（防止以后又被塞回去）。
# 🔴 产线条里有嵌套 div，别按 </div> 切 —— 要切到下一个 panel 才是完整一段。
_band = home2.split('class="line-bar"')[1].split('class="panel"')[0] \
    if 'class="line-bar"' in home2 else ""
check("灵活报告入口在第一屏产线条（不在审计链接堆里）",
      'href="/p/202607/flexible"' in _band
      and home2.count("灵活报告") == 2        # 产线条一处 + <style> 注释一处
      and "灵活报告" not in (home2.split("审计视图")[-1]))
st, fp, _ = call("GET", "/p/202607/flexible")
check("灵活页可开且生成表单齐备（意图/后端/学科/提交）",
      st == 200 and 'name="intent"' in fp and 'name="backend"' in fp
      and 'method="post"' in fp and 'id="flex-report"' in fp)
# 重出报告：没有填写内容时**不执行**（安全分支，不覆盖任何产物）。
# ⚠ 要用**确定没填过**的期次：202605_复现 有 2 条填写记录（演示样例），
#   POST 上去会真的重出一次稿（2026-09-20 实测，断言因此误红）。
st, _rb, _rfin = call("POST", "/p/202601_%E5%A4%8D%E7%8E%B0/rebuild",
                      {"back": "/#todo-panel"})
# ⚠ 回跳带的提示是 URL 编码的；而且要拼在问号位置而不是锚点后面
#   （写成 /#todo-panel?err=… 的话浏览器整段忽略，提示永远不显示）
_rf = urllib.parse.unquote(_rfin)
check("没填内容时 rebuild 拒绝执行", "还没有填写内容" in _rf, f"final={_rfin}")
check("提示拼在问号位置而非锚点后", "?err=" in _rf and "?err=" not in _rf.split("#")[-1],
      f"final={_rfin}")

out("=" * 56)
if FAILS:
    out(f"结果：{len(FAILS)} 项未过")
    for f in FAILS:
        out("  - " + f)
else:
    out("结果：全部通过（%d 项断言）" % len(LOG))
dump_log()
sys.exit(1 if FAILS else 0)
