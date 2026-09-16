# -*- coding: utf-8 -*-
"""Agent 层 M3 · 自愈闭环测试（SRS R-23 / R-24 / R-26；WH-DOC-04 §6.5）。

四层，由内向外：

  1. **规则库本身** —— 结构与口径（别名表必须覆盖全部 22 个学科的中文名）
  2. **执行闸** —— 未确认的规则类型必须被拒绝（R-24 的可核验判据）
  3. **解析口径** —— overlay 真的改变"怎么读"，且默认口径逐字不变
  4. **端到端脏例** —— 真实台账 + 一处人为脏化：拦停 → 自愈 → 断言全过，且**原件零改动**

第 4 层依赖馆员台账（`input/`，不入库），故缺数据时 `skip` 而非 fail。
脏化方式为 **zip 级 XML 替换**（不是 openpyxl 存盘）—— 后者会抹掉公式缓存值，
把"一处脏"变成"满表脏"，测出来的就不是自愈能力了。
"""
import hashlib
import json
import pathlib
import re
import zipfile

import openpyxl
import pytest

from agent import flow, heal, states, tools
from parse_ledger import DISCIPLINES_CN, DISCIPLINES_EN, _parse_scope, parse_wide


# ============================================================ 工具：zip 级脏化
def _sheet_xml(zf, title):
    """工作表名 → 它在 zip 里的 XML 路径（走 workbook.xml + rels，不猜 sheetN）。"""
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
    """把某工作表**首列**里第一个等于 `old` 的单元格改成 `new`。

    只动两个 XML：目标 sheet + sharedStrings。其余条目**逐字节原样搬运**，
    所以公式、图表、条件格式、缓存值全部保住 —— 这就是"一处脏"。
    """
    with zipfile.ZipFile(src) as zf:
        sheet_path = _sheet_xml(zf, sheet)
        xml = zf.read(sheet_path).decode("utf-8")
        ss = zf.read("xl/sharedStrings.xml").decode("utf-8")

    # 定位要改的行（用 openpyxl 只读找，不改）
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


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# ============================================================ 工具：假工作表
class FakeWS:
    """只实现 parse_* 用到的那点接口（title + iter_rows）。"""

    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def iter_rows(self, values_only=True, **kw):
        assert values_only
        return iter(self._rows)


def wide_rows(header, first_col_values):
    return [header] + [[v] + [1.0] * (len(header) - 1) for v in first_col_values]


def parse_diag(rows, title="总被引", **kw):
    """跑一次 parse_wide 并取回 (df, diag)——诊断通道就是断言与报告的眼睛。"""
    diag = {}
    df = parse_wide(FakeWS(title, rows), [], diag=diag, **kw)
    return df, diag


def known(diag, title="总被引"):
    return set((diag.get("known_names") or {}).get(title, []))


def unknown(diag, title="总被引"):
    return (diag.get("unknown_names") or {}).get(title, [])


# ============================================================ 1. 规则库
def test_规则库六条且错误码在文档全集内():
    rules = heal.load_rules()
    assert len(rules) == 6, "WH-DOC-04 §6.5 首批 6 类"
    assert len({r["id"] for r in rules}) == 6
    for r in rules:
        assert r["code"] in tools.ERROR_CODES, r["id"]


def test_每条规则都说清了依据与可执行档位():
    for r in heal.load_rules():
        assert r.get("doc"), f"{r['id']} 没写文档依据"
        assert r["executable"] in (heal.AUTO, heal.DECLARE, heal.NEVER)


def test_别名表覆盖全部22个学科的中文名_防漂移():
    """学科名单改了而规则库没跟上 → 中文名会再次静默丢行。这条断言就是防这个。"""
    alias = {}
    for r in heal.load_rules():
        alias.update((r.get("overlay") or {}).get("discipline_alias") or {})
    # DISCIPLINES_CN 是 {英文规范名: 中文名}；别名表是 {别名: 英文规范名}
    missing = [cn for cn in DISCIPLINES_CN.values() if cn not in alias]
    assert not missing, f"别名表缺中文名：{missing}"
    wrong = {cn: alias[cn] for en, cn in DISCIPLINES_CN.items() if alias[cn] != en}
    assert not wrong, f"别名映射与 DISCIPLINES_CN 不一致：{wrong}"
    assert len(DISCIPLINES_EN) == 22


