/* 学科报告（2026-11-04 票 1：学科分析并入分析台）——分析台的一个区＝灵活报告的卡片式入口。
   区纸面：区头（「学科报告」章题 / 写作位开启时的时长预告 / 「打开最近一份」条件链）
   ＋ 22 张学科卡网格（名单来自后端 getFlexible().disciplines，en/cn；空则整区空态）。
   点卡＝唯一动作：流式生成单学科分析报告（runFlexibleStream，NDJSON plan/section/done），
   同区同时只允许一个任务（busy 锁，其余卡禁用）；done 新窗开
   /p/<期次>/flexible/single_trend/report.html，卡面标「最近生成」（本地 state，不入库）；
   error 卡面一句。权限：生成口后端 admin-only——非 admin 点未生成的卡提示
   「生成请找管理员」（hint，不禁用整区）；已生成报告的打开人人可用。

   票 2（流式健壮化）：控制器自带看门狗——90s 没有任何事件（含后端 10s 一条的 ping
   心跳）就 abort 本次 fetch；流终止而未收到 done/error/stopped 同样视为连接中断。
   中断的卡面显式报「连接中断——报告可能已在后台完成，点『打开最近一份』查看」并解除
   busy（后台生成不随连接死，产物可能照常落盘）；error/中断后重取一次 getFlexible
   刷新最近稿。ping 不是进度：不渲染，只重置计时。

   🔴 本区没有任何数字，只有学科名单与流事件文案——运行期大模型不进数据路径。
   测试无 jsdom（与全站同口径，照 ModelPanel 的缝）：展示件 DisciplineView、
   权限分流 cardAction、生成控制器 generateDisciplineReport 都导出，
   DisciplineSection.test.tsx 直接调（控制器就是卡片 onClick 走的那份代码）。 */

import { useEffect, useRef, useState } from 'react'
import {
  getFlexible, runFlexibleStream,
  type FlexStreamEvent, type FlexibleData, type FlexibleDiscipline,
} from '../api-flexible'
import type { Me } from '../api'
import { errorNote } from '../lib/status'
import { Icon } from '../icons'
import './discipline.css'

/** 单学科报告的公开读路由（票面 URL；报告与后端同源，前端只开窗不加工）。 */
export function reportUrl(period: string): string {
  return `/p/${encodeURIComponent(period)}/flexible/single_trend/report.html`
}

/** 最近一份 single_trend 报告是哪个学科的（meta.disc，en；没有已生成报告回 null）。
    「该学科无已生成报告」的判定口径：flex_meta.json 只留最近一次的学科，
    前端只认这份——不猜历史。 */
export function latestDiscOf(data: FlexibleData | null): string | null {
  const r = data?.reports.find((x) => x.intent === 'single_trend')
  const d = (r?.meta as { disc?: unknown } | undefined)?.disc
  return typeof d === 'string' && d ? d : null
}

export type CardAction = { kind: 'generate' } | { kind: 'open' } | { kind: 'hint' }

/** 卡片点击的分流（权限口径的唯一来源）：admin → 生成；
    最近一份报告正是这个学科 → 打开（spec 原话「已生成报告的打开人人可用」，
    打开不设角色门；页面本有登录门）；否则 → 提示找管理员。 */
export function cardAction(me: Me | null, disc: FlexibleDiscipline,
                           latestDisc: string | null): CardAction {
  if (me?.role === 'admin') return { kind: 'generate' }
  if (latestDisc && latestDisc === disc.en) return { kind: 'open' }
  return { kind: 'hint' }
}

/** 卡面进度句（spec：「规划中…」→「第 N 节…」→收尾）。 */
export const STAGE_PLANNING = '规划中…'
export const STAGE_TAIL = '收尾…'
export const stageSection = (n: number) => `第 ${n} 节…`

/** 看门狗时限：90s 没有任何事件（含 ping）＝链路断了（票 2）。
    写作位逐段润色一节可长到分钟级，但后端每 10s 必有一条 ping——
    90s 全静默只可能是连接断了，不是「写得慢」。 */
