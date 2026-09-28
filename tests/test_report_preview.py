# -*- coding: utf-8 -*-
"""审核台 · 试排报告预览（docx → 可渲染块 + 在线填空字段）。

覆盖四件事：
1. 解析产出：段落/表格/图块齐全，空位给的字段 id 与工作台同一套规则；
2. 字段闭环：预览里的字段 id，正是「重出报告」能替换进 docx 的键；
3. 图片按 rId 可取、越权/不存在一律 None；
4. 签单闸门：有「已填未写入」的填值时 409 —— 防签出一份不含填值的稿。
"""
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _guard_registry import skip_unless                          # noqa: E402
from server import report_preview, workbench                     # noqa: E402
from server.app import resolve_period_dir                        # noqa: E402
from server import app as app_module, config                     # noqa: E402


class _Req:
    def __init__(self, user, method="GET", body=None):
        self.session = {"user": user}
        self.method = method
        self.body = body

    async def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def _any_period_dir_with_docx(repo):
    out = repo / "out"
    if not out.exists():
        return None
    cands = [d for d in sorted(out.iterdir())
             if d.is_dir() and list(d.glob("报告初稿_*.docx"))]
    return cands[-1] if cands else None


class Test解析:
    def test_有段表格和图块且字段id与工作台一致(self, repo):
        d = _any_period_dir_with_docx(repo)
        if d is None:
            skip_unless("out/ 没有带 docx 的期次",
                        lambda: _any_period_dir_with_docx(repo) is not None)
        data = report_preview.build(d)
        kinds = {b["t"] for b in data["blocks"]}
        assert "p" in kinds, "报告预览必须有段落"
        assert data["docx"].endswith(".docx")
        assert data["blocks"], "报告预览不应为空"

        # 字段 id ⊆ 工作台的 todo id（同一套「位置::标记文字」规则；
        # 两边一旦漂移，在线填的值会被写到报告不认的键上）
        if data["fields"]:
            wb = workbench.build(d)
            known = {t["id"] for t in wb["todo_fill"]}
            extra = set(data["fields"]) - known
            assert not extra, f"预览字段必须是工作台认识的键，多了：{extra}"

    def test_空位切分不跨run不丢字(self):
        segs, n_ph = report_preview._segments(
            [["据【手工：ESI发布日期】ESI最新数据显示", False, 15.0]],
            None, {"ESI发布日期": ["正文/p1::ESI发布日期"]})
        assert n_ph == 1
        assert "".join(s.get("t") or f"【{s.get('ph')}】" for s in segs) \
            == "据【正文/p1::ESI发布日期】ESI最新数据显示"

    def test_未知标记不硬凑字段(self):
        segs, n_ph = report_preview._segments(
            [["据【手工：没人认识的空】…", False, 15.0]], None, {})
        assert n_ph == 0
        assert segs and segs[0]["t"].startswith("据")

    def test_图片按rid可取且非法rid拒绝(self, repo):
        d = _any_period_dir_with_docx(repo)
        if d is None:
            skip_unless("out/ 没有带 docx 的期次",
                        lambda: _any_period_dir_with_docx(repo) is not None)
        data = report_preview.build(d)
        rids = [b["rid"] for b in data["blocks"] if b["t"] == "img"]
        if not rids:
            skip_unless("该期 docx 内无正文插图",
                        lambda: bool([b for b in report_preview.build(d)["blocks"]
                                      if b["t"] == "img"]))
        blob, ctype = report_preview.image(d, rids[0])
        assert blob and ctype.startswith("image/")
        assert report_preview.image(d, "rId999999") is None
        assert report_preview.image(d, "../../etc/passwd") is None


class Test路由:
    def test_路由是GET_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/periods/{period}/report-preview")' in src
        assert '@app.get("/api/periods/{period}/report-image/{rid}")' in src

    def test_预览用require_admin(self):
        assert asyncio.run(app_module.api_period_report_preview(
            _Req(config.GUEST_USER), "202609")).status_code == 403
        assert asyncio.run(app_module.api_period_report_preview(
            _Req(None), "202609")).status_code == 401

    def test_图片用require_admin(self):
        assert asyncio.run(app_module.api_period_report_image(
            _Req(config.GUEST_USER), "202609", "rId1")).status_code == 403


class Test签单拦截已填未写入:
    def _make_out(self, tmp_path):
        out = tmp_path / "out"
        d = out / "202609"
        d.mkdir(parents=True)
        (d / "红件占位").write_text("", encoding="utf-8")
        (d / "red_slots.json").write_text(json.dumps([{
            "location": "正文/p1", "old": "母版",
            "new": "据【手工：ESI发布日期】ESI最新数据显示", "new_full": None,
            "source": "sentences.py（句骨架+数字槽）",
        }], ensure_ascii=False), encoding="utf-8")
        return out, d

    def test_已填未写入被拦且不落approval(self, tmp_path, monkeypatch):
        out, d = self._make_out(tmp_path)
        (d / "manual_inputs.json").write_text(json.dumps({
            "正文/p1::ESI发布日期": {"value": "2026年9月23日", "by": "demo",
                                     "at": "2026-09-28 22:03:10"},
        }, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(config, "OUT_DIR", out)
        resp = asyncio.run(app_module.api_period_sign_json(
            _Req(config.DEMO_USER, "POST", {"known": True, "note": "试签"}), "202609"))
        assert resp.status_code == 409
        body = json.loads(resp.body)
        assert "没有写进报告" in body["error"]
        assert not (d / "approval.json").exists(), "被拦时不能落审批记录"

    def test_填值已写入时放行(self, tmp_path, monkeypatch):
        out, d = self._make_out(tmp_path)
        # 重出后的状态：槽位正文里已无【手工】，填值记录还在（applied）
        (d / "red_slots.json").write_text(json.dumps([{
            "location": "正文/p1", "old": "母版",
            "new": "据2026年9月23日ESI最新数据显示",
            "new_full": "据2026年9月23日ESI最新数据显示",
            "source": "sentences.py（句骨架+数字槽）",
        }], ensure_ascii=False), encoding="utf-8")
        (d / "manual_inputs.json").write_text(json.dumps({
            "正文/p1::ESI发布日期": {"value": "2026年9月23日", "by": "demo",
                                     "at": "2026-09-28 22:03:10"},
        }, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(config, "OUT_DIR", out)
        resp = asyncio.run(app_module.api_period_sign_json(
            _Req(config.DEMO_USER, "POST", {"known": True, "note": "试签"}), "202609"))
        assert isinstance(resp, dict), f"放行时应返回签单结果：{resp!r}"
        assert resp["status"] == "signed"
        assert (d / "approval.json").exists()
