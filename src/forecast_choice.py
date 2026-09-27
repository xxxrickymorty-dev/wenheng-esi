# -*- coding: utf-8 -*-
"""预测选模（forecast choice）：读写、读取顺序、快照与留痕的唯一 implementation。

一份选模记录的完整生命（原先散在 server/app.py、server/jobs.py、src/run_pipeline.py、
src/report_forecast.py 四处，各自重复实现读取与形状判定；本 module 是那次收敛的唯一落点）：

    POST 写盘（server adapter）        out/_forecast_choices/<期次>.json
    → 创建任务冻结（job 快照）          out/_jobs/<id>/forecast_choice.json
    → 运行时应用（pipeline adapter）    out/<期次>/_forecast_choice_applied.json
    → 出图解析（report_forecast）       {(路线, 学科): 模型}

读取顺序（primary → legacy → default）只在这里出现一次；形状清洗（choice/by/at 的
类型容错）与常量（ROUTES / VALID_MODELS）同理。HTTP 的 400 由 server 适配层用
`validate()` 产生；流水线的宽松降级（旧扁平形状整份忽略等）用 `load()`。

不依赖 server/config：目录一律由调用方传入，本 module 不引入任何重型依赖。
"""
from __future__ import annotations

import json
import pathlib
import time

from esi_v1.config_v1 import MODEL_NAMES

#: 选模路线（值与 server/forecasting.ROUTES 必须一致，tests 有跨 module 一致性断言）
ROUTES = ("citation", "rank")
#: 可选模型：recommended＝V1 基线推荐；all＝五模型全跑取滚动 MAPE 最小者。
VALID_MODELS = frozenset({"recommended", "all", *MODEL_NAMES})

CHOICE_FILE = "forecast_choice.json"            # legacy 落点：out/<期次>/
APPLIED_FILE = "_forecast_choice_applied.json"  # 运行时应用到输出期次目录的快照
CHOICES_DIR = "_forecast_choices"               # primary 落点：out/_forecast_choices/