export const WATCHDOG_MS = 90_000

/** 连接中断的卡面提示（票 2 spec 原话）：报告可能已在后台完成，让「打开最近一份」接手。 */
export const INTERRUPTED_NOTE = '连接中断——报告可能已在后台完成，点『打开最近一份』查看'

/** 点卡走的生成控制器（与 onClick 同一份代码）：进度上卡面，done 开新窗并回传 onDone
    （父层标「最近生成」），error 事件或请求失败回传 onError 一句（errorNote 口径），
    连接中断回传 onInterrupted（票 2：看门狗超时 abort / 流终止无终态事件）。 */
export async function generateDisciplineReport(
  period: string,
  disc: FlexibleDiscipline,
  h: { onStage: (label: string) => void; onDone: () => void
       onError: (message: string) => void; onInterrupted: () => void },
): Promise<void> {
  h.onStage(STAGE_PLANNING)
  let n = 0
  let doneSeen = false
  let failed = false
  let interrupted = false
  const ctrl = new AbortController()
  /* 看门狗：收到任何事件（含 ping）都重置计时；90s 全静默 → abort 本次 fetch。 */
  let watchdog: ReturnType<typeof setTimeout> | null = null
  const arm = () => {
    if (watchdog !== null) clearTimeout(watchdog)
    watchdog = setTimeout(() => { interrupted = true; ctrl.abort() }, WATCHDOG_MS)
  }
  arm()
  try {
    await runFlexibleStream(period, { intent: 'single_trend', disc: disc.en },
      (ev: FlexStreamEvent) => {
        arm()                                       // 任何事件都算「链路活着」
        if (ev.event === 'ping') return             // 心跳只喂看门狗，不是进度
        if (ev.event === 'section') { n += 1; h.onStage(stageSection(n)); return }
        if (ev.event === 'done') {
          doneSeen = true
          h.onStage(STAGE_TAIL)
          window.open(reportUrl(period), '_blank', 'noopener')
          return
        }
        if (ev.event === 'stopped') { failed = true; h.onError('这次生成被停了——可回卡面重新点。'); return }
        if (ev.event === 'error') { failed = true; h.onError(ev.message); return }
      }, { signal: ctrl.signal })
    if (doneSeen) h.onDone()
    else if (!failed) h.onInterrupted()             // 流终止但没等到终态事件＝连接中断
  } catch (e) {
    if (interrupted) h.onInterrupted()              // 看门狗掐断的那次 abort
    else h.onError(errorNote(e, '生成学科报告'))
  } finally {
    if (watchdog !== null) clearTimeout(watchdog)
  }
}

/** 卡面一句话（生成失败 / 连接中断 / 权限提示），标在点过的那张卡上。 */
export type CardNote = { en: string; kind: 'error' | 'hint' | 'warn'; text: string }

/** 展示件（测试从这里进：无 effect、无请求）。loading＝名单还没读到（不画空态，
    免得一进页就闪「没有学科」）；empty 名单才给空态句。 */
