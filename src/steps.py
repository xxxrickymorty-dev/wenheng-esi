# -*- coding: utf-8 -*-
"""五步流水线注册表：parse / compute / forecast / charts / docx 的**唯一实现**。

两个编排壳与历史补跑都从这里取步骤体，各自只保留政策：

- `run_pipeline.py`（直跑，演示站主路径）：进度事件、带病出稿、run_log、运行期护栏；
- `agent/flow.py`（受控）：状态机、自愈、拦停、轨迹、诊断报告；
- `rerun_history.py`（历史补跑）：期次 override、试排文件名、省域/矩阵附加件。

接口约定：

- `StepCtx` 是一切输入（期次、out_dir、自愈 overlay、选模快照、override…）；
- `StepResult.data` 是该步的产物与事实（期次、计数、路径、断言结论）；
- 步骤失败抛 `StepError`（`code` 用 `agent/tools.ERROR_CODES` 的码）；
- `parse` 是例外：断言过不过属于**政策**（直跑带病、受控拦停），由
  `StepCtx.strict_assertions` 决定；`probe=True` 只探期次，一个字节不落盘。

⚠ 步骤内不做留痕/进度/清理策略；壳负责它们。步骤只读台账、写当期产物目录。
"""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass, field

import period as period_mod


class StepError(RuntimeError):
    """步骤失败：`code` 是工具契约里的错误码；`detail` 进诊断/记录。"""

    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class StepCtx:
    """一步的全部输入。壳按需填字段，步骤只读。"""

    ledger: str = ""
    out_dir: str = ""
    period: str = ""
    overlay: dict | None = None                 # 自愈注入的读表口径（只影响读法）
    strict_assertions: bool = True              # parse：断言未过 → 拦停（False＝带病出稿）
    probe: bool = False                         # parse：只探期次，不落盘
    choice_path: str | None = None              # charts：预测选模快照（job 私有）
    period_override: str | None = None          # charts/docx：历史补跑的输出期次
    docx_out_path: str | None = None            # docx：显式报告文件名（补跑「（试排）」）
    write_texts: bool = False                   # compute：额外写 texts_preview.json


@dataclass(frozen=True)
class StepResult:
    data: dict = field(default_factory=dict)
    warnings: tuple = ()


#: 步骤注册表（顺序即主干顺序；`agent/flow.STEPS` 的元数据与其逐位对齐，测试钉）。
@dataclass(frozen=True)
class Step:
    id: str
    run: object


def choice_snapshot_from_env() -> str | None:
    """job 冻结的预测选模快照路径（只由 `server/jobs.py` 设）。"""
    return os.environ.get("WENHENG_FORECAST_CHOICE_SNAPSHOT") or None


def _period_of(ctx: StepCtx) -> str:
    """期次取 override > 显式 > 目录名（口径在 `period`，这里只是取值顺序）。"""
    if ctx.period_override or ctx.period:
        return ctx.period_override or ctx.period
    return period_mod.from_dir(ctx.out_dir) or ""


# ================================================================== parse
def parse(ctx: StepCtx) -> StepResult:
    """解析 22 工作表 + 机器断言（+ 落盘）。

    - `probe=True`：只回期次/断言结论，不写任何文件（编排预判用）；
    - `strict_assertions=True`：断言未过 → `ASSERT_FAIL`（**在 write_outputs 之前**）；
    - `False`：落盘照写，断言结论/失败清单/不认识的名字放进 data（直跑带病出稿）。
    """
    import parse_ledger                                        # noqa: PLC0415

    p = pathlib.Path(ctx.ledger)
    if not p.exists():
        raise StepError("FILE_INVALID", f"台账不存在：{p}")
    led = parse_ledger.load_ledger(p, overlay=ctx.overlay)
    ok, report, _missing = parse_ledger.run_assertions(led)
    P, Q = parse_ledger._latest_periods(led)

    if ctx.probe:
        return StepResult({"period": P, "prev": Q, "assertions_ok": ok})

    diag = dict(led.get("diagnostics", {}))
    fails = [m for s, m in report if s == "FAIL"]
    if not ok:
        diag["unmatched_names"] = parse_ledger.unmatched_name_hints(led)
    if not ok and ctx.strict_assertions:
        # ⚠ 静默跳过 = 静默产错报告。某张宽表少了学科时，把那张表首列里
        #    **认不出来的名字**一并送出去——否则规则库只知道"少了一个"。
        raise StepError("ASSERT_FAIL", f"{len(fails)} 项断言未过",
                        period=P, fails=fails[:10], diagnostics=diag)

    # ⚠ 落盘必须在断言闸**之后**（strict）。顺序反过来会让一次失败运行在
    #    `out/<期次>/` 留下"本次的宽表 + 上一次的报告"，页面上没有任何警报。
    out = pathlib.Path(ctx.out_dir)
    parse_ledger.write_outputs(led, p, out)
    data = {"out_dir": str(out), "period": P, "prev": Q, "assertions_ok": ok,
            "n_checks": len(report), "missing": list(_missing or []),
            "overlay_applied": sorted(ctx.overlay) if ctx.overlay else []}
    if not ok:
        data.update({"fails": fails, "diagnostics": diag})
    return StepResult(data)


