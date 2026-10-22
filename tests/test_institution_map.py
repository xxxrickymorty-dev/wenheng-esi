# -*- coding: utf-8 -*-
"""学院/机构名归一（`config/college_map.yaml` + `src/college_stats.py`）回归。

钉的是 2026-10-22 这次改造（把「代码里写死一张小别名表」升级成可审的映射表）：

  ① 映射表是数据文件，每条映射都带 确认人/时间/依据，代码里只留兜底；
  ② 映射表的 `parser_version` 与代码的 `_PARSER_VERSION` 必须相等 —— 不等就**报错**，
     不许静默用旧缓存（2026-09-24 踩过：加了别名没动版本，报告里天文所仍是两行）；
  ③ 未归一/可疑写法产出 `out/<期次>/institution_review.md`；签认后该条从「待签认」消失；
  ④ 现产那一期按映射表重建后与 `college_stats.json` 逐字段一致
     （改了表不重建 → 这条会红，提示该期报告已与口径脱节）；
  ⑤ AI 建议默认关：关掉时全流程不产出建议文件、也不依赖它。

只用 tmp 合成件与**只读**的真产物，不碰任何原始数据。
"""
from __future__ import annotations

import json
import pathlib
import sys

import openpyxl
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import college_stats as cs                                          # noqa: E402
from _guard_registry import skip_unless                             # noqa: E402

HDR = ["序号", "WOS收录号", "被引频次", "ESI学科", "出版年", "云大作者", "热点论文"]
MAP = REPO / "config" / "college_map.yaml"


def _xlsx(path: pathlib.Path, rows: list[list], header=None) -> pathlib.Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header or HDR))
    for r in rows:
        ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _make_list(tmp_path, rows=None, name="202609论文清单.xlsx") -> pathlib.Path:
    rows = rows if rows is not None else [
        [1, "W1", 617, "Physics", 2025, "Zhu, Lei//天文研究所", ""],
        [2, "W2", 8, "Physics", 2025, "Li, Wei//中国（西南）天文研究所", ""],
        [3, "W3", 10, "Chemistry", 2025, "Wang//化学科学与工程学院", ""],
    ]
    return _xlsx(pathlib.Path(tmp_path) / name, rows)


def _tmp_map(tmp_path, body: dict, name="map.yaml") -> pathlib.Path:
    p = pathlib.Path(tmp_path) / name
    p.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def _base_map() -> dict:
    return {"parser_version": cs._PARSER_VERSION, "updated": "2026-10-22",
            "default_by": "测试（占位）", "default_at": "2026-10-22",
            "colleges": [{"college": "化学科学与工程学院", "basis": "占位", "aliases": []},
                         {"college": "中国（西南）天文研究所", "basis": "占位", "aliases": []}]}


# ──────────────────────────────────────────────── ① 映射表本身
def test_映射表每条都有确认人时间依据():
    m = cs.load_map(MAP)
    assert m["source"] == "file" and m["version"] == cs._PARSER_VERSION
    assert m["canonical"], "映射表没有规范名"
    assert len(m["canonical"]) == len(set(m["canonical"])), "规范名有重复"
    for r in m["rows"]:
        assert r["by"] and r["at"] and r["basis"], f"{r['college']} 缺 确认人/时间/依据"
        for a in r["aliases"]:
            assert a["by"] and a["at"] and a["basis"], f"别名 {a['form']} 缺 确认人/时间/依据"


def test_映射表里不留本机绝对路径():
    text = MAP.read_text(encoding="utf-8")
    assert "C:\\" not in text and "C:/" not in text, "映射表里不许写本机绝对路径（换台机器不成立）"


def test_兜底别名表与映射表一致():
    """代码里的兜底（UNIT_ALIAS）与映射表不许各说各话。"""
    m = cs.load_map(MAP)
    for form, target in cs.UNIT_ALIAS.items():
        assert m["aliases"].get(form) == target, f"兜底与映射表不一致：{form}"


def test_表缺席时退回兜底():
    m = cs.load_map(pathlib.Path("no") / "such" / "map.yaml")
    assert m["source"] == "builtin"
    assert cs.normalize_unit("天文研究所", m) == "中国（西南）天文研究所"


def test_版本不一致就报错不静默(tmp_path):
    body = _base_map()
    body["parser_version"] = 99
    with pytest.raises(ValueError, match="parser_version"):
        cs.load_map(_tmp_map(tmp_path, body))


def test_别名缺依据不许进表(tmp_path):
    body = _base_map()
    body["colleges"][0]["aliases"] = [{"form": "化学学院"}]        # 没有 by/at/basis
    with pytest.raises(ValueError, match="缺 by/basis"):
        cs.load_map(_tmp_map(tmp_path, body))


def test_同一写法映射到两处就报错(tmp_path):
    body = _base_map()
    body["colleges"][1]["aliases"] = [{"form": "化学学院", "basis": "占位"}]
    body["colleges"][0]["aliases"] = [{"form": "化学学院", "basis": "占位"}]
    with pytest.raises(ValueError, match="冲突"):
        cs.load_map(_tmp_map(tmp_path, body))


