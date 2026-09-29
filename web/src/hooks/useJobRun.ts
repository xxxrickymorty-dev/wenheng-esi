import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getJob, getJobProgress, getPeriodDetail, getStatus, jobEventsUrl,
  type Job, type JobProgress,
} from '../api'
import { isTerminal } from '../wb'

export type Run = {
  jobId: string
  requestedPeriod: string
  outputPeriod: string | null
  status: string | null
  last: string | null
  lines: string[]
  connection: 'snapshot' | 'live' | 'reconnecting' | 'polling'
}

export type ActivityState = 'checking' | 'active' | 'idle' | 'unknown'

type TerminalRun = Pick<Run, 'jobId' | 'requestedPeriod' | 'outputPeriod' | 'status'>

type UseJobRunOptions = {
  enabled: boolean
  restorePeriod?: string | null
  onActivePeriod?: (period: string) => void
  onTerminal?: (run: TerminalRun) => void
}

const MAX_RECONNECTS = 3
const RECONNECT_DELAYS = [800, 1600, 3200]
const MAX_LOG_LINES = 80
const POLL_INTERVAL_MS = 3000
const JOB_SNAPSHOT_INTERVAL_MS = 5000

function outputPeriod(job: Job): string | null {
  return typeof job.out_period === 'string' ? job.out_period : null
}

function latestProgress(progress: JobProgress | null): string | null {
  const events = progress?.events ?? []
  const latest = events[events.length - 1]
  return latest?.detail ?? latest?.name ?? null
}

/** SSE 的 progress 行是 JSON；取「哪一步做了什么」的人话，解析不出就原样（不丢信息）。 */
function humanProgress(line: string): string {
  try {
    const d = JSON.parse(line) as { detail?: unknown; name?: unknown }
    const name = typeof d.name === 'string' ? d.name.trim() : ''
    const detail = typeof d.detail === 'string' ? d.detail.trim() : ''
    if (name && detail) return `${name}：${detail}`
    if (name || detail) return name || detail
  } catch { /* 不是 JSON 就原样显示 */ }
  return line
}

