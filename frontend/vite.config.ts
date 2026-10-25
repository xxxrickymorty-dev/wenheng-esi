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
    /* dev 下 /api 转给同一台 FastAPI（登录 cookie 同 host 共享） */
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
