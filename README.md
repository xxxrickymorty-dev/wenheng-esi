# 文衡 wenheng — ESI 学科信息参考自动化流水线

只读台账、确定性计算、母版原地替换。LLM 不在数据路径。

## 目录

- `src/parse_ledger.py` — 监测表 22 sheet 解析（宽表/转置/分组三种布局），断言闸全绿
- `src/compute.py` — 大表 22×11 + 概述数字事实（口径经第 4 期实物反推验证）
- `src/backtest.py` — 回测闸：第 4 期 docx 逐格 diff → 《对照差异报告》
- `src/forecast.py` — 预测模块（方法 B：InCites + 历史差值校准），MAPE 1.26% < 5% 验收线
- `src/charts.py` — 图表库：16 学科 × 6 图（排名/CNCI/发文/被引阈值/顶尖/分区）+ 概览
- `src/fill_docx.py` — 母版原地替换：大表填充 + 图表槽位 + 红色件清单（red_slots.json）
- `src/rerun_history.py` — 历史期次复现（`python src\rerun_history.py 202605`）
- `src/run_pipeline.py` — 一键入口（全链路约 15 秒）
- `tools/verify_report_docx.py` — 报告结构校验（16 学科 × 6 = 96 槽位 + 22 行大表）
- `tools/compare_reports.py` — 原件 vs 生成稿的结构对照（骨架/图表/表格/占位）
- `tests/` — pytest 回归套件，见下文「测试」

> 配套 Agent 技能：`C:\Users\damn\.agents\skills\wenheng-esi-report`（操作流程 + 踩坑清单），
> 新会话直接说「复现第 N 期报告 / 跑当期报告」即可。校验脚本已收编进本仓库 `tools/`。

## 运行

**首次安装依赖（uv）**：

```powershell
uv sync        # 按 pyproject.toml + uv.lock 建 .venv（含演示站依赖）
```

**每期一条命令（自动化入口）**：

```powershell
uv run python src\run_pipeline.py input\<期次>\监测表.xlsx
```

（馆员日常也可直接双击 `一键出报告.bat`，等价于跑最新一期，不依赖 uv。）

自动完成：解析 22 sheet → 机器断言 → 大表 22×11 → 概述数字事实 → 预测回测 → `out/<期次>/run_log.json`。
当期/上期从台账自动检测（以总被引表最后一个有数据的期次为准），新增一期只需把台账放进新目录、跑一次命令。

分模块运行（调试用）：

```powershell
uv run python src\parse_ledger.py   # 输入台账 → out/<期次>/ 规整数据 + meta
uv run python src\compute.py        # 大表+概述（自动定位最新 out/<期次>）
uv run python src\backtest.py       # 金样回测（固定第 4 期）→ 对照差异报告
uv run python src\forecast.py       # 预测回测报告
```

输入契约（v1.0）：唯一输入 = 馆员维护的《云大全学科排名、阈值动态检测表.xlsx》，
放入 `input/<期次>/监测表.xlsx`；母版 = 第 5 期 docx（结构金母版，**已入库**）。
数据下载与贴表由有权限馆员完成，agent 不碰。缺台账时 parse 步会明确报错，不会静默出空报告。

## 测试

```powershell
uv run pytest            # 默认套件，约 20 秒（跳过端到端）
uv run pytest -m ""      # 含端到端全链路，约 30 秒（会真跑一次流水线）
uv run pytest -m slow    # 只跑端到端
```

| 测试组 | 覆盖什么 | 需要外部数据 |
|---|---|---|
| `test_compute_units` | 大表格式化口径（`139/↓4`、`↑33.87%`）、当期/上期自动检测 | 否 |
| `test_permille_rule` | 1‰ 取位公式 ⌊(m+1)/10⌋、文本单元格转数、与台账已存列逐格对账、与 ThresholdESI 交叉校验 | ESI 原始包 |
| `test_ledger_assertions` | 每期台账断言闸全绿、期次严格递增 | 台账 |
| `test_report_structure` | 报告初稿 96 槽位 + 22 行大表（`tools/verify_report_docx.py`） | `out/` 产物 |
| `test_pipeline_smoke` | parse→compute 主链路、端到端全链路 | 台账 |

外部数据（`input/`、`out/`、ESI 原始包）按 `.gitignore` 不入库，
**缺数据时夹具自动 skip**，不会误报红灯——新 clone 的仓库只会跑纯函数那一层。

> ⚠️ 改 `compute.py` 的口径、`extract_1permille.py` 的取位公式、
> 或母版槽位几何（列宽 8.64 / 图 8.26×5.50）时**先跑测试**。
> 这几处改错了不会抛异常，只会静默产出错的报告。

## 演示站（FastAPI）

```powershell
copy server\.env.example server\.env   # 改账号/密码/公网地址
uv run uvicorn server.app:app --host 0.0.0.0 --port 8080
```

浏览器打开 `http://<服务器IP>:8080`，测试账号登录 → 选期次或上传台账 → 一键生成 →
实时五步进度 + 控制台 → 下载报告初稿/红色件清单/审计数据（SSE 推送，单 worker）。
部署：Linux 装 `fonts-noto-cjk`（图表字体回退），`uv sync` 后可用
`server/deploy/wenheng-demo.service`（systemd，直连 `.venv/bin/python`）。
