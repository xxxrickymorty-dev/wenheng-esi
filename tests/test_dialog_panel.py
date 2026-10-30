# -*- coding: utf-8 -*-
"""对话层 · 他校简报（阶段 2）：一句话 → `panel()` 的数字，**模型不碰数据路径**。

钉四件事（题面要求）：
  ① 一句话能解析出两校 + 期次；
  ② 回答里的每个数字与 `panel()` 返回**逐字一致**（并反向钉死「没有多出来的数字」）；
  ③ 混进一所查不到的学校（昆明学院）时，该校给中文说明、其余照常、不抛错；
  ④ 无模型（离线 / 无 key）时仍然能出结果。

另外两条口径也钉住：
  · 「对比 A 和 B 的化学接近度」是**单学科问数**，仍走 qa 老路（不被简报抢走）；
  · 期次不在数据目录时给一句中文，不把异常甩给对话。

真数据用例依赖 `数据与复现/ESI数据/202609`（不入库）；缺席按 `_guard_registry` 登记跳过。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai                                                       # noqa: E402
from ai import _dialog                                          # noqa: E402
from ai._shield import NUM                                      # noqa: E402
from _guard_registry import skip_unless                         # noqa: E402

PERIODS = ["202609", "202607", "202605", "202603", "202601", "202511"]
DEMO = "对比昆明理工大学和海南大学最新一期学科发展"
KUNMING, HAINAN, ABSENT = "昆明理工大学", "海南大学", "昆明学院"


def _esi_ready() -> bool:
    from flexible import peers
    return (peers.ESI_ROOT / "202609").is_dir()


def _need_data():
    if not _esi_ready():
        skip_unless("ESI 数据目录里没有 202609（数据不入库，属正常）", _esi_ready)


class _Bomb:
    """被调用即炸的 brain：证明这一轮没有模型参与。"""

    name = "bomb"
    is_rule = False

    def think(self, brief):                                     # noqa: ARG002
        raise AssertionError("他校简报不该问模型")


def run_dialog(text, *, root, periods=PERIODS, history=None, slot="", **ov):
    payload = {"text": text, "history": history or []}
    if periods is not None:
        payload["periods"] = periods
    with ai.using(data_root=root, brain=_Bomb(), **ov):
        return ai.run("dialog", slot, payload=payload, actor="admin")


@pytest.fixture(scope="module")
def direct():
    """直接调 `panel()`（真数据）——回答里的数字以它为准。"""
    _need_data()
    from flexible.panel import panel
    return panel([KUNMING, HAINAN, ABSENT], period_end="202609", n=6)


# ============================================================ ① 解析：两校 + 期次
class TestParse:
    def test_一句话解析出两校与最新期次(self):
        p = _dialog.parse(DEMO)
        assert p.kind == "compare"
        assert p.schools == (KUNMING, HAINAN)
        assert p.case == "latest", "「最新一期」由 payload.periods 落成期次，不猜数字"

    def test_落期次用台账有效期次(self, tmp_path):
        ans = run_dialog(DEMO, root=tmp_path)
        assert ans.data["kind"] == "compare"
        assert ans.data["period"] == "202609"
        # 窗口由 panel 的 prev_before 链回溯（升序），不是日历减法
        assert ans.data["compare"]["periods"] == sorted(PERIODS)

    def test_句子里带期次就用句子里的(self):
        p = _dialog.parse("对比昆明理工大学和海南大学 202607 那期的学科发展")
        assert p.kind == "compare" and p.period == "202607"

    def test_顿号与和混写都认得(self):
        assert _dialog.parse("各校 昆明理工大学、海南大学、昆明学院 上榜学科") .schools == (
            KUNMING, HAINAN, ABSENT)

    def test_单校不算简报(self):
        assert _dialog.parse("对比一下昆明理工大学的学科发展").kind != "compare"

    def test_指标问句不算简报_仍走问数(self):
        """「对比 A 和 B 的化学接近度」是单学科问数——不能被简报抢走。"""
        p = _dialog.parse("对比昆明理工大学和海南大学的化学接近度")
        assert p.kind == "query"

    def test_没有比较字样不算简报(self):
        assert _dialog.parse("昆明理工大学和海南大学最新一期").kind != "compare"

    @pytest.mark.parametrize("text", [
        "帮我对比一下昆明理工大学和海南大学最新一期学科发展",
        "对比一下昆明理工大学和海南大学",
        "比一比昆明理工大学和海南大学",
    ])
    def test_套话被摘干净_校名不带前缀(self, text):
        """「一下 / 比一比 / 帮我」不能粘进校名——粘了就会去查一所不存在的学校。"""
        p = _dialog.parse(text)
        assert p.kind == "compare"
        assert p.schools == (KUNMING, HAINAN)


# ============================================================ ② 数字与 panel 逐字一致
class TestNumbers:
    def test_各校六期计数逐字等于panel(self, tmp_path, direct):
        ans = run_dialog(DEMO, root=tmp_path)
        assert ans.mode == "rule" and ans.backend == "rule" and ans.notice == ""
        rows = {}
        for line in ans.text.splitlines():
            head, _, tail = line.partition("　")
            if head in {KUNMING, HAINAN}:
                rows[head] = [c.strip() for c in tail.split("·")]
        want = {s["cn"]: [str(v) for v in s["counts"]]
                for s in direct["schools"] if s["status"] == "ok"}
        assert rows == want, "表里的六期计数必须与 panel 的 counts 一格不差"

    def test_共同与差异逐字等于panel(self, tmp_path, direct):
        from discipline_list import cn_of
        ans = run_dialog(DEMO, root=tmp_path)
        assert f"共同上榜 {len(direct['common'])} 个学科" in ans.text
        for stem in direct["common"]:
            assert cn_of(stem) in ans.text
        for cn, stems in direct["only"].items():
            line = next(ln for ln in ans.text.splitlines() if ln.startswith(f"· {cn}："))
            assert line == f"· {cn}：" + "、".join(cn_of(s) for s in stems)

    def test_回答里没有panel给不出的数字(self, tmp_path, direct):
        """反证：把回答里的每个数字都拿回 panel 的返回里找，找不到就是编的。"""
        ans = run_dialog(DEMO, root=tmp_path)
        allowed: set[str] = set()
        for per in direct["periods"]:
            allowed |= {per, per[:4], per[4:6]}
        for s in direct["schools"]:
            allowed |= {str(c) for c in (s["counts"] or []) if c is not None}
            allowed |= set(NUM.findall(s["note"]))
        allowed |= {str(len(direct["common"])), str(len(direct["periods"])),
                    str(len(direct["disciplines"]))}
        for e in direct["events"]:
            allowed |= set(NUM.findall(e["text"]))
        allowed |= set(NUM.findall(direct["source"]["dataset"]))
        stray = set(NUM.findall(ans.text)) - allowed
        assert not stray, f"这些数字 panel 里没有：{sorted(stray)}"

    def test_每个数字都有来源_且来源指向panel(self, tmp_path):
        ans = run_dialog(DEMO, root=tmp_path)
        assert len(ans.sources) == len(NUM.findall(ans.text))
        assert [s.value for s in ans.sources] == NUM.findall(ans.text), "第 k 个数字 ↔ 第 k 条来源"
        assert all(s.pointer.startswith("panel/") for s in ans.sources)
        assert "panel/unknown" not in {s.pointer for s in ans.sources}, "每行都该有确定来源"
        assert all(s.kind == "fact" for s in ans.sources)

    def test_记账期次是他校那期(self, tmp_path):
        ans = run_dialog(DEMO, root=tmp_path)
        rows = [json.loads(x) for x in
                (tmp_path / "202609" / "ai_calls.jsonl").read_text("utf-8").splitlines()]
        assert rows[-1]["capability"] == "dialog" and rows[-1]["period"] == "202609"


# ============================================================ ③ 一所查不到，其余照常
class TestAbsentSchool:
    def test_该校给中文说明_其余照常_不抛错(self, tmp_path):
        ans = run_dialog("对比昆明理工大学、海南大学和昆明学院最新一期学科发展",
                         root=tmp_path)
        assert ans.mode == "rule"
        assert f"未能纳入：{ABSENT}" in ans.text
        assert "整校未在 ESI 中出现" in ans.text
        assert "没有「昆明学院」" in ans.text          # panel 的 note 原样交出去
        # 另外两所照常出数（不是整批失败）
        assert KUNMING in ans.text and HAINAN in ans.text
        assert "共同上榜" in ans.text
        status = {s["cn"]: s["status"] for s in ans.data["compare"]["schools"]}
        assert status[ABSENT] == "absent"
        assert status[KUNMING] == "ok" and status[HAINAN] == "ok"

    def test_查不到的那所不画计数行(self, tmp_path):
        ans = run_dialog("对比昆明理工大学、海南大学和昆明学院最新一期学科发展",
                         root=tmp_path)
        assert not any(ln.startswith(f"{ABSENT}　") for ln in ans.text.splitlines())

    def test_期次不在数据目录_给中文不抛(self, tmp_path):
        ans = run_dialog(DEMO, root=tmp_path, periods=["201901"])
        assert ans.mode == "rule"
        assert ans.text.startswith("这次没取到数：")
        assert "201901" in ans.text and "没有改动任何数据" in ans.text

    def test_期次在目录但没有学科表_记破折号不填零(self, tmp_path):
        """201903 只有目录没有学科表：panel 报 missing、counts 为 None——不能写成 0。"""
        ans = run_dialog(DEMO, root=tmp_path, periods=["201903"])
        assert ans.mode == "rule"
        assert "下列期次没有学科表" in ans.text
        assert f"{KUNMING}　—" in ans.text
        assert ans.data["compare"]["missing"] == ["201903"]
        assert all(s["counts"] == [None] for s in ans.data["compare"]["schools"]
                   if s["status"] == "ok")


# ============================================================ ④ 无模型也能出结果
class TestOffline:
    def test_注入炸弹brain也照常出数(self, tmp_path, direct):
        ans = run_dialog(DEMO, root=tmp_path)          # run_dialog 已注入 _Bomb
        assert ans.mode == "rule" and ans.backend == "rule"
        assert "kernel" not in (ans.data or {})         # 内核这一轮根本没起
        assert str(direct["schools"][0]["counts"][-1]) in ans.text

    def test_有上文也不问内核(self, tmp_path):
        """简报轮不走模型兜底：期次缺了按台账最近一期出，模型不碰这一轮。"""
        ans = run_dialog(DEMO, root=tmp_path,
                         history=[{"who": "me", "text": "上上期怎么样"}])
        assert ans.data["kind"] == "compare" and "kernel" not in (ans.data or {})


# ============================================================ 预热（冷启动 20 多秒）
class TestPrewarm:
    @pytest.fixture(autouse=True)
    def _reset(self):
        _dialog._WARM["started"] = False
        yield
        _dialog._WARM["started"] = False

    def test_测试里不预热(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("WENHENG_PANEL_PREWARM", "0")
        assert _dialog._warm_async() is False

    def test_起一次守护线程(self, monkeypatch):
        started = []
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("WENHENG_PANEL_PREWARM", raising=False)
        monkeypatch.setattr(_dialog, "_warm_panel_cache", lambda: started.append(1))
        assert _dialog._warm_async() is True
        assert _dialog._warm_async() is False, "进程内只预热一次"
        for t in list(__import__("threading").enumerate()):
            if t.name == "wenheng-panel-prewarm":
                t.join(5)
        assert started == [1]


# ============================================================ 接口：不被服务器转去 qa
class TestApi:
    def test_对话口原样交回简报正文(self, monkeypatch, tmp_path):
        """`kind=compare` 不在服务器那条 `kind == "query"` 分支上——不会转去调 qa。"""
        import asyncio
        import urllib.parse
        from server import app as appmod, config

        _need_data()
        monkeypatch.setattr(appmod, "require_user", lambda request: config.ADMIN_USER)
        import taskview
        monkeypatch.setattr(taskview, "known_periods", lambda: list(PERIODS))

        body = json.dumps({"text": DEMO, "history": []}).encode()
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(msg):
            sent.append(msg)

        scope = {"type": "http", "http_version": "1.1", "method": "POST",
                 "path": "/api/dialog/turn",
                 "raw_path": b"/api/dialog/turn",
                 "query_string": urllib.parse.urlencode({}).encode(),
                 "root_path": "", "scheme": "http", "server": ("testserver", 80),
                 "client": ("test", 12345),
                 "headers": [(b"host", b"testserver"),
                             (b"content-type", b"application/json"),
                             (b"content-length", str(len(body)).encode())]}
        with ai.using(data_root=tmp_path):
            asyncio.run(appmod.app(scope, receive, send))

        assert sent[0]["status"] == 200
        raw = b"".join(m.get("body", b"") for m in sent
                       if m["type"] == "http.response.body")
        resp = json.loads(raw)
        assert resp["kind"] == "compare"
        assert resp["answer"] is None, "简报不进 qa 那条路"
        assert "共同上榜" in resp["text"]
        assert re.search(r"昆明理工大学　12 · 12", resp["text"])
