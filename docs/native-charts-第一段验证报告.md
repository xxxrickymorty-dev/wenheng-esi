# 原生 Word 图表 · 第一段技术验证报告

> 对象：`src/native_charts.py`（通用引擎）、`src/native_report_charts.py`（C1–C6 规格）、
> `src/fill_docx.py`（开关与插入）、`tests/test_native_charts.py`
> 起因：rick 2026-10-22「所有图表都要 Word 可编辑」
> 环境：Windows / Word 16.0（COM 校验）/ WPS **未安装，未验**（见 §7）
> 日期：2026-10-22

---

## 1. 一句话结论

**可行。** 96 张学科槽位图 + 6 张正文图（1% 接近度 / 1‰ 潜力 / ESI 排名 / 发展趋势 /
顶尖论文年代 / 顶尖论文学科）全部改成 **Word 原生 chart part**（带内嵌数据工作簿），
在 Word 里右键「编辑数据」能打开数据表、改数后图跟着变；
`tools/verify_report_docx.py` 仍 **96/96 + 22/22 全绿**，文档体积反而**从 7.96 MB 降到 2.25 MB**。

只剩 **4 张预测章配图仍为 PNG** —— 转它们要改 `src/report_forecast.py` 暴露序列数据，
该文件不在本次的并行会话文件边界内（见 §6.3）。

**做不到 1:1 的只有一处硬边界**：Word/WPS 没有「数值标签自动避让」能力，
边缘点的标签会压到纵轴刻度字（matplotlib 路径靠 `_labels` 的贪心避让解决）。
其余 P0（反向轴、无框图例、每点标值、六位期次、千分位/%格式、逐学科自适应纵轴、
8.26×5.50cm 图幅、颜色）**全部做到**。

---

## 2. 机制：一个「可编辑图表」＝三件东西，缺一件就不成立

| 部件 | 内容 | 缺了会怎样（实测） |
|---|---|---|
| `word/charts/chartN.xml` | `c:chartSpace`（图形 + `c:numCache` 数值缓存） | 没有图 |
| `word/embeddings/*.xlsx` + `<c:externalData>` + `chartN.xml.rels` 的 `…/package` 关系 | 「编辑数据」打开的数据源 | 右键「编辑数据」报错 `HRESULT 0xB0D7019E`，**改不了数** |
| 段落里的 `<c:chart r:id>` | 图形框引用（`wp:inline` + `wp:extent`） | 图不显示 |

🔴 **只写 `numCache` 不够**。实测（同一份 docx 三个版本，见 §3.3）：

| 实验 | 改了什么 | 图的像素变化 |
|---|---|---|
| A | 只改 `numCache`，工作簿不动 | **0 px（图不变）** |
| B | 改内嵌工作簿，`numCache` 不动 | 图表区 **6722 px / 131 行**变化 |
| C | 摘掉工作簿 + 改 `numCache` | 图表区 **9436 px / 151 行**变化 |

即：**有工作簿时工作簿说了算**（Word 甚至会把 cache 按工作簿回写）；
没有工作簿时 `cache` 才是唯一来源（预览器/部分 WPS 版本走这条路）。
所以本实现**同时写工作簿与 `numCache`**，两者同源同值，避免"预览显示 A、编辑看到 B"。

---

## 3. 硬证据

### 3.1 是原生 chart part，不是图片

```
out/_native_spike/报告_原生图表_spike_202609.docx   ← 单图原型（C1，化学）
  word/charts/chart7.xml            6189 B   c:chartSpace / c:ser / c:numCache
  word/charts/_rels/chart7.xml.rels  319 B   …/package → ../embeddings/Microsoft_Excel_Worksheet1.xlsx
  word/embeddings/Microsoft_Excel_Worksheet1.xlsx  5146 B
[Content_Types].xml                          Default Extension="xlsx"（正确）
```

全量产物（96 槽位 + 6 正文 = 102 张原生图）：

```
tmp/_native_check/报告_全原生_202609.docx   （2.25 MB；PNG 版 7.96 MB）
  chart parts 108（母版原有 6 + 新增 102）
  embeddings  102
  document.xml 里 <c:chart r:id> 102 个、<a:blip>（图片）7 个
  wp:docPr id 113 个，无重复；document.xml.rels 无重复；zip 无重复条目
```

