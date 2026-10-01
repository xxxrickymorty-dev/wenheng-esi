# CONTEXT.md — 文衡项目状态板

> 一页纸，给「接手的人 / 未来的自己 / AI」看。详细规格看 `../评审文档/`，本文件不重复。
> 最后核对：2026-09-16。

## 这是什么

云南大学图书馆《学科信息参考》双月报告的自动化流水线。
**代码与流水线全在本目录（`wenheng/`）**；工作区其余目录是文档、数据与归档。

**最大的设计约束（红线）**：运行期 **LLM 不进数据路径**。所有数字只能来自台账，
正文由 `src/sentences.py` 出句骨架拼装。任何「让模型顺手算个数」的想法都是违规。

## 目录地图

| 路径 | 作用 |
|---|---|
| `src/` | 确定性流水线（解析台账 → 算大表 → 预测回测 → 渲染图 → 替换母版） |
| `src/agent/` | Agent 层：`states.py`(状态机) / `tools.py`(工具契约) / `flow.py`(编排) / `heal.py`(自愈) / `trace.py` / `rules/repair_rules.yaml`(自愈规则库) |
| `src/ai/` | AI 层（SPEC）：对外仅 `run`/`capabilities`/`set_switch`；**模型调用唯一进出一处**＝`_attempt.py`（盾→端口→校验→回落），`ai_calls` 留痕唯一写口＝`_record.Recorder` |
| `src/flexible/` | 灵活报告（第二条产线）：查询 / 规划 / 图表规格 / 正文组装；模型口经 `src/ai/` 边界 |
| `server/` | FastAPI + Jinja2 看板（服务端渲染） |
| `web/` | 新工作区前端：React + TypeScript + Vite；经 FastAPI `/api/*` 取数，本机构建 `dist/` 并入库，由 FastAPI 挂载于 `/app/` |
| `master/` | **结构金母版** `学科信息参考母版_2026第5期.docx`，必须入库 |
| `tools/` | 校验脚本（单一来源），如 `verify_demo_run.py`、`crossing_by_report.py` |
| `tests/` | 回归测试 |
| `input/<期次>/监测表.xlsx` | 当期快照：取数后自动新建、馆员核对、并入主台账；生成台的开跑输入（见 ADR-0004） |
| `out/<期次>/` | 产物：`报告初稿_*.docx`、`charts/`、`table2.csv`、`red_slots.json`、`approval.json`；`_superseded/<时间戳>/` 是被新运行撤下的上版成品 |
| `out/_jobs/` | 运行档案（每个任务一个目录） |
| `out/_acquisition/<期次>.json` | 取数状态（取数台读；写方为取数工具，人触发；ADR-0004） |
| `tmp/` | 临时脚本，用完归位或删 |

## 怎么跑（三个入口）

| 入口 | 用途 | 命令 |
|---|---|---|
| **看板**（日常） | 有运行档案、有审批门，是**日常入口** | `uvicorn server.app:app --host 127.0.0.1 --port 8080` |
| 直跑流水线 | 脚本化/调试 | `.venv\Scripts\python.exe src\run_latest.py` |
| `一键出报告.bat` | **仅断网兜底** | 双击 |

- `run_latest.py` 自动取 `input/` 下最新的 `监测表.xlsx`，按台账内最新数据列判定「当期」，
  产物落 `out/<当期>/`。
- 最近实测（2026-09-16）：`input/202609/监测表.xlsx` → `当期=202607 上期=202605`，
  断言全绿、大表 22×11（242 格）、图表 99 张、红色件 354 条、整体 MAPE 1.26%、约 14 秒。

## 流水线五步

```
[1/5] 解析台账 → 断言（不过即拦停）
[2/5] 计算大表 22×11 = 242 格 + 概述事实
[3/5] 预测回测（方法 B：InCites + 历史差值校准）
[4/5] 图表渲染（16 学科 × 6 + 概览 3 = 99 张 PNG）
[5/5] 母版替换 → 报告初稿 docx
```

## 红线（越了就出事）

1. **运行期 LLM 不进数据路径**（见上）。
   模型调用（能力口四能力 / 写作位 / 规划器）唯一进出 `src/ai/_attempt.py`；`ai_calls` 留痕唯一写口 `src/ai/_record.py` 的 `Recorder`。新能力别绕过这两处。
