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
| `src/agent/` | Agent 层：`states.py`(状态机) / `tools.py`(工具契约) / `flow.py`(编排) / `trace.py` |
| `server/` | FastAPI + Jinja2 看板（服务端渲染） |
| `master/` | **结构金母版** `学科信息参考母版_2026第5期.docx`，必须入库 |
| `tools/` | 校验脚本（单一来源），如 `verify_demo_run.py`、`crossing_by_report.py` |
| `tests/` | 回归测试 |
| `input/<期次>/监测表.xlsx` | 输入台账（馆员手工维护的原始导出） |
| `out/<期次>/` | 产物：`报告初稿_*.docx`、`charts/`、`table2.csv`、`red_slots.json`、`approval.json` |
| `out/_jobs/` | 运行档案（每个任务一个目录） |
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
2. 《云大全学科排名、阈值动态检测表.xlsx》是**唯一事实源**，馆员手工维护。
   **禁止用 openpyxl 存盘改它**（会丢 6 张图表、条件格式、打印设置）——只能 zip 级 XML 替换，改前备份。
   新期次列**贴在已有列后面**，按列追加，绝不覆盖历史。
3. **状态口径唯一来源**是 `src/agent/states.py`（10 态）；`server/jobs.py` 的 `TERMINAL` 直接引用，不许复制。
4. **两套状态词别混**：
   - 任务级 10 态：`pending / running / retrying / stalled / waiting_approval / completed / warned / escalated / failed / cancelled`
   - 步骤级 4 态：`start / done / warn / failed`（对应 `job.js` 的 CSS 类名，改会坏五步进度样式）
5. **GET 不改状态**；数字只来自后端；产物只经 `/download/{key}` 白名单出去。守卫在 `tests/test_stack_contract.py`。
6. **技术栈冻结**：FastAPI + Jinja2 服务端渲染；前端**零框架、零构建、零 CDN**。
   图表由 matplotlib 出 PNG。别再提 React/Vue/Tailwind/Vite/WebSocket。
7. `.bat` / `.cmd` **纯 ASCII + CRLF**（`.gitattributes` 已钉）。中文交给 Python 输出。
8. `master/`、`云南大学原报告/`、`wenheng/` 的名称与位置被脚本引用，**不要改名移动**。

## 容易搞错的口径

- **ESI 1% 阈值 = 榜单末位 Cites**；**1‰ 阈值 = 榜单第 ⌊(m+1)/10⌋ 位** Cites
  （`+1` 是因为馆员表含表头行，用 ⌊m/10⌋ 会差 1 位）。工具：`src/extract_1permille.py`。
- ESI 原始导出的**单元格是文本**，必须自行转数。
- 阈值**不单调**（202603→202605 回落是真实回落，不是 bug）。
- 预测有**两条线，别混**：生产线 = 方法 B（`src/forecast.py`）；研究线 = 五模型按学科选模
  （`src/forecast_select.py`）。两维度（被引 / 排名）结论一致率仅 2/8，
  **任一维度都不能单独当学科结论**。

## 验收三件套（改状态相关代码后按序跑）

```bash
.venv\Scripts\python.exe -m pytest -m ""          # 122 例（默认 120 例，-m "" 含 e2e）
uvicorn server.app:app --port 8080                 # 起服务后跑 server/e2e_check.py（只读 96 断言）
.venv\Scripts\python.exe tools/verify_demo_run.py <期次>   # 写路径验收
```

**改这三处前必跑全套**（错了不抛异常，只静默产错报告）：
① `src/compute.py` 大表口径 ② `src/extract_1permille.py` 取位公式 ③ 母版槽位几何（列宽 8.64 / 图 8.26×5.50）。

## 当前未决 / 待办

| # | 事项 | 状态 |
|---|---|---|
| L1 | `SRS R-19` 要求 `approval.json` 含 `red_slots_sha256` | ❌ **未实现**：实际只有 `fingerprint: {文件名: "size:mtime"}`，全库零处 `sha256`。属实质缺口（内容变了而 size/mtime 没变就查不出来），**待决定是否本期补** |
| L3 | 待裁决 13 号：两维度结论不一致时预测章以谁为准 | 待裁 |
| L4 | #11 已定口径确认人＝卜彤，须当面知会馆员 | 待做 |
| — | `src/agent/heal.py`（M3 自愈）、`audit.py` + `rules/repair_rules.yaml` | 未开工，**需先由人工手写验收标准** |
| — | M4b 学院统计（`src/college_stats.py`，即 F34） | 已顺延 v2.0（赛后） |
| — | M6 公网部署 | 未开工 |
| — | `out/_archive/`（M4 期次归档） | 未开工 |

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
