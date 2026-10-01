# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 工具契约（WH-DOC-04 §5.1）。

13 个工具，全部登记在此。编排器**只允许调用注册表里的工具**——
这是「模型不得增删主干步骤」在代码层面的落点：
`call()` 拒绝未注册名，且入参按 schema 校验后才执行。

每个工具带 `milestone` 标注当前状态：
  M2 = 本里程碑已实现；M3 = 自愈闭环；M4 = 审计/归档；M4b = 学院清单。
未实现的工具**注册契约但调用即抛 `TOOL_NOT_IMPLEMENTED`**，
这样编排与前端可以照契约开发，不会因为缺实现而谎报成功。
"""
from __future__ import annotations

import pathlib

# ------------------------------------------------------------------ 错误码
#: WH-DOC-04 §7 定义的错误码全集
ERROR_CODES = (
    "FILE_INVALID", "CELL_EMPTY", "ASSERT_FAIL", "MISSING_PERIOD",
    "SAMPLE_TOO_FEW", "FONT_MISSING", "SLOT_MISS", "REF_MISSING",
    "RULE_UNAPPROVED", "COL_MAP_MISSING", "TOOL_NOT_IMPLEMENTED",
)


class ToolError(Exception):
    """工具失败。`code` 必须是 ERROR_CODES 之一——编排器按码决定自愈还是升级。"""

    def __init__(self, code, message, **detail):
        if code not in ERROR_CODES:
            raise ValueError(f"未知错误码 {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.detail}


# ------------------------------------------------------------------ 注册表
class Tool:
    __slots__ = ("name", "args", "returns", "errors", "handler", "milestone", "note")

    def __init__(self, name, args, returns, errors, handler, milestone="M2", note=""):
        self.name = name
        self.args = args              # {参数名: (类型, 是否必填, 说明)}
        self.returns = returns
        self.errors = errors
        self.handler = handler
        self.milestone = milestone
        self.note = note


REGISTRY: dict[str, Tool] = {}


def tool(name, args, returns, errors, milestone="M2", note=""):
    def deco(fn):
        REGISTRY[name] = Tool(name, args, returns, errors, fn, milestone, note)
        return fn
    return deco


def _check_args(t: Tool, kwargs):
    for key, (typ, required, _desc) in t.args.items():
        if required and key not in kwargs:
            raise ToolError("FILE_INVALID", f"{t.name} 缺必填参数 {key}")
        if key in kwargs and kwargs[key] is not None and not isinstance(kwargs[key], typ):
            raise ToolError("FILE_INVALID",
                            f"{t.name} 参数 {key} 类型应为 {typ.__name__}，"
                            f"实为 {type(kwargs[key]).__name__}")
    unknown = set(kwargs) - set(t.args)
    if unknown:
        raise ToolError("FILE_INVALID", f"{t.name} 收到未声明参数：{sorted(unknown)}")


def call(name, **kwargs):
    """按契约调用工具。未注册 → 直接拒绝（主干不可被模型扩展）。"""
    if name not in REGISTRY:
        raise ToolError("TOOL_NOT_IMPLEMENTED", f"未注册的工具：{name}")
    t = REGISTRY[name]
    _check_args(t, kwargs)
    result = t.handler(**kwargs)
    if isinstance(result, dict) and result.get("__not_implemented__"):
        raise ToolError("TOOL_NOT_IMPLEMENTED",
                        f"{name} 契约已定，实现归属 {t.milestone}", **result)
    return result


def schema():
    """导出全部工具契约（供文档生成 / 前端展示）。"""
    return [{
        "name": t.name,
        "args": {k: {"type": v[0].__name__, "required": v[1], "desc": v[2]}
                 for k, v in t.args.items()},
        "returns": t.returns,
        "errors": list(t.errors),
        "milestone": t.milestone,
        "note": t.note,
    } for t in REGISTRY.values()]


def _todo(milestone):
    def fn(**kw):
        return {"__not_implemented__": True, "milestone": milestone}
    # 打标记，让外部能**枚举**出"契约已定、实现待补"的工具。
    # 没有它，测试只能写死某个工具名——M4 三工具一落地，写死的用例立刻变红。
    fn.__not_implemented__ = True
    return fn


# ================================================================== 已实现
@tool("inspect_ledger",
      {"xlsx": (str, True, "台账路径")},
      "sheets / 期次覆盖 / 脏格式预警", ["FILE_INVALID"])
def inspect_ledger(xlsx):
    """运行前预检：确认文件可读、工作表齐全、期次可定位。"""
    import openpyxl
    p = pathlib.Path(xlsx)
    if not p.exists():
        raise ToolError("FILE_INVALID", f"台账不存在：{p}")
    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            sheets = list(wb.sheetnames)
        finally:
            wb.close()
    except Exception as e:                                    # noqa: BLE001
        raise ToolError("FILE_INVALID", f"台账打不开：{e}") from e
    if not sheets:
        raise ToolError("FILE_INVALID", "台账没有任何工作表")
    return {"ok": True, "file": p.name, "n_sheets": len(sheets), "sheets": sheets}


@tool("run_parse",
      {"ledger": (str, True, "台账路径"), "out_dir": (str, True, "产物目录"),
       "overlay": (dict, False, "自愈注入的读表口径（默认 None＝既有口径，原件只读）"),
       "probe": (bool, False, "只探期次不落盘（编排预判用）")},
      "out_dir / meta.json / 断言清单 / diagnostics",
      ["FILE_INVALID", "ASSERT_FAIL"])
def run_parse(ledger, out_dir, overlay=None, probe=False):
    """解析 22 工作表并跑机器断言（实现在 `steps.parse`）。

    断言 FAIL → 抛 ASSERT_FAIL（由编排器决定自愈/升级）；落盘永远在断言闸之后。
    `overlay` 来自 `heal.attempt()`（M3），只改变**怎么读**台账，不改台账文件本身。
    `probe=True` 只回期次与断言结论，一个字节不写——编排先探期次再决定产物目录。
    """
    import steps
    try:
        res = steps.parse(steps.StepCtx(ledger=ledger, out_dir=out_dir,
                                        overlay=overlay, probe=probe))
    except steps.StepError as e:
        raise ToolError(e.code, e.message, **e.detail) from e
    return {"ok": True, **res.data}


@tool("run_compute",
      {"out_dir": (str, True, "解析产物目录")},
      "table2.csv / overview_facts.json", ["MISSING_PERIOD"])
def run_compute(out_dir):
    import steps
    try:
        res = steps.compute(steps.StepCtx(out_dir=out_dir))
    except steps.StepError as e:
        raise ToolError(e.code, e.message, **e.detail) from e
    return {"ok": True, **res.data}


@tool("run_forecast",
      {"out_dir": (str, True, "产物目录")},
      "MAPE / 超线清单", ["SAMPLE_TOO_FEW"])
def run_forecast(out_dir):
    import steps
    try:
        res = steps.forecast(steps.StepCtx(out_dir=out_dir))
    except steps.StepError as e:
        raise ToolError(e.code, e.message, **e.detail) from e
    return {"ok": True, **res.data}


@tool("run_charts",
      {"out_dir": (str, True, "产物目录")},
      "图数", ["FONT_MISSING"])
def run_charts(out_dir):
    # 预测图失败不拦停（母版原生图表保留 + 红色件预警），由步骤内部降级。
    import steps
    try:
        res = steps.charts(steps.StepCtx(out_dir=out_dir,
                                         period=steps.period_from_dir(out_dir)))
    except steps.StepError as e:
        raise ToolError(e.code, e.message, **e.detail) from e
    return {"ok": True, **res.data}


@tool("run_docx",
      {"out_dir": (str, True, "产物目录")},
      "docx / red_slots", ["SLOT_MISS"])
def run_docx(out_dir):
    import steps
    try:
        res = steps.docx(steps.StepCtx(out_dir=out_dir))
    except steps.StepError as e:
        raise ToolError(e.code, e.message, **e.detail) from e
    return {"ok": True, **res.data}


@tool("read_cell",
      {"xlsx": (str, True, "台账路径"), "sheet": (str, True, "工作表名"),
       "cell": (str, True, "单元格坐标，如 C12")},
      "值 + 坐标（只读）", ["FILE_INVALID", "CELL_EMPTY"])
def read_cell(xlsx, sheet, cell):
    """红件追溯用：任一处改动都能回读到台账源单元格（SRS R-10 / NFR-04）。"""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
        try:
            if sheet not in wb.sheetnames:
                raise ToolError("FILE_INVALID", f"无工作表 {sheet}")
            v = wb[sheet][cell].value
        finally:
            wb.close()
    except ToolError:
        raise
    except Exception as e:                                    # noqa: BLE001
        raise ToolError("FILE_INVALID", f"读取失败：{e}") from e
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ToolError("CELL_EMPTY", f"{sheet}!{cell} 为空", sheet=sheet, cell=cell)
    return {"ok": True, "sheet": sheet, "cell": cell, "value": v}


# ================================================================== 契约已定、实现待补
@tool("run_backtest",
      {"reference": (str, True, "已出版原件 docx"), "out_dir": (str, True, "产物目录")},
      "一致率 / 差异格", ["REF_MISSING"], milestone="M2",
      note="有原件时执行；无原件抛 REF_MISSING 由编排器降级标注")
def run_backtest(reference, out_dir):
    import backtest
    if not pathlib.Path(reference).exists():
        raise ToolError("REF_MISSING", f"原件不存在：{reference}")
    rc = backtest.main(reference, str(out_dir))
    return {"ok": rc == 0, "reference": reference}


@tool("scan_stale",
      {"out_dir": (str, True, "产物目录"), "ledger": (str, True, "台账路径")},
      "陈旧数字残留清单", [], milestone="M4",
      note="审计闭环六项之一（LLD §6.6）")
def scan_stale(out_dir, ledger):
    """第 3 项审计。实现在 `audit.scan_stale`（本文件只做契约与错误码）。

    扫的是**期次标签残留**：合法期次只有 {本期 P, 上期 Q}，出现其它 `20xxxx` 列可疑。
    输出是**可疑清单**而非自动"0 残留"判定——图是 PNG 扫不到字，正文也可能正当引用早期期次。
    """
    from . import audit                                       # noqa: PLC0415
    return audit.scan_stale(out_dir, ledger)


@tool("apply_repair_rule",
      {"rule": (str, True, "规则名"), "params": (dict, False, "规则参数")},
      "overlay 片段（写入 repair.yaml 由 heal.py 负责）", ["RULE_UNAPPROVED"], milestone="M3",
      note="原件只读；新规则类型首次使用须馆员确认（规则库 approved_by 为空即拒绝）")
def apply_repair_rule(rule, params=None):
    """自愈规则的唯一执行闸。

    在这里而不是在 heal.py 里做批准校验，是为了让**任何**调用方（编排器、看板、
    将来的人工重放）都走同一道闸——绕过它的写法只有"直接 import parse_ledger"，
    而那不叫自愈，叫改口径。
    """
    from . import heal                                          # noqa: PLC0415
    r = heal.rule_by_id(rule)
    if r is None:
        raise ToolError("RULE_UNAPPROVED", f"规则库无此规则：{rule}")
    if not heal.is_approved(r):
        raise ToolError("RULE_UNAPPROVED",
                        f"规则类型 {rule} 未经馆员确认，拒绝执行（R-24）",
                        rule=rule, advice=r.get("advice_unapproved"))
    if r["executable"] == heal.NEVER:
        raise ToolError("RULE_UNAPPROVED",
                        f"规则 {rule} 设计上不可修复，只出建议（{r.get('doc')}）",
                        rule=rule, advice=r.get("advice_unapproved"))
    ov = heal.overlay_of(r, params)
    if not ov:
        raise ToolError("RULE_UNAPPROVED",
                        f"规则 {rule} 的参数尚未由馆员声明（declared 为空）",
                        rule=rule, advice=r.get("advice_unapproved"))
    return {"ok": True, "rule": rule, "params": params or {}, "overlay": ov}


@tool("collect_artifacts",
      {"run_dir": (str, True, "运行目录")},
      "产物清单 + sha256", [], milestone="M4", note="归档包 manifest 来源")
def collect_artifacts(run_dir):
    from . import audit                                       # noqa: PLC0415
    return audit.collect_artifacts(run_dir)


@tool("run_college_stats",
      {"csv": (str, True, "学院顶尖论文清单.csv"), "map_yaml": (str, False, "学院映射表")},
      "学院统计 + 清单产物", ["FILE_INVALID", "COL_MAP_MISSING"], milestone="M4b",
      note="映射表待卜彤确认（SRS §9#6）")
def run_college_stats(csv, map_yaml=None):
    return _todo("M4b")()


@tool("write_env_snapshot",
      {"run_dir": (str, False, "运行目录（默认 out/202607）")},
      "env_snapshot.json", [], milestone="M4",
      note="python / deps / git_commit / os / tz（架构设计 §5.2）；"
           "**原契约无参**——2026-09-16 补一个可选 run_dir，否则不知道该写哪儿")
def write_env_snapshot(run_dir="out/202607"):
    from . import audit                                       # noqa: PLC0415
    return audit.write_env_snapshot(run_dir)
