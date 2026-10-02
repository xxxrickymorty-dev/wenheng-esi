/* 馆员话术的**唯一来源**：任务十态 / 签单三态 / 取数与核验 / 审计 × 错误提示。
   词表出处：GLOSSARY.md；UX.md 第十节。
   页面一律从这里取词：状态用 `taskLabel`/`approvalLabel`/`acqGroupLabel`/…，
   HTTP 失败用 `errorNote`，站内视图链接用 `appHref`——不许再各写一份 Record 或三目。 */

import { buildPeriodUrl } from './period'

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

/* ---------------------------------------------------------------- 取数与核验 */

/** 取数组的状态（server/acquisition_state.py 的组级状态）。 */
export const ACQ_GROUP_LABEL: Record<string, string> = {
  pending: '未开始',
  live: '进行中',
  done: '核验通过',
  fail: '有未通过',
  retrying: '重新核验中',
}

/** 取数单文件的状态。 */
export const ACQ_FILE_LABEL: Record<string, string> = {
  pending: '待取数',
  received: '已收到 · 待核验',
  ok: '核验通过',
  bad: '未通过',
}

/** 审计留痕的三种核对结果。 */
export const AUDIT_LABEL: Record<string, string> = {
  pass: '通过',
  review: '待确认',
  fail: '不通过',
}

export function acqGroupLabel(state?: string | null): string {
  if (!state) return '—'
  return ACQ_GROUP_LABEL[state] ?? state
}

export function acqFileLabel(state?: string | null): string {
  if (!state) return '—'
  return ACQ_FILE_LABEL[state] ?? state
}

/* ---------------------------------------------------------------- 错误提示 */

/** 只取形状，不 import api 层：任何带 status/body/message 的失败都能喂进来。 */
type Httpish = {
  status?: number
  body?: { error?: string; hint?: string } | null
  message?: string
}

export interface ErrorNoteOpts {
  /** 404 的自定义说法（默认「这一期还没有{what}（可能尚未出稿）。」）。 */
  n404?: string
  /** 409 的自定义说法；`body.error` 优先于它。 */
  n409?: string
}

/**
 * HTTP 失败 → 馆员话术（唯一口径）。
 * 401/403 标准说法；404 先看 `body.hint`；409 先看 `body.error`；
 * 其余取 `body.error → message → 读取{what}失败。`。
 */
export function errorNote(e: unknown, what: string, opts: ErrorNoteOpts = {}): string {
  const err = (e ?? {}) as Httpish
  const body = err.body ?? null
  const detail = body?.error || err.message || ''
  switch (err.status) {
    case 401:
      return `需要登录才能看${what}。`
    case 403:
      return `${what}需要管理员权限（用馆员账号登录后再来）。`
    case 404:
      return body?.hint || opts.n404 || `这一期还没有${what}（可能尚未出稿）。`
    case 409:
      return detail || opts.n409 || '服务端拒绝了这次操作，可能有一个任务还在跑。'
    default:
      return detail || `读取${what}失败。`
  }
}

/* ---------------------------------------------------------------- 站内链接 */

/** 站内视图链接（写入当期）：`/app/?view=workbench&period=202607`。 */
export function appHref(view: string, period: string): string {
  return buildPeriodUrl(`/app/?view=${view}`, period)
}