export function DisciplineView(props: {
  period: string | null
  loading: boolean
  loadErr: string
  hasReport: boolean
  /** 写作位开启（getFlexible().write.available）＝出稿含逐段润色，区头给时长预告（票 2） */
  writeAvailable: boolean
  disciplines: FlexibleDiscipline[]
  busy: string | null
  stage: string
  note: CardNote | null
  recent: string | null
  onCard: (d: FlexibleDiscipline) => void
}) {
  const { period, loading, loadErr, hasReport, writeAvailable, disciplines,
          busy, stage, note, recent, onCard } = props
  return (
    <section aria-labelledby="dp-sec-h">
      <header className="dp-sec">
        <h2 className="an-sec" id="dp-sec-h">学科报告</h2>
        {writeAvailable && <p className="dp-note">写作位开启：出稿含逐段润色，需数分钟</p>}
        {hasReport && period && (
          <a className="dp-open" href={reportUrl(period)} target="_blank" rel="noopener">
            打开最近一份 ↗
          </a>
        )}
      </header>

      {loading ? null : loadErr ? (
        <p className="dp-empty" role="alert">{loadErr}</p>
      ) : disciplines.length === 0 ? (
        <p className="dp-empty">本期还没有可分析的学科。</p>
      ) : (
        <ol className="dp-grid">
          {disciplines.map((d) => {
            const state = busy === d.en
              ? { cls: 'run', text: stage }
              : note?.en === d.en
                ? { cls: note.kind, text: note.text }
                : recent === d.en
                  ? { cls: 'ok', text: '最近生成' }
                  : null
            return (
              <li key={d.en}>
                <button type="button" className="dp-card" disabled={!!busy}
                        data-now={busy === d.en || undefined}
                        onClick={() => onCard(d)}>
                  <span className="dp-cn">{d.cn}</span>
                  <span className="dp-en">{d.en}</span>
                  {state && <span className={`dp-state ${state.cls}`}>{state.text}</span>}
                  <i className="dp-arrow" aria-hidden="true"><Icon name="arrow" size={14} /></i>
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

/** 分析台里的「学科报告」区（票 1：原学科分析页整体迁入，me/period 传参不变）。 */
export function DisciplineSection({ period, me }: { period: string; me: Me | null }) {
  const [data, setData] = useState<FlexibleData | null>(null)
  const [loadErr, setLoadErr] = useState('')
  /** busy＝正在生成的学科 en（单任务锁；null＝空闲） */
  const [busy, setBusy] = useState<string | null>(null)
  const [stage, setStage] = useState('')
  const [note, setNote] = useState<CardNote | null>(null)
  /** 最近生成的学科 en（本地 state，不入库——spec 原话） */
  const [recent, setRecent] = useState<string | null>(null)
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false }, [])

  useEffect(() => {
    setLoadErr('')
    setNote(null)
    setBusy(null)
    setStage('')
    setRecent(null)
    let alive = true
    setData(null)
    void getFlexible(period).then((j) => {
      if (alive) setData(j)
    }).catch((e) => {
      if (alive) setLoadErr(errorNote(e, '学科名单'))
    })
    return () => { alive = false }
  }, [period])

  const latestDisc = latestDiscOf(data)
  /* 区头链的开关照 spec 原话：reports 含 single_trend 即亮（与 meta.disc 的有无无关） */
  const hasReport = !!data?.reports.some((x) => x.intent === 'single_trend')
  const writeAvailable = data?.write?.available === true

  function onCard(d: FlexibleDiscipline) {
    if (busy) return
    const act = cardAction(me, d, latestDisc)
    if (act.kind === 'hint') {
      setNote({ en: d.en, kind: 'hint', text: '生成请找管理员' })
      return
    }
    if (act.kind === 'open') {
      window.open(reportUrl(period), '_blank', 'noopener')
      return
    }
    setNote(null)
    setBusy(d.en)
    /* error / 中断 / 完成后各重取一次（票 2：error/中断后自动轮询一次刷新最近稿状态） */
    const refetch = () => {
      void getFlexible(period).then((j) => { if (aliveRef.current) setData(j) })
        .catch(() => { /* 重取失败不打扰：卡面的话已经说清了 */ })
    }
    void generateDisciplineReport(period, d, {
      onStage: setStage,
      onDone: () => {
        setRecent(d.en)
        setBusy(null)
        setStage('')
        refetch()
      },
      onError: (m) => {
        setNote({ en: d.en, kind: 'error', text: m })
        setBusy(null)
        setStage('')
        refetch()
      },
      onInterrupted: () => {
        setNote({ en: d.en, kind: 'warn', text: INTERRUPTED_NOTE })
        setBusy(null)
        setStage('')
        refetch()
      },
    })
  }

  const loading = !data && !loadErr
  return (
    <DisciplineView
      period={period}
      loading={loading}
      loadErr={loadErr}
      hasReport={hasReport}
      writeAvailable={writeAvailable}
      disciplines={data?.disciplines ?? []}
      busy={busy}
      stage={stage}
      note={note}
      recent={recent}
      onCard={onCard}
    />
  )
}
