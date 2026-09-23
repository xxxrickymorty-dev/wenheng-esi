import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 后端地址（开发时把 API 与登录转发过去，保持同源 → cookie 直接生效）
const BACKEND = process.env.WENHENG_BACKEND ?? 'http://127.0.0.1:8080'

// https://vite.dev/config/
export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // 契约见 docs/前后端分工与接口契约（2026-09-23）.md §5
      '/api': BACKEND,
      '/login': BACKEND,
      '/logout': BACKEND,
      '/healthz': BACKEND,
    },
  },
})
