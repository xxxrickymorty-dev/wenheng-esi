# -*- coding: utf-8 -*-
"""他校简报（`flexible/brief.py`）的验收用例。

两层：
- **纯函数**：`_delta` / `_short_period` / `_flat_run` / `_matrix_lines` / `render`
  用合成 panel 喂，不碰数据、不碰磁盘；
- **落盘**：真实 202609 三校跑一次 `generate()`，锁 md 里的数字、图真的落盘且被引用、
  `flex_meta.json` 的自检结论，以及「现有 `list_reports` 能列出这份稿」。
"""
from __future__ import annotations

import json

import pytest

from _guard_registry import skip_unless

from flexible import brief, peers, report

PERIODS = ["202511", "202601", "202603", "202605", "202607", "202609"]

SECTIONS = ("## 一、各期上榜学科数", "## 二、各期趋势", "## 三、学科覆盖矩阵",
            "## 四、逐校画像", "## 五、共同与差异", "## 六、值得标注的变化",
            "## 七、口径与来源")


def _esi_ready() -> bool:
    root = peers.ESI_ROOT
    return ((root / "202511" / "Clinical Medicine.xlsx").is_file()
            and (root / "202609" / "Clinical Medicine.xlsx").is_file())


def _fake_panel(**over) -> dict:
    """最小 panel 结构：够 render 用，不含真实数据。"""
    p = {
        "periods": ["202511", "202609"],
        "period_end": "202609",
        "missing": [],
        "disciplines": ["Chemistry", "Engineering"],
        "n_periods": 2,
        "schools": [
            {"query": "昆明理工大学", "cn": "昆明理工大学", "en": "K",
             "status": "ok", "match": "map", "counts": [1, 2],
             "entered": [], "exited": [], "note": ""},
            {"query": "海南大学", "cn": "海南大学", "en": "H",
             "status": "ok", "match": "map", "counts": [2, 2],
             "entered": [], "exited": [], "note": ""},
        ],
        "common": ["Chemistry"],
        "only": {"昆明理工大学": ["Engineering"], "海南大学": []},
        "events": [],
        "grid": {"counts": {}, "sets": {"昆明理工大学": {"202511": ["Chemistry"],
                                                        "202609": ["Chemistry", "Engineering"]},
                                        "海南大学": {"202511": ["Chemistry", "Engineering"],
                                                     "202609": ["Chemistry", "Engineering"]}}},
        "source": {"dataset": "数据与复现/ESI数据/202609", "period": "202609",
                   "generated_at": "2026-10-30T00:00:00"},
    }
    p.update(over)
    return p


def _matrix_panel(**over) -> dict:
    """三校 × 4 学科：共同 / 仅甲 / 仅丙 / 末期全无，四层各一条（假校名，不掺真实数）。"""
    p = _fake_panel(
        disciplines=["Chemistry", "Engineering", "Mathematics", "Physics"],
        schools=[
            {"query": "甲校", "cn": "甲校", "en": "A", "status": "ok", "match": "map",
             "counts": [1, 2], "entered": [], "exited": [], "note": ""},
            {"query": "乙校", "cn": "乙校", "en": "B", "status": "ok", "match": "map",
             "counts": [1, 1], "entered": [], "exited": [], "note": ""},
            {"query": "丙校", "cn": "丙校", "en": "C", "status": "ok", "match": "map",
             "counts": [1, 2], "entered": [], "exited": [], "note": ""},
        ],
        common=["Chemistry"],
        only={"甲校": ["Engineering"], "乙校": [], "丙校": ["Mathematics"]},
        grid={"counts": {}, "sets": {
            "甲校": {"202511": ["Chemistry"], "202609": ["Chemistry", "Engineering"]},
            "乙校": {"202511": ["Chemistry"], "202609": ["Chemistry"]},
            "丙校": {"202511": ["Chemistry"], "202609": ["Chemistry", "Mathematics"]}}},
    )
    p.update(over)
    return p


# ------------------------------------------------------------------ 纯函数


def test_首末变化_缺数据不给差值():
    assert brief._delta([1, 3]) == "+2"
    assert brief._delta([3, 1]) == "-2"
    assert brief._delta([2, 2]) == "持平"
    # 任一期为 None＝该期无数据，不能拿缺数据凑一个差值出来
    assert brief._delta([2, None]) == "—"
    assert brief._delta([]) == "—"


def test_期次表头写法():
    assert brief._short_period("202511") == "2025-11"
    assert brief._short_period("202609") == "2026-09"


def test_最长持平_只数相邻相等且取靠后那段():
    ps = PERIODS
    assert brief._flat_run([12] * 6, ps) == (6, "202511")
    assert brief._flat_run([9, 10, 11, 11, 11, 12], ps) == (3, "202603")
    assert brief._flat_run([13, 13, 14, 14, 14, 14], ps) == (4, "202603")
    # 缺数据把序列切断：「两期都没数」不是「两期一样」
    assert brief._flat_run([5, None, 5, 5], ps[:4]) == (2, "202603")
    assert brief._flat_run([None, None], ps[:2]) == (0, None)


