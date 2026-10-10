# AGENTS.md — wenheng 代码仓

> 独立 Git 仓库（remote: `xxxrickymorty-dev/wenheng-esi`）。
> 项目背景、跨仓协作与提交纪律见上一级工作区根目录 `AGENTS.md`；本文件自足，单独 clone 也能用。
> 状态板与红线全文在 `CONTEXT.md`；术语（通用语言）在 `GLOSSARY.md`。
> **前后端分工**：`docs/前后端分工与接口契约（2026-09-23）.md` —— 前端只碰 `web/**`，后端只碰 `server/`|`src/`|`tools/`|`tests/`，两边只通过 `/api/*` 说话；改接口要同时改那份文档。

## 常用命令（Windows，一律 `uv run`；⚠ 控制台脚本直呼会撞中文路径 trampoline，Python 工具走 `python -m`）

```powershell
uv run python -m pytest            # 默认套件（跳过 slow）
uv run python -m pytest -m ""      # 全量（含端到端；PowerShell 里空串会丢，用 -m "slow or not slow"）
uv run ruff check .                # lint（致命级，见 pyproject [tool.ruff.lint]）
uv run python tools\doc_counts.py  # 用例数/断言数 ↔ 文档 对齐检查（--write 回写）
```

演示站与验收（先起服务再跑）：

```powershell
uv run python -m uvicorn server.app:app --host 127.0.0.1 --port 8080
uv run python server\e2e_check.py            # 只读断言
uv run python tools\verify_demo_run.py 202607  # 写路径（会重跑当期流水线）
uv run python tools\verify_report_cells.py 202607   # 逐格回读原始源
```

## 提交纪律

- **做完就提交，不要攒**；只 add 自己的文件；提交前看 `git diff` + `git status`。
- 推送绕本机代理 7897（姿势见 `CONTEXT.md`）；失败**不要反复重试**，改 `git bundle` 兜底。
- 打 tag / 部署前跑根目录 `AGENTS.md` 的「交付前验证清单」。

## 硬约束（违反不会报错，只会在评审现场炸）

- **运行期 LLM 不进数据路径**：数字只来自台账，正文由 `src/sentences.py` 出句骨架。
- **台账只读**：禁 openpyxl 存盘改台账（只能 zip 级 XML 替换，改前备份）；运行期有 sha256 护栏。
- **旧站技术栈冻结**：`server/` 模板与 `static/` 继续使用 FastAPI + Jinja2 / 原生 HTML、CSS、JS；零框架 / 零构建 / 零 CDN。`tests/test_stack_contract.py` 的对应约束只适用于旧站。
- **新工作区**：`web/` 使用 React + TypeScript + Vite，经 FastAPI `/api/*` 获取数据；在本机执行 `npm run build` 生成并入库 `web/dist/`，由 FastAPI 挂载到 `/app/`。开发、构建与 UX 遵循 `web/AGENTS.md` 和 `web/UX.md`。
- **`tests/` 下禁止裸 `pytest.skip`**：数据驱动用例一律 `_guard_registry.skip_unless(理由, lambda: 探针)`，
  探针必须可调用；会话收尾会复核（探针说资源在却跳过 = 整个会话判失败）。
- **改口径必跑逐格核验**：`compute.py` 大表口径 / `extract_1permille.py` 取位 / 母版槽位几何，
  改完跑 `tools/verify_report_cells.py`，判据是「报告数字对」而不是「断言全过」。
- **跑流水线验证必须指定临时 out_root**（如 `tmp/_det_check`），否则覆盖 `out/202607`（金标期次 + 演示站首屏依赖）。

## 数据位置（不入库，缺了用例会登记跳过）

- 台账：`../数据与复现/云大全学科排名、阈值动态检测表.xlsx`（唯一事实源）
- 投喂副本：`input/<期次>/监测表.xlsx`；产物：`out/<期次>/`
- ESI 原始包：`../数据与复现/ESI数据/<期次>/`；InCites：`../数据与复现/incites/`
- 人工原件：`../云南大学原报告/`