# ================================================================== compute
def compute(ctx: StepCtx) -> StepResult:
    """大表 22×11 + 概述数字事实（+ 可选句骨架）。"""
    import compute as _compute                                 # noqa: PLC0415

    out = pathlib.Path(ctx.out_dir)
    try:
        wide, ni, nc, thr = _compute.load_wide(str(out))
        if ctx.period:
            filled = [c for c in wide["total_cites"].columns
                      if wide["total_cites"][c].notna().any()]
            if ctx.period not in filled:
                raise ValueError(f"台账无 {ctx.period} 期数据（有效期次："
                                 f"{filled[0]}..{filled[-1]}）")
            P = ctx.period
            Q = [c for c in filled if c < P][-1]
        else:
            P, Q = _compute.detect_periods(wide)
        t2 = _compute.build_table2(wide, ni, nc, thr, P, Q)
        t2.to_csv(out / "table2.csv", index=False, encoding="utf-8-sig")
        import pandas as pd                                    # noqa: PLC0415

        ynd = pd.read_parquet(out / "wide" / "ynd_rank.parquet").set_index("period")
        top_total = (pd.read_parquet(out / "wide" / "top_total.parquet")
                     .set_index("period")["total"].to_dict())
        facts = _compute.build_overview(wide, ni, nc, thr, ynd, top_total, P, Q)
        (out / "overview_facts.json").write_text(
            json.dumps(facts, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except StepError:
        raise
    except Exception as e:                                     # noqa: BLE001
        raise StepError("MISSING_PERIOD", f"大表/概述失败：{e}") from e

    data = {"out_dir": str(out), "period": P, "prev": Q, "rows": len(t2),
            "table2": str(out / "table2.csv")}
    if ctx.write_texts:
        import sentences                                       # noqa: PLC0415

        texts = sentences.build(facts, P, Q)
        (out / "texts_preview.json").write_text(
            json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8")
        data["texts_preview"] = str(out / "texts_preview.json")
    return StepResult(data)


# ================================================================== forecast
def forecast(ctx: StepCtx) -> StepResult:
    """预测回测（InCites + 差值校准，验收 MAPE<5%）。"""
    import forecast as _forecast                               # noqa: PLC0415

    try:
        mape = _forecast.main(ledger_dir=ctx.out_dir, out_dir=ctx.out_dir)
    except Exception as e:                                     # noqa: BLE001
        raise StepError("SAMPLE_TOO_FEW", f"预测回测失败：{e}") from e
    return StepResult({"mape_overall": round(float(mape), 3)})


# ================================================================== charts
def cleanup_failed_forecast(out_dir, report_forecast=None) -> None:
    """预测模块不可用时隔离残留（防「旧预测图 + 新报告」混装）。"""
    if report_forecast is not None:
        report_forecast.quarantine_forecast_artifacts(out_dir)
        return
    out_dir = pathlib.Path(out_dir)
    (out_dir / "forecast_charts.json").unlink(missing_ok=True)
    overview = out_dir / "charts" / "_overview"
    if overview.is_dir():
        for png in overview.glob("forecast_*.png"):
            png.unlink(missing_ok=True)


def charts(ctx: StepCtx) -> StepResult:
    """期次图 + 预测章配图。预测图失败**不拦停**（母版原生图表保留 + 红色件预警）。"""
    import charts as _charts                                   # noqa: PLC0415

    P = _period_of(ctx)
    try:
        n = _charts.render_all(ledger_dir=ctx.out_dir, n_periods=7,
                               end_period=(ctx.period_override or P or None))
    except Exception as e:                                     # noqa: BLE001
        raise StepError("FONT_MISSING", f"图表渲染失败：{e}") from e

    n_fc, fc_warn, warns = 0, [], []
    module = None
    choice_applied = None
    try:
        import report_forecast as module                       # noqa: PLC0415
        if ctx.choice_path:
            import forecast_choice                             # noqa: PLC0415

            choice_applied = forecast_choice.apply_snapshot(
                ctx.choice_path, ctx.out_dir, ctx.period_override or P)
        n_fc = module.generate(ctx.out_dir, choice_path=choice_applied,
                               period_override=ctx.period_override)
        fc_warn = module.load_warnings(ctx.out_dir)
    except Exception as e:                                     # noqa: BLE001
        # 即使清理遇到瞬时文件错误，也不要让 fill_docx 读到旧图/元数据。
        cleanup_failed_forecast(ctx.out_dir, module)
        warns.append(f"预测图：跳过（{type(e).__name__}: {e}）")
    data = {"out_dir": ctx.out_dir, "n_charts": n, "n_forecast_charts": n_fc,
            "forecast_warnings": fc_warn}
    if choice_applied is not None:
        data["choice_applied"] = str(choice_applied)
    return StepResult(data, warnings=tuple(warns))


# ================================================================== docx
def docx(ctx: StepCtx) -> StepResult:
    """母版替换 → 报告初稿 + 红色件清单。"""
    import fill_docx                                           # noqa: PLC0415

    try:
        path = fill_docx.main(ledger_dir=ctx.out_dir, out_path=ctx.docx_out_path,
                              period_override=ctx.period_override)
    except Exception as e:                                     # noqa: BLE001
        raise StepError("SLOT_MISS", f"母版替换失败：{e}") from e
    return StepResult({"docx": str(path)})


#: 主干步骤（顺序唯一事实源；`agent/flow.STEPS` 只存元数据，测试钉逐位一致）。
STEPS: tuple[Step, ...] = (
    Step("parse", parse),
    Step("compute", compute),
    Step("forecast", forecast),
    Step("charts", charts),
    Step("docx", docx),
)

STEP_IDS: tuple[str, ...] = tuple(s.id for s in STEPS)


def run_step(step_id: str, ctx: StepCtx) -> StepResult:
    """按注册表跑一步（parity 测试/脚本用；壳也可以直接调函数）。"""
    for s in STEPS:
        if s.id == step_id:
            return s.run(ctx)
    raise KeyError(f"未注册的步骤：{step_id!r}（允许：{list(STEP_IDS)}）")
