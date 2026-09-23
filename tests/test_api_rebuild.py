# -*- coding: utf-8 -*-
"""POST /api/periods/{period}/rebuild 填完重出 JSON 版（契约 §2.2 #14）。

与表单版 POST /p/{period}/rebuild 同一套三步，顺序不能乱：
  ① 先存填值 -> ② 旧成品撤到 _superseded/ -> ③ fill_docx 重出
关键安全语义：**没填值时不碰产物**（在 quarantine 之前就返回）。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _block():
    src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
    return src.split("async def api_period_rebuild_json")[1].split("@app.")[0]


class Test路由与权限:
    def test_rebuild路由是POST_api(self):
        src = (REPO / "server" / "app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/periods/{period}/rebuild")' in src

    def test_rebuild用require_admin(self):
        assert "require_admin" in _block()

    def test_items参数校验(self):
        assert '"items"' in _block() and "isinstance(items, dict)" in _block()


class Test三步顺序:
    def test_先存再撤再重出(self):
        b = _block()
        i_save = b.index("save_fill")
        i_quar = b.index("quarantine_final_products")
        i_fill = b.index("fill_docx.main")
        assert i_save < i_quar < i_fill, "顺序不能乱：先存填值，再撤旧成品，最后重出"

    def test_没填值时在quarantine之前返回(self):
        b = _block()
        i_reject = b.index("还没有填写内容")
        i_quar = b.index("quarantine_final_products")
        assert i_reject < i_quar, "没填值必须不碰产物（在撤旧成品之前就返回）"

    def test_不重新解析台账(self):
        """重出用已解析宽表（fill_docx.main 只收 ledger_dir），不调 load_ledger。"""
        b = _block()
        assert "load_ledger" not in b
        assert "fill_docx.main(ledger_dir=" in b


class Test返回与错误:
    def test_返回ok与rebuilt(self):
        b = _block()
        assert '"ok": True' in b and '"rebuilt": n' in b

    def test_错误体带hint(self):
        b = _block()
        assert b.count('"hint"') >= 4, "404/400/409/500 都要给 hint"

    def test_无填值走409(self):
        b = _block()
        idx = b.index("还没有填写内容")
        assert "409" in b[idx:idx + 120]
