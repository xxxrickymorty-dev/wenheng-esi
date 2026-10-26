/* 本机数据存储只读降级 → 页面常驻告警（ADR-0012 决定 7，纯函数，vitest 直测）。
   后端 `/api/status` 的 `state_db` 只说「现在能不能写」；这里只决定「要不要挂横幅、横幅写哪几句」，
   组件只管把它画出来。

   判定**只认后端明确说的 `degraded: true`**：字段缺失（老服务没有这个字段）、`degraded: false`、
   或形状非法（不是对象 / 不是布尔 true）时一律按正常处理。告警必须是事实，不靠前端猜；
   某次保存真的失败，由那次操作自己的失败提示说清——两处说法不互相顶替。 */

/** 后端没给可用文案时的兜底（与 `server/app.py` 的 STATE_DB_TOO_NEW 同一句，页面不另起说法）。 */
export const READONLY_FALLBACK = '本机数据存储版本比程序新，已进入只读模式，请联系管理员。'

/** 横幅正文（讲人话）：哪些不受影响、哪些会失败、东西丢没丢。 */
export const READONLY_LINES: readonly string[] = [
  '看报告、红件清单、运行档案不受影响。',
  '签单、撤回签单、标记存疑、在线填写后重出报告——这几样现在都会失败。',
  '已经签过、填过的记录都还在，不会丢。',
]

export type StateDbAlert = {
  /** 横幅标题行（后端的人话；缺失或空白时用兜底那句） */
  message: string
  /** 正文行：受影响的动作 + 不受影响的东西 */
  lines: string[]
}

/**
 * `/api/status` 的 `state_db` → 页面告警；不该告警时返回 `null`（组件零渲染）。
 * `raw` 故意收 `unknown`：老服务没有这个字段，或字段被改坏，都不该让整页崩。
 */
export function stateDbAlert(raw: unknown): StateDbAlert | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const sdb = raw as { degraded?: unknown; message?: unknown }
  if (sdb.degraded !== true) return null
  const message = typeof sdb.message === 'string' && sdb.message.trim()
    ? sdb.message.trim()
    : READONLY_FALLBACK
  return { message, lines: [...READONLY_LINES] }
}