2. 《云大全学科排名、阈值动态检测表.xlsx》是**唯一事实源**。
   **禁止用 openpyxl 存盘改它**（会丢 6 张图表、条件格式、打印设置）——只能 zip 级 XML 替换，改前备份。
   新期次列**贴在已有列后面**，按列追加，绝不覆盖历史。
   **受控写路径（2026-09-29 定，ADR-0004）**：取数核验 → 自动新建 `input/<期次>/监测表.xlsx`（只动当期列）
   → 馆员核对 → 按键「并入台账」才写主台账；写前备份、冲突拒写、列白名单、旧列逐格比对、写后 audit。
   除此之外**馆员不再手工贴表**；运行期流水线对台账仍只读。
   **自愈同样改不了它**：`heal.py` 只产出「解析 overlay」（改变*怎么读*）。两道护栏：
   - **测试级**：`tests/test_agent_heal.py` 用 sha256 钉住自愈路径；
   - **运行期**：`flow.run` 与直跑 `run_pipeline.main` 都在开跑与收尾各取一次台账
     sha256，不等即拦停（flow → `escalated` + 《诊断报告》「原件只读护栏触发」；
     直跑 → 退出码 2 + run_log 的 `ledger_mutated`）。这条覆盖**所有**路径，不只是自愈。

   规则库 `approved_by` 为空 = 未授权，命中也不执行（`RULE_UNAPPROVED`），只往《诊断报告》写建议。
3. **失败运行不在 `out/<期次>/` 留半成品**。两条规矩：
   - `run_parse` **先过断言闸、再落盘**（顺序反了会留下「本次的新宽表 + 上一次的旧报告」）；
   - `flow.run` 在期次确定后把**上版成品**（`报告初稿_*.docx` / `红色件清单.md` / `red_slots.json`）
     撤进 `out/<期次>/_superseded/<时间戳>/`。撤下≠删除，要能追溯。

   由此得到口径：**成品只在它所在目录开始被本次运行改写之后才撤下**。若解析两轮都没过
   （目录压根没被碰过），上一版继续有效。看板据此显示"本期未出稿"，而不是展示一份跟新表格
   对不上的旧报告。详见 `tests/test_agent_heal.py` §8。
4. **状态口径唯一来源**是 `src/agent/states.py`（10 态）；`server/jobs.py` 的 `TERMINAL` 直接引用，不许复制。
5. **两套状态词别混**：
   - 任务级 10 态：`pending / running / retrying / stalled / waiting_approval / completed / warned / escalated / failed / cancelled`
   - 步骤级 4 态：`start / done / warn / failed`（对应 `job.js` 的 CSS 类名，改会坏五步进度样式）
6. **GET 不改状态**；数字只来自后端；产物只经 `/download/{key}` 白名单出去。守卫在 `tests/test_stack_contract.py`。
7. **前端按站点区分**：旧站 `server/` 模板与 `static/` 继续使用 FastAPI + Jinja2 和原生 HTML/CSS/JS，保持**零框架、零构建、零 CDN**；此冻结只约束旧站。新工作区 `web/` 使用 React + TypeScript + Vite，通过 FastAPI `/api/*` 取数；本机运行 `npm run build` 后将 `web/dist/` 入库，由 FastAPI 挂载于 `/app/`（Vite 基路径 `/app/`）。`web/` 遵循 `web/AGENTS.md` 和 `web/UX.md`。旧站继续留在 `server/`，不迁入 React。
   图表由 matplotlib 出 PNG。
8. `.bat` / `.cmd` **纯 ASCII + CRLF**（`.gitattributes` 已钉）。中文交给 Python 输出。
9. `master/`、`云南大学原报告/`、`wenheng/` 的名称与位置被脚本引用，**不要改名移动**。
10. **测试里的跳过必须登记**。数据驱动的用例（依赖 `input/`、`out/`、原始 ESI 包）在缺数据时
    该 skip 而不是 fail，但代价是"数据整片丢失 → pytest 全绿"。所以一律用
    `tests/_guard_registry.py` 的 `skip_unless(理由, 探针)`；会话收尾复核探针，
    **探针说资源其实在就判整个会话失败**。裸 `pytest.skip` 由
    `tests/test_guard_coverage.py` 结构性地禁止。

## 容易搞错的口径

- **ESI 1% 阈值 = 榜单末位 Cites**；**1‰ 阈值 = 榜单第 ⌊(m+1)/10⌋ 位** Cites
  （`+1` 是因为馆员表含表头行，用 ⌊m/10⌋ 会差 1 位）。工具：`src/extract_1permille.py`。
