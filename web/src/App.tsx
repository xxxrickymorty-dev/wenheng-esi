/* 文衡 · 工作台（外壳）
   一个应用两屏：工作台（工具面，本文件）→ 陈列馆（G 的体验，挂在 /app/shelf/）。
   数据全部来自后端 API；接口没就绪的地方**如实标注"未就绪"**，不编数据。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getHealth, getMe, getPeriodDetail, getPeriods, postJob,
  type ApiError, type Me, type Period, type PeriodDetail,
} from './api'
import {
  getForecastChoice, getForecastMeta, saveForecastChoice,
  type ForecastChoiceEntry, type ForecastMeta,
} from './api5'
import { useJobRun, type Run } from './hooks/useJobRun'
import { Icon, Sprite } from './icons'
import { Workbench } from './Workbench'
import { Report } from './Report'
import { Review } from './Review'
import { Ledger } from './Ledger'
import { Analysis } from './Analysis'
import { RedList } from './RedList'
import { Charts } from './Charts'
import { Reading } from './Reading'
import { Trace } from './Trace'
import { Tools } from './Tools'
import { Forecast } from './Forecast'
import { Archive } from './Archive'
import { deriveWorkbench, statusToWB, type WBState } from './wb'

const DEMO_STATES: WBState[] = ['empty', 'ready', 'running', 'done', 'warned', 'waiting-approval', 'fail-ledger', 'fail-other', 'stalled', 'signed']

function sameForecastChoice(
  left: Record<string, Record<string, string>>,
  right: Record<string, Record<string, string>>,
  meta: ForecastMeta,
): boolean {
  return meta.routes.every((route) => meta.subjects.every((subject) =>
    (left[route.value]?.[subject] ?? '') === (right[route.value]?.[subject] ?? '')))
}

function savedForecastChoice(
  choice: Record<string, Record<string, string>>,
  meta: ForecastMeta,
): Record<string, Record<string, string>> {
  const result: Record<string, Record<string, string>> = {}
  for (const route of meta.routes) {
    const bySubject: Record<string, string> = {}
    for (const subject of meta.subjects) {
      const model = choice[route.value]?.[subject]
      if (model) bySubject[subject] = model
    }
    result[route.value] = bySubject
  }
  return result
}

export default function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  /* 角色是否已有结论：false = 还没问过（探活失败 / 首屏）；true = 问过了（me 为 null 即未登录） */
  const [roleKnown, setRoleKnown] = useState(false)
  const [periods, setPeriods] = useState<Period[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [urlRestorePeriod, setUrlRestorePeriod] = useState<string | null>(null)
  const [detailsByPeriod, setDetailsByPeriod] = useState<Record<string, PeriodDetail | null>>({})
  const [artifactRefreshByPeriod, setArtifactRefreshByPeriod] = useState<Record<string, number>>({})
  const [forecastMeta, setForecastMeta] = useState<ForecastMeta | null>(null)
  const [forecastMetaError, setForecastMetaError] = useState('')
  const [forecastChoiceByPeriod, setForecastChoiceByPeriod] = useState<Record<string, ForecastChoiceEntry>>({})
  const [err, setErr] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const [toolAction, setToolAction] = useState<'upload' | 'rerun' | null>(null)
  const actionOwnerRef = useRef<'generate' | 'upload' | 'rerun' | null>(null)
  const manualSelectionRef = useRef(false)
  const restoredActivePeriodRef = useRef<string | null>(null)
  const periodsRequestRef = useRef(0)
  const detailRequestByPeriodRef = useRef<Record<string, number>>({})
  const forecastChoiceRequestRef = useRef<Record<string, number>>({})

  const refreshPeriods = useCallback(async () => {
    const request = ++periodsRequestRef.current
    const list = await getPeriods()
    if (request !== periodsRequestRef.current) return null
    setPeriods(list)
    return list
  }, [])

  const refreshForecastMeta = useCallback(async () => {
    try {
      const next = await getForecastMeta()
      setForecastMeta(next)
      setForecastMetaError('')
      return next
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setForecastMetaError(h.status === 403
        ? '预测模型设置需要管理员权限。'
        : h.body?.error ?? h.message ?? '暂时读不到模型清单。')
      return null
    }
  }, [])

  const refreshDetail = useCallback((period: string) => {
    const request = (detailRequestByPeriodRef.current[period] ?? 0) + 1
    detailRequestByPeriodRef.current[period] = request
    void getPeriodDetail(period).then((detail) => {
      if (detailRequestByPeriodRef.current[period] !== request) return
      setDetailsByPeriod((current) => ({ ...current, [period]: detail }))
    }).catch(() => {
      if (detailRequestByPeriodRef.current[period] !== request) return
      setDetailsByPeriod((current) => ({ ...current, [period]: null }))
    })
  }, [])

  useEffect(() => () => { periodsRequestRef.current += 1 }, [])

  useEffect(() => {
    if (roleKnown && me?.role === 'admin') void refreshForecastMeta()
  }, [me?.role, refreshForecastMeta, roleKnown])

  /* ?period= 深链：从老站迁移过来的等价地址（老站 /p/<期次> → 新站 ?view=report&period=<期次>） */
  const wantPeriod = new URLSearchParams(location.search).get('period')
  const _v = new URLSearchParams(location.search).get('view')
  const view: 'workbench' | 'report' | 'review' | 'ledger' | 'analysis' | 'red' | 'charts' | 'reading' | 'trace' | 'forecast' | 'archive' =
    _v === 'report' ? 'report'
      : _v === 'review' ? 'review'
        : _v === 'ledger' ? 'ledger'
          : _v === 'analysis' ? 'analysis'
            : _v === 'red' ? 'red'
              : _v === 'charts' ? 'charts'
                : _v === 'reading' ? 'reading'
                  : _v === 'trace' ? 'trace'
                    : _v === 'forecast' ? 'forecast'
                      : _v === 'archive' ? 'archive'
                        : 'workbench'

  const demo = useMemo(() => {
    const v = new URLSearchParams(location.search).get('demo') as WBState | null
    return v && DEMO_STATES.includes(v) ? v : null
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps -- wantPeriod 只在首屏读一次

  const onActivePeriod = useCallback((period: string) => {
    restoredActivePeriodRef.current = period
    if (!manualSelectionRef.current) setSelected(period)
  }, [])

  const onRunTerminal = useCallback((finished: {
    requestedPeriod: string; outputPeriod: string | null
  }) => {
    void refreshPeriods().catch(() => { /* 列表刷新失败不影响过程展示 */ })
    void refreshForecastMeta()
    const affectedPeriods = [...new Set([finished.requestedPeriod, finished.outputPeriod].filter(
      (period): period is string => !!period,
    ))]
    for (const period of affectedPeriods) refreshDetail(period)
    setArtifactRefreshByPeriod((current) => {
      const next = { ...current }
      for (const period of affectedPeriods) next[period] = (next[period] ?? 0) + 1
      return next
    })
  }, [refreshDetail, refreshForecastMeta, refreshPeriods])

  const runEnabled = healthy === true && roleKnown && me?.role === 'admin'
  const { run, attach, activity } = useJobRun({
    enabled: runEnabled,
    restorePeriod: urlRestorePeriod,
    onActivePeriod,
    onTerminal: onRunTerminal,
  })

  function pickPeriod(period: string) {
    manualSelectionRef.current = true
    setSelected(period)
  }

  useEffect(() => {
    let alive = true
    ;(async () => {
      const ok = await getHealth()
      if (!alive) return
      setHealthy(ok)
      if (!ok) return
      const m = await getMe()
      if (!alive) return
      setMe(m)
      setRoleKnown(true)
      try {
        const list = await refreshPeriods()
        if (!alive || !list) return
        const hit = wantPeriod && list.some((p) => p.period === wantPeriod)
        if (hit) setUrlRestorePeriod(wantPeriod)
        if (!manualSelectionRef.current) {
          setSelected(restoredActivePeriodRef.current ?? (hit ? wantPeriod : (list[0]?.period ?? null)))
        }
      } catch (e) {
        if (alive) setErr(e as ApiError)
      }
    })()
    return () => { alive = false }
  }, [refreshPeriods, wantPeriod])

  useEffect(() => {
    if (selected) refreshDetail(selected)
  }, [selected, refreshDetail])

  useEffect(() => {
    if (!roleKnown || me?.role !== 'admin' || !selected) return
    const existing = forecastChoiceByPeriod[selected]
    if (existing?.loaded || existing?.loading || existing?.error) return
    const request = (forecastChoiceRequestRef.current[selected] ?? 0) + 1
    forecastChoiceRequestRef.current[selected] = request
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [selected]: {
        loaded: false, loading: true, saving: false, error: '',
        choice: {}, saved: {}, by: '', at: '',
      },
    }))
    void getForecastChoice(selected).then((record) => {
      if (forecastChoiceRequestRef.current[selected] !== request) return
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [selected]: {
          loaded: true, loading: false, saving: false, error: '',
          choice: record.choice ?? {}, saved: record.choice ?? {}, by: record.by ?? '', at: record.at ?? '',
        },
      }))
    }).catch((e) => {
      if (forecastChoiceRequestRef.current[selected] !== request) return
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [selected]: {
          loaded: false, loading: false, saving: false,
          error: h.status === 403 ? '本期模型设置需要管理员权限。'
            : h.body?.error ?? h.message ?? '暂时读不到本期模型设置。',
          choice: {}, saved: {}, by: '', at: '',
        },
      }))
    })
  }, [forecastChoiceByPeriod, me?.role, roleKnown, selected])

  const detail = selected ? detailsByPeriod[selected] ?? null : null
  const selectedForecastChoice = selected ? forecastChoiceByPeriod[selected] ?? null : null
  const selectedForecastChoiceDirty = !!(forecastMeta && selectedForecastChoice?.loaded
    && !sameForecastChoice(selectedForecastChoice.choice, selectedForecastChoice.saved, forecastMeta))
  const anyForecastChoiceDirty = !!forecastMeta && Object.values(forecastChoiceByPeriod).some((entry) =>
    entry.loaded && !sameForecastChoice(entry.choice, entry.saved, forecastMeta))
  const choiceLoadLockReason = selected && !forecastMeta
    ? forecastMetaError || '正在读取模型清单，读取完成后才能开始生成。'
    : selected && !selectedForecastChoice?.loaded
      ? selectedForecastChoice?.error || '正在读取本期已保存的模型选择，读取完成后才能开始生成。'
      : selectedForecastChoiceDirty
        ? '本期模型选择有未保存修改，请保存并确认成功后再开始生成。'
        : null

  useEffect(() => {
    if (!anyForecastChoiceDirty) return
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeLeaving)
    return () => window.removeEventListener('beforeunload', warnBeforeLeaving)
  }, [anyForecastChoiceDirty])

  function reloadForecastChoice() {
    if (!selected) return
    forecastChoiceRequestRef.current[selected] = (forecastChoiceRequestRef.current[selected] ?? 0) + 1
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [selected]: {
        loaded: false, loading: false, saving: false, error: '',
        choice: {}, saved: {}, by: '', at: '',
      },
    }))
  }

  function changeForecastChoice(route: string, subject: string, model: string) {
    if (!selected || !selectedForecastChoice?.loaded) return
    setForecastChoiceByPeriod((current) => {
      const entry = current[selected]
      if (!entry?.loaded) return current
      return {
        ...current,
        [selected]: {
          ...entry, error: '',
          choice: { ...entry.choice, [route]: { ...(entry.choice[route] ?? {}), [subject]: model } },
        },
      }
    })
  }

  async function saveSelectedForecastChoice() {
    if (!selected || !forecastMeta || !selectedForecastChoice?.loaded || !selectedForecastChoiceDirty) return
    const period = selected
    const entry = selectedForecastChoice
    const payload = savedForecastChoice(entry.choice, forecastMeta)
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [period]: { ...current[period], saving: true, error: '' },
    }))
    try {
      await saveForecastChoice(period, payload)
      const readback = await getForecastChoice(period)
      if (!sameForecastChoice(payload, readback.choice ?? {}, forecastMeta)) {
        throw new Error('保存后确认到的选择与页面不一致，请重试。')
      }
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [period]: {
          loaded: true, loading: false, saving: false, error: '',
          choice: readback.choice ?? {}, saved: readback.choice ?? {},
          by: readback.by ?? '', at: readback.at ?? '',
        },
      }))
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [period]: {
          ...current[period], saving: false,
          error: h.body?.error ?? h.message ?? '保存失败，选择仍未保存。',
        },
      }))
    }
  }
  const runForSelected: Run | null = run?.requestedPeriod === selected ? run : null
  const approvalStatus = periods.find((p) => p.period === selected)?.status ?? 'unsigned'
  const runApprovalStatus = periods.find((p) => p.period === run?.requestedPeriod)?.status ?? 'unsigned'
  const runForWorkbench = run && (run.requestedPeriod === selected || activity === 'active') ? run : null
  const wb0 = deriveWorkbench(selected, periods, detail, healthy === true, demo)
  /* 任务状态独立显示；期次列表仍保留签发状态这一审批事实。 */
  const runState: WBState | null = runForSelected?.status === 'warned'
    ? 'warned'
    : runForSelected?.status === 'completed' && approvalStatus === 'signed'
      ? 'signed'
      : runForSelected?.status
        ? statusToWB(runForSelected.status)
        : null
  const wb = runState
    ? { ...wb0, state: runState }
    : wb0
  const actionLockReason = healthy === false
    ? '服务未连接，生成、上传与重跑暂不能使用。'
    : healthy === null
      ? '正在连接服务，暂不能开始生成、上传或重跑。'
      : activity === 'checking'
      ? '正在确认是否有任务在进行；确认前暂不能生成、上传或重跑。'
      : activity === 'unknown'
        ? '暂时无法确认当前任务状态。为避免重复开始任务，生成、上传与重跑暂不可用；刷新页面后再试。'
      : activity === 'active'
          ? '已有任务正在进行，任务结束后才能开始新的生成、上传或重跑。'
          : busy
            ? '正在生成，请稍候。'
            : toolAction === 'upload'
              ? '正在上传并开始生成，请稍候。'
            : toolAction === 'rerun'
              ? '正在重跑，请稍候。'
              : selected && !/^\d{6}$/.test(selected)
                ? '历史复现期次不能直接新建任务，请选择六位正式期次。'
                : choiceLoadLockReason
  const selectedPeriodCanStartJob = !!selected && /^\d{6}$/.test(selected)
  const jobActionsLocked = !runEnabled || activity !== 'idle' || busy || toolAction !== null
    || !!choiceLoadLockReason || !selectedPeriodCanStartJob

  const beginToolAction = useCallback((action: 'upload' | 'rerun') => {
    if (!runEnabled || activity !== 'idle' || actionOwnerRef.current || jobActionsLocked) return false
    actionOwnerRef.current = action
    setToolAction(action)
    return true
  }, [activity, jobActionsLocked, runEnabled])

  const endToolAction = useCallback((action: 'upload' | 'rerun') => {
    if (actionOwnerRef.current !== action) return
    actionOwnerRef.current = null
    setToolAction(null)
  }, [])

  async function onGenerate() {
    if (!selected || jobActionsLocked || actionOwnerRef.current) return
    const requestedPeriod = selected
    actionOwnerRef.current = 'generate'
    setBusy(true)
    setErr(null)
    try {
      const r = await postJob(requestedPeriod)
      attach(r.job_id, requestedPeriod)
    } catch (e) {
      const h = e as { status?: number; body?: ApiError; message?: string }
      setErr(h.body ?? { error: h.message ?? '生成请求失败' })
    } finally {
      if (actionOwnerRef.current === 'generate') actionOwnerRef.current = null
      setBusy(false)
    }
  }

  /* 工作区导航（契约 §4：前端按 /api/me 的 role 决定显示什么；**真门在后端**，这里只是不打扰）。
     游客只留 报告 / 台账 / 陈列馆 这些「看已出的东西」的屏；管理页直连也挡在这里，给一句人话 + 去处。 */
  const NAV: { view: string; label: string; icon: string; href: string; admin?: boolean }[] = [
    { view: 'workbench', label: '生成台', icon: 'play', href: '/app/', admin: true },
    { view: 'report', label: '报告', icon: 'chart', href: '/app/?view=report' },
    { view: 'review', label: '审核台', icon: 'seal', href: '/app/?view=review', admin: true },
    { view: 'ledger', label: '台账', icon: 'doc', href: '/app/?view=ledger' },
    { view: 'analysis', label: '分析台', icon: 'chart', href: '/app/?view=analysis', admin: true },
    { view: 'forecast', label: '预测台', icon: 'trend', href: '/app/?view=forecast', admin: true },
    { view: 'shelf', label: '陈列馆', icon: 'book', href: '/app/shelf/' },
  ]
  const isGuest = me?.role === 'guest'
  const notLoggedIn = roleKnown && !me
  /* 未登录按游客待遇：管理入口不渲染（此前 fail-open——401 被当成「角色未知」，管理页照常开） */
  const gated = notLoggedIn || isGuest
  /* 角色还没确认时，先不渲染只给管理员的块（避免游客先发出被拒的请求） */
  const noAdminBits = !roleKnown || gated
  /* charts（图册）后端允许 guest 读（契约 §7.1），所以不进这张表 */
  const ADMIN_VIEWS = new Set(['workbench', 'review', 'analysis', 'forecast', 'archive', 'trace', 'red'])
  const denied = gated && ADMIN_VIEWS.has(view)
  const navHref = (h: string) =>
    (selected && h.startsWith('/app/?') ? `${h}&period=${encodeURIComponent(selected)}` : h)

  return (
    <>
      <Sprite />
      <header className="topbar">
        <div className="brand">
          <strong>文衡</strong>
          <span>学科信息参考</span>
        </div>
        <nav className="nav" aria-label="工作区">
          {NAV.filter((n) => !n.admin || !gated).map((n) => (
            <a key={n.view} href={navHref(n.href)}
               aria-current={view === n.view ? 'page' : undefined}>
              <Icon name={n.icon} size={19} />{n.label}
            </a>
          ))}
        </nav>
        <div className="who">
          <span className="avatar">{me?.name?.slice(0, 1) ?? '？'}</span>
          {me?.name ?? (roleKnown ? '未登录' : '角色未知')}
          {me?.role
            ? ` · ${me.role === 'admin' ? '管理员' : '游客'}`
            : notLoggedIn
              ? <> · <a href="/login">去登录</a></>
              : '（未提供 /api/me）'}
        </div>
      </header>

      <main className="wrap">
        {healthy === false && (
          <div className="banner bad" style={{ marginTop: 0 }}>
            <span className="ico"><Icon name="alert" size={22} /></span>
            <span>
              <b className="title">连不上本机服务</b>
              <ul>
                <li>后端没有响应 —— 检查它是否在运行（`/healthz`）。</li>
                <li>下面显示的期次列表可能不完整；你的台账与已出的报告都没有受影响。</li>
              </ul>
            </span>
          </div>
        )}

        {denied ? (
          <div className="pending-box" style={{ marginTop: 0 }}>
            {notLoggedIn ? (
              <><b>请先登录</b> —— 生成台 / 审核台 / 分析台 / 预测台要馆员账号，
                <a href="/login">去登录</a>后再来（游客账号只能看已出的东西）。
              </>
            ) : (
              <><b>这一屏要馆员账号</b> —— 生成台 / 审核台 / 分析台 / 预测台是馆员的工作区，
                你现在是游客身份（只能看已出的东西）。
              </>
            )}
            想看这一期报告去「<a href={navHref('/app/?view=report')}>报告</a>」，
            想按期翻看卷宗去「<a href="/app/shelf/">陈列馆</a>」。
          </div>
        ) : view === 'archive' ? (
          <Archive period={selected} approvalStatus={approvalStatus} />
        ) : view === 'forecast' ? (
          <Forecast
            period={selected}
            periods={periods}
            actualOutputPeriod={run?.outputPeriod ?? null}
            meta={forecastMeta}
            metaError={forecastMetaError}
            choice={selectedForecastChoice}
            choiceDirty={selectedForecastChoiceDirty}
            onPickPeriod={pickPeriod}
            onChoiceChange={changeForecastChoice}
            onSaveChoice={saveSelectedForecastChoice}
            onReloadChoice={reloadForecastChoice}
          />
        ) : view === 'trace' ? (
          <Trace period={selected} />
        ) : view === 'reading' ? (
          <Reading period={selected} />
        ) : view === 'charts' ? (
          <Charts period={selected} />
        ) : view === 'red' ? (
          <RedList period={selected} />
        ) : view === 'analysis' ? (
          <Analysis period={selected} />
        ) : view === 'ledger' ? (
          <Ledger />
        ) : view === 'review' ? (
          <Review
            period={selected}
            me={me}
            periods={periods}
            onChanged={() => { void refreshPeriods().catch(() => { /* 刷新失败不影响操作结果 */ }) }}
          />
        ) : view === 'report' ? (
          <Report periods={periods} current={selected} onPick={pickPeriod} guest={noAdminBits}
            refreshToken={selected ? artifactRefreshByPeriod[selected] ?? 0 : 0} />
        ) : (
          <>
                      <Workbench
                        period={selected}
                        me={me}
                        wb={wb}
                        err={err}
                        healthy={healthy === true}
                        run={runForWorkbench}
                        approvalStatus={approvalStatus}
                        runApprovalStatus={runApprovalStatus}
                        activityState={activity}
                        actionLockReason={actionLockReason}
                        activeRun={activity === 'active'}
                        actionsLocked={jobActionsLocked}
                        submitting={busy}
                        onGenerate={onGenerate}
                        periods={periods}
                        forecastMeta={forecastMeta}
                        forecastMetaError={forecastMetaError}
                        actualOutputPeriod={run?.outputPeriod ?? null}
                        forecastChoice={selectedForecastChoice}
                        forecastChoiceDirty={selectedForecastChoiceDirty}
                        onPickPeriod={pickPeriod}
                        onForecastChoiceChange={changeForecastChoice}
                        onSaveForecastChoice={saveSelectedForecastChoice}
                        onReloadForecastChoice={reloadForecastChoice}
                      />
            {!noAdminBits && <Tools
              period={selected}
              jobId={runForSelected?.jobId ?? null}
              approvalStatus={approvalStatus}
              actionsLocked={jobActionsLocked}
              actionLockReason={actionLockReason}
              onActionStart={beginToolAction}
              onActionEnd={endToolAction}
              onUploaded={(jobId, period) => { pickPeriod(period); attach(jobId, period) }}
              refreshToken={selected ? artifactRefreshByPeriod[selected] ?? 0 : 0}
            />}
          </>
        )}

        <a className="entry" href="/app/shelf/">
          <span>
            <span className="t">陈列馆 · 历期卷宗</span>
            <span className="d">按期翻看已出刊的报告（书架 → 端详 → 开卷）</span>
          </span>
          <span className="go" aria-hidden="true">→</span>
        </a>

        {view === 'workbench' && (
        <section className="card tablewrap" style={{ marginTop: 18 }}>
          <table className="periods">
            <thead>
              <tr>
                <th>期次</th><th>目录名</th><th>状态</th><th style={{ width: 90 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {periods.length === 0 && (
                <tr><td colSpan={4} style={{ color: 'var(--ink-3)' }}>
                  {healthy === false ? '服务未启动，读不到期次。' : '暂无期次。'}
                </td></tr>
              )}
              {periods.map((p) => (
                <tr key={p.period}
                    onClick={() => pickPeriod(p.period)}
                    style={{ cursor: 'pointer', background: p.period === selected ? 'var(--panel)' : undefined }}>
                  <td>{p.label}</td>
                  <td className="mono">{p.period}</td>
                  <td>
                    <span className={`pill ${p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'}`}>
                      {p.status === 'signed' ? '已签发' : p.status === 'stale' ? '签名已失效' : '未签发'}
                    </span>
                  </td>
                  <td>
                    <a href={`/app/?view=report&period=${encodeURIComponent(p.period)}`}
                       onClick={(e) => e.stopPropagation()}>打开</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        )}

        <p className="hint" style={{ marginTop: 14 }}>
          {busy && '正在提交生成请求……'}
          {!busy && '演示时想直接看某个状态（空/生成中/失败…）可在网址后加 '}
          {!busy && <code>?demo=fail-ledger</code>}
        </p>
      </main>
    </>
  )
}
