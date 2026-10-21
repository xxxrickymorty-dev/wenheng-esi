# -*- coding: utf-8 -*-
"""自愈沙盘（决赛演示用）：复制真实台账 → 一处 zip 级脏化 → flow 只跑 parse。

用法（在 wenheng/ 下）：
    uv run python tools\\heal_sandbox.py

它回答三个问题：
1. 系统会不会把「学科名中英混排」当成 22 个学科少了 1 个而拦停？——会。
2. 它能不能自己认出「化学」就是 Chemistry，改解析口径后重跑通过？——能。
3. 改的是台账吗？——不是；脏件与原件哈希前后都不变。

红线：只读 input/ 的原件；所有写入都在 tmp/_heal_sandbox/ 里。
定位、复制、指纹走 `ledger_contract`；脏化只改目标 sheet 与 sharedStrings，
落盘统一过 `xlsx_io.rewrite` 的良构闸（坏 XML 拒绝写、其余成员逐字节原样）。
"""
from __future__ import annotations

import datetime
import html
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

import ledger_contract as contract                               # noqa: E402
import ledger_patch                                              # noqa: E402
import xlsx_io                                                   # noqa: E402
from agent import flow, states                                   # noqa: E402

WORK = REPO / "tmp" / "_heal_sandbox"


def corrupt_cell_text(path, sheet, old, new):
    """把某工作表首列里第一个等于 `old` 的单元格改成 `new`（原地改）。

    只动目标 sheet（真台账再加 sharedStrings）；其余条目不经过内存重写，
    由 `xlsx_io.rewrite` 逐字节复制。良构闸不过 → `SystemExit`，文件一字节不动。
    """
    grid, shared = ledger_patch.read_grid(path, sheet)
    row = ledger_patch.locate(grid, shared, "A", old, by="col")
    coord = f"A{row}"

    with zipfile.ZipFile(path) as zf:
        sheet_path = xlsx_io.member_of(zf, sheet)
        xml = zf.read(sheet_path).decode("utf-8")
        has_shared = "xl/sharedStrings.xml" in zf.namelist()
        texts = xlsx_io.read_shared_strings(zf) if has_shared else []
        ss = zf.read("xl/sharedStrings.xml").decode("utf-8") if has_shared else None

    # 真台账走共享串表；openpyxl 合成件写行内字符串（t="inlineStr"）。两条路都认。
    attrs, inner = grid[row].get("A", ("", None))
    use_shared = has_shared and not (inner and "<is>" in inner)
    if use_shared:
        if old not in texts:
            raise LookupError(f"{sheet}!{coord} 的值 {old!r} 不在共享字符串表里")
        if new in texts:
            new_idx = texts.index(new)
        else:
            new_idx = len(texts)
            ss = re.sub(r"</sst>\s*$",
                        f"<si><t>{html.escape(new)}</t></si></sst>", ss)
        value = f"<v>{new_idx}</v>"
        cell_type = ' t="s"'
        payload = {sheet_path: xml, "xl/sharedStrings.xml": ss}
    else:
        value = f"<is><t>{html.escape(new)}</t></is>"
        cell_type = ' t="inlineStr"'
        payload = {sheet_path: xml}

    # 单元格坐标要卡边界：`A2` 不能误中 `A20`。
    m = re.search(r'<c r="%s"(?=[\s/>])([^>]*?)(?:/>|>.*?</c>)' % coord, xml, re.S)
    if not m:
        raise LookupError(f"工作表 XML 里找不到单元格 {coord}")
    style = re.search(r'\bs="(\d+)"', attrs or "")
    cell = (f'<c r="{coord}"' + (f' s="{style.group(1)}"' if style else "")
            + cell_type + f">{value}</c>")
    xml = xml[:m.start()] + cell + xml[m.end():]

    payload[sheet_path] = xml
    xlsx_io.rewrite(path, payload)
    return coord


def main() -> int:
    src = contract.require(REPO)
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True, exist_ok=True)
    dirty = contract.sandbox_copy(src, WORK / "监测表_脏.xlsx", refresh=True)
    coord = corrupt_cell_text(dirty, "总被引", "Chemistry", "化学")

    src_before, dirty_before = contract.sha256(src), contract.sha256(dirty)
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

    src_after, dirty_after = contract.sha256(src), contract.sha256(dirty)
    print("\n" + "=" * 64)
    print(f"原件哈希不变：{src_before == src_after}")
    print(f"脏件哈希不变：{dirty_before == dirty_after}")
    print("=" * 64)

    ok = (r.status == states.COMPLETED
          and [s["attempt"] for s in r.steps] == [1, 2]
          and any("discipline_alias_map" in (rep.get("rules") or []) for rep in (r.repairs or []))
          and src_before == src_after and dirty_before == dirty_after)
    rules = [rule for rep in (r.repairs or []) for rule in (rep.get("rules") or [])]
    events = []
    events_path = WORK / "run" / "agent_events.jsonl"
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append({k: e[k] for k in
                           ("ts", "phase", "tool", "observation", "decision", "reason")
                           if e.get(k)})

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
        "events": events[:12],
        "ok": ok,
    }
    (WORK / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n故事卡：{(WORK / 'story.json').relative_to(REPO)}")
    print("结论：" + ("一次自愈成功，台账原件与脏件都零字节改动。" if ok else "未按预期完成，见上。"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