| 图表位 | 原生 | 说明 |
|---|---|---|
| 16 学科 × 6 槽位图 | **96** | C1–C6 六个模板 |
| 1% 接近度 / 1‰ 潜力 | **2** | 横向堆叠柱 + 红色基线（组合图） |
| ESI 排名情况 | **1** | 柱 + 折线**双轴**（左轴柱、右轴折线，双轴反序） |
| 主要学科近期发展趋势 | **1** | 4 折线 + 100% 红基线 + **原生数据表** `c:dTable` |
| 顶尖论文年代 / 学科分布 | **2** | 柱状 |
| 学院贡献度（被引/发文） | 0 → 实跑应为 2 | 本机临时目录缺《论文清单》源件，回落 PNG；`out/202609` 实跑会走原生 |
| 预测章 4 张配图 | **0** | 仍是 PNG（见 §6.3） |

### 3.2 Word 能正常打开，且图表对象是真的

`tmp/_native_spike/probe_doc_charts.ps1`（Word COM，`DisplayAlerts=0`）：

```
OPEN_OK inlineShapes=112 tables=22 seconds=…
  CHARTDATA_OK idx=… series=…         ← InlineShape.Chart.ChartData.Activate() 成功
CHARTS_FOUND=102 charts_without_series=0
```

- `OPEN_OK` ＝ Word 打开**没有走"修复"流程**（文档损坏会直接报错，不返回）；
- `ChartType = 65`（`xlLineMarkers`）＝ 是一个折线图对象（柱状图 51＝`xlColumnClustered`）；
- `SeriesCollection(1).Values` 读回的值与台账逐位一致：
  `[0.2877, 0.2818, 0.2714, 0.2611, 0.2515, 0.2469, 0.2384]`
  （＝`rank_pct` 7 期，化学，国际）；
- 我们的 96 张全部 `ChartData.Activate()` 成功 → **「编辑数据」可用**；
  母版自带的 6 张全部失败（它们只有一条指向 `E:\…` 的外链，没有内嵌工作簿）——
  这是母版的历史遗留，与本次改造无关。

### 3.3 「改数字图会变」的证明方式

`tmp/_native_spike/mutate_workbook.py`（改内嵌 xlsx）→ 重新用 Word 导 PDF →
`tmp/_native_spike/render_and_diff.py`（PyMuPDF 渲染 + numpy 逐像素比对）：

```
page 12: crop (355, 960), differing pixels(>16) = 6722 (1.97%)
rows whose dark-pixel count changed: 131 / 355   y-range: 142 - 331
```

同法做的对照见 §2 的表（A/B/C 三组）。

### 3.4 图幅是精确的 8.26×5.50 cm

PDF 里图表区外框 `Rect(80.6, 165.6, 314.7, 321.5)` pt → **234.1 × 155.9 pt＝8.26 × 5.50 cm**，
与母版槽位硬约束逐位一致（`wp:extent cx=2973600 cy=1980000` EMU）。

### 3.5 纵轴口径与 matplotlib 路径**逐学科一致**

`tests/test_native_charts.py::test_原生轴刻度与_matplotlib_路径逐学科一致`
—— 16 学科 × 6 图 = **96 例，不符 0 例**（`native_charts.auto_axis` 的刻度列表
== `charts._auto_ylim` 的刻度列表，两边共用 `charts._nice_step`）。

---

## 4. 逐条对照 `评审文档/13` 的 P0

### 4.1 共性问题

| # | 项 | 原生图表 | 说明 |
|---|---|---|---|
| C-1 | 窗口 7 期 | ✅ | 类目由 `c:cat` 的 `strCache` 显式给，不依赖自动窗口 |
| C-2 | 每点标数值 | ✅（有保留） | `c:dLbls showVal=1`；**但不能自动避让**（见 §6.1） |
| C-3 | 图例无框 + 多系列顶部居中 / 单系列右上 | ✅ / ⚠️ | 无框 ✅（`spPr noFill+noLine`）；顶部居中 ✅（`legendPos=t`）；「右上」只能选 `legendPos=r`（右侧），**不能是"坐标区外右上、距轴顶 1 行字高"** |
| C-4 | 横轴六位数字、水平 | ✅ | `strRef` 原样出「202509」，不旋转 |
| C-5 | 纵轴 `%` / 千分位 | ✅ | `numFmt 0%` / `#,##0`；百分比图**必须存小数**（存 28.77 会显示 2877.16%，实测踩过） |
| C-6 | 图内标题带单位 | ✅ | `c:title` 富文；但复刻稿口径是**槽位图不写图内标题**（rick 2026-09-25），故 C1–C6 不设 |
| C-7 | 字号/线宽/空心标记 | ✅ | `defRPr sz` / `a:ln w` / `c:marker symbol+size+白填充` 全可控 |
| C-8 | 轴末越界 | ✅ | 类目显式给，不会有第 8 格 |

