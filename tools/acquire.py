# -*- coding: utf-8 -*-
"""取数模块编排器（X3）：scan / copy / merge / preflight / fetch。

流程（ADR-0004）：
    fetch/scan  取数 + 逐文件核验 → 写状态
    copy        清洗链 --out 新建 input/<期次>/监测表.xlsx（主台账不碰）→ 核对表 → 状态「待核对」
    merge       守卫（母版 sha 对得上）→ clean_ledger --write 并入 → 写后五查 → 状态「已并入」

用法（wenheng/ 下，.venv 的 python）：
    python tools\\acquire.py scan 202611
    python tools\\acquire.py copy 202611
    python tools\\acquire.py merge 202611 --dry
    python tools\\acquire.py merge 202611
    python tools\\acquire.py preflight 202611      # 需系统 python（playwright 在那边）
    python tools\\acquire.py fetch 202611          # 同上；跑 9 组下载 → 自动 scan + copy
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / "Scripts" / "python.exe"
LEDGER = REPO.parent / "数据与复现" / "云大全学科排名、阈值动态检测表.xlsx"

sys.path.insert(0, str(REPO / "src"))
import acquisition_state as A                                          # noqa: E402
import ledger_merge as LM                                              # noqa: E402
import ledger_patch as LP                                              # noqa: E402

#: 取数用的解释器（playwright 装系统 python 里；可用环境变量覆盖）
FETCH_PY = os.environ.get("WENHENG_FETCH_PYTHON") or shutil.which("python") or sys.executable


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _set_op(period: str, kind: str, state: str, note: str = "") -> dict:
    st = A.load_state(period) or {}
    st["op"] = {"kind": kind, "state": state, "note": note, "at": _now()}
    A.write_state(period, st)
    return st


def _run(cmd: list) -> int:
    print(f"\n===== {' '.join(str(c) for c in cmd)} =====", flush=True)
    return subprocess.call([str(c) for c in cmd], cwd=str(REPO))


def _print_scan_summary(st: dict, period: str) -> None:
    t = st["totals"]
    print(f"[scan] {period}: {t['verified']}/{t['expected']} 已核验"
          f"（failed={t['failed']}）· InCites 快照 {st.get('snapshot','')}")
    for g in st["groups"]:
        print(f"  {g['state']:8s} {g['title']}  {g['verified']}/{len(g['files'])}")


# ------------------------------------------------------------------ scan
def cmd_scan(args) -> int:
    st = A.scan(args.period, esi_root=args.esi_root or None, snapshot=args.snapshot)
    A.write_state(args.period, st)
    _print_scan_summary(st, args.period)
    return 0


# ------------------------------------------------------------------ copy
def cmd_copy(args) -> int:
    period = args.period
    out = pathlib.Path(args.out) if args.out else (REPO / "input" / period / "监测表.xlsx")
    if not LEDGER.exists():
        print(f"[拒绝] 主台账不存在：{LEDGER}")
        return 1
    sha0 = LM.sha256_file(LEDGER)
    _set_op(period, "copy", "running", f"新建监测表 → {out}")
    cmd = [PY, REPO / "tools" / "clean_ledger.py", period, "--out", out]
    if args.snapshot:
        cmd += ["--snapshot", args.snapshot]
    if args.esi_root:
        cmd += ["--esi-root", args.esi_root]
    rc = _run(cmd)
    if LM.sha256_file(LEDGER) != sha0:
        _set_op(period, "copy", "failed", "建副本期间主台账被改动——先查原因再重来")
        print("[拒绝] 主台账在建副本期间被改动，本次副本作废。")
        return 1
    if rc != 0 or not out.exists():
        _set_op(period, "copy", "failed", f"清洗链退出码 {rc}")
        print(f"[失败] 清洗链退出码 {rc}，副本未产出。")
        return 1
    rows = LM.review_summary(LEDGER, out, period)
    st = A.load_state(period) or A.scan(period, esi_root=args.esi_root or None)
    try:
        rel = out.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        rel = str(out)
    st["copy"] = {"state": "review", "path": rel, "built_at": _now(),
                  "master_sha": sha0, "sha256": LM.sha256_file(out)}
    st["review"] = {"sheets": rows}
    st["op"] = {"kind": "copy", "state": "done", "note": f"监测表已建好，待核对（{len(rows)} 张表）",
                "at": _now()}
    A.write_state(period, st)
    print(f"[copy] 副本就绪：{rel}（{len(rows)} 张表将被并入）——请核对后 merge")
    return 0


# ------------------------------------------------------------------ merge
def cmd_merge(args) -> int:
    period = args.period
    st = A.load_state(period)
    if not st:
        print(f"[拒绝] 没有 {period} 的取数状态——先 scan/copy。")
        return 1
    copy_path = pathlib.Path(args.copy) if args.copy else (REPO / (st.get("copy") or {}).get(
        "path", f"input/{period}/监测表.xlsx"))
    if not copy_path.is_absolute():
        copy_path = REPO / copy_path
    copy_state = (st.get("copy") or {}).get("state")
    if copy_state != "review":
        print(f"[拒绝] 副本状态是「{copy_state}」，只有「待核对（review）」的副本能并入。")
        return 1
    if not copy_path.exists():
        print(f"[拒绝] 找不到已核对的副本：{copy_path}（先 copy）")
        return 1
    master_sha = LM.sha256_file(LEDGER)
    if (st.get("copy") or {}).get("master_sha") != master_sha:
        print("[拒绝] 主台账在「建副本」之后被改动过——副本已不是同一底座，请重新 copy 后核对。")
        return 1
    if args.dry:
        print(f"[dry] 守卫通过：副本 {copy_path.name} 与主台账同底座（sha {master_sha[:12]}…）")
        print(f"[dry] 将执行：clean_ledger.py {period} --write（每工具自带冲突拒写 + 备份）")
        print("[dry] 写后五查：没删 / 旧格不动 / 新增归期 / 审写同值 / XML 良构")
        return 0
    _set_op(period, "merge", "running", "正在并入主台账（写前备份）")
    bak = LP.backup(LEDGER, tag=f"并入{period}前")
    print(f"[备份] {bak}")
    rc = _run([PY, REPO / "tools" / "clean_ledger.py", period, "--write"]
              + (["--snapshot", args.snapshot] if args.snapshot else [])
              + (["--esi-root", args.esi_root] if args.esi_root else []))
    checks = LM.write_after_checks(bak, LEDGER, copy_path, period)
    log = REPO / "out" / "_acquisition" / f"{period}-merge.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"at": _now(), "rc": rc, "checks": checks},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    if rc != 0 or not checks["ok"]:
        st = A.load_state(period) or st
        st["op"] = {"kind": "merge", "state": "failed",
                    "note": (f"清洗链退出码 {rc}；" if rc != 0 else "") +
                            "；".join(checks["reasons"][:3]), "at": _now()}
        st.setdefault("copy", {})["verify"] = checks
        A.write_state(period, st)
        print(f"[未宣告成功] 退出码 {rc}；核对问题见 {log}")
        for r in checks["reasons"][:8]:
            print("  -", r)
        print(f"  （备份可回退：{bak}）")
        return 1
    st = A.load_state(period) or st
    st["copy"] = {**(st.get("copy") or {}), "state": "merged", "merged_at": _now(), "verify": checks}
    st["op"] = {"kind": "merge", "state": "done",
                "note": f"已并入（新增 {checks.get('added_cells', 0)} 格 · 五查全过）", "at": _now()}
    A.write_state(period, st)
    print(f"[merge] 已并入主台账：新增/改动 {checks.get('added_cells', 0)} 格，五查全过。")
    return 0


# ------------------------------------------------------------------ preflight / fetch
_PROBE = r"""
import json, sys
out = {"browser": "bad", "esi": "waiting", "incites": "waiting"}
try:
    from playwright.sync_api import sync_playwright
    import urllib.request
    cdp = None
    for url in ("http://127.0.0.1:9222", "http://localhost:9222"):
        try:
            with urllib.request.urlopen(url + "/json/version", timeout=2) as r:
                if r.status == 200:
                    cdp = url; break
        except Exception:
            pass
    if not cdp:
        raise SystemExit(json.dumps(out))
    out["browser"] = "ok"
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(cdp)
        ctx = b.contexts[0] if b.contexts else None
        # ESI：页面在不在 + 会话可用性粗判（响应头 x-frame 无关；看正文是否登录页）
        if ctx:
            pg = next((x for x in ctx.pages if "esi.clarivate.com" in x.url), None)
            if pg:
                r = pg.request.get("https://esi.clarivate.com/IndicatorsAction.action?app=esi&Init=Yes",
                                   timeout=20000, max_redirects=3)
                body = r.text()[:4000].lower()
                out["esi"] = "bad" if ("sign in" in body or "log in" in body or "password" in body) else "ok"
            # InCites：/config 带 pssid = 会话可用（取数脚本同款判据）
            pg2 = next((x for x in ctx.pages if "incites.clarivate.com" in x.url), None) or pg
            if pg2:
                cfg = pg2.request.get("https://incites.clarivate.com/config", timeout=20000)
                out["incites"] = "ok" if cfg.headers.get("pssid") else "bad"
