/* 任务运行状态的**纯迁移**（票 05）：SSE 事件 / 快照 / 断线重连 / 轮询的语义只在这里。
   无 DOM 依赖（ADR-0003：纯逻辑测试）；useJobRun 只做事件源与定时器，并执行 effects。
   规则：重连 3 次（800/1600/3200ms）→ 转轮询（1.5× 退避，封顶 12s）；
        终态一次性（同一运行只回调一次）；断线先快照确认，不凭断线判终。 */

import { isTerminalState } from './status'

export type RunConnection = 'snapshot' | 'live' | 'reconnecting' | 'polling'

export type Run = {
  jobId: string
  requestedPeriod: string
  outputPeriod: string | null
  status: string | null
  last: string | null
  lines: string[]
  connection: RunConnection
}

export type TerminalRun = Pick<Run, 'jobId' | 'requestedPeriod' | 'outputPeriod' | 'status'>

export type RunPhase = 'idle' | 'snapshot' | 'live' | 'reconnecting' | 'polling' | 'done'

export type RunState = {
  phase: RunPhase
  run: Run | null
  /** 已发起的重连次数（0＝还没重连过）。 */
  attempt: number
  /** 轮询当前间隔（毫秒）。 */
  pollDelay: number
}

export type RunEvent =
  | { type: 'attach'; jobId: string; requestedPeriod: string; initialStatus?: string | null }
  | { type: 'detach' }
  /** 一次快照请求的结果；失败也发（空对象），由机器决定「连 / 重连 / 轮询」。 */
  | { type: 'snapshot'; status?: string | null; outPeriod?: string | null; last?: string | null }
  /** SSE 连接已建立（onopen）。 */
  | { type: 'opened' }
  | { type: 'sse-progress'; data: string }
  | { type: 'sse-log'; data: string }
  | { type: 'sse-status'; data: string }
  /** SSE 断线（onerror / 构造失败）：先快照确认，再决定重连或转轮询。 */
  | { type: 'disconnect' }

export type RunEffect =
  | { type: 'open'; attempt: number }
  | { type: 'snapshot'; delay: number }
  | { type: 'reconnect'; attempt: number; delay: number }
  | { type: 'poll'; delay: number }
  | { type: 'stop' }
  | { type: 'terminal'; run: TerminalRun }

export const MAX_RECONNECTS = 3
export const RECONNECT_DELAYS = [800, 1600, 3200]
export const MAX_LOG_LINES = 80
export const POLL_INTERVAL_MS = 3000
export const JOB_SNAPSHOT_INTERVAL_MS = 5000

export const IDLE_STATE: RunState = {
  phase: 'idle', run: null, attempt: 0, pollDelay: POLL_INTERVAL_MS,
}

/** SSE 的 progress 行是 JSON；取「哪一步做了什么」的人话，解析不出就原样（不丢信息）。 */
export function humanProgress(line: string): string {
  try {
    const d = JSON.parse(line) as { detail?: unknown; name?: unknown }
    const name = typeof d.name === 'string' ? d.name.trim() : ''
    const detail = typeof d.detail === 'string' ? d.detail.trim() : ''
    if (name && detail) return `${name}：${detail}`
    if (name || detail) return name || detail
  } catch { /* 不是 JSON 就原样显示 */ }
  return line
}

export type ProgressLike = { events?: { detail?: string; name?: string }[] } | null

/** 快照里的进度行 → 一句话（取最后一条；没有就 null，不编）。 */
export function latestProgress(progress: ProgressLike): string | null {
  const events = progress?.events ?? []
  const latest = events[events.length - 1]
  return latest?.detail ?? latest?.name ?? null
}

/** SSE 的 log 行 → `{line}`；不合法返回 null（忽略，不丢别的）。 */
export function logLine(data: string): string | null {
  try {
    const d = JSON.parse(data) as { line?: unknown }
    return typeof d.line === 'string' ? d.line : null
  } catch {
    return null
  }
}

/** SSE 的 status 行 → `{status, outPeriod}`；不合法返回 null。 */
export function statusData(data: string): { status?: string; outPeriod?: string | null } | null {
  try {
    const d = JSON.parse(data) as { status?: unknown; out_period?: unknown }
    const status = typeof d.status === 'string' ? d.status : undefined
    const outPeriod = typeof d.out_period === 'string' ? d.out_period : undefined
    if (!status && !outPeriod) return null
    return { status, outPeriod }
  } catch {
    return null
  }
}

