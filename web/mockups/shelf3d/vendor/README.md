# vendor/page-flip.browser.js

`page-flip`（StPageFlip）2.0.7 的浏览器构建，**只取 `dist/js/page-flip.browser.js` 这一个文件**。

| 项 | 值 |
|---|---|
| 来源 | npm 包 `page-flip` / 仓库 `Nodlik/StPageFlip` |
| 许可 | **MIT**（全文在 `page-flip.LICENSE.txt`，保留版权头） |
| 体积 | 44 KB，零运行时依赖，UMD 挂到全局 `St` |
| 用途 | 翻书态的 2D 翻页 |

## 拿到手时审过什么（2026-09-22）

- 构建产物里 `eval` / `Function(` / `fetch` / `XMLHttpRequest` / `WebSocket` / `localStorage` / `http(s)://` —— **出现次数全部为 0**。纯渲染库，不联网、不碰存储。
- 许可证是 MIT，不是「未声明许可」（那是保留所有权利，不能用）。
- npm 包里还带 `src/`、`video.gif`（9 MB）等，**一概不取**。

## 两个已知的坑（改它容器里的东西之前先看）

1. **`destroy()` 会把挂载的宿主元素一起从 DOM 摘掉**（源码里是 `this.block.remove()`）。
   之后再碰宿主会抛异常——如果这句落在状态机收尾里，界面会卡死在中间态。
   → 开卷时**重建宿主**，收尾一律 `try/catch` 兜底。
2. **样式表里有 `.stf__parent canvas { position:absolute; width:100%; height:100% }`**，
   选择器是「容器内所有 canvas」。页内要放 canvas（图表）必须用更高特异性压回去。
