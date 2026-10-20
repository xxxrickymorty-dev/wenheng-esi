# -*- coding: utf-8 -*-
"""自愈沙盘（决赛演示用）：复制真实台账 → 一处 zip 级脏化 → flow 只跑 parse。

用法（在 wenheng/ 下）：
    uv run python tools\\heal_sandbox.py

它回答三个问题：
1. 系统会不会把「学科名中英混排」当成 22 个学科少了 1 个而拦停？——会。
2. 它能不能自己认出「化学」就是 Chemistry，改解析口径后重跑通过？——能。
3. 改的是台账吗？——不是；脏件与原件哈希前后都不变。

红线：只读 input/ 的原件；所有写入都在 tmp/_heal_sandbox/ 里。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import re
import shutil
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import openpyxl                                                  # noqa: E402

from agent import flow, states                                   # noqa: E402

WORK = REPO / "tmp" / "_heal_sandbox"
LEDGER_NAME = "云大全学科排名、阈值动态检测表.xlsx"


def _sheet_xml(zf, title):
    wb = zf.read("xl/workbook.xml").decode("utf-8")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rid = None
    for tag in re.finditer(r"<sheet\b[^>]*>", wb):
        t = re.search(r'name="([^"]*)"', tag.group(0))
        r = re.search(r'r:id="([^"]*)"', tag.group(0))
        if t and r and t.group(1) == title:
            rid = r.group(1)
            break
    if rid is None:
        raise LookupError(f"台账无工作表 {title}")
    m = re.search(r'Id="%s"[^>]*Target="([^"]*)"' % re.escape(rid), rels)
    target = m.group(1).lstrip("/")
    return target if target.startswith("xl/") else "xl/" + target.lstrip("./")


def _si_texts(ss):
    return ["".join(re.findall(r"<t[^>]*>(.*?)</t>", blk, re.S))
            for blk in re.findall(r"<si>(.*?)</si>", ss, re.S)]


def corrupt_cell_text(src, dst, sheet, old, new):
    """把某工作表首列里第一个等于 old 的单元格改成 new；只动 sheet + sharedStrings。"""
    with zipfile.ZipFile(src) as zf:
        sheet_path = _sheet_xml(zf, sheet)
        xml = zf.read(sheet_path).decode("utf-8")
        ss = zf.read("xl/sharedStrings.xml").decode("utf-8")

    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    try:
        row = next(r[0].row for r in wb[sheet].iter_rows(min_col=1, max_col=1)
                   if r[0].value == old)
    finally:
        wb.close()
    coord = f"A{row}"

    texts = _si_texts(ss)
    if old not in texts:
        raise LookupError(f"{sheet}!{coord} 的值 {old!r} 不在共享字符串表里")
    if new in texts:
        new_idx = texts.index(new)
    else:
        new_idx = len(texts)
        ss = re.sub(r"</sst>\s*$", f"<si><t>{new}</t></si></sst>", ss)

    m = re.search(r'<c r="%s"([^>]*?)(?:/>|>.*?</c>)' % coord, xml, re.S)
    if not m:
        raise LookupError(f"工作表 XML 里找不到单元格 {coord}")
    style = re.search(r'\bs="(\d+)"', m.group(1))
    cell = (f'<c r="{coord}"' + (f' s="{style.group(1)}"' if style else "")
            + f' t="s"><v>{new_idx}</v></c>')
    xml = xml[:m.start()] + cell + xml[m.end():]

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == sheet_path:
                data = xml.encode("utf-8")
            elif item.filename == "xl/sharedStrings.xml":
                data = ss.encode("utf-8")
            zout.writestr(item, data)
    return coord


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def find_ledger():
    for p in (REPO / "input" / LEDGER_NAME,
              REPO.parent / "数据与复现" / LEDGER_NAME):
        if p.exists():
            return p
    raise SystemExit(f"找不到台账：{LEDGER_NAME}")


def main() -> int:
    src = find_ledger()
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True, exist_ok=True)
    dirty = WORK / "监测表_脏.xlsx"
    coord = corrupt_cell_text(src, dirty, "总被引", "Chemistry", "化学")

    src_before, dirty_before = sha256(src), sha256(dirty)
    print("=" * 64)
    print("自愈沙盘 · 一处脏：总被引!" + coord + "  Chemistry → 化学")
    print(f"原件  {src.name}  sha256={src_before[:16]}…")
    print(f"脏件  {dirty.name}  sha256={dirty_before[:16]}…")
    print("=" * 64)

    # 只跑 parse：自愈发生在这一步；不重画 99 张图，演示更快。
    flow.STEPS = tuple(s for s in flow.STEPS if s["id"] == "parse")
    r = flow.run(str(dirty), out_root=WORK / "out", run_dir=WORK / "run")

    print(f"\n终态：{r.status}")
    print(f"尝试：{[s['attempt'] for s in r.steps]}")
    for rep in r.repairs or []:
        print(f"自愈：{rep.get('rules')} · {rep.get('outcome')} · overlay={list((rep.get('overlay') or {}).keys())}")
    repair_yaml = WORK / "run" / "repair.yaml"
    if repair_yaml.exists():
        print("\nrepair.yaml：")
        print("\n".join("  " + ln for ln in repair_yaml.read_text(encoding="utf-8").splitlines()[:18]))
    diag = WORK / "run" / "诊断报告.md"
    if diag.exists():
        print(f"\n诊断报告：{diag.relative_to(REPO)}")

    src_after, dirty_after = sha256(src), sha256(dirty)
    print("\n" + "=" * 64)
    print(f"原件哈希不变：{src_before == src_after}")
    print(f"脏件哈希不变：{dirty_before == dirty_after}")
    print("=" * 64)

    ok = (r.status == states.COMPLETED
          and [s["attempt"] for s in r.steps] == [1, 2]
          and any("discipline_alias_map" in (rep.get("rules") or []) for rep in (r.repairs or []))
          and src_before == src_after and dirty_before == dirty_after)
    rules = [rule for rep in (r.repairs or []) for rule in (rep.get("rules") or [])]
    story = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ledger": src.name,
        "dirty_cell": f"总被引!{coord}",
        "old": "Chemistry",
        "new": "化学",
        "src_sha256": src_before,
        "dirty_sha256": dirty_before,
        "src_unchanged": src_before == src_after,
        "dirty_unchanged": dirty_before == dirty_after,
        "status": r.status,
        "attempts": [s["attempt"] for s in r.steps],
        "rules": rules,
        "outcome": (r.repairs or [{}])[0].get("outcome", ""),
        "failure": str(r.failure or (r.repairs or [{}])[0].get("error_message") or "")[:300],
        "ok": ok,
    }
    (WORK / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n故事卡：{(WORK / 'story.json').relative_to(REPO)}")
    print("结论：" + ("一次自愈成功，台账原件与脏件都零字节改动。" if ok else "未按预期完成，见上。"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
