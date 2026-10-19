# -*- coding: utf-8 -*-
"""「这一期下载的数据」打包下载（server/datapack.py + `/acquisition/datapack` 端点）。

2026-10-19 馆员需求：把已下载的原始数据打成一个 zip 存回本地（操作员也可下）。
测试只在 tmp 合成目录上跑——**绝不碰真 数据与复现/**（打包器只读源；这里把「只读」钉住）。
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import zipfile

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from server import datapack                            # noqa: E402
from server import app as app_module                   # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402


class _Req:
    """极简请求替身：`user_route` 的登录门只读 session 里的用户（这里用操作员账号）。"""
    session = {"user": "demo"}


def _mk_period_dirs(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    esi = tmp_path / "ESI数据" / "202603"
    inc = tmp_path / "incites" / "数据覆盖2015-2025.12.31"
    (esi).mkdir(parents=True)
    (inc / "sub").mkdir(parents=True)
    (esi / "Institutions.xlsx").write_bytes(b"esi-x")
    (esi / "下载信息.json").write_text("{}", encoding="utf-8")
    (inc / "数学.xlsx").write_bytes(b"inc-x")
    (inc / "sub" / "x.txt").write_text("hi", encoding="utf-8")
    return esi, inc


def test_pack_两路都打上_说明在包内(tmp_path):
    esi, inc = _mk_period_dirs(tmp_path)
    readme = datapack.build_readme(period="202603", snapshot="数据覆盖2015-2025.12.31",
                                   verified=56, expected=64, esi_dir=esi, incites_dir=inc)
    out = tmp_path / "pack.zip"
    stats = datapack.pack(out, period="202603", esi_dir=esi, incites_dir=inc, readme=readme)
    assert stats["esi_files"] == 2 and stats["incites_files"] == 2
    assert stats["bytes"] > 0
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert datapack.README_NAME in names
        assert "ESI数据/202603/Institutions.xlsx" in names
        assert "InCites数据/数据覆盖2015-2025.12.31/sub/x.txt" in names
        assert z.read("ESI数据/202603/Institutions.xlsx") == b"esi-x"
        txt = z.read(datapack.README_NAME).decode("utf-8")
    assert "期次：202603" in txt and "已取到 56 / 64" in txt
    # 源目录只读：打完包源文件原样
    assert (esi / "Institutions.xlsx").read_bytes() == b"esi-x"


def test_pack_只有一路也能打(tmp_path):
    esi, _ = _mk_period_dirs(tmp_path)
    out = tmp_path / "pack.zip"
    stats = datapack.pack(out, period="202603", esi_dir=esi, readme="（说明）")
    assert stats["esi_files"] == 2 and stats["incites_files"] == 0
    with zipfile.ZipFile(out) as z:
        assert not any(n.startswith(datapack.INCITES_ARC_ROOT) for n in z.namelist())


def test_pack_一个文件都没有_抛错且不留半成品(tmp_path):
    out = tmp_path / "pack.zip"
    with pytest.raises(datapack.EmptyPack):
        datapack.pack(out, period="202603", esi_dir=None, incites_dir=None, readme="x")
    assert not out.exists()


# ------------------------------------------------------------------ 端点（拆两个包：?source=esi|incites）
def _patch_roots(tmp_path, monkeypatch, st=None):
    monkeypatch.setattr(app_module.acquisition, "ESI_ROOT_DEFAULT", tmp_path / "ESI数据")
    monkeypatch.setattr(app_module.acquisition, "INCITES_ROOT_DEFAULT", tmp_path / "incites")
    monkeypatch.setattr(app_module.acquisition, "load",
                        lambda _p: st if st is not None else
                        {"snapshot": "数据覆盖2015-2025.12.31",
                         "totals": {"verified": 56, "expected": 64}})
    monkeypatch.setattr(app_module.acquisition, "resolve_snapshot", lambda *a, **k: "")


def test_端点_esi包_操作员可下_只含ESI_下完即删(tmp_path, monkeypatch):
    esi, _inc = _mk_period_dirs(tmp_path)
    _patch_roots(tmp_path, monkeypatch)
    r = asyncio.run(app_module.api_acq_datapack(_Req(), "202603", source="esi"))
    assert isinstance(r, FileResponse)
    assert r.filename.startswith("wenheng-esi-data-202603-") and r.filename.endswith(".zip")
    assert r.filename.isascii()
    p = pathlib.Path(r.path)
    assert p.exists() and zipfile.is_zipfile(p)
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        assert not any(n.startswith("InCites数据/") for n in names), "ESI 包里不该有 InCites"
        assert "ESI数据/202603/Institutions.xlsx" in names
        assert "（ESI 部分）" in z.read(datapack.README_NAME).decode("utf-8")
    assert r.background is not None
    asyncio.run(r.background())                      # 响应结束 → 临时件删除
    assert not p.exists()
    assert esi.is_dir()                              # 源目录只读、原样


def test_端点_incites包_只含incites(tmp_path, monkeypatch):
    _mk_period_dirs(tmp_path)
    _patch_roots(tmp_path, monkeypatch)
    r = asyncio.run(app_module.api_acq_datapack(_Req(), "202603", source="incites"))
    assert isinstance(r, FileResponse)
    assert r.filename.startswith("wenheng-incites-data-202603-")
    with zipfile.ZipFile(pathlib.Path(r.path)) as z:
        names = z.namelist()
        assert not any(n.startswith("ESI数据/") for n in names), "InCites 包里不该有 ESI"
        assert "InCites数据/数据覆盖2015-2025.12.31/数学.xlsx" in names
        assert "（InCites 部分）" in z.read(datapack.README_NAME).decode("utf-8")
    asyncio.run(r.background())


def test_端点_source非法_400(tmp_path, monkeypatch):
    _patch_roots(tmp_path, monkeypatch)
    r = asyncio.run(app_module.api_acq_datapack(_Req(), "202603", source="bogus"))
    assert isinstance(r, JSONResponse) and r.status_code == 400


def test_端点_没下过这一路_404(tmp_path, monkeypatch):
    _patch_roots(tmp_path, monkeypatch, st={})
    r = asyncio.run(app_module.api_acq_datapack(_Req(), "202603", source="esi"))
    assert isinstance(r, JSONResponse) and r.status_code == 404
    r2 = asyncio.run(app_module.api_acq_datapack(_Req(), "202603", source="incites"))
    assert isinstance(r2, JSONResponse) and r2.status_code == 404


def test_端点_非法期次_404():
    r = asyncio.run(app_module.api_acq_datapack(_Req(), "20260", source="esi"))
    assert r.status_code == 404
