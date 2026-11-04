// 沙箱跑 vitest 用（2026-11-04）：vitest 加载 vite.config.ts 要 spawn，沙箱 EPERM。
// 直接走 vitest JS API：configFile:false 属 **vite overrides**（startVitest 第 4 参，
// 第 3 参是 vitest 自身 options——放错槽位会被当未知键忽略，config 照旧加载）；
// 池用 threads（默认 forks 池要 spawn node 进程，沙箱同样 EPERM）。
// 默认环境由各测试文件的 @vitest-environment 注释自行声明（仓库现状即如此）。
// include 显式钉在 src/（2026-11-04 票 3）：不依赖 vitest 缺省 glob，
// 不带参数跑就是全量（npm test 同款，不再手动传 src）。
import { fileURLToPath } from 'node:url'
import { startVitest } from 'vitest/node'

const ok = await startVitest('test', process.argv.slice(2), {
  pool: 'threads',
  include: ['src/**/*.{test,spec}.?(c|m)[jt]s?(x)'],
}, {
  configFile: false,
  root: fileURLToPath(new URL('../', import.meta.url)),
})
process.exitCode = ok ? 0 : 1