except Exception:
    pass
print(json.dumps(out))
"""


def cmd_preflight(args) -> int:
    r = subprocess.run([FETCH_PY, "-c", _PROBE], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    try:
        pf = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        pf = {"browser": "bad", "esi": "waiting", "incites": "waiting"}
    st = A.load_state(args.period) or A.scan(args.period)
    st["preflight"] = pf
    A.write_state(args.period, st)
    print(f"[preflight] {pf}")
    return 0


#: 9 组下载命令（顺序照《ESI数据下载流程》与 incites 流程；--out 直接落到归档目录）
def _fetch_steps(period: str, snapshot: str) -> list:
    esi = A.ESI_ROOT_DEFAULT / period
    inc = A.INCITES_ROOT_DEFAULT / snapshot
    esi_script = REPO / "tools" / "clarivate_esi_fetch.py"
    inc_script = REPO / "tools" / "clarivate_incites_fetch.py"
    return [
        ("esi-institutions", [FETCH_PY, esi_script, "institutions", "--out", esi]),
        ("esi-subjects", [FETCH_PY, esi_script, "subjects", "--out", esi]),
        ("esi-fields", [FETCH_PY, esi_script, "fields", "--out", esi]),
        ("esi-papers", [FETCH_PY, esi_script, "toppapers", "--out", esi]),
        ("esi-thresholds", [FETCH_PY, esi_script, "thresholds", "--out", esi]),
        ("esi-baselines", [FETCH_PY, esi_script, "baselines", "--out", esi]),
        ("incites-subjects", [FETCH_PY, inc_script, "subjects", "--out", inc]),
        ("incites-fields", [FETCH_PY, inc_script, "fields", "--out", inc]),
        ("incites-institutions", [FETCH_PY, inc_script, "institutions", "--out", inc]),
    ]


def cmd_fetch(args) -> int:
    period = args.period
    st = A.load_state(period) or A.scan(period)
    snapshot = st.get("snapshot") or A.resolve_snapshot(period, A.INCITES_ROOT_DEFAULT)
    if not snapshot:
        print("[拒绝] 认不出 InCites 快照目录——先跑一次 incites 任一条命令或给 SNAP_MAP 登记。")
        return 1
    st["snapshot"] = snapshot
    A.write_state(period, st)
    want = set(args.groups.split(",")) if args.groups else None
    _set_op(period, "fetch", "running", "正在按组下载（登录由馆员在专用浏览器完成）")
    failed = 0
    for gid, cmd in _fetch_steps(period, snapshot):
        if want is not None and gid not in want:
            continue
        st = _set_op(period, "fetch", "running", f"正在下载：{gid}")
        rc = _run(cmd)
        st = A.scan(period, snapshot=snapshot)
        g = next((x for x in st["groups"] if x["id"] == gid), None)
        if g and g["state"] == "pending":                 # 命令失败且一个文件都没落
            g["state"] = "fail"
        st["op"] = {"kind": "fetch", "state": "running", "note": f"{gid} 退出码 {rc}", "at": _now()}
        A.write_state(period, st)
        failed += 1 if rc else 0
    st = A.scan(period, snapshot=snapshot)
    A.write_state(period, st)
    _print_scan_summary(st, period)
    t = st["totals"]
    if failed or t["failed"]:
        _set_op(period, "fetch", "failed", f"{failed} 组命令失败 / {t['failed']} 份未通过核验")
        return 1
    if t["verified"] < t["expected"]:
        _set_op(period, "fetch", "done", f"取到 {t['verified']}/{t['expected']}（还有没取到的组，可 retry）")
        return 1
    if args.no_copy:
        _set_op(period, "fetch", "done", "全部核验通过（未自动建副本）")
        return 0
    _set_op(period, "fetch", "done", "全部核验通过，正在新建监测表")
    return cmd_copy(argparse.Namespace(period=period, out=None, snapshot=snapshot, esi_root=None))


def main() -> int:
    ap = argparse.ArgumentParser(description="取数模块编排器（scan/copy/merge/preflight/fetch）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("scan", help="扫下载包、逐文件核验、写状态")
    p1.add_argument("period")
    p1.add_argument("--snapshot", default=None)
    p1.add_argument("--esi-root", default=None)
    p1.set_defaults(fn=cmd_scan)

    p2 = sub.add_parser("copy", help="清洗链 --out 新建监测表副本 + 生成核对表")
    p2.add_argument("period")
    p2.add_argument("--out", default=None, help="默认 input/<期次>/监测表.xlsx")
    p2.add_argument("--snapshot", default=None)
    p2.add_argument("--esi-root", default=None)
    p2.set_defaults(fn=cmd_copy)

    p3 = sub.add_parser("merge", help="把已核对副本并入主台账（写前备份 + 写后五查）")
    p3.add_argument("period")
    p3.add_argument("--copy", default=None, help="默认读状态里的副本路径")
    p3.add_argument("--snapshot", default=None)
    p3.add_argument("--esi-root", default=None)
    p3.add_argument("--dry", action="store_true", help="只查守卫与计划，不落笔")
    p3.set_defaults(fn=cmd_merge)

    p4 = sub.add_parser("preflight", help="开始前检查（浏览器连接 / 两家网站登录）")
    p4.add_argument("period")
    p4.set_defaults(fn=cmd_preflight)

    p5 = sub.add_parser("fetch", help="按 9 组下载 → 自动 scan + copy")
    p5.add_argument("period")
    p5.add_argument("--groups", default=None, help="逗号分隔：只跑这几组（断组重试用）")
    p5.add_argument("--no-copy", action="store_true")
    p5.set_defaults(fn=cmd_fetch)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
