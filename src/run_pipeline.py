# -*- coding: utf-8 -*-
"""每期一条命令：动态监测表（母本）xlsx → 规整数据 + 断言 + 大表 + 概述 + 预测 + 图表 + 报告初稿。

用法（母本在 `input/`，2026-10-13 起 input/ 只放母本）：
    .venv\\Scripts\\python.exe src\\run_pipeline.py                     # 跑台账最新一期
    .venv\\Scripts\\python.exe src\\run_pipeline.py --period 202607     # 历史期补跑（母本+目标期）
    .venv\\Scripts\\python.exe src\\run_pipeline.py <路径> --period <期次>

`--period` 给定时期次是「被补跑期」而不是台账最新：大表/概述/图表/预测/省域/矩阵/报告
全部按它切窗（"07 的报告不读 09 的数据"在消费层强制；口径与 `src/rerun_history.py` 一致）。

流程：
  1. parse_ledger  解析 22 sheet → out/<当期>/（含 meta.json 断言清单）
  2. compute       定位当期/上期（--period 时按被补跑期）→ 大表 22×11 + 概述全部数字事实
  3. forecast      预测回测（InCites+差值校准，验收 MAPE<5%）
  4. charts        98 张期次图（16 学科 × 6 + 2 概览）
  5. fill_docx     母版原地替换 → 报告初稿 + 红色件清单
"""
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import atomic_io  # noqa: E402
import display_path  # noqa: E402
import forecast_choice  # noqa: E402
import ledger  # noqa: E402
import parse_ledger  # noqa: E402
import steps  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]


def _emit(step, name, status, detail=""):
    """结构化进度事件（演示站 SSE 用）：仅当设置 WENHENG_PROGRESS_FILE 时写 JSONL。"""
    path = os.environ.get("WENHENG_PROGRESS_FILE")
    if not path:
        return
    rec = {"ts": time.strftime("%H:%M:%S"), "step": step, "name": name,
           "status": status, "detail": detail, "elapsed": round(time.time() - _T0, 1)}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


_T0 = time.time()


def _write_diagnosis(led, P, out_dir, report, n_fail, run_dir=None):
    """带病出稿时附一份《诊断报告》，落到 `out/<期次>/`（演示站产物列表收得到）。

    ⚠ 它跟 `agent/flow.py` 那份**不是一回事**，别拿混：
      · `flow` 那份 = 自愈逾限、**明确拦停**后的交接物；
      · 这份        = 直跑路径上断言未过时的核对指引，出不出稿取决于后续步骤
                      （缺数据会中断，那是预期行为 —— 总比出一份错报告强）。
    措辞因此**不预设结局**：标题只说"断言未过"，出没出稿由正文两种情况都写到。
    """
    try:
        from agent import heal, narrator                       # noqa: PLC0415
    except Exception:                                          # noqa: BLE001
        return None                       # 没接 agent 层就不附，不影响出稿
    fails = [m for s, m in report if s == "FAIL"]
    diag = dict(led.get("diagnostics") or {})
    # 步骤已带回 unmatched_names 就直接用；老调用方（合成 led）走兼容计算。
    unmatched = diag.get("unmatched_names")
    if unmatched is None:
        unmatched = parse_ledger.unmatched_name_hints(led)
    failure = {"code": "ASSERT_FAIL", "message": f"{n_fail} 项断言未过",
               "period": P, "fails": fails,
               "diagnostics": {"unmatched_names": unmatched}}
    try:
        # run_dir 为 None 时 heal 不落 repair.yaml（传空串会写进 cwd，别传）
        repair = heal.attempt(failure, {"run_dir": str(run_dir) if run_dir else None})
    except Exception:                                          # noqa: BLE001
        repair = None
    try:
        lines, meta = narrator.compose(failure, repair,
                                       data_root=pathlib.Path(out_dir).parent)
    except Exception:                                          # noqa: BLE001
        lines, meta = [], {"backend": "rule"}

    body = [f"# 诊断报告 · 台账断言未过", "",
            f"- 期次：**{P}**",
            f"- 未过断言：**{n_fail}** 项", "",
            "> ⚠ 本次运行有断言未过。",
            ">",
            "> - 若最终**出了**报告初稿：报告里的数字可能建立在不完整或错位的"
            "台账读法上，请先按下面指引核对，再决定要不要签发；",
            "> - 若**没出**（后续步骤因缺数据中断，属预期行为）：先修台账再重跑，"
            "不要拿上一版的旧报告顶上。",
            "", "## 未通过的断言", ""] + [f"- {m}" for m in fails]
    body += lines
    be = (meta or {}).get("backend")
    body += ["", "---", "",
             f"> 本文件由 `src/run_pipeline.py` 生成（叙事后端：{be or 'rule'}）。"
             "自愈逾限、拦停不出稿的那份《诊断报告》由 `src/agent/flow.py` 产出，两者不是一回事。"]
    p = pathlib.Path(out_dir) / "诊断报告.md"
    try:
        atomic_io.write_text_atomic(p, "\n".join(body))
        return p
    except OSError:
        return None