### 4.2 逐图

| 图 | 关键点 | 原生图表 |
|---|---|---|
| 1 排名百分位 | **反向轴**（百分位小＝上面） | ✅ `c:scaling orientation="maxMin"`；⚠️ 反向轴下类目轴会被顶到上方，必须显式 `crosses="max"`（已修） |
| 2 CNCI | 基准线 1.0 + 两项图例 | ✅ 两条系列（第二条常量 1.0），轴 `include=[1.0]` |
| 3 新增发文量 | 柱状 + 可正可负 | ✅ `barChart`，0 基准（`crosses autoZero`） |
| 4 被引/阈值 | 千分位轴 + 双系列 | ✅ 轴 `#,##0`，标签 `0`（无千分位，同原件） |
| 5 顶尖论文 | **截断轴**（不从 0 起） | ✅ 显式 `min/max` |
| 6 分区占比 | 分组柱 × 3 口径 | ✅ `grouping="clustered"` + `gapWidth/overlap`；标签 `0.##"%"` 按数据原样出位数 |

### 4.3 结论

**不能 1:1 复刻的只有「标签自动避让」与「图例精确像素位」两项**（Word 没有对应 API）。
其余观感要素（配色、空心标记、无框、反向轴、图内标题、期次格式、千分位、逐学科自适应轴）都在。

---

## 5. 六个「Word 直接拒绝打开整份文档」的坑（本次全部踩到并已加固）

这些坑的失败形态**不是"图不显示"，而是"整份报告打不开"**，报错只有一句
「Word 在读取该文件时遇到错误」。定位方法是**二分剥离**单张图的 XML
（`tmp/_native_spike/bar_bisect.py` + `probe_batch.ps1`，一次 Word 会话批量试 N 个变体）。

| # | 坑 | 现象 | 修法 |
|---|---|---|---|
| 1 | 柱状图用了折线专属的 `c:dLblPos val="t"` | Word 拒开 | 柱状图改 `outEnd`；折线图才用 `t` |
| 2 | 堆叠柱用了 `c:dLblPos val="outEnd"` | Word 拒开 | 堆叠柱只认 `ctr`/`inBase`/`inEnd` → 改 `inBase` |
| 3 | `c:gapWidth val="525"` | Word 拒开（`ST_GapAmount` 上限 **500**；matplotlib `width=0.16` 换算正是 525） | 夹到 500（柱宽 1/6≈0.167，观感无可辨差异） |
| 4 | `c:axId val="c1"`（逻辑名） | Word 拒开（`ST_AxId` 是 `xsd:unsignedInt`） | 组合图内部把逻辑名映射成 9 位数字 |
| 5 | 两个 chart group 的 `c:ser/c:idx` 都从 0 数 | Word 拒开（Word 自己生成的组合图是 bar 0,1 + line 2） | 组合图里用**全局递增**的 series 序号 |
| 6 | `formatCode="0.##"%"` 的引号没转义 | Word 拒开（属性被截断） | 属性值统一 `_esc`（`"`→`&quot;`） |

3–6 由 **`native_charts.validate_chart_xml`** 在插入前拦住（抛 `ValueError`，
不会产出一份打不开的报告），并由 `tests/test_native_charts.py` 逐条钉住。

> 顺带三条经验：
> ① 元素顺序（`CT_DLbls` 的 `dLbl*` 必须在 `numFmt/spPr/txPr/dLblPos` 之前、`CT_BarSer` 的
> `invertIfNegative` 在 `dLbls` 之前）Word 宽容、校验器不宽容 —— 一律照 **Word 自己生成的
> chart XML** 抄序（`tmp/_native_spike/word_make_chart.ps1` 可以让 Word 现做一张当金样本）；
> ② `c:f` 的引用区间**参与布局**：写成 `Sheet1!$B$1:$G$1`（少一格）时 Word 只画 6 个点、
> 却仍从 `numCache` 读出 7 个值（COM 读到的点数与画出来的不一致，很容易误判"没问题"）；
> ③ `c:dTable`（原生数据表）是 **plotArea** 的子元素，不能挂在 chartSpace 上。