/** 恢复上一个任务的接受规则（重新打开页面时用）：输出期 / 请求期 / 规范请求期 任一吻合。 */
export function restoredJobFor(
  detail: { period?: string; lastJob?: { id?: string } | null } | null,
  job: { id: string; period?: string; out_period?: string; status?: string },
  period: string,
): { jobId: string; requestedPeriod: string; status?: string } | null {
  const canonical = detail?.period ?? period
  const exactOutput = typeof job.out_period === 'string' && job.out_period === period
  const exactRequest = job.period === period
  const canonicalRequest = period === canonical && job.period === canonical
  if (!exactOutput && !exactRequest && !canonicalRequest) return null
  return { jobId: job.id, requestedPeriod: job.period ?? period, status: job.status }
}

function terminalOf(run: Run): TerminalRun {
  return { jobId: run.jobId, requestedPeriod: run.requestedPeriod,
           outputPeriod: run.outputPeriod, status: run.status }
}

function finished(state: RunState, run: Run): { state: RunState; effects: RunEffect[] } {
  return { state: { ...state, phase: 'done', run },
           effects: [{ type: 'stop' }, { type: 'terminal', run: terminalOf(run) }] }
}

export function reduce(state: RunState, event: RunEvent): { state: RunState; effects: RunEffect[] } {
  if (event.type === 'attach') {
    const seeded: Run = {
      jobId: event.jobId, requestedPeriod: event.requestedPeriod, outputPeriod: null,
      status: event.initialStatus ?? null, last: null, lines: [], connection: 'snapshot',
    }
    return { state: { phase: 'snapshot', run: seeded, attempt: 0, pollDelay: POLL_INTERVAL_MS },
             effects: [{ type: 'snapshot', delay: 0 }] }
  }
  if (event.type === 'detach') {
    return { state: IDLE_STATE, effects: [{ type: 'stop' }] }
  }
  const run = state.run
  if (!run || state.phase === 'idle' || state.phase === 'done') {
    return { state, effects: [] }   // 没在跑或已终态：事件一律忽略（终态只回调一次）
  }

  switch (event.type) {
    case 'snapshot': {
      const next: Run = {
        ...run,
        status: event.status ?? run.status,
        outputPeriod: event.outPeriod ?? run.outputPeriod,
        last: event.last ?? run.last,
      }
      if (state.phase === 'snapshot') {
        // 首帧快照不判终（与 attach 当时的行为一致）：开流后由 SSE status 定。
        return { state: { ...state, phase: 'live', run: { ...next, connection: 'live' } },
                 effects: [{ type: 'open', attempt: 0 }] }
      }
      if (isTerminalState(next.status ?? undefined)) return finished(state, next)
      if (state.phase === 'reconnecting') {
        if (state.attempt < MAX_RECONNECTS) {
          const attempt = state.attempt + 1
          return {
            state: { ...state, attempt,
                     run: { ...next, connection: 'reconnecting', lines: [], last: null } },
            effects: [{ type: 'reconnect', attempt, delay: RECONNECT_DELAYS[state.attempt] }],
          }
        }
        return { state: { ...state, phase: 'polling', pollDelay: POLL_INTERVAL_MS,
                          run: { ...next, connection: 'polling' } },
                 effects: [{ type: 'poll', delay: POLL_INTERVAL_MS }] }
      }
      if (state.phase === 'polling') {
        const delay = Math.min(Math.round(state.pollDelay * 1.5), 12000)
        return { state: { ...state, run: next, pollDelay: delay },
                 effects: [{ type: 'poll', delay }] }
      }
      // live：快照循环续期
      return { state: { ...state, run: next },
               effects: [{ type: 'snapshot', delay: JOB_SNAPSHOT_INTERVAL_MS }] }
    }
    case 'opened':
      return { state: { ...state, run: { ...run, connection: 'live' } },
               effects: [{ type: 'snapshot', delay: JOB_SNAPSHOT_INTERVAL_MS }] }
    case 'sse-progress':
      return { state: { ...state, run: { ...run, last: humanProgress(event.data) } }, effects: [] }
    case 'sse-log': {
      const line = logLine(event.data)
      if (line === null) return { state, effects: [] }
      return { state: { ...state,
                        run: { ...run, lines: [...run.lines.slice(-(MAX_LOG_LINES - 1)), line] } },
               effects: [] }
    }
    case 'sse-status': {
      const parsed = statusData(event.data)
      if (!parsed) return { state, effects: [] }
      const next: Run = {
        ...run,
        status: parsed.status ?? run.status,
        outputPeriod: parsed.outPeriod ?? run.outputPeriod,
      }
      if (parsed.status && isTerminalState(parsed.status)) return finished(state, next)
      return { state: { ...state, run: next }, effects: [] }
    }
    case 'disconnect':
      return { state: { ...state, phase: 'reconnecting' },
               effects: [{ type: 'snapshot', delay: 0 }] }
    default:
      return { state, effects: [] }
  }
}
