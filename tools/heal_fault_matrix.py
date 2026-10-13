# -*- coding: utf-8 -*-
"""自愈故障注入矩阵实测 —— 给申报书回填「自愈成功率 / 升级率」提供真实数字。

只跑 parse 步（自愈发生在这步），每例独立 out/run 目录，台账原件 sha256 前后比对。
输出 JSON + 控制台表格。
"""
import io, json, pathlib, shutil, sys, tempfile, hashlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO = pathlib.Path(__file__).resolve().parent.parent   # wenheng/
for sub in ("src", "tools", "tests"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import openpyxl, re, zipfile
from xml.sax.saxutils import escape, unescape

from test_agent_heal import _sheet_xml, _si_texts       # noqa: E402
from agent import flow, states                          # noqa: E402


def corrupt_cell_text(src, dst, sheet, old, new):
    """同 tests/test_agent_heal.corrupt_cell_text，但共享字符串做 XML 实体反转义。

    原版把 `<t>Plant &amp; Animal Science</t>` 读成 `Plant &amp; Animal Science`，
    于是含 `&` 的学科名永远匹配不上（实测用例 4/5 因此脏化失败）。
    这里读写两端都做实体处理，不改测试文件本身。
    """
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

    texts = [unescape(t) for t in _si_texts(ss)]
    if old not in texts:
        raise LookupError(f"{sheet}!{coord} 的值 {old!r} 不在共享字符串表里")
    if new in texts:
        new_idx = texts.index(new)
    else:
        new_idx = len(texts)
        ss = re.sub(r"</sst>\s*$", f"<si><t>{escape(new)}</t></si></sst>", ss)
        assert new_idx in range(len(_si_texts(ss))), "追加共享字符串失败"

    m = re.search(r'<c r="%s"([^>]*?)(?:/>|>.*?</c>)' % coord, xml, re.S)
    assert m, f"工作表 XML 里找不到单元格 {coord}"
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

LED = REPO / "out" / "_acquisition" / "202607" / "监测表.xlsx"   # 202607 当期核对副本
assert LED.exists(), "缺 202607 当期核对副本（out/_acquisition/202607/监测表.xlsx）"
print("台账:", LED)

#  (用例名, 原值, 脏值, 预期: heal=应自愈成功 / escalate=应升级)
CASES = [
    ("学科名中文化",        "Chemistry",              "化学",                      "heal"),
    ("英文别名·空格变体",   "Environment/Ecology",    "Environment / Ecology",     "heal"),
    ("英文别名·缩写",       "Social Sciences, general", "Social Sciences",         "heal"),
    ("英文别名·and 变体",   "Plant & Animal Science", "Plant and Animal Science",  "heal"),
    ("英文别名·神经科学",   "Neuroscience & Behavior", "Neuroscience and Behavior", "heal"),
    ("规则库认不出的名字",  "Chemistry",              "某某新学科",                "escalate"),
]

results = []
tmp_root = pathlib.Path(tempfile.mkdtemp(prefix="heal_matrix_"))
try:
    for i, (name, old, new, expect) in enumerate(CASES, 1):
        case_dir = tmp_root / f"case{i}"
        case_dir.mkdir(parents=True)
        dirty = case_dir / "监测表.xlsx"
        try:
            coord = corrupt_cell_text(LED, dirty, "总被引", old, new)
        except LookupError as e:
            results.append({"case": name, "error": f"脏化失败: {e}"})
            print(f"[{i}] {name}: 脏化失败 {e}")
            continue

        before = hashlib.sha256(dirty.read_bytes()).hexdigest()
        flow.STEPS = tuple(s for s in flow.STEPS if s["id"] == "parse")
        try:
            r = flow.run(str(dirty), out_root=case_dir / "out", run_dir=case_dir / "run")
        except Exception as e:  # noqa: BLE001
            results.append({"case": name, "error": f"运行异常: {type(e).__name__}: {e}"})
            print(f"[{i}] {name}: 运行异常 {e}")
            continue
        after = hashlib.sha256(dirty.read_bytes()).hexdigest()

        rec = {
            "case": name,
            "inject": f"{old} -> {new}",
            "coord": coord,
            "status": r.status,
            "expect": expect,
            "attempts": [s["attempt"] for s in r.steps],
            "rules": [x.get("rules") for x in (r.repairs or [])],
            "ledger_unchanged": before == after,
            "diag": bool((case_dir / "run" / "诊断报告.md").exists()),
        }
        ok = ((expect == "heal" and r.status == states.COMPLETED)
              or (expect == "escalate" and r.status == states.ESCALATED))
        rec["pass"] = ok and rec["ledger_unchanged"]
        results.append(rec)
        print(f"[{i}] {name:16s} {r.status:10s} expect={expect:8s} "
              f"attempts={rec['attempts']} 原件未改={rec['ledger_unchanged']} pass={rec['pass']}")
finally:
    pass

n = len([r for r in results if "pass" in r])
good = len([r for r in results if r.get("pass")])
heal_cases = [r for r in results if r.get("expect") == "heal"]
heal_ok = len([r for r in heal_cases if r.get("pass")])
esc_cases = [r for r in results if r.get("expect") == "escalate"]
esc_ok = len([r for r in esc_cases if r.get("pass")])

print("\n==== 汇总 ====")
print(f"总用例 {n}，符合预期 {good}")
print(f"可自愈形态 {len(heal_cases)} 例，自愈后断言全过 {heal_ok} 例")
print(f"不可自愈形态 {len(esc_cases)} 例，按设计升级 {esc_ok} 例")
print(f"台账原件改动 0 例: {all(r.get('ledger_unchanged') for r in results if 'ledger_unchanged' in r)}")

out = REPO / "tmp" / "heal_matrix_result.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("结果 ->", out)
print("临时目录保留:", tmp_root)
