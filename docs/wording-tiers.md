# 报告措辞档位表（评价用词可配置）

> 状态：**代码层已落地（2026-10-22）**；页面要不要暴露、暴露在哪一套前端 —— **待 rick 定**（见 §6）。
> 配置单源：`config/wording_tiers.yaml`（读它的模块是 `src/sentences.py`）。
> 来由：`../调研与论证/discca-试用-20261022/学科竞争力分析平台（DISCCA）试用评测与对文衡的启发-20261022.md` §四.1 ——
> DISCCA 在「平台配置 → 报告配置」里把「排名百分比 → 评价用词」「变动幅度 → 评价用词」做成可改可预览的档位表。

## 1. 一句话

报告出句里的**评价用词**（「接近度**较高**的学科」「发展力度**持续增强**」「较上期**上升**22位」）
原本硬编码在 `src/sentences.py`，现在全部从一张 YAML 档位表取；**改表即改措辞，不必改代码**。
**表里没有一个数字槽**：数字仍只来自动态监测表（运行期 LLM 不进数据路径）。
默认表与今天逐字一致（五期实测 0 差异，见 §5）。

## 2. 这张表管哪几句

| 表 id | 类别 | 驱动量（来自 facts） | 落在报告哪一段 | 今天的词 |
|---|---|---|---|---|
| `prox_level` | 水平档 | `best_1permille.prox_pct`（1‰ 接近度 %） | 概述·前1%与前1‰段（p2）：「与ESI前1‰接近度{用词}的学科为…」 | 较高 |
| `prox_verdict` | 变动档 | `top2_prox_change` 里较大的那个（百分点） | 概述·亮点与警示段（p3）+ 学科发展态势段：「在接近度方面较{上期}月{用词}」 | 表现较好 |
| `prox_strength` | 变动档 | 2 号目标学科 7 期接近度尾迹的净变化（百分点） | 预测章（forecast_p2）：「进入ESI前1%的发展力度{用词}」 | 持续增强 / 需要继续加强 |
| `rank_shift` | 变动档 | `rank_intl_delta` / `rank_cn_inst_delta` / `rank_cn_uni_delta`（位） | 概述·数据来源段（p1）+ 学校发展趋势段：「较上期{用词}」 | 上升 / 下降 / 位次不变 |
| `prox_shape` | 形态档 | 尾迹形态（连涨 / 波动上升 / 其他） | 预测章（forecast_p1）：「学科的发展{用词}」 | 一直呈稳步上升趋势 / 呈波动上升趋势 / 呈波动趋势 |

- **水平档**对应 DISCCA 的「排名百分比档位」（0–10% 领先水平 …）。我们的报告没有「综合排名百分比」这句话，
  与之同性质的是**接近度百分数**（`GLOSSARY.md`「接近度」①：被引 ÷ 阈值 × 100%），所以按它分档，
  用词也换成了我们报告在用的（「较高」），没有照抄 DISCCA 的「领先水平 / 较高水平」。
- 区间一律**左闭右开** `[lo, hi)`，`lo/hi` 写 `null` 表示 ±∞；变动档按**方向 × |值| 的幅度**取档。

## 3. 怎么用（三条命令）

```powershell
# ① 校验（改完表先跑这个；坏表会指名道姓说是哪张表的哪一档）
uv run python -m src.sentences --check
uv run python -m src.sentences --check --tiers tmp\我改过的表.yaml

# ② 预览：给定值 → 命中哪一档 → 最终出句（评审现场演示用）
uv run python -m src.sentences --preview
uv run python -m src.sentences --preview --rank-pct 56.74 --change 7.5
uv run python -m src.sentences --preview --period 202609            # 追加该期真实出句
uv run python -m src.sentences --preview --period 202609 --tiers tmp\我改过的表.yaml

# ③ 逐字回归：用当期 facts 在内存里出句，与现产报告 docx 的对应段落逐字比对
uv run python -m src.sentences --regress 202609
```

退出码：`0` 通过；`2` 档位表非法（stderr 打「档位表报错：…」）；`--regress` 有差异返回 `1`。

### 评审现场那一下：改一个边界，看句子变、数字不动