/** 管理当前任务的进度；连接中断时继续更新，直到任务结束。 */
export function useJobRun({ enabled, restorePeriod = null, onActivePeriod, onTerminal }: UseJobRunOptions) {
  const [run, setRun] = useState<Run | null>(null)
  const [activityState, setActivityState] = useState<ActivityState>('checking')
  const runRef = useRef<Run | null>(null)
  const generationRef = useRef(0)
  const sourceRef = useRef<EventSource | null>(null)
  const snapshotSourceRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const snapshotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const snapshotRequestRef = useRef(0)
  const terminalRef = useRef<string | null>(null)
  const restoreStartedRef = useRef(false)
  const activeCheckDoneRef = useRef(false)
  const activeFoundRef = useRef(false)
  const restoredPeriodRef = useRef<string | null>(null)
  const restorePeriodRef = useRef<string | null>(restorePeriod)
  const connectRef = useRef<(jobId: string, generation: number, attempt: number) => void>(() => {})
  const disconnectRef = useRef<(jobId: string, generation: number, attempt: number) => void>(() => {})
  const pollRef = useRef<(jobId: string, generation: number, delay?: number) => void>(() => {})
  const refreshSnapshotRef = useRef<(jobId: string, generation: number) => void>(() => {})
  const enabledRef = useRef(enabled)
  const callbacksRef = useRef({ onActivePeriod, onTerminal })
  const changeActivity = useCallback((next: ActivityState) => {
    setActivityState(next)
  }, [])
  useEffect(() => {
    enabledRef.current = enabled
    restorePeriodRef.current = restorePeriod
    callbacksRef.current = { onActivePeriod, onTerminal }
  }, [enabled, onActivePeriod, onTerminal, restorePeriod])

  const clearSnapshotTimer = useCallback(() => {
    if (snapshotTimerRef.current) clearTimeout(snapshotTimerRef.current)
    snapshotTimerRef.current = null
  }, [])

  const clearTransport = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
    snapshotSourceRef.current = null
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
    clearSnapshotTimer()
  }, [clearSnapshotTimer])

  const isCurrent = useCallback((jobId: string, generation: number) => (
    generationRef.current === generation && runRef.current?.jobId === jobId
  ), [])

  const update = useCallback((jobId: string, generation: number, change: (current: Run) => Run) => {
    if (!isCurrent(jobId, generation)) return
    const current = runRef.current
    if (!current) return
    const next = change(current)
    runRef.current = next
    setRun(next)
  }, [isCurrent])

  const finish = useCallback((jobId: string, generation: number, status?: string, outPeriod?: string | null) => {
    if (!isTerminal(status) || !isCurrent(jobId, generation)) return false
    const key = `${generation}:${jobId}`
    if (terminalRef.current === key) return true
    terminalRef.current = key
    snapshotRequestRef.current += 1
    clearTransport()
    changeActivity('idle')
    update(jobId, generation, (current) => ({
      ...current,
      status: status ?? current.status,
      outputPeriod: outPeriod ?? current.outputPeriod,
      connection: current.connection,
    }))
    const current = runRef.current
    if (current) callbacksRef.current.onTerminal?.({
      jobId: current.jobId,
      requestedPeriod: current.requestedPeriod,
      outputPeriod: outPeriod ?? current.outputPeriod,
      status: status ?? current.status,
    })
    return true
  }, [changeActivity, clearTransport, isCurrent, update])

  const snapshot = useCallback(async (
    jobId: string, generation: number, finishOnTerminal = true,
  ): Promise<Job | null> => {
    const request = ++snapshotRequestRef.current
    const [jobResult, progressResult] = await Promise.allSettled([
      getJob(jobId), getJobProgress(jobId),
    ])
    if (!isCurrent(jobId, generation) || request !== snapshotRequestRef.current) return null

    const job = jobResult.status === 'fulfilled' ? jobResult.value : null
    const progress = progressResult.status === 'fulfilled' ? progressResult.value : null
    update(jobId, generation, (current) => ({
      ...current,
      status: job?.status ?? current.status,
      outputPeriod: job ? outputPeriod(job) ?? current.outputPeriod : current.outputPeriod,
      last: latestProgress(progress) ?? current.last,
    }))
    if (finishOnTerminal && job && isTerminal(job.status)) finish(jobId, generation, job.status, outputPeriod(job))
    return job
  }, [finish, isCurrent, update])

  const refreshSnapshot = useCallback((jobId: string, generation: number) => {
    const stream = snapshotSourceRef.current
    if (!stream || sourceRef.current !== stream || !isCurrent(jobId, generation)) return
    const timer = setTimeout(() => {
      if (snapshotTimerRef.current === timer) snapshotTimerRef.current = null
      if (!isCurrent(jobId, generation) || snapshotSourceRef.current !== stream || sourceRef.current !== stream) return
      void snapshot(jobId, generation).then((job) => {
        if (!isCurrent(jobId, generation) || snapshotSourceRef.current !== stream || sourceRef.current !== stream
          || (job && isTerminal(job.status))) return
        refreshSnapshotRef.current(jobId, generation)
      }).catch(() => {
        if (isCurrent(jobId, generation) && snapshotSourceRef.current === stream && sourceRef.current === stream) {
          refreshSnapshotRef.current(jobId, generation)
        }
      })
    }, JOB_SNAPSHOT_INTERVAL_MS)
    snapshotTimerRef.current = timer
  }, [isCurrent, snapshot])

  const poll = useCallback((jobId: string, generation: number, delay = POLL_INTERVAL_MS) => {
    if (!isCurrent(jobId, generation)) return
    update(jobId, generation, (current) => ({ ...current, connection: 'polling' }))
    timerRef.current = setTimeout(async () => {
      timerRef.current = null
      if (!isCurrent(jobId, generation)) return
      const job = await snapshot(jobId, generation)
      if (!isCurrent(jobId, generation) || (job && isTerminal(job.status))) return
      pollRef.current(jobId, generation, Math.min(Math.round(delay * 1.5), 12000))
    }, delay)
  }, [isCurrent, snapshot, update])

  const connect = useCallback((jobId: string, generation: number, attempt: number) => {
    if (!isCurrent(jobId, generation)) return
    update(jobId, generation, (current) => ({
      ...current,
      connection: attempt === 0 ? 'live' : 'reconnecting',
      ...(attempt > 0 ? { lines: [], last: null } : {}),
    }))

    let source: EventSource
    try {
      source = new EventSource(jobEventsUrl(jobId))
    } catch {
      disconnectRef.current(jobId, generation, attempt)
      return
    }
    sourceRef.current = source
    source.onopen = () => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      snapshotSourceRef.current = source
      update(jobId, generation, (current) => ({ ...current, connection: 'live' }))
      snapshotRequestRef.current += 1
      clearSnapshotTimer()
      refreshSnapshotRef.current(jobId, generation)
    }

    source.addEventListener('progress', (event) => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      snapshotRequestRef.current += 1
      const line = (event as MessageEvent<string>).data
      update(jobId, generation, (current) => ({ ...current, last: humanProgress(line) }))
    })
    source.addEventListener('log', (event) => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      try {
        const data = JSON.parse((event as MessageEvent<string>).data) as { line?: string }
        if (typeof data.line !== 'string') return
        const line = data.line
        update(jobId, generation, (current) => ({
          ...current,
          lines: [...current.lines.slice(-(MAX_LOG_LINES - 1)), line],
        }))
      } catch {
        /* 忽略无法识别的进度记录。 */
      }
    })
    source.addEventListener('status', (event) => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      try {
        snapshotRequestRef.current += 1
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          status?: string
          out_period?: string
        }
        update(jobId, generation, (current) => ({
          ...current,
          status: data.status ?? current.status,
          outputPeriod: data.out_period ?? current.outputPeriod,
        }))
        if (isTerminal(data.status)) finish(jobId, generation, data.status, data.out_period)
      } catch {
        /* 忽略不完整的任务状态说明。 */
      }
    })
    source.onerror = () => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      snapshotSourceRef.current = null
      clearSnapshotTimer()
      snapshotRequestRef.current += 1
      source.close()
      sourceRef.current = null
      disconnectRef.current(jobId, generation, attempt)
    }
  }, [clearSnapshotTimer, finish, isCurrent, update])

  const onDisconnect = useCallback(async (jobId: string, generation: number, attempt: number) => {
    if (!isCurrent(jobId, generation)) return
    const job = await snapshot(jobId, generation)
    if (!isCurrent(jobId, generation) || (job && isTerminal(job.status))) return
    if (attempt < MAX_RECONNECTS) {
      update(jobId, generation, (current) => ({ ...current, connection: 'reconnecting', lines: [] }))
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        connectRef.current(jobId, generation, attempt + 1)
      }, RECONNECT_DELAYS[attempt])
      return
    }
    poll(jobId, generation)
  }, [isCurrent, poll, snapshot, update])

  useEffect(() => {
    connectRef.current = connect
    disconnectRef.current = onDisconnect
    pollRef.current = poll
    refreshSnapshotRef.current = refreshSnapshot
  }, [connect, onDisconnect, poll, refreshSnapshot])

  const attach = useCallback((jobId: string, requestedPeriod: string, initialStatus?: string) => {
    if (!enabledRef.current) return
    generationRef.current += 1
    const generation = generationRef.current
    clearTransport()
    terminalRef.current = null
    changeActivity(isTerminal(initialStatus) ? 'idle' : 'active')
    const next: Run = {
      jobId, requestedPeriod, outputPeriod: null, status: initialStatus ?? null,
      last: null, lines: [], connection: 'snapshot',
    }
    runRef.current = next
    setRun(next)
    void snapshot(jobId, generation, false).then(() => {
      if (!isCurrent(jobId, generation)) return
      connect(jobId, generation, 0)
    }).catch(() => {
      if (isCurrent(jobId, generation)) connect(jobId, generation, 0)
    })
  }, [changeActivity, clearTransport, connect, isCurrent, snapshot])

  const restoreLastJob = useCallback(async (period: string | null) => {
    if (!enabledRef.current || activeFoundRef.current || runRef.current || !period || restoredPeriodRef.current === period) return
    const startingGeneration = generationRef.current
    restoredPeriodRef.current = period
    try {
      const detail = await getPeriodDetail(period)
      const jobId = detail?.lastJob?.id
      if (!jobId || !enabledRef.current || activeFoundRef.current || generationRef.current !== startingGeneration) return
      const job = await getJob(jobId)
      if (!enabledRef.current || activeFoundRef.current || generationRef.current !== startingGeneration) return
      const canonical = detail?.period ?? period
      const exactOutput = typeof job.out_period === 'string' && job.out_period === period
      const exactRequest = job.period === period
      const canonicalRequest = period === canonical && job.period === canonical
      if (!exactOutput && !exactRequest && !canonicalRequest) return
      attach(job.id, job.period ?? period, job.status)
    } catch {
      /* 旧任务信息不可用时，不影响继续查看期次。 */
    }
  }, [attach])

  useEffect(() => {
    if (!enabled) {
      generationRef.current += 1
      runRef.current = null
      restoreStartedRef.current = false
      activeCheckDoneRef.current = false
      activeFoundRef.current = false
      restoredPeriodRef.current = null
      clearTransport()
      return
    }
    if (restoreStartedRef.current) return
    restoreStartedRef.current = true
    let cancelled = false
    const startingGeneration = generationRef.current
    void (async () => {
      try {
        const state = await getStatus()
        if (cancelled || generationRef.current !== startingGeneration) {
          return
        }
        if (!Object.prototype.hasOwnProperty.call(state, 'active')) {
          changeActivity('unknown')
          return
        }
        if (state.active === null) {
          changeActivity('idle')
          activeCheckDoneRef.current = true
          void restoreLastJob(restorePeriodRef.current)
          return
        }
        if (typeof state.active !== 'string' || !state.active) {
          changeActivity('unknown')
          return
        }
        activeFoundRef.current = true
        changeActivity('active')
        const job = await getJob(state.active)
        if (cancelled || generationRef.current !== startingGeneration) return
        if (typeof job.period !== 'string' || !job.period) {
          changeActivity('unknown')
          return
        }
        callbacksRef.current.onActivePeriod?.(job.period)
        attach(state.active, job.period, job.status)
      } catch {
        if (!cancelled && generationRef.current === startingGeneration) changeActivity('unknown')
      }
    })()
    return () => {
      cancelled = true
      restoreStartedRef.current = false
    }
  }, [attach, changeActivity, clearTransport, enabled, restoreLastJob])

  useEffect(() => {
    if (enabled && activeCheckDoneRef.current) void restoreLastJob(restorePeriod)
  }, [enabled, restoreLastJob, restorePeriod])

  useEffect(() => () => {
    generationRef.current += 1
    runRef.current = null
    clearTransport()
  }, [clearTransport])

  const visibleRun = enabled ? run : null
  return { run: visibleRun, attach, activity: enabled ? activityState : 'checking' }
}
