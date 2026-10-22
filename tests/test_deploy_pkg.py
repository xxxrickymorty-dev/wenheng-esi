# -*- coding: utf-8 -*-
"""部署打包口径（`tools/make_deploy_pkg.py`）：进什么、不进什么、缺件要拦、外发前要脱敏。

用合成目录树验（不依赖 out/202607 等真实数据）；口径写在打包脚本里，这里钉住它——
2026-09-17 的旧包是手搓 tar 命令，口径散在文档里，迟早漂。

脱敏这一组（2026-10-22）：包里有 `out/_state` 就是「外发演示包 = 外发人名」，
所以钉三件事——库与数据文本换成化名、`审批记录.md` 用脱敏库重渲染、**真名漏在包里就打包失败**；
另有一条反向断言：真库里的 actor 一个都不许被改动。
"""
import json
import pathlib
import sqlite3
import sys
import tarfile

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import make_deploy_pkg as pkg                                   # noqa: E402
import state_store as store                                     # noqa: E402 与打包脚本同一个模块实例

RECORD = "审批记录.md"


def _mkfile(p: pathlib.Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


def _write(p: pathlib.Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
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


def _demo_repo(tmp_path, *, signer="admin", filler="demo", extra=None):
    """演示包的样子：库里有签单/填写/任务，`out/` 下有带操作人的数据文本与《审批记录.md》。"""
    root = _fake_repo(tmp_path)
    _write(root / "out/202607" / RECORD,
           "# 审批记录 · 202607 期\n\n"
           "- 当前状态：**已签单**\n"
           f"- 签单人：{signer}\n\n"
           "| 时间 | 动作 | 操作人 | 待人工 | 说明 |\n|---|---|---|---|---|\n"
           f"| 2026-10-19 14:49:00 | 签单 | {signer} | 0 | {filler} 代签 |\n")
    _write(root / "out/202607/ai_calls.jsonl",
           '{"kind": "call", "actor": "%s", "period": "202607"}\n' % signer)
    _write(root / "out/_jobs/j1/job.json",
           '{"id": "j1", "period": "202607", "actor": "%s", "status": "completed"}'
           % filler)
    _write(root / "out/_acquisition/202607.json", '{"by": "%s"}' % signer)
    for rel, text in (extra or {}).items():
        _write(root / rel, text)

    db = root / "out/_state" / "wenheng.sqlite"
    db.unlink(missing_ok=True)                                   # 换成真 schema 的库
    fingerprint = pkg.approval_mod.fingerprint(root / "out/202607")
    store.put_approval(
        db, "202607",
        {"signed": True, "actor": signer, "signed_at": "2026-10-19 14:49:00",
         "note": f"{filler} 复核后签单", "manual_ack": True, "period": "202607",
         "snapshot": {"counts": {"total": 712, "text": 15, "cell": 591,
                                 "chart": 106, "manual": 4},
                      "assertions": {"total": 48, "fail": 0}},
         "fingerprint": fingerprint},
        history_entry={"action": "sign", "actor": signer, "at": "2026-10-19 14:49:00",
                       "note": f"{filler} 复核后签单", "manual_ack": True, "manual_open": 0})
    store.set_fill(db, "202607", "正文/p1::当期机构总数",
                   {"value": "10428", "by": filler, "at": "2026-10-19 14:48:46"})
    store.put_job(db, {"id": "j1", "period": "202607", "actor": filler,
                       "status": "completed", "created_at": "2026-10-19 10:11:53",
                       # 老记录里存的是绝对路径（本票要处理的那一类）
                       "input": str(root / "input" / pkg.ledger_mod.LEDGER_NAME)})
    return root, db


def _rels(root, include_data):
    return {str(p.relative_to(root)).replace("\\", "/")
            for p in pkg.collect(root, include_data)}


def _unpack(tar_path, dest):
    with tarfile.open(tar_path) as tf:
        tf.extractall(dest, filter="data")
    return dest / "wenheng"


def _rows(db, sql):
    con = sqlite3.connect(str(db))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


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


class Test脱敏:
    """2026-10-22：包里出现真实操作人就算外发人名。"""

    def test_库内三张表与payload换成化名(self, tmp_path):
        root, db = _demo_repo(tmp_path)
        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")
        pack_db = installed / "out/_state/wenheng.sqlite"

        assert _rows(pack_db, "SELECT actor FROM approvals") == [("管理员",)]
        assert [r[0] for r in _rows(pack_db, "SELECT DISTINCT actor FROM approval_history")] \
            == ["管理员"]
        assert _rows(pack_db, "SELECT actor FROM manual_inputs") == [("馆员",)]

        # payload 里的操作人（含 jobs 的 actor、填写的 by）也换掉，且 JSON 仍然有效
        approvals_payload = json.loads(
            _rows(pack_db, "SELECT payload FROM approvals")[0][0])
        assert approvals_payload["actor"] == "管理员"
        assert "admin" not in json.dumps(approvals_payload, ensure_ascii=False)
        fill_payload = json.loads(
            _rows(pack_db, "SELECT payload FROM manual_inputs")[0][0])
        assert fill_payload["by"] == "馆员"
        job_payload = json.loads(_rows(pack_db, "SELECT payload FROM jobs")[0][0])
        assert job_payload["actor"] == "馆员"
        assert job_payload["id"] == "j1"                        # 其余字段一个不改

        # 库文件里连自由页的原文都不该留（VACUUM 之后）
        raw = pack_db.read_bytes()
        assert b"admin" not in raw and b"demo" not in raw

    def test_审批记录md用脱敏库重渲染(self, tmp_path):
        root, _db = _demo_repo(tmp_path)
        source = (root / "out/202607" / RECORD).read_text(encoding="utf-8")
        assert "admin" in source and "demo" in source                    # 原件确实带真名（未改）

        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")
        md = (installed / "out/202607" / RECORD).read_text(encoding="utf-8")

        assert "管理员" in md and "馆员" in md
        assert "admin" not in md and "demo" not in md
        assert "已签单" in md                                            # 状态照旧由产物现场判
        assert "10428" not in md                                         # md 只写审批，不搬填写值
        assert (root / "out/202607" / RECORD).read_text(encoding="utf-8") == source

    def test_数据面的文本也换化名(self, tmp_path):
        root, _db = _demo_repo(tmp_path)
        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")

        ai_log = (installed / "out/202607/ai_calls.jsonl").read_text(encoding="utf-8")
        assert json.loads(ai_log)["actor"] == "管理员"
        job_json = json.loads(
            (installed / "out/_jobs/j1/job.json").read_text(encoding="utf-8"))
        assert job_json["actor"] == "馆员"
        acq = json.loads(
            (installed / "out/_acquisition/202607.json").read_text(encoding="utf-8"))
        assert acq["by"] == "管理员"
        assert pkg.scan_package(p, {"admin": "管理员", "demo": "馆员"}) == []

    def test_脱敏不动真库(self, tmp_path):
        root, db = _demo_repo(tmp_path)
        pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        assert _rows(db, "SELECT actor FROM approvals") == [("admin",)]
        assert _rows(db, "SELECT actor FROM manual_inputs") == [("demo",)]
        assert json.loads(_rows(db, "SELECT payload FROM jobs")[0][0])["actor"] == "demo"

    def test_脱敏不破坏签单有效性与指纹(self, tmp_path):
        """`stale` 只看 `out/<期次>/` 产物的 sha256，与 actor 无关——换名字不该让签单失效。"""
        root, _db = _demo_repo(tmp_path)
        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")
        out_dir = installed / "out/202607"
        with pkg._state_db_env(installed / "out/_state/wenheng.sqlite"):
            rec = pkg.approval_mod.read(out_dir)
            assert rec["actor"] == "管理员"
            assert pkg.approval_mod.status(out_dir, rec) == "signed"

    def test_额外词也能换(self, tmp_path):
        """批注这类自由文本里的人名不在 actor 里，用 --redact-term 追加。"""
        root, _db = _demo_repo(tmp_path, extra={"out/202607/备忘.md": "张三改了学科数\n"})
        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz",
                      extra_terms=["张三=馆员"])
        installed = _unpack(p, tmp_path / "unpacked")
        assert (installed / "out/202607/备忘.md").read_text(encoding="utf-8") \
            == "馆员改了学科数\n"

    def test_漏一个真名就打包失败(self, tmp_path):
        """判据是「一个真名都不剩」：脱敏覆盖不到的位置必须让打包失败，而不是静静放过。"""
        root, _db = _demo_repo(
            tmp_path, signer="张三", filler="馆员",
            extra={"out/202607/anomaly.dat": "操作人：张三\n"})   # 未知扩展名 → 不替换
        out = tmp_path / "pkg"
        try:
            pkg.build(root, out, include_data=True, name="leak.tar.gz")
        except pkg.LeakError as exc:
            assert any("anomaly.dat" in h["member"] for h in exc.hits)
            assert all(h["term"] == "张三" for h in exc.hits)
        else:
            raise AssertionError("带真名的包必须打包失败")
        assert not (out / "leak.tar.gz").exists()                 # 带名字的包不留
        assert not (out / "leak.tar.gz.sha256").exists()

    def test_库内文本列泄漏能被扫到(self, tmp_path):
        """库是二进制文件，字节扫不到不代表没有名字——这条钉「按文本列逐格扫」。"""
        db = tmp_path / "state.sqlite"
        store.put_approval(db, "202607",
                           {"signed": True, "actor": "张三", "period": "202607"},
                           history_entry={"action": "sign", "actor": "张三", "at": ""})
        hits = pkg._scan_sqlite(db.read_bytes(), tmp_path,
                                "wenheng/out/_state/wenheng.sqlite", {"张三": "馆员"})
        assert any((h.get("where") or "").startswith("approvals.") for h in hits)
        assert all(h["count"] >= 1 for h in hits)

    def test_显式关闭脱敏就不换(self, tmp_path):
        root, _db = _demo_repo(tmp_path)
        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="raw.tar.gz",
                      redact=False)
        installed = _unpack(p, tmp_path / "unpacked")
        md = (installed / "out/202607" / RECORD).read_text(encoding="utf-8")
        assert "admin" in md                                     # 自用备份：名字原样留着