def test_规则库缺文件时抛错而非静默空库(tmp_path):
    with pytest.raises(heal.RuleError):
        heal.load_rules(tmp_path / "不存在.yaml")


# ============================================================ 2. 执行闸（R-24）
def test_未确认的规则被拒绝执行():
    """R-24 的可核验判据：未确认规则被拒绝执行。"""
    with pytest.raises(tools.ToolError) as e:
        tools.call("apply_repair_rule", rule="header_offset")
    assert e.value.code == "RULE_UNAPPROVED"
    assert e.value.detail.get("advice"), "拒绝时必须给出人工处置建议"


def test_不可修复的规则不给过():
    with pytest.raises(tools.ToolError) as e:
        tools.call("apply_repair_rule", rule="append_period_column")
    assert e.value.code == "RULE_UNAPPROVED"


def test_不存在的规则被拒绝():
    with pytest.raises(tools.ToolError) as e:
        tools.call("apply_repair_rule", rule="我自己编的规则")
    assert e.value.code == "RULE_UNAPPROVED"


def test_已确认规则能取出overlay():
    out = tools.call("apply_repair_rule", rule="normalize_period")
    assert out["overlay"] == {"normalize_period": True}


# ============================================================ 3. 匹配与落盘
def _assert_fail(text, **extra):
    return {"code": "ASSERT_FAIL", "message": "1 项断言未过",
            "fails": [text], "step": "parse", **extra}


def test_规则库无匹配时返回None():
    r = heal.attempt({"code": "MISSING_PERIOD", "message": "缺期次"}, {})
    assert r is None, "错误码都不沾边就不该假装有方案"


def test_命中学科数断言时给出别名overlay(tmp_path):
    ctx = {"run_dir": str(tmp_path)}
    r = heal.attempt(_assert_fail("宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"), ctx)
    assert "discipline_alias_map" in r["rules"]
    assert "化学" in r["overlay"]["discipline_alias"]
    assert ctx["overlay"] is r["overlay"], "overlay 必须挂到 ctx 上，否则重跑还是旧口径"
    assert (tmp_path / "repair.yaml").exists()
    y = (tmp_path / "repair.yaml").read_text(encoding="utf-8")
    for field in ("rule:", "params:", "reason:", "approved_by:"):
        assert field in y, f"repair.yaml 缺文档规定的字段 {field}"


def test_一次自愈把能命中的规则全用上():
    """自愈只有一次机会（MAX_HEAL_ATTEMPTS=1），所以不能只挑第一条规则。"""
    ctx = {}
    r = heal.attempt(_assert_fail("宽表 cnci 学科数=22 (实际 21，缺 ['Physics']) · "
                                  "宽表 cnci 202609 列为空（下期未贴数）"), ctx)
    assert set(r["rules"]) >= {"discipline_alias_map", "normalize_period"}
    assert set(r["overlay"]) == {"discipline_alias", "normalize_period"}


def test_命中但未确认的规则进建议而非overlay(tmp_path):
    ctx = {"run_dir": str(tmp_path)}
    r = heal.attempt(_assert_fail("新国际排名 期组数≥5"), ctx)
    assert not r["overlay"], "未确认规则不得进入 overlay"
    assert r["outcome"] == "refused"
    assert any(a["rule"] == "header_offset" for a in r["advice"])
    assert r["advice"][0]["advice"], "建议必须写出来，否则人工不知道该干什么"


def test_自愈钩子永不抛异常():
    """它在主干上：抛出去会把"台账脏"变成"程序崩"，两者必须分得很清楚。"""
    for bad in (None, {}, {"code": "ASSERT_FAIL"}, {"code": "ASSERT_FAIL", "fails": None},
                {"code": None, "message": None}):
        heal.attempt(bad, {})       # 不抛即通过