def now() -> str:
    """服务端记录用的时间戳格式（与历史 `time.strftime` 写法一致）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_file(path):
    """读一份记录 → (record, error)。

    record 为 None＝没有可用记录（不存在 / 坏 JSON / 顶层不是对象）；
    error 非 None＝文件存在但读不出来。
    utf-8-sig：容忍手工编辑（记事本另存）时带上的 BOM——服务端写盘不带 BOM。
    """
    try:
        loaded = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(loaded, dict):
        return None, None
    return loaded, None


def primary_path(period, choices_dir):
    return pathlib.Path(choices_dir) / f"{period}.json"


def legacy_path(period, out_dir):
    return pathlib.Path(out_dir) / period / CHOICE_FILE


def _clean(record):
    """类型容错：choice 必须是 dict；by/at 必须是 str。"""
    record = record if isinstance(record, dict) else {}
    choice = record.get("choice", {})
    by = record.get("by", "")
    at = record.get("at", "")
    return {
        "choice": choice if isinstance(choice, dict) else {},
        "by": by if isinstance(by, str) else "",
        "at": at if isinstance(at, str) else "",
    }


def read_entry(period, *, choices_dir, out_dir):
    """按 primary → legacy → default 读回请求期次的记录。

    返回 dict：
      record       原始记录（坏 / 无 → None），给需要留痕字段（request_period…）的调用方
      choice/by/at 清洗后的展示三件套（与线上 GET 同口径）
      source       "primary" | "legacy" | "default"
      source_path  相对 out/ 的展示路径（与 job 快照留痕一致）
      error        命中的文件存在但读不出来时的原因（不存在 → None）

    回退只看文件**是否存在**，不看内容是否可读——primary 存在但坏掉时不落到
    legacy（这是线上 GET 与 job 快照的既定口径）。
    """
    primary = primary_path(period, choices_dir)
    legacy = legacy_path(period, out_dir)
    if primary.exists():
        source, path, source_path = "primary", primary, f"{CHOICES_DIR}/{period}.json"
    elif legacy.exists():
        source, path, source_path = "legacy", legacy, f"{period}/{CHOICE_FILE}"
    else:
        source, path, source_path = "default", None, ""
    record, error = _read_file(path) if path is not None else (None, None)
    entry = {"record": record, "source": source, "source_path": source_path, "error": error}
    entry.update(_clean(record))
    return entry


def write_entry(period, choice, *, by, at, choices_dir):
    """写 primary 落点 out/_forecast_choices/<期次>.json；返回落盘路径。"""
    target = primary_path(period, choices_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"choice": choice, "by": by, "at": at}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return target


def snapshot(period, *, choices_dir, out_dir, snapshot_at):
    """创建任务时冻结请求期次的配置（不改写 legacy 文件）。"""
    entry = read_entry(period, choices_dir=choices_dir, out_dir=out_dir)
    return {
        "request_period": period,
        "choice_period": period,
        "choice": entry["choice"],
        "by": entry["by"],
        "at": entry["at"],
        "snapshot_at": snapshot_at,
        "snapshot_source": entry["source"],
        "snapshot_source_path": entry["source_path"],
    }


def apply_snapshot(snapshot_path, out_dir, output_period):
    """把 job 私有快照写成实际输出期次的选模输入，并补齐来源留痕。"""
    record, error = _read_file(snapshot_path)
    if record is None:
        if error is not None:
            raise ValueError(f"任务选模快照读取失败：{error}")
        raise ValueError("任务选模快照形状无效")
    if not isinstance(record.get("choice", {}), dict):
        raise ValueError("任务选模快照形状无效")
    request_period = (record.get("request_period") or record.get("choice_period")
                      or record.get("period"))
    if not isinstance(request_period, str) or not request_period:
        raise ValueError("任务选模快照缺少请求期次")

    def _text(value):
        return value if isinstance(value, str) else ""

    applied = dict(record)
    applied.update({
        "period": output_period,
        "request_period": request_period,
        "choice_period": request_period,
        "source_period": output_period,
        "output_period": output_period,
        "operator": _text(record.get("by")),
        "config_updated_at": _text(record.get("at")),
    })
    target = pathlib.Path(out_dir) / APPLIED_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(applied, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def provenance(period_dir, data_period, choice_path=None):
    """读回留痕字段（显式路径或 primary → legacy），映射为 forecast_charts.json 字段。"""
    period_dir = pathlib.Path(period_dir)
    if choice_path is not None:
        record, _error = _read_file(choice_path)
    else:
        entry = read_entry(period_dir.name,
                           choices_dir=period_dir.parent / CHOICES_DIR,
                           out_dir=period_dir.parent)
        record = entry["record"]
    if not isinstance(record, dict):
        record = {}

    def text_field(key, fallback=""):
        value = record.get(key, fallback)
        return value if isinstance(value, str) else fallback

    return {
        "request_period": text_field(
            "request_period", text_field("choice_period", data_period)),
        "choice_period": text_field(
            "choice_period", text_field("request_period", data_period)),
        "source_period": data_period,
        "output_period": text_field("output_period", data_period),
        "config_updated_at": text_field("config_updated_at", text_field("at")),
        "operator": text_field("operator", text_field("by")),
        "snapshot_at": text_field("snapshot_at"),
        "snapshot_source": text_field("snapshot_source"),
        "snapshot_source_path": text_field("snapshot_source_path"),
    }


def load(period_dir, choice_path=None):
    """宽松读取 → `({(路线, 学科): 模型名}, warnings)`。

    · choice_path 给定（运行时 applied 快照）→ 只读它；
    · 否则按 primary → legacy 读回（与服务端 GET 同序）。
    只认嵌套形状；旧扁平形状 / 形状不识别 → 整份忽略并警告；未知路线 / 未知模型
    → 忽略该条并警告；其余 (路线, 学科) 保持 "recommended"（不拦停出图）。
    """
    period_dir = pathlib.Path(period_dir)
    warnings = []
    if choice_path is not None:
        path = pathlib.Path(choice_path)
        record, error = _read_file(path)
        label = path.name
    else:
        entry = read_entry(period_dir.name,
                           choices_dir=period_dir.parent / CHOICES_DIR,
                           out_dir=period_dir.parent)
        record, error, label = entry["record"], entry["error"], CHOICE_FILE
    if error is not None:
        warnings.append(f"预测选模：{label} 读取失败（{error}），全部按 V1 推荐出图")
        return {}, warnings
    if not isinstance(record, dict):
        return {}, warnings
    choice = record.get("choice")
    if choice is None or choice == {}:
        return {}, warnings
    if not isinstance(choice, dict):
        warnings.append(f"预测选模：{label} 形状不识别，整份忽略，全部按 V1 推荐出图")
        return {}, warnings
    if not all(isinstance(v, dict) for v in choice.values()):
        warnings.append(
            f"预测选模：{label} 是旧扁平形状（英文键），整份忽略，全部按 V1 推荐出图")
        return {}, warnings
    picked = {}
    for route, entries in choice.items():
        if route not in ROUTES:
            warnings.append(f"预测选模：未知路线「{route}」已忽略")
            continue
        for subject, model in entries.items():
            if not isinstance(model, str) or model not in VALID_MODELS:
                warnings.append(
                    f"预测选模：{route}/{subject} 的模型「{model}」不在可选模型里，"
                    "已忽略（按 V1 推荐）")
                continue
            picked[(route, str(subject))] = model
    return picked, warnings


def validate(choice, *, subjects):
    """严格校验（HTTP 400 口径）→ `(ok, error)`。

    路线 / 模型用本 module 常量判定；学科候选由调用方传入（服务端按请求期次动态解析）。
    """
    if not isinstance(choice, dict):
        return False, "choice 必须是 {路线: {学科: 模型名}}"
    for route, entries in choice.items():
        if route not in ROUTES or not isinstance(entries, dict):
            return False, "choice 的路线或路线值无效"
        for subject, model in entries.items():
            if subject not in subjects or not isinstance(model, str) or model not in VALID_MODELS:
                return False, "choice 的学科或模型无效"
    return True, ""


def count(choice):
    """改选统计：嵌套形状按各路线学科数求和；旧扁平形状按条目数。

    返回 `(学科总数, 路线数或 None)`。🔴 嵌套形状下 `len(choice)` 恒为路线数，
    拿它当 saved 是错的（2026-09-24 前端实报 #17）。
    """
    nested = bool(choice) and all(isinstance(v, dict) for v in choice.values())
    if nested:
        return sum(len(v) for v in choice.values()), len(choice)
    return len(choice), None
