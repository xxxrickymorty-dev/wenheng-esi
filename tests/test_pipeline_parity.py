# -*- coding: utf-8 -*-
"""双壳 parity（slow）：直跑与受控编排用同一份台账，核心产物必须一致。

两个壳的政策不同（直跑：进度 + 带病出稿；受控：状态机 + 自愈拦停），
但步骤体是同一份（`src/steps.py`）——本用例是 C1「steps 注册表」的验收：
为同一份台账各跑一遍，比表、比事实、比成品在场。任何一边又长出私有步骤体，
这里会先红。
"""
import json

import pytest

import run_pipeline

from agent import flow, states


@pytest.mark.slow
def test_双壳产物一致(latest_ledger, tmp_path):
    direct_root = tmp_path / "direct"
    agent_root = tmp_path / "agent"

    rc = run_pipeline.main(str(latest_ledger), out_root=str(direct_root))
    assert rc == 0, "直跑壳未返回 0"

    r = flow.run(str(latest_ledger), out_root=agent_root,
                 run_dir=agent_root / "_jobs" / "parity")
    assert r.status in (states.COMPLETED, states.WARNED), r.as_dict()
    assert r.period

    d1, d2 = direct_root / r.period, agent_root / r.period
    assert (d1 / "table2.csv").read_bytes() == (d2 / "table2.csv").read_bytes(), \
        "两壳的大表字节不一致 —— 步骤体又分叉了"
    v1 = json.loads((d1 / "overview_facts.json").read_text(encoding="utf-8"))
    v2 = json.loads((d2 / "overview_facts.json").read_text(encoding="utf-8"))
    assert v1 == v2, "两壳的概述事实不一致"
    # 说明：red_slots/报告初稿不在比对面内——直跑壳多跑省域/矩阵两个**壳内附加件**
    # （flow 不跑，也不在五步注册表里），fill_docx 会消费它们。这里只钉五步步骤体的 parity。
    assert list(d1.glob("报告初稿*.docx")), "直跑壳没出报告初稿"
    assert list(d2.glob("报告初稿*.docx")), "受控壳没出报告初稿"
