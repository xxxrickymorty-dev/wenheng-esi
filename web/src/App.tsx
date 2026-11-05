/* 文衡 · 工作台（外壳）
   两种角色（2026-10-11）：admin＝管理员（全可见可写）；operator＝操作员（评委/馆员）——
   主台账仅管理员；运行档案/红件/溯源/水位/沙盘对操作员只读开放。签单、出稿、取数
   按既有政策对操作员开放（真门在后端，前端不假拦）。
   数据全部来自后端 API；接口没就绪的地方**如实标注"未就绪"**，不编数据。 */

import { useCallback, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { SideRail, useSideRail } from './SideRail'
import {
  getHealth, getMe, getPeriodDetail, getPeriods, getStatus, postJob,
  type ApiError, type Me, type Period, type PeriodDetail,
} from './api'
import {
  getForecastChoice, getForecastMeta, saveForecastChoice,
  type ForecastChoiceEntry, type ForecastMeta,
} from './api-forecast'
import { applyPeriod, buildPeriodUrl } from './lib/period'
import {
  forecastAppliedDiffs, forecastAppliedStale, resolveSubjects, sameForecastChoice,
  sameSubjects, savedForecastChoice,
} from './lib/forecast'
import { errorNote } from './lib/status'
import { stateDbAlert, type StateDbAlert } from './lib/stateDb'
import { wireEnter } from './lib/motion'
import { pickRunForPeriod } from './lib/run'
import { useJobRun, type Run } from './hooks/useJobRun'
import { usePeriodResource } from './hooks/usePeriodResource'
import { Icon, Sprite } from './icons'
import { SealInkDefs } from './StateSeal'
import { Acquire } from './Acquire'
import { Workbench } from './Workbench'
import { Tools } from './Tools'
import { Report } from './Report'
import { Ledger } from './Ledger'
import { AnalysisPage } from './AnalysisPage'
import { RedList } from './RedList'
import { Reading } from './Reading'
import { Trace } from './Trace'
import { Archive } from './Archive'
import { ArchiveLedger } from './ArchiveLedger'
import { Panorama } from './Panorama'
import { HealSandbox } from './HealSandbox'
import { MigrateSandbox } from './MigrateSandbox'
import { deriveWorkbench, isTerminal, statusToWB, type WBState } from './wb'
import { useSettingsCenter } from './dialog/ModelPanel'

/* 39 分册 F：图表三屏懒载。图册/审核台/预测台都经 ChartFigure 拖 echarts 整包（约 1.13MB），
   静态 import 让工作台首屏也背上它；改 React.lazy 分包后 echarts chunk 只在这三屏进入时才拉，
   等待的一两帧落现有降级样式（见下方视图分支的 Suspense）。他校简报 Panel 是独立入口
   /app/panel/（panel/main.tsx 自己拉 ChartFigure），不在工作台首屏图里，不动。 */
const Charts = lazy(() => import('./Charts').then((m) => ({ default: m.Charts })))
const Review = lazy(() => import('./Review').then((m) => ({ default: m.Review })))
const Forecast = lazy(() => import('./Forecast').then((m) => ({ default: m.Forecast })))
/* 懒载帧的兜底（复用 .degraded 诚实态样式，不新造骨架组件） */
const screenFallback = <div className="degraded mt-0">这一屏正在加载……</div>

const DEMO_STATES: WBState[] = ['empty', 'ready', 'running', 'done', 'warned', 'waiting-approval', 'fail-ledger', 'fail-other', 'stalled', 'signed']

/* 39 分册 B：旧「AI 问数」页（?view=aiqa）退役——深链 replace 到问文衡。
   查证（2026-11-03）：Aiqa 仅 App.tsx 一处 import＋一处分支，摘除后无活引用；
   Aiqa.tsx 组件文件暂留仓库（不再被打包），确认无回滚需求后再删。 */
function LegacyRedirect({ to, label }: { to: string; label: string }) {
  useEffect(() => { location.replace(to) }, [to])
  return <div className="pending-box mt-0">这一页已并入{label}，正在带您过去……</div>
}

export default function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  /** 本机数据存储只读降级时的那条常驻告警（正常为 null＝零渲染） */
  const [stateDbWarn, setStateDbWarn] = useState<StateDbAlert | null>(null)
  /* 角色是否已有结论：false = 还没问过（探活失败 / 首屏）；true = 问过了（me 为 null 即未登录） */
  const [roleKnown, setRoleKnown] = useState(false)

  /* 侧栏（与问文衡同一套组件、同一份本地偏好）：宽度 + 完全收回两态，
     拖到最左收回、收回态悬停滑出——交互与状态都在 SideRail（src/SideRail.tsx）。 */
  const rail = useSideRail()
  /* 设置中心（2026-11-04 票 1）：齿轮全站常驻——出报告 / 分析台 / 运行档案等
     工作区每一屏共用这一份接线（齿轮 / Ctrl+, 带出）。 */
  const settings = useSettingsCenter(me)
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

  /* 期次详情：按期分桶缓存 + 按期序号防同期重发（2026-10-25 抽成 usePeriodResource，
     语义与原手写版逐行一致：序号不符的迟到响应丢弃，相符的只写该期自己的桶）。 */
  const { request: refreshDetail } = usePeriodResource(useMemo(() => ({
    load: (period: string) => getPeriodDetail(period),
    onData: (period: string, detail: PeriodDetail | null) =>
      setDetailsByPeriod((current) => ({ ...current, [period]: detail })),
    onError: (period: string) =>
      setDetailsByPeriod((current) => ({ ...current, [period]: null })),
  }), []))

  /* 选模记录：与期次详情同一原语（usePeriodResource）。request 由下方 effect 调；
     invalidate 供「重出完成后作废在途响应、重置占位让 effect 重拉」用——
     与原手写版共享同一个计数器的行为等价。 */
  const { request: loadForecastChoice, invalidate: invalidateForecastChoice } =
    usePeriodResource(useMemo(() => ({
      load: (period: string) => getForecastChoice(period),
      onData: (period: string, record: Awaited<ReturnType<typeof getForecastChoice>>) =>
        setForecastChoiceByPeriod((current) => ({
          ...current,
          [period]: {
            loaded: true, loading: false, saving: false, error: '',
            choice: record.choice ?? {}, saved: record.choice ?? {},
            subjects: record.subjects ?? [], savedSubjects: record.subjects ?? [],
            by: record.by ?? '', at: record.at ?? '',
            applied: record.applied ?? null,
          },
        })),
      onError: (period: string, e: unknown) =>
        setForecastChoiceByPeriod((current) => ({
          ...current,
          [period]: {
            loaded: false, loading: false, saving: false,
            error: errorNote(e, '本期模型设置'),
            choice: {}, saved: {}, subjects: [], savedSubjects: [],
            by: '', at: '', applied: null,
          },
        })),
    }), []))

  /* 按周期请求一份新的选模记录（loading 占位 → 由下方 effect 拉取）。
     重出完成后用它刷新「上次出稿实际用的选择」，让「报告还是旧的」提示及时消失。 */
  const requestForecastChoice = useCallback((period: string) => {
    invalidateForecastChoice(period)
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [period]: {
        loaded: false, loading: false, saving: false, error: '',
        choice: {}, saved: {}, subjects: [], savedSubjects: [], by: '', at: '', applied: null,
      },
    }))
  }, [invalidateForecastChoice])

  useEffect(() => () => { periodsRequestRef.current += 1 }, [])

  useEffect(() => {
    /* 预测模型设置两种角色都读（操作员看已保存的选择；保存按钮只给管理员）。 */
    if (roleKnown && me) void refreshForecastMeta()
  }, [me, refreshForecastMeta, roleKnown])

  /* ?period= 深链：从老站迁移过来的等价地址（老站 /p/<期次> → 新站 ?view=report&period=<期次>） */
  const wantPeriod = new URLSearchParams(location.search).get('period')
  const _v = new URLSearchParams(location.search).get('view')
  /* 运行档案（2026-11-02）：默认是全部期次的留痕总账；`&one=<期次>` 才进那一期详情。
     总账与详情是两屏，用同一个 view 加一个参数区分——不新增导航位。 */
  const archiveOne = new URLSearchParams(location.search).get('one')
  const view: 'workbench' | 'acquire' | 'report' | 'review' | 'ledger' | 'analysis' | 'red' | 'charts' | 'reading' | 'trace' | 'forecast' | 'pano' | 'archive' | 'heal' | 'migrate' | 'aiqa' =
    _v === 'acquire' ? 'acquire'
      /* 39 分册 C：旧「选章节」页退役（四步流水无此步，纯深链孤儿）——落预测选模现行入口 */
      : _v === 'pick' ? 'forecast'
      : _v === 'report' ? 'report'
        : _v === 'review' ? 'review'
          : _v === 'ledger' ? 'ledger'
            : _v === 'analysis' ? 'analysis'
              : _v === 'red' ? 'red'
                : _v === 'charts' ? 'charts'
                  : _v === 'reading' ? 'reading'
                    : _v === 'trace' ? 'trace'
                      : _v === 'forecast' ? 'forecast'
                        : _v === 'pano' ? 'pano'
                          : _v === 'archive' ? 'archive'
                          : _v === 'heal' ? 'heal'
                            : _v === 'migrate' ? 'migrate'
                              : _v === 'aiqa' ? 'aiqa'
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

  /* 39 分册 C：?view=pick 深链已改落预测选模——地址栏同步改写（照 ?rerun=1「读完就摘」同款），
     刷新/复制链接不再带回已退役的 view 值。 */
  const isPickLegacy = _v === 'pick'
  useEffect(() => {
    if (!isPickLegacy) return
    const url = new URL(window.location.href)
    url.searchParams.set('view', 'forecast')
    window.history.replaceState(null, '', url.pathname + url.search + url.hash)
  }, [isPickLegacy])

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

  /* 本机数据存储只读降级（ADR-0012 决定 7）：登录后问一次 /api/status，降级就挂常驻横幅。
     两种角色都看（这是环境故障，不是权限）；读不到就不挂——横幅只报后端明确说的降级，
     某次保存真的失败时，那次操作自己的失败提示照旧说清。 */
  useEffect(() => {
    if (!me) {
      setStateDbWarn(null)
      return
    }
    let alive = true
    void getStatus().then((status) => {
      if (alive) setStateDbWarn(stateDbAlert(status.state_db))
    }).catch(() => { /* 问不到不影响使用（真门在后端） */ })
    return () => { alive = false }
  }, [me])

  useEffect(() => {
    /* 本期已保存的模型选择两种角色都读（操作员只读展示；保存按钮在预测台按角色裁剪）。 */
    if (!roleKnown || !me || !selected) return
    const existing = forecastChoiceByPeriod[selected]
    if (existing?.loaded || existing?.loading || existing?.error) return
    loadForecastChoice(selected)
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [selected]: {
        loaded: false, loading: true, saving: false, error: '',
        choice: {}, saved: {}, subjects: [], savedSubjects: [], by: '', at: '', applied: null,
      },
    }))
  }, [forecastChoiceByPeriod, loadForecastChoice, me?.role, roleKnown, selected])

  const detail = selected ? detailsByPeriod[selected] ?? null : null
  const selectedForecastChoice = selected ? forecastChoiceByPeriod[selected] ?? null : null
  /* 改动判定＝模型选择 + 进报告的两科（2026-11-05）；两科空＝缺省（接近度前二），
     和缺省比不产生「未保存」——否则一进页面就红。 */
  const choiceDirty = (entry: ForecastChoiceEntry) => !!forecastMeta
    && (!sameForecastChoice(entry.choice, entry.saved, forecastMeta)
      || !sameSubjects(resolveSubjects(entry.subjects, forecastMeta),
        resolveSubjects(entry.savedSubjects, forecastMeta)))
  const selectedForecastChoiceDirty = !!(forecastMeta && selectedForecastChoice?.loaded
    && choiceDirty(selectedForecastChoice))
  /* 「报告还是旧的」：已保存的选择 ≠ 上次出稿实际用的选择（见 lib/forecast.ts；无快照不猜） */
  const selectedForecastStale = forecastAppliedStale(selectedForecastChoice, forecastMeta)
  const selectedForecastStaleDiffs = selectedForecastStale && selectedForecastChoice && forecastMeta
    ? forecastAppliedDiffs(selectedForecastChoice, forecastMeta)
    : []
  const anyForecastChoiceDirty = !!forecastMeta && Object.values(forecastChoiceByPeriod).some((entry) =>
    entry.loaded && choiceDirty(entry))
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
        /* 两栏各自从本侧进（下段）；审核台整张报告 5 万像素，按 4% 阈值永远进不了视口，
           以前会把整块卡在 opacity:0——它不做入场，直接显示。 */
        if (el.classList.contains('fx-panes') || el.classList.contains('rv-grid')) continue
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

  /** 改「进报告正文的两科」（顺序＝报告 1/2 号位）。 */
  function changeReportSubjects(subjects: string[]) {
    if (!selected || !selectedForecastChoice?.loaded) return
    setForecastChoiceByPeriod((current) => {
      const entry = current[selected]
      if (!entry?.loaded) return current
      return { ...current, [selected]: { ...entry, error: '', subjects } }
    })
  }

  /** 保存本期选择 → 成功返回 true（重出前要确认真的存进去了）。 */
  async function saveSelectedForecastChoice(): Promise<boolean> {
    if (!selected || !forecastMeta || !selectedForecastChoice?.loaded) return false
    const period = selected
    const entry = selectedForecastChoice
    const payload = savedForecastChoice(entry.choice, forecastMeta)
    const subjects = resolveSubjects(entry.subjects, forecastMeta)
    /* 老记录没有「两科」字段：即使模型没改，也把它写实——报告的两科从此有据可查，
       不再依赖「接近度前二」的缺省推断（2026-11-05）。 */
    if (!choiceDirty(entry) && entry.subjects.length) return true
    setForecastChoiceByPeriod((current) => ({
      ...current,
      [period]: { ...current[period], saving: true, error: '' },
    }))
    try {
      await saveForecastChoice(period, payload, subjects)
      const readback = await getForecastChoice(period)
      if (!sameForecastChoice(payload, readback.choice ?? {}, forecastMeta)
          || !sameSubjects(subjects, readback.subjects ?? [])) {
        throw new Error('保存后确认到的选择与页面不一致，请重试。')
      }
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [period]: {
          loaded: true, loading: false, saving: false, error: '',
          choice: readback.choice ?? {}, saved: readback.choice ?? {},
          subjects: readback.subjects ?? [], savedSubjects: readback.subjects ?? [],
          by: readback.by ?? '', at: readback.at ?? '',
          applied: readback.applied ?? null,
        },
      }))
      return true
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string }; message?: string }
      setForecastChoiceByPeriod((current) => ({
        ...current,
        [period]: {
          ...current[period], saving: false,
          error: h.body?.error ?? h.message ?? '保存失败，选择仍未保存。',
        },
      }))
      return false
    }
  }
  const runForSelected: Run | null = pickRunForPeriod(run, selected)
  const approvalStatus = periods.find((p) => p.period === selected)?.status ?? 'unsigned'
  /* 总期号（第 39 期）——四屏本期头共用；从期次 label 里取，取不到就不写（不编） */
  const issueNo = /第 (\d+) 期/.exec(periods.find((p) => p.period === selected)?.label ?? '')?.[1] ?? ''
  const issueLabel = issueNo ? `第 ${issueNo} 期` : ''
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
  /* 步骤条上的四个真实状态（2026-11-05）：取数看采集计数、预测看保存态、
     生成看产物/任务、核验看签发态。读不到就写「—」，不猜。 */
  const acq = detail?.acquisition
  const flowStatus: Record<string, { text: string; tone: 'ok' | 'wait' | 'warn' }> = {
    acquire: acq?.expected
      ? {
        text: `${acq.verified ?? 0} / ${acq.expected}`,
        tone: (acq.verified ?? 0) >= acq.expected ? 'ok' : 'wait',
      }
      : { text: acq?.started ? '进行中' : '未开始', tone: 'wait' },
    forecast: !selectedForecastChoice?.loaded
      ? { text: '读取中', tone: 'wait' }
      : selectedForecastChoiceDirty
        ? { text: '有改动', tone: 'warn' }
        : { text: '已保存', tone: 'ok' },
    gen: runForSelected?.status === 'running'
      ? { text: '生成中', tone: 'wait' }
      : detail?.steps?.generate
        ? { text: '已完成', tone: 'ok' }
        : { text: '待生成', tone: 'wait' },
    review: approvalStatus === 'signed'
      ? { text: '已签发', tone: 'ok' }
      : approvalStatus === 'stale'
        ? { text: '待重签', tone: 'warn' }
        : { text: '待签', tone: 'wait' },
  }
  const flowStepClass = (key: string, on: boolean) => {
    if (on) return 'ia-card now'
    const tone = flowStatus[key]?.tone
    return `ia-card${tone === 'ok' ? ' done' : tone === 'warn' ? ' done' : ' todo'}`
  }
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

  async function onGenerate(): Promise<boolean> {
    if (!selected || jobActionsLocked || actionOwnerRef.current) return false
    const requestedPeriod = selected
    actionOwnerRef.current = 'generate'
    setBusy(true)
    setErr(null)
    try {
      const r = await postJob(requestedPeriod)
      attach(r.job_id, requestedPeriod)
      return true
    } catch (e) {
      const h = e as { status?: number; body?: ApiError; message?: string }
      setErr(h.body ?? { error: h.message ?? '生成请求失败' })
      return false
    } finally {
      if (actionOwnerRef.current === 'generate') actionOwnerRef.current = null
      setBusy(false)
    }
  }

  /** 预测台「重出报告」：先把改过的选择存进去，再直接开生成任务（2026-11-05）。
      此前是跳到生成台再点一次二次确认——3 秒就缩回去，等于没重出。 */
  async function regenerateReport(): Promise<boolean> {
    if (!selected || jobActionsLocked) return false
    if (!(await saveSelectedForecastChoice())) return false
    return onGenerate()
  }

  /* 工作区导航（契约 §4：前端按 /api/me 的 role 决定显示什么；**真门在后端**，这里只是不打扰）。
     导航六项＋管理组两项在 SideRail（src/SideRail.tsx），工作区与问文衡同一份。
     2026-11-02 rick 定稿（跨页书式：左页导航 / 右页工作面）。
     2026-10-31 撤出的他校简报 / AI 问数不回来（能力已并入高校ESI报告与问文衡）；
     学科分析 2026-11-04 并入分析台（＝学科报告区），不再单列导航项。
     深链 ?view=analysis · /app/panel/ 仍保留（不占导航位）；?view=aiqa 重定向到问文衡（39 分册 B）、
     ?view=pick 重定向到预测选模（39 分册 C）；?view=discipline 落回工作台（学科分析已并入分析台）。 */
  /* 子屏归到哪个主区（决定左栏高亮）；report 区已无导航项，子屏一律归「出报告」，
     因为报告与它的下钻屏都是从四步流水里长出来的；台账/沙盘从运行档案进，跟着它高亮。 */
  const GROUP: Record<string, string> = {
    workbench: 'flow', acquire: 'flow', review: 'flow', forecast: 'flow',
    report: 'flow', red: 'flow', charts: 'flow', reading: 'flow', trace: 'flow',
    analysis: 'analysis', aiqa: 'ask', dialog: 'ask', pano: 'flow',
    archive: 'archive', ledger: 'archive', heal: 'archive', migrate: 'archive',
  }
  /* 「出报告」四步流水（2026-10-19 rick：「选章节」入口关闭——一直空着，核验定稿里已有章节选择）。
     步骤条只在流水屏出现；2026-11-05（rick）：步骤条兼目录——每格带一个真实状态，
     页头不再重复写页名。不画序号之外的装饰：章号在左、页名在中、状态贴右。 */
  const STEP_CN = ['壹', '贰', '叁', '肆']
  const FLOW_STEPS: { key: string; label: string; icon: string; href?: string }[] = [
    { key: 'acquire', label: '取数核验', icon: 'download', href: '/app/?view=acquire' },
    { key: 'forecast', label: '预测选模', icon: 'chart', href: '/app/?view=forecast' },
    { key: 'gen', label: '生成初稿', icon: 'doc', href: '/app/' },
    { key: 'review', label: '核验定稿', icon: 'seal', href: '/app/?view=review' },
  ]
  /* 流程条「进行中」按这一期的真实状态推进（39 分册 C：原 FLOW_ACTIVE 按屏恒映射会说谎——
     已签发期次打开生成台仍点亮第叁步）。未取数亮壹、取数完亮贰、生成中亮叁、生成完未签亮肆；
     已签发四步全「完成态」不亮进行中（activeIdx = 步骤数 → 四卡全落 done、无 now）。
     waiting-approval 的界面口径是「报告已出，等你在审核台签单」（wb.ts FOCUS），归肆。 */
  const FLOW_STEP_BY_STATE: Record<WBState, string | null> = {
    empty: 'acquire',
    ready: 'forecast',
    running: 'gen', stalled: 'gen', 'fail-ledger': 'gen', 'fail-other': 'gen',
    done: 'review', warned: 'review', 'waiting-approval': 'review',
    signed: null,
  }
  const isOperator = me?.role === 'operator'
  const notLoggedIn = roleKnown && !me
  /* 未登录按最低待遇：管理入口不渲染（此前 fail-open——401 被当成「角色未知」，管理页照常开） */
  const gated = notLoggedIn
  /* 角色还没确认时，先不渲染只给管理员的块（避免未登录先发出被拒的请求） */
  const noAdminBits = !roleKnown || gated
  /* 操作员不可见的「里子」屏（rick 2026-10-11 定）：直开 URL 给空态，真门在后端。
     2026-10-17 rick：demo 放开取数核验与选章节（后端同批改 @user_route）。
     2026-10-20 决赛证据面：运行档案 / 逐格溯源 / 红件清单 / 水位 / 沙盘对操作员只读开放；
     原始主台账仍只给管理员；下载口与写动作的真门仍在后端。 */
  /* 2026-10-20：页面可见性也读 /api/me 的 capabilities；老服务没有该字段时退回 ledger 一条。 */
  const caps = me?.capabilities
  const viewDenied = (v: string) => caps ? caps.views?.[v] === false : v === 'ledger'
  const canEdit = caps?.actions?.edit ?? me?.role === 'admin'
  const canSwitchModel = caps?.actions?.switch_model ?? me?.role === 'admin'
  /* 红件/溯源「页面」对操作员开放；红件「产物下载」才看 download。 */
  const canSeeAdminBits = caps?.views?.red ?? !!me
  const canDownloadRedList = caps?.download?.red_list ?? me?.role === 'admin'
  const operatorDenied = !!isOperator && viewDenied(view)
  const navHref = (h: string) =>
    (selected
      ? h === '/app/' ? buildPeriodUrl(h, selected)
        : h.startsWith('/app/?') ? buildPeriodUrl(h, selected) : h
      : h)
  const activeNav = GROUP[view] ?? 'flow'
  /* 步骤条只在四步流水自身的屏上出现（报告/图册/红件等是流水长出来的下钻屏，
     没有「当前第几步」这回事，画一条全是灰的进度线只会误导）。 */
  const inFlow = ['workbench', 'acquire', 'review', 'forecast'].includes(view)
  const flowActive = FLOW_STEP_BY_STATE[wb.state] ?? ''
  const flowActiveIdx = flowActive
    ? Math.max(0, FLOW_STEPS.findIndex((s) => s.key === flowActive))
    : FLOW_STEPS.length   /* 已签发：无进行中步，四步全落「完成态」 */

  return (
    <div className="app-shell" data-view={view} {...rail.rootProps}>
      <Sprite />
      <SealInkDefs />
      <a className="skip-link" href="#main">跳到主要内容</a>

      {/* 左页 · 会泽（跨页书式）：品牌 / 导航 / 管理组 / 期次与身份。
          一屏放全、栏内不滚——所以这里不设 overflow（设了 auto 就会出滚动条，设了 hidden
          又会裁掉 ⓘ 与身份弹层）；靠 clamp 与 44px 行高把总高压在 720px 以内。
          与问文衡同一套组件（src/SideRail.tsx）：拖宽、拖到最左收回、收展合一。 */}
      <SideRail rail={rail} active={activeNav} me={me} roleKnown={roleKnown}
                navHref={navHref} onSettings={settings.show}
                period={{ list: periods, selected, onPick: pickPeriod }} />

      <main className="wrap app-main" id="main">
        {/* 本机数据存储只读降级：常驻、不遮操作（不是 toast，自己不会消失）。
            讲人话：哪些不受影响、哪些会失败、东西丢没丢。 */}
        {stateDbWarn && (
          <div className="banner warn" role="status">
            <span className="ico"><Icon name="alert" size={22} /></span>
            <span>
              <b className="title">{stateDbWarn.message}</b>
              <ul>
                {stateDbWarn.lines.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </span>
          </div>
        )}

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
                /* 2026-10-17 rick：demo 放开取数核验与选章节——四卡全员可点（后端同批改 @user_route）。 */
                const cls = flowStepClass(s.key, on)
                const stat = flowStatus[s.key]
                return (
                  <li key={s.key} className={cls}>
                    {s.href ? (
                      <a href={navHref(s.href)} aria-current={on ? 'step' : undefined}>
                        <Icon name={s.icon} size={16} />
                        <span className="ia-no" aria-hidden="true">{STEP_CN[i]}</span>
                        <span>{s.label}</span>
                        <span className="ia-stat">{stat?.text ?? ''}</span>
                      </a>
                    ) : (
                      <span title="还没做：从某期报告里勾选章节加进初稿（.scratch/ia-rework 票 06，待设计）">
                        <Icon name={s.icon} size={16} />
                        <span className="ia-no" aria-hidden="true">{STEP_CN[i]}</span>
                        <span>{s.label} · 即将</span>
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
            <b>操作员不可见</b> —— 原始主台账仅管理员可用；运行档案、红件清单与逐格溯源
            已对操作员只读开放。看报告请回 <a href={navHref('/app/?view=report')}>报告</a>。
          </div>
        ) : view === 'pano' ? (
          <Panorama
            period={selected}
            periods={periods}
            detail={detail}
            approvalStatus={approvalStatus}
            live={(!!runForSelected && !isTerminal(runForSelected.status ?? undefined)) || wb.state === 'running'}
            liveNote={runForSelected?.last ?? null} />
        ) : view === 'archive' ? (
          archiveOne ? (
          <>
            <p className="al-back">
              <a href="/app/?view=archive">← 回运行档案总账</a>
            </p>
            <Archive period={archiveOne} approvalStatus={approvalStatus} />
            {/* 「这一期的工具」折块（2026-10-24 rick 工作台减负）从生成台迁来：重跑/回滚/上传/
                日志包都是管理向动作，放运行档案页（管理区）正合适，生成台首屏回归极致低密。
                门控沿用生成台原条件（角色已确认且可编辑）；props 原样透传，组件本身未动。 */}
            {!noAdminBits && canEdit && (
              <details className="fold">
                <summary>这一期的工具<span className="sm">重跑 · 回滚 · 台账 · 日志包</span></summary>
                <p className="hint fold-lead">
                  看数据源：<a href={`/app/?view=ledger&period=${encodeURIComponent(archiveOne)}`}>主台账（只读）→</a>
                </p>
                <Tools
                  period={archiveOne}
                  jobId={runForSelected?.jobId ?? null}
                  approvalStatus={approvalStatus}
                  actionsLocked={jobActionsLocked}
                  actionLockReason={actionLockReason}
                  onActionStart={beginToolAction}
                  onActionEnd={endToolAction}
                  onUploaded={(jobId, period) => { pickPeriod(period); attach(jobId, period) }}
                  refreshToken={artifactRefreshByPeriod[archiveOne] ?? 0}
                />
              </details>
            )}
          </>
          ) : (
            /* 总账：一期一组，点期次进那一期详情（`?view=archive&one=<期次>`）。
               切期次也一并带上，右页与左栏的期次不打架。 */
            <ArchiveLedger
              onOpen={(p) => {
                location.href = `/app/?view=archive&one=${encodeURIComponent(p)}&period=${encodeURIComponent(p)}`
              }}
            />
          )
        ) : view === 'heal' ? (
          <HealSandbox />
        ) : view === 'migrate' ? (
          <MigrateSandbox />
        ) : view === 'acquire' ? (
          <Acquire period={selected} issue={issueLabel} detail={detail} onOpenPeriod={pickPeriod} />
        ) : view === 'forecast' ? (
          <Suspense fallback={screenFallback}>
            <Forecast
              period={selected}
              issue={issueLabel}
              detail={detail}
              meta={forecastMeta}
              metaError={forecastMetaError}
              choice={selectedForecastChoice}
              choiceDirty={selectedForecastChoiceDirty}
              onChoiceChange={changeForecastChoice}
              onSubjectsChange={changeReportSubjects}
              onSaveChoice={saveSelectedForecastChoice}
              onReloadChoice={reloadForecastChoice}
              onRegenerate={regenerateReport}
              regenBusy={runForSelected?.status === 'running'
                || runForSelected?.status === 'queued'}
              regenNote={runForSelected?.last ?? ''}
              canEdit={canSwitchModel}
              canRegenerate={canSwitchModel && !jobActionsLocked && healthy === true}
            />
          </Suspense>
        ) : view === 'trace' ? (
          <Trace period={selected} />
        ) : view === 'reading' ? (
          <Reading period={selected} />
        ) : view === 'charts' ? (
          <Suspense fallback={screenFallback}><Charts period={selected} /></Suspense>
        ) : view === 'red' ? (
          <RedList period={selected} canDownload={canDownloadRedList} />
        ) : view === 'analysis' ? (
          /* 分析台（2026-11-02 静态稿）：同期的两种看法——上面看分布、下面查数。
             数据全走后端产物（water / charts-data），前端不换算、不聚合。
             2026-11-04 票 1：学科报告区并入（原学科分析页，me 供其权限分流提示口径）。 */
          <AnalysisPage period={selected} periods={periods} onPick={pickPeriod} me={me} />
        ) : view === 'aiqa' ? (
          /* 39 分册 B：旧「AI 问数」页退役，深链落问文衡新页 */
          <LegacyRedirect to="/app/dialog/" label="问文衡" />
        ) : view === 'ledger' ? (
          <Ledger />
        ) : view === 'review' ? (
          <Suspense fallback={screenFallback}>
            <Review
              period={selected}
              issue={issueLabel}
              detail={detail}
              me={me}
              periods={periods}
              onChanged={() => { void refreshPeriods().catch(() => { /* 刷新失败不影响操作结果 */ }) }}
            />
          </Suspense>
        ) : view === 'report' ? (
          <Report periods={periods} current={selected} guest={noAdminBits}
            canSeeAdminBits={canSeeAdminBits}
            refreshToken={selected ? artifactRefreshByPeriod[selected] ?? 0 : 0} />
        ) : (
          <>
                      {/* 2026-10-24 rick 工作台减负：工具折块迁往运行档案页（archive 分支），
                          此处不再传工具相关 props；beginToolAction/endToolAction/attach 仍由 App 持有。 */}
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
                        detail={detail}
                        issue={issueLabel}
                        forecastAppliedStale={selectedForecastStale}
                        forecastAppliedDiffs={selectedForecastStaleDiffs}
                        autoConfirmRerun={autoConfirmRerun}
                      />
          </>
        )}

        {busy && <p className="hint mt-14">正在提交生成请求……</p>}
      </main>

      {/* 设置中心（useSettingsCenter 接线）：挂在根容器末尾——inert 圈禁
          依赖弹层是最后一个元素，问文衡同款。 */}
      {settings.node}
    </div>
  )
}