def test_渲染_七节齐全且数字来自panel():
    md = brief.render(_fake_panel(), generated_at="2026-10-30T00:00:00")
    for sec in SECTIONS:
        assert sec in md, sec
    assert "| 昆明理工大学 | 1 | 2 | +1 |" in md
    assert "| 海南大学 | 2 | 2 | 持平 |" in md
    assert "共同上榜 1 个学科" in md
    assert "化学" in md                      # 学科中文名，不是 stem
    assert "数据与复现/ESI数据/202609" in md
    assert "运行期无模型参与" in md


def test_渲染_确定性():
    p = _fake_panel()
    a = brief.render(p, generated_at="2026-10-30T00:00:00")
    b = brief.render(p, generated_at="2026-10-30T00:00:00")
    assert a == b


def test_趋势图按相对路径引用_不传图则照实说():
    md = brief.render(_fake_panel(), generated_at="t",
                      charts=[{"file": "trend.png", "title": "各校各期上榜学科数"}])
    assert "![各校各期上榜学科数](charts/trend.png)" in md
    # 纯函数路径没有图：不许编一个指向空文件的链接
    bare = brief.render(_fake_panel(), generated_at="t")
    assert "](charts/" not in bare
    assert "本期未出图" in bare


def test_覆盖矩阵_共同到全无四层排序():
    md = brief.render(_matrix_panel(), generated_at="t")
    lines = md.splitlines()
    pos = {k: next(i for i, x in enumerate(lines) if x.startswith(f"| {k} |"))
           for k in ("化学", "工程学", "数学", "物理学")}
    assert pos["化学"] < pos["工程学"] < pos["数学"] < pos["物理学"]
    assert "| 化学 | ✓ | ✓ | ✓ | 共同 |" in md
    assert "| 工程学 | ✓ | — | — | 仅甲校 |" in md
    assert "| 数学 | — | — | ✓ | 仅丙校 |" in md
    assert "| 物理学 | — | — | — | 末期均未上榜 |" in md


def test_覆盖矩阵_未纳入学校记点并加脚注():
    p = _matrix_panel()
    p["schools"].append({"query": "丁校", "cn": "丁校", "en": "", "status": "absent",
                         "match": "absent", "counts": [None, None],
                         "entered": [], "exited": [], "note": "查无此校"})
    md = brief.render(p, generated_at="t")
    assert "| 化学 | ✓ | ✓ | ✓ | · | 共同 |" in md
    assert "·＝该校未纳入 ESI" in md


def test_逐校画像_四个数都来自panel():
    md = brief.render(_matrix_panel(), generated_at="t")
    assert "### 甲校" in md
    assert "- 覆盖广度：末期上榜 **2** 个学科（口径 4 个）" in md
    assert "- 首末变化：1 → 2（+1）" in md
    assert "- 最长持平：1 期" in md            # 甲校 [1,2] 没有连续相等
    assert "### 乙校" in md and "- 首末变化：1 → 1（持平）" in md
    assert "- 最长持平：2 期（2025-11 起）" in md


def test_逐校画像_新进退出按学科列出():
    p = _matrix_panel()
    p["schools"][0]["entered"] = [{"period": "202609", "disc": "Engineering", "cn": "工程学"}]
    p["schools"][1]["exited"] = [{"period": "202609", "disc": "Physics", "cn": "物理学"}]
    md = brief.render(p, generated_at="t")
    assert "- 新进 1 个：工程学（2026-09）" in md
    assert "- 退出 1 个：物理学（2026-09）" in md
    assert "- 新进：无" in md                   # 乙校没有新进


def test_名次交叉不读成自己追自己():
    """overtake 的 school 是**被追上的那方**，直接套 text 会出现「昆工追平昆工」。"""
    ev = {"kind": "overtake", "school": "昆明理工大学", "period": "202609", "index": 1,
          "value": 2, "text": "2 期追平昆明理工", "meta": {"with": "海南大学", "gap": 0}}
    md = brief.render(_fake_panel(events=[ev]), generated_at="2026-10-30T00:00:00")
    assert "被海南大学追平" in md
    assert "追平昆明理工" not in md


def test_事件为空时照实说():
    md = brief.render(_fake_panel(events=[]), generated_at="2026-10-30T00:00:00")
    assert "没有值得标注的变化" in md


def test_缺数据期次进正文():
    md = brief.render(_fake_panel(missing=["202605"]), generated_at="2026-10-30T00:00:00")
    assert "缺数据的期次" in md and "2026-05" in md


