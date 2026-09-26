# -*- coding: utf-8 -*-
"""审批（签单）落库。

业务语义：机器把红件都替换完了，但「这期能不能报送」是人拍板的。
所以签单不该只是 UI 上的一次动画，而是一条要落盘、可追责、并且**绑住当时那份报告**的记录。

三件事：

1. **落盘**：`out/<期次>/approval.json`（含操作历史）+ 导出一份 `审批记录.md`。
2. **绑版本**：签单时给报告初稿与 `red_slots.json` 取指纹（mtime + size）。流水线一重跑，
   指纹就变了，签名立刻标记为 `stale`（已失效）——否则「签过」这两个字会跟着一份
   没人看过的稿子走，这是审批里最危险的事。
3. **闸门**：签之前必过
   - 机器断言无 FAIL；
   - 待人工 `【手工：…】` 若 > 0，必须显式勾选「已知悉并放行」（理由写进批注）。

不落库、不过闸的签单，等于没签。
"""
import json
import pathlib
import tempfile
import time

APPROVAL_NAME = "approval.json"
RECORD_NAME = "审批记录.md"

# 指纹覆盖的产物：任何一份变了，签名即失效
FINGERPRINT_GLOBS = ["red_slots.json", "报告初稿_*.docx", "table2.csv"]


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _paths(out_dir):
    out_dir = pathlib.Path(out_dir)
    return out_dir, out_dir / APPROVAL_NAME, out_dir / RECORD_NAME


def fingerprint(out_dir):
    """报告状态指纹：{文件名: size:mtime}。读不到的文件不进指纹。"""
    out_dir = pathlib.Path(out_dir)
    fp = {}
    for pat in FINGERPRINT_GLOBS:
        for p in sorted(out_dir.glob(pat)):
            try:
                st = p.stat()
            except OSError:
                continue
            fp[p.name] = f"{st.st_size}:{int(st.st_mtime)}"
    return fp


def read(out_dir):
    """读审批记录；不存在则返回未签单的初始结构（不落盘）。"""
    out_dir = pathlib.Path(out_dir)
    p = out_dir / APPROVAL_NAME
    if p.exists():
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(rec, dict):
                rec.setdefault("history", [])
                return rec
        except (OSError, json.JSONDecodeError):
            pass
    return {"signed": False, "actor": "", "signed_at": "", "note": "",
            "manual_ack": False, "snapshot": {}, "fingerprint": {}, "history": []}


def status(out_dir, rec=None):
    """unsigned | signed | stale（签过但报告已被重新生成）。"""
    rec = rec if rec is not None else read(out_dir)
    if not rec.get("signed"):
        return "unsigned"
    if rec.get("fingerprint") != fingerprint(out_dir):
        return "stale"
    return "signed"


def sign(out_dir, actor, data, note="", manual_ack=False):
    """签单。返回 (ok, rec_or_error)。

    闸门不过就拒绝落盘——这是审批门的意义所在。
    """
    out_dir, p, _ = _paths(out_dir)
    rec = read(out_dir)
    counts = (data or {}).get("counts") or {}
    assertions = (data or {}).get("assertions") or {}

    if status(out_dir, rec) == "signed":
        return False, "本期已签单，无需重复"
    if assertions.get("fail"):
        return False, f"机器断言有 {assertions['fail']} 项未过，闸门未放行"
    if counts.get("manual") and not manual_ack:
        return False, f"仍有 {counts['manual']} 处待人工补录项，需显式确认「已知悉并放行」"

    rec.update({
        "signed": True,
        "actor": actor,
        "signed_at": _now(),
        "note": (note or "").strip(),
        "manual_ack": bool(manual_ack),
        "period": (data or {}).get("period") or out_dir.name,
        "snapshot": {
            "counts": counts,
            "assertions": assertions,
            "bigtable": (data or {}).get("bigtable") or {},
        },
        "fingerprint": fingerprint(out_dir),
        "revoked_at": "",
    })
    rec.setdefault("history", []).append({
        "action": "sign", "actor": actor, "at": rec["signed_at"],
        "note": rec["note"], "manual_ack": bool(manual_ack),
        "manual_open": counts.get("manual", 0),
    })
    if not _write(p, rec):
        return False, "审批记录写入失败，签发未生效"
    _write_record(out_dir, rec)
    return True, rec


def revoke(out_dir, actor, note=""):
    """撤回签单（保留历史，不删记录）。"""
    out_dir, p, _ = _paths(out_dir)
    rec = read(out_dir)
    if not rec.get("signed"):
        return False, "本期尚未签单"
    rec.update({
        "signed": False,
        "revoked_at": _now(),
        "revoke_note": (note or "").strip(),
        "revoke_actor": actor,
    })
    rec.setdefault("history", []).append({
        "action": "revoke", "actor": actor, "at": rec["revoked_at"],
        "note": (note or "").strip(),
    })
    if not _write(p, rec):
        return False, "审批记录写入失败，撤回未生效"
    _write_record(out_dir, rec)
    return True, rec


def _write(path, obj):
    path = pathlib.Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = pathlib.Path(temp_file.name)
            temp_file.write(json.dumps(obj, ensure_ascii=False, indent=1))
        temp_path.replace(path)
        return True
    except OSError:
        return False
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _write_record(out_dir, rec):
    """导出人可读的《审批记录.md》——给不了系统的人也能看懂谁在什么时候放了什么行。"""
    st = status(out_dir, rec)
    snap = rec.get("snapshot") or {}
    c = snap.get("counts") or {}
    a = snap.get("assertions") or {}
    lines = [
        f"# 审批记录 · {rec.get('period') or out_dir.name} 期", "",
        f"- 当前状态：**{'已签单' if st == 'signed' else '已失效（签单后报告被重新生成）' if st == 'stale' else '未签单'}**",
    ]
    if rec.get("signed"):
        lines += [
            f"- 签单人：{rec.get('actor', '')}",
            f"- 签单时间：{rec.get('signed_at', '')}",
            f"- 批注：{rec.get('note') or '（无）'}",
            f"- 待人工项知悉：{'是' if rec.get('manual_ack') else '否'}",
        ]
    lines += [
        "", "## 签单时快照", "",
        f"- 槽位总数：{c.get('total', '—')}（文字 {c.get('text', '—')} / 大表 {c.get('cell', '—')} / 图表 {c.get('chart', '—')}）",
        f"- 待人工补录：{c.get('manual', '—')} 处",
        f"- 机器断言：{(a.get('total', 0) - a.get('fail', 0))}/{a.get('total', 0)}"
        + (f"（{a.get('fail')} 项未过）" if a.get("fail") else " 全绿"),
        "", "## 操作历史", "",
        "| 时间 | 动作 | 操作人 | 待人工 | 说明 |", "|---|---|---|---|---|",
    ]
    for h in rec.get("history", []):
        act = {"sign": "签单", "revoke": "撤回"}.get(h.get("action"), h.get("action", ""))
        lines.append("| {} | {} | {} | {} | {} |".format(
            h.get("at", ""), act, h.get("actor", ""),
            h.get("manual_open", "—"), (h.get("note") or "—").replace("|", "／")))
    if st == "stale":
        lines += ["", "> 报告初稿或红色件数据在签单之后被重新生成，本次签单不再对应当前稿件，需重新核对并签单。"]
    try:
        (out_dir / RECORD_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
