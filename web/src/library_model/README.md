# 图书馆建筑模型

`LibraryBuildingModel.tsx` 是独立的 React 组件。它用本地 WebGL 程序绘制低面数建筑；浏览器没有 WebGL 时自动显示矢量示意。没有网络请求、外部贴图或新增 npm 依赖。

```tsx
import LibraryBuildingModel from './library_model/LibraryBuildingModel'

<div style={{ position: 'absolute', inset: 0 }}>
  <LibraryBuildingModel style={{ width: '100%', height: '100%', aspectRatio: 'auto' }} />
</div>
```

默认 `placement="right"`，为入口左侧标题和按钮留空间。小范围拖动、左右方向键可转动；`interactive={false}` 可禁用交互，`placement="center"` 用于单独陈列。组件背景透明，文字由外层页面叠放。桌面入口在模型与文字间建议加一层 `linear-gradient(90deg,#233b37 0%,rgba(35,59,55,.95) 22%,transparent 53%)`；窄屏改成从上往下的同色渐变，保证标题可读。模型是参考用户给出的视觉资料创作的建筑意象，不代表真实馆舍的精确测绘。

静态审核稿使用 `library-building-static.svg`：将文件中的 `<svg>…</svg>` 整段复制进单文件 HTML，设置 `width:100%; height:100%`，即可双击离线打开。将 SVG 放在文字后方并加上述渐变，窄屏时将 SVG 移至文字下方。它与组件无 WebGL 时的构图一致：双塔、红砖两翼、穹顶、玻璃大厅、柱廊和台阶。正式页面通过审核后再接入上方组件。