```powershell
# 1) 复制一份、只把 prox_level 的 [40,60) / [60,80) 边界从 60 挪到 50
$s = Get-Content config\wording_tiers.yaml -Raw -Encoding UTF8
$s = $s.Replace('- {lo: 40.0, hi: 60.0, word: "较高"}', '- {lo: 40.0, hi: 50.0, word: "较高"}')
$s = $s.Replace('- {lo: 60.0, hi: 80.0, word: "很高"}', '- {lo: 50.0, hi: 80.0, word: "很高"}')
[System.IO.File]::WriteAllText("$PWD\tmp\_wording_tiers_demo.yaml", $s, (New-Object System.Text.UTF8Encoding($false)))

# 2) 用改过的表出句（p2 从「接近度较高」变「接近度很高」，56.74% / 14 / 1.61% 一个不动）
uv run python -m src.sentences --preview --period 202609 --tiers tmp\_wording_tiers_demo.yaml

# 3) 数字不动的机器判据（也可直接跑用例）
uv run python -m pytest tests/test_wording_tiers.py -k 改档位 -q
```

⚠ **PowerShell 读写中文 YAML 别偷懒**：`Get-Content` 不加 `-Encoding UTF8` 会按系统码页（GBK）读，
写回去就成乱码、PyYAML 直接报「found character '%'」。上面的 `WriteAllText` + `UTF8Encoding($false)`
是刻意写成不带 BOM 的；手工改表请用 UTF-8 编辑器。

## 4. 校验规则（不过就炸，不静默回退）

`validate_tiers()` 是唯一闸。任一不满足即抛 `TierError`，**指出是哪张表、第几档、哪个字段**：

1. 顶层要有 `tables` 列表；每张表要有 `id`（唯一）、`kind`（level/change/shape）、`name`；
   level/change 还要有 `unit`（量纲），level 还要有 `better`（up/down）。
2. 每一档要有 `lo` / `hi`（没有界写 `null`，不许省略）/ `word`（非空）；
   `lo ≥ hi` 即「边界反了」。
3. **连续、无缺口、不重叠**：首档 `lo: null`、末档 `hi: null`（兜底档），相邻档 `hi == 下一档 lo`。
4. 变动档三个方向 `up / flat / down` 必须齐；`flat` 只一档且不分幅度；
   `up`/`down` 的首档必须覆盖到 0、末档必须 `hi: null`。
5. 形态档三键 `monotone_up / volatile_up / other` 必须齐（缺了就有数据无档可落）。

报错示例（实测）：

```
档位表报错：档位表 `prox_level`（config\wording_tiers.yaml）的水平档 第 1 档 [-∞, 15) 与 第 2 档 [20, 40) 之间有**缺口**：[15, 20) 没有档
档位表报错：档位表 `prox_level`（…）的 第 3 档 [40, 30) 边界反了：lo=40 ≥ hi=30
档位表报错：档位表 `prox_verdict`（…）缺方向档：['flat']（up / flat / down 三个方向都必须有…）
```

## 5. 默认值与「逐字一致」的证据

- 五期（202601 / 03 / 05 / 07 / 09）逐字回归：**14/14 段 0 差异**（与现产报告 docx 比）。
  `202607` 的 `p4` / `top_section` 那段 docx 生成时还没有 `college_stats.json`（报告写「覆盖19个学科」），
  是**改动前就有**的差异，与措辞档位无关（用例里单独放行并注明）。
- 与 `HEAD` 版 `sentences.py` 做 A/B（同一 facts 出句）：
  五期 × 14 段 = **70 段，差异 0**。
- 证据落在 `tests/test_wording_tiers.py`（33 例，含坏表逐条报错、边界换档、数字不变）。

### ⚠️ 需要知道的一处「设计内」差异

档位表把「幅度」分出来了，今天没有这一层。所以**将来的某期**若恰好落在新露出来的档里，用词会比今天更具体：

| 场景 | 今天 | 用表之后 |
|---|---|---|
| 2 号目标学科尾迹净变化 2–8 百分点 | 持续增强 | **稳步增强** |
| 2 号目标学科尾迹净变化 0–2 百分点 | 持续增强 | **基本持平** |
| 亮点学科接近度上升 2–8 百分点 | 表现较好 | **表现平稳** |

五期实测都落在 ≥8 档或 <2 档，所以**没有触发**。若想让它在任何情况下都与今天一字不差，
把 `prox_strength` / `prox_verdict` 的 `up` 三档 `word` 全填成今天那个词即可（表就是干这个的）。

## 6. 暂不档位化清单（为什么这些没进表）