class Test路径与用户名:
    """2026-10-22 第二票：包里出现本机绝对路径 / 用户名同样不能外发。

    两档范围（理由见 `tools/make_deploy_pkg.py` 模块头）：
    本机实际路径全包扫，通用形态（盘符 / `/home/` / `/Users/`）只看数据面。
    """

    def test_数据面与本机路径换成仓库相对(self, tmp_path):
        root, _db = _demo_repo(tmp_path)
        abs_input = str(root / "input" / pkg.ledger_mod.LEDGER_NAME)
        _write(root / "out/202607/audit_record.json",
               json.dumps({"out_dir": str(root / "out/202607"), "ledger": abs_input},
                          ensure_ascii=False))

        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")

        rec = json.loads((installed / "out/202607/audit_record.json").read_text(encoding="utf-8"))
        assert rec["out_dir"].replace("\\", "/") == "out/202607"     # 仓库根前缀去掉
        # 数据面文本只去前缀（分隔符原样留着：日志与正文里的路径不保证是字段值）；
        # 真正要在部署机上解析的是库里的任务记录，那条见下面。
        assert rec["ledger"].replace("\\", "/") == f"input/{pkg.ledger_mod.LEDGER_NAME}"
        assert not pkg.DRIVE_RE.search(json.dumps(rec, ensure_ascii=False))

        # 库里的老记录（payload 存绝对路径）换成**posix** 仓库相对：
        # 部署机是 Linux，`out\_jobs\…` 在那里会被当成一个文件名。
        job_payload = json.loads(_rows(
            installed / "out/_state/wenheng.sqlite", "SELECT payload FROM jobs")[0][0])
        assert job_payload["input"] == f"input/{pkg.ledger_mod.LEDGER_NAME}"
        assert not pkg.DRIVE_RE.search(json.dumps(job_payload, ensure_ascii=False))

    def test_数据面植入本机用户目录就打包失败(self, tmp_path):
        """判据是「一个本机路径都不剩」：脱敏覆盖不到的位置必须让打包失败。"""
        root, _db = _demo_repo(tmp_path, extra={
            "out/202607/导出的路径.txt":
                "打开 C:\\Users\\someone\\Desktop\\wenheng\\out\\202607\\报告初稿.docx\n"})
        out = tmp_path / "pkg"
        try:
            pkg.build(root, out, include_data=True, name="leak-path.tar.gz")
        except pkg.LeakError as exc:
            assert any("导出的路径.txt" in h["member"] for h in exc.hits)
            assert any(h["term"] == "盘符路径" for h in exc.hits)
            assert all(h["count"] >= 1 for h in exc.hits)
        else:
            raise AssertionError("带本机路径的包必须打包失败")
        assert not (out / "leak-path.tar.gz").exists()
        assert not (out / "leak-path.tar.gz.sha256").exists()

    def test_代码与文档里的通用前缀不算泄漏(self, tmp_path):
        """`C:/Users/xxx` 是 docstring 里的常见举例；把它算命中，闸门会永远红。"""
        root, _db = _demo_repo(tmp_path, extra={
            "docs/部署手册.md": "示例：数据放在 `C:/Users/xxx/Desktop/wenheng/input/` 下。\n"})
        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")
        assert (installed / "docs/部署手册.md").exists()
        assert pkg.scan_package(p, {}, root) == []

    def test_本机实际路径在代码里也拦(self, tmp_path):
        """通用前缀可以举例，**本机真实路径**不行——代码里写死开发机根目录同样是外发本机信息。"""
        root, _db = _demo_repo(tmp_path)
        _write(root / "docs/笔记.md", f"截图取自 {root}/out/202607\n")
        try:
            pkg.build(root, tmp_path / "pkg", include_data=True, name="leak-doc.tar.gz")
        except pkg.LeakError as exc:
            assert any("笔记.md" in h["member"] for h in exc.hits)
            assert any(h["term"] == "本机工作区路径" for h in exc.hits)
        else:
            raise AssertionError("代码/文档里出现本机真实路径也要打包失败")

    def test_家目录写法换成代字号(self, tmp_path):
        """家目录（`%USERPROFILE%` / `$HOME` 的展开形态）不是仓库路径，换成 `~/` 保留可读性。"""
        root, _db = _demo_repo(tmp_path)
        home = pathlib.Path.home()
        _write(root / "out/202607/env_note.txt", f"缓存位于 {home / 'AppData' / 'cache'}\n")

        p = pkg.build(root, tmp_path / "pkg", include_data=True, name="d.tar.gz")
        installed = _unpack(p, tmp_path / "unpacked")
        note = (installed / "out/202607/env_note.txt").read_text(encoding="utf-8")
        assert note.startswith("缓存位于 ~/"), note
        assert str(home) not in note and "Users" not in note
