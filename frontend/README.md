# 文衡 · 新前端（`frontend/`）

> **并行实验。不动契约。随时可能删除。**
> rick 2026-10-17 定：wenheng 内开新目录、接同一套后端（`/api/*`），
> 栈用**可复用组件库**（React Bits / Tailwind 一类）。
> 所以根 `AGENTS.md` 的「前端只碰 `web/**`」**不必改**——本目录是实验，
> 不进那份《前后端分工与接口契约》。

## 栈（已定）

**React 19 + TypeScript + Vite + Tailwind CSS v4**，组件按 shadcn 模式**复制进仓库**
（不是黑盒依赖）——这就是「可复用组件库」的意思：组件源码在手，改得动、搬得走。

- Tailwind 的 `@theme` 层把设计令牌灌进去，见 `src/index.css`
- 命名：**蓝＝场 → `sea`**，**绿＝器 → `pine`**。语义见下
- React Bits 那类动效件后接（现在零动效，层次全靠字号与色阶）

## 命令

```bash
cd frontend
npm install
npm run dev        # http://localhost:5180
npm run build      # tsc -b && vite build → dist/
npm run typecheck
```

## 目录

```
frontend/
  README.md            ← 本文件
  package.json         ← 工程（实验）
  index.html           ← Vite 入口（React）
  src/
    index.css          ← Tailwind 主题层（令牌在这）
    App.tsx            ← 屏切换
    components/
      shell.tsx        ← TopBar / StatusBand / SectionHead / RelNote / PageFoot
      data.tsx         ← Tag / Button / DataTable / DataPanel / Wrap / Grid2
      devices.tsx      ← FlapDigits / Gauge / Stamp / Seal   ← 四件签名器件
    screens/
      OutReport.tsx    ← 00 枢纽（四件全在）
      AcquireCheck.tsx ← 01 取数核验
      VerifyFinal.tsx  ← 05 核验定稿
  static/              ← 纯 HTML 设计源（不进构建，留作对照与零件目录）
    kit.html           ← 零件目录：每块活摆出来 + 类名 + 组件映射 ★ 先看这份
    index.html / screens/ / css/
```

## 设计分工（写死在主题层）

- **蓝 ＝ 场**（数据 / 时序 / 读数）
- **绿 ＝ 器**（工序 / 戳印 / 签发）
- 红色只作警戒（阈值虚线、复核 PENDING），全站两处以内

## 四件器件按屏落位（不平铺）

| 器件 | 属 | 落在哪 |
|---|---|---|
| ① `FlapDigits` 翻牌数字 | 蓝·场 | 01 / 04 / 06 / 07 |
| ② `Gauge` 水位标尺 | 蓝·场 | 01 / 02 / 03 |
| ③ `Stamp` 橡皮戳 | 绿·器 | 04 落第 2 枚 / 05 落第 3 枚 |
| ④ `Seal` 至公天下钤印 | 绿·器 | 只在 05 的「盖印签单」旁落一次 |

全套在站五收束。

## 用词（全站一份，见《全站-冗余收敛对照稿》定词表）

- **取数**（机器）／**取数核验**（人的步骤）
- **一键生成**（机器）／**生成初稿**（人的步骤）
- **5 站 5 屏**：取数核验 · 选章节 · 预测选模 · 生成初稿 · 核验定稿
- **屏题 ＝ 站名**，不另起名
- 状态词只两套：**任务**（进行中／已完成／未开始）＋ **签发**（未签发／已签发／签发已失效）
- 动作叫 **签单**，状态叫 **签发**；「签名」只指数字签名

## 规矩

1. **不引 CDN**。字体走系统栈或打包，离线能开。
2. **零渐变、零投影、零玻璃、零圆角面板**。层次靠字号与色阶。
3. **细线只用在该物本身的结构上**（牌缝、刻度、戳框、印框、表格线）。
4. **静态样式落类，只有动态值才内联**（宽度、百分比这类来自数据的值）。
5. 面向馆员的文案讲人话，不出技术术语。

## 边界

- **不动契约**：根 `AGENTS.md` 与《前后端分工与接口契约》**都不改**。本目录不进契约。
- **不覆盖测试**：`tests/test_stack_contract.py` 盯 `web/dist`，与本目录无关。
- **随时可删**：整个 `frontend/` 目录可以整体删掉，不影响 `web/`、`server/`、`tests/`。
- **不与 web/ 合流**：`web/` 那边并行会话在把绿蓝落进 React（`63e83e4`），
  本目录是独立实验。两者撞了以 `web/` 为准。

## 下一步

- 剩 5 屏（02 选章节 / 03 预测选模 / 04 生成初稿 / 06 主台账 / 07 问文衡）
- 接 `/api/*` 真数据（现在是版式样例）
- 动效层（可选接 React Bits 一类）