# ------------------------------------------------------------------ 落盘


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    if not _esi_ready():
        skip_unless("ESI数据 202511/202609 的学科表缺失", _esi_ready)
    out = tmp_path_factory.mktemp("brief") / "202609"
    r = brief.generate(out, ["昆明理工大学", "海南大学", "云南大学"], n=6,
                       generated_at="2026-10-30 00:00:00")
    return out, r


def test_三校简报_落盘与自检(produced):
    out, r = produced
    dest = out / "flexible" / "multi_school"
    assert (dest / "report.md").is_file()
    assert (dest / "brief.json").is_file()
    assert (dest / "flex_meta.json").is_file()
    assert r["check"]["pass"], r["check"]["problems"]

    p = r["panel"]
    assert p["periods"] == PERIODS
    counts = {s["cn"]: s["counts"] for s in p["schools"]}
    assert counts["昆明理工大学"] == [12] * 6
    assert counts["海南大学"] == [9, 10, 11, 11, 11, 12]
    assert counts["云南大学"] == [13, 13, 14, 14, 14, 14]
    assert len(p["common"]) == 10

    md = (dest / "report.md").read_text(encoding="utf-8")
    assert "| 海南大学 | 9 | 10 | 11 | 11 | 11 | 12 | +3 |" in md
    assert "共同上榜 10 个学科" in md
    assert "昆明理工大学 · 2026-09：被海南大学追平" in md


def test_趋势图真的落盘且正文引用了(produced):
    """图不是摆设：文件在、是 PNG、md 里用相对路径指过去，三处对得上。"""
    out, r = produced
    dest = out / "flexible" / "multi_school"
    png = dest / "charts" / "trend.png"
    assert png.is_file() and png.stat().st_size > 5000
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    md = (dest / "report.md").read_text(encoding="utf-8")
    assert "](charts/trend.png)" in md
    assert r["check"]["n_charts"] == 1
    assert r["charts"] and r["charts"][0].endswith("trend.png")


def test_元信息可被现有列表接口读出(produced):
    """沿用旧线的 `report.md` + `flex_meta.json` 约定，`list_reports` 应能直接列出。"""
    out, _ = produced
    items = report.list_reports(out)
    hit = [x for x in items if x["intent"] == brief.INTENT]
    assert len(hit) == 1
    m = hit[0]["meta"]
    assert m["backend"] == "rule" and m["n_charts"] == 1
    assert m["charts"] == ["trend.png"]
    assert m["check"]["pass"] is True
    assert [s["cn"] for s in m["schools"]][0] == "昆明理工大学"


def test_机读件与稿子同源(produced):
    """`brief.json` 里的数字必须和 md 表里的同一批——两处各存一份就会漂。"""
    out, _ = produced
    dest = out / "flexible" / "multi_school"
    data = json.loads((dest / "brief.json").read_text(encoding="utf-8"))
    md = (dest / "report.md").read_text(encoding="utf-8")
    for s in data["schools"]:
        row = "| " + s["cn"] + " | " + " | ".join(str(v) for v in s["counts"]) + " |"
        assert row in md, row


def test_同输入两次生成逐字节一致(tmp_path):
    """铁律 1：除 `generated_at` 外同输入逐字节一致——稿子与图都要一致。"""
    if not _esi_ready():
        skip_unless("ESI数据 202511/202609 的学科表缺失", _esi_ready)
    args = ("昆明理工大学", "海南大学", "云南大学")
    a = tmp_path / "a" / "202609"
    b = tmp_path / "b" / "202609"
    brief.generate(a, args, n=6, generated_at="2026-10-30 00:00:00")
    brief.generate(b, args, n=6, generated_at="2026-10-30 00:00:00")
    rel = "flexible/multi_school"
    assert (a / rel / "report.md").read_bytes() == (b / rel / "report.md").read_bytes()
    assert (a / rel / "charts" / "trend.png").read_bytes() == \
        (b / rel / "charts" / "trend.png").read_bytes()


def test_缺席学校照实写不静默(tmp_path):
    """缺席校要写进「未能纳入」，且 counts 是 None 而不是 0（0 会被画成贴底的假曲线）。"""
    if not _esi_ready():
        skip_unless("ESI数据 202511/202609 的学科表缺失", _esi_ready)
    out = tmp_path / "202609"
    r = brief.generate(out, ["昆明理工大学", "昆明学院"], n=2, generated_at="2026-10-30 00:00:00")
    md = (out / "flexible" / "multi_school" / "report.md").read_text(encoding="utf-8")
    assert "未能纳入的学校" in md and "昆明学院" in md
    assert r["panel"]["schools"][1]["status"] == "absent"
    assert r["panel"]["schools"][1]["counts"] == [None, None]
    # 缺席校不进图（全 None 的线画不出来，图例里却会占一个词条），矩阵里记「·」
    assert "·＝该校未纳入 ESI" in md
    assert r["check"]["pass"], r["check"]["problems"]
