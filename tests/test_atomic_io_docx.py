# -*- coding: utf-8 -*-
"""R2-5【S2】产物非原子写：报告 docx 与两份清单必须先落 tmp 再 `os.replace`。

红队第二轮（`docs/reviews/2026-10-28-ADR0014-对抗性审查-第二轮.md` R2-5）：
`fill_docx.main` 里 `doc.save(out_path)` 之后紧跟 `write_text(red_slots.json)`，
二者都不是原子写 —— 中途崩掉会留下半截 docx / 半截 JSON，而这两样正是
`FINAL_PRODUCTS`（会被当报告看）。

本文件钉住：
  1. `doc.save` 写同目录 tmp → `os.replace`；失败时旧产物不动、tmp 清干净；
  2. 两份清单走 `atomic_io.write_text_atomic`（源码里不许再有裸 `write_text`）；
  3. `atomic_io.replace` 的退避重试真的会重试（Windows 上 `os.replace` 撞读句柄）。
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                   # noqa: E402

import atomic_io                                                # noqa: E402
import fill_docx                                                # noqa: E402


class _FakeDoc:
    """只实现 `save`：写什么由用例决定（真 docx 太大，这里验的是落盘时序）。"""

    def __init__(self, payload=b"NEW"):
        self.payload = payload

    def save(self, path):
        pathlib.Path(path).write_bytes(self.payload)


def _no_tmp(d):
    return not list(pathlib.Path(d).glob("*.tmp-*"))


class TestDocx原子写:
    def test_成功时换成新内容且不留tmp(self, tmp_path):
        out = tmp_path / "报告初稿_209901（试排）.docx"
        out.write_bytes(b"OLD")
        tmp = atomic_io.tmp_path(out)

        fill_docx._save_docx(_FakeDoc(b"NEW"), tmp, out)

        assert out.read_bytes() == b"NEW"
        assert _no_tmp(tmp_path)

    def test_替换失败时旧产物不动且不留tmp(self, tmp_path, monkeypatch):
        out = tmp_path / "报告初稿_209901（试排）.docx"
        out.write_bytes(b"OLD")

        def boom(*_a, **_k):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(atomic_io.os, "replace", boom)

        with pytest.raises(OSError):
            fill_docx._save_docx(_FakeDoc(b"NEW"), atomic_io.tmp_path(out), out)

        assert out.read_bytes() == b"OLD", "失败时不能动上一次的完整产物"
        assert _no_tmp(tmp_path), "tmp 必须清掉，别留在产物目录里"

    def test_保存阶段就失败也不动旧产物(self, tmp_path):
        out = tmp_path / "报告初稿_209901（试排）.docx"
        out.write_bytes(b"OLD")

        class Bad(_FakeDoc):
            def save(self, path):
                pathlib.Path(path).write_bytes(b"HALF")     # 写了半截
                raise RuntimeError("disk full")

        with pytest.raises(RuntimeError):
            fill_docx._save_docx(Bad(), atomic_io.tmp_path(out), out)

        assert out.read_bytes() == b"OLD"
        assert _no_tmp(tmp_path)


class Test清单走原子写:
    def test_main里没有裸write_text也没有裸doc_save(self):
        """源码级守卫：两份清单和 docx 都不许绕过 `atomic_io` / `_save_docx`。"""
        tree = ast.parse(pathlib.Path(fill_docx.__file__).read_text(encoding="utf-8"))
        bare_writes, bare_saves = [], []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr == "write_text":
                    bare_writes.append((fn.name, node.lineno))
                if node.func.attr == "save" and fn.name != "_save_docx":
                    bare_saves.append((fn.name, node.lineno))
        assert not bare_saves, f"doc.save 只许出现在 _save_docx 里：{bare_saves}"
        assert not bare_writes, f"清单必须走 atomic_io.write_text_atomic：{bare_writes}"

    def test_原子写与write_text逐字节相同(self, tmp_path):
        """ADR-0012 的硬要求：只换怎么写，不换字节（换行翻译按平台）。"""
        text = '[\n {\n  "location": "T19/整表"\n }\n]'
        want = tmp_path / "want.json"
        want.write_text(text, encoding="utf-8")
        got = tmp_path / "got.json"

        atomic_io.write_text_atomic(got, text)

        assert got.read_bytes() == want.read_bytes()


class TestReplace重试:
    def test_撞权限错误会退避重试(self, tmp_path, monkeypatch):
        """Windows 上 `os.replace` 撞并发读句柄是常态：第一次失败不能直接放弃。"""
        src = tmp_path / "a.tmp-1-abc"
        src.write_bytes(b"x")
        dst = tmp_path / "a.txt"
        dst.write_bytes(b"old")
        real = atomic_io.os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("WinError 32")
            return real(a, b)

        monkeypatch.setattr(atomic_io.os, "replace", flaky)
        monkeypatch.setattr(atomic_io._acq, "WRITE_RETRY_SLEEP", 0.0)

        atomic_io.replace(src, dst)

        assert calls["n"] == 2
        assert dst.read_bytes() == b"x"