---

## 6. 做不到 / 降级清单

### 6.1 硬边界（Word 没有这个能力）

1. **数值标签自动避让**。matplotlib 路径用 `_labels` 的贪心避让把 1088 个标签的压字从 117 处降到 0。
   原生图表只有 `dLblPos` 五个固定位，没有"躲开别的字"。**现实后果**：
   8.26 cm 宽的图里，最左/最右点的标签会压到纵轴刻度字或框外（实测 `36.64%` 压 `35%`）。
   可选缓解：`c:dLbl/c:layout/c:manualLayout` 逐点给偏移量 —— 那等于把避让算法搬过来，
   但 Word 的字体度量与渲染时机不可预知，**不可靠**，本段未做。
2. **图例精确位置**。`legendPos` 只有 `t/b/l/r/tr`，没有"坐标区外右上、距轴顶 1 行字高"。
   单系列图（C3/C5）原口径是「坐标区外右上」，原生只能取 `r`（右侧居中）或 `t`（顶部居中）。
   当前取 `r`。
3. **图上自由文字**。如 1‰ 图里的红字「ESI1‰ 基线 = 100%」、`1pct` 图柱左端的数值标签位置。
4. **网格线不穿标签**。无法控制（matplotlib 路径把它当二级障碍物躲）。
5. **堆叠柱的系列级数值标签不渲染**（`1pct`/`1permille` 两张，见 §6.3）。
6. **字体回退策略**。`c:txPr` 能指定 `<a:latin typeface="Times New Roman"/>` /
   `<a:ea typeface="宋体"/>`，但缺字时用 **Word 自己的**回退，不能像 matplotlib 那样钉住
   字体名列表（所以服务器字体与本地字体不一致时，观感差异比 PNG 路径更难控）。

### 6.2 观感差异（不是"做不到"，是"换了渲染引擎"）

1. 网格线/轴线粗细由 Word 画，与 matplotlib 的 0.7pt 不完全一致（当前 9525 EMU≈0.75pt）。
2. 图例的 handle 长度、字距由 Word 排版。
3. 柱宽：matplotlib `width=0.16` → `gapWidth 500`（＝0.1667），差 4%。

### 6.3 逐图可见差异（相对 PNG 版）

| 图 | 差异 | 原因 |
|---|---|---|
| **1% 接近度 / 1‰ 潜力** | **没有数值标签**（PNG 版标了） | Word 不渲染**堆叠柱**的系列级 `c:dLbls`：`inBase`/`ctr`/`outEnd` 三种位置都试过，一张也标不出来（导 PDF 逐张看过）。已显式关掉标签；数值由柱长 + 横轴刻度读出 |
| **ESI 排名情况** | 三系列都没有数值标签；也没有图下数据表 | 3 系列 × 7 期 = 21 个标签在 13.9 cm 里必然叠；`_labels` 的避让机制在原生图表里没有对应物。数据表同理（PNG 版是自己画的表） |
| **发展趋势** | 图下原生数据表**多一行「ESI1‰ 基线 100」** | `c:dTable` 会列出 plotArea 里的**全部**系列，而 100% 基线是靠一条常量系列画出来的（Word 没有「参考线」API）。PNG 版刻意删了那一行（rick 2026-09-24） |
| 各图数值标签 | 边缘点的标签可能压轴刻度字 | §6.1-1，无自动避让 |

### 6.4 未覆盖

- **预测章 4 张配图仍是 PNG**。转它们需要 `src/report_forecast.py` 把「历史/拟合/预测」
  三条序列暴露出来（现在它只把图直接画成 PNG，`forecast_charts.json` 里只有元数据）。
  该文件不在本次并行会话给的文件边界内，故未动。要补的话：在 `report_forecast` 里加一个
  `forecast_series(...)` 返回 `(hist_periods, hist, model_hist, fut_periods, fut, labels, colors)`，
  `native_report_charts` 再加一个 `ov_forecast` 就齐了（`line_chart_xml` 已支持虚线）。
