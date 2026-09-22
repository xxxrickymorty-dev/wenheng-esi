# AGENTS.md — `web/` 工作区系统（前端）

> 文衡新工作区系统的前端工程。**旧站（`../server/` 模板与 static）不在此列**——
> 它继续零框架 / 零构建 / 零 CDN，别把这里的做法带过去。
> 决策依据：`../docs/adr/0001-前端技术栈放开-web工作区系统.md`。

## 技术栈（已定，别换）

React + TypeScript + Vite + Tailwind CSS + GSAP；组件层用 shadcn/ui（组件按需复制进仓库）。
后端是 `../server/`（FastAPI）——本工程**只做视图**：不预测、不换算、不聚合，
任何数字都必须能回溯到后端产物（与旧站同一条红线）。

## 设计纪律：用户思维第一（rick 定调，2026-09-22）

**一切以用户体验为第一性原则。** 每个工作区开工前先读 `UX.md` 并回答它的「四问」；
设计与它冲突时，以**用户任务**为准，不是以后端能力为准。验收时逐条过 `UX.md` 的体验判据。

## 两条交付纪律（rick 定，2026-09-22）

1. **任何前端页面，先出静态 HTML 供 rick 审核**——审核通过再动 React 代码。
   静态稿放 `web/mockups/<页面名>.html`：单文件、双击即开、零依赖（与离线演示件同规格）。
2. **面向馆员的文案与注释一律讲人话**——馆员不懂代码。界面文案、错误提示、**代码注释**
   都不出现技术术语：`run_parse` / 断言 / sha256 / SSE 要翻译成
   「跑哪一步」「数据齐不齐」「文件有没有被改过」「进度实时更新」这类说法。

## 命令（在 `web/` 下）

```powershell
npm run dev      # 开发；需同时起 FastAPI（../.venv/Scripts/python.exe -m uvicorn server.app:app --port 8080）
npm run build    # 构建 → dist/（dist 入库；服务器不装 Node）
npm run lint
```

## 三条硬规则

1. **改完 `src/` 必须 `npm run build` 并提交 `dist/`。**
   忘了构建不会报任何错，演示站会继续跑旧代码。`tests/test_stack_contract.py` 里
   `test_web构建产物不含外链` 盯着 dist 的存在性与自足性。
2. **不引 CDN。** 字体、图标、脚本全部打包进 dist；构建产物里出现 `http(s)://` 外链
   = 断网崩版。
3. **新增接口写进 `../server/app.py`**，必须是 `/api/*`、必须带登录检查
   （`current_user(request)`）、只允许 GET/POST——`tests/test_stack_contract.py` 三条契约钉着。

## 挂载与路径（服务端）

- `/app` → `web/dist`（`server/app.py` 的 StaticFiles 挂载，`html=True`，`check_dir=False`）
- 基路径是 `/app/`（`vite.config.ts` 的 `base`）：前端引资源、写路由都要带它
- `/app/**` 与 `/static/**` 一样强制 `Cache-Control: no-cache`（改了要立刻可见）

## 验证

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_stack_contract.py   # 契约（快）
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" ../tools/check_web_app.py
# ↑ 真实浏览器端到端（登录 → /app 取数 → 渲染 → 零报错），需先起服务；playwright 在系统 Python 里
```

## 汇报纪律

**每次对话都要向 rick 报告本次调用了哪些 skill**（一句话，放开头或结尾）。