def test_编排把overlay传给run_parse(monkeypatch, tmp_path):
    seen = {}
    real_call = tools.call

    def spy(name, **kw):
        if name == "run_parse":
            seen.update(kw)
            return {"ok": True, "period": "202607", "out_dir": "x"}
        return real_call(name, **kw)

    monkeypatch.setattr(tools, "call", spy)
    monkeypatch.setattr(flow, "_heal_hook",
                        lambda failure, ctx: (ctx.update({"overlay": {"normalize_period": True}})
                                              or {"overlay": {"normalize_period": True},
                                                  "rules": ["normalize_period"],
                                                  "outcome": "repaired", "refused": [],
                                                  "advice": []}))
    n = {"i": 0}

    def behaviour(sid):
        if sid == "parse":
            n["i"] += 1
            if n["i"] == 1:
                raise tools.ToolError("ASSERT_FAIL", "1 项断言未过",
                                      fails=["宽表 cnci 202609 列为空（下期未贴数）"])
        return {"ok": True, "period": "202607", "out_dir": "x"}

    monkeypatch.setattr(flow, "_invoke", lambda step, ctx, result: behaviour(step["id"]))
    r = flow.run("fake.xlsx", out_root=tmp_path / "o", run_dir=tmp_path / "r")
    assert r.status == states.COMPLETED
    assert r.repairs and r.repairs[0]["rules"] == ["normalize_period"]
    assert (tmp_path / "r" / "run_result.json").exists()
    assert "repairs" in json.loads((tmp_path / "r" / "run_result.json").read_text(encoding="utf-8"))


