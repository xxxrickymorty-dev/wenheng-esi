# spec：AI 问数 —— SQLite + 受控 NL2SQL + MCP + ECharts

- **状态**：已实现（2026-10-25；对照 LLM 侧架构草案的四不变量，本 spec 是其「问数引擎」的第二个消费者）
- **契约**：接口 #38（`docs/前后端分工与接口契约（2026-09-23）.md`）
- **先例（必读）**：`src/ledger_mirror.py`（台账→SQLite 只读镜像，票 01）；
  `src/flexible/queries.py`（白名单查询＋来源链）；`src/ai/_attempt.py`（模型边界）
- **关联**：`docs/specs/2026-10-12-LLM侧架构（草案）.md`——本实现 = 该草案「一条流水线」的
  数据库落地版：`规划器认问 → 引擎取值`（写作轮暂不做，答案为确定性句骨架拼装）

## 缘起

用户需求（2026-10-25）：
1. 改造使用**数据库**存储清理后的数据或报告等数据——合理设计表结构，用 SQLite；
2. AI 问数通过 **MCP 或 NL2SQL** 查询相关数据；
3. 数据旁边支持**本地各类图**（柱状图/饼图等）**ECharts 可视化**。

## 红线（四不变量，任何改动不得违反）

1. **运行期 LLM 不进数据路径**：所有数字只能来自 SQLite 库（台账镜像同口径），
   模型输出类型里没有数值。「NL2SQL」是**受控版**——模型/规划器只产
   **白名单查询规格**（零数字），SQL 由引擎参数化拼装，永不拼接字符串。
2. **只读**：问数库由确定性 ETL 构建（`tools/build_aiqa_db.py`），运行期唯一可写表
   是 `qa_log`（留痕）。镜像/问数库都是只读连接。
3. **白名单**：规划器产出只含 `(_KINDS, dim_metric 白名单, 学科白名单, 期次轴)`；
   MCP `aiqa_sql` 只放行表/列白名单内的 SELECT，禁 `;` / `--` / DML/DDL 关键字，
   自动补 `LIMIT 200`。
4. **留痕**：每问落 `qa_log`（问题/规格/规划来源/行数/耗时/图型），写失败不阻塞查询。

## 库表设计（`src/aiqa_db.py` → `out/_aidata/aiqa.sqlite`）

| 表 | 作用 | 关键列 |
|---|---|---|
| `dim_discipline` | 22 学科维 | discipline（EN，主键）、discipline_cn |
| `dim_metric` | 指标白名单维 | metric（EN）、metric_cn、source_sheet（台账工作表） |
| `dim_period` | 期次轴 | period（YYYYMM，主键）、idx（排序） |
| `facts` | **长表事实**（与 `ledger_mirror` 同口径） | period、metric、discipline、value |
| `report_table2` | 当期大表 22×11（报告口径快照） | discipline、col、value |
| `report_overview` | 概述事实键值 | key、value |
| `qa_log` | 唯一运行期可写：问数留痕 | ts、user、question、specs、plan_origin、n_rows、elapsed_ms、answer_text、chart_kind |

ETL 由 `tools/build_aiqa_db.py` 驱动（确定性：同输入同库；构建前先跑台账解析断言）。
演示环境：`uv run python tools/make_demo_ledger.py` 生成演示台账
（**并落 sidecar 标记 `input/.demo_marker.json`**，含 sha256；
钉真实指纹的数据测试读标记自动 skip——走 `_guard_registry` 登记，守卫体检照常复核）。

## 问数引擎（`src/aiqa_engine.py`）三口

```
plan(question, con)         # 规则规划器：问句 → {"specs":[…], "origin":"rule", "note"}
execute(con, specs)         # 参数化 SQL 执行（只读连接）→ {"rows":[…]}
render_text(con, q, result) # 人话渲染（句骨架拼装，千分位）
suggest_chart(con, specs, result)  # 图型建议：series→line；compare→bar/pie；at/overview→table
to_chart_data(con, chart, result)  # ECharts 就绪 {kind,title,categories,series}
```

- 规格类型 `_KINDS = ("series", "compare", "at", "overview", "table2")`：
  `series`（某学科某指标历期）/ `compare`（当期多学科对比）/ `at`（指定期次查数）/
  `overview`（概述键值）/ `table2`（当期大表）。
- 规划器是**规则适配器**（离线可跑）：别名表 `_METRIC_ALIAS`
  （「总被引」→`total_cites`、「顶尖论文」→`top_papers`、中文/英文、学科中文名反查等）；
  期次解析（「最新」「202603」）；后续接 ModelPlanner 时同样只产规格（草案票 03 口径）。

## 三条消费路径

| 路径 | 入口 | 说明 |
|---|---|---|
| Web 前端 | `POST /api/aiqa/ask` + `web/src/Aiqa.tsx`（`/app/?view=aiqa`） | 提问 → 人话答案 + ECharts（line/bar/pie/table 切换，npm 打包不引 CDN）；示例问题 chips |
| HTTP API | `GET /api/aiqa/meta` / `POST /api/aiqa/ask` / `GET /api/aiqa/log`（admin） | 契约 #38；meta/ask 登录可用（`user_route`），log 仅 admin |
| MCP | `server/mcp_aiqa.py`（stdio JSON-RPC，零依赖） | 工具 `aiqa_meta` / `aiqa_ask` / `aiqa_sql`；`aiqa_sql`＝受控只读 SELECT（外部分析工具可直接接） |

## 用户故事（验收口径）

1. 作为馆员，我在问数页问「化学的总被引近年来怎么走」→ 得到带数字的人话答案 + 折线图。
2. 作为馆员，我问「当期各学科高水平论文占比」→ 得到柱状/饼图，可切换图型。
3. 作为维护者，我在 MCP 客户端里 `aiqa_sql` 查 `facts` → 白名单外表名/危险语句被拒。
4. 作为维护者，我数「qa_log」行数 = 问数次数 → 留痕可审计。
5. 作为评审，我读答案里的任一数字 → 能在 `facts`/`report_table2` 里找到同值行（来源可溯）。

## 测试与守卫

- 全量 pytest：1323 passed / 41 skipped（守卫体检通过）/ 2 存量失败
  （`test_acquisition_state` 两条与本次改动无关，干净基线同样失败）。
- 指纹用例与演示数据：`tests/conftest.py::real_ledger` +
  `test_forecast_select.py::out_dir` 检测演示标记即 skip（理由登记守卫体检）；
  `test_agent_heal._sheet_xml` 修 rels 属性顺序兼容（Excel `Id` 在前 / openpyxl `Target` 在前）。
- 契约测试 `tests/test_stack_contract.py` 27 例全过——新路由在登录保护与 GET 不改状态红线内。
