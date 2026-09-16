# -*- coding: utf-8 -*-
"""文衡 Agent 层 · 自愈闭环（M3；WH-DOC-04 §3.8 / §6.5；SRS R-23 / R-24 / R-26）。

裁决语义（WH-DOC-08 裁决 #1）：**首轮拦停 → 一次自愈 → 再败升级**。
本模块只负责「给这一次自愈提供修复方案」；重跑与升级由 `flow.py` 决定。

三条安全边界（R-24，不可越）
────────────────────────────────────────────────────────────────
1. **原件只读**。本模块不打开、不写入台账，`attempt()` 全程不碰 xlsx。
   产出物是一份「解析 overlay」——只在本次运行内改变 `parse_ledger` 的读表口径。
   台账的文件内容在任何自愈路径上都不变（`tests/test_agent_heal.py` 用 sha256 钉住）。
2. **新规则类型首次使用须馆员确认**。`repair_rules.yaml` 里 `approved_by` 为空的规则，
   命中也不执行 —— 记为 refused（错误码 `RULE_UNAPPROVED`），只往《诊断报告》写建议。
3. **不改断言**。自愈只让本该被读到的数据被读到，不让断言放行。
   断言集本身不可谈判：改断言＝改口径，属评审事项。

一次机会，所以一次全给
────────────────────────────────────────────────────────────────
`MAX_HEAL_ATTEMPTS = 1` 意味着自愈只有一发子弹。因此 `attempt()` 会把**所有**匹配到的
auto 规则合并成同一个 overlay 一次提交，而不是只挑第一条 —— 见 `_hits()`。

命中记录
────────────────────────────────────────────────────────────────
每次运行写 `<run_dir>/repair.yaml`（LLD §5.2 产物表：rule / params / reason / approved_by），
它是**只追加的运行档案**，不覆盖历史。规则命中率可用 `summary()` 统计。
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re

import yaml

from . import tools

RULES_DIR = pathlib.Path(__file__).resolve().parent / "rules"
RULES_PATH = RULES_DIR / "repair_rules.yaml"

#: 三档可执行性
AUTO = "auto"          # 机器可直接改口径
DECLARE = "declare"    # 须馆员预先声明参数
NEVER = "never"        # 设计上不可修复，只出建议


class RuleError(Exception):
    """规则库自身的问题（文件缺失 / 格式非法）。属工程缺陷，不是台账脏。"""


# ---------------------------------------------------------------- 规则库
def load_rules(path=None) -> list[dict]:
    """读规则库。文件缺失或结构非法 → 抛 RuleError（不静默降级成"无规则"）。

    静默返回空规则库的后果是"看起来自愈跑了、其实一条规则都没有"，
    比直接报错更难查，所以这里选择抛。
    """
    p = pathlib.Path(path or RULES_PATH)
    if not p.exists():
        raise RuleError(f"规则库不存在：{p}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:                                # noqa: PERF203
        raise RuleError(f"规则库 YAML 解析失败：{e}") from e
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuleError("规则库缺 rules 列表或为空")
    seen = set()
    for r in rules:
        for key in ("id", "code", "match", "executable"):
            if key not in r:
                raise RuleError(f"规则 {r.get('id', '?')} 缺字段 {key}")
        if r["id"] in seen:
            raise RuleError(f"规则 id 重复：{r['id']}")
        seen.add(r["id"])
        if r["executable"] not in (AUTO, DECLARE, NEVER):
            raise RuleError(f"规则 {r['id']} 的 executable 非法：{r['executable']}")
        if r["code"] not in tools.ERROR_CODES:
            raise RuleError(f"规则 {r['id']} 的错误码 {r['code']} 不在文档全集内")
    return rules


def rule_by_id(rule_id, path=None) -> dict | None:
    for r in load_rules(path):
        if r["id"] == rule_id:
            return r
    return None


def is_approved(rule) -> bool:
    """馆员是否已确认该规则类型（R-24 的安全闸）。"""
    return bool(str(rule.get("approved_by") or "").strip())


def overlay_of(rule, params=None) -> dict:
    """把一条规则摊平成解析 overlay 片段。`declare` 档必须带 `declared` 参数。

    `declared` 的形状＝**最终 overlay 的形状**，即 `{工作表名: 参数值}`。
    返回值直接挂到 `overlay_key` 下：`{overlay_key: declared}`。
    规则库里因此**不能再套一层参数名**——套了会与 `parse_ledger._parse_scope`
    错位，声明将静默失效（2026-09-16 实测并修正，见 tests/test_agent_heal.py）。
    """
    key = rule.get("overlay_key")
    if rule["executable"] == AUTO:
        return dict(rule.get("overlay") or {})
    if rule["executable"] == DECLARE:
        declared = (params or {}).get("declared") or rule.get("declared") or {}
        # 只过滤"馆员没填"：None / 空串 / 空容器。
        # ⚠ 不能用 `if v` —— 表头恰好落在第 0 行是合法声明，会被当成"没填"丢掉。
        merged = {k: v for k, v in declared.items()
                  if v is not None and v != "" and v != {} and v != []}
        if not merged:
            return {}
        return {key: merged} if key else {}
    return {}


# ---------------------------------------------------------------- 诊断与匹配
def _failure_text(failure) -> str:
    """把一次失败摊成可正则匹配的一段文字（消息 + 前若干条未过的断言）。"""
    parts = [str(failure.get("message") or "")]
    fails = failure.get("fails")
    if isinstance(fails, (list, tuple)):
        parts += [str(m) for m in fails]
    return " · ".join(parts)


def classify(failure) -> dict:
    """错误分类：错误码 + 症状文本。规则库按这两项匹配。"""
    return {
        "code": failure.get("code"),
        "message": failure.get("message"),
        "step": failure.get("step"),
        "symptom": _failure_text(failure),
    }


def _hits(failure, rules):
    """返回 (可执行命中, 拒绝命中)。**不做短路** —— 一次自愈要把能用的规则全用上。"""
    cls = classify(failure)
    if not cls["code"]:
        return [], []
    applyable, refused = [], []
    for r in rules:
        if r["code"] != cls["code"]:
            continue
        pat = (r.get("match") or {}).get("message_re")
        if pat and not re.search(pat, cls["symptom"]):
            continue

        rec = {"rule": r["id"], "name": r.get("name"), "doc": r.get("doc"),
               "executable": r["executable"], "advice": r.get("advice_unapproved"),
               "declared": r.get("declared")}
        if not is_approved(r):
            rec["why"] = "未确认规则类型（R-24）"
            rec["error_code"] = "RULE_UNAPPROVED"
            refused.append(rec)
            continue
        if r["executable"] == NEVER:
            rec["why"] = "设计上不可修复"
            refused.append(rec)
            continue
        ov = overlay_of(r)
        if not ov:
            rec["why"] = "馆员尚未声明参数（declared 为空）"
            rec["error_code"] = "RULE_UNAPPROVED"
            refused.append(rec)
            continue
        rec["overlay"] = ov
        applyable.append(rec)
    return applyable, refused


# ---------------------------------------------------------------- 落盘
def _write_repair_yaml(run_dir, failure, hit, refused, outcome) -> pathlib.Path | None:
    """写 `repair.yaml`（LLD §5.2）。字段名对齐文档：rule / params / reason / approved_by。"""
    if not run_dir:
        return None
    p = pathlib.Path(run_dir)
    try:
        p.mkdir(parents=True, exist_ok=True)
        first = (hit or refused or [{}])[0]
        body = {
            "ts": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "outcome": outcome,                  # repaired | refused | no_match
            "step": failure.get("step"),
            "error_code": failure.get("code"),
            "error_message": failure.get("message"),
            # —— 文档规定的四个字段 ——
            "rule": first.get("rule"),
            "params": first.get("overlay") or first.get("declared") or {},
            "reason": first.get("why") or (f"命中 {len(hit)} 条 auto 规则并合并提交"
                                           if hit else "规则库无匹配"),
            "approved_by": "项目组自测（待卜彤追认）" if hit else None,
            # —— 本次运行的完整记录（供 M4 审计与命中率统计）——
            "rules": [h["rule"] for h in hit],
            "overlay": {k: v for h in hit for k, v in h["overlay"].items()},
            "refused": [{k: v for k, v in r.items() if k != "declared"} for r in refused],
            "source": "src/agent/heal.py（规则库 src/agent/rules/repair_rules.yaml）",
        }
        p.joinpath("repair.yaml").write_text(
            yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return p / "repair.yaml"
    except OSError:
        return None          # 留痕失败不阻断生产（与 trace.py 同口径）


# ---------------------------------------------------------------- 对外
def attempt(failure, ctx, rules_path=None):
    """自愈钩子。返回 dict（已定方案）或 None（规则库无匹配）。

    **本函数永不抛异常**：它在 `flow.run` 的主干上，抛出去会把"台账脏"
    变成"程序崩"，两者要分得很清楚。
    """
    try:
        rules = load_rules(rules_path)
    except RuleError as e:
        _write_repair_yaml(ctx.get("run_dir"), failure or {},
                           [], [{"rule": None, "why": str(e), "error_code": "RULE_UNAPPROVED"}],
                           "refused")
        return {"rules": [], "overlay": {}, "refused": [{"rule": None, "why": str(e)}],
                "advice": [{"rule": None, "why": str(e)}], "outcome": "refused"}

    hit, refused = _hits(failure or {}, rules)
    overlay = {k: v for h in hit for k, v in h["overlay"].items()}

    outcome = "repaired" if overlay else ("refused" if refused else "no_match")
    path = _write_repair_yaml(ctx.get("run_dir"), failure or {}, hit, refused, outcome)

    if not hit and not refused:
        return None                       # 无匹配：交回编排器照裁决重跑一次后升级

    # 关键：把 overlay 挂到 ctx 上，`flow._invoke` 会在重跑时把它喂给 run_parse。
    if overlay:
        ctx["overlay"] = overlay

    return {
        "rules": [h["rule"] for h in hit],
        "overlay": overlay,
        "refused": refused,
        "advice": [{"rule": r["rule"], "why": r.get("why"), "doc": r.get("doc"),
                    "advice": r.get("advice")} for r in refused],
        "outcome": outcome,
        "repair_yaml": str(path) if path else None,
    }


def summary(out_root="out") -> dict:
    """统计历史运行里的规则命中情况（命中率 / 拒绝率）。

    只读 `out/**/repair.yaml`，不写任何东西。给 M4 审计与演示用。
    """
    root = pathlib.Path(out_root)
    n, by_rule, by_outcome, refused = 0, {}, {}, 0
    for f in sorted(root.rglob("repair.yaml")):
        try:
            rec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        n += 1
        by_outcome[rec.get("outcome")] = by_outcome.get(rec.get("outcome"), 0) + 1
        for rid in rec.get("rules") or []:
            by_rule[rid] = by_rule.get(rid, 0) + 1
        refused += len(rec.get("refused") or [])
    return {"n_runs_with_repair": n, "by_rule": by_rule,
            "by_outcome": by_outcome, "n_refused": refused,
            "n_rules_in_library": len(load_rules()) if RULES_PATH.exists() else 0}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="文衡自愈规则库 · 查看与统计")
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--show", action="store_true", help="列出规则库全部规则")
    a = ap.parse_args()
    if a.show:
        for r in load_rules():
            flag = "已确认" if is_approved(r) else "待确认"
            print(f"[{r['executable']:7s}][{flag}] {r['id']:22s} {r.get('name')} — {r.get('doc')}")
    print(json.dumps(summary(a.out_root), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
