/* 文衡 · 工作台（外壳）
   两种角色（2026-10-11）：admin＝管理员（全可见可写）；operator＝操作员（评委，只读）——
   取数/台账/运行档案/红件/溯源对操作员不可见，写动作一律拦住（真门在后端）。
   数据全部来自后端 API；接口没就绪的地方**如实标注"未就绪"**，不编数据。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getHealth, getMe, getPeriodDetail, getPeriods, postJob,
  type ApiError, type Me, type Period, type PeriodDetail,
} from './api'
import {
  getForecastChoice, getForecastMeta, saveForecastChoice,
  type ForecastChoiceEntry, type ForecastMeta,
} from './api-forecast'
import { applyPeriod, buildPeriodUrl } from './lib/period'
import { errorNote } from './lib/status'
import { pickRunForPeriod } from './lib/run'
import { UserChip } from './lib/UserChip'
import { useJobRun, type Run } from './hooks/useJobRun'
import { Icon, Sprite } from './icons'
import { Acquire } from './Acquire'
import { Workbench, PeriodsPanel } from './Workbench'
import { Report } from './Report'
import { Review } from './Review'
import { Ledger } from './Ledger'
import { Analysis } from './Analysis'
import { RedList } from './RedList'
import { Charts } from './Charts'
import { Reading } from './Reading'
import { Trace } from './Trace'
import { Forecast } from './Forecast'
import { Archive } from './Archive'
import { deriveWorkbench, statusToWB, type WBState } from './wb'

const DEMO_STATES: WBState[] = ['empty', 'ready', 'running', 'done', 'warned', 'waiting-approval', 'fail-ledger', 'fail-other', 'stalled', 'signed']
type Palette = 'ynu' | 'zhu'
const PALETTE_STORAGE_KEY = 'wenheng-palette'

function initialPalette(): Palette {
  try {
    return localStorage.getItem(PALETTE_STORAGE_KEY) === 'zhu' ? 'zhu' : 'ynu'
  } catch {
    return 'ynu'
  }
}

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
  const [palette, setPalette] = useState<Palette>(initialPalette)
  /* 窄屏左栏抽屉（2026-10-15）：宽屏无关；<=900px 时用顶栏按钮开合。 */
  const [menuOpen, setMenuOpen] = useState(false)
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
  const [toolAction, setToolAction] = useState<'upload' | 'rerun' | 'rollback' | null>(null)
  const actionOwnerRef = useRef<'generate' | 'upload' | 'rerun' | 'rollback' | null>(null)
  const manualSelectionRef = useRef(false)
  const restoredActivePeriodRef = useRef<string | null>(null)
  const periodsRequestRef = useRef(0)
  const detailRequestByPeriodRef = useRef<Record<string, number>>({})
  const forecastChoiceRequestRef = useRef<Record<string, number>>({})

  useEffect(() => {
    document.documentElement.dataset.palette = palette
    try {
      localStorage.setItem(PALETTE_STORAGE_KEY, palette)
    } catch {
      // 浏览器不允许保存时，当前页面仍可正常切换。
    }
  }, [palette])

  /* 窄屏抽屉：点链接后收起；Esc 关闭（与遮罩点击一致）。 */
  const closeMenu = useCallback(() => setMenuOpen(false), [])
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

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
      setForecastMetaError(errorNote(e, '预测模型设置'))
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
    /* 预测模型设置两种角色都读（操作员看已保存的选择；保存按钮只给管理员）。 */
    if (roleKnown && me) void refreshForecastMeta()
  }, [me, refreshForecastMeta, roleKnown])

  /* ?period= 深链：从老站迁移过来的等价地址（老站 /p/<期次> → 新站 ?view=report&period=<期次>） */
  const wantPeriod = new URLSearchParams(location.search).get('period')
  const _v = new URLSearchParams(location.search).get('view')
  const view: 'workbench' | 'acquire' | 'report' | 'review' | 'ledger' | 'analysis' | 'red' | 'charts' | 'reading' | 'trace' | 'forecast' | 'archive' =
    _v === 'acquire' ? 'acquire'
      : _v === 'report' ? 'report'
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

  /* 2026-10-12：出报告对操作员也开放——runEnabled 只看「服务健康 + 已登录」。 */
  const runEnabled = healthy === true && roleKnown && !!me
  const { run, attach, activity } = useJobRun({
    enabled: runEnabled,
    restorePeriod: urlRestorePeriod,
    onActivePeriod,
    onTerminal: onRunTerminal,
  })

  function pickPeriod(period: string) {
    manualSelectionRef.current = true
    setSelected(period)
    applyPeriod(period)   /* 票 03：期次变更一律写 URL（唯一真相） */
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
      /* 两种角色（管理员/操作员）都进工作区；操作员的可见范围与只读由下方按角色裁剪。
         未登录留在本页（不跳转），由下方 gated 块给「去登录」。 */
      try {
        const list = await refreshPeriods()
        if (!alive || !list) return
        const hit = wantPeriod && list.some((p) => p.period === wantPeriod)
        if (hit) setUrlRestorePeriod(wantPeriod)
        if (!manualSelectionRef.current) {
          const chosen = restoredActivePeriodRef.current ?? (hit ? wantPeriod : (list[0]?.period ?? null))
          setSelected(chosen)
          /* 票 03：URL 是期次的唯一真相——缺省期次也写进地址栏，复制链接/刷新不丢期 */
          if (!hit && chosen) applyPeriod(chosen)
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
    /* 本期已保存的模型选择两种角色都读（操作员只读展示；保存按钮在预测台按角色裁剪）。 */
    if (!roleKnown || !me || !selected) return
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
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [selected]: {
          loaded: false, loading: false, saving: false,
          error: errorNote(e, '本期模型设置'),
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
        ? '本期模型选择有未保存修改——去预测台保存，或在生成台点「放弃修改并重新读取」后再开始生成。'
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
  const runForSelected: Run | null = pickRunForPeriod(run, selected)
  const approvalStatus = periods.find((p) => p.period === selected)?.status ?? 'unsigned'
  /* 票 05：执行条只画同期次的运行；别期在跑由工作台的一行提示说明（A3） */
  const runForWorkbench: Run | null = runForSelected
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
            : toolAction === 'rollback'
              ? '正在回滚到上一版，请稍候。'
              : selected && !/^\d{6}$/.test(selected)
                ? '历史复现期次不能直接新建任务，请选择六位正式期次。'
                : choiceLoadLockReason
  const selectedPeriodCanStartJob = !!selected && /^\d{6}$/.test(selected)
  const jobActionsLocked = !runEnabled || activity !== 'idle' || busy || toolAction !== null
    || !!choiceLoadLockReason || !selectedPeriodCanStartJob

  const beginToolAction = useCallback((action: 'upload' | 'rerun' | 'rollback') => {
    if (!runEnabled || activity !== 'idle' || actionOwnerRef.current || jobActionsLocked) return false
    actionOwnerRef.current = action
    setToolAction(action)
    return true
  }, [activity, jobActionsLocked, runEnabled])

  const endToolAction = useCallback((action: 'upload' | 'rerun' | 'rollback') => {
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
     角色（2026-10-11 改两级）：admin＝管理员（全可见）；operator＝操作员（评委，只读）——
     取数台、台账、运行档案、红件清单、逐格溯源对操作员不可见；其余屏可见但无写按钮。 */
  const NAV: { view: string; label: string; icon: string; href: string; admin?: boolean }[] = [
    { view: 'dialog', label: '对话前门', icon: 'chat', href: '/app/dialog/' },
    { view: 'acquire', label: '取数', icon: 'download', href: '/app/?view=acquire', admin: true },
    { view: 'workbench', label: '生成台', icon: 'play', href: '/app/' },
    { view: 'report', label: '报告', icon: 'chart', href: '/app/?view=report' },
    { view: 'review', label: '审核台', icon: 'seal', href: '/app/?view=review' },
    { view: 'analysis', label: 'AI 分析台', icon: 'chart', href: '/app/?view=analysis' },
    { view: 'forecast', label: '预测台', icon: 'trend', href: '/app/?view=forecast' },
  ]
  const isOperator = me?.role === 'operator'
  const notLoggedIn = roleKnown && !me
  /* 未登录按最低待遇：管理入口不渲染（此前 fail-open——401 被当成「角色未知」，管理页照常开） */
  const gated = notLoggedIn
  /* 角色还没确认时，先不渲染只给管理员的块（避免未登录先发出被拒的请求） */
  const noAdminBits = !roleKnown || gated
  /* 操作员不可见的「里子」屏（rick 2026-10-11 定）：直开 URL 给空态，真门在后端。 */
  const OPERATOR_DENIED = new Set(['acquire', 'ledger', 'archive', 'red', 'trace'])
  const operatorDenied = !!isOperator && OPERATOR_DENIED.has(view)
  const navHref = (h: string) =>
    (selected
      ? h === '/app/' ? buildPeriodUrl(h, selected)
        : h.startsWith('/app/?') ? buildPeriodUrl(h, selected) : h
      : h)
  /* 顶栏标题＝当前屏名（与左栏高亮同源，改一处两边一致） */
  const navLabel = NAV.find((n) => n.view === view)?.label ?? '文衡'

  return (
    <div className="ws-shell">
      <Sprite />
      <a className="skip-link" href="#main">跳到主要内容</a>

      {/* 常驻左栏（2026-10-15）：品牌 / 工作区导航 / 里子入口 / 身份。窄屏变抽屉。 */}
      <aside className={`ws-side${menuOpen ? ' open' : ''}`} id="ws-side" aria-label="工作区导航">
        <div className="ws-brand">
          <strong>文衡</strong>
          <span>云南大学图书馆<br />学科信息参考</span>
        </div>
        <nav className="ws-nav" aria-label="工作区">
          <p className="ws-cap">工作区</p>
          {NAV.filter((n) => !n.admin || me?.role === 'admin').map((n) => (
            <a key={n.view} href={navHref(n.href)} onClick={closeMenu}
               aria-current={view === n.view ? 'page' : undefined}>
              <Icon name={n.icon} size={19} />{n.label}
            </a>
          ))}
          {me?.role === 'admin' && (
            <>
              <p className="ws-cap">里子 · 仅管理员</p>
              <a href={navHref('/app/?view=ledger')} onClick={closeMenu}
                 aria-current={view === 'ledger' ? 'page' : undefined}>
                <Icon name="ledger" size={19} />主台账
              </a>
              <a href={navHref('/app/?view=archive')} onClick={closeMenu}
                 aria-current={view === 'archive' ? 'page' : undefined}>
                <Icon name="archive" size={19} />运行档案
              </a>
            </>
          )}
        </nav>
        <div className="ws-user">
          {me ? <UserChip me={me} /> : (
            <span className="user-chip" aria-live="polite">
              <span className="user-chip-btn" aria-disabled="true">
                <span className="av">？</span>
                <span className="user-chip-name">{roleKnown ? '未登录' : '角色确认中…'}</span>
              </span>
            </span>
          )}
        </div>
      </aside>
      <div className={`ws-overlay${menuOpen ? ' open' : ''}`} onClick={closeMenu} aria-hidden="true" />

      <div className="ws-main">
        <header className="topbar">
          <button type="button" className="ws-menu" onClick={() => setMenuOpen((v) => !v)}
                  aria-label="打开导航" aria-expanded={menuOpen} aria-controls="ws-side">
            <Icon name="menu" size={20} />
          </button>
          <span className="ws-title">{navLabel}</span>
          {/* 皮肤开关：与对话页同款（2026-10-12）；默认云大绿 */}
          <span className="skin-switch ml-auto" role="group" aria-label="切换配色">
            <button type="button" aria-pressed={palette === 'ynu'} onClick={() => setPalette('ynu')}>云大绿</button>
            <button type="button" aria-pressed={palette === 'zhu'} onClick={() => setPalette('zhu')}>朱砂</button>
          </span>
        </header>

        <div className="ws-scroll">
          <main className="wrap" id="main">
        {healthy === false && (
          <div className="banner bad mt-0">
            <span className="ico"><Icon name="alert" size={22} /></span>
            <span>
              <b className="title">连不上本机服务</b>
              <ul>
                <li>后端没有响应 —— 检查它是否在运行。</li>
                <li>下面显示的期次列表可能不完整；你的台账与已出的报告都没有受影响。</li>
              </ul>
            </span>
          </div>
        )}

        {/* 身份未确认：先不渲染任何视图（避免发出注定被拒的请求）；未登录给「去登录」；
            操作员直开隐藏屏给「不可见」空态（真门在后端）。 */}
        {!roleKnown ? (
          <div className="pending-box mt-0">正在确认身份……</div>
        ) : notLoggedIn ? (
          <div className="pending-box mt-0">
            <b>请先登录</b> —— 工作区要登录账号，<a href="/login">去登录</a>后再来。
          </div>
        ) : operatorDenied ? (
          <div className="pending-box mt-0">
            <b>操作员不可见</b> —— 这一屏是管理员的「里子」（取数 / 台账 / 运行档案 / 红件 / 溯源），
            操作员账号看不到。看报告请回 <a href={navHref('/app/?view=report')}>报告</a>。
          </div>
        ) : view === 'archive' ? (
          <Archive period={selected} approvalStatus={approvalStatus} />
        ) : view === 'acquire' ? (
          <Acquire period={selected} />
        ) : view === 'forecast' ? (
          <Forecast
            period={selected}
            meta={forecastMeta}
            metaError={forecastMetaError}
            choice={selectedForecastChoice}
            choiceDirty={selectedForecastChoiceDirty}
            onChoiceChange={changeForecastChoice}
            onSaveChoice={saveSelectedForecastChoice}
            onReloadChoice={reloadForecastChoice}
            canEdit={me?.role === 'admin'}
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
          <Analysis period={selected} canEdit={me?.role === 'admin'} />
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
            canSeeAdminBits={me?.role === 'admin'}
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
                        activityState={activity}
                        actionLockReason={actionLockReason}
                        activeRun={activity === 'active'}
                        actionsLocked={jobActionsLocked}
                        submitting={busy}
                        onGenerate={onGenerate}
                        periods={periods}
                        forecastMeta={forecastMeta}
                        forecastMetaError={forecastMetaError}
                        actualOutputPeriod={busy || toolAction ? null : runForSelected?.outputPeriod ?? null}
                        forecastChoice={selectedForecastChoice}
                        forecastChoiceDirty={selectedForecastChoiceDirty}
                        onPickPeriod={pickPeriod}
                        onReloadForecastChoice={reloadForecastChoice}
                        showTools={!noAdminBits && me?.role === 'admin'}
                        toolJobId={runForSelected?.jobId ?? null}
                        toolArtifactsToken={selected ? artifactRefreshByPeriod[selected] ?? 0 : 0}
                        onToolActionStart={beginToolAction}
                        onToolActionEnd={endToolAction}
                        onToolUploaded={(jobId, period) => { pickPeriod(period); attach(jobId, period) }}
                      />
          </>
        )}

        {view === 'workbench' && (
          <PeriodsPanel periods={periods} selected={selected} healthy={healthy} onPick={pickPeriod} />
        )}

        <p className="hint mt-14">
          {busy && '正在提交生成请求……'}
        </p>
      </main>

      {/* 全局页脚（2026-10-01，rick：形态参考陈列馆）：口径 · 来源 · 只读声明全站唯一一份；
          合规声明（请勿外传）2026-10-14 起放底部行中位（rick：自工作台顶部移入） */}
      <footer className="app-footer" role="contentinfo">
        <div className="inner">
          <div className="cols">
            <div className="f-brand">
              <strong>文衡</strong>
              <span>WENHENG · 学科信息参考</span>
            </div>
            <div className="f-note">
              <b>说明 · 口径、来源与只读声明</b>
              <p>
                ① 数字只来自馆员维护的台账与派生产物，运行期大模型不进入数据路径；
                ② 本系统是只读视图，不修改台账与报告；③ 预测章按「本期已选」的已保存选择执行，未列学科用 V1 推荐；
                ④ 期次与状态以任务记录为准，未签发报告不可下载。来源：期内产物目录 · 运行档案 · 预测选模配置。
              </p>
            </div>
            <nav className="f-nav" aria-label="页脚导航">
              <a href="/app/shelf/">陈列馆</a>
              {me?.role === 'admin' && (
                <>
                  <a href={navHref('/app/?view=ledger')}>主台账</a>
                  <a href={navHref('/app/?view=archive')}>运行档案</a>
                </>
              )}
            </nav>
          </div>
          <div className="f-bottom">
            <span>云南大学图书馆 · 学科信息参考</span>
            <span className="f-claim">分析报告属于内部资料，仅用于参赛，禁止外传。</span>
            <span>会泽百家　至公天下</span>
          </div>
        </div>
      </footer>
        </div>
      </div>
    </div>
  )
}