| # | 位置 | 为什么不进表 |
|---|---|---|
| 1 | `_dir_chg`（预测章的「较上期上升3.51%」）与 p2 的「此数值较7月上升1.61%」 | 方向词（上升/下降）由数值符号直接决定，今天不分幅度。它与 `rank_shift`/`prox_strength` 同源，同一数值若三处各开一套词，改一处忘两处反而更容易出错。 |
| 2 | p3「国内排名继续呈现**较大降幅**」、态势段「继续呈现**排名下降现象**」 | 同一事实（`worst_cn_rank.drop`）在两段两种固定说法，且「较大」今天**不与降幅挂钩**（降 2 位也写「较大」）。要档位化得先定「降幅」的业务档界——属口径变更，留给 rick 定，不在本次最小改动里。 |
| 3 | `qianfen`（「其中已有学科进入前1‰」/「但暂时还没有」）、`years_text`（「还需要5.0年左右」）、`_eta_goal`/`_eta_expect`（「有望在2027年底至2028年初进入」）、`_cross_clauses`（模型说明句） | 布尔事实与**年份**陈述，不是评价用词。年份/期次是数字，**数字不进表**（红线）。 |
| 4 | `MANUAL`（`【手工：…】`）槽 | 人工填写，不归表管；填值走 `manual_inputs.json`。 |
| 5 | `situation_head` / `top_section` / `table2_title` / `province_p` / `cover_*` | 说明性文字与标题，没有评价措辞。 |
| 6 | p3「**值得关注的是**…」 | 段落框架词（framer），不是分档措辞。 |
| 7 | 灵活报告（`src/flexible/opinion.py`：`descriptive_trend` 的「一路走高 / 震荡上行 / 方向向好」、`rank_sentence` 的「前 1/3 / 中间 1/3 / 后 1/3」） | 第二条产线自己的措辞体系，本次不动（文件边界 + 产线不同）。要档位化另开一张表，别混进复刻报告这张。 |

## 7. 要不要在页面上暴露（给 rick 的决策项）

| 方案 | 落地成本 | 风险 | 建议 |
|---|---|---|---|
| **A. 不暴露**，只留 CLI + 本文档 | 0 | 无 | 评审现场用 `--preview` 演示即可 |
| **B. 只读 + 预览**（新站 `web/` 加一页「报告配置」，`GET /api/wording-tiers` 返回表 + 服务端内存出句预览） | 中（1 页 + 1 个只读接口） | 低：不写文件 | **推荐**——评审看到「措辞是分档的、可核对」就够了 |
| **C. 可改可保存**（`PUT` 校验后写 YAML，写前备份） | 高 | 中：档位表属**签字口径**，改了会让已签单报告的重出指纹变化，需要一条「改了要重出/重签」的联动提示 | 赛后再说 |
| 旧站 `server/` + `static/` | — | — | **不动**（技术栈冻结：零框架/零构建/零 CDN） |

要点：**别做成"在线编辑一个 YAML 文本框"**。档位表是口径，改它应当留下「谁改的、改前是什么」——
如果真要做 C，请复用状态库的留痕思路（`approval_history` 那种），而不是直接覆盖文件。

## 8. 已知边界

- 档位表**只**影响 `src/sentences.py` 出的复刻报告正文；`src/flexible/`、图表标题、docx 母版里的静态文字都不读它。
- **换词会撞两处外部锚点**（不报错，只会静默对不上）：
  - `tools/compare_reports.py` 的 `TEXT_ANCHORS` 里有「与ESI前1‰接近度较高」「国内排名继续呈现较大降幅」——
    那份工具按锚点找新旧两边的段落做对比，**改了 `prox_level` / 那两句的用词，要同步它**。
  - `src/fill_docx.py` 的段落锚点匹配的是**母版原文**（不是本次生成的文字），所以换词不影响找段；
    但换词后仍应跑一遍 `tools/verify_demo_run.py <期次>` 确认母版替换正常（本次按红线**没跑**，留给串行验收）。
- 换表后**必须**跑 `--regress <当期>`：判据是「报告数字对 + 该变的词变了」，不是「断言全过」。
- 表在运行时按 (路径, mtime) 缓存，改完文件不用重启进程（下一句生效）；但**已生成的 docx 不会自动更新**。
- 本次把档位表的读/校验/取档与 CLI 都放在 `src/sentences.py` 里（文件边界只给了这一个 `.py`）。
  它现在是 880 行，**偏胖**；若 rick 同意，下一步可把第 41–260 行的档位机制拆成 `src/wording_tiers.py`，
  `sentences.py` 只留 `tier_word(...)` 调用。
