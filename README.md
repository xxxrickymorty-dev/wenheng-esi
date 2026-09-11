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

> 配套 Agent 技能：`C:\Users\damn\.agents\skills\wenheng-esi-report`（操作流程 + 踩坑清单 + 结构验证脚本），
> 新会话直接说「复现第 N 期报告 / 跑当期报告」即可。

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
放入 `input/<期次>/监测表.xlsx`；母版 = 第 5 期 docx（结构金母版）。
数据下载与贴表由有权限馆员完成，agent 不碰。

## 演示站（FastAPI）

```powershell
copy server\.env.example server\.env   # 改账号/密码/公网地址
uv run uvicorn server.app:app --host 0.0.0.0 --port 8080
```

浏览器打开 `http://<服务器IP>:8080`，测试账号登录 → 选期次或上传台账 → 一键生成 →
实时五步进度 + 控制台 → 下载报告初稿/红色件清单/审计数据（SSE 推送，单 worker）。
部署：Linux 装 `fonts-noto-cjk`（图表字体回退），`uv sync` 后可用
`server/deploy/wenheng-demo.service`（systemd，直连 `.venv/bin/python`）。