# ──────────────────────────────────────────────── ② 解析与归一口径
def test_同一机构两种写法合并成一行(tmp_path):
    st = cs.parse(_make_list(tmp_path))
    units = {u["unit"]: (u["papers"], u["cites"]) for u in st["units"]}
    assert units["中国（西南）天文研究所"] == (2, 625), "别名没合并"
    assert "天文研究所" not in units
    assert st["n_papers"] == 3 and st["n_cites"] == 635


def test_末段取不出来的行走旧口径(tmp_path):
    """末段为空的行走旧口径：照样计进 n_papers（与改造前逐字一致），只是不进 units。"""
    p = _make_list(tmp_path, [[1, "W1", 7, "Physics", 2025, "//", ""]])
    st = cs.parse(p)
    assert st["units"] == [] and st["n_papers"] == 1 and st["n_cites"] == 7
    assert st["no_unit"] == ["//"]


def test_没有斜杠的单元格整格当写法():
    """清单里偶尔会把作者名直接写在「云大作者」列 —— 取段规则不猜，原样当写法，
    它会出现在签认清单的「待签认」里由人处理。"""
    assert cs.unit_of("Zhu, Lei") == "Zhu,Lei"


def test_取末段单双斜杠混用都认():
    assert cs.unit_of("Zhu, Lei//生命科学学院") == "生命科学学院"
    assert cs.unit_of("Chen, Wen/通讯作者/地球科学学院") == "地球科学学院"
    assert cs.unit_of("Wang/第一作者、通讯作者/材料与能源学院") == "材料与能源学院"
    assert cs.unit_of("") == ""


# ──────────────────────────────────────────────── ③ 可疑规则（可解释，不用模型猜）
@pytest.mark.parametrize("a, b, rule", [
    ("软件学院（人工智能学院）", "软件学院", "R1"),
    ("云南马来亚学院（现代工学院）", "现代工学院", "R2"),
    ("中国（西南）天文研究所", "中国(西南)天文研究所", "R3"),
    ("地球科学学院", "地球科学院", "R4"),
    ("生态与环境学院", "生态与环", "R5"),
    ("中国（西南）天文研究所", "天文研究所", "R5"),
])
def test_可疑规则逐条命中(a, b, rule):
    assert cs._rule_of(a, b) == rule
    assert cs._rule_of(b, a) == rule, "方向换了也要认出来"


@pytest.mark.parametrize("a, b", [
    ("医学院", "药学院"),
    ("生命科学学院", "生态与环境学院"),
    ("材料与能源学院", "物理与天文学院"),
    ("", "医学院"),
])
def test_不相干的写法不误报(a, b):
    assert cs._rule_of(a, b) is None


def test_两条规范名之间不提示合并():
    """「云南大学」与「云南大学附属医院」出版件是两行 —— 都在表里就不该互相提示。"""
    m = cs.load_map(MAP)
    papers = {"云南大学": 1, "云南大学附属医院": 3, "天文研究所": 5,
              "中国（西南）天文研究所": 1}
    got = [(s["a"], s["b"]) for s in cs.suspects(papers, m)]
    assert ("云南大学", "云南大学附属医院") not in got
    assert got == [("中国（西南）天文研究所", "天文研究所")], got
    assert cs.suspects(papers, m)[0]["signed"] is True


# ──────────────────────────────────────────────── ④ 签认闭环 + 产物
def _state_from(rows, tmp_path):
    return cs.parse(_make_list(tmp_path, rows))


def test_未归一的写法进待签认清单(tmp_path):
    rows = [[1, "W1", 5, "Physics", 2025, "Zhu//某个没见过的学院", ""]]
    st = _state_from(rows, tmp_path)
    rev = cs.review_of(st, period="202609")
    unmapped = [i for i in rev["items"] if i["status"] == "unmapped"]
    assert [i["form"] for i in unmapped] == ["某个没见过的学院"]
    assert unmapped[0]["papers"] == 1 and unmapped[0]["cites"] == 5
    assert unmapped[0]["sample"] == "Zhu//某个没见过的学院"
    assert "某个没见过的学院" in cs.render_review_md(rev)


def test_签认后该条从待签认消失(tmp_path):
    """签认闭环：加一条别名 → 重建 → 两行并一行、待签认清零。"""
    rows = [[1, "W1", 617, "Physics", 2025, "Zhu, Lei//天文研究所", ""],
            [2, "W2", 8, "Physics", 2025, "Li, Wei//中国（西南）天文研究所", ""]]
    body = _base_map()
    body["colleges"] = [{"college": "中国（西南）天文研究所", "basis": "占位", "aliases": []}]
    before = _tmp_map(tmp_path, body, "before.yaml")
    st = cs.parse(_make_list(tmp_path, rows), map_path=before)
    rev = cs.review_of(st, period="202609", map_path=before)
    assert st["n_units"] == 2
    assert {i["form"] for i in rev["items"] if i["status"] == "unmapped"} == {"天文研究所"}

    body["colleges"][0]["aliases"] = [{"form": "天文研究所", "by": "测试签认人",
                                       "at": "2026-10-22", "basis": "两行同机构"}]
    after = _tmp_map(tmp_path, body, "after.yaml")
    st2 = cs.parse(_make_list(tmp_path, rows), map_path=after)
    rev2 = cs.review_of(st2, period="202609", map_path=after)
    units = {u["unit"]: (u["papers"], u["cites"]) for u in st2["units"]}
    assert st2["n_units"] == 1 and units["中国（西南）天文研究所"] == (2, 625)
    assert not [i for i in rev2["items"] if i["status"] == "unmapped"]
    assert [h["form"] for h in rev2["hits"]] == ["天文研究所"]