- **WPS 未验**：本机只装了 WPS 云服务组件（`wpscloudsvr.exe`），没有 `wps.exe`/`et.exe`，
  无法实测。按 OOXML 规范写的 chart part + 内嵌工作簿是 WPS 支持的主流形态，
  但**没有证据**，评审前请在装了 WPS 的机器上开一份 `out/_native_spike/` 里的样件确认。

---

## 7. 切默认之后，现有验收会不会仍全绿（rick 指定要的部分）

先给结论：**会全绿，但有 3 处需要同步改口径，1 处会静默降级为 skip。**

### 7.1 不动就绿（已实测）

⚠️ **验 native docx 时必须 `period_override` 或让目录名带期次**：`fill_docx.main` 的期次三级优先是
`override > 目录名 > 台账最新`。把 `out/202607` 复制到 `tmp/_p607` 再跑（目录名没有 6 位期次），
会被判成「台账最新＝202609」，产出「文件名 202607、内容是 202609」的错稿 ——
`verify_report_cells` 立刻报 T01 207 处不符。这不是图表的问题，是**复现铁律**。

| 验收 | 结果 | 为什么 |
|---|---|---|
| `tools/verify_report_docx.py` | **96/96 + 22/22 + 结构验证全绿** | 它只判「格子里恰 2 段 + 1 个 `w:drawing` + `wp:extent` = 8.26×5.50cm」。原生图表用 `wp:inline`，这两项**完全相同** |
| `tools/verify_report_cells.py 202607` | **T01 220/0 · T19 99/0 · T20 242/0 · 附录 274/0，不符 0** | 纯数字核验（T01/T19/T20/附录清单），全程不碰图形 |
| `tools/verify_demo_run.py` | **不受影响** | 验的是任务状态机（running → completed/warned）与徽章文案，不看图 |
| `pytest -m "slow or not slow"` | 需重跑确认（见 §7.3） | 见下 |
| 回测口径（`src/backtest.py`） | **不受影响** | 只读 docx 的**文字与表格**，不读图 |
| `charts.render_all` 的 104 张 PNG | **逐字节不变** | 本次只从 `chart_trend_table` 里抽出了 `trend_picks()`（口径单一来源）。实测「重渲全部图 → 与 `out/202609/charts` 比 sha256」：**bad=0**；唯一"缺"的 16 张是 `forecast_*.png`（由 `report_forecast` 出，不在 `render_all` 里） |

```powershell
uv run python tools\verify_report_docx.py "tmp\_native_check\报告_全原生_202609.docx"
# 槽位格通过: 96/96
# 大表数据行: 22/22
# 正文: 原生图表(需人工确认)=6 图片段=17
# 结构验证全绿

uv run python tools\verify_report_cells.py 202607 `
  --docx "$PWD\tmp\_p607\报告_原生_202607.docx"     # 必须绝对路径（工具要 relative_to(REPO)）
