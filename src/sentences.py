# -*- coding: utf-8 -*-
"""结语句句骨架：模板 + 数字槽（只填台账可算数；台账外用手工槽标记）。

输出键 → 报告段落映射：
  p1 概述·数据来源段      p2 概述·前1%与前1‰段
  p3 概述·亮点与警示段    p4 概述·顶尖论文段
  trend 学校发展趋势段    situation 学科发展态势段（22 学科升降统计）
  cover_issue 封面期数     cover_month 封面年月

**评价用词走档位表**（`wording_tiers.yaml`，2026-10-22）：本模块里所有「分档的措辞」
（接近度水平用词 / 变动幅度用词 / 尾迹形态用词）都从表里取，改表即改措辞、无需改代码。
表只决定**怎么说**，不决定**是多少** —— 数字仍只来自动态监测表（运行期 LLM 不进数据路径）。
默认表与今天逐字一致；缺表 / 坏表直接抛 `TierError`，不静默回退到硬编码。

预览 / 回归 / 校验入口（评审现场用）：
    uv run python -m src.sentences --preview
    uv run python -m src.sentences --preview --rank-pct 56.74 --change 7.5
    uv run python -m src.sentences --preview --period 202609 --tiers tmp\\改过的表.yaml
    uv run python -m src.sentences --regress 202609
    uv run python -m src.sentences --check [--tiers PATH]
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import yaml                                                     # noqa: E402

import period as period_mod                                     # noqa: E402

from parse_ledger import DISCIPLINES_CN                         # noqa: E402

MANUAL = "【手工：{}】"

#: 报告措辞档位表（评价用词）。数据文件、入库；与 `college_map.yaml` 同住 `config/`
#: （`REPO_ROOT` 的口径照 `college_stats.py`，别各写一套）。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TIERS_PATH = REPO_ROOT / "config" / "wording_tiers.yaml"


# ════════════════════════════════════════════════════════════════════════
# 措辞档位表：读 / 校验 / 取档
# ════════════════════════════════════════════════════════════════════════

class TierError(Exception):
    """档位表非法（缺字段 / 非法值 / 边界反 / 缺口 / 重叠 / 无兜底档）。

    一律**当场报错并指出是哪张表的哪一档** —— 不许静默回退到硬编码用词，
    否则「现场改了档位却没生效」会被读成「报告本来就长这样」。
    """


_LEVEL, _CHANGE, _SHAPE = "level", "change", "shape"
#: change 表的三个方向档。`flat` 只一档（净变化恰为 0，不分幅度）。
_DIRECTIONS = ("up", "flat", "down")
#: shape 表的三个形态档（判据见 `_prox_shape_key`）。
_SHAPE_KEYS = ("monotone_up", "volatile_up", "other")

_TIERS_CACHE: dict = {}


def _band_label(band, i):
    """档位的人读标签：`第 2 档 [20, 40)`。报错与预览都用它。"""
    lo, hi = band.get("lo"), band.get("hi")
    left = "-∞" if lo is None else f"{lo:g}"
    right = "+∞" if hi is None else f"{hi:g}"
    return f"第 {i} 档 [{left}, {right})"


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_band(tid, where, band, i, *, need_word=True):
    """单档体检：字段齐、类型对、边界没反。"""
    if not isinstance(band, dict):
        raise TierError(f"档位表 `{tid}`{where}的 {_band_label({}, i)} 必须是映射"
                        f"（lo / hi / word），实为 {type(band).__name__}")
    for key in ("lo", "hi"):
        if key not in band:
            raise TierError(f"档位表 `{tid}`{where}的 {_band_label(band, i)} 缺字段 `{key}`"
                            f"（没有界就写 null，别省略）")
        v = band[key]
        if v is not None and not _is_num(v):
            raise TierError(f"档位表 `{tid}`{where}的 {_band_label(band, i)} 的 `{key}` "
                            f"必须是数或 null，实为 {v!r}")
    lo, hi = band.get("lo"), band.get("hi")
    if lo is not None and hi is not None and lo >= hi:
        raise TierError(f"档位表 `{tid}`{where}的 {_band_label(band, i)} 边界反了："
                        f"lo={lo:g} ≥ hi={hi:g}")
    if need_word:
        w = band.get("word")
        if not isinstance(w, str) or not w.strip():
            raise TierError(f"档位表 `{tid}`{where}的 {_band_label(band, i)} 缺 `word`"
                            f"（用词不能为空，实为 {w!r}）")


def _check_ladder(tid, where, bands, axis, *, first_from_zero):
    """一串幅度/区间档的连续性体检：升序、无缺口、无重叠、首尾兜底。"""
    prev_hi = None
    for i, band in enumerate(bands, 1):
        _check_band(tid, where, band, i)
        lo, hi = band.get("lo"), band.get("hi")
        if i == 1:
            if first_from_zero:
                if lo not in (None, 0, 0.0):
                    raise TierError(f"档位表 `{tid}`{where}的 {axis} 首档 "
                                    f"{_band_label(band, i)} 覆盖不到 0：lo 必须是 null 或 0")
            elif lo is not None:
                raise TierError(f"档位表 `{tid}`{where}的 {axis} 首档 "
                                f"{_band_label(band, i)} 不是兜底档：lo 必须是 null（覆盖 -∞）")
        else:
            if lo is None:
                raise TierError(f"档位表 `{tid}`{where}的 {axis} {_band_label(band, i)} "
                                f"不该再有 lo=null：兜底下限只允许出现在首档")
            if prev_hi is None:
                raise TierError(f"档位表 `{tid}`{where}的 {axis} 第 {i - 1} 档已是开区间上界"
                                f"（hi=null），后面不该再排档")
            if lo < prev_hi:
                raise TierError(f"档位表 `{tid}`{where}的 {axis} {_band_label(bands[i - 2], i - 1)} "
                                f"与 {_band_label(band, i)} **重叠**：{prev_hi:g} 被两档同时覆盖")
            if lo > prev_hi:
                raise TierError(f"档位表 `{tid}`{where}的 {axis} {_band_label(bands[i - 2], i - 1)} "
                                f"与 {_band_label(band, i)} 之间有**缺口**："
                                f"[{prev_hi:g}, {lo:g}) 没有档")
        prev_hi = hi
    if bands[-1].get("hi") is not None:
        raise TierError(f"档位表 `{tid}`{where}的 {axis} 末档 "
                        f"{_band_label(bands[-1], len(bands))} 不是兜底档："
                        f"hi 必须是 null（覆盖 +∞）")


def _validate_level(t, where):
    tid = t["id"]
    if t.get("better") not in ("up", "down"):
        raise TierError(f"档位表 `{tid}`{where}缺 `better`（up / down：数值越大越好还是越小越好）")
    bands = t.get("bands")
    if not isinstance(bands, list) or not bands:
        raise TierError(f"档位表 `{tid}`{where}缺 `bands` 列表（至少一档）")
    _check_ladder(tid, where, bands, "水平档", first_from_zero=False)


def _validate_change(t, where):
    tid = t["id"]
    bands = t.get("bands")
    if not isinstance(bands, dict):
        raise TierError(f"档位表 `{tid}`{where}的 `bands` 必须是映射："
                        f"{{up: [...], flat: [...], down: [...]}}")
    missing = [d for d in _DIRECTIONS if d not in bands]
    if missing:
        raise TierError(f"档位表 `{tid}`{where}缺方向档：{missing}"
                        f"（up / flat / down 三个方向都必须有，缺了就有数据无档可落）")
    extra = [k for k in bands if k not in _DIRECTIONS]
    if extra:
        raise TierError(f"档位表 `{tid}`{where}有未知方向：{extra}（只能是 up / flat / down）")
    flat = bands["flat"]
    if not isinstance(flat, list) or len(flat) != 1:
        raise TierError(f"档位表 `{tid}`{where}的 flat 方向必须**恰好一档**"
                        f"（净变化为 0，不分幅度）")
    _check_band(tid, where, flat[0], 1)
    if flat[0].get("lo") is not None or flat[0].get("hi") is not None:
        raise TierError(f"档位表 `{tid}`{where}的 flat 档 lo / hi 都必须为 null（不分幅度）")
    for d in ("up", "down"):
        bs = bands[d]
        if not isinstance(bs, list) or not bs:
            raise TierError(f"档位表 `{tid}`{where}的 {d} 方向缺幅度档（至少一档）")
        _check_ladder(tid, where, bs, f"{d} 方向", first_from_zero=True)


def _validate_shape(t, where):
    tid = t["id"]
    bands = t.get("bands")
    if not isinstance(bands, list) or not bands:
        raise TierError(f"档位表 `{tid}`{where}缺 `bands` 列表（至少一档）")
    seen = []
    for i, band in enumerate(bands, 1):
        if not isinstance(band, dict):
            raise TierError(f"档位表 `{tid}`{where}的第 {i} 档必须是映射（match / word）")
        m = band.get("match")
        if m not in _SHAPE_KEYS:
            raise TierError(f"档位表 `{tid}`{where}的第 {i} 档 match 非法：{m!r}"
                            f"（只能是 {list(_SHAPE_KEYS)}）")
        if m in seen:
            raise TierError(f"档位表 `{tid}`{where}的第 {i} 档 match `{m}` 重复")
        seen.append(m)
        w = band.get("word")
        if not isinstance(w, str) or not w.strip():
            raise TierError(f"档位表 `{tid}`{where}的第 {i} 档（match={m}）缺 `word`")
    miss = [m for m in _SHAPE_KEYS if m not in seen]
    if miss:
        raise TierError(f"档位表 `{tid}`{where}缺形态档：{miss}"
                        f"（三种形态都要有，缺了就有数据无档可落）")


def validate_tiers(doc, *, source=None):
    """档位表的**唯一闸**：结构 / 连续性 / 无缺口无重叠 / 有兜底档 / 边界方向。"""
    where = f"（{source}）" if source else ""
    if not isinstance(doc, dict):
        raise TierError(f"档位表{where}必须是 YAML 映射，实为 {type(doc).__name__}")
    tables = doc.get("tables")
    if not isinstance(tables, list) or not tables:
        raise TierError(f"档位表{where}缺 `tables` 列表（至少一张表）")
    seen = set()
    for n, t in enumerate(tables, 1):
        if not isinstance(t, dict):
            raise TierError(f"档位表{where}的第 {n} 张表必须是映射，实为 {type(t).__name__}")
        tid = t.get("id")
        if not isinstance(tid, str) or not tid.strip():
            raise TierError(f"档位表{where}的第 {n} 张表缺 `id`")
        if tid in seen:
            raise TierError(f"档位表{where}有重名表 `{tid}`（id 是取档的唯一键）")
        seen.add(tid)
        kind = t.get("kind")
        if kind not in (_LEVEL, _CHANGE, _SHAPE):
            raise TierError(f"档位表 `{tid}`{where}的 kind 非法：{kind!r}"
                            f"（只能是 {_LEVEL} / {_CHANGE} / {_SHAPE}）")
        if not str(t.get("name") or "").strip():
            raise TierError(f"档位表 `{tid}`{where}缺 `name`")
        if kind in (_LEVEL, _CHANGE) and not str(t.get("unit") or "").strip():
            raise TierError(f"档位表 `{tid}`{where}缺 `unit`（量纲，如 % / 百分点 / 位）")
        if kind == _LEVEL:
            _validate_level(t, where)
        elif kind == _CHANGE:
            _validate_change(t, where)
        else:
            _validate_shape(t, where)
    return doc


def load_tiers(path=None):
    """读 + 校验档位表；同一 (路径, mtime) 只读一次。缺表 / 坏表抛 `TierError`。"""
    p = pathlib.Path(path) if path else TIERS_PATH
    try:
        stamp = p.stat().st_mtime_ns
    except OSError as e:
        raise TierError(f"读不到报告措辞档位表 {p}：{e}") from e
    key = (str(p), stamp)
    if key not in _TIERS_CACHE:
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
        except yaml.YAMLError as e:
            raise TierError(f"报告措辞档位表 {p} 不是合法 YAML：{e}") from e
        _TIERS_CACHE[key] = validate_tiers(doc, source=p)
    return _TIERS_CACHE[key]


def tier_table(tiers, table_id):
    """按 id 取一张表；没有这张表 → 报错（删表不许静默回退）。"""
    for t in (tiers or {}).get("tables") or []:
        if t.get("id") == table_id:
            return t
    raise TierError(f"报告措辞档位表里没有 `{table_id}` 这张表"
                    f"（删档位可以，删表不行——出句会无词可用）")


def _hit(value, band):
    """左闭右开 [lo, hi)；null 界＝±∞。"""
    lo, hi = band.get("lo"), band.get("hi")
    return (lo is None or value >= lo) and (hi is None or value < hi)


def _direction_of(value):
    """按数值符号定方向档（`up` / `flat` / `down`）。"""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def pick_band(tiers, table_id, value, *, direction=None):
    """取命中的那一档。`change` 表用 |value| 比幅度档，方向单独给或按符号推。"""
    t = tier_table(tiers, table_id)
    if t["kind"] == _SHAPE:
        for band in t["bands"]:
            if band["match"] == direction:
                return band
        raise TierError(f"档位表 `{table_id}` 没有形态档 `{direction}`")
    if t["kind"] == _LEVEL:
        for band in t["bands"]:
            if _hit(value, band):
                return band
        raise TierError(f"档位表 `{table_id}` 没有覆盖 {value!r} 的档"
                        f"（校验本该拦住缺口，这里不该发生）")
    d = direction if direction is not None else _direction_of(value)
    bands = t["bands"].get(d)
    if not bands:
        raise TierError(f"档位表 `{table_id}` 没有方向档 `{d}`")
    mag = abs(value)
    for band in bands:
        if _hit(mag, band):
            return band
    raise TierError(f"档位表 `{table_id}` 的 `{d}` 方向没有覆盖 |{value!r}| 的档")


def tier_word(tiers, table_id, value, *, direction=None):
    """取命中的那一档的用词。出句只经这一个口拿措辞。"""
    return pick_band(tiers, table_id, value, direction=direction)["word"]


def cn_name(en):
    return DISCIPLINES_CN.get(en, en)


def updown_phrase(delta, unit="位", tiers=None):
    """位次变动 → 「上升22位」/「下降2位」/「位次不变」。

    方向词走 `rank_shift` 档位表（表里可按幅度分档，今天默认三档同词）。
    """
    tiers = tiers if tiers is not None else load_tiers()
    if delta > 0:
        return f"{tier_word(tiers, 'rank_shift', delta, direction='up')}{delta}{unit}"
    if delta < 0:
        return f"{tier_word(tiers, 'rank_shift', -delta, direction='down')}{abs(delta)}{unit}"
    return tier_word(tiers, "rank_shift", 0, direction="flat")


def top3_text(groups):
    """[(count, [disc_en,...]), ...] → '化学44篇、材料科学36篇、工程学和植物与动物学同为29篇'"""
    parts = []
    for count, discs in groups:
        names = [cn_name(d) for d in discs]
        if len(names) == 1:
            parts.append(f"{names[0]}{count}篇")
        else:
            parts.append("和".join(names) + f"同为{count}篇")
    return "、".join(parts)


def _college_clauses(college):
    """学院统计（college_stats.json）→ 文句子句素材；缺数据时返回 None（沿用旧稿措辞）。"""
    if not college or not college.get("units"):
        return None
    units = college["units"]                      # 已按（发文量降序, 被引降序）
    by_cites = sorted(units, key=lambda u: (-u["cites"], u["unit"]))[:3]
    tot = college.get("n_cites") or sum(u["cites"] for u in units) or 1
    return {
        "n_subjects": college.get("n_subjects") or 0,
        "n_units": college.get("n_units") or len(units),
        "by_papers": units[:3],
        "by_cites": [(u["unit"], u["cites"] / tot * 100) for u in by_cites],
    }


def _fmt_period_cn(period):
    """202709 → '2027年9月'；None/空 → None。"""
    if not period:
        return None
    p = str(int(period))
    return f"{p[:4]}年{int(p[4:])}月"


def _forecast_index(forecast):
    """forecast_charts.json 的 charts 列表 → {(index, task): meta}（脏数据跳过）。"""
    out = {}
    for c in forecast or []:
        try:
            out[(int(c["index"]), str(c["task"]))] = c
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _cross_clauses(model1, model2, cross1, cross2):
    """模型说明子句（rick 2026-09-24 定稿样式）：
    两线同名模型 →「采用拟合度较好的X得到的预测显示，其…」；
    不同模型 →「采用拟合度较好的X与Y分别对被引频次、国内排名进行预测，…」。
    """
    if model1 and model1 == model2:
        head = f"采用拟合度较好的{model1}得到的预测显示，其"
    else:
        head = f"采用拟合度较好的{model1}与{model2}分别对被引频次、国内排名进行预测，"
    t1 = (f"被引频次预测曲线预计于{_fmt_period_cn(cross1)}前后越过ESI前1%阈值预测曲线"
          if cross1 else "被引频次预测曲线在预测区间内尚未越过ESI前1%阈值预测曲线")
    t2 = (f"国内排名预测曲线预计于{_fmt_period_cn(cross2)}前后与国内ESI前1%机构数预测曲线交叉"
          if cross2 else "国内排名预测曲线在预测区间内尚未与国内ESI前1%机构数预测曲线交叉")
    return f"{head}{t1}，{t2}"


def _prox_shape_key(vals):
    """接近度尾迹形态 → (形态档键, 净变化百分点, 是否全程不回落)。判据与今天逐字一致。

    ⚠ `prox_tail` 存的是**比例**（0–1，`compute.py` 口径），这里换算成**百分点**再进档位表
    （表里的阈值都是百分点，如「≥8 百分点」）——比例口径直接比会把 16.15 百分点读成 0.16。
    """
    rising = all(b >= a for a, b in zip(vals, vals[1:]))
    net_pp = (vals[-1] - vals[0]) * 100
    if rising:
        return "monotone_up", net_pp, rising
    if net_pp > 0:
        return "volatile_up", net_pp, rising
    return "other", net_pp, rising


def _strength_direction(net, rising):
    """发展力度的方向档。

    ⚠ 净变化恰为 0 时：全程不回落 → 持平；期间有回落 → **按下降判**（与今天一致，
    今天的判据是「连涨 or 净变化>0 才给『持续增强』」）。
    """
    if net > 0:
        return "up"
    if net < 0:
        return "down"
    return "flat" if rising else "down"


def _prox_phrases(tail, tiers=None):
    """近一年接近度尾迹 → (趋势描述, 发展力度评价)；数据不足返回 (None, None)（保留手工槽）。

    两个用词分别走 `prox_shape` / `prox_strength` 档位表，默认值与今天逐字一致。
    """
    vals = [float(v) for v in (tail or []) if v is not None and v == v]
    if len(vals) < 2:
        return None, None
    tiers = tiers if tiers is not None else load_tiers()
    shape, net_pp, rising = _prox_shape_key(vals)
    trend = tier_word(tiers, "prox_shape", net_pp, direction=shape)
    strength = tier_word(tiers, "prox_strength", net_pp,
                         direction=_strength_direction(net_pp, rising))
    return trend, strength


def _eta_goal(cross1, cross2):
    """第一学科口径：取两线较晚的交叉点 →「可能将在2027年前后实现」；无交叉点保留手工槽。"""
    pts = [int(c) for c in (cross1, cross2) if c]
    if not pts:
        return MANUAL.format("预计时间（两线交叉点）")
    return f"可能将在{max(pts) // 100}年前后实现"


def _eta_expect(cross1, cross2):
    """第二学科口径：两线跨年（11 月/次年 1 月型）→「有望在2027年底至2028年初进入ESI前1%」；
    否则以较晚交叉点 →「有望在YYYY年前后进入ESI前1%」；无交叉点保留手工槽。"""
    pts = sorted(int(c) for c in (cross1, cross2) if c)
    if not pts:
        return MANUAL.format("预计时间（两线交叉点）")
    first, last = pts[0], pts[-1]
    if last // 100 - first // 100 == 1 and first % 100 >= 10 and last % 100 <= 3:
        return f"有望在{first // 100}年底至{last // 100}年初进入ESI前1%"
    return f"有望在{last // 100}年前后进入ESI前1%"


def build(facts, period, prev, college=None, forecast=None, targets=None, tiers=None):
    """句骨架 → 各段落文本。

    `targets`（2026-10-16，可选）：报告预测章的目标学科（**中文名**，顺序即 1/2 号位）——
    来自 `forecast_charts.json` 的 `report_subjects`（改选学科优先的产物）。
    文字段与预测图必须同一套学科；不传＝按接近度前二（老行为）。
    明细取自 `facts["not_entered"]`（全量）；缺该键的老 facts 回落 `top2_not_entered`。

    `tiers`（2026-10-22，可选）：措辞档位表（`load_tiers()` 的结果）。不传＝读默认表；
    传进来只为测试与预览换表用。**评价用词一律从表里取**，本函数不再写死措辞。
    """
    tiers = tiers if tiers is not None else load_tiers()
    y, m = period[:4], str(int(period[4:]))
    prev_m = str(int(prev[4:]))
    p1 = facts
    best = p1["best_1permille"]
    col = _college_clauses(college)
    d1, c1 = p1["top2_prox_change"][0]
    d2, c2 = p1["top2_prox_change"][1]
    d3 = p1["worst_cn_rank"]
    # 接近度水平用词（排名百分比档的对应物）：驱动量＝1‰ 接近度百分数
    prox_level_word = tier_word(tiers, "prox_level", best["prox_pct"])
    # 接近度变动用词（亮点/警示段）：驱动量＝两个变动最大的学科里较大的那个
    prox_verdict = tier_word(tiers, "prox_verdict", c1)

    qianfen = ("，其中已有学科进入前1‰" if p1["any_1permille"]
               else "，但暂时还没有前1‰的学科")
    years = p1.get("permille_years_est")
    if years:
        years_text = f"按此增长率，{cn_name(best['discipline'])}进入ESI前1‰的时间预计还需要{years}年左右。"
    else:
        years_text = f"按当前增速尚难估算{cn_name(best['discipline'])}进入ESI前1‰的时间。"

    if best["prox_prev_pct"] is not None:
        prev_clause = f"此数值较{prev_m}月上升{best['prox_pct'] - best['prox_prev_pct']:.2f}%，"
    else:
        prev_clause = f"此数值较{prev_m}月{MANUAL.format('升幅%（台账缺上期1‰阈值）')}，"
    p2 = (f"本期我校仍保持有ESI前1%学科{p1['n_disc_1pct']}个，位列云南省高校首位"
          f"{qianfen}。我校目前与ESI前1‰接近度{prox_level_word}的学科为{cn_name(best['discipline'])}，"
          f"接近度为{best['prox_pct']:.2f}%，{prev_clause}较一年前上升"
          f"{MANUAL.format('去年同期升幅%')}，{years_text}")

    p3 = (f"本期我校{cn_name(d1)}和{cn_name(d2)}在ESI前1%接近度方面较{prev_m}月{prox_verdict}，"
          f"分别上升{c1:.2f}%和{c2:.2f}%；值得关注的是{cn_name(d3['discipline'])}国内排名"
          f"继续呈现较大降幅，该学科本期较{prev_m}月下降了{d3['drop']}位，国内排名为{d3['rank']}。")

    if col:
        p4 = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加{p1['top_papers_delta']}篇，"
              f"分别有{col['n_subjects']}个学科来自{col['n_units']}个学院。"
              f"论文量排名前三位的学科分别是{top3_text(p1['top3_groups'])}。"
              f"本期顶尖论文量及其被引频次学院贡献度排名前三位的是："
              f"{'、'.join(u for u, _p in col['by_cites'])}。")
    else:
        p4 = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加{p1['top_papers_delta']}篇，"
              f"覆盖{MANUAL.format('学科数')}个学科。"
              f"论文量排名前三位的学科分别是{top3_text(p1['top3_groups'])}。")

    # ⚠️ 国内机构 / 国内高校是**两个独立 delta**，不能合并成一个值。
    # 2026-09-18 逐格回测发现：旧版写成「…排名较X月均{...inst_delta}…」，
    # 但原件第 2/3 期两者并不相等（202603: +2/+1、202605: +3/+2；台账实测一致），
    # 于是机器稿在 3 期里有 3 期把高校升降说错。现值各说各的。
    trend = (f"与上期数据相比，我校国内机构排名较{p1['prev_label']}"
             f"{updown_phrase(p1['rank_cn_inst_delta'], tiers=tiers)}，排在{p1['rank_cn_inst_now']}名；"
             f"国内高校排名较{p1['prev_label']}{updown_phrase(p1['rank_cn_uni_delta'], tiers=tiers)}，"
             f"排在{p1['rank_cn_uni_now']}名；本期云南大学国际排名{p1['rank_intl_now']}位，"
             f"较上期{updown_phrase(p1['rank_intl_delta'], tiers=tiers)}。")

    situation = (f"本期云南大学22个ESI学科从国内排名上看，有{p1['rank_up']}个学科排名上升，"
                 f"有{p1['rank_down']}个学科排名下降，{p1['rank_flat']}个学科排名与{prev_m}月持平；"
                 f"本期我校{cn_name(d1)}和{cn_name(d2)}在接近度方面较{prev_m}月{prox_verdict}，"
                 f"分别上升{c1:.2f}%和{c2:.2f}%；{cn_name(d3['discipline'])}继续呈现排名下降现象，"
                 f"本期较{prev_m}月下降了{d3['drop']}位，国内排名为{d3['rank']}。")

    # 期号口径唯一在 `period.issue_of`：早于锚点直接报错，不给封面算假期号。
    idx, total = period_mod.issue_of(period)

    # 预测章两个目标学科：targets（report_subjects）优先，缺位按接近度补齐；
    # 不传 targets ＝ entries 前二（与老行为一致）。明细来自全量 not_entered。
    entries = p1.get("not_entered") or p1["top2_not_entered"]
    picked = []
    if targets:
        by_cn = {cn_name(e["discipline"]): e for e in entries}
        picked = [by_cn[t] for t in targets if t in by_cn and by_cn[t] not in picked]
    for e in entries:
        if len(picked) >= 2:
            break
        if e not in picked:
            picked.append(e)
    ne1, ne2 = picked[0], picked[1]
    top3_paren = "、".join(f"{cn_name(d)}（{c}篇）"
                          for c, discs in p1["top3_groups"] for d in discs)
    sit_head = (f"本期云南大学ESI前1%学科继续保持{p1['n_disc_1pct']}个。下图红线为ESI前1%基线。"
                f"各数值为论文被引频次与该学科进入ESI阈值的比值百分数，通过该图展示出我校各学科"
                f"与ESI全球前1%学科的接近度，数值大于100%则为ESI前1%学科。")
    if col:
        by_p = "、".join(f"{u['unit']}（{u['papers']}篇）" for u in col["by_papers"])
        by_c = "、".join(f"{u}（{p:.2f}%）" for u, p in col["by_cites"])
        top_section = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加"
                       f"{p1['top_papers_delta']}篇，分别有{col['n_subjects']}个学科来自"
                       f"{col['n_units']}个学院。论文量排名前三位的学科分别是{top3_paren}。"
                       f"本期顶尖论文量排名前3位的学院分别是{by_p}；"
                       f"顶尖论文被引频次学院贡献度排名前三位的是：{by_c}。")
    else:
        top_section = (f"本期我校共有{p1['top_papers_now']}篇顶尖论文，较上期总数增加"
                       f"{p1['top_papers_delta']}篇，覆盖{MANUAL.format('学科数')}个学科。"
                       f"论文量排名前三位的学科分别是{top3_paren}。")

    def _dir_chg(v):
        # 方向词（上升/下降）由数值符号直接决定，今天不分幅度 —— 见 docs/wording-tiers.md
        # 「暂不档位化清单」第 1 条：同一数值若三处各开一套词，改一处忘两处更容易出错。
        return ("上升" if v >= 0 else "下降") + f"{abs(v):.2f}%"

    fc1 = (f"我校{cn_name(ne1['discipline'])}学科的发展{MANUAL.format('趋势描述')}，"
           f"本期该学科的ESI前1%接近度达到{ne1['prox_pct']:.2f}%，较上期{_dir_chg(ne1['chg'])}；"
           f"学科如按目前的态势发展，进入ESI前1%的目标{MANUAL.format('预计时间（两线交叉点）')}。")
    fc2 = (f"我校{cn_name(ne2['discipline'])}学科本期ESI前1%接近度为{ne2['prox_pct']:.2f}%，"
           f"较上期{_dir_chg(ne2['chg'])}。从预测情况看，{MANUAL.format('发展力度评价')}。")

    # 有预测图元数据（forecast_charts.json）时把上面的手工槽换成模型说明：
    # 数字/日期只来自 report_forecast 的 V1 推荐模型结果，措辞分档是确定的（见 _prox_phrases）。
    fm = _forecast_index(forecast)
    f1c, f1r = fm.get((1, "citation")), fm.get((1, "rank"))
    f2c, f2r = fm.get((2, "citation")), fm.get((2, "rank"))
    trend1, _strength1 = _prox_phrases(ne1.get("prox_tail"), tiers=tiers)
    _trend2, strength2 = _prox_phrases(ne2.get("prox_tail"), tiers=tiers)
    if f1c and f1r and f2c and f2r and trend1 and strength2:
        fc1 = (f"我校{cn_name(ne1['discipline'])}学科的发展{trend1}，本期该学科的ESI前1%接近度达到"
               f"{ne1['prox_pct']:.2f}%，较上期{_dir_chg(ne1['chg'])}；从预测情况看，"
               f"{_cross_clauses(f1c['model'], f1r['model'], f1c.get('first_crossing'), f1r.get('first_crossing'))}，"
               f"学科如按目前的态势发展，进入ESI前1%的目标"
               f"{_eta_goal(f1c.get('first_crossing'), f1r.get('first_crossing'))}。（两线交叉点）")
        fc2 = (f"我校{cn_name(ne2['discipline'])}学科本期ESI前1%接近度为{ne2['prox_pct']:.2f}%，"
               f"较上期{_dir_chg(ne2['chg'])}。从预测情况看，我校{cn_name(ne2['discipline'])}进入ESI前1%的"
               f"发展力度{strength2}，"
               f"{_cross_clauses(f2c['model'], f2r['model'], f2c.get('first_crossing'), f2r.get('first_crossing'))}，"
               f"{_eta_expect(f2c.get('first_crossing'), f2r.get('first_crossing'))}。")

    return {
        "p1": (f"据{MANUAL.format('ESI发布日期')}ESI最新数据显示（ESI数据覆盖时间范围为"
               f"{p1['coverage_window']}），本期全球共有{MANUAL.format('当期机构总数')}个机构登上"
               f"ESI前1%榜单，我校位于第{p1['rank_intl_now']}位，较上期"
               f"{updown_phrase(p1['rank_intl_delta'], tiers=tiers)}。"),
        "p2": p2, "p3": p3, "p4": p4, "trend": trend, "situation": situation,
        "situation_head": sit_head,
        "table2_title": f"云南大学ESI学科发展主要参数情况（{y}年{int(m)}月）",
        "top_section": top_section,
        "forecast_p1": fc1, "forecast_p2": fc2,
        "province_p": (f"本期云南高校ESI前1%学科总数为{MANUAL.format('总数')}个，"
                       f"与上期相比增加{MANUAL.format('增减')}个，{MANUAL.format('新晋学科描述')}。"),
        "cover_issue": f"{y}年第{idx}期（总第{total}期）",
        "cover_month": f"{y}年{int(m)}月",
    }


# ════════════════════════════════════════════════════════════════════════
# 命令行：校验 / 预览 / 逐字回归（评审现场用；全部只读，不写 out/）
# ════════════════════════════════════════════════════════════════════════

_MAN_RE = re.compile(r"【手工：([^】]*)】")

#: 预览用示例值（没给 --rank-pct / --change 时铺一张格子看全档）。
_SAMPLE_LEVEL = (5.0, 30.0, 50.0, 70.0, 95.0)
_SAMPLE_CHANGE = (12.0, 5.0, 1.0, 0.0, -1.0, -5.0, -12.0)

_DIR_CN = {"up": "上升", "flat": "持平", "down": "下降"}
_SHAPE_CN = {"monotone_up": "连涨（逐期不回落）", "volatile_up": "波动上升",
             "other": "其他（含净变化为 0 且有回落）"}


def _read_json(path, default=None):
    if not pathlib.Path(path).exists():
        return default
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_period(out_dir):
    """产物目录 → 出句所需的全部输入（**只读**：facts / meta / 学院 / 预测 / 人工填值）。"""
    d = pathlib.Path(out_dir)
    if not (d / "overview_facts.json").exists():
        raise SystemExit(f"{d} 下没有 overview_facts.json（先跑一期流水线，或换 --period）")
    meta = _read_json(d / "meta.json", {}) or {}
    period = str(meta.get("period_current") or d.name)
    prev = str(meta.get("period_prev") or "")
    if not prev:
        raise SystemExit(f"{d}/meta.json 缺 period_prev：出不了「较上期…」的对比句")
    fm = _read_json(d / "forecast_charts.json", {}) or {}
    return {
        "dir": d, "facts": _read_json(d / "overview_facts.json", {}),
        "period": period, "prev": prev,
        "college": _read_json(d / "college_stats.json"),
        "forecast": fm.get("charts"), "targets": fm.get("report_subjects"),
        "fills": _read_json(d / "manual_inputs.json", {}) or {},
    }


def build_period(out_dir, tiers=None):
    """在**内存里**出句（不写盘）。`tiers` 传路径或表都行。"""
    src = load_period(out_dir)
    if isinstance(tiers, (str, pathlib.Path)):
        tiers = load_tiers(tiers)
    return build(src["facts"], src["period"], src["prev"], college=src["college"],
                 forecast=src["forecast"], targets=src["targets"], tiers=tiers)


def _band_ladder(bands):
    return " ｜ ".join(f"{_band_label(b, i)} {b['word']}" for i, b in enumerate(bands, 1))


def _preview_lines(tiers, source, rank_pct=None, change=None):
    """档位表 → 人读预览：档位全貌 + 输入命中哪一档 + 最终出句。"""
    out = [f"措辞档位表 {source}（version {tiers.get('version')} · "
           f"{len(tiers['tables'])} 张表 · {tiers.get('updated')}）", ""]
    levels = [x for x in (_SAMPLE_LEVEL if rank_pct is None else (rank_pct,))]
    changes = [x for x in (_SAMPLE_CHANGE if change is None else (change,))]
    for n, t in enumerate(tiers["tables"], 1):
        kind = t["kind"]
        head = f"{n}. {t['id']} — {t['name']}（{kind}"
        head += f" · {t['unit']}" if t.get("unit") else ""
        head += "）"
        out.append(head)
        if t.get("used_at"):
            out.append(f"   应用位置：{str(t['used_at']).replace('{word}', '〈用词〉')}")
        if kind == _SHAPE:
            for i, b in enumerate(t["bands"], 1):
                out.append(f"   档位：{b['match']}（{_SHAPE_CN.get(b['match'], '')}）"
                           f" → 「{b['word']}」")
            out.append(f"   出句（以 {t['bands'][0]['match']} 为例）："
                       f"{_render(t, t['bands'][0], None)}")
            out.append("")
            continue
        if kind == _LEVEL:
            out.append(f"   档位：{_band_ladder(t['bands'])}")
            for v in levels:
                b = pick_band(tiers, t["id"], v)
                i = t["bands"].index(b) + 1
                out.append(f"   输入 {v:g}{t['unit']} → {_band_label(b, i)} → 「{b['word']}」")
                out.append(f"     出句：{_render(t, b, v)}")
            out.append("")
            continue
        for d in _DIRECTIONS:
            out.append(f"   档位（{_DIR_CN[d]}）：{_band_ladder(t['bands'][d])}")
        for v in changes:
            d = _direction_of(v)
            b = pick_band(tiers, t["id"], v)
            i = t["bands"][d].index(b) + 1
            sign = "+" if v > 0 else ""
            out.append(f"   输入 {sign}{v:g}{t['unit']}（{_DIR_CN[d]}）→ {_band_label(b, i)}"
                       f" → 「{b['word']}」")
            out.append(f"     出句：{_render(t, b, v)}")
        out.append("")
    return out


def _render(table, band, value):
    """按表的 `template` 拼一句给人看的出句（预览专用，不参与正式出句）。"""
    tpl = table.get("template")
    if not tpl:
        return band["word"]
    if value is None:                       # shape 表没有数值：占位显示
        return tpl.replace("{value:.2f}", "〈值〉").replace("{value}", "〈值〉")
    phrase = band["word"]
    if table["kind"] == _CHANGE and _direction_of(value) != "flat":
        phrase = f"{band['word']}{abs(value):g}{table['unit']}"
    try:
        return tpl.format(word=band["word"], value=value, phrase=phrase)
    except (KeyError, ValueError, TypeError):
        return tpl


def _fill_manual(text, key, fills):
    """把 【手工：槽】 换成 manual_inputs.json 里记的人工填值（读侧回填，同 fill_docx 口径）。"""
    return _MAN_RE.sub(
        lambda m: str((fills.get(f"正文/{key}::{m.group(1)}") or {}).get("value", m.group(0))),
        text)


def regress(period="202609", out_root="out", tiers=None):
    """逐字回归：用当期 facts 在内存里出句 → 与**现产报告 docx 的对应段落**逐字比对。

    判据：段落原文一字不差（人工填值按 `manual_inputs.json` 回填后再比）。
    返回 (行列表, 差异条数)。
    """
    d = pathlib.Path(out_root) / period
    src = load_period(d)
    texts = build_period(d, tiers)
    docx = sorted(d.glob("报告初稿*.docx"))
    if not docx:
        raise SystemExit(f"{d} 下没有报告初稿 docx：没法逐字比对")
    from docx import Document                                       # noqa: PLC0415
    paras = [p.text.strip() for p in Document(str(docx[-1])).paragraphs if p.text.strip()]
    lines = [f"逐字回归 · 期次 {src['period']}（上期 {src['prev']}）", 
             f"- 机器稿（内存出句）：本模块 + {TIERS_PATH.name}"
             f"{'（换表：' + str(tiers) + '）' if isinstance(tiers, (str, pathlib.Path)) else ''}",
             f"- 人工原件：`{docx[-1].name}`（{len(paras)} 段）", ""]
    bad = 0
    for key, text in texts.items():
        exp = _fill_manual(text, key, src["fills"])
        if exp in paras:
            lines.append(f"  ✅ {key}：逐字一致（{len(exp)} 字）")
        elif any(exp in p for p in paras):
            lines.append(f"  ✅ {key}：段落内一致（{len(exp)} 字，封面这类嵌在整行里）")
        else:
            bad += 1
            near = min(paras, key=lambda p: abs(len(p) - len(exp)), default="")
            lines.append(f"  ❌ {key}：对不上（{len(exp)} 字）")
            lines.append(f"     机器稿：{exp}")
            lines.append(f"     报告里最接近的一段：{near}")
    lines.append("")
    lines.append(f"结论：{len(texts) - bad}/{len(texts)} 段逐字一致，差异 {bad} 条"
                 f"（{'PASS' if bad == 0 else 'FAIL'}）")
    return lines, bad


def _check_lines(tiers, source):
    lines = [f"✅ 档位表校验通过：{source}（version {tiers.get('version')} · "
             f"{len(tiers['tables'])} 张表）"]
    for t in tiers["tables"]:
        if t["kind"] == _SHAPE:
            n = len(t["bands"])
        elif t["kind"] == _LEVEL:
            n = len(t["bands"])
        else:
            n = sum(len(t["bands"][d]) for d in _DIRECTIONS)
        lines.append(f"  · {t['id']}（{t['kind']}）{n} 档 — {t['name']}")
    return lines


def _main(argv):
    tiers_path, period, out_root, mode, target = None, None, "out", None, None
    rank_pct = change = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--tiers":
            i += 1
            tiers_path = argv[i]
        elif a == "--period":
            i += 1
            period = argv[i]
        elif a == "--out-root":
            i += 1
            out_root = argv[i]
        elif a == "--rank-pct":
            i += 1
            rank_pct = float(argv[i])
        elif a == "--change":
            i += 1
            change = float(argv[i])
        elif a == "--check":
            mode = "check"
        elif a == "--preview":
            mode = mode or "preview"
        elif a == "--regress":
            mode = "regress"
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                i += 1
                target = argv[i]
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            target, mode = a, (mode or "dump")
        i += 1

    source = pathlib.Path(tiers_path) if tiers_path else TIERS_PATH
    try:
        if mode == "check":
            for line in _check_lines(load_tiers(tiers_path), source):
                print(line)
            return 0
        if mode == "preview":
            for line in _preview_lines(load_tiers(tiers_path), source, rank_pct, change):
                print(line)
            if period or target:
                p = period or target
                d = pathlib.Path(p)
                d = d if d.exists() else pathlib.Path(out_root) / p
                print(f"—— 本期实际出句（{d}，内存出句，不写盘）——")
                for k, v in build_period(d, tiers_path).items():
                    print(f"[{k}] {v}")
            return 0
        if mode == "regress":
            lines, bad = regress(period or target or "202609", out_root, tiers_path)
            for line in lines:
                print(line)
            return 1 if bad else 0
        ld = pathlib.Path(target or "out/202607")
        facts = _read_json(ld / "overview_facts.json", {})
        for k, v in build(facts, ld.name, str(_read_json(ld / "meta.json", {}).get(
                "period_prev") or "202605")).items():
            print(f"--- {k} ---")
            print(v)
        return 0
    except TierError as e:
        print(f"档位表报错：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