- ⚠ **`extract_1permille.DEFAULT_DATA_ROOT` 指向「子目录名即期次」的那一层**。
  2026-09-16 原始包由 `数据与复现/202601-03ESI数据/<期次>/` 改为 `数据与复现/<期次>/`；
  2026-09-18 去冗余 + 命名归一后固定为 `数据与复现/ESI数据/<期次>/`
  （45 期齐 201903→202607，目录名统一 `YYYYMM`；Incites 导出在 `数据与复现/incites/`）。
  常量过期**不报错**，只会让 `test_permille_rule.py` 整组**静默 skip**（守卫生效 0）。
  `test_数据根常量指向真正含期次的那一层` 现在盯着这件事——再挪目录它会响亮地红。
- ESI 原始导出的**单元格是文本**，必须自行转数。
- 阈值**不单调**（202603→202605 回落是真实回落，不是 bug）。
- 预测有**两条线，别混**：生产线 = 方法 B（`src/forecast.py`）；研究线 = 五模型按学科选模
  （`src/forecast_select.py`）。两维度（被引 / 排名）结论一致率仅 2/8，
  **任一维度都不能单独当学科结论**。
- **预测选模的记录读写归 `src/forecast_choice.py`**（T08 后收敛）：读序 primary
  （`out/_forecast_choices/<期次>.json`）→ legacy（`out/<期次>/forecast_choice.json`）；
  建任务时冻结进 job 快照，运行时写 `out/<期次>/_forecast_choice_applied.json`。
  server / jobs / run_pipeline / report_forecast 都只是它的 adapter，别各自再实现读序。

## 界面用语（UI 术语表，2026-09-28 定）

> 一词一义，**界面文案**以此为准（代码注释不在此列）。**导师明确禁用「数字图书馆」**，
> 对外一律写「云南大学图书馆」。执行细节见 `web/UX.md` 第十节。

| 概念 | 界面写法 | 淘汰 / 禁用 |
|---|---|---|
| 图书馆访客体验（工作区导航入口） | 短标签「陈列馆」；页面品牌「云南大学图书馆」 | 数字图书馆、数字阅览室、学科情报阅览室、数字学科阅览空间 |
| 签单（动作） | 签单（复核并签单） | 签发／钤印／审批／放行（当动作名） |
| 签单状态 | 已签发 · 未签发 · 签名已失效 | 待审批、已放行 |
| 红色件 | 红色件清单（清单页）；页边朱批（报告页批注区）；待人工（条目状态） | 红件、红件清单 |
| 对勘 | 对勘本（页面）；校记（右栏） | 对照本、对勘本页 |
| 数据校验 | 数据校验（失败文案：有 N 处对不上，点看明细） | 断言／机器断言（直出面客） |
| 模型基线 | V1 推荐 | V1 推荐基线／V1 基线推荐／V1 基线 |
| 期次 | 期次（值形如 202607）；需解释时用「数据截至 2026-07」 | 任务期次／报告期次／输出期次 并列出现 |
| 自动修复 | 自动修复中；未能自动修复，需人工接手 | 自愈重试中／已升级（待人工）／需要人接手（多套说法） |
| 生成台三步条（2026-09-29 改） | ①取数 ②核对并并入 ③一键生成 | 取数贴表、放入监测表（旧名） |
| 取数数据核对（2026-09-29 定） | 核对本期数据（通过 / 退回） | 审核（数据侧禁用，避免与报告审核台撞词） |
| 取数数据写进主台账 | 并入台账；已并入 | 回写、贴表、入库（当动作名） |
| 当期快照对象 | 本期监测表 | 输入台账、投喂副本 |

任务级十态的界面话术（唯一映射，前端一个组件渲染）：
待运行 / 运行中 / 自动修复中 / 已停住 / 待签单 / 已完成 / 已完成（有提醒）/ 需人工接手 / 失败 / 已取消

**界面文案禁用词**（技术术语黑名单，自动检查进 `tools/check_web_app.py`）：
`/api`、`sha256`、`agent_events`、`state_history`、`_superseded`、`require_admin`、`?demo=`、
工具名（`run_parse` 等）、`契约 §`、`P0 #`、裸 Markdown `**`。

## 验收三件套（改状态相关代码后按序跑）

```bash
.venv\Scripts\python.exe -m pytest -m ""          # 全量 964 例（默认 960 例，4 个 slow 被 marker 排除）
.venv\Scripts\python.exe -m uvicorn server.app:app --port 8080   # 起服务：仓内 venv 直调，别用 uv 管理的裸 python（会缺包）；起后跑 server/e2e_check.py（只读 188 断言）
.venv\Scripts\python.exe tools/verify_demo_run.py <期次>   # 写路径验收
```

