# -*- coding: utf-8 -*-
"""报告措辞档位表：校验 / 取档 / 与今天逐字一致 / 改档位只换词不换数字。

来源：`../调研与论证/discca-试用-20261022/…对文衡的启发-20261022.md` §四.1 ——
DISCCA 把「排名百分比 → 评价用词」「变动幅度 → 评价用词」做成可配置档位表，
我们这一层原本硬编码在 `src/sentences.py` 里，现搬到 `src/wording_tiers.yaml`。

本文件守卫四件事：
  1. **表本身合法**：区间连续、无缺口不重叠、有兜底档、边界方向对、字段齐；
  2. **坏表响亮报错**：指出是哪张表的哪一档 —— 不许静默回退到硬编码用词；
  3. **默认表 = 今天的措辞**：与现产报告 docx 逐字比对（数据驱动的用例按登记簿跳过）；
  4. **改档位只换词、不换数字**：边界一改，句子跟着变，数字一字不动。

数据驱动的用例依赖 `out/<期次>/`（按 `.gitignore` 不入库），缺数据走
`tests/_guard_registry.skip_unless`（登记理由 + 复核探针）。
"""
import copy
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest                                                   # noqa: E402
import yaml                                                     # noqa: E402

import sentences                                                # noqa: E402
from _guard_registry import skip_unless                         # noqa: E402

TIERS = sentences.load_tiers()
#: 句子里所有数字（含小数）：改档位不许动它们。
NUM_RE = re.compile(r"\d+(?:\.\d+)?")

PERIODS = ("202601", "202603", "202605", "202607", "202609")


def _load_raw():
    return yaml.safe_load(sentences.TIERS_PATH.read_text(encoding="utf-8"))


def _by_id(doc, tid):
    return next(t for t in doc["tables"] if t["id"] == tid)


def _bad_table(mutate):
    """默认表深拷贝 → 按 `mutate` 弄坏 → 交给校验（不落盘、不污染缓存）。"""
    doc = copy.deepcopy(_load_raw())
    mutate(doc)
    return doc


def _period_dir(repo, period):
    return repo / "out" / period


def _need_facts(repo, period):
    d = _period_dir(repo, period)
    probe = lambda: (d / "overview_facts.json").exists()        # noqa: E731
    if not probe():
        skip_unless(f"out/{period} 无 overview_facts.json（产物不入库，属正常）", probe)
    return d