def test_自愈逾限的诊断报告写清了自愈过程(monkeypatch, tmp_path):
    def behaviour(step, ctx, result):
        if step["id"] == "parse":
            raise tools.ToolError("ASSERT_FAIL", "1 项断言未过",
                                  fails=["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
                                  diagnostics={})
        return {"ok": True, "period": "202607", "out_dir": "x"}

    monkeypatch.setattr(flow, "_invoke", behaviour)
    r = flow.run("fake.xlsx", out_root=tmp_path / "o", run_dir=tmp_path / "r")
    assert r.status == states.ESCALATED
    doc = (tmp_path / "r" / "诊断报告.md").read_text(encoding="utf-8")
    assert "## 自愈过程" in doc and "已应用规则" in doc


# ============================================================ 4. 解析口径（纯函数）
def test_默认口径逐字不变_不归一不映射():
    rows = wide_rows(["学科", "2023.3"], ["Chemistry", "Plant and Animal Science"])
    df, diag = parse_diag(rows)
    assert list(df.columns) == ["2023.3"], "默认不该动期次写法"
    assert known(diag) == {"Chemistry"}, "默认不该认别名"
    assert "Plant and Animal Science" in unknown(diag)


def test_别名overlay能把中英混排救回来():
    rows = wide_rows(["学科", "202607"], ["化学", "Physics"])
    _df, diag = parse_diag(rows, alias={"化学": "Chemistry"})
    assert known(diag) == {"Chemistry", "Physics"}
    assert unknown(diag) == []


def test_脏期次overlay归一到YYYYMM():
    rows = wide_rows(["学科", "2023.3", "2023-05", "2023年7月", "202311"],
                     ["Chemistry"])
    df, _ = parse_diag(rows, normalize=True)
    assert list(df.columns) == ["202303", "202305", "202307", "202311"]


def test_表头行偏移overlay生效():
    """表头偏移的症状是**期次列整列丢失**（学科列照样能认出来），
    所以机器不猜行号 —— 猜错会整体错位且一声不响。"""
    rows = [["某期 ESI 学科数据（内部）", None],
            ["学科", "202607"],
            ["Chemistry", 1.0]]
    df0, diag0 = parse_diag(rows)
    assert list(df0.columns) == [], "默认口径下期次表头读不到（这正是故障现场）"
    assert known(diag0) == {"Chemistry"}, "学科列不受表头偏移影响"

    df, diag = parse_diag(rows, header_row=1)
    assert list(df.columns) == ["202607"]
    assert known(diag) == {"Chemistry"}


def test_诊断不写进产物_parquet字节可复现(tmp_path):
    """pandas 3 会把 df.attrs 写进 parquet 元数据。诊断必须走独立通道，
    否则每次改动诊断内容都会改动全部宽表产物的字节，"金样回测按哈希比对"就废了。"""
    import pandas as pd
    rows = wide_rows(["学科", "202607"], ["Chemistry"])
    a, _ = parse_diag(rows)
    b, _ = parse_diag(rows)
    fa, fb = tmp_path / "a.parquet", tmp_path / "b.parquet"
    a.to_parquet(fa)
    b.to_parquet(fb)
    assert not a.attrs, "parse_wide 不该往 DataFrame 上挂 attrs"
    assert fa.read_bytes() == fb.read_bytes()


# ============================================================ 5. 端到端脏例（需真实台账）
@pytest.fixture(scope="module")
def ledger_path():
    leds = sorted((pathlib.Path(__file__).resolve().parent.parent / "input")
                  .glob("*/监测表.xlsx"))
    if not leds:
        pytest.skip("input/ 下无台账（馆员数据不入库，属正常）")
    return leds[-1]


@pytest.fixture(scope="module")
def dirty_alias_ledger(ledger_path, tmp_path_factory):
    """真实台账 + 一处脏：首列 Chemistry → 化学。别名规则可救。"""
    d = tmp_path_factory.mktemp("dirty")
    dst = d / "监测表.xlsx"
    coord = corrupt_cell_text(ledger_path, dst, "总被引", "Chemistry", "化学")
    return {"path": dst, "coord": coord, "src": ledger_path}


@pytest.fixture(scope="module")
def dirty_unknown_ledger(ledger_path, tmp_path_factory):
    """真实台账 + 规则库救不了的脏：改成谁都不认识的名字。"""
    d = tmp_path_factory.mktemp("dirty2")
    dst = d / "监测表.xlsx"
    corrupt_cell_text(ledger_path, dst, "总被引", "Chemistry", "某某新学科")
    return {"path": dst, "src": ledger_path}


def test_脏化只改一个格_其余逐字不变(dirty_alias_ledger):
    """先自证夹具干净，否则后面测的是别的东西。"""
    a = openpyxl.load_workbook(dirty_alias_ledger["src"], read_only=True, data_only=True)
    b = openpyxl.load_workbook(dirty_alias_ledger["path"], read_only=True, data_only=True)
    try:
        diff = [(c, ra[0], rb[0])
                for c, (ra, rb) in enumerate(zip(a["总被引"].iter_rows(values_only=True),
                                                 b["总被引"].iter_rows(values_only=True)))
                if ra != rb]
        assert len(diff) == 1, f"应只差一行，实际 {len(diff)} 行：{diff[:3]}"
    finally:
        a.close()
        b.close()


def test_学科名写错时断言点名到具体学科(dirty_alias_ledger, tmp_path):
    """⚠ 回归护栏：宽表 reindex 后 df.index 恒为 22 个规范名，
    若断言用 df.index 判名单，这两条断言会**恒真**——学科名写错也放行。"""
    from parse_ledger import load_ledger, run_assertions
    ok, report = run_assertions(load_ledger(dirty_alias_ledger["path"]))
    fails = [m for s, m in report if s == "FAIL"]
    assert not ok, "拼错的学科名必须被拦住"
    assert any("Chemistry" in m for m in fails), f"应点名缺的是谁，实际：{fails[:3]}"


@pytest.mark.parametrize("step_only", [True], ids=["parse步"])
def test_脏例端到端_拦停到自愈成功(dirty_alias_ledger, monkeypatch, tmp_path, step_only):
    """验收主用例：真实台账脏一处 → 拦停 → 一次自愈 → 断言全过 → 原件零改动。"""
    led = dirty_alias_ledger["path"]
    before = sha256(led)

    # 只跑 parse 步：自愈发生在这一步，后续四步的正确性由既有端到端用例覆盖，
    # 没必要为了一次自愈再等十几秒出 99 张图。
    monkeypatch.setattr(flow, "STEPS", tuple(s for s in flow.STEPS if s["id"] == "parse"))
    r = flow.run(str(led), out_root=tmp_path / "out", run_dir=tmp_path / "run")

    assert r.status == states.COMPLETED, f"自愈后应走完：{r.failure}"
    assert [s["attempt"] for s in r.steps] == [1, 2], "应恰好重跑一次（首轮 1 + 自愈 2）"
    assert r.repairs and "discipline_alias_map" in r.repairs[0]["rules"]

    run = tmp_path / "run"
    assert (run / "repair.yaml").exists(), "自愈决定必须落盘（LLD §5.2）"
    events = (run / "agent_events.jsonl").read_text(encoding="utf-8")
    assert "apply_repair_rule" in events, "轨迹要记下用了哪条规则"
    hist = (run / "state_history.jsonl").read_text(encoding="utf-8")
    assert "retrying" in hist and "running" in hist, "拦停→重试→继续 必须有状态留痕"

    assert sha256(led) == before, "🔴 自愈绝不能改台账原件（R-24）"


def test_规则库救不了时升级并出诊断报告(dirty_unknown_ledger, monkeypatch, tmp_path):
    led = dirty_unknown_ledger["path"]
    before = sha256(led)
    monkeypatch.setattr(flow, "STEPS", tuple(s for s in flow.STEPS if s["id"] == "parse"))
    r = flow.run(str(led), out_root=tmp_path / "out", run_dir=tmp_path / "run")

    assert r.status == states.ESCALATED
    assert [s["attempt"] for s in r.steps] == [1, 2], "仍应走满一次自愈机会再升级"
    doc = (tmp_path / "run" / "诊断报告.md").read_text(encoding="utf-8")
    assert "某某新学科" in doc, "诊断报告要点名那个认不出的名字"
    assert "自愈过程" in doc
    assert sha256(led) == before


# ============================================================ 6. declare 档 overlay 形状
# 钉住的是一处**静默失效**（2026-09-16 实测发现并修正）：`declared` 里曾多套一层参数名
# （`header_row: {...}` / `group_size: {...}`），overlay 于是变成
#     {header_offset: {header_row: {工作表: 行号}}}
# 而 `_parse_scope` 期待 {header_offset: {工作表: 行号}} → 永远读到默认值。
# 症状：馆员填了参数、规则显示已批准、自愈报 repaired，实际口径一个字节没改。
# 它不抛异常、不影响任何断言，只有形状断言能钉住 —— 下面几条就是那个钉子。
def test_declare档overlay形状与解析口径对齐():
    r = heal.rule_by_id("header_offset")
    ov = heal.overlay_of(r, params={"declared": {"总被引": 2}})
    assert ov == {"header_offset": {"总被引": 2}}, "多包一层会让声明静默失效"
    assert _parse_scope(ov, "总被引")["header_row"] == 2

    r2 = heal.rule_by_id("split_column_group")
    ov2 = heal.overlay_of(r2, params={"declared": {"新国际排名": 4}})
    assert _parse_scope(ov2, "新国际排名")["group_size"] == 4


def test_declare档声明表头在第0行不算未声明():
    """0 是合法行号。曾用 `if v` 过滤，会把 0 当成「馆员没填」丢掉并误报 RULE_UNAPPROVED。"""
    r = heal.rule_by_id("header_offset")
    ov = heal.overlay_of(r, params={"declared": {"总被引": 0}})
    assert _parse_scope(ov, "总被引")["header_row"] == 0


def test_规则库declare档的declared不得再套参数名():
    """结构性防回归：declared 的键应是工作表名，不是 header_row / group_size 这类参数名。"""
    banned = {"header_row", "group_size"}
    for r in heal.load_rules():
        if r["executable"] != heal.DECLARE:
            continue
        assert not (banned & set(r.get("declared") or {})), \
            f"{r['id']} 的 declared 又套了参数名，会与 _parse_scope 错位、静默失效"


def test_overlay只含解析口径键_不碰断言():
    """自愈只让本该被读到的数据被读到，不让断言放行 —— 改断言＝改口径，属评审事项。"""
    allowed = {"header_offset", "group_size", "normalize_period", "discipline_alias"}
    for r in heal.load_rules():
        ov = heal.overlay_of(r, params={"declared": {"某表": 1}})
        assert set(ov) <= allowed, f"{r['id']} 产出了断言口径之外的键：{set(ov) - allowed}"


@pytest.mark.parametrize("body,why", [
    ("version: 1\n", "缺 rules 列表"),
    ("version: 1\nrules: []\n", "rules 为空"),
    ("version: 1\nrules:\n  - id: x\n", "规则缺必需字段"),
    ("version: 1\nrules:\n  - {id: x, code: ASSERT_FAIL, match: {message_re: a},"
     " executable: 乱写}\n", "executable 非法"),
    ("version: 1\nrules:\n  - {id: x, code: 不存在的码, match: {message_re: a},"
     " executable: auto}\n", "错误码不在文档全集内"),
])
def test_规则库结构非法时报错(tmp_path, body, why):
    """坏规则库必须响亮地失败 —— 静默降级成「无规则」比报错难查得多。"""
    p = tmp_path / "bad.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(heal.RuleError):
        heal.load_rules(p)
