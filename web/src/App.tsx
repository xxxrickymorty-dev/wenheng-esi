/* 文衡 · 工作台（外壳）
   两种角色（2026-10-11）：admin＝管理员（全可见可写）；operator＝操作员（评委，只读）——
   下载数据/台账/运行档案/红件/溯源对操作员不可见，写动作一律拦住（真门在后端）。
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
import { forecastAppliedDiffs, forecastAppliedStale, sameForecastChoice, savedForecastChoice } from './lib/forecast'
import { errorNote } from './lib/status'
import { wireEnter } from './lib/motion'
import { pickRunForPeriod } from './lib/run'
import { UserChip } from './lib/UserChip'
import { useJobRun, type Run } from './hooks/useJobRun'
import { Icon, Sprite } from './icons'
import { Acquire } from './Acquire'
import { Pick } from './Pick'
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
type Palette = 'blue' | 'green'
const PALETTE_STORAGE_KEY = 'wenheng-palette'

function initialPalette(): Palette {
  try {
    const v = localStorage.getItem(PALETTE_STORAGE_KEY)
    if (v === 'green' || v === 'blue') return v
    return v === 'zhu' ? 'green' : 'blue'
  } catch {
    return 'blue'
  }
}

export default function App() {
  const [palette, setPalette] = useState<Palette>(initialPalette)
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
  /** 步骤条细线的「画入」一帧：挂载后下一帧点亮 → 细线从零画到当前步（reduced-motion 直接终态） */
  const [railDrawn, setRailDrawn] = useState(false)
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

  /* 按周期请求一份新的选模记录（loading 占位 → 由下方 effect 拉取）。
     重出完成后用它刷新「上次出稿实际用的选择」，让「报告还是旧的」提示及时消失。 */
  const requestForecastChoice = useCallback((period: string) => {
    forecastChoiceRequestRef.current[period] = (forecastChoiceRequestRef.current[period] ?? 0) + 1
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [period]: {
        loaded: false, loading: false, saving: false, error: '',
        choice: {}, saved: {}, by: '', at: '', applied: null,
      },
    }))
  }, [])

  useEffect(() => () => { periodsRequestRef.current += 1 }, [])

  useEffect(() => {
    /* 预测模型设置两种角色都读（操作员看已保存的选择；保存按钮只给管理员）。 */
    if (roleKnown && me) void refreshForecastMeta()
  }, [me, refreshForecastMeta, roleKnown])

  /* ?period= 深链：从老站迁移过来的等价地址（老站 /p/<期次> → 新站 ?view=report&period=<期次>） */
  const wantPeriod = new URLSearchParams(location.search).get('period')
  const _v = new URLSearchParams(location.search).get('view')
  const view: 'workbench' | 'acquire' | 'pick' | 'report' | 'review' | 'ledger' | 'analysis' | 'red' | 'charts' | 'reading' | 'trace' | 'forecast' | 'archive' =
    _v === 'acquire' ? 'acquire'
      : _v === 'pick' ? 'pick'
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

  /* 从预测台「回出报告并重新生成」来的一次性提示（?rerun=1）：生成台把重跑确认态直接打开；
     读完就摘掉参数（刷新不该再弹，确认与否仍由人点）。 */
  const [autoConfirmRerun] = useState(() => new URLSearchParams(location.search).get('rerun') === '1')
  useEffect(() => {
    if (!autoConfirmRerun) return
    const url = new URL(window.location.href)
    url.searchParams.delete('rerun')
    window.history.replaceState(null, '', url.pathname + url.search + url.hash)
  }, [autoConfirmRerun])

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
    for (const period of affectedPeriods) {
      refreshDetail(period)
      /* 重出完成：重新读「上次出稿实际用的选择」——新选择已进报告，提示条随之消失 */
      requestForecastChoice(period)
    }
    setArtifactRefreshByPeriod((current) => {
      const next = { ...current }
      for (const period of affectedPeriods) next[period] = (next[period] ?? 0) + 1
      return next
    })
  }, [refreshDetail, refreshForecastMeta, refreshPeriods, requestForecastChoice])

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
          /* 缺省落在「最近一期已出稿的期次」——开新一期登记的期次虽在列表里（票 05），
             但还没有内容，不该抢走默认落点（否则报告/工作台会去拉不存在的产物）。 */
          const firstWithContent = list.find((p) => p.generated) ?? list[0]
          const chosen = restoredActivePeriodRef.current ?? (hit ? wantPeriod : (firstWithContent?.period ?? null))
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
        choice: {}, saved: {}, by: '', at: '', applied: null,
      },
    }))
    void getForecastChoice(selected).then((record) => {
      if (forecastChoiceRequestRef.current[selected] !== request) return
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [selected]: {
          loaded: true, loading: false, saving: false, error: '',
          choice: record.choice ?? {}, saved: record.choice ?? {}, by: record.by ?? '', at: record.at ?? '',
          applied: record.applied ?? null,
        },
      }))
    }).catch((e) => {
      if (forecastChoiceRequestRef.current[selected] !== request) return
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [selected]: {
          loaded: false, loading: false, saving: false,
          error: errorNote(e, '本期模型设置'),
          choice: {}, saved: {}, by: '', at: '', applied: null,
        },
      }))
    })
  }, [forecastChoiceByPeriod, me?.role, roleKnown, selected])

  const detail = selected ? detailsByPeriod[selected] ?? null : null
  const selectedForecastChoice = selected ? forecastChoiceByPeriod[selected] ?? null : null
  const selectedForecastChoiceDirty = !!(forecastMeta && selectedForecastChoice?.loaded
    && !sameForecastChoice(selectedForecastChoice.choice, selectedForecastChoice.saved, forecastMeta))
  /* 「报告还是旧的」：已保存的选择 ≠ 上次出稿实际用的选择（见 lib/forecast.ts；无快照不猜） */
  const selectedForecastStale = forecastAppliedStale(selectedForecastChoice, forecastMeta)
  const selectedForecastStaleDiffs = selectedForecastStale && selectedForecastChoice && forecastMeta
    ? forecastAppliedDiffs(selectedForecastChoice, forecastMeta)
    : []
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

  /* 动效层接线（taste P4，2026-10-16）：主区一级块入场错峰（首屏内依次 70ms）；
     灵活报告两栏左横右纵各自从本侧进。异步到达的块经 MutationObserver 补接（元素级幂等，
     已接过的不会重放）；接线失败/无 IO 时 m-done 全展示（见 lib/motion.ts）。 */
  useEffect(() => {
    const main = document.querySelector<HTMLElement>('main')
    if (!main) return
    const wireList = () => {
      let i = 0
      for (const el of Array.from(main.children) as HTMLElement[]) {
        if (el.classList.contains('fx-panes')) continue   // 两栏各自从本侧进（下段）
        wireEnter(el, { delayMs: Math.min(i, 8) * 70 })
        i += 1
      }
      document.querySelectorAll<HTMLElement>('.fx-panes > .fx-pane').forEach((el, j) => {
        wireEnter(el, { delayMs: j * 90, side: j === 0 ? 'left' : 'right' })
      })
    }
    wireList()
    const mo = new MutationObserver(() => wireList())
    mo.observe(main, { childList: true })
    return () => mo.disconnect()
  }, [view, selected])

  /* 步骤条细线画入：挂载后下一帧点亮（一次；reduced-motion 时 CSS 停过渡＝直接终态） */
  useEffect(() => {
    const id = window.requestAnimationFrame(() => setRailDrawn(true))
    return () => window.cancelAnimationFrame(id)
  }, [])

  /* 按周期请求一份新的选模记录（loading 占位 → 由上方 effect 拉取）。
     重出完成后用它刷新「上次出稿实际用的选择」，让「报告还是旧的」提示及时消失。 */
  function reloadForecastChoice() {
    if (selected) requestForecastChoice(selected)
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
          applied: readback.applied ?? null,
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
     下载数据台、台账、运行档案、红件清单、逐格溯源对操作员不可见；其余屏可见但无写按钮。
     2026-10-15 新信息架构（rick 定 A 方案）：**4 主区 + 1 管理** —— 下载数据/审核/预测/红件/图册/对勘/溯源
     不再是平级入口，降为「出报告」四步流水里的步骤或报告的下钻；深链 ?view=… 一律保留。 */
  const NAV: { key: string; label: string; href: string }[] = [
    { key: 'flow', label: '出报告', href: '/app/' },
    { key: 'flexible', label: '灵活报告', href: '/app/?view=analysis' },
    /* 2026-10-19 rick：「报告」入口关闭（只读阅稿屏，日常走 出报告→核验定稿，用不上）——
       页面与深链 ?view=report 保留；子屏（红件/图册/对勘/溯源）的「回报告」链接照旧。 */
    { key: 'ask', label: '问文衡', href: '/app/dialog/' },
  ]
  /* 子屏归到哪个主区（决定顶栏高亮）；report 区已无导航项，子屏顶栏不高亮，属预期 */
  const GROUP: Record<string, string> = {
    workbench: 'flow', acquire: 'flow', pick: 'flow', review: 'flow', forecast: 'flow',
    report: 'report', red: 'report', charts: 'report', reading: 'report', trace: 'report',
    analysis: 'flexible', dialog: 'ask', ledger: 'admin', archive: 'admin',
  }
  /* 「出报告」四步流水（2026-10-19 rick：「选章节」入口关闭——一直空着，核验定稿里已有章节选择）。
     步骤条只在流水屏出现；2026-10-16 二版（rick 拍板）：不画序号——顺序由位置与细线方向表达。
     深链 ?view=pick 保留（页面不删），只是不再有入口。 */
  const FLOW_STEPS: { key: string; label: string; href?: string }[] = [
    { key: 'acquire', label: '取数核验', href: '/app/?view=acquire' },
    { key: 'forecast', label: '预测选模', href: '/app/?view=forecast' },
    { key: 'gen', label: '生成初稿', href: '/app/' },
    { key: 'review', label: '核验定稿', href: '/app/?view=review' },
  ]
  const FLOW_ACTIVE: Record<string, string> = {
    acquire: 'acquire', workbench: 'gen', review: 'review', forecast: 'forecast',
  }
  const isOperator = me?.role === 'operator'
  const notLoggedIn = roleKnown && !me
  /* 未登录按最低待遇：管理入口不渲染（此前 fail-open——401 被当成「角色未知」，管理页照常开） */
  const gated = notLoggedIn
  /* 角色还没确认时，先不渲染只给管理员的块（避免未登录先发出被拒的请求） */
  const noAdminBits = !roleKnown || gated
  /* 操作员不可见的「里子」屏（rick 2026-10-11 定）：直开 URL 给空态，真门在后端。
     2026-10-17 rick：demo 放开取数核验与选章节（后端同批改 @user_route）。 */
  const OPERATOR_DENIED = new Set(['ledger', 'archive', 'red', 'trace'])
  const operatorDenied = !!isOperator && OPERATOR_DENIED.has(view)
  const navHref = (h: string) =>
    (selected
      ? h === '/app/' ? buildPeriodUrl(h, selected)
        : h.startsWith('/app/?') ? buildPeriodUrl(h, selected) : h
      : h)
  const activeNav = GROUP[view] ?? 'flow'
  const inFlow = activeNav === 'flow'
  const flowActive = FLOW_ACTIVE[view] ?? ''
  const flowActiveIdx = Math.max(0, FLOW_STEPS.findIndex((s) => s.key === flowActive))

  return (
    <div className="app-shell">
      <Sprite />
      <a className="skip-link" href="#main">跳到主要内容</a>

      {/* 顶栏（2026-10-17 庚·卷宗）：品牌 / 导航 / 陈列馆 / 配色开关 / 身份；正文自然滚动。 */}
      <header className="app-top">
        <a className="app-brand" href={navHref('/app/')}>
          <b>文衡</b>
          <span>云南大学图书馆 · 学科信息参考</span>
        </a>
        <nav className="app-nav" aria-label="工作区">
          {NAV.map((n) => (
            <a key={n.key} href={navHref(n.href)}
               aria-current={activeNav === n.key ? 'page' : undefined}>
              {n.label}
            </a>
          ))}
          {me?.role === 'admin' && (
            <>
              <span className="app-nav-sep" aria-hidden="true" />
              <a href={navHref('/app/?view=ledger')} aria-current={view === 'ledger' ? 'page' : undefined}>
                主台账
              </a>
              <a href={navHref('/app/?view=archive')} aria-current={view === 'archive' ? 'page' : undefined}>
                运行档案
              </a>
            </>
          )}
        </nav>
        <div className="app-side">
          {/* 期次是全局控件（2026-10-17 冗余收敛稿③）：从报告屏印记链升到顶栏，各屏同一份 */}
          {periods.length > 0 && (
            <label className="app-period">期次
              <select value={selected ?? ''} onChange={(e) => pickPeriod(e.target.value)} aria-label="切换期次">
                {periods.map((p) => <option key={p.period} value={p.period}>{p.period}</option>)}
                {selected && !periods.some((p) => p.period === selected) && <option value={selected}>{selected}</option>}
              </select>
            </label>
          )}
          {/* 陈列馆＝给人看的「展示面」，不在工作区里——顶栏给一个离开工作区的入口（2026-10-15） */}
          <a className="app-jump" href="/app/shelf/" title="陈列馆（成品）">
            陈列馆 <Icon name="arrow" size={14} />
          </a>
          {/* 皮肤开关：与对话页同款（2026-10-12）；默认云大绿 */}
          <span className="skin-switch" role="group" aria-label="切换配色">
            <button type="button" aria-pressed={palette === 'blue'} onClick={() => setPalette('blue')}>蓝场</button>
            <button type="button" aria-pressed={palette === 'green'} onClick={() => setPalette('green')}>绿场</button>
          </span>
          {me ? <UserChip me={me} /> : (
            <span className="user-chip" aria-live="polite">
              <span className="user-chip-btn" aria-disabled="true">
                <span className="av">？</span>
                <span className="user-chip-name">{roleKnown ? '未登录' : '角色确认中…'}</span>
              </span>
            </span>
          )}
        </div>
      </header>

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

        {/* 「出报告」五步流水步骤条（2026-10-16 二版 rick 拍板；2026-10-17 五站五屏）：一条 2px 细线（含当前步）
            ＋ 五张等大方角卡片；不画序号——顺序由位置与细线方向表达（仍是真顺序的 ol）。只在流水屏出现。 */}
        {inFlow && roleKnown && !notLoggedIn && !operatorDenied && (
          <nav className="ia-steps" aria-label="出报告步骤">
            <div className="ia-rail" aria-hidden="true">
              {FLOW_STEPS.map((s, i) => (
                <i key={s.key}
                   className={`ia-rail-seg${railDrawn && i <= flowActiveIdx ? ' on' : ''}`} />
              ))}
            </div>
            <ol className="ia-steps-list">
              {FLOW_STEPS.map((s, i) => {
                const on = s.key === flowActive
                /* 2026-10-17 rick：demo 放开取数核验与选章节——五卡全员可点（后端同批改 @user_route）。 */
                const cls = `ia-card${i < flowActiveIdx ? ' done' : ''}${on ? ' now' : ''}`
                return (
                  <li key={s.key} className={cls}>
                    {s.href ? (
                      <a href={navHref(s.href)} aria-current={on ? 'step' : undefined}>{s.label}</a>
                    ) : (
                      <span title="还没做：从某期报告里勾选章节加进初稿（.scratch/ia-rework 票 06，待设计）">
                        {s.label} · 即将
                      </span>
                    )}
                  </li>
                )
              })}
            </ol>
          </nav>
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
            <b>操作员不可见</b> —— 这一屏在「管理」里（下载数据 / 台账 / 运行档案 / 红件 / 溯源），
            操作员账号看不到。看报告请回 <a href={navHref('/app/?view=report')}>报告</a>。
          </div>
        ) : view === 'archive' ? (
          <Archive period={selected} approvalStatus={approvalStatus} />
        ) : view === 'pick' ? (
          <Pick period={selected} />
        ) : view === 'acquire' ? (
          <Acquire period={selected} onOpenPeriod={pickPeriod} />
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
          <Report periods={periods} current={selected} guest={noAdminBits}
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
                        forecastChoice={selectedForecastChoice}
                        forecastAppliedStale={selectedForecastStale}
                        forecastAppliedDiffs={selectedForecastStaleDiffs}
                        autoConfirmRerun={autoConfirmRerun}
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

        {busy && <p className="hint mt-14">正在提交生成请求……</p>}
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
  )
}
