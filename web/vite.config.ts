import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// 后端地址（开发时把 API 与登录转发过去，保持同源 → cookie 直接生效）
const BACKEND = process.env.WENHENG_BACKEND ?? 'http://127.0.0.1:8080'
const WEB_ROOT = fileURLToPath(new URL('.', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    proxy: {
      // 契约见 docs/前后端分工与接口契约（2026-09-23）.md §5
      '/api': BACKEND,
      '/login': BACKEND,
      '/logout': BACKEND,
      '/healthz': BACKEND,
      '/qr.png': BACKEND,   // 工具卡「手机上接着看」的二维码（此前未代理，dev 下假 404）
      '^/app/shelf/data\\.js$': BACKEND,
    },
  },
  build: {
    rolldownOptions: {
      input: {
        workspace: resolve(WEB_ROOT, 'index.html'),
        shelf: resolve(WEB_ROOT, 'shelf/index.html'),
      },
    },
  },
})
