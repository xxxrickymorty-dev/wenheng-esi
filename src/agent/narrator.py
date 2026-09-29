# -*- coding: utf-8 -*-
"""诊断叙事 · 过渡 shim（D1 起行为已搬进 `src/ai` 的 diagnose 构建器）。

迁移记录（SPEC §4 步骤 1）：
    `narrator.compose` 的规则拼装（本次实况 + 怎么核对 + 规则库口径）已迁入
    `src/ai/_diagnose.py`；`flow.py` 已改调 `ai.run("diagnose", …)`。
    本模块**留一轮**，只服务 `run_pipeline._write_diagnosis` 直跑路径的旧签名；
    D6 收编清理时删除，调用点全部改 `ai.run`。

    旧的 `ollama` / `http` 多后端随之收编（D3 统一走 OpenAI 兼容适配器，key 仅服务器 env）。

纪律不变：rule 模式输出与迁移前**逐字一致**（金样 `tests/fixtures/ai/diagnose_rule_*.txt` 对拍守）。
"""
from __future__ import annotations

import contextlib

BACKENDS = ("rule",)          # 旧多后端已收编；测试替身经 ai.using(brain=…) 注入
DEFAULT_BACKEND = "rule"


def compose(failure, repair=None, backend=None, *, data_root=None, actor="system"):
    """旧签名兼容：返回 (lines, meta)。

    `backend=` 参数保留仅为签名兼容（AI 层禁后端旋钮，SPEC §1）；
    `data_root=` 指定留痕根（run_pipeline 传产物目录的上一级，避免落到别处）。
    """
    import ai                                                  # noqa: PLC0415

    scope = ai.using(data_root=data_root) if data_root else contextlib.nullcontext()
    with scope:
        ans = ai.run("diagnose", str((failure or {}).get("period") or ""),
                     payload={"failure": failure, "repair": repair}, actor=actor)
    lines = ans.text.splitlines() if ans.text else []
    meta = {"backend": ans.backend, "mode": ans.mode,
            "segments": [s.as_dict() for s in ans.segments],
            "record_id": ans.record_id, "notice": ans.notice}
    return lines, meta


def main():
    """手工验一把：`python -m agent.narrator`（用一条样例失败）。"""
    import json

    sample = {"code": "ASSERT_FAIL", "message": "2 项断言未过",
              "period": "202607",
              "fails": ["宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"],
              "diagnostics": {"unmatched_names": {"total_cites": ["某某新学科"]}}}
    repair = {"advice": [{"rule": "discipline_alias_map",
                          "why": "未确认规则类型（R-24）",
                          "doc": "WH-DOC-04 §6.5",
                          "advice": "请馆员核对该学科归属后，在 repair_rules.yaml 填 approved_by"}]}
    lines, meta = compose(sample, repair)
    print("\n".join(lines))
    print("\n--- meta ---")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
