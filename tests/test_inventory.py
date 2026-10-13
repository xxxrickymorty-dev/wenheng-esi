# -*- coding: utf-8 -*-
"""盘点（票 02）：四件「必需件」按件在不在判 + 「未发布」语义 + 最新完整一期。

全程 tmp 路径注入（repo_root / filled），不读真台账与真数据目录。
「未发布」＝该期不在主台账的有效期次里（rick 2026-10-10 定）：随发布才到的
两件（顶尖论文清单 / InCites 快照）一律报「未到」，不去翻本机试排预览件。
"""
from __future__ import annotations

import pytest

import inventory

LEDGER_NAME = "云大全学科排名、阈值动态检测表.xlsx"
#: 与 SNAP_MAP 对齐的快照目录（测试只用到这几期）。
SNAPS = {"202605": "数据覆盖2016-2026.02.28", "202607": "数据覆盖2016-2026.04.30",
         "202609": "数据覆盖2016-2026.06.30"}


@pytest.fixture()
def roots(tmp_path):
    """(仓库根, 数据与复现根) 两块 tmp 目录。"""
    repo = tmp_path / "wenheng"
    repo.mkdir()
    data = tmp_path / "数据与复现"
    return repo, data


def seed(repo, data, period, *, monitor=True, papers=True, esi=True, esi_zip=False, incites=True):
    if monitor:
        # 当期核对副本：out/_acquisition/<期次>/监测表.xlsx（2026-10-13 起 input/ 只放母本）
        d = repo / "out" / "_acquisition" / period
        d.mkdir(parents=True, exist_ok=True)
        (d / "监测表.xlsx").write_bytes(b"x")
    if papers:
        d = repo / "out" / "_acquisition" / period
        d.mkdir(parents=True, exist_ok=True)
        (d / "顶尖论文清单.csv").write_text("a,b\n", encoding="utf-8")
    if esi:
        (data / "ESI数据" / period).mkdir(parents=True, exist_ok=True)
    if esi_zip:
        (data / "ESI数据").mkdir(parents=True, exist_ok=True)
        (data / "ESI数据" / f"{period}.zip").write_bytes(b"PK")
    if incites:
        (data / "incites" / SNAPS[period]).mkdir(parents=True, exist_ok=True)
    return repo, data


def states(inv):
    return {p.key: (p.state, p.note) for p in inv.pieces}


# ------------------------------------------------------------------ 已发布
def test_已发布四件齐(roots):
    repo, data = roots
    seed(repo, data, "202607")
    inv = inventory.scan("202607", repo_root=repo, filled=["202605", "202607"])
    assert inv is not None and inv.released and inv.ok and inv.n_missing == 0
    assert [p.label for p in inv.pieces] == ["动态监测表", "ESI 原始包", "顶尖论文清单", "InCites 快照"]
    assert inv.fallback == "", "齐了不需要替代期次"


def test_已发布缺一件_照实报缺并给替代(roots):
    repo, data = roots
    seed(repo, data, "202605")
    seed(repo, data, "202607", papers=False)
    inv = inventory.scan("202607", repo_root=repo, filled=["202605", "202607"])
    assert not inv.ok and inv.n_missing == 1
    assert states(inv)["papers"] == ("missing", ""), "已发布期次的缺件照实判（不带「未到」注记）"
    assert inv.fallback == "202605", "替代期次＝最近一个四件齐的有效期次"


def test_ESI包zip也算已有(roots):
    repo, data = roots
    seed(repo, data, "202607", esi=False, esi_zip=True)
    inv = inventory.scan("202607", repo_root=repo, filled=["202607"])
    assert states(inv)["esi"][0] == "ok"


def test_清单认取数落地的_数据与复现期次论文清单xlsx(roots):
    """2026-10-11 修：202609 的清单来自 Clarivate 取数落地的
    `数据与复现/<期次>论文清单.xlsx`（college_stats source 可证）——
    此前只认 input 下的 csv，把已完成的期次误报「缺 1 件」。"""
    repo, data = roots
    seed(repo, data, "202609", papers=False)
    data.mkdir(parents=True, exist_ok=True)
    (data / "202609论文清单.xlsx").write_bytes(b"x")
    inv = inventory.scan("202609", repo_root=repo, filled=["202609"])
    assert states(inv)["papers"][0] == "ok"
    assert inv.ok, "四件齐"


def test_清单认核对区下的xlsx(roots):
    repo, data = roots
    seed(repo, data, "202607", papers=False)
    (repo / "out" / "_acquisition" / "202607" / "202607论文清单.xlsx").write_bytes(b"x")
    inv = inventory.scan("202607", repo_root=repo, filled=["202607"])
    assert states(inv)["papers"][0] == "ok"


# ------------------------------------------------------------------ 未发布
def test_未发布_随发布的两件报未到_不论本机文件(roots):
    repo, data = roots
    seed(repo, data, "202607")                        # 替代期次：四件齐
    seed(repo, data, "202609")                        # 本机文件都在（试排预览件）
    inv = inventory.scan("202609", repo_root=repo, filled=["202605", "202607"])
    assert inv is not None and not inv.released
    st = states(inv)
    assert st["monitor"][0] == "ok" and st["esi"][0] == "ok", "监测表/ESI 包照文件判"
    assert st["papers"] == ("missing", "未到（随发布）"), "顶尖论文清单随发布才到，不翻预览件"
    assert st["incites"] == ("missing", "未到（随发布）"), "InCites 快照同上"
    assert inv.n_missing == 2 and inv.fallback == "202607"


def test_最新完整一期_跳过不齐的(roots):
    repo, data = roots
    seed(repo, data, "202605")
    seed(repo, data, "202607", papers=False)          # 最近一期不齐
    inv = inventory.scan("202609", repo_root=repo, filled=["202605", "202607"])
    assert inv.fallback == "202605"


def test_没有可用替代_替代为空(roots):
    repo, data = roots
    seed(repo, data, "202609")
    inv = inventory.scan("202609", repo_root=repo, filled=["202607"])   # 202607 本机无件
    assert inv.fallback == ""


# ------------------------------------------------------------------ 台账读不动
def test_台账读不动_返回None不编(roots):
    repo, data = roots
    seed(repo, data, "202607")
    assert inventory.scan("202607", repo_root=repo,
                          ledger_path=repo / "不存在的台账.xlsx") is None


def test_有效期次读得动_自动判发布(roots, monkeypatch):
    repo, data = roots
    seed(repo, data, "202607")
    monkeypatch.setattr(inventory, "_filled_for", lambda p: ["202605", "202607"])
    inv = inventory.scan("202607", repo_root=repo,
                         ledger_path=repo / "任意.xlsx")
    assert inv is not None and inv.released