# T01 220 核验 不符 0 / T19 99 不符 0 / T20 242 不符 0 / 附录 274 不符 0
```

### 7.2 需要同步改的 3 处

1. **`服务器/前端` 的图源不变，但要让「图能不能看」不再依赖 docx。**
   `/p/<期次>/chart/*` 照旧读 `out/<期次>/charts/**/*.png` —— **本次一行没动**，
   所以网站、`e2e_check.py`、`test_chart_preview.py` 全部照旧。
   → **前提**：`charts.render_all()` 必须继续跑（`steps.charts` 保持在第五步前）。
   ⚠️ 如果哪天为了"省时间"跳过出 PNG，网站与 `test_chart_preview` 会一起哑掉。

2. **`tools/verify_report_docx.py` 的"正文原生图表"计数会从 0 变成 6（或更多）。**
   该行目前是**纯打印、不断言**，不会红；但读报告的人要知道这个数变了：
   实跑后应为「正文: 原生图表=6~8 图片段=4（预测章）」。建议顺带把文案改成
   「正文: 原生图表=N（可编辑） 图片段=M（网站图源）」。

3. **`tests/test_chart_preview.py::test_真实期次：99张图里至少能解析出大部分`**
   依赖 `out/<期次>/red_slots.json` 里 source 以 `charts/` 开头的槽位。
   本次**刻意保持 source 前缀为 `charts/<学科>/<图名>.png`**（只在 `new` 里加「（原生图表）」），
   所以这条测试照旧有意义、照旧绿。
   🔴 **如果改成 `native_charts/...` 前缀，这条会静默降级成 skip，且
   `agent/audit.manual_slot_checklist` 的"待人工清点"会虚高到 100+。别改。**

### 7.3 会静默降级为 skip 的 1 处（要主动登记）

- `tests/test_chart_preview.py::test_真实期次…`：只在 `red_slots.json` **完全没有** `charts/`
  开头槽位时才 skip。按 §7.2-3 的做法不会发生，**但若以后有人改前缀**，
  它会走 `skip_unless("red_slots.json 里没有图槽位", lambda: False)` ——
  探针返回 `False`（说得过去），守卫复核不会判失败，**等于这条守卫悄悄消失了**。
  真改了前缀的话，请把它换成"原生图槽位必须能在 docx 里找到 `c:chart`"。

### 7.4 其它依赖「图片存在/尺寸」的断言（已逐条查过，均不受影响）

| 位置 | 依赖什么 | 影响 |
|---|---|---|
| `tools/verify_report_docx.py` | `w:drawing` + `wp:extent` 8.26×5.50 | ✅ 原生图表同构 |
| `tests/test_chart_preview.py` | `charts/**/*.png` 落在磁盘上（**网站图源**） | ✅ 仍生成 |
| `tests/test_flexible.py` | 灵活产线自己的 PNG | ✅ 不同路径 |
| `tests/test_api_period_read.py` / `test_archive_page.py` | 服务器图路由 | ✅ 仍读 PNG |
| `tests/test_agent_audit.py` | 红色件槽位文案 | ✅ 只多一个「（原生图表）」后缀 |
| `docx 内嵌图与 charts/ 逐字节相等` | 仅在 `tmp/verify_img_swap_*.py`（临时脚本，非测试） | ⚠️ 该脚本对原生图表模式不适用，不要跑 |

---

## 8. 开关与默认路径

- **默认已切到原生图表**（rick 2026-10-23：「验证通过后就把报告初稿的默认路径切到原生图表」）。
- 回 PNG 版报告的逃生口：**`WENHENG_NATIVE_CHARTS=0`**（`0/false/no/off`）。
  回测/复现需要与旧产物逐字节比时用它；`fill_docx.main(native_charts=False)` 优先级更高。
- **整段兜底**：原生规格构建若抛异常，`fill_docx.main` 会**整套回落 PNG** 并在红色件清单里
  留一条「构建失败，已整体回落 PNG：…」。所以切换默认**不会**因为新渲染器出问题而产出缺图的报告。
  单张失败则只回落那一张。
- 两条路的关系（rick 2026-10-22 定）：
  **DOCX → 原生图表；`charts/**/*.png` → 网站/前端的唯一图源**。PNG 出图步骤**不删**，
  `steps.charts` 仍排在出 docx 之前。

## 9. 复现方式（workdir = `wenheng`）

```powershell
# ① 单图原型（化学 C1，直接读 202609 台账，产物落 out/_native_spike/）
uv run python tmp\_native_spike\native_chart_spike.py 202609

# ② Word 侧体检（打开 / 图表对象 / 编辑数据 / 导 PDF）
powershell -NoProfile -ExecutionPolicy Bypass -File tmp\_native_spike\probe_doc_charts.ps1 `
  -Docx "$PWD\out\_native_spike\报告_原生图表_spike_202609.docx" `
  -OutFile "$PWD\tmp\_native_spike\probe.txt"

# ③ 「改数图会变」：改内嵌工作簿 → 重导 PDF → 逐像素比
uv run python tmp\_native_spike\mutate_workbook.py out\_native_spike\报告_原生图表_spike_202609.docx `
  out\_native_spike\改数版.docx 0.15
uv run --with pymupdf python tmp\_native_spike\render_and_diff.py a.pdf b.pdf 12 tmp\_native_spike\cmp

# ④ 96 张全量（临时 out_root，不碰 out/202609）
$env:WENHENG_NATIVE_CHARTS="1"
uv run python -c "import sys;sys.path.insert(0,'src');import run_pipeline,ledger,pathlib;run_pipeline.main(str(ledger.runtime_path(pathlib.Path('.'))),out_root='tmp/_native_check',period='202609')"

# ⑤ 单元测试
uv run python -m pytest tests\test_native_charts.py -q
```

> `tmp/` 与 `out/` 都不入库：本报告的中间脚本放在 `tmp/_native_spike/`，
> 样件放在 `out/_native_spike/`。要留档请把样件另存到 `归档/`。
