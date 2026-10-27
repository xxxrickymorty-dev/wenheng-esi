import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 文衡新前端 · 并行实验（不动契约，随时可能删除）
// 独立端口/基路径，不与 web/ 的 /app/ 挂载混。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  server: {
    host: '127.0.0.1',
    port: 5180, strictPort: false,
    /* 8080 预览壳（wenheng/preview_5180.py）反代 /app 到这里时，HMR 直连 5180，
       不走那条 HTTP 反代（它不转 WebSocket）；直连 5180 浏览时本来就是默认值。 */
    hmr: { host: '127.0.0.1', port: 5180 },
    /* dev 下 /api 与登录转给同一台 FastAPI（登录 cookie 同 host 共享）。
       工作区全量迁入后，壳内 陈列馆(ShelfPage) 还要吃 8080 的陈列馆数据与素材。 */
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/login': 'http://127.0.0.1:8080',
      '/logout': 'http://127.0.0.1:8080',
      '/healthz': 'http://127.0.0.1:8080',
      '/qr.png': 'http://127.0.0.1:8080',
      '^/app/shelf/data\.js$': 'http://127.0.0.1:8080',
      '^/app/shelf/preview\.js$': 'http://127.0.0.1:8080',
      '/app/shelf/assets': 'http://127.0.0.1:8080',
      '/app/shelf/pages.html': 'http://127.0.0.1:8080',
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
