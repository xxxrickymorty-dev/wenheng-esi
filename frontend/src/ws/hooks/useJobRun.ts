import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getJob, getJobProgress, getPeriodDetail, getStatus, jobEventsUrl,
} from '../api'
import {
  IDLE_STATE, latestProgress, reduce, restoredJobFor,
  type RunEffect, type RunEvent, type RunState, type TerminalRun,
} from '../lib/runMachine'
import { isTerminal } from '../wb'

export type { Run } from '../lib/runMachine'

export type ActivityState = 'checking' | 'active' | 'idle' | 'unknown'

type UseJobRunOptions = {
  enabled: boolean
  restorePeriod?: string | null
  onActivePeriod?: (period: string) => void
  onTerminal?: (run: TerminalRun) => void
}

/** 管理当前任务的进度：迁移语义全在 `lib/runMachine`（纯测试），
    这里只做事件源（EventSource）、定时器与快照请求。 */
export function useJobRun({ enabled, restorePeriod = null, onActivePeriod, onTerminal }: UseJobRunOptions) {
  const [state, setState] = useState<RunState>(IDLE_STATE)
  const stateRef = useRef<RunState>(IDLE_STATE)
  const [activityState, setActivityState] = useState<ActivityState>('checking')
  const generationRef = useRef(0)
  const sourceRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const snapshotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const snapshotRequestRef = useRef(0)
  const restoreStartedRef = useRef(false)
  const activeCheckDoneRef = useRef(false)
  const activeFoundRef = useRef(false)
  const restoredPeriodRef = useRef<string | null>(null)
  const restorePeriodRef = useRef<string | null>(restorePeriod)
  const connectRef = useRef<(jobId: string, generation: number) => void>(() => {})
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
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
    clearSnapshotTimer()
    snapshotRequestRef.current += 1
  }, [clearSnapshotTimer])

  const isCurrent = useCallback((jobId: string, generation: number) => (
    generationRef.current === generation && stateRef.current.run?.jobId === jobId
  ), [])

  const doSnapshot = useCallback(async (jobId: string, generation: number) => {
    const request = ++snapshotRequestRef.current
    const [jobResult, progressResult] = await Promise.allSettled([
      getJob(jobId), getJobProgress(jobId),
    ])
    if (!isCurrent(jobId, generation) || request !== snapshotRequestRef.current) return
    const job = jobResult.status === 'fulfilled' ? jobResult.value : null
    const progress = progressResult.status === 'fulfilled' ? progressResult.value : null
    dispatchRef.current({
      type: 'snapshot',
      status: job?.status ?? undefined,
      outPeriod: job && typeof job.out_period === 'string' ? job.out_period : undefined,
      last: latestProgress(progress) ?? undefined,
    }, generation)
  }, [isCurrent])

  const runEffect = useCallback((effect: RunEffect, generation: number) => {
    const jobId = stateRef.current.run?.jobId
    if (effect.type === 'stop') { clearTransport(); return }
    if (!jobId) return
    switch (effect.type) {
      case 'open':
        connectRef.current(jobId, generation)
        break
      case 'snapshot':
        if (effect.delay <= 0) { void doSnapshot(jobId, generation); break }
        snapshotTimerRef.current = setTimeout(() => {
          snapshotTimerRef.current = null
          void doSnapshot(jobId, generation)
        }, effect.delay)
        break
      case 'reconnect':
        timerRef.current = setTimeout(() => {
          timerRef.current = null
          connectRef.current(jobId, generation)
        }, effect.delay)
        break
      case 'poll':
        timerRef.current = setTimeout(() => {
          timerRef.current = null
          void doSnapshot(jobId, generation)
        }, effect.delay)
        break
      case 'terminal':
        changeActivity('idle')
        callbacksRef.current.onTerminal?.(effect.run)
        break
    }
  }, [changeActivity, clearTransport, doSnapshot])

  const dispatch = useCallback((event: RunEvent, generation: number) => {
    if (generationRef.current !== generation) return
    const before = stateRef.current
    const { state: next, effects } = reduce(before, event)
    if (next !== before) {
      stateRef.current = next
      setState(next)
    }
    for (const effect of effects) runEffect(effect, generation)
  }, [runEffect])
  const dispatchRef = useRef(dispatch)
  useEffect(() => { dispatchRef.current = dispatch }, [dispatch])

  const connect = useCallback((jobId: string, generation: number) => {
    if (!isCurrent(jobId, generation)) return
    let source: EventSource
    try {
      source = new EventSource(jobEventsUrl(jobId))
    } catch {
      dispatchRef.current({ type: 'disconnect' }, generation)
      return
    }
    sourceRef.current = source
    source.onopen = () => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      snapshotRequestRef.current += 1
      clearSnapshotTimer()
      dispatchRef.current({ type: 'opened' }, generation)
    }

    source.addEventListener('progress', (event) => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      snapshotRequestRef.current += 1
      dispatchRef.current({ type: 'sse-progress', data: (event as MessageEvent<string>).data }, generation)
    })
    source.addEventListener('log', (event) => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      dispatchRef.current({ type: 'sse-log', data: (event as MessageEvent<string>).data }, generation)
    })
    source.addEventListener('status', (event) => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      snapshotRequestRef.current += 1
      dispatchRef.current({ type: 'sse-status', data: (event as MessageEvent<string>).data }, generation)
    })
    source.onerror = () => {
      if (sourceRef.current !== source || !isCurrent(jobId, generation)) return
      clearSnapshotTimer()
      snapshotRequestRef.current += 1
      source.close()
      sourceRef.current = null
      dispatchRef.current({ type: 'disconnect' }, generation)
    }
  }, [clearSnapshotTimer, isCurrent])

  useEffect(() => { connectRef.current = connect }, [connect])

  const attach = useCallback((jobId: string, requestedPeriod: string, initialStatus?: string) => {
    if (!enabledRef.current) return
    generationRef.current += 1
    const generation = generationRef.current
    clearTransport()
    changeActivity(isTerminal(initialStatus) ? 'idle' : 'active')
    dispatchRef.current({ type: 'attach', jobId, requestedPeriod, initialStatus }, generation)
  }, [changeActivity, clearTransport])

  const restoreLastJob = useCallback(async (period: string | null) => {
    if (!enabledRef.current || activeFoundRef.current || stateRef.current.run || !period
      || restoredPeriodRef.current === period) return
    const startingGeneration = generationRef.current
    restoredPeriodRef.current = period
    try {
      const detail = await getPeriodDetail(period)
      const jobId = detail?.lastJob?.id
      if (!jobId || !enabledRef.current || activeFoundRef.current || generationRef.current !== startingGeneration) return
      const job = await getJob(jobId)
      if (!enabledRef.current || activeFoundRef.current || generationRef.current !== startingGeneration) return
      const restored = restoredJobFor(detail, job, period)
      if (!restored) return
      attach(restored.jobId, restored.requestedPeriod, restored.status)
    } catch {
      /* 旧任务信息不可用时，不影响继续查看期次。 */
    }
  }, [attach])

  useEffect(() => {
    if (!enabled) {
      generationRef.current += 1
      stateRef.current = IDLE_STATE
      setState(IDLE_STATE)
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
        const stateResp = await getStatus()
        if (cancelled || generationRef.current !== startingGeneration) return
        if (!Object.prototype.hasOwnProperty.call(stateResp, 'active')) {
          changeActivity('unknown')
          return
        }
        if (stateResp.active === null) {
          changeActivity('idle')
          activeCheckDoneRef.current = true
          void restoreLastJob(restorePeriodRef.current)
          return
        }
        if (typeof stateResp.active !== 'string' || !stateResp.active) {
          changeActivity('unknown')
          return
        }
        activeFoundRef.current = true
        changeActivity('active')
        const job = await getJob(stateResp.active)
        if (cancelled || generationRef.current !== startingGeneration) return
        if (typeof job.period !== 'string' || !job.period) {
          changeActivity('unknown')
          return
        }
        callbacksRef.current.onActivePeriod?.(job.period)
        attach(stateResp.active, job.period, job.status)
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
    stateRef.current = IDLE_STATE
    clearTransport()
  }, [clearTransport])

  const visibleRun = enabled ? state.run : null
  return { run: visibleRun, attach, activity: enabled ? activityState : 'checking' }
}
