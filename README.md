# 文衡 wenheng — ESI 学科信息参考自动化流水线

只读台账、确定性计算、母版原地替换。LLM 不在数据路径。

## 目录

- `src/parse_ledger.py` — 监测表 22 sheet 解析（宽表/转置/分组三种布局），断言闸全绿
- `src/compute.py` — 大表 22×11 + 概述数字事实（口径经第 4 期实物反推验证）
- `src/backtest.py` — 回测闸：第 4 期 docx 逐格 diff → 《对照差异报告》
- `src/forecast.py` — 预测模块（方法 B：InCites + 历史差值校准），MAPE 1.26% < 5% 验收线

## 运行

```powershell
.venv\Scripts\python.exe src\parse_ledger.py  # 输入台账 → out/<期次>/ 规整数据 + meta
.venv\Scripts\python.exe src\compute.py
.venv\Scripts\python.exe src\backtest.py      # 对照差异报告
.venv\Scripts\python.exe src\forecast.py      # 预测回测报告
```

输入契约（v1.0）：唯一输入 = 馆员维护的《云大全学科排名、阈值动态检测表.xlsx》，
放入 `input/<期次>/监测表.xlsx`；母版 = 第 5 期 docx（结构金母版）。
数据下载与贴表由有权限馆员完成，agent 不碰。
