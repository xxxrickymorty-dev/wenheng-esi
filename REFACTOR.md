# REFACTOR.md — 重构交接书（唯一必读）

> 给接手重构的模型 / agent。**读完这一份就能开工**，不用探索仓库。
> 本文没写的，先问 rick；不要自己 `ls -R`、不要全库 grep。
> 要做的是**升级**（改成什么样、按什么顺序）而不是单纯重构 → 先读 `docs/refactor/UPGRADE.md`。
> 规模数字为 2026-10-25 实测，改代码后重跑 `uv run python tools/gen_route_map.py`
> 与 `uv run python tools/gen_front_map.py` 同步。

---

## 0. 这是什么，重构要达成什么

云南大学图书馆《学科信息参考》双月 ESI 分析报告的自动化流水线（参赛作品）。
三件套产物：报告初稿 docx / 对照差异报告 / 红色件清单。

代码分两块，**重构目标不同，不要混在一起做**：

| 块 | 位置 | 现状痛点 | 重构目标 |
|---|---|---|---|
| 后端 | `server/` + `src/` | `server/app.py` 单文件 3021 行 / 91 个路由，页面渲染与 JSON API 混在一起 | 按「资源」拆成 APIRouter 模块；页面路由与数据路由分离 |
| 前端 | `web/src/` | 页面组件与 api 层直接耦合；`library/` 3D 书架 3 个文件 3850 行 | api 层稳定后，页面按「工作台一条动线」切分；3D 书架单独隔离 |

**旧站 `server/templates` + `server/static` 是冻结区**（零框架/零构建/零CDN），重构不要顺手改它。

### 一条前提：不做整体重写

2026-09-25 试过一轮「多 agent 大重构」（规划 / 建模 / 实施三角色），结果：建筑模型被否、静态稿删除、多数模块暂停，只有安全相关落地。台账见 `docs/重构规划与验收台账（2026-09-25）.md`（**已过时**，远端早从 `a5b7130` 推进了 100+ 提交）。

所以走「绞杀者」式：一次只搬一个资源组，每片可 `git revert`，**接口路径与返回结构一律不动**。整体重写在这个项目上等于自毁 704 个可盖章槽位。

## 1. 三条红线（违反即作废，不论代码多漂亮）

1. **运行期 LLM 不进数据路径。** 报告里每个数字只能来自台账和 `out/` 产物，正文由 `src/sentences.py` 出句骨架拼装。任何「让模型顺手算个数 / 润色一下数字」都是违规。
2. **数据只读。** `../数据与复现/`、`../云南大学原报告/`、`out/`、`input/` 一律不许写。演示要什么状态就用真实状态，不许清空/回填凑数。
3. **报告产物一字节不许变。** 复刻线 704 个槽位、可盖章。改 `src/charts.py`、`compute.py`、`fill_docx.py` 之后必须验证复刻产物未变（见 §6）。

## 2. 规模事实：先知道哪 96% 是噪声

| 路径 | 体积 | 文件数 | 能不能读 |
|---|---:|---:|---|
| `out/` | 708 M | 2121 | ❌ 产物。要数据只看 `out/<期次>/*.json` 的字段名 |
| `.venv/` | 638 M | — | ❌ 虚拟环境 |
| `web/node_modules/` | 140 M | — | ❌ |
| `recon/` | 115 M | 290 | ❌ 参考站勘察截图，与代码无关 |
| `web/dist/` | 22 M | — | ⚠️ 构建产物，只在验证时看 `index.html` 是否存在 |
| **真源码合计** | **17 M** | **398** | ✅ `src/` 191 + `server/` 55 + `web/src/` 82 + `tools/` 70 |

**结论：源码只占 1.5%。** 直接让模型在 `wenheng/` 里 `ls`，它看到的第一个目录就是 `out/`（708M），一读就废。

源码体量：

| 模块 | 文件 | 行数 | 最大单文件 |
|---|---:|---:|---|
| `src/`（引擎） | 191 | 26,539 | `charts.py` 1254 / `fill_docx.py` 1226 |
| `server/`（Web 层） | 55 | 7,828 | **`app.py` 3021** ← 91 路由 |
| `web/src/`（新前端） | 82 | 18,254 | `libraryRuntime.ts` 1751 / `LibraryScene.tsx` 1376 |

## 3. 只读白名单（省上下文的核心）

**启动成本目标：≤ 600 行文档，0 个源码文件。** 开工前只读这三份：

1. 本文件（约 140 行，读完别回头翻）
2. `CONTEXT.md`（185 行）—— 红线全文 + 待办
3. `GLOSSARY.md` 的「禁用词」一节（约 40 行）—— 界面上不能出现的词

然后**按任务卡读，一次只读卡上列的文件**。

