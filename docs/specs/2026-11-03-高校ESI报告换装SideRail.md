# spec：高校 ESI 报告页换装 SideRail（方案 A，rick 裁「a」）

- **状态**：设计定稿（2026-11-03）。两票待落码。纯前端，零后端改动。
- **背景**：`/app/schools/` 是独立整页入口（自含壳），侧栏为静态稿手搓的 `whs-nav`——
  导航词条与 SideRail 逐字一致但机制/观感件缺失（无折叠、无身份行、无齿轮、无 ⓘ）。
  rick 问「为什么不一致」→ 裁方案 A：换装 SideRail，展陈观感保留。
- **关键判断**：SideRail **不加皮肤 prop**——SchoolsPage 渲染在 `.whs-root` 内，
  `--whs-*` 令牌（schools.css:10-24）对挂进来的 SideRail 天然可见；换肤＝schools.css
  里一段 `.whs-root` 作用域的覆盖（调色/字号/焦点色），机制零改动（工程原则 6）。

## 契约（两票）

### 票 1 换装（`web/src/schools/SchoolsPage.tsx` + `schools.css`）

- 删自绘左页块：`whs-l`/`whs-seal`/`whs-bm`/`whs-nav`/`whs-idb`（SchoolsPage.tsx:280-299）
  与 schools.css 对应死段；改挂 `<SideRail active="schools" me={me} roleKnown={roleKnown}
  onSettings={…} middle={…} />`（不传 period——期次在右页报头）。
- `me`/`roleKnown`：SchoolsPage 增 `/api/me` 获取（用 `web/src/api.ts` 现成函数；
  失败/未登录走 roleKnown+me=null 分支，SideRail 自带「未登录」占位）。
- `middle`：现 whs-idb 的「院校 N 所」小字收进 SideRail 中段（whs 皮肤样式），
  院校清单为空时显示「院校清单」。
- `onSettings`：开票 2 的设置 hub（SchoolsPage 增 settingsOpen state）。
- **皮肤覆盖段**（schools.css，`.whs-root` 作用域）：`.app-page-l` 底色 `--whs-deep`、
  品牌字/导航文字 `--whs-ivory*`、当前项与悬停金线 `--whs-seam`、导航字号 13.5px
  （静态稿原值）、折叠把手订口色对齐；**导航图标保留 SideRail 现行样式**（全站一致；
  与静态稿「短横线」的差异是已知取舍，rick 不满意再调）。
- 布局适配：`.whs-spread` 左列宽改由 SideRail 自身宽度驱动（`grid-template-columns:
  auto minmax(0,1fr)` 或等价；SideRail 折叠 64px/拖宽 232–420 机制原样生效），
  `--lw` 若仅此用则一并清理。

### 票 2 设置 hub 进 schools（`ModelPanel.tsx` 样式迁移 + `SchoolsPage.tsx`）

- **mdl-\* 样式迁 index.css**：ModelSettings 的样式现住 dialog 入口私有 css
  （window.css/dialog.css，先 rg 确认落点），schools 入口看不到——把 `mdl-*` 段
  **整体搬进 `index.css`** 并从原文件删除（dialog 入口因引 index.css 照常可用）；
  vitest 照跑防回归。
- SchoolsPage 挂 `<ModelSettings open={settingsOpen} me={me} onClose={…}
  onChanged={() => {}} />`（hub 自拉清单，onChanged 空实现即可）；
  齿轮由票 1 的 SideRail 接线带出；非 admin/未登录照现有 hint 只读。

## 验收与测试

- `cd web && npx vitest run` 全绿（既有 140 例不回归；不强制新增用例）；
- `npm run build` 成功且 `web/dist` 入库；
- `uv run ruff check .` 干净（本票零 python 改动，跑一遍兜底）；
- UI 自查四点（文字描述）：schools 侧栏出现折叠把手/图标导航/身份行/齿轮；
  深绿品牌面观感（--whs-deep/ivory/seam）保持；「院校 N 所」还在；齿轮开设置
  供应商节可读、界面节字体三选生效。

## 范围外

- 右页纸面（站位表/对比/生成）一字不动；预开页文档（loadingDoc/errDoc）不动；
- 期次控件不进侧栏（报头已有）；霞鹜新致宋；e2e（存量 4 失败另案）；
- SideRail 组件 API 零改动；不推送远程。
