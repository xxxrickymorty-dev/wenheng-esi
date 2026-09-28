# 前端纯逻辑测试接入 vitest：给 tdd 一个落点

- **状态**：已接受（2026-09-28，rick 确认；mattpocock 技能链适配）
- **依据**：`docs/specs/2026-09-28-地基与信息减负.md`；`web/UX.md` 第十节

## 背景

技能链（grill-with-docs → … → implement 内嵌 tdd）要求"先红后绿"的测试落点。
`web/`（React + Vite）目前**没有任何测试框架**（devDeps 只有 vite/typescript/oxlint），
期次解析、术语/状态映射、禁用词检查这类纯逻辑没有单元测试可写；
UI 行为只能靠 `tools/check_web_app.py`（真浏览器）与静态稿人工审。

## 决定

1. **加 vitest 作为 devDependency**（与 Vite 同栈：零额外构建配置，`npm run test` 即跑）。
2. **范围只到"纯逻辑"**：期次上下文解析/同步、状态与术语映射、禁用词词表与检查等
   **无 DOM 依赖**的模块。**不引 jsdom / 组件渲染测试**——UI 仍以静态稿审 + 真浏览器
   e2e（`tools/check_web_app.py`）验收，避免为测试引入第二套"真相"。
3. 测试与被测模块同目录（`src/lib/xxx.test.ts`），随 `npm run test` 一起跑。
4. 服务器不装 Node（ADR-0001）：vitest 只在开发机跑，不影响 dist 产物与部署。

## 为什么不是别的

- **不用 jest**：与 Vite 两套转换栈，配置成本高、收益为零。
- **不引 jsdom / Testing Library**：组件行为已有真浏览器 e2e；DOM 模拟会让
  "测试里过了、浏览器里挂了"，纯逻辑抽出来单测，正好倒逼"逻辑与渲染分离"。

## 代价（知情接受）

- 前端多一个 devDependency 与 `package-lock.json` 变更；
- 纯逻辑必须**先抽成模块**才测得到——这是期望的架构压力，不是损失。

## 后果

- 前端逻辑票有红绿循环；UI 票验收＝静态稿审过 ＋ e2e 断言；
- spec/票落点见 `docs/agents/issue-tracker.md`；要扩组件测试再立新 ADR。