def test_签认清单确定性(tmp_path):
    st = _state_from([[1, "W1", 5, "Physics", 2025, "Zhu//天文研究所", ""]], tmp_path)
    d1, d2 = tmp_path / "a", tmp_path / "b"
    cs.write_review(d1, st, period="202609")
    cs.write_review(d2, st, period="202609")
    for name in (cs.REVIEW_MD, cs.REVIEW_JSON):
        assert (d1 / name).read_bytes() == (d2 / name).read_bytes(), f"{name} 不确定"


def test_签认清单与现产不一致时会喊(tmp_path):
    """缓存来自旧口径（映射表改了、现产没重建）→ 清单顶部要出现警示，不许装作没事。"""
    rows = [[1, "W1", 5, "Physics", 2025, "Zhu//天文研究所", ""]]
    no_alias = _tmp_map(tmp_path, _base_map(), "no_alias.yaml")   # 表里没有天文研究所那条
    st = cs.parse(_make_list(tmp_path, rows))                     # 现产：用真表（已合并）
    assert st["units"] == [{"unit": "中国（西南）天文研究所", "papers": 1, "cites": 5}]
    rev = cs.review_of(st, period="202609", map_path=no_alias)
    assert rev["consistent"] is False
    assert "缓存与映射表不一致" in cs.render_review_md(rev)


def test_load落盘时顺带刷新签认清单(tmp_path, monkeypatch):
    p = _make_list(tmp_path)
    d = pathlib.Path(tmp_path) / "202609"
    monkeypatch.setattr(cs, "find_list", lambda *a, **k: p)
    st = cs.load(d, "202609", save=True)
    assert st and (d / "college_stats.json").is_file()
    assert (d / cs.REVIEW_MD).is_file() and (d / cs.REVIEW_JSON).is_file()
    assert not (d / cs.SUGGEST_MD).exists(), "建议默认关，不许自己冒出来"


def test_建议默认关_开关打开才产出且不改数字(tmp_path):
    p = _make_list(tmp_path)
    d = pathlib.Path(tmp_path) / "202609"
    assert cs.SUGGESTIONS_ENABLED is False, "建议必须默认关"
    st = cs.parse(p)
    rev = cs.review_of(st, period="202609")
    before = json.dumps(st, ensure_ascii=False)
    cs.write_suggestions(d, rev)
    assert (d / cs.SUGGEST_MD).is_file()
    assert json.dumps(st, ensure_ascii=False) == before, "建议不许改动数据"
    text = (d / cs.SUGGEST_MD).read_text(encoding="utf-8")
    assert "不进数据路径" in text and "签认" in text


def test_命令行_check_对得上退0对不上退1(tmp_path, capsys):
    p = _make_list(tmp_path)
    d = pathlib.Path(tmp_path) / "202609"
    d.mkdir()
    (d / "college_stats.json").write_text(
        json.dumps(cs.parse(p), ensure_ascii=False, indent=1), encoding="utf-8")
    assert cs.main([str(d), "--check", str(p)]) == 0
    assert "0 差异" in capsys.readouterr().out

    bad = json.loads((d / "college_stats.json").read_text(encoding="utf-8"))
    bad["n_papers"] = 999
    (d / "college_stats.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert cs.main([str(d), "--check", str(p)]) == 1
    assert "n_papers" in capsys.readouterr().out


# ──────────────────────────────────────────────── ⑤ 与现产逐字段一致（数据驱动）
def test_现产那期按映射表重建后逐字段一致():
    """把现产 `college_stats.json` 里的清单行重建成 xlsx 再解析 → 逐字段一致。

    判据是「报告数字对」：改了 `config/college_map.yaml` 却没重建该期，这条会红。
    """
    j = REPO / "out" / "202609" / "college_stats.json"
    if not j.is_file():
        skip_unless("out/202609 无现产 college_stats.json（产物不入库，属正常）",
                    lambda: j.is_file())
    now = json.loads(j.read_text(encoding="utf-8"))
    import tempfile                                                # noqa: PLC0415

    with tempfile.TemporaryDirectory() as td:
        p = _xlsx(pathlib.Path(td) / "202609论文清单.xlsx", now["rows"], header=now["header"])
        again = cs.parse(p)
    a = {k: v for k, v in now.items() if k != "source"}
    b = {k: v for k, v in again.items() if k != "source"}
    diff = [k for k in sorted(a) if a[k] != b[k]]
    assert not diff, (
        f"现产与按映射表重建的结果对不上，差异字段 {diff} —— "
        f"改了 config/college_map.yaml 就要重建该期（或把演练用的表放 tmp/）")
