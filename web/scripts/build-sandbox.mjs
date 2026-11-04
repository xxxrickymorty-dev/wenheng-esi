// 沙箱构建用（2026-11-04）：vite 加载任何配置文件都要 spawn 子进程打包，
// 沙箱下 spawn EPERM —— 本脚本直接走 vite JS API（configFile:false），
// 不读配置文件、不 spawn。内容与 vite.config.ts 逐项一致；改主配置时同步这里。
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const WEB_ROOT = fileURLToPath(new URL('../', import.meta.url))

await build({
  configFile: false,
  root: WEB_ROOT,
  base: '/app/',
  plugins: [react()],
  build: {
    rolldownOptions: {
      input: {
        workspace: resolve(WEB_ROOT, 'index.html'),
        shelf: resolve(WEB_ROOT, 'shelf/index.html'),
        dialog: resolve(WEB_ROOT, 'dialog/index.html'),
        panel: resolve(WEB_ROOT, 'panel/index.html'),
        schools: resolve(WEB_ROOT, 'schools/index.html'),
      },
    },
  },
})