| 任务 | 只读这些（精确到行号区间） | 禁止读 |
|---|---|---|
| 拆后端路由 | `server/app.py:1-90`（imports/依赖注入）+ `docs/refactor/route-map.md` 对应行 | app.py 全文 |
| 改某个接口 | `docs/refactor/route-map.md` 查到行号 → 只读那 10–70 行 | 整份 app.py |
| 改前端页面 | `docs/refactor/front-map.md` 查到文件的 api 依赖 → 只读那一个 `.tsx` | 其它页面 |
| 改 3D 书架 | `web/src/library/scene/LibraryScene.tsx` + `libraryRuntime.ts` 目标函数附近 100 行 | Reader.tsx / *.css |
| 改图表口径 | `src/charts.py` 对应函数 + `CONTEXT.md`「图表」节 | 先跑测试再说 |

**硬性禁止**：`ls -R`、`grep -r`（不带 `-l`）、`find .`、`cat out/**`、读 `tests/` 下 125 个测试文件中的任何一个（要口径样本时只读 `tests/test_compute_units.py`）。

## 4. 模块切分（按这个切，不按文件名字母序）

### 后端 91 个路由，实际是 5 组

| 组 | 路由数 | 在 `app.py` 的位置 | 性质 |
|---|---:|---|---|
| `/api/periods/*` | 40 | 837–1613、2874–2944（散布） | **数据 API，重构主战场**（取数/签署/填充/回滚/预测选择） |
| 页面型（返回 HTMLResponse） | 15 | 263–700 一带 | 服务端渲染 Jinja2，**冻结** |
| `/api/jobs/*` | 8 | 695–739、2734–2780、2945–2991 | 生成任务与进度（SSE） |
| `/api/dialog/*` | 6 | 2224–2503 | 对话前门（单函数 152 行，最大） |
| 杂项 | 22 | 740–836、1694–1725、2141–2223、2504–2720 | healthz / me / status / sandbox / ai / forecast / ledger / login |

完整清单与每个函数的确切行号 → `docs/refactor/route-map.md`（91 行表格，别读 app.py 找）。

### 前端 82 个 ts/tsx，实际是 3 层

| 层 | 文件 | 说明 |
|---|---|---|
| 数据层 | `api.ts`(503) / `api-dialog.ts` / `api-forecast.ts` / `api-flexible.ts` | 只做请求与类型；28 个导出函数 |
| 页面层 | `Workbench.tsx`(484) `Acquire.tsx`(713) `Panorama.tsx`(673) `Review.tsx`(643) `Report.tsx`(493) `StoryBand.tsx`(392) `Archive.tsx`(354) + 十余个薄页 | 每个页面 = 一条动线节点 |
| 隔离层 | `library/scene/*`(3850) + `library/Reader.tsx`(723) | 3D 书架，独立演化，**别和页面重构混做** |

每个文件的 api 耦合面 → `docs/refactor/front-map.md`（耦合越多改动风险越高，第一行就是 `DialogPage.tsx` 8 个依赖）。

## 5. 任务卡（一次一张，整段贴给模型）

```
【任务】<一句话，例如：把 /api/periods/{period}/acquisition/* 抽成独立 APIRouter>
【范围】只准改：<列出 2-3 个精确路径>
【只读】<列出精确文件:行号区间>，其它一律不读
【不动】数据与复现/ 云南大学原报告/ out/ input/ server/templates/（冻结区）
【验收】<命令，见 §6>
【交付】先给计划（改哪些文件、每处改什么），我确认后再动手
【禁止】不得新增依赖；不得改接口路径与返回结构；不得顺手重构范围外代码
```

**为什么必须「先给计划」**：计划阶段它只会说法，不会读文件。你在这一步就能看出它有没有乱猜模块，省掉后面 80% 的无效读取和返工。

## 6. 验收（每张任务卡收尾必跑）

```bash
cd wenheng
uv run python -m pytest -m ""                    # 全量回归
uv run python tools/verify_report_cells.py 202607 # 报告数字未变
uv run python tools/verify_demo_run.py 202607     # 流水线产物确定性
uv run ruff check .
cd web && npm run build                           # 改了 src/ 必须重构建并提交 dist/
```

**判据是「报告数字对」，不是「测试全绿」。** 测试全绿只说明没触发已想到的不变量。

## 7. 已经踩过的坑（别再踩）

1. **`uv run uvicorn ...` 会报 `trampoline failed to canonicalize script path`**（中文路径）。一律用 `uv run python -m uvicorn server.app:app --host 127.0.0.1 --port 8080`。
2. **改了 `web/src/` 忘了 `npm run build`**，演示站继续跑旧代码，不报任何错。
3. **新增接口路径必须 `/api/*` 且带登录检查**，`tests/test_stack_contract.py` 三条契约钉着。
4. **接口路径与返回结构不许动** —— 旧站模板、新前端、`e2e_check.py` 152 项断言、`tests/` 都在依赖它们。
5. **`server/app.py` 里有两个同名路由**（`/api/periods/{period}/forecast-choice` 的 GET 与 GET/POST），拆模块时别合并。
