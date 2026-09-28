/* 任务状态与签单状态 → 馆员话术的**唯一映射**（票 04）。
   词表出处：CONTEXT.md「界面用语」；UX.md 第十节。
   UI 一律 `import { taskLabel } from '../lib/status'`，不许再各写一份 Record。 */

/** 后端任务十态（src/agent/states.py 的权威集合，顺序即生命周期顺序）。 */
export const TASK_STATES = [
  'pending', 'running', 'retrying', 'stalled', 'waiting_approval',
  'completed', 'warned', 'escalated', 'failed', 'cancelled',
] as const
export type TaskState = (typeof TASK_STATES)[number]

/** 十态 → 馆员话术（唯一映射）。 */
export const TASK_LABEL: Record<TaskState, string> = {
  pending: '待运行',
  running: '运行中',
  retrying: '自动修复中',
  stalled: '已停住',
  waiting_approval: '待签单',
  completed: '已完成',
  warned: '已完成（有提醒）',
  escalated: '需人工接手',
  failed: '失败',
  cancelled: '已取消',
}

/** 终态集合（与后端一致：进入后不自动迁移）。 */
export const TERMINAL_STATES: readonly TaskState[] = [
  'completed', 'warned', 'escalated', 'failed', 'cancelled',
]

export function isTaskState(value: unknown): value is TaskState {
  return typeof value === 'string' && (TASK_STATES as readonly string[]).includes(value)
}

export function isTerminalState(status?: string): boolean {
  return !!status && (TERMINAL_STATES as readonly string[]).includes(status)
}

/** 任务状态 → 话术；未知非空值原样返回（不编），空值给「—」。 */
export function taskLabel(status?: string | null): string {
  if (!status) return '—'
  return isTaskState(status) ? TASK_LABEL[status] : status
}

/** 签单三态（后端 approval：unsigned / signed / stale）。 */
export const APPROVAL_STATES = ['unsigned', 'signed', 'stale'] as const
export type ApprovalState = (typeof APPROVAL_STATES)[number]

export const APPROVAL_LABEL: Record<ApprovalState, string> = {
  unsigned: '未签发',
  signed: '已签发',
  stale: '签名已失效',
}

export function isApprovalState(value: unknown): value is ApprovalState {
  return typeof value === 'string' && (APPROVAL_STATES as readonly string[]).includes(value)
}

export function approvalLabel(status?: string | null): string {
  if (!status) return '—'
  return isApprovalState(status) ? APPROVAL_LABEL[status] : status
}
