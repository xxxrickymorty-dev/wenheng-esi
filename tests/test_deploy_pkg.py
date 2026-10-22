# -*- coding: utf-8 -*-
"""部署打包口径（`tools/make_deploy_pkg.py`）：进什么、不进什么、缺件要拦。

用合成目录树验（不依赖 out/202607 等真实数据）；口径写在打包脚本里，这里钉住它——
2026-09-17 的旧包是手搓 tar 命令，口径散在文档里，迟早漂。
"""
import pathlib
import sqlite3
import sys
import tarfile

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import make_deploy_pkg as pkg                                   # noqa: E402


def _mkfile(p: pathlib.Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


def _mkdb(p: pathlib.Path):
    """建一个**真** sqlite 文件：`build()` 打包前会对主库做 `wal_checkpoint`。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    con.commit()
    con.close()
    return p


def _fake_repo(tmp_path):
    root = tmp_path / "wenheng"
    for rel in ("pyproject.toml", "CONTEXT.md", "GLOSSARY.md", "AGENTS.md",
                "src/run_pipeline.py", "server/app.py", "server/.env",
                "server/.env.example", "tools/x.py", "tests/test_x.py",
                "master/母版.docx", "docs/部署手册.md",
                "web/dist/index.html", "web/dist/assets/app.js",
                "web/node_modules/pkg/index.js", "web/src/App.tsx",
                f"input/{pkg.ledger_mod.LEDGER_NAME}",
                "out/202607/red_slots.json",
                "out/202607/overview_facts.json", "out/202607/报告初稿_202607.docx",
                "out/202607/_superseded/old.docx", "out/202609/x.json",
                "out/_acquisition/202609/监测表.xlsx",
                "out/_jobs/20260901/progress.jsonl", "tmp/junk.txt",
                ".venv/pyvenv.cfg", "src/__pycache__/m.pyc",
                "server/e2e_report.txt",
                "out/_state/backups/wenheng-20261022-075735.sqlite",
                "out/_state/backups/wenheng-20261022-075735.sqlite-wal",
                "out/_state/backups/wenheng-20261022-075735.sqlite-shm"):
        _mkfile(root / rel)
    _mkdb(root / "out/_state" / "wenheng.sqlite")
    return root


def _rels(root, include_data):
    return {str(p.relative_to(root)).replace("\\", "/")
            for p in pkg.collect(root, include_data)}


class Test进包口径:
    def test_代码与构建产物进包(self, tmp_path):
        rels = _rels(_fake_repo(tmp_path), include_data=True)
        for rel in ("pyproject.toml", "GLOSSARY.md", "src/run_pipeline.py", "server/app.py",
                    "server/.env.example", "web/dist/index.html", "web/dist/assets/app.js",
                    "master/母版.docx", "docs/部署手册.md"):
            assert rel in rels, rel

    def test_密钥与开发物不进包(self, tmp_path):
        rels = _rels(_fake_repo(tmp_path), include_data=True)
        for rel in ("server/.env", "web/node_modules/pkg/index.js", "web/src/App.tsx",
                    "tmp/junk.txt", ".venv/pyvenv.cfg", "src/__pycache__/m.pyc",
                    "server/e2e_report.txt", "out/202607/_superseded/old.docx",
                    "out/202609/x.json"):
            assert rel not in rels, rel

    def test_演示数据与任务史进包(self, tmp_path):
        rels = _rels(_fake_repo(tmp_path), include_data=True)
        for rel in (f"input/{pkg.ledger_mod.LEDGER_NAME}", "out/202607/red_slots.json",
                    "out/_acquisition/202609/监测表.xlsx",
                    "out/_jobs/20260901/progress.jsonl"):
            assert rel in rels, rel

    def test_状态库进包(self, tmp_path):
        """签单/复核/任务记录都在 `out/_state`（ADR-0012 决定 11）——漏了它包就是空的。"""
        root = _fake_repo(tmp_path)
        _mkdb(root / "out/_state" / "wenheng.sqlite")
        assert "out/_state/wenheng.sqlite" in _rels(root, include_data=True)
        assert "out/_state/wenheng.sqlite" not in _rels(root, include_data=False)

    def test_状态库备份不进包(self, tmp_path):
        """`out/_state/backups/` 是库的副本（含已清理的 e2e 历史）——只该留在本机。

        主库要进包，备份（连同 `-wal` / `-shm` 副文件）不进；本机目录位置不动。
        """
        rels = _rels(_fake_repo(tmp_path), include_data=True)
        assert "out/_state/wenheng.sqlite" in rels
        assert not [r for r in rels if r.startswith("out/_state/backups/")]

    def test_纯代码包不含数据(self, tmp_path):
        rels = _rels(_fake_repo(tmp_path), include_data=False)
        assert "web/dist/index.html" in rels
        assert not any(r.startswith(("input/", "out/")) for r in rels)


class Test预检:
    def test_缺dist要拦(self, tmp_path):
        root = _fake_repo(tmp_path)
        (root / "web" / "dist" / "index.html").unlink()
        problems = pkg.preflight(root, include_data=True)
        assert any("index.html" in p for p in problems)

    def test_齐件不拦(self, tmp_path):
        root = _fake_repo(tmp_path)
        assert pkg.preflight(root, include_data=True) == []
        assert pkg.preflight(root, include_data=False) == []

    def test_纯代码包不查数据(self, tmp_path):
        root = _fake_repo(tmp_path)
        (root / "out" / "202607" / "red_slots.json").unlink()
        assert pkg.preflight(root, include_data=False) == []


class Test打包:
    def test_包内顶层是wenheng且不含密钥(self, tmp_path):
        root = _fake_repo(tmp_path)
        out = tmp_path / "pkg"
        p = pkg.build(root, out, include_data=True, name="wenheng-demo-test.tar.gz")
        assert p.exists() and (out / (p.name + ".sha256")).exists()
        with tarfile.open(p) as tf:
            names = tf.getnames()
        assert "wenheng/pyproject.toml" in names
        assert "wenheng/web/dist/index.html" in names
        assert "wenheng/out/_state/wenheng.sqlite" in names                # 主库进包
        assert not [n for n in names if n.startswith("wenheng/out/_state/backups/")]
        assert not [n for n in names
                    if n.startswith("wenheng/server/.env") and not n.endswith(".example")]