def _edit_demo_table(tmp_path, *pairs):
    """按字面替换生成一份改过的档位表（与评审现场手工改配置同一条路）。"""
    text = sentences.TIERS_PATH.read_text(encoding="utf-8")
    for old, new in pairs:
        assert old in text, f"档位表里找不到要改的这一行：{old}"
        text = text.replace(old, new)
    p = tmp_path / "wording_tiers_demo.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class Test档位表校验:
    def test_默认表通过校验且五张表齐(self):
        assert TIERS["version"] == 1
        assert [t["id"] for t in TIERS["tables"]] == [
            "prox_level", "prox_verdict", "prox_strength", "rank_shift", "prox_shape"]

    def test_水平档有缺口_报错并指出哪一档(self):
        def mutate(doc):
            _by_id(doc, "prox_level")["bands"][0]["hi"] = 15.0   # 20 → 15，与下一档之间空出 [15, 20)
        with pytest.raises(sentences.TierError, match=r"prox_level.*缺口.*\[15, 20\)"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_水平档重叠_报错并指出哪一档(self):
        def mutate(doc):
            _by_id(doc, "prox_level")["bands"][0]["hi"] = 30.0   # 20 → 30，与下一档重叠 [20, 30)
        with pytest.raises(sentences.TierError, match=r"prox_level.*重叠"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_边界反了_报错并指出哪一档(self):
        def mutate(doc):
            _by_id(doc, "prox_level")["bands"][2]["hi"] = 30.0   # lo=40 ≥ hi=30
        with pytest.raises(sentences.TierError, match=r"prox_level.*第 3 档.*边界反了"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_缺用词字段_报错并指出哪一档(self):
        def mutate(doc):
            del _by_id(doc, "prox_verdict")["bands"]["up"][1]["word"]
        with pytest.raises(sentences.TierError, match=r"prox_verdict.*第 2 档.*word"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_用词写成空串_报错(self):
        def mutate(doc):
            _by_id(doc, "rank_shift")["bands"]["flat"][0]["word"] = "   "
        with pytest.raises(sentences.TierError, match=r"rank_shift.*word"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_缺方向档_报错(self):
        def mutate(doc):
            del _by_id(doc, "prox_strength")["bands"]["flat"]
        with pytest.raises(sentences.TierError, match=r"prox_strength.*缺方向档.*flat"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_方向档缺幅度档_报错(self):
        def mutate(doc):
            _by_id(doc, "rank_shift")["bands"]["down"] = []
        with pytest.raises(sentences.TierError, match=r"rank_shift.*down 方向缺幅度档"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_末档不兜底_报错(self):
        def mutate(doc):
            _by_id(doc, "prox_level")["bands"][-1]["hi"] = 100.0
        with pytest.raises(sentences.TierError, match=r"prox_level.*末档.*兜底档"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_首档不兜底_报错(self):
        def mutate(doc):
            _by_id(doc, "prox_level")["bands"][0]["lo"] = 0.0
        with pytest.raises(sentences.TierError, match=r"prox_level.*首档.*兜底档"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_幅度档覆盖不到0_报错(self):
        def mutate(doc):
            _by_id(doc, "prox_verdict")["bands"]["up"][0]["lo"] = 1.0
        with pytest.raises(sentences.TierError, match=r"prox_verdict.*覆盖不到 0"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_未知kind_报错(self):
        def mutate(doc):
            _by_id(doc, "prox_level")["kind"] = "level2"
        with pytest.raises(sentences.TierError, match=r"prox_level.*kind 非法"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_形态档缺一种_报错(self):
        def mutate(doc):
            _by_id(doc, "prox_shape")["bands"] = [
                b for b in _by_id(doc, "prox_shape")["bands"] if b["match"] != "other"]
        with pytest.raises(sentences.TierError, match=r"prox_shape.*缺形态档.*other"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_表缺unit_报错(self):
        def mutate(doc):
            del _by_id(doc, "prox_strength")["unit"]
        with pytest.raises(sentences.TierError, match=r"prox_strength.*unit"):
            sentences.validate_tiers(_bad_table(mutate))

    def test_缺表文件_报错不静默回退(self, tmp_path):
        with pytest.raises(sentences.TierError, match="读不到报告措辞档位表"):
            sentences.load_tiers(tmp_path / "没有这张表.yaml")

    def test_表不是合法YAML_报错(self, tmp_path):
        p = tmp_path / "broken.yaml"
        p.write_text("tables: [\n  {id: x,", encoding="utf-8")
        with pytest.raises(sentences.TierError, match="不是合法 YAML"):
            sentences.load_tiers(p)

    def test_删掉一张表_取档时报错(self):
        with pytest.raises(sentences.TierError, match=r"没有 `prox_level_不存在` 这张表"):
            sentences.tier_word(TIERS, "prox_level_不存在", 50.0)


class Test取档:
    def test_区间左闭右开(self):
        """边界值归**上一档**的右端不给、下一档的左端收下 —— 不重不漏。"""
        assert sentences.tier_word(TIERS, "prox_level", 39.99) == "较低"
        assert sentences.tier_word(TIERS, "prox_level", 40.0) == "较高"
        assert sentences.tier_word(TIERS, "prox_level", 59.99) == "较高"
        assert sentences.tier_word(TIERS, "prox_level", 60.0) == "很高"
        assert sentences.tier_word(TIERS, "prox_level", -5.0) == "很低"

    def test_变动档按方向与幅度(self):
        assert sentences.tier_word(TIERS, "prox_verdict", 1.9) == "变化不大"
        assert sentences.tier_word(TIERS, "prox_verdict", 2.0) == "表现平稳"
        assert sentences.tier_word(TIERS, "prox_verdict", 8.0) == "表现较好"
        assert sentences.tier_word(TIERS, "prox_verdict", 0.0) == "变化不大"
        assert sentences.tier_word(TIERS, "prox_verdict", -9.0) == "降幅明显"

    def test_位次变动词走表(self):
        assert sentences.updown_phrase(22) == "上升22位"
        assert sentences.updown_phrase(-2) == "下降2位"
        assert sentences.updown_phrase(0) == "位次不变"

    def test_尾迹形态与力度走表(self):
        # 连涨 / 波动上升 + 净变化约 5–6 百分点 → 上升方向 [2, 8) 档
        assert sentences._prox_phrases([0.7, 0.72, 0.75]) == ("一直呈稳步上升趋势", "稳步增强")
        assert sentences._prox_phrases([0.7, 0.69, 0.75]) == ("呈波动上升趋势", "稳步增强")
        # 净变化为负且期间有回落 → 下降方向 <2 档
        assert sentences._prox_phrases([0.7, 0.69, 0.68]) == ("呈波动趋势", "需要继续加强")
        assert sentences._prox_phrases([]) == (None, None)

    def test_尾迹比例换算成百分点再进表(self):
        """`prox_tail` 存的是 0–1 比例：16.15 百分点必须落 ≥8 档（不是 0.16 的 <2 档）。"""
        tail = [0.6506, 0.6411, 0.6696, 0.6972, 0.7036, 0.7513, 0.8121]
        assert sentences._prox_phrases(tail)[1] == "持续增强"

    def test_默认表命中档就是今天在用的词(self):
        assert sentences.tier_word(TIERS, "prox_level", 56.74) == "较高"
        assert sentences.tier_word(TIERS, "prox_verdict", 48.39) == "表现较好"
        assert sentences.tier_word(TIERS, "prox_strength", 16.15) == "持续增强"
        assert sentences.tier_word(TIERS, "prox_strength", -1.07) == "需要继续加强"
        assert sentences.tier_word(TIERS, "prox_shape", 0.0, direction="monotone_up") \
            == "一直呈稳步上升趋势"


class Test与今天逐字一致:
    """默认档位表 = 今天的措辞：与**现产报告 docx** 的对应段落逐字比对。"""

    @pytest.mark.parametrize("period", PERIODS)
    def test_与现产报告逐字一致(self, repo, period):
        d = _period_dir(repo, period)
        probe = lambda: bool(list(d.glob("报告初稿*.docx")))    # noqa: E731
        if not probe():
            skip_unless(f"out/{period} 无报告初稿 docx（产物不入库，属正常）", probe)
        lines, bad = sentences.regress(period, str(repo / "out"))
        diffs = {ln.split("：")[0].strip("  ❌") for ln in lines if ln.startswith("  ❌")}
        # 202607 的那份 docx 生成时还没有 college_stats.json（报告写「覆盖19个学科」），
        # 故 p4 / top_section 的差异是**改动前就有的**，与措辞档位无关。
        allow = {"p4", "top_section"} if period == "202607" else set()
        if period == "202605":
            # 202605 于 2026-10-28 按 R2-1 修复后的代码重出（旧稿备份在
            # `归档/202605-重出前-20261028/`），S0「增加-11篇」已消失。
            # 但重出后 p4 / top_section 仍与 `build_period` 骨架差一处：
            # 骨架留 `【手工：学科数】`，而成品由 college_stats 填成「19 个学科来自 23 个学院」。
            # 这不是缺陷漂移，是「骨架 vs 装配」的固有差；下面四条断言把它钉死：
            # 两边都必须已修正 R2-1，且差异只允许是这一处占位符替换。
            allow = {"p4", "top_section"}
            docx = sorted((repo / "out" / period).glob("报告初稿*.docx"))[-1]
            from docx import Document                                # noqa: PLC0415
            body = "\n".join(p.text for p in Document(str(docx)).paragraphs)
            skel = sentences.build_period(repo / "out" / period)["p4"]
            assert "较上期总数减少11篇" in body, "成品没修好 R2-1，豁免站不住脚"
            assert "较上期总数增加-11篇" not in body, "成品仍有 S0 缺陷，豁免站不住脚"
            assert "分别有19个学科来自23个学院" in body, "成品缺 college_stats 装配"
            assert "【手工：学科数】" in skel, "骨架没有占位符，差异就不止这一处"
        assert bad == len(diffs) and diffs <= allow, "\n".join(lines)

    def test_五期用词都是表里的词(self, repo):
        """出句里的评价用词必须能在表里找到 —— 防「改了表却没走表」的漏网硬编码。"""
        for period in PERIODS:
            d = _need_facts(repo, period)
            texts = sentences.build_period(d)
            words = set()
            for t in TIERS["tables"]:
                if t["kind"] == "shape":
                    words |= {b["word"] for b in t["bands"]}
                elif t["kind"] == "level":
                    words |= {b["word"] for b in t["bands"]}
                else:
                    words |= {b["word"] for v in t["bands"].values() for b in v}
            for key in ("p2", "p3", "situation", "trend", "forecast_p1", "forecast_p2"):
                assert any(w in texts[key] for w in words), f"{period}/{key} 没有任何档位用词"


class Test改档位只换词不换数字:
    """评审现场那一下：改边界 → 句子按新档位变、数字一字不动。"""

    def test_水平档边界60改50_p2换词数字不动(self, repo, tmp_path):
        d = _need_facts(repo, "202609")
        demo = _edit_demo_table(
            tmp_path,
            ('- {lo: 40.0, hi: 60.0, word: "较高"}', '- {lo: 40.0, hi: 50.0, word: "较高"}'),
            ('- {lo: 60.0, hi: 80.0, word: "很高"}', '- {lo: 50.0, hi: 80.0, word: "很高"}'))
        base = sentences.build_period(d)
        moved = sentences.build_period(d, demo)
        assert "接近度较高的学科" in base["p2"]
        assert "接近度很高的学科" in moved["p2"], moved["p2"]
        assert base["p2"] != moved["p2"]
        for key in base:
            assert NUM_RE.findall(base[key]) == NUM_RE.findall(moved[key]), \
                f"{key} 的数字被改档位带跑了"

    def test_变动幅度边界8改6_命中档变(self, tmp_path):
        """8 边界改到 6：7 个百分点从「表现平稳」挪进「表现较好」（数字仍是 7）。"""
        demo = _edit_demo_table(
            tmp_path,
            ('- {lo: 2.0, hi: 8.0, word: "表现平稳"}', '- {lo: 2.0, hi: 6.0, word: "表现平稳"}'),
            ('- {lo: 8.0, hi: null, word: "表现较好"}', '- {lo: 6.0, hi: null, word: "表现较好"}'))
        assert sentences.tier_word(TIERS, "prox_verdict", 7.0) == "表现平稳"
        assert sentences.tier_word(sentences.load_tiers(demo), "prox_verdict", 7.0) == "表现较好"

    def test_改词即可改句子(self, repo, tmp_path):
        """连边界都不用动：把 ≥8 档的词换成「显著增强」，预测章那句话就变了。"""
        d = _need_facts(repo, "202609")
        demo = _edit_demo_table(
            tmp_path, ('- {lo: 8.0, hi: null, word: "持续增强"}',
                       '- {lo: 8.0, hi: null, word: "显著增强"}'))
        base = sentences.build_period(d)
        moved = sentences.build_period(d, demo)
        assert "发展力度持续增强" in base["forecast_p2"]
        assert "发展力度显著增强" in moved["forecast_p2"]
        assert NUM_RE.findall(base["forecast_p2"]) == NUM_RE.findall(moved["forecast_p2"])

    def test_坏表出句直接报错不静默回退(self, repo, tmp_path):
        """边界反了的表 → build 当场抛错（绝不悄悄用回硬编码用词）。"""
        d = _need_facts(repo, "202609")
        demo = _edit_demo_table(
            tmp_path,
            ('- {lo: 40.0, hi: 60.0, word: "较高"}', '- {lo: 40.0, hi: 30.0, word: "较高"}'))
        with pytest.raises(sentences.TierError, match=r"prox_level.*第 3 档.*边界反了"):
            sentences.build_period(d, demo)
