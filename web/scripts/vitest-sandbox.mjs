// 沙箱跑 vitest 用（2026-11-04）：vitest 加载 vite.config.ts 要 spawn，沙箱 EPERM。
// 直接走 vitest JS API（configFile:false）；默认环境由各测试文件的
// @vitest-environment 注释自行声明（仓库现状即如此）。
import { fileURLToPath } from 'node:url'
import { startVitest } from 'vitest/node'

const ok = await startVitest('test', process.argv.slice(2), {
  configFile: false,
  root: fileURLToPath(new URL('../', import.meta.url)),
})
process.exitCode = ok ? 0 : 1