def _apply_forecast_choice_snapshot(snapshot_path, out_dir, output_period):
    """把 job 私有快照写成实际输出期次的选模输入，并补齐来源留痕（见 forecast_choice）。"""
    return forecast_choice.apply_snapshot(snapshot_path, out_dir, output_period)


def _cleanup_failed_forecast(out_dir, report_forecast=None):
    """预测模块可用时隔离残留；模块导入失败时直接清除，防止带旧图出稿。

    实现已收进 `steps.cleanup_failed_forecast`（编排/直跑同口径）；这里留名兼容旧调用。
    """
    return steps.cleanup_failed_forecast(out_dir, report_forecast)


def _ledger_guard(before, after):
    """原件只读护栏（R-24 运行期落点，与 `agent/flow.py` 同口径）。

    返回 None＝未发现改写；否则返回护栏记录——本次运行结果不可采信，
    调用方负责落 run_log 并让退出码非 0。文件不在（测试假路径）不误报。
    """
    if before and after and before != after:
        return {"code": "FILE_INVALID",
                "message": "台账在本次运行期间被改写 —— 原件只读红线（R-24）被破",
                "step": "guard", "before": before, "after": after}
    return None


def main(ledger_path, out_root="out", run_backtest=False, period=None):
    t0 = _T0
    p = pathlib.Path(ledger_path)
    led_sha0 = parse_ledger.file_sha256(p)

    _emit("parse", "解析台账", "start", f"输入：{p.name}")
    print(f"[1/5] 解析台账: {p}")

    # 先探期次（probe 不落盘）：探出来 = 本次确定要改写 out/<当期>/ —— 先把上版成品撤下来。
    # 不撤的话，一次在 charts / docx 步失败的运行会留下「本次的新表格 + 上一次的旧报告」：
    # 看板照旧展示那份旧报告，对勘本拿旧槽位配新格子，页面上没有任何警报。
    # （实现与 agent/flow.py 共用 parse_ledger.quarantine_final_products，别各写一套。）
    probe = steps.parse(steps.StepCtx(ledger=str(p), probe=True))
    P, Q = probe.data["period"], probe.data["prev"]
    if period:
        # 历史期补跑：期次显式给定（母本里含该期）；上期由 compute 按 filled 取
        # （prev_before，台账允许缺口），随后回填 meta 与 run_log——与 rerun_history 同口径。
        P, Q = str(period), ""
    out_dir = pathlib.Path(out_root) / P
    _run_dir = (pathlib.Path(os.environ["WENHENG_PROGRESS_FILE"]).parent
                if os.environ.get("WENHENG_PROGRESS_FILE") else None)
    moved = parse_ledger.quarantine_final_products(out_dir, _run_dir)
    if moved:
        _emit("parse", "解析台账", "warn", f"已撤下上版成品：{'、'.join(moved)}")

    # 正式解析：直跑路径 strict=False（带病出稿），断言结论/失败清单由步骤带回。
    parse_res = steps.parse(steps.StepCtx(ledger=str(p), out_dir=str(out_dir),
                                          strict_assertions=False))
    ok = bool(parse_res.data["assertions_ok"])
    missing = parse_res.data.get("missing") or []
    n_fail = len(parse_res.data.get("fails") or [])
    print(f"      当期={P} 上期={Q or '（补跑，随后定）'} 断言={'全绿' if ok else f'{n_fail} 项 FAIL'} → {out_dir}")
    _emit("parse", "解析台账", "done" if ok else "warn",
          f"当期 {P} · 上期 {Q} · 机器断言 {'全绿' if ok else f'{n_fail} 项未过（已附诊断报告）'}")

    # 断言未过时**立刻**写诊断（不等后续步骤）：后面 charts/docx 若因缺数据崩掉，
    # 人工至少还能拿到这份"哪里脏"的清单，而不是只剩一句 exit code。
    diag_path = None
    if not ok:
        led_face = {"wide": {}, "diagnostics": dict(parse_res.data.get("diagnostics") or {})}
        diag_path = _write_diagnosis(led_face, P, out_dir,
                                     [("FAIL", m) for m in parse_res.data.get("fails") or []],
                                     n_fail, _run_dir)
        if diag_path:
            print(f"      诊断报告 → {diag_path}")

    _emit("compute", "计算大表与概述", "start")
    print("[2/5] 计算大表 + 概述事实")
    try:
        cres = steps.compute(steps.StepCtx(out_dir=str(out_dir), period=P))
    except steps.StepError as e:
        print(f"      失败（{e.code}）：{e.message}")
        _emit("compute", "计算大表与概述", "failed", f"{e.code}：{e.message}")
        return 1
    if period:
        # 补跑：上期按 filled 取（prev_before），并把 meta 的「当期/上期」按被补跑期写回——
        # facts 接口与报告屏的「本期」标注都读它（与 rerun_history 同一处理）。
        Q = str(cres.data.get("prev") or "")
        meta_path = out_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["period_current"] = P
        meta["period_prev"] = Q
        atomic_io.write_text_atomic(
            meta_path, json.dumps(meta, ensure_ascii=False, indent=1, default=str))
        print(f"      补跑：当期={P} 上期={Q}（meta 已按被补跑期写回）")
    print(f"      大表 22×11 → {out_dir}/table2.csv；概述事实 → overview_facts.json")
    _emit("compute", "计算大表与概述", "done", "大表 22 学科 × 11 列 · 概述 11 项数字事实")

    _emit("forecast", "预测回测", "start")
    print("[3/5] 预测回测（InCites+差值校准）")
    try:
        mape = float(steps.forecast(steps.StepCtx(out_dir=str(out_dir))).data["mape_overall"])
    except steps.StepError as e:
        print(f"      失败（{e.code}）：{e.message}")
        _emit("forecast", "预测回测", "failed", f"{e.code}：{e.message}")
        return 1
    print(f"      整体 MAPE = {mape:.2f}%（验收线 <5%）")
    _emit("forecast", "预测回测", "done", f"整体 MAPE {mape:.2f}%（验收线 <5%）")

    # ---- 省域表（T19）：数据源是 ESI 原始包，**不在台账里** ----
    # 台账的《高校学科发展》是另一个口径（昆工发文量 19259 vs 机构总表 31045），
    # 不能拿来填。ESI 包在就算、不在就跳过（服务器上没有 数据与复现/，会走到降级）。
    _emit("province", "省域表（ESI 机构总表）", "start")
    try:
        import extract_province                                  # noqa: PLC0415
        pdata = extract_province.write_json(P, out_dir)
        print(f"      省域表 T19：{pdata['n_universities']} 校 × 9 列 → province.json")
        _emit("province", "省域表（ESI 机构总表）", "done",
              f"{pdata['n_universities']} 所高校 · 学科榜 {pdata['n_disciplines']} 个")
    except (Exception, SystemExit) as e:                         # noqa: BLE001
        # ⚠ 必须连 SystemExit 一起接住：extract_* 缺源件时 raise SystemExit("[拒绝] …")，
        #   而 SystemExit 不是 Exception——2026-10-13 实踩：服务器（无 数据与复现/）上任务
        #   在省域步整进程退出，charts/docx/run_log 全没跑，退出码 1 又被 jobs 映射成
        #   「warned（有提醒）」掩盖了半途死。
        print(f"      省域表 T19：跳过（{type(e).__name__}: {e}）")
        _emit("province", "省域表（ESI 机构总表）", "warn",
              f"跳过：{type(e).__name__}（缺 ESI 原始包时属预期）")

    # ---- 学科×高校矩阵（T20）：数据源是 InCites **历史快照**，同样不在台账里 ----
    # 被引必须取「当期对应那一期」的快照：那份表每期覆盖更新，拿最新的算历史必然错。
    _emit("matrix", "学科×高校矩阵（InCites）", "start")
    try:
        import extract_matrix                                    # noqa: PLC0415
        mdata = extract_matrix.write_json(P, out_dir)
        n_cell = sum(1 for r in mdata["matrix"].values() for x in r.values() if x.get("v"))
        print(f"      矩阵表 T20：{len(mdata['matrix'])} 学科 × 11 校 → {n_cell} 格"
              f"（快照 {mdata['snapshot']}）")
        _emit("matrix", "学科×高校矩阵（InCites）", "done",
              f"快照 {mdata['snapshot']} · {n_cell} 格")
    except (Exception, SystemExit) as e:                         # noqa: BLE001
        # 同省域步：extract_matrix 缺快照时 raise SystemExit，必须一起接住。
        print(f"      矩阵表 T20：跳过（{type(e).__name__}: {e}）")
        _emit("matrix", "学科×高校矩阵（InCites）", "warn",
              f"跳过：{type(e).__name__}（该期未登记快照映射时属预期，见 extract_matrix.SNAP_MAP）")

    _emit("charts", "图表渲染", "start")
    print("[4/5] 图表渲染（16 学科 × 6 + 概览 3）")
    # n_periods=7 + end_period=当期：与人工原件口径一致（近一年 7 期）；
    # 预测选模快照（job 冻结）由 steps.charts 一处应用——直跑与编排不再两说。
    try:
        chres = steps.charts(steps.StepCtx(
            out_dir=str(out_dir), period=P,
            choice_path=steps.choice_snapshot_from_env()))
    except steps.StepError as e:
        print(f"      失败（{e.code}）：{e.message}")
        _emit("charts", "图表渲染", "failed", f"{e.code}：{e.message}")
        return 1
    n_charts = chres.data["n_charts"]
    n_fc = chres.data["n_forecast_charts"]
    fc_warnings = chres.data["forecast_warnings"]
    if n_fc:
        import report_forecast                                   # noqa: PLC0415
        print(f"      预测图：{n_fc} 张（按预测台选模，未选＝V1 推荐；"
              f"递推 {report_forecast.HORIZON} 期）")
    for w in (*chres.warnings, *fc_warnings):
        print(f"      ⚠ {w}")
    if fc_warnings:
        _emit("charts", "预测选模", "warn", "；".join(fc_warnings))
    _emit("charts", "图表渲染", "done",
          f"{n_charts} 张图 · 16 学科 × 6 + 概览" + (f" · 预测 {n_fc} 张" if n_fc else "（预测图跳过）"))

    _emit("docx", "母版替换", "start")
    print("[5/5] 母版替换 → 报告初稿")
    try:
        docx_path = steps.docx(steps.StepCtx(out_dir=str(out_dir))).data["docx"]
    except steps.StepError as e:
        print(f"      失败（{e.code}）：{e.message}")
        _emit("docx", "母版替换", "failed", f"{e.code}：{e.message}")
        return 1
    _emit("docx", "母版替换", "done", f"报告初稿 + 红色件清单：{pathlib.Path(docx_path).name}")

    # 原件只读护栏：直跑路径过去只有测试级守卫，这里补运行期检查。
    ledger_guard = _ledger_guard(led_sha0, parse_ledger.file_sha256(p))
    if ledger_guard:
        print(f"      ⚠ {ledger_guard['message']}")
        _emit("guard", "原件只读护栏", "failed", ledger_guard["message"])

    log = {
        "period": P, "prev": Q,
        # 输入存**仓库相对**：run_log.json 进部署包，绝对路径等于外发本机用户名；
        # 读方（`server/forecasting.py::_resolve_processed_input`）两种写法都认。
        "input": display_path.to_repo_relative(p, REPO),
        "assertions_ok": ok, "assertions_fail": n_fail, "missing": missing,
        "ledger_sha256": led_sha0,
        "ledger_mutated": ledger_guard is not None,
        "predict_mape_overall": round(float(mape), 3),
        "charts": n_charts,
        "forecast_charts": n_fc,
        "forecast_warnings": fc_warnings,
        "docx": str(docx_path),
        "artifacts": {
            "ledger_long": str(out_dir / "ledger_long.parquet"),
            "table2_csv": str(out_dir / "table2.csv"),
            "overview_facts": str(out_dir / "overview_facts.json"),
            "forecast_report": str(out_dir / "预测回测报告.md"),
            "red_slots": str(out_dir / "red_slots.json"),
            "red_list_md": str(out_dir / "红色件清单.md"),
        },
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if diag_path:
        log["artifacts"]["diagnosis"] = str(diag_path)
        log["diagnosis"] = True
    atomic_io.write_text_atomic(
        out_dir / "run_log.json", json.dumps(log, ensure_ascii=False, indent=1))
    print(json.dumps(log, ensure_ascii=False, indent=1))
    _emit("done", "完成", "done" if ok else "warn",
          f"全链路 {log['elapsed_sec']} 秒 · 断言 {'全绿' if ok else f'{n_fail} 项 FAIL'} · "
          f"大表 22×11 · 图 {n_charts} 张 · MAPE {mape:.2f}%")

    if ledger_guard:
        return 2

    if run_backtest:
        import backtest
        ref = os.environ.get("WENHENG_REFERENCE_DOCX") or r"..\云南大学原报告\云南大学学科信息参考2026年第4期.docx"
        print(f"[附加] 金样回测：{ref}")
        backtest.main(ref, str(out_dir))
    return 0 if ok else 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    period = None
    if "--period" in argv:
        i = argv.index("--period")
        period = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    positional = [a for a in argv if not a.startswith("--")]
    src = positional[0] if positional else str(ledger.runtime_path(REPO))
    sys.exit(main(src, run_backtest="--backtest" in argv, period=period))