**改这三处前必跑全套**（错了不抛异常，只静默产错报告）：
① `src/compute.py` 大表口径 ② `src/extract_1permille.py` 取位公式 ③ 母版槽位几何（列宽 8.64 / 图 8.26×5.50）。

**验收判据（M3 起）**：里程碑的验收不是"断言全过 / 用例全绿"，而是**「报告数字对」**——
自愈后的宽表与报告大表逐格对齐干净台账（`tests/test_agent_heal.py::test_自愈后的读数与干净原件逐格一致`）。
断言全过只说明没触发已想到的不变量，不说明数字对。

## 当前未决 / 待办

| # | 事项 | 状态 |
|---|---|---|
| L1 | `SRS R-19` 要求 `approval.json` 含 `red_slots_sha256` | ✅ **T04 已实现（2026-09-26）**：签发记录保存红色件 SHA-256（缺少 `red_slots.json` 时为 `null`）；报告指纹为版本化 SHA-256 内容哈希。同大小、同时间戳的内容变化会使旧签发 `stale`；旧 `size:mtime` 与空 `{}` 指纹保持可读但未验证/失效，不自动回填哈希 |
| L3 | 待裁决 13 号：两维度结论不一致时预测章以谁为准 | 待裁 |
| L4 | #11 已定口径确认人＝卜彤，须当面知会馆员 | 待做 |
| — | M3 自愈 | ✅ **已完成**（`187426a` + 09-16 补强）：`heal.py` + `rules/repair_rules.yaml`（6 条规则）+ `tests/test_agent_heal.py`（46 例，含真实台账端到端脏例与逐格对齐的「报告数字对」判据）。2 条 auto 已生效；**2 条 declare 待卜彤填 `approved_by` 才生效**；2 条 never 只出建议。补强项：失败运行不落盘 + 上版成品隔离（两条路径共用 `parse_ledger.quarantine_final_products`）+ 台账运行期 sha256 护栏 + 规则库故障与"无匹配"分开报 + 跳过登记复核 |
| — | M4 审计闭环：`audit.py` / `scan_stale` / `collect_artifacts` / `out/_archive/` | 🟡 **4A 已完成（09-16），4B 未开工**：4A＝`src/agent/audit.py`（LLD §6.6 六项）+ 三个 P3 工具接线 + `write_env_snapshot` + `out/_archive/<期次>/`；实跑 202607 总判定「待人工确认」（4 项通过 / 2 项待签）。4B＝运行档案页（动演示站，待 rick 验收 4A 后决定）。**三个 M4 工具契约本就在 `tools.py` 里、只是 `_todo`，本次是接实现不是新建** |
| — | M4b 学院统计（`src/college_stats.py`，即 F34） | 已顺延 v2.0（赛后） |
| — | M6 公网部署 | 🟡 **脚本与手册已就绪，待上机执行**：`server/deploy/deploy_linux.sh`（09-16 16:36）+ `docs/部署手册（Linux 服务器）.md`（目标 116.62.37.161:8080，服务名 `wenheng-demo`）。**尚无证据表明已在服务器执行过**；本机两条路径都探不通（沙箱出网走白名单代理，非白名单 IP 一律挡），**须由 rick 用手机流量或非沙箱网络确认** |
| — | `out/_archive/`（M4 期次归档） | ✅ 已实现（`audit.archive_period()`，只复制不动源目录；首次归档 202607＝135 文件 / 13.7MB） |

## 两个仓库

| 仓库 | 路径 | 远程 |
|---|---|---|
| 文档 | 工作区**根目录** | 无（刻意） |
| 代码 | `wenheng/` | `github.com/xxxrickymorty-dev/wenheng-esi` |

推送要绕本机代理（沙箱不放行 `github.com`）：

```bash
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main
```

梯子没开就找人开，**不要反复重试**。验证远程用 `git ls-remote origin`，**别用 `git fetch`**（会抹掉 ref）。

## 工程约定

- **做完就提交，不要攒**（吃过攒 20 项悬空改动的亏）。
- 校验脚本单一来源在 `tools/`，不要在别处复写。
- 改动较大的活走 `ai-dev-workflow`：需求澄清 → 方案对齐 → 切增量 → 实现自测 → 验收 → 沉淀。
